"""DEX alternate-construction stress test — re-run H1 (direction) and H3
(incremental break/bounce over gamma) under 6 alternate DEX definitions.

Challenges the engine's DEX = sum(delta*oi*100), raw option delta (call +, put -).

Variants:
  raw      : delta*oi*100                       (baseline / engine def)
  dollar   : delta*oi*100*spot                  (a) dollar delta
  short    : -(delta*oi*100)                    (b) dealer-short convention
  no_itm   : delta*oi*100, exclude |delta|>0.85 (c) drop stock-replacement noise
  call_only: call-leg delta*oi*100 only         (d) call-only DEX
  put_only : put-leg  delta*oi*100 only         (d) put-only DEX
  slope    : DEX(t) - DEX(t-1)                   (e) day-over-day CHANGE  <-- key

For each variant we test:
  H1: corr(predictor_z, fwd direction) with block-bootstrap p, AND a placebo
      (within-date permutation) to see if |corr| beats the 97.5pct placebo band.
  H3: date-blocked 5-fold CV AUC lift of (gamma+momentum+predictor) over
      (gamma+momentum). Pass bar: lift >= +0.02.

Note on sign: H1 mean-reversion / dealer-short conventions flip predictor sign;
since we test |corr| against a two-sided placebo and feed raw z into a logistic
(which fits its own sign), a global negation of the predictor cannot change the
H1 |corr| or the H3 AUC. So 'short' is reported but is mechanically identical to
'raw' for these two tests — included for completeness / to make that explicit.

Out -> data/dex_alt_results.json   Run: python scripts/gex_bt/dex_alt_constructions.py
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
ITM_CUT = 0.85
RNG = np.random.default_rng(20260618)

VARIANTS = ["raw", "dollar", "short", "no_itm", "call_only", "put_only", "slope"]


def load_features() -> pd.DataFrame:
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

    dlt = df["delta"].values
    oi = df["oi"].values
    base = dlt * oi * 100.0
    df["dex_raw"] = base
    df["dex_dollar"] = base * S
    df["dex_short"] = -base
    df["dex_no_itm"] = np.where(np.abs(dlt) > ITM_CUT, 0.0, base)
    is_call = df["right"].values == "C"
    df["dex_call_only"] = np.where(is_call, base, 0.0)
    df["dex_put_only"] = np.where(~is_call, base, 0.0)

    g = df.groupby(["root", "date"])
    agg = g.agg(
        GEX=("gex", "sum"),
        DEX_raw=("dex_raw", "sum"),
        DEX_dollar=("dex_dollar", "sum"),
        DEX_short=("dex_short", "sum"),
        DEX_no_itm=("dex_no_itm", "sum"),
        DEX_call_only=("dex_call_only", "sum"),
        DEX_put_only=("dex_put_only", "sum"),
        spot=("spot", "median"),
    ).reset_index()

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
    dex_cols = [f"DEX_{v}" for v in VARIANTS if v != "slope"]
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
        # day-over-day SLOPE on the raw DEX (the "accelerated" variant)
        d["DEX_slope"] = d["DEX_raw"].diff()
        for col in dex_cols + ["DEX_slope", "GEX"]:
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
    p["near_level"] = (np.abs(dist) <= NEAR_LEVEL) & np.isfinite(L)
    fwd_spot = p["spot"] * (1 + p["fwd1"])
    atr = p["atr"].replace(0, np.nan)
    up_level = dist > 0
    broke = np.where(up_level, fwd_spot > (L + BREAK_ATR * atr),
                     fwd_spot < (L - BREAK_ATR * atr))
    bounced = np.where(up_level, fwd_spot < spot, fwd_spot > spot)
    p["bb"] = np.where(broke, 1.0, np.where(bounced, 0.0, np.nan))
    return p


def _boot_corr_p(x, y, dates, n=2000):
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


def _placebo_corr(x, y, dates, n=500):
    """Within-date permutation null for |corr| (matches the H2 placebo style)."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dates = x[m], y[m], dates[m]
    if len(x) < 50:
        return np.nan, np.nan
    obs = np.corrcoef(x, y)[0, 1]
    s = pd.Series(x); dd = pd.Series(dates)
    null = []
    for _ in range(n):
        perm = s.groupby(dd).transform(lambda v: v.sample(frac=1, random_state=RNG.integers(1e9)).values)
        c = np.corrcoef(perm.values, y)[0, 1]
        null.append(abs(c))
    null = np.array(null)
    p95 = np.nanpercentile(null, 97.5) if len(null) else np.nan
    beats = bool(abs(obs) > p95) if p95 == p95 else False
    return float(p95), beats


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


def run() -> dict:
    p = build_panel(load_features())
    dates = p["date"].values
    nl = p[p["near_level"]].copy()
    y = nl["bb"].values

    # H3 baseline (gamma + momentum) — shared across variants
    base_cols = nl[["gamma_regime", "prior5"]].values
    auc_base = _cv_auc(base_cols, y, nl["date"].values)

    res = {
        "n_name_days": int(len(p)),
        "n_near_level": int(p["near_level"].sum()),
        "H3_auc_gamma_momentum": round(auc_base, 4) if auc_base == auc_base else None,
        "variants": {},
    }

    for v in VARIANTS:
        zcol = f"DEX_{v}_z"
        # H1: direction (fwd1 + fwd3) — block-bootstrap p + within-date placebo band
        c1, pv1 = _boot_corr_p(p[zcol].values, p["fwd1_std"].values, dates)
        pb1_95, beats1 = _placebo_corr(p[zcol].values, p["fwd1_std"].values, dates)
        c3, pv3 = _boot_corr_p(p[zcol].values, p["fwd3_std"].values, dates)
        pb3_95, beats3 = _placebo_corr(p[zcol].values, p["fwd3_std"].values, dates)

        # H3: incremental lift over gamma+momentum
        full_cols = nl[["gamma_regime", "prior5", zcol]].values
        auc_full = _cv_auc(full_cols, y, nl["date"].values)
        lift = (auc_full - auc_base) if (auc_full == auc_full and auc_base == auc_base) else None

        res["variants"][v] = {
            "H1_fwd1": {"corr": round(c1, 4), "boot_p": round(pv1, 4),
                        "placebo_97.5pct": round(pb1_95, 4) if pb1_95 == pb1_95 else None,
                        "beats_placebo": beats1},
            "H1_fwd3": {"corr": round(c3, 4), "boot_p": round(pv3, 4),
                        "placebo_97.5pct": round(pb3_95, 4) if pb3_95 == pb3_95 else None,
                        "beats_placebo": beats3},
            "H3": {"auc_plus": round(auc_full, 4) if auc_full == auc_full else None,
                   "lift": round(lift, 4) if lift is not None else None,
                   "pass_lift_0.02": bool(lift is not None and lift >= 0.02)},
        }

    return res


if __name__ == "__main__":
    out = run()
    print("\n=== DEX ALTERNATE-CONSTRUCTION RESULTS ===")
    print(json.dumps(out, indent=2))
    Path("data/dex_alt_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote data/dex_alt_results.json")
