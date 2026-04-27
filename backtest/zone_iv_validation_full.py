"""IV-Zone inversion validation with FULL 19-name ground-truth IV.

Combines the existing chain CSVs (AAOI, CIEN, GLW, MU) with the new
ThetaData-pulled ATM IV series (data/atm_iv_30dte/*.csv) for the other
15 cohort names. Total: 19-name validation universe.

Same methodology as zone_iv_validation.py but with the wider sample.

Run:
    python -m backtest.zone_iv_validation_full
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

CHAIN_NAMES = ["AAOI", "CIEN", "GLW", "MU"]   # have full chain CSVs
THETA_NAMES = [                                # have ATM-IV pulls
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "RES", "CAMT", "TROX",
    "LAR", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
]
COHORT = CHAIN_NAMES + THETA_NAMES
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ATM_DIR = DATA_DIR / "atm_iv_30dte"

DTE_TARGET = 30
DTE_TOLERANCE = (20, 45)
RV_LOOKBACK = 60
FWD_HORIZONS = [5, 10, 21]


def load_atm_iv_from_chain(ticker: str) -> pd.DataFrame:
    """Build ATM-30DTE IV daily series from full chain CSV (AAOI/CIEN/GLW/MU)."""
    path = DATA_DIR / f"{ticker}_chains.csv"
    df = pd.read_csv(path, parse_dates=["date", "expiration"])
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    df = df[(df["dte"] >= DTE_TOLERANCE[0]) & (df["dte"] <= DTE_TOLERANCE[1])]
    df = df[df["iv"] > 0.05]

    # Need spot per date — pull from yfinance to pick ATM strike
    start = df["date"].min().date().isoformat()
    end = (df["date"].max().date() + timedelta(days=1)).isoformat()
    spot = yf.download(ticker, start=start, end=end, progress=False,
                       auto_adjust=True, threads=False)
    if isinstance(spot.columns, pd.MultiIndex):
        spot.columns = spot.columns.get_level_values(0)
    spot = spot["Close"]
    spot.index = pd.to_datetime(spot.index).tz_localize(None)

    rows = []
    for date in sorted(df["date"].unique()):
        if date not in spot.index:
            continue
        spot_px = spot.loc[date]
        if pd.isna(spot_px):
            continue
        day = df[df["date"] == date].copy()
        day["dte_dist"] = (day["dte"] - DTE_TARGET).abs()
        best_exp = day.loc[day["dte_dist"].idxmin(), "expiration"]
        exp_chain = day[day["expiration"] == best_exp].copy()
        exp_chain["strike_dist"] = (exp_chain["strike"] - spot_px).abs()
        atm_row = exp_chain.loc[exp_chain["strike_dist"].idxmin()]
        call = exp_chain[
            (exp_chain["strike"] == atm_row["strike"])
            & (exp_chain["option_type"] == "call")
        ]
        if not call.empty:
            atm_iv = call.iloc[0]["iv"]
        else:
            put = exp_chain[
                (exp_chain["strike"] == atm_row["strike"])
                & (exp_chain["option_type"] == "put")
            ]
            atm_iv = put.iloc[0]["iv"] if not put.empty else atm_row["iv"]
        rows.append({"date": date, "atm_iv": atm_iv})
    return pd.DataFrame(rows).set_index("date").sort_index()


def load_atm_iv_from_theta(ticker: str) -> pd.DataFrame:
    """Load pre-pulled ATM-IV series from data/atm_iv_30dte/{ticker}.csv."""
    path = ATM_DIR / f"{ticker}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")[["atm_iv"]].sort_index()


def add_indicators_and_zones(ohlc: pd.DataFrame) -> pd.DataFrame:
    out = ohlc.copy()
    out["ema10"] = out["Close"].ewm(span=10, adjust=False).mean()
    out["sma20"] = out["Close"].rolling(20).mean()
    out["sma50"] = out["Close"].rolling(50).mean()
    out["sma200"] = out["Close"].rolling(200).mean()
    out["high_20"] = out["High"].rolling(20).max()
    out["low_20"] = out["Low"].rolling(20).min()
    out["range_pos"] = (out["Close"] - out["low_20"]) / (
        out["high_20"] - out["low_20"]
    )
    out["vol_avg_20"] = out["Volume"].rolling(20).mean()
    out["vol_ratio"] = out["Volume"] / out["vol_avg_20"]
    out["pct_above_ema10"] = (out["Close"] - out["ema10"]) / out["ema10"]
    log_ret = np.log(out["Close"] / out["Close"].shift(1))
    out["rv_5d"] = log_ret.rolling(5).std() * np.sqrt(252)
    out["rv_rank"] = out["rv_5d"].rolling(RV_LOOKBACK).rank(pct=True)

    in_uptrend = (
        (out["Close"] > out["sma50"])
        & (out["sma50"] > out["sma200"])
        & (out["sma50"].diff(10) > 0)
    )
    zone_a = (
        in_uptrend
        & (out["pct_above_ema10"] <= 0.025)
        & (out["pct_above_ema10"] >= -0.015)
        & (out["range_pos"] <= 0.55)
        & (out["vol_ratio"] <= 1.30)
    )
    zone_b = (
        in_uptrend
        & (out["Close"] >= out["high_20"] * 0.99)
        & (out["vol_ratio"] >= 1.30)
    )
    zone = pd.Series("Other", index=out.index)
    zone.loc[zone_a] = "A"
    zone.loc[zone_b & ~zone_a] = "B"
    out["zone"] = zone
    for h in FWD_HORIZONS:
        out[f"fwd_{h}d"] = out["Close"].shift(-h) / out["Close"] - 1.0
    return out


def main() -> int:
    print(f"FULL 19-name IV-zone validation\n")

    all_rows = []
    for ticker in COHORT:
        if ticker in CHAIN_NAMES:
            iv = load_atm_iv_from_chain(ticker)
            source = "chain_csv"
        else:
            iv = load_atm_iv_from_theta(ticker)
            source = "theta_pull"

        if iv.empty:
            print(f"  {ticker}: no IV data ({source}) — skipping")
            continue

        start = iv.index.min().date().isoformat()
        end = (iv.index.max().date() + timedelta(days=2)).isoformat()
        ohlc = yf.download(ticker, start=start, end=end, progress=False,
                           auto_adjust=True, threads=False)
        if isinstance(ohlc.columns, pd.MultiIndex):
            ohlc.columns = ohlc.columns.get_level_values(0)
        ohlc.index = pd.to_datetime(ohlc.index).tz_localize(None)
        if ohlc.empty:
            continue

        ind = add_indicators_and_zones(ohlc)
        ind = ind.join(iv, how="left")
        ind["iv_rank"] = ind["atm_iv"].rolling(RV_LOOKBACK).rank(pct=True)
        ind["ticker"] = ticker
        ind["iv_source"] = source

        n_a = (ind["zone"] == "A").sum()
        n_b = (ind["zone"] == "B").sum()
        print(f"  {ticker:<6} ({source}): {len(iv)} IV days, "
              f"Zone A bars={n_a}, Zone B bars={n_b}")
        all_rows.append(ind)

    big = pd.concat(all_rows)
    big = big.dropna(subset=["atm_iv", "iv_rank", "rv_rank"])
    print(f"\nTotal valid rows (all bars w/ IV-rank + RV-rank): {len(big)}")

    # ====== Validation 1 — proxy-vs-real correlation ======
    print("\n" + "=" * 70)
    print("V1: realized-vol-rank PROXY vs real IV-rank correlation")
    print("=" * 70)
    pearson = big["iv_rank"].corr(big["rv_rank"], method="pearson")
    spearman = big["iv_rank"].corr(big["rv_rank"], method="spearman")
    print(f"  Pearson:  {pearson:+.3f}")
    print(f"  Spearman: {spearman:+.3f}")

    # ====== Validation 2 — zone-level real IV-rank ======
    print("\n" + "=" * 70)
    print("V2: Real IV-rank by zone (the central claim)")
    print("=" * 70)
    for zone in ["A", "B", "Other"]:
        sub = big[big["zone"] == zone]
        if sub.empty:
            continue
        iv_r = sub["iv_rank"]
        atm = sub["atm_iv"]
        print(f"  Zone {zone:<5} n={len(sub):>5}  "
              f"iv_rank mean={iv_r.mean():.2f} med={iv_r.median():.2f} "
              f"p25={iv_r.quantile(0.25):.2f} p75={iv_r.quantile(0.75):.2f}  "
              f"atm_iv med={atm.median()*100:.1f}%")

    a = big[big["zone"] == "A"]["iv_rank"]
    b = big[big["zone"] == "B"]["iv_rank"]
    if len(a) >= 5 and len(b) >= 5:
        from scipy import stats
        t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
        delta = a.mean() - b.mean()
        print(f"\n  Welch t-test (A vs B real IV-rank): t={t_stat:.3f} p={p_val:.4f}")
        print(f"  Mean delta (A - B): {delta:+.3f}")
        if p_val < 0.05:
            if delta < 0:
                print("  --> CONFIRMED: Zone A has lower real IV-rank "
                      "(supports inversion claim)")
            else:
                print("  --> REVERSED: Zone A has HIGHER real IV-rank "
                      "(claim falsified)")
        else:
            print(f"  --> Not significant (p={p_val:.3f}) — "
                  "no robust difference in either direction")

    # ====== Validation 3 — forward returns ======
    print("\n" + "=" * 70)
    print("V3: Forward equity returns by zone")
    print("=" * 70)
    for h in FWD_HORIZONS:
        col = f"fwd_{h}d"
        print(f"\n  --- {h}d ---")
        for zone in ["A", "B", "Other"]:
            sub = big[big["zone"] == zone][col].dropna()
            if sub.empty:
                continue
            hit = (sub > 0).mean() * 100
            print(f"    Zone {zone:<5} n={len(sub):>5}  hit={hit:5.1f}%  "
                  f"avg={sub.mean()*100:+6.2f}%  med={sub.median()*100:+6.2f}%")

    # ====== Validation 4 — per-ticker IV-rank delta ======
    print("\n" + "=" * 70)
    print("V4: Per-ticker IV-rank delta (A - B), sorted")
    print("=" * 70)
    rows = []
    for ticker in COHORT:
        sub = big[big["ticker"] == ticker]
        a = sub[sub["zone"] == "A"]["iv_rank"]
        b = sub[sub["zone"] == "B"]["iv_rank"]
        if len(a) < 3 or len(b) < 3:
            rows.append({"ticker": ticker, "na": len(a), "nb": len(b),
                         "a_med": a.median() if len(a) else np.nan,
                         "b_med": b.median() if len(b) else np.nan,
                         "delta": np.nan})
            continue
        rows.append({
            "ticker": ticker, "na": len(a), "nb": len(b),
            "a_med": round(a.median(), 2), "b_med": round(b.median(), 2),
            "delta": round(a.median() - b.median(), 2),
        })
    pt = pd.DataFrame(rows).sort_values("delta")
    with pd.option_context("display.max_rows", None, "display.width", 100):
        print(pt.to_string(index=False))

    # ====== Validation 5 — IV-rank tertiles vs forward returns ======
    print("\n" + "=" * 70)
    print("V5: Forward returns by REAL IV-rank tertile (regardless of zone)")
    print("=" * 70)
    big["iv_tertile"] = pd.qcut(big["iv_rank"], 3,
                                 labels=["LOW", "MID", "HIGH"])
    for h in FWD_HORIZONS:
        col = f"fwd_{h}d"
        print(f"\n  --- {h}d ---")
        for t in ["LOW", "MID", "HIGH"]:
            sub = big[big["iv_tertile"] == t][col].dropna()
            if sub.empty:
                continue
            hit = (sub > 0).mean() * 100
            print(f"    IV {t:<4} n={len(sub):>5}  hit={hit:5.1f}%  "
                  f"avg={sub.mean()*100:+6.2f}%")

    big.to_csv("data/zone_iv_validation_full.csv")
    print(f"\nWrote {len(big)} rows to data/zone_iv_validation_full.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
