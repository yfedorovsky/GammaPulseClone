"""Vega-adjusted options PnL framework.

Phase 3 #3. Built to answer two questions the equity-only validation
cannot:

  Q1: Is the IV-rank gate threshold (currently 0.66) calibrated correctly?
      Should it be 0.50, 0.75, or something else for max edge in options?

  Q2: Does the HIGH-IV right-tail observed in equity returns survive
      after vega decay on a 21-day ATM long call? (i.e. would buying
      HIGH-IV calls actually pay off, or does IV mean reversion eat the
      equity gain?)

Method:
  - For each cohort bar with (spot, atm_iv, fwd_21d), simulate buying an
    ATM 30-DTE call at the bar's date and selling 21 days later.
  - Use Black-Scholes to price entry; price exit using:
      * spot moved by fwd_21d
      * IV mean-reverted partially toward the rolling-60d median (40% reversion)
      * time decayed by 21 days (now 9 DTE)
  - Net PnL = exit_price - entry_price (per share, scale by 100 if you want $)

Assumptions:
  - Risk-free rate 4.5% (current TBill levels)
  - No dividends (all cohort names are non-dividend-payers)
  - 40% IV mean reversion over 21 days — empirical estimate from options
    literature for short-dated single-name vol; can sensitivity-test.

Run:
    python -m backtest.vega_adjusted_pnl
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "zone_iv_validation_full.csv"
RFR = 0.045
ENTRY_DTE = 30
EXIT_DTE = 9                # 21 days held, started at 30
IV_MEAN_REV_FRAC = 0.40    # 40% of IV diff to median reverts in 21d


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(spot: float, strike: float, dte: float, iv: float, rfr: float = RFR) -> float:
    """Black-Scholes call price. dte in calendar days, iv as decimal."""
    if dte <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, spot - strike)
    t = dte / 365.0
    d1 = (math.log(spot / strike) + (rfr + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    return spot * normal_cdf(d1) - strike * math.exp(-rfr * t) * normal_cdf(d2)


def simulate_call_pnl_pct(spot0: float, iv0: float, fwd_ret: float,
                          iv_target: float, ticker: str | None = None,
                          iv_rank: float | None = None,
                          moneyness_pct: float = 0.0,
                          apply_slippage: bool = True) -> float | None:
    """Simulate buying ATM 30-DTE call, selling 21 days later.

    Phase 6A.1 update (Apr 26 night): now applies nonlinear per-name
    slippage from `backtest.slippage_model`. Default ON. Pass
    apply_slippage=False to compare gross vs net edge.

    Args:
        spot0: spot price at entry
        iv0: implied vol at entry (decimal)
        fwd_ret: 21-day spot return (decimal, e.g. 0.05 = +5%)
        iv_target: the rolling-median IV (the level toward which iv0 reverts)
        ticker: cohort symbol (for slippage lookup; None = no slippage)
        iv_rank: current IV-rank (for nonlinear slippage adjustment)
        moneyness_pct: strike distance OTM (0 = ATM, 0.05 = 5% OTM)
        apply_slippage: whether to debit slippage from PnL

    Returns: PnL as percent of entry premium (e.g. 50.0 = +50% return on call),
        net of round-trip slippage if apply_slippage=True.
        None if simulation invalid.
    """
    if spot0 <= 0 or iv0 <= 0 or iv_target <= 0:
        return None
    strike = spot0 * (1 + moneyness_pct)  # ATM if moneyness=0, OTM if positive
    entry = bs_call(spot0, strike, ENTRY_DTE, iv0)
    if entry <= 0.01:
        return None
    spot_exit = spot0 * (1 + fwd_ret)
    # IV mean reversion: iv1 = iv0 + frac * (target - iv0)
    iv1 = iv0 + IV_MEAN_REV_FRAC * (iv_target - iv0)
    iv1 = max(0.05, iv1)  # floor at 5 vol
    exit_p = bs_call(spot_exit, strike, EXIT_DTE, iv1)
    gross_pnl_pct = 100.0 * (exit_p - entry) / entry

    if not apply_slippage or ticker is None:
        return gross_pnl_pct

    # Phase 6A.1: subtract realistic round-trip slippage as % of premium
    try:
        from .slippage_model import slippage_lookup
    except ImportError:
        from backtest.slippage_model import slippage_lookup
    slip = slippage_lookup(ticker, iv_rank=iv_rank, moneyness_pct=moneyness_pct)
    return gross_pnl_pct - slip["round_trip_pct"]


def main() -> int:
    print("Vega-adjusted options PnL — IV-rank gate threshold tuning\n")
    df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")
    df.index.name = "date"
    df = df.dropna(subset=["atm_iv", "iv_rank", "fwd_21d", "Close"])
    print(f"Loaded {len(df):,} bars")

    # Compute rolling 60d median IV per ticker as the mean-reversion target
    df = df.sort_values(["ticker", "Date"] if "Date" in df.columns else ["ticker"])
    df["iv_target"] = (
        df.groupby("ticker")["atm_iv"]
        .transform(lambda s: s.rolling(60, min_periods=20).median())
    )
    df = df.dropna(subset=["iv_target"])

    # Simulate options PnL for each bar — gross AND net of slippage
    print("Simulating per-bar Black-Scholes ATM call PnL (gross + net of slippage)...")
    df["call_pnl_gross_pct"] = df.apply(
        lambda r: simulate_call_pnl_pct(
            spot0=r["Close"],
            iv0=r["atm_iv"],
            fwd_ret=r["fwd_21d"],
            iv_target=r["iv_target"],
            apply_slippage=False,
        ),
        axis=1,
    )
    df["call_pnl_net_pct"] = df.apply(
        lambda r: simulate_call_pnl_pct(
            spot0=r["Close"],
            iv0=r["atm_iv"],
            fwd_ret=r["fwd_21d"],
            iv_target=r["iv_target"],
            ticker=r["ticker"],
            iv_rank=r["iv_rank"],
            moneyness_pct=0.0,  # ATM baseline; rerun separately for OTM
            apply_slippage=True,
        ),
        axis=1,
    )
    # Default analysis uses NET (post-slippage)
    df["call_pnl_pct"] = df["call_pnl_net_pct"]
    df = df.dropna(subset=["call_pnl_pct"])
    print(f"After simulation: {len(df):,} bars\n")
    print(f"Gross vs Net medians:")
    print(f"  GROSS median PnL: {df['call_pnl_gross_pct'].median():+.1f}%")
    print(f"  NET median PnL:   {df['call_pnl_net_pct'].median():+.1f}%")
    print(f"  Slippage drag:    {df['call_pnl_gross_pct'].median() - df['call_pnl_net_pct'].median():.1f}pp\n")

    # === Q1: Tune IV-rank threshold ===
    print("=" * 78)
    print("Q1: IV-rank threshold tuning — block HIGH-IV in BEAR/TRANS")
    print("=" * 78)
    # Need historical regime — use the cohort-proxy approach from gate_replay
    # Approximate via per-bar SMA50 > SMA200 + slope check on each ticker
    # Faster: re-derive from existing zone-classification context
    # Easiest: use Close vs (rolling 200d) per ticker as a regime proxy
    df = df.sort_values(["ticker", "date"] if "date" in df.columns else ["ticker"])
    df["sma200"] = df.groupby("ticker")["Close"].transform(
        lambda s: s.rolling(200, min_periods=100).mean()
    )
    df["above_200"] = df["Close"] > df["sma200"]
    df = df.dropna(subset=["sma200"])

    # Aggregate to a synthetic daily breadth: % of cohort above 200d on each date
    daily_breadth = (
        df.reset_index().groupby("date" if "date" in df.reset_index().columns else "Date")["above_200"]
        .mean() * 100
    ).rename("pct_above")
    df = df.reset_index().merge(daily_breadth, left_on="date" if "date" in df.reset_index().columns else "Date",
                                  right_index=True, how="left").set_index("date" if "date" in df.reset_index().columns else "Date")
    df["regime"] = pd.cut(
        df["pct_above"], bins=[-1, 40, 60, 101],
        labels=["BEAR", "TRANSITIONAL", "FULL_BULL"],
    )
    print("Regime distribution:")
    print(df["regime"].value_counts().to_string())
    print()

    # Compare gate thresholds
    not_biotech = ~df["ticker"].isin({"ANAB", "CAPR", "GHRS"})
    in_block_regime = df["regime"].isin(["BEAR", "TRANSITIONAL"])
    print("\nGate threshold sweep (block when iv_rank > THRESHOLD in BEAR/TRANS):")
    print(f"  {'thresh':>7}  {'n_blocked':>9}  {'block_pnl_med':>14}  {'pass_pnl_med':>13}  {'delta_med':>10}  {'block_pnl_avg':>14}  {'pass_pnl_avg':>13}")
    for thresh in [0.50, 0.55, 0.60, 0.66, 0.70, 0.75, 0.80, 0.85]:
        block_mask = in_block_regime & (df["iv_rank"] > thresh) & not_biotech
        blocked = df.loc[block_mask, "call_pnl_pct"]
        passed = df.loc[~block_mask, "call_pnl_pct"]
        if blocked.empty or passed.empty:
            continue
        b_med = blocked.median()
        p_med = passed.median()
        b_avg = blocked.mean()
        p_avg = passed.mean()
        delta_med = p_med - b_med
        print(f"  {thresh:>7.2f}  {len(blocked):>9}  {b_med:>+13.1f}%  {p_med:>+12.1f}%  "
              f"{delta_med:>+9.1f}pp  {b_avg:>+13.1f}%  {p_avg:>+12.1f}%")

    print("\n  (delta_med = passed.median() - blocked.median(); higher = gate adds more value)")

    # === Q2: HIGH-IV right tail in bull regime — does it pay in options? ===
    print("\n" + "=" * 78)
    print("Q2: HIGH-IV right tail in FULL_BULL — does the equity gain survive vega?")
    print("=" * 78)
    bull = df[df["regime"] == "FULL_BULL"]
    if bull.empty:
        print("No FULL_BULL bars in sample")
    else:
        bull = bull.copy()
        bull["iv_tertile"] = pd.qcut(
            bull["iv_rank"], 3, labels=["LOW", "MID", "HIGH"], duplicates="drop"
        )
        print("\n  In FULL_BULL regime:")
        print(f"  {'IV-tertile':<12}  {'n':>5}  {'eq_avg_21d':>11}  {'call_avg_pnl':>13}  {'call_med_pnl':>13}  {'win_rate':>9}")
        for t in ["LOW", "MID", "HIGH"]:
            sub = bull[bull["iv_tertile"] == t]
            if sub.empty:
                continue
            eq = sub["fwd_21d"].mean() * 100
            call_avg = sub["call_pnl_pct"].mean()
            call_med = sub["call_pnl_pct"].median()
            win = (sub["call_pnl_pct"] > 0).mean() * 100
            print(f"  {t:<12}  {len(sub):>5}  {eq:>+10.2f}%  {call_avg:>+12.1f}%  "
                  f"{call_med:>+12.1f}%  {win:>8.1f}%")

    # === Q3: HIGH-IV right tail in BEAR regime ===
    print("\n" + "=" * 78)
    print("Q3: HIGH-IV right tail in BEAR — does vega decay AMPLIFY the loss?")
    print("=" * 78)
    bear = df[df["regime"] == "BEAR"]
    if bear.empty:
        print("No BEAR bars in sample")
    else:
        bear = bear.copy()
        bear["iv_tertile"] = pd.qcut(
            bear["iv_rank"], 3, labels=["LOW", "MID", "HIGH"], duplicates="drop"
        )
        print("\n  In BEAR regime:")
        print(f"  {'IV-tertile':<12}  {'n':>5}  {'eq_avg_21d':>11}  {'call_avg_pnl':>13}  {'call_med_pnl':>13}  {'win_rate':>9}")
        for t in ["LOW", "MID", "HIGH"]:
            sub = bear[bear["iv_tertile"] == t]
            if sub.empty:
                continue
            eq = sub["fwd_21d"].mean() * 100
            call_avg = sub["call_pnl_pct"].mean()
            call_med = sub["call_pnl_pct"].median()
            win = (sub["call_pnl_pct"] > 0).mean() * 100
            print(f"  {t:<12}  {len(sub):>5}  {eq:>+10.2f}%  {call_avg:>+12.1f}%  "
                  f"{call_med:>+12.1f}%  {win:>8.1f}%")

    # === Q4: Equity-vs-options sanity — is the avg call PnL ~5x the equity? ===
    print("\n" + "=" * 78)
    print("Q4: Sanity — options leverage (call PnL vs equity return)")
    print("=" * 78)
    print(f"  Average equity 21d return: {df['fwd_21d'].mean() * 100:+.2f}%")
    print(f"  Average call 21d PnL:      {df['call_pnl_pct'].mean():+.1f}%")
    print(f"  Ratio (leverage):           {df['call_pnl_pct'].mean() / (df['fwd_21d'].mean() * 100):.1f}x")
    print(f"  (For ATM 30-DTE → 9-DTE expected leverage ~2-4x; >4x suggests right-tail dominance.)")

    df.to_csv("data/vega_adjusted_pnl.csv")
    print(f"\nWrote {len(df)} rows to data/vega_adjusted_pnl.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
