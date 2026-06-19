"""DEX (Delta Exposure) predictive-power test — deterministic engine (pre-reg).

Pre-registration: docs/research/DEX_PREREG.md. Tests the Discord claim that "DEX
near GEX levels tells you break vs bounce, and how fast/much." The decisive test
is H3: does DEX add predictive power BEYOND the gamma regime (or is it just a
proxy for gamma, which we've already shown detects-but-doesn't-predict)?

Single-name daily, chains.db (116 roots, ~12.4K name-days, Jan-Jun 2026).
DEX from delta*oi; GEX from vectorized BSM gamma (iv). All predictors use day-t
close data only; outcomes strictly t+1 / t+3. Clustered/bootstrap inference.

Out -> data/dex_bt_results.json   Run: python scripts/gex_bt/dex_backtest.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

DB = "data/chains_ytd_2026.db"
R, Q = 0.045, 0.0
MONEY_BAND = 0.15      # strikes within +-15% of spot
MAX_DTE = 45
NEAR_LEVEL = 0.03      # spot within +-3% of a GEX wall = "near"
BREAK_ATR = 0.5        # close beyond level by >0.5*ATR = break
RNG = np.random.default_rng(20260618)


def load_features() -> pd.DataFrame:
    """One row per (root, date): DEX, GEX, gamma_regime, spot, nearest call/put
    wall. Computed from near-money near-term strikes."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    q = f"""
        SELECT date, root, expiration, strike, right, delta, iv, spot, oi
        FROM option_eod
        WHERE oi > 0 AND delta IS NOT NULL AND iv > 0 AND spot > 0
          AND ABS(strike/spot - 1.0) <= {MONEY_BAND}
          AND julianday(expiration) - julianday(date) BETWEEN 0 AND {MAX_DTE}
    """
    df = pd.read_sql_query(q, con)
    con.close()
    print(f"loaded {len(df):,} near-money near-term strike-rows", flush=True)

    # vectorized BSM gamma
    T = np.maximum((pd.to_datetime(df["expiration"]) - pd.to_datetime(df["date"])).dt.days, 1) / 365.0
    S, K, sig = df["spot"].values, df["strike"].values, df["iv"].values
    sqrtT = np.sqrt(T.values)
    d1 = (np.log(S / K) + (R - Q + 0.5 * sig ** 2) * T.values) / (sig * sqrtT)
    gamma = np.exp(-Q * T.values) * stats.norm.pdf(d1) / (S * sig * sqrtT)
    csign = np.where(df["right"].values == "C", 1.0, -1.0)
    df["gex"] = gamma * df["oi"].values * 100 * S * S * 0.01 * csign     # +call/-put dealer conv
    df["dex"] = df["delta"].values * df["oi"].values * 100               # raw option delta exposure

    # per name-day aggregates
    g = df.groupby(["root", "date"])
    agg = g.agg(DEX=("dex", "sum"), GEX=("gex", "sum"),
                spot=("spot", "median")).reset_index()

    # per-strike signed GEX -> nearest call wall (max +GEX above) / put wall (below)
    strike_gex = df.groupby(["root", "date", "strike"])["gex"].sum().reset_index()
    strike_gex = strike_gex.merge(agg[["root", "date", "spot"]], on=["root", "date"])
    above = strike_gex[(strike_gex.gex > 0) & (strike_gex.strike > strike_gex.spot)]
    below = strike_gex[(strike_gex.gex > 0) & (strike_gex.strike < strike_gex.spot)]
    cw = above.loc[above.groupby(["root", "date"])["gex"].idxmax(), ["root", "date", "strike"]] \
        .rename(columns={"strike": "call_wall"})
    pw = below.loc[below.groupby(["root", "date"])["gex"].idxmax(), ["root", "date", "strike"]] \
        .rename(columns={"strike": "put_wall"})
    agg = agg.merge(cw, on=["root", "date"], how="left").merge(pw, on=["root", "date"], how="left")
    print(f"built {len(agg):,} name-days", flush=True)
    return agg


def build_panel(agg: pd.DataFrame) -> pd.DataFrame:
    """Add per-name z-scores, forward returns, momentum, ATR, level break/bounce."""
    agg = agg.sort_values(["root", "date"]).reset_index(drop=True)
    out = []
    for root, d in agg.groupby("root"):
        d = d.sort_values("date").copy()
        sp = d["spot"].values
        ret = np.concatenate([[np.nan], sp[1:] / sp[:-1] - 1])
        d["daily_ret"] = ret
        vol = np.nanstd(ret) or 1e-9
        d["fwd1"] = np.concatenate([sp[1:] / sp[:-1] - 1, [np.nan]])          # t->t+1
        d["fwd3"] = d["spot"].shift(-3) / d["spot"] - 1
        d["fwd1_std"] = d["fwd1"] / vol
        d["fwd3_std"] = d["fwd3"] / (vol * np.sqrt(3))
        d["prior5"] = d["spot"] / d["spot"].shift(5) - 1
        d["atr"] = pd.Series(ret).rolling(14, min_periods=5).std().values * d["spot"].values
        for col in ("DEX", "GEX"):
            mu, sd = d[col].mean(), d[col].std() or 1e-9
            d[f"{col}_z"] = (d[col] - mu) / sd
        d["gamma_regime"] = np.sign(d["GEX"])
        out.append(d)
    p = pd.concat(out, ignore_index=True)

    # level break/bounce on near-level rows
    cw, pw, spot = p["call_wall"], p["put_wall"], p["spot"]
    dist_cw = (cw - spot).abs() / spot
    dist_pw = (spot - pw).abs() / spot
    use_cw = dist_cw <= dist_pw
    L = np.where(use_cw, cw, pw)
    dist = np.where(use_cw, (cw - spot) / spot, (pw - spot) / spot)  # signed: + above / - below
    p["level"] = L
    p["near_level"] = (np.abs(dist) <= NEAR_LEVEL) & np.isfinite(L)
    fwd_spot = p["spot"] * (1 + p["fwd1"])
    atr = p["atr"].replace(0, np.nan)
    up_level = dist > 0
    broke = np.where(up_level, fwd_spot > (L + BREAK_ATR * atr),
                     fwd_spot < (L - BREAK_ATR * atr))
    bounced = np.where(up_level, fwd_spot < spot, fwd_spot > spot)
    p["broke"] = broke
    p["bounced"] = bounced
    # binary outcome: 1 break, 0 bounce, NaN ambiguous
    p["bb"] = np.where(broke, 1.0, np.where(bounced, 0.0, np.nan))
    return p


def _boot_corr_p(x, y, dates, n=2000):
    """Block-bootstrap (resample whole dates) two-sided p that corr==0."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dates = x[m], y[m], dates[m]
    if len(x) < 50:
        return np.nan, np.nan
    obs = np.corrcoef(x, y)[0, 1]
    uniq = pd.unique(dates)
    idx_by_date = {dt: np.where(dates == dt)[0] for dt in uniq}
    cnt = 0
    for _ in range(n):
        pick = RNG.choice(uniq, size=len(uniq), replace=True)
        ii = np.concatenate([idx_by_date[dt] for dt in pick])
        c = np.corrcoef(x[ii], y[ii])[0, 1]
        if abs(c) >= abs(obs):
            cnt += 1
    return float(obs), (cnt + 1) / (n + 1)


def _placebo_auc(score, y, dates, n=500):
    """Permute score WITHIN each date (break name-link, keep cross-section)."""
    m = np.isfinite(score) & np.isfinite(y)
    score, y, dates = score[m], y[m], dates[m]
    if len(np.unique(y)) < 2 or len(y) < 50:
        return np.nan, np.nan, np.nan
    obs = roc_auc_score(y, score)
    s = pd.Series(score); dd = pd.Series(dates)
    null = []
    for _ in range(n):
        perm = s.groupby(dd).transform(lambda v: v.sample(frac=1, random_state=RNG.integers(1e9)).values)
        try:
            null.append(roc_auc_score(y, perm.values))
        except Exception:
            pass
    null = np.array(null)
    p95 = np.nanpercentile(null, 97.5) if len(null) else np.nan
    p = (np.sum(np.abs(null - 0.5) >= abs(obs - 0.5)) + 1) / (len(null) + 1) if len(null) else np.nan
    return float(obs), float(p95), float(p)


def _cv_auc(X, y, dates):
    """Date-blocked 5-fold CV AUC for a logistic model."""
    m = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    X, y, dates = X[m], y[m], dates[m]
    if len(np.unique(y)) < 2 or len(y) < 200:
        return np.nan
    uniq = pd.unique(dates)
    folds = np.array_split(RNG.permutation(uniq), 5)
    aucs = []
    for f in folds:
        te = np.isin(dates, f); tr = ~te
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        lr = LogisticRegression(max_iter=1000)
        lr.fit(X[tr], y[tr])
        aucs.append(roc_auc_score(y[te], lr.predict_proba(X[te])[:, 1]))
    return float(np.mean(aucs)) if aucs else np.nan


def run() -> dict:
    p = build_panel(load_features())
    dates = p["date"].values
    res = {"n_name_days": int(len(p)), "n_near_level": int(p["near_level"].sum())}

    # H1: DEX_z -> forward direction (corr, block-bootstrap p) + placebo vs gamma
    for w in ("fwd1_std", "fwd3_std"):
        c, pv = _boot_corr_p(p["DEX_z"].values, p[w].values, dates)
        cg, pg = _boot_corr_p(p["GEX_z"].values, p[w].values, dates)
        res[f"H1_DEX_{w}"] = {"corr": round(c, 4), "boot_p": round(pv, 4)}
        res[f"H1_GEX_{w}"] = {"corr": round(cg, 4), "boot_p": round(pg, 4)}

    # H2: at levels, DEX_z predicts break — AUC vs within-date placebo
    nl = p[p["near_level"]].copy()
    y = nl["bb"].values
    obs, p95, pp = _placebo_auc(nl["DEX_z"].values, y, nl["date"].values)
    res["H2_DEX_break_auc"] = {"auc": round(obs, 4) if obs == obs else None,
                               "placebo_97.5pct": round(p95, 4) if p95 == p95 else None,
                               "p": round(pp, 4) if pp == pp else None,
                               "n": int(np.isfinite(y).sum())}
    # H3: incremental over gamma — CV AUC gamma+momentum vs +DEX
    base_cols = nl[["gamma_regime", "prior5"]].values
    full_cols = nl[["gamma_regime", "prior5", "DEX_z"]].values
    auc_base = _cv_auc(base_cols, y, nl["date"].values)
    auc_full = _cv_auc(full_cols, y, nl["date"].values)
    res["H3_incremental"] = {
        "auc_gamma_momentum": round(auc_base, 4) if auc_base == auc_base else None,
        "auc_plus_DEX": round(auc_full, 4) if auc_full == auc_full else None,
        "lift": round((auc_full - auc_base), 4) if (auc_full == auc_full and auc_base == auc_base) else None,
    }
    # H4: |DEX_z| -> forward move size
    move = (p["fwd1"].abs() / p["atr"] * p["spot"]).values
    c4, p4 = _boot_corr_p(p["DEX_z"].abs().values, move, dates)
    res["H4_DEX_mag_vs_move"] = {"corr": round(c4, 4), "boot_p": round(p4, 4)}

    # Holm-Bonferroni across the family
    fam = {
        "H1_DEX_fwd1": res["H1_DEX_fwd1_std"]["boot_p"],
        "H1_DEX_fwd3": res["H1_DEX_fwd3_std"]["boot_p"],
        "H2_break": res["H2_DEX_break_auc"]["p"],
        "H4_magnitude": res["H4_DEX_mag_vs_move"]["boot_p"],
    }
    fam = {k: v for k, v in fam.items() if v is not None and v == v}
    ranked = sorted(fam.items(), key=lambda kv: kv[1])
    m = len(ranked)
    holm = {}
    for i, (k, pv) in enumerate(ranked):
        thr = 0.05 / (m - i)
        holm[k] = {"p": round(pv, 4), "holm_thr": round(thr, 4), "pass": bool(pv < thr)}
    res["holm"] = holm
    return res


if __name__ == "__main__":
    out = run()
    print("\n=== DEX TEST RESULTS (descriptive — verdict in the review) ===")
    print(json.dumps(out, indent=2))
    Path("data/dex_bt_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote data/dex_bt_results.json")
