"""VIX intraday regime backtest.

Hypothesis: Days where VIX opens < 20 AND declines intraday are
"easy bullish momentum" days — SPY tends to trend in the direction
of the morning move with low drawdown.

Method:
1. Pull daily VIX + SPY OHLC for the last 365 days (long history, reliable)
2. Pull 15-min VIX + SPY bars for the last ~90 days (intraday granularity)
3. Classify each day by VIX regime (VIX_BULL / VIX_FLAT / VIX_RISING)
4. Measure SPY behavior per regime: open-to-close return, intraday drawdown,
   trend consistency
5. Output a regime → SPY-behavior matrix

Usage:
    python -m scripts.backtest_vix_regime              # daily + intraday
    python -m scripts.backtest_vix_regime --daily-only # daily only (faster)
    python -m scripts.backtest_vix_regime --days 180   # custom lookback
"""
from __future__ import annotations

import asyncio
import datetime
import math
import sys
from collections import defaultdict
from statistics import mean, stdev

# Make the server module importable when run as a script
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.tradier import TradierClient


# ── Regime classification ─────────────────────────────────────────────

VIX_LOW_THRESHOLD = 20.0     # "low vol" regime absolute level
VIX_DECLINE_PCT = 3.0        # VIX close must be this% below open to qualify as declining
VIX_RISE_PCT = 3.0           # VIX close this% above open = rising


def classify_day(vix_open: float, vix_close: float, vix_high: float, vix_low: float) -> str:
    """Classify a single day's VIX behavior.

    Returns one of:
      VIX_BULL_COMPRESS  — VIX open < 20, VIX close down 3%+  ← target regime
      VIX_LOW_FLAT       — VIX open < 20, sideways intraday
      VIX_LOW_RISING     — VIX open < 20 but close up 3%+
      VIX_ELEVATED_COMP  — VIX open 20-25, declining (volatility normalizing)
      VIX_ELEVATED_FLAT  — VIX 20-25, sideways
      VIX_HIGH           — VIX > 25 (stress regime)
      VIX_SPIKE          — VIX closing +3%+ higher from open (risk-off)
    """
    change_pct = (vix_close - vix_open) / vix_open * 100 if vix_open else 0

    if vix_open < VIX_LOW_THRESHOLD:
        if change_pct <= -VIX_DECLINE_PCT:
            return "VIX_BULL_COMPRESS"
        elif change_pct >= VIX_RISE_PCT:
            return "VIX_LOW_RISING"
        else:
            return "VIX_LOW_FLAT"
    elif vix_open < 25:
        if change_pct <= -VIX_DECLINE_PCT:
            return "VIX_ELEVATED_COMP"
        else:
            return "VIX_ELEVATED_FLAT"
    else:
        if change_pct >= VIX_RISE_PCT:
            return "VIX_SPIKE"
        return "VIX_HIGH"


# ── Daily analysis ────────────────────────────────────────────────────

async def analyze_daily(days: int = 365) -> dict:
    """Pull daily OHLC for VIX + SPY, classify each day, measure SPY behavior."""
    tradier = TradierClient()
    try:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        start_str = start.isoformat()
        end_str = end.isoformat()

        print(f"[DAILY] Pulling VIX + SPY from {start_str} to {end_str}...")
        vix_bars = await tradier.history("VIX", interval="daily", start=start_str, end=end_str)
        spy_bars = await tradier.history("SPY", interval="daily", start=start_str, end=end_str)
    finally:
        await tradier.close()

    print(f"[DAILY] Got {len(vix_bars)} VIX bars, {len(spy_bars)} SPY bars")

    # Align by date
    vix_by_date = {b["time"]: b for b in vix_bars}
    spy_by_date = {b["time"]: b for b in spy_bars}

    # Per-regime SPY behavior
    regime_stats: dict[str, list[dict]] = defaultdict(list)

    for date, vix in vix_by_date.items():
        spy = spy_by_date.get(date)
        if not spy:
            continue
        regime = classify_day(vix["open"], vix["close"], vix["high"], vix["low"])

        # SPY metrics
        spy_oc_pct = (spy["close"] - spy["open"]) / spy["open"] * 100 if spy["open"] else 0
        spy_hl_pct = (spy["high"] - spy["low"]) / spy["open"] * 100 if spy["open"] else 0
        # Proxy for intraday drawdown (can't tell direction without intraday bars):
        # if close > open, drawdown proxy = (low - open)/open (negative)
        # if close < open, rally proxy = (high - open)/open (positive)
        spy_dd_pct = (spy["low"] - spy["open"]) / spy["open"] * 100 if spy["open"] else 0
        spy_rally_pct = (spy["high"] - spy["open"]) / spy["open"] * 100 if spy["open"] else 0

        vix_change_pct = (vix["close"] - vix["open"]) / vix["open"] * 100 if vix["open"] else 0

        regime_stats[regime].append({
            "date": date,
            "vix_open": vix["open"],
            "vix_close": vix["close"],
            "vix_change_pct": vix_change_pct,
            "spy_open": spy["open"],
            "spy_close": spy["close"],
            "spy_oc_pct": spy_oc_pct,
            "spy_hl_pct": spy_hl_pct,
            "spy_dd_pct": spy_dd_pct,
            "spy_rally_pct": spy_rally_pct,
        })

    return regime_stats


def print_regime_report(regime_stats: dict, title: str) -> None:
    """Print per-regime SPY behavior summary."""
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)

    # Order by "desirability" — target regime first, risk regimes last
    ordered = [
        "VIX_BULL_COMPRESS",
        "VIX_LOW_FLAT",
        "VIX_ELEVATED_COMP",
        "VIX_LOW_RISING",
        "VIX_ELEVATED_FLAT",
        "VIX_HIGH",
        "VIX_SPIKE",
    ]

    total_days = sum(len(days) for days in regime_stats.values())

    header = f"{'Regime':<22} {'Days':>5} {'Pct':>6} {'SPY OC%':>10} {'SPY Rng%':>10} {'Win Rate':>10} {'Sharpe':>8}"
    print(header)
    print("-" * 80)

    for regime in ordered:
        days = regime_stats.get(regime, [])
        if not days:
            continue
        n = len(days)
        pct = n / total_days * 100 if total_days else 0
        oc_returns = [d["spy_oc_pct"] for d in days]
        ranges = [d["spy_hl_pct"] for d in days]
        wins = sum(1 for r in oc_returns if r > 0)
        win_rate = wins / n * 100
        avg_oc = mean(oc_returns)
        avg_rng = mean(ranges)
        # Daily Sharpe-like: mean / std
        sharpe = avg_oc / stdev(oc_returns) if n > 1 and stdev(oc_returns) > 0 else 0

        print(f"{regime:<22} {n:>5} {pct:>5.1f}% {avg_oc:>9.2f}% {avg_rng:>9.2f}% {win_rate:>8.1f}%  {sharpe:>7.2f}")

    # Summary
    print()
    bull_days = regime_stats.get("VIX_BULL_COMPRESS", [])
    if bull_days:
        bull_wins = sum(1 for d in bull_days if d["spy_oc_pct"] > 0)
        bull_win_rate = bull_wins / len(bull_days) * 100
        bull_avg = mean([d["spy_oc_pct"] for d in bull_days])

        # Compare against all-other-days baseline
        other_days = [d for r, days in regime_stats.items() for d in days if r != "VIX_BULL_COMPRESS"]
        other_wins = sum(1 for d in other_days if d["spy_oc_pct"] > 0)
        other_win_rate = other_wins / len(other_days) * 100 if other_days else 0
        other_avg = mean([d["spy_oc_pct"] for d in other_days]) if other_days else 0

        print(f"  >> VIX_BULL_COMPRESS vs All Others:")
        print(f"     Win rate:    {bull_win_rate:.1f}%  (vs {other_win_rate:.1f}% baseline, {bull_win_rate - other_win_rate:+.1f}pp)")
        print(f"     Avg SPY OC:  {bull_avg:+.2f}%  (vs {other_avg:+.2f}% baseline, {bull_avg - other_avg:+.2f}pp)")


# ── Intraday analysis (15-min bars) ──────────────────────────────────

async def analyze_intraday(days: int = 90) -> dict:
    """Pull 15-min bars for VIX + SPY. Classify days by intraday VIX path.

    Enhanced classification using morning vs afternoon VIX:
      - If VIX declines monotonically through the day → strongest bull signal
      - If VIX spikes early then fades → bull reversal
      - If VIX rises monotonically → risk-off
    """
    tradier = TradierClient()
    try:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        # Tradier timesales uses full ISO with time, use market open time
        start_str = f"{start.isoformat()} 09:30"
        end_str = f"{end.isoformat()} 16:00"

        print(f"[INTRADAY] Pulling 15-min bars for VIX + SPY ({days} days)...")
        vix_bars = await tradier.history("VIX", interval="15min", start=start_str, end=end_str)
        spy_bars = await tradier.history("SPY", interval="15min", start=start_str, end=end_str)
    finally:
        await tradier.close()

    print(f"[INTRADAY] Got {len(vix_bars)} VIX bars, {len(spy_bars)} SPY bars")

    if not vix_bars:
        print("[INTRADAY] No intraday VIX data returned — skipping intraday analysis")
        return {}

    # Group bars by trading day
    def group_by_day(bars):
        by_day = defaultdict(list)
        for b in bars:
            ts = b["time"]
            if isinstance(ts, int):
                dt = datetime.datetime.fromtimestamp(ts)
            else:
                continue
            # Only regular hours 9:30 - 16:00 ET (approximate)
            day = dt.date().isoformat()
            by_day[day].append(b)
        return {d: sorted(bars, key=lambda x: x["time"]) for d, bars in by_day.items()}

    vix_days = group_by_day(vix_bars)
    spy_days = group_by_day(spy_bars)

    regime_stats: dict[str, list[dict]] = defaultdict(list)

    for day, vix_day_bars in vix_days.items():
        spy_day_bars = spy_days.get(day)
        if not spy_day_bars or len(vix_day_bars) < 5:
            continue

        # Compute intraday metrics
        vix_open = vix_day_bars[0]["open"]
        vix_close = vix_day_bars[-1]["close"]
        vix_high = max(b["high"] for b in vix_day_bars)
        vix_low = min(b["low"] for b in vix_day_bars)

        # Monotonic decline check: VIX made lower highs and lower lows
        vix_closes = [b["close"] for b in vix_day_bars]
        n = len(vix_closes)
        if n >= 4:
            first_half = vix_closes[:n // 2]
            second_half = vix_closes[n // 2:]
            first_avg = mean(first_half)
            second_avg = mean(second_half)
            is_monotonic_decline = second_avg < first_avg * 0.98  # 2%+ morning vs afternoon
        else:
            is_monotonic_decline = False

        base_regime = classify_day(vix_open, vix_close, vix_high, vix_low)

        # Upgrade VIX_BULL_COMPRESS if also monotonic
        if base_regime == "VIX_BULL_COMPRESS" and is_monotonic_decline:
            regime = "VIX_BULL_SMOOTH"  # best case: low + monotonic decline
        else:
            regime = base_regime

        # SPY metrics intraday
        spy_open = spy_day_bars[0]["open"]
        spy_close = spy_day_bars[-1]["close"]
        spy_high = max(b["high"] for b in spy_day_bars)
        spy_low = min(b["low"] for b in spy_day_bars)

        spy_oc_pct = (spy_close - spy_open) / spy_open * 100 if spy_open else 0
        spy_hl_pct = (spy_high - spy_low) / spy_open * 100 if spy_open else 0

        # Intraday drawdown from open (worst)
        spy_intraday_closes = [b["close"] for b in spy_day_bars]
        min_so_far = spy_open
        max_dd_from_open = 0
        for c in spy_intraday_closes:
            if c < min_so_far:
                min_so_far = c
            dd = (c - spy_open) / spy_open * 100 if spy_open else 0
            if dd < max_dd_from_open:
                max_dd_from_open = dd

        # Trend consistency — % of 15-min closes above open (for bull days)
        pct_above_open = sum(1 for c in spy_intraday_closes if c > spy_open) / len(spy_intraday_closes) * 100

        regime_stats[regime].append({
            "date": day,
            "vix_open": vix_open,
            "vix_close": vix_close,
            "spy_oc_pct": spy_oc_pct,
            "spy_hl_pct": spy_hl_pct,
            "spy_max_dd_pct": max_dd_from_open,
            "pct_above_open": pct_above_open,
        })

    return regime_stats


def print_intraday_report(regime_stats: dict, title: str) -> None:
    """Print intraday regime report with trend metrics."""
    print()
    print("=" * 90)
    print(f"  {title}")
    print("=" * 90)

    ordered = [
        "VIX_BULL_SMOOTH",
        "VIX_BULL_COMPRESS",
        "VIX_LOW_FLAT",
        "VIX_ELEVATED_COMP",
        "VIX_LOW_RISING",
        "VIX_ELEVATED_FLAT",
        "VIX_HIGH",
        "VIX_SPIKE",
    ]

    total_days = sum(len(days) for days in regime_stats.values())

    header = f"{'Regime':<22} {'Days':>5} {'Pct':>6} {'SPY OC%':>10} {'SPY Rng%':>10} {'SPY MaxDD':>10} {'%Above':>8} {'WinRate':>8}"
    print(header)
    print("-" * 90)

    for regime in ordered:
        days = regime_stats.get(regime, [])
        if not days:
            continue
        n = len(days)
        pct = n / total_days * 100 if total_days else 0
        oc_returns = [d["spy_oc_pct"] for d in days]
        ranges = [d["spy_hl_pct"] for d in days]
        max_dds = [d["spy_max_dd_pct"] for d in days]
        pct_aboves = [d["pct_above_open"] for d in days]
        wins = sum(1 for r in oc_returns if r > 0)
        win_rate = wins / n * 100
        avg_oc = mean(oc_returns)
        avg_rng = mean(ranges)
        avg_dd = mean(max_dds)
        avg_above = mean(pct_aboves)

        print(f"{regime:<22} {n:>5} {pct:>5.1f}% {avg_oc:>9.2f}% {avg_rng:>9.2f}% {avg_dd:>9.2f}% {avg_above:>7.1f}% {win_rate:>7.1f}%")


async def main():
    args = sys.argv[1:]
    days = 365
    daily_only = False
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
        elif a == "--daily-only":
            daily_only = True

    print(f"VIX Intraday Regime Backtest")
    print(f"Lookback: {days} days")
    print(f"Low VIX threshold: <{VIX_LOW_THRESHOLD}")
    print(f"Decline threshold: -{VIX_DECLINE_PCT}%")
    print()

    # Daily analysis (always)
    daily_stats = await analyze_daily(days)
    print_regime_report(daily_stats, f"DAILY ANALYSIS — {days} day lookback")

    # Show some concrete recent examples of VIX_BULL_COMPRESS
    bull_days = sorted(daily_stats.get("VIX_BULL_COMPRESS", []),
                       key=lambda d: d["date"], reverse=True)[:10]
    if bull_days:
        print()
        print(f"  Recent VIX_BULL_COMPRESS days (top 10):")
        print(f"  {'Date':<12} {'VIX':>12} {'SPY Move':>12}")
        for d in bull_days:
            vix_str = f"{d['vix_open']:.2f}->{d['vix_close']:.2f}"
            spy_str = f"{d['spy_oc_pct']:+.2f}%"
            print(f"  {d['date']:<12} {vix_str:>14} {spy_str:>12}")

    if not daily_only:
        # Intraday analysis (last 90 days)
        intraday_days = min(days, 90)
        intraday_stats = await analyze_intraday(intraday_days)
        if intraday_stats:
            print_intraday_report(intraday_stats, f"INTRADAY ANALYSIS — 15-min bars, {intraday_days} days")


if __name__ == "__main__":
    asyncio.run(main())
