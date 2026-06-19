"""DEX subgroup hunt — honest search for WHERE DEX predicts break/bounce.

Guards against data-mining:
  * H2/H3 re-run within named subgroups defined a-priori (not threshold-mined):
      (a) high-|GEX| name-days (top tercile of |GEX| -> strong dealer positioning)
      (b) call-wall tests vs put-wall tests, separately
      (c) short-DTE-heavy chains (top tercile of OI-weighted near-money short-DTE share)
      (d) high-IV vs low-IV names (median split on per-name-day median IV)
  * Every subgroup where DEX "looks predictive" gets its OWN within-subgroup placebo
    (permute DEX within (subgroup, date) — break the name<->outcome link).
  * Multiple-comparison context reported explicitly: with K independent subgroup
    tests at alpha, expect ~K*alpha false positives under the null.

Reuses the exact feature/panel construction from dex_backtest.py so the only new
thing is subgroup partitioning. Outcome = break (1) / bounce (0) on near-level days,
identical definition to the main test.

Out -> data/dex_subgroup_results.json
Run: python scripts/gex_bt/dex_subgroup_hunt.py
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
MONEY_BAND = 0.15
MAX_DTE = 45
NEAR_LEVEL = 0.03
BREAK_ATR = 0.5
SHORT_DTE = 7          # "short-dated" = expiring within 7 days
RNG = np.random.default_rng(20260618)


def load_features() -> pd.DataFrame:
    """One row per (root,date) with the extra subgroup tags."""
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

    dte = (pd.to_datetime(df["expiration"]) - pd.to_datetime(df["date"])).dt.days
    T = np.maximum(dte, 1).values / 365.0
    S, K, sig = df["spot"].values, df["strike"].values, df["iv"].values
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (R - Q + 0.5 * sig ** 2) * T) / (sig * sqrtT)
    gamma = np.exp(-Q * T) * stats.norm.pdf(d1) / (S * sig * sqrtT)
    csign = np.where(df["right"].values == "C", 1.0, -1.0)
    df["gex"] = gamma * df["oi"].values * 100 * S * S * 0.01 * csign
    df["dex"] = df["delta"].values * df["oi"].values * 100
    df["dte"] = dte.values
    df["oi_iv"] = df["oi"].values * df["iv"].values    # for OI-weighted IV
    df["short_oi"] = np.where(dte.values <= SHORT_DTE, df["oi"].values, 0)

    g = df.groupby(["root", "date"])
    agg = g.agg(
        DEX=("dex", "sum"),
        GEX=("gex", "sum"),
        spot=("spot", "median"),
        tot_oi=("oi", "sum"),
        short_oi=("short_oi", "sum"),
        oi_iv=("oi_iv", "sum"),
    ).reset_index()
    agg["iv_w"] = agg["oi_iv"] / agg["tot_oi"].replace(0, np.nan)      # OI-weighted IV
    agg["short_share"] = agg["short_oi"] / agg["tot_oi"].replace(0, np.nan)

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
    agg = agg.sort_values(["root", "date"]).reset_index(drop=True)
    out = []
    for root, d in agg.groupby("root"):
        d = d.sort_values("date").copy()
        sp = d["spot"].values
        ret = np.concatenate([[np.nan], sp[1:] / sp[:-1] - 1])
        d["daily_ret"] = ret
        vol = np.nanstd(ret) or 1e-9
        d["fwd1"] = np.concatenate([sp[1:] / sp[:-1] - 1, [np.nan]])
        d["prior5"] = d["spot"] / d["spot"].shift(5) - 1
        d["atr"] = pd.Series(ret).rolling(14, min_periods=5).std().values * d["spot"].values
        for col in ("DEX", "GEX"):
            mu, sd = d[col].mean(), d[col].std() or 1e-9
            d[f"{col}_z"] = (d[col] - mu) / sd
        d["gamma_regime"] = np.sign(d["GEX"])
        out.append(d)
    p = pd.concat(out, ignore_index=True)

    cw, pw, spot = p["call_wall"], p["put_wall"], p["spot"]
    dist_cw = (cw - spot).abs() / spot
    dist_pw = (spot - pw).abs() / spot
    use_cw = dist_cw <= dist_pw
    L = np.where(use_cw, cw, pw)
    dist = np.where(use_cw, (cw - spot) / spot, (pw - spot) / spot)
    p["level"] = L
    p["wall_type"] = np.where(use_cw, "call", "put")   # which wall is being tested
    p["near_level"] = (np.abs(dist) <= NEAR_LEVEL) & np.isfinite(L)
    fwd_spot = p["spot"] * (1 + p["fwd1"])
    atr = p["atr"].replace(0, np.nan)
    up_level = dist > 0
    broke = np.where(up_level, fwd_spot > (L + BREAK_ATR * atr),
                     fwd_spot < (L - BREAK_ATR * atr))
    bounced = np.where(up_level, fwd_spot < spot, fwd_spot > spot)
    p["bb"] = np.where(broke, 1.0, np.where(bounced, 0.0, np.nan))
    p["absGEX"] = p["GEX"].abs()
    return p


def _placebo_auc(score, y, dates, n=500):
    """Within-(subgroup already filtered)-date permutation placebo on the score."""
    m = np.isfinite(score) & np.isfinite(y)
    score, y, dates = score[m], y[m], dates[m]
    if len(np.unique(y)) < 2 or len(y) < 50:
        return np.nan, np.nan, np.nan, int(len(y))
    obs = roc_auc_score(y, score)
    s = pd.Series(score); dd = pd.Series(dates)
    null = []
    for _ in range(n):
        perm = s.groupby(dd).transform(
            lambda v: v.sample(frac=1, random_state=RNG.integers(1_000_000_000)).values)
        try:
            null.append(roc_auc_score(y, perm.values))
        except Exception:
            pass
    null = np.array(null)
    if not len(null):
        return float(obs), np.nan, np.nan, int(len(y))
    p975 = np.nanpercentile(null, 97.5)
    pval = (np.sum(np.abs(null - 0.5) >= abs(obs - 0.5)) + 1) / (len(null) + 1)
    return float(obs), float(p975), float(pval), int(len(y))


def _cv_auc(X, y, dates):
    m = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    X, y, dates = X[m], y[m], dates[m]
    if len(np.unique(y)) < 2 or len(y) < 200:
        return np.nan
    uniq = pd.unique(dates)
    if len(uniq) < 5:
        return np.nan
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


def eval_subgroup(sub: pd.DataFrame, name: str) -> dict:
    """Run H2 (DEX break AUC + within-subgroup placebo) and H3 (incremental CV lift)."""
    y = sub["bb"].values
    dts = sub["date"].values
    auc, p975, pval, n = _placebo_auc(sub["DEX_z"].values, y, dts)
    base = _cv_auc(sub[["gamma_regime", "prior5"]].values, y, dts)
    full = _cv_auc(sub[["gamma_regime", "prior5", "DEX_z"]].values, y, dts)
    lift = (full - base) if (full == full and base == base) else np.nan
    return {
        "subgroup": name,
        "n": n,
        "base_rate_break": round(float(np.nanmean(y)), 4) if n else None,
        "H2_auc": round(auc, 4) if auc == auc else None,
        "H2_placebo_97.5pct": round(p975, 4) if p975 == p975 else None,
        "H2_placebo_p": round(pval, 4) if pval == pval else None,
        "H3_auc_base": round(base, 4) if base == base else None,
        "H3_auc_plus_DEX": round(full, 4) if full == full else None,
        "H3_lift": round(lift, 4) if lift == lift else None,
    }


def run() -> dict:
    p = build_panel(load_features())
    nl = p[p["near_level"] & np.isfinite(p["bb"])].copy()
    print(f"near-level rows with break/bounce outcome: {len(nl):,}", flush=True)

    # ----- define subgroups (a-priori, not threshold-mined) -----
    # (a) |GEX| terciles -> top tercile = strong dealer positioning
    absgex = nl["absGEX"]
    qa = absgex.quantile([1/3, 2/3]).values
    nl["gex_tercile"] = np.where(absgex >= qa[1], "high",
                          np.where(absgex >= qa[0], "mid", "low"))
    # (c) short-DTE-heavy chains: top tercile of short_share
    ss = nl["short_share"]
    qc = ss.quantile([1/3, 2/3]).values
    nl["dte_tercile"] = np.where(ss >= qc[1], "shortheavy",
                          np.where(ss >= qc[0], "mid", "longheavy"))
    # (d) high vs low IV: median split of OI-weighted IV
    iv_med = nl["iv_w"].median()
    nl["iv_grp"] = np.where(nl["iv_w"] >= iv_med, "highIV", "lowIV")

    subgroups = {
        "ALL_near_level": nl,
        "a_highGEX_tercile": nl[nl["gex_tercile"] == "high"],
        "a_lowGEX_tercile": nl[nl["gex_tercile"] == "low"],
        "b_call_wall_tests": nl[nl["wall_type"] == "call"],
        "b_put_wall_tests": nl[nl["wall_type"] == "put"],
        "c_shortDTE_heavy": nl[nl["dte_tercile"] == "shortheavy"],
        "c_longDTE_heavy": nl[nl["dte_tercile"] == "longheavy"],
        "d_highIV": nl[nl["iv_grp"] == "highIV"],
        "d_lowIV": nl[nl["iv_grp"] == "lowIV"],
    }

    results = []
    for nm, sub in subgroups.items():
        r = eval_subgroup(sub, nm)
        results.append(r)
        print(f"  {nm:22s} n={r['n']:5} "
              f"AUC={r['H2_auc']} plc975={r['H2_placebo_97.5pct']} "
              f"p={r['H2_placebo_p']} H3lift={r['H3_lift']}", flush=True)

    # ----- pick best honest subgroup (exclude ALL) on H2 AUC, must beat its own placebo -----
    cand = [r for r in results if r["subgroup"] != "ALL_near_level"
            and r["H2_auc"] is not None]
    # "predictive" = AUC above its own within-subgroup placebo 97.5pct AND p<0.05
    survivors = [r for r in cand
                 if r["H2_placebo_97.5pct"] is not None
                 and r["H2_auc"] > r["H2_placebo_97.5pct"]
                 and r["H2_placebo_p"] is not None and r["H2_placebo_p"] < 0.05]
    best = max(cand, key=lambda r: r["H2_auc"]) if cand else None

    # subgroup family is 8 tested partitions (the 8 non-ALL); expected false positives
    K = len(cand)
    alpha = 0.05
    expected_fp = round(K * alpha, 2)

    return {
        "n_subgroups_tested": K,
        "expected_false_positives_at_0.05": expected_fp,
        "results": results,
        "survivors_beating_own_placebo": [s["subgroup"] for s in survivors],
        "n_survivors": len(survivors),
        "best_by_auc": best,
    }


if __name__ == "__main__":
    out = run()
    print("\n=== DEX SUBGROUP HUNT (descriptive) ===")
    print(json.dumps(out, indent=2))
    Path("data/dex_subgroup_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote data/dex_subgroup_results.json")
