"""IV-Zone inversion validation — ground-truth IV (not proxy).

Phase 1.5 follow-up to zone_iv_inversion.py.

The proxy backtest used 5-day realized-vol-rank as a stand-in for IV-rank,
because we didn't have historical IV per ticker readily available. But the
existing chain CSVs (data/AAOI_chains.csv, CIEN_chains.csv, GLW_chains.csv,
MU_chains.csv) DO have IV at every date/strike/expiration. That's 330
trading days x 4 names of full chain history with implied vol.

This script:
  1. For each of AAOI/CIEN/GLW/MU, build a daily ATM-30DTE IV time series
     from the chain CSV (no API calls — uses cached data on disk).
  2. Compute rolling 60d IV-rank per ticker.
  3. Re-classify each daily bar as Zone A / Zone B / Other (same logic as
     zone_iv_inversion.py).
  4. Cross-check the realized-vol-rank PROXY against the real IV-rank
     (correlation + zone-level mean comparison).
  5. Re-run the inversion analysis with REAL IV-rank.
  6. Decide: ship the inversion live, or hold pending more validation.

Run:
    python -m backtest.zone_iv_validation
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

NAMES_WITH_CHAINS = ["AAOI", "CIEN", "GLW", "MU"]
CHAIN_DIR = Path(__file__).resolve().parent.parent / "data"
DTE_TARGET = 30
DTE_TOLERANCE = (20, 45)   # accept any contract with DTE in this band
RV_LOOKBACK = 60           # rolling window for IV-rank and proxy rank
FWD_HORIZONS = [5, 10, 21]


def load_chain(ticker: str) -> pd.DataFrame:
    """Load one ticker's chain CSV with cleaned types."""
    path = CHAIN_DIR / f"{ticker}_chains.csv"
    df = pd.read_csv(path, parse_dates=["date", "expiration"])
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    return df


def build_atm_iv_series(ticker: str, spot: pd.Series) -> pd.DataFrame:
    """Build a daily ATM-30DTE IV time series for one ticker.

    For each date:
      - Filter to contracts with DTE in [20, 45]
      - Pick the expiration closest to 30 DTE
      - For that expiration, pick the strike closest to spot
      - Use call IV (calls are typically more liquid OTM-ATM than puts)
      - If no call available at that strike, fall back to put IV

    Returns: DataFrame indexed by date with columns:
      [atm_strike, atm_dte, expiration, atm_iv]
    """
    df = load_chain(ticker)
    df = df[(df["dte"] >= DTE_TOLERANCE[0]) & (df["dte"] <= DTE_TOLERANCE[1])]
    df = df[df["iv"] > 0.05]  # filter out garbage IV (<5%)

    spot_aligned = spot.reindex(df["date"].unique()).sort_index()

    rows = []
    for date in sorted(df["date"].unique()):
        if date not in spot.index:
            continue
        spot_px = spot.loc[date]
        if pd.isna(spot_px):
            continue
        day = df[df["date"] == date]
        # Pick expiration closest to 30 DTE
        day = day.copy()
        day["dte_dist"] = (day["dte"] - DTE_TARGET).abs()
        best_exp = day.loc[day["dte_dist"].idxmin(), "expiration"]
        exp_chain = day[day["expiration"] == best_exp].copy()
        # Pick strike closest to spot
        exp_chain["strike_dist"] = (exp_chain["strike"] - spot_px).abs()
        atm_row = exp_chain.loc[exp_chain["strike_dist"].idxmin()]
        # Prefer call IV; if not available take put
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

        rows.append({
            "date": date,
            "atm_strike": atm_row["strike"],
            "atm_dte": atm_row["dte"],
            "expiration": best_exp,
            "atm_iv": atm_iv,
            "spot": spot_px,
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out


def fetch_spot(ticker: str, start: str, end: str) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=True, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Match the indicator stack from zone_iv_inversion.py."""
    out = df.copy()
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
    return out


def classify_zone(df: pd.DataFrame) -> pd.Series:
    in_uptrend = (
        (df["Close"] > df["sma50"])
        & (df["sma50"] > df["sma200"])
        & (df["sma50"].diff(10) > 0)
    )
    zone_a = (
        in_uptrend
        & (df["pct_above_ema10"] <= 0.025)
        & (df["pct_above_ema10"] >= -0.015)
        & (df["range_pos"] <= 0.55)
        & (df["vol_ratio"] <= 1.30)
    )
    zone_b = (
        in_uptrend
        & (df["Close"] >= df["high_20"] * 0.99)
        & (df["vol_ratio"] >= 1.30)
    )
    zone = pd.Series("Other", index=df.index)
    zone.loc[zone_a] = "A"
    zone.loc[zone_b & ~zone_a] = "B"
    return zone


def forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        out[f"fwd_{h}d"] = out["Close"].shift(-h) / out["Close"] - 1.0
    return out


def main() -> int:
    print("IV-Zone inversion VALIDATION (ground-truth IV from chain CSVs)\n")

    all_rows: list[pd.DataFrame] = []
    for ticker in NAMES_WITH_CHAINS:
        print(f"--- {ticker} ---")
        # Pull spot for the full chain date range
        chain = load_chain(ticker)
        start = chain["date"].min().date().isoformat()
        end = (chain["date"].max().date() + timedelta(days=1)).isoformat()
        spot = fetch_spot(ticker, start, end)
        # Need OHLC not just close for indicators
        ohlc = yf.download(ticker, start=start, end=end, progress=False,
                           auto_adjust=True, threads=False)
        if isinstance(ohlc.columns, pd.MultiIndex):
            ohlc.columns = ohlc.columns.get_level_values(0)
        ohlc.index = pd.to_datetime(ohlc.index).tz_localize(None)
        ind = add_indicators(ohlc)
        ind["zone"] = classify_zone(ind)
        ind = forward_returns(ind, FWD_HORIZONS)

        # Build ATM IV series and join
        iv_series = build_atm_iv_series(ticker, spot)
        ind = ind.join(iv_series[["atm_iv", "atm_dte", "atm_strike"]], how="left")

        # IV-rank: percentile within trailing 60 trading days
        ind["iv_rank"] = ind["atm_iv"].rolling(RV_LOOKBACK).rank(pct=True)
        ind["ticker"] = ticker
        all_rows.append(ind)
        n_days = ind["atm_iv"].notna().sum()
        n_zone_a = (ind["zone"] == "A").sum()
        n_zone_b = (ind["zone"] == "B").sum()
        print(f"  {n_days} days with ATM IV, {n_zone_a} Zone A bars, "
              f"{n_zone_b} Zone B bars")

    big = pd.concat(all_rows)
    big = big.dropna(subset=["atm_iv", "iv_rank", "rv_rank"])

    print(f"\nTotal bars with both IV-rank and proxy rank: {len(big)}")

    # === Validation 1: correlation between real IV-rank and proxy rv-rank ===
    print("\n" + "=" * 70)
    print("Validation 1: Does the realized-vol proxy track real IV-rank?")
    print("=" * 70)
    corr_pearson = big["iv_rank"].corr(big["rv_rank"], method="pearson")
    corr_spearman = big["iv_rank"].corr(big["rv_rank"], method="spearman")
    print(f"  Pearson correlation:  {corr_pearson:+.3f}")
    print(f"  Spearman correlation: {corr_spearman:+.3f}")
    if corr_spearman > 0.5:
        print("  --> Proxy is reasonably aligned with real IV (rho>0.5)")
    elif corr_spearman > 0.3:
        print("  --> Proxy is moderately aligned (0.3<rho<0.5) — directional only")
    else:
        print("  --> Proxy is POORLY aligned — original conclusions may not transfer")

    # === Validation 2: zone-level real IV-rank distribution ===
    print("\n" + "=" * 70)
    print("Validation 2: Real IV-rank by zone (the actual claim)")
    print("=" * 70)
    for zone in ["A", "B", "Other"]:
        sub = big[big["zone"] == zone]
        if sub.empty:
            continue
        iv_r = sub["iv_rank"].dropna()
        atm_iv = sub["atm_iv"].dropna()
        print(f"  Zone {zone:<5} n={len(sub):>4}  "
              f"iv_rank: mean={iv_r.mean():.2f} med={iv_r.median():.2f} "
              f"p25={iv_r.quantile(0.25):.2f} p75={iv_r.quantile(0.75):.2f}  "
              f"atm_iv: med={atm_iv.median()*100:.1f}%")

    a_iv = big[big["zone"] == "A"]["iv_rank"].dropna()
    b_iv = big[big["zone"] == "B"]["iv_rank"].dropna()
    if len(a_iv) >= 5 and len(b_iv) >= 5:
        from scipy import stats
        t_stat, p_val = stats.ttest_ind(a_iv, b_iv, equal_var=False)
        print(f"\n  Welch t-test (real IV-rank A vs B): t={t_stat:.3f} p={p_val:.4f}")
        delta = a_iv.mean() - b_iv.mean()
        print(f"  Mean delta: A-B = {delta:+.3f}")
        if p_val < 0.05 and delta < 0:
            print("  --> CONFIRMED with REAL IV: Zone A has lower IV-rank than Zone B")
        elif p_val < 0.05 and delta > 0:
            print("  --> REVERSED: real IV shows opposite pattern from proxy")
        else:
            print("  --> Not significant with real IV — proxy may have been noise")

    # === Validation 3: forward returns by zone with real IV ===
    print("\n" + "=" * 70)
    print("Validation 3: Forward returns by zone (real IV-rank universe)")
    print("=" * 70)
    for h in FWD_HORIZONS:
        col = f"fwd_{h}d"
        print(f"\n  --- {h}d ---")
        for zone in ["A", "B", "Other"]:
            sub = big[big["zone"] == zone][col].dropna()
            if sub.empty:
                continue
            hit = (sub > 0).mean() * 100
            print(f"    Zone {zone:<5} n={len(sub):>4}  "
                  f"hit={hit:5.1f}%  avg={sub.mean()*100:+6.2f}%  "
                  f"med={sub.median()*100:+6.2f}%")

    # === Validation 4: per-ticker breakdown ===
    print("\n" + "=" * 70)
    print("Validation 4: Per-ticker IV-rank by zone (sanity check)")
    print("=" * 70)
    for ticker in NAMES_WITH_CHAINS:
        sub = big[big["ticker"] == ticker]
        a = sub[sub["zone"] == "A"]["iv_rank"].dropna()
        b = sub[sub["zone"] == "B"]["iv_rank"].dropna()
        if len(a) < 3 or len(b) < 3:
            print(f"  {ticker}: insufficient zone bars")
            continue
        print(f"  {ticker}: A med={a.median():.2f} (n={len(a)}) "
              f"B med={b.median():.2f} (n={len(b)}) "
              f"delta={a.median() - b.median():+.2f}")

    big.to_csv("data/zone_iv_validation.csv")
    print(f"\nWrote {len(big)} rows to data/zone_iv_validation.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
