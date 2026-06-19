"""SCRATCH: BREAK/BOUNCE definition sensitivity sweep for the DEX backtest.

Challenge: dex_backtest.py calls a "break" when fwd close clears the level by
>0.5*ATR and a "bounce" when it rejects toward spot, DROPPING ambiguous rows
(7124 near-level -> 4838 resolved). Does that definition manufacture or hide H2
(DEX break AUC ~0.526) and H3 (incremental over gamma +0.0147)?

We copy load_features() from the engine (identical feature build), then re-run
H2 + H3 under alternates:
  BREAK_ATR  in {0.25, 0.5(orig), 0.75, 1.0}
  NEAR_LEVEL in {0.02, 0.03(orig), 0.05}
  + a NO-DROP variant per (BREAK_ATR,NEAR_LEVEL): keep ALL near-level rows,
    label by SIGN of forward move THROUGH the level (no ambiguous NaN).

Smaller placebo/CV bootstrap (n=200) for speed. Stability question:
  - is trivial H2 (~0.526, barely above 0.5) stable?
  - is sub-floor H3 (+0.0147 < +0.02 bar) stable, or does ANY def lift >= +0.02?

Run: python scripts/gex_bt/dex_bb_sensitivity.py
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
RNG = np.random.default_rng(20260618)

PLACEBO_N = 200
ATR_GRID = [0.25, 0.5, 0.75, 1.0]
NEAR_GRID = [0.02, 0.03, 0.05]


def load_features() -> pd.DataFrame:
    """IDENTICAL to dex_backtest.load_features (copied verbatim)."""
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

    T = np.maximum((pd.to_datetime(df["expiration"]) - pd.to_datetime(df["date"])).dt.days, 1) / 365.0
    S, K, sig = df["spot"].values, df["strike"].values, df["iv"].values
    sqrtT = np.sqrt(T.values)
    d1 = (np.log(S / K) + (R - Q + 0.5 * sig ** 2) * T.values) / (sig * sqrtT)
    gamma = np.exp(-Q * T.values) * stats.norm.pdf(d1) / (S * sig * sqrtT)
    csign = np.where(df["right"].values == "C", 1.0, -1.0)
    df["gex"] = gamma * df["oi"].values * 100 * S * S * 0.01 * csign
    df["dex"] = df["delta"].values * df["oi"].values * 100

    g = df.groupby(["root", "date"])
    agg = g.agg(DEX=("dex", "sum"), GEX=("gex", "sum"),
                spot=("spot", "median")).reset_index()

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


def build_panel_base(agg: pd.DataFrame) -> pd.DataFrame:
    """Everything EXCEPT the break/bounce labels (those depend on the sweep params).
    Copied from dex_backtest.build_panel up through the level/dist computation."""
    agg = agg.sort_values(["root", "date"]).reset_index(drop=True)
    out = []
    for root, d in agg.groupby("root"):
        d = d.sort_values("date").copy()
        sp = d["spot"].values
        ret = np.concatenate([[np.nan], sp[1:] / sp[:-1] - 1])
        d["daily_ret"] = ret
        vol = np.nanstd(ret) or 1e-9
        d["fwd1"] = np.concatenate([sp[1:] / sp[:-1] - 1, [np.nan]])
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

    cw, pw, spot = p["call_wall"], p["put_wall"], p["spot"]
    dist_cw = (cw - spot).abs() / spot
    dist_pw = (spot - pw).abs() / spot
    use_cw = dist_cw <= dist_pw
    L = np.where(use_cw, cw, pw)
    dist = np.where(use_cw, (cw - spot) / spot, (pw - spot) / spot)
    p["level"] = L
    p["dist_signed"] = dist
    p["fwd_spot"] = p["spot"] * (1 + p["fwd1"])
    p["atr_safe"] = p["atr"].replace(0, np.nan)
    return p


def label_bb(p: pd.DataFrame, break_atr: float, near_level: float, no_drop: bool) -> pd.DataFrame:
    """Apply a specific break/bounce labeling. Returns near-level rows with bb in {0,1}/NaN.

    Original mode (no_drop=False): break = fwd clears level by break_atr*ATR;
      bounce = fwd rejects toward spot; ambiguous (cleared-but-not-by-ATR, or
      went-through-but-not-rejected) -> NaN (DROPPED).

    no_drop=True: every near-level row labeled by SIGN of forward move THROUGH the
      level. up_level (level above spot): bb=1 if fwd_spot crosses ABOVE level
      (break up), else 0. down_level: bb=1 if fwd_spot crosses BELOW level. No NaN.
    """
    L = p["level"].values
    spot = p["spot"].values
    fwd_spot = p["fwd_spot"].values
    atr = p["atr_safe"].values
    dist = p["dist_signed"].values
    up_level = dist > 0

    near = (np.abs(dist) <= near_level) & np.isfinite(L)
    p = p.copy()
    p["near_level"] = near

    if no_drop:
        # label by whether fwd close ended on the FAR side of the level (a "break
        # through"). up_level: break if fwd_spot > L. down_level: break if fwd_spot < L.
        broke = np.where(up_level, fwd_spot > L, fwd_spot < L)
        bb = np.where(broke, 1.0, 0.0)
        # only NaN where fwd_spot itself is undefined
        bb = np.where(np.isfinite(fwd_spot), bb, np.nan)
    else:
        broke = np.where(up_level, fwd_spot > (L + break_atr * atr),
                         fwd_spot < (L - break_atr * atr))
        bounced = np.where(up_level, fwd_spot < spot, fwd_spot > spot)
        bb = np.where(broke, 1.0, np.where(bounced, 0.0, np.nan))
    p["bb"] = bb
    return p


def _placebo_auc(score, y, dates, n=PLACEBO_N):
    m = np.isfinite(score) & np.isfinite(y)
    score, y, dates = score[m], y[m], dates[m]
    if len(np.unique(y)) < 2 or len(y) < 50:
        return np.nan, np.nan, np.nan, 0
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
    pv = (np.sum(np.abs(null - 0.5) >= abs(obs - 0.5)) + 1) / (len(null) + 1) if len(null) else np.nan
    return float(obs), float(p95), float(pv), int(m.sum())


def _cv_auc(X, y, dates):
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


def eval_def(p_base: pd.DataFrame, break_atr, near_level, no_drop) -> dict:
    p = label_bb(p_base, break_atr, near_level, no_drop)
    nl = p[p["near_level"]].copy()
    y = nl["bb"].values
    n_near = int(p["near_level"].sum())
    n_resolved = int(np.isfinite(y).sum())
    pos_rate = float(np.nanmean(y)) if n_resolved else np.nan

    obs, p95, pv, _ = _placebo_auc(nl["DEX_z"].values, y, nl["date"].values)
    base_cols = nl[["gamma_regime", "prior5"]].values
    full_cols = nl[["gamma_regime", "prior5", "DEX_z"]].values
    auc_base = _cv_auc(base_cols, y, nl["date"].values)
    auc_full = _cv_auc(full_cols, y, nl["date"].values)
    lift = (auc_full - auc_base) if (auc_full == auc_full and auc_base == auc_base) else np.nan

    return {
        "break_atr": break_atr, "near_level": near_level, "no_drop": no_drop,
        "n_near": n_near, "n_resolved": n_resolved,
        "break_rate": round(pos_rate, 4) if pos_rate == pos_rate else None,
        "H2_auc": round(obs, 4) if obs == obs else None,
        "H2_placebo975": round(p95, 4) if p95 == p95 else None,
        "H2_p": round(pv, 4) if pv == pv else None,
        "H3_auc_base": round(auc_base, 4) if auc_base == auc_base else None,
        "H3_auc_full": round(auc_full, 4) if auc_full == auc_full else None,
        "H3_lift": round(lift, 4) if lift == lift else None,
        "H3_ge_0.02": bool(lift >= 0.02) if lift == lift else None,
    }


def run():
    p_base = build_panel_base(load_features())
    results = []

    # 1) original-style (drop ambiguous): full ATR x NEAR grid
    for na in NEAR_GRID:
        for at in ATR_GRID:
            r = eval_def(p_base, at, na, no_drop=False)
            results.append(r)
            print(f"[DROP] ATR={at} NEAR={na}: n_res={r['n_resolved']} "
                  f"H2={r['H2_auc']} (p={r['H2_p']}) H3lift={r['H3_lift']} ge.02={r['H3_ge_0.02']}",
                  flush=True)

    # 2) no-drop (sign-of-move-through-level): break_atr irrelevant, sweep NEAR only
    for na in NEAR_GRID:
        r = eval_def(p_base, 0.0, na, no_drop=True)
        results.append(r)
        print(f"[NODROP] NEAR={na}: n_res={r['n_resolved']} "
              f"H2={r['H2_auc']} (p={r['H2_p']}) H3lift={r['H3_lift']} ge.02={r['H3_ge_0.02']}",
              flush=True)

    out = {
        "placebo_n": PLACEBO_N,
        "baseline_orig": {"H2_auc": 0.5258, "H3_lift": 0.0147, "n_resolved": 4838},
        "results": results,
        "any_H3_ge_0.02": bool(any(r["H3_ge_0.02"] for r in results if r["H3_ge_0.02"] is not None)),
        "H2_range": [min(r["H2_auc"] for r in results if r["H2_auc"]),
                     max(r["H2_auc"] for r in results if r["H2_auc"])],
        "H3_range": [min(r["H3_lift"] for r in results if r["H3_lift"] is not None),
                     max(r["H3_lift"] for r in results if r["H3_lift"] is not None)],
    }
    Path("data/dex_bb_sensitivity.json").write_text(json.dumps(out, indent=2))
    print("\n=== SUMMARY ===")
    print(json.dumps({k: v for k, v in out.items() if k != "results"}, indent=2))
    print("wrote data/dex_bb_sensitivity.json")
    return out


if __name__ == "__main__":
    run()
