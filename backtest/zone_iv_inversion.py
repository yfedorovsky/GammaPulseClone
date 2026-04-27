"""IV-Zone inversion backtest — test Perplexity's claim.

Claim: For options buyers, Zone A (pullback to rising EMA) has COMPRESSED
implied volatility (cheap premium = good entry), while Zone B (breakout above
swing high on volume) has ELEVATED IV (paying up = bad entry). The current
workflow allocates more size at Zone B than Zone A — backwards if true.

Test approach (proxy):
  - Reuse the 19-name QM x Minervini cohort + 2y daily history
  - Re-find triggers (same gates as qm_minervini_cohort.py)
  - For each trigger day, classify entry context:
      * Zone A:    close within 1.5% ABOVE EMA10
                   AND price in BOTTOM 60% of trailing 20d range
                   AND today's volume <= 1.2x 20d avg (no breakout volume)
      * Zone B:    close >= high20d * 0.995 (at/near 20d breakout)
                   AND today's volume >= 1.3x 20d avg (volume confirmation)
      * Other:     trigger day matching neither pattern
  - For each trigger compute "vol-rank proxy":
      * 5d realized vol annualized at trigger close
      * compare to trailing 60d distribution of same metric --> percentile rank
  - Compare:
      * vol-rank distribution Zone A vs Zone B  (the IV compression claim)
      * forward returns 5d / 10d / 21d Zone A vs Zone B  (the actionable test)

Run:
    python -m backtest.zone_iv_inversion
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

COHORT = [
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "CIEN", "RES", "AAOI",
    "CAMT", "TROX", "GLW", "LAR", "MU", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
]
LOOKBACK_DAYS = 730
RS_PCT_MIN = 0.70
FWD_HORIZONS = [5, 10, 21]


def fetch(ticker: str, period_days: int) -> pd.DataFrame | None:
    end = datetime.now()
    start = end - timedelta(days=period_days + 250)
    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False,
            auto_adjust=True, threads=False,
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except Exception:
        return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema10"] = out["Close"].ewm(span=10, adjust=False).mean()
    out["sma20"] = out["Close"].rolling(20).mean()
    out["sma50"] = out["Close"].rolling(50).mean()
    out["sma100"] = out["Close"].rolling(100).mean()
    out["sma200"] = out["Close"].rolling(200).mean()
    out["ret_1m"] = out["Close"].pct_change(21)
    out["high_252"] = out["Close"].rolling(252).max()
    out["pct_to_high"] = out["Close"] / out["high_252"]
    out["high_20"] = out["High"].rolling(20).max()
    out["low_20"] = out["Low"].rolling(20).min()
    out["range_pos"] = (out["Close"] - out["low_20"]) / (
        out["high_20"] - out["low_20"]
    )
    out["vol_avg_20"] = out["Volume"].rolling(20).mean()
    out["vol_ratio"] = out["Volume"] / out["vol_avg_20"]
    out["pct_above_ema10"] = (out["Close"] - out["ema10"]) / out["ema10"]
    # Realized vol proxy: 5d std of log returns annualized
    log_ret = np.log(out["Close"] / out["Close"].shift(1))
    out["rv_5d"] = log_ret.rolling(5).std() * np.sqrt(252)
    return out


def find_triggers(stock: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    df = stock.copy()
    df["spy_1m"] = spy["ret_1m"].reindex(df.index)
    df["rs_pct"] = (df["ret_1m"] - df["spy_1m"]).rolling(252).rank(pct=True)

    stacked = (
        (df["Close"] > df["ema10"])
        & (df["ema10"] > df["sma20"])
        & (df["sma20"] > df["sma50"])
        & (df["sma50"] > df["sma100"])
        & (df["sma100"] > df["sma200"])
    )
    rs_ok = df["rs_pct"] >= RS_PCT_MIN
    green = df["Close"] > df["Open"]
    near_high = df["pct_to_high"] >= 0.85
    df["trigger"] = stacked & rs_ok & green & near_high

    # Zone classification — applied to every bar in the uptrend regime,
    # not just the strict 7-gate triggers (which exclude most pullbacks
    # by construction).
    in_uptrend = (
        (df["Close"] > df["sma50"])
        & (df["sma50"] > df["sma200"])
        & (df["sma50"].diff(10) > 0)
    )
    # Zone A = price near rising EMA10/20, lower half of 20d range, normal volume
    zone_a = (
        in_uptrend
        & (df["pct_above_ema10"] <= 0.025)
        & (df["pct_above_ema10"] >= -0.015)
        & (df["range_pos"] <= 0.55)
        & (df["vol_ratio"] <= 1.30)
    )
    # Zone B = at/near 20d high with volume confirmation
    zone_b = (
        in_uptrend
        & (df["Close"] >= df["high_20"] * 0.99)
        & (df["vol_ratio"] >= 1.30)
    )
    df["zone"] = "Other"
    df.loc[zone_a, "zone"] = "A"
    df.loc[zone_b & ~zone_a, "zone"] = "B"

    # Vol-rank: 5d RV percentile within trailing 60 days
    df["rv_rank"] = df["rv_5d"].rolling(60).rank(pct=True)
    return df


def forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        out[f"fwd_{h}d"] = out["Close"].shift(-h) / out["Close"] - 1.0
    return out


def main() -> int:
    print(f"Zone IV-inversion backtest — {len(COHORT)} tickers, "
          f"{LOOKBACK_DAYS}d lookback")
    print("Vol proxy: 5d realized vol annualized, ranked vs trailing 60d\n")

    spy_raw = fetch("SPY", LOOKBACK_DAYS)
    if spy_raw is None:
        print("FATAL: SPY fetch failed")
        return 1
    spy = add_indicators(spy_raw)

    all_triggers: list[dict] = []
    for ticker in COHORT:
        raw = fetch(ticker, LOOKBACK_DAYS)
        if raw is None or len(raw) < 252:
            continue
        ind = add_indicators(raw)
        trig = find_triggers(ind, spy)
        fwd = forward_returns(trig, FWD_HORIZONS)
        # Test on every bar where zone is A or B (not just 7-gate triggers).
        # The 7-gate filter pre-selects extended bars and excludes most pullbacks.
        hits = fwd[fwd["zone"].isin(["A", "B"])].copy()
        for idx, row in hits.iterrows():
            all_triggers.append({
                "ticker": ticker,
                "date": idx,
                "zone": row["zone"],
                "rv_5d": row["rv_5d"],
                "rv_rank": row["rv_rank"],
                "vol_ratio": row["vol_ratio"],
                "range_pos": row["range_pos"],
                "pct_above_ema10": row["pct_above_ema10"],
                **{f"fwd_{h}d": row[f"fwd_{h}d"] for h in FWD_HORIZONS},
            })

    df = pd.DataFrame(all_triggers)
    print(f"Total triggers: {len(df)}")
    print(df["zone"].value_counts().to_string())
    print()

    # === Hypothesis 1: Zone A has lower vol-rank than Zone B (IV compression) ===
    print("=" * 70)
    print("H1: Zone A vol-rank < Zone B vol-rank (proxy for IV compression)")
    print("=" * 70)
    for zone in ["A", "B", "Other"]:
        sub = df[df["zone"] == zone]
        if sub.empty:
            continue
        rv = sub["rv_rank"].dropna()
        rv_5d = sub["rv_5d"].dropna()
        print(f"  Zone {zone:<5} n={len(sub):>4}  "
              f"rv_rank: mean={rv.mean():.2f} med={rv.median():.2f} "
              f"p25={rv.quantile(0.25):.2f} p75={rv.quantile(0.75):.2f}  "
              f"rv_5d (annual): med={rv_5d.median()*100:.1f}%")

    # Statistical test
    a = df[df["zone"] == "A"]["rv_rank"].dropna()
    b = df[df["zone"] == "B"]["rv_rank"].dropna()
    if len(a) >= 5 and len(b) >= 5:
        try:
            from scipy import stats
            t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
            print(f"\n  Welch t-test (A vs B vol-rank): t={t_stat:.3f} p={p_val:.4f}")
            print(f"  Mean diff: A-B = {a.mean() - b.mean():+.3f}")
            if p_val < 0.05:
                if a.mean() < b.mean():
                    print("  --> SIGNIFICANT: Zone A has lower vol-rank than Zone B "
                          "(supports Perplexity's IV-compression claim)")
                else:
                    print("  --> SIGNIFICANT but REVERSED: Zone A has HIGHER vol-rank")
            else:
                print("  --> NOT significant at p<0.05 — claim not supported by proxy")
        except ImportError:
            print("  (scipy not available, skipping t-test)")

    # === Hypothesis 2: Forward returns Zone A vs Zone B (the actionable test) ===
    print("\n" + "=" * 70)
    print("H2: Forward returns by zone (does it pay to weight A over B?)")
    print("=" * 70)
    for h in FWD_HORIZONS:
        col = f"fwd_{h}d"
        print(f"\n  --- {h}d forward return ---")
        for zone in ["A", "B", "Other"]:
            sub = df[df["zone"] == zone][col].dropna()
            if sub.empty:
                continue
            hit = (sub > 0).mean() * 100
            print(f"    Zone {zone:<5} n={len(sub):>4}  hit={hit:5.1f}%  "
                  f"avg={sub.mean()*100:+6.2f}%  med={sub.median()*100:+6.2f}%  "
                  f"p25={sub.quantile(0.25)*100:+6.2f}%  "
                  f"p75={sub.quantile(0.75)*100:+6.2f}%")

    # === Implication for options sizing ===
    print("\n" + "=" * 70)
    print("Implication for options sizing")
    print("=" * 70)
    a_5d = df[df["zone"] == "A"]["fwd_5d"].dropna()
    b_5d = df[df["zone"] == "B"]["fwd_5d"].dropna()
    a_21d = df[df["zone"] == "A"]["fwd_21d"].dropna()
    b_21d = df[df["zone"] == "B"]["fwd_21d"].dropna()

    if len(a_5d) and len(b_5d):
        # Crude options EV proxy: forward return minus IV-rank-driven cost
        # If vol-rank ~ IV-rank, then expected option pnl ~ fwd_return - (vol_rank_diff)
        # We compare zones on equity returns first, then layer on the IV penalty
        a_vol = df[df["zone"] == "A"]["rv_rank"].dropna().mean()
        b_vol = df[df["zone"] == "B"]["rv_rank"].dropna().mean()
        print(f"\n  Avg vol-rank Zone A: {a_vol:.2f}  (lower = cheaper options)")
        print(f"  Avg vol-rank Zone B: {b_vol:.2f}")
        print(f"  Vol-rank delta (B - A): {b_vol - a_vol:+.3f}")
        print(f"\n  Avg 5d return Zone A:  {a_5d.mean()*100:+.2f}%")
        print(f"  Avg 5d return Zone B:  {b_5d.mean()*100:+.2f}%")
        print(f"  Avg 21d return Zone A: {a_21d.mean()*100:+.2f}%")
        print(f"  Avg 21d return Zone B: {b_21d.mean()*100:+.2f}%")

    df.to_csv("data/zone_iv_inversion_triggers.csv", index=False)
    print(f"\nWrote {len(df)} rows to data/zone_iv_inversion_triggers.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
