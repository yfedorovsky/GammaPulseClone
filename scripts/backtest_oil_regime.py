"""Oil regime backtest — geopolitical risk-off detector.

Hypothesis: Days where USO (WTI crude ETF) spikes intraday (+3% or more)
signal geopolitical risk-off that drags SPY down same-day or next-session.

Conversely, days where USO crashes (-3%+) signal demand destruction that
is bearish for cyclicals but can be mixed for SPY (often neutral to mildly
positive if driven by deflation hopes vs. recession fears).

Why this matters in 2026: Hormuz/Iran/Houthis produce 3-8% oil pops
within hours with no warning. A systematic detector firing at the first
tick gives 30+ min head start on the equity sell-off cascade.

Method:
1. Pull daily OHLC for USO, SPY, XLE (energy ETF), BNO (Brent) for 365 days
2. Classify each day by USO intraday behavior:
   - OIL_CALM:      |change| < 2%
   - OIL_UP_MILD:   +2% to +4%
   - OIL_SPIKE:     +4%+ (geopolitical risk-off)
   - OIL_DOWN_MILD: -2% to -4%
   - OIL_CRASH:     -4%+ (demand destruction)
3. Cross-check: was XLE also strong (validates oil move as real, not just
   ETF distortion)? Was BNO aligned (Brent+WTI both = global, not local)?
4. Measure SPY same-day open-to-close AND next-session behavior
5. Output regime → market-reaction matrix

Usage:
    python -m scripts.backtest_oil_regime
    python -m scripts.backtest_oil_regime --days 730  # 2yr lookback
"""
from __future__ import annotations

import asyncio
import datetime
import os
import sys
from collections import defaultdict
from statistics import mean, stdev

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.tradier import TradierClient


# ── Thresholds ────────────────────────────────────────────────────────

OIL_SPIKE_PCT = 4.0          # USO +4%+ = geopolitical spike
OIL_UP_MILD_PCT = 2.0        # USO +2-4% = elevated, watch
OIL_CRASH_PCT = -4.0         # USO -4%+ = demand destruction
OIL_DOWN_MILD_PCT = -2.0     # USO -2-4% = bearish but not crisis


def classify_oil_day(uso_open: float, uso_close: float) -> str:
    """Classify a single day's USO behavior."""
    pct = (uso_close - uso_open) / uso_open * 100 if uso_open else 0

    if pct >= OIL_SPIKE_PCT:
        return "OIL_SPIKE"
    elif pct >= OIL_UP_MILD_PCT:
        return "OIL_UP_MILD"
    elif pct <= OIL_CRASH_PCT:
        return "OIL_CRASH"
    elif pct <= OIL_DOWN_MILD_PCT:
        return "OIL_DOWN_MILD"
    else:
        return "OIL_CALM"


async def pull_daily(tradier: TradierClient, symbol: str, start: str, end: str):
    bars = await tradier.history(symbol, interval="daily", start=start, end=end)
    return {b["time"]: b for b in bars}


async def analyze(days: int = 365) -> tuple[dict, dict]:
    """Pull daily USO, SPY, XLE, BNO. Classify, measure reactions.

    Returns (regime_stats, bno_confirm_stats).
    """
    tradier = TradierClient()
    try:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        start_str = start.isoformat()
        end_str = end.isoformat()

        print(f"[OIL] Pulling USO, SPY, XLE, BNO from {start_str} to {end_str}...")
        uso = await pull_daily(tradier, "USO", start_str, end_str)
        spy = await pull_daily(tradier, "SPY", start_str, end_str)
        xle = await pull_daily(tradier, "XLE", start_str, end_str)
        bno = await pull_daily(tradier, "BNO", start_str, end_str)
    finally:
        await tradier.close()

    print(f"[OIL] Got: USO={len(uso)} SPY={len(spy)} XLE={len(xle)} BNO={len(bno)} bars")

    # Sort dates chronologically for next-day lookup
    all_dates = sorted(set(uso.keys()) & set(spy.keys()))
    regime_stats: dict[str, list[dict]] = defaultdict(list)

    for i, date in enumerate(all_dates):
        u = uso[date]
        s = spy[date]
        x = xle.get(date)
        b = bno.get(date)

        regime = classify_oil_day(u["open"], u["close"])
        uso_pct = (u["close"] - u["open"]) / u["open"] * 100 if u["open"] else 0
        spy_oc_pct = (s["close"] - s["open"]) / s["open"] * 100 if s["open"] else 0
        spy_hl_pct = (s["high"] - s["low"]) / s["open"] * 100 if s["open"] else 0

        # XLE confirm — was energy sector actually green on oil spikes?
        xle_oc_pct = (x["close"] - x["open"]) / x["open"] * 100 if (x and x["open"]) else None
        bno_oc_pct = (b["close"] - b["open"]) / b["open"] * 100 if (b and b["open"]) else None

        # Next session SPY behavior
        next_spy_oc = None
        next_spy_gap = None
        if i + 1 < len(all_dates):
            next_date = all_dates[i + 1]
            ns = spy.get(next_date)
            if ns and ns["open"]:
                next_spy_oc = (ns["close"] - ns["open"]) / ns["open"] * 100
                next_spy_gap = (ns["open"] - s["close"]) / s["close"] * 100

        regime_stats[regime].append({
            "date": date,
            "uso_open": u["open"],
            "uso_close": u["close"],
            "uso_pct": uso_pct,
            "spy_oc_pct": spy_oc_pct,
            "spy_hl_pct": spy_hl_pct,
            "xle_oc_pct": xle_oc_pct,
            "bno_oc_pct": bno_oc_pct,
            "next_spy_oc": next_spy_oc,
            "next_spy_gap": next_spy_gap,
        })

    return regime_stats


def print_regime_report(regime_stats: dict, days: int) -> None:
    print()
    print("=" * 98)
    print(f"  OIL REGIME ANALYSIS — {days} day lookback")
    print("=" * 98)

    ordered = ["OIL_SPIKE", "OIL_UP_MILD", "OIL_CALM", "OIL_DOWN_MILD", "OIL_CRASH"]
    total = sum(len(d) for d in regime_stats.values())

    print(f"{'Regime':<18} {'Days':>5} {'%':>5} {'USO Avg%':>9} "
          f"{'SPY OC%':>9} {'SPY Rng%':>9} {'WinRate':>8} {'Next OC%':>9} {'Next Gap%':>10}")
    print("-" * 98)

    for regime in ordered:
        days_list = regime_stats.get(regime, [])
        if not days_list:
            continue
        n = len(days_list)
        pct_of_total = n / total * 100 if total else 0
        uso_avg = mean(d["uso_pct"] for d in days_list)
        spy_oc = [d["spy_oc_pct"] for d in days_list]
        spy_rng = mean(d["spy_hl_pct"] for d in days_list)
        wins = sum(1 for r in spy_oc if r > 0)
        win_rate = wins / n * 100
        avg_oc = mean(spy_oc)

        next_ocs = [d["next_spy_oc"] for d in days_list if d["next_spy_oc"] is not None]
        next_gaps = [d["next_spy_gap"] for d in days_list if d["next_spy_gap"] is not None]
        avg_next_oc = mean(next_ocs) if next_ocs else 0
        avg_next_gap = mean(next_gaps) if next_gaps else 0

        print(f"{regime:<18} {n:>5} {pct_of_total:>4.1f}% {uso_avg:>+8.2f}% "
              f"{avg_oc:>+8.2f}% {spy_rng:>8.2f}% {win_rate:>7.1f}% "
              f"{avg_next_oc:>+8.2f}% {avg_next_gap:>+9.2f}%")

    # Focus comparison: OIL_SPIKE vs OIL_CALM baseline
    print()
    spike = regime_stats.get("OIL_SPIKE", [])
    calm = regime_stats.get("OIL_CALM", [])
    if spike and calm:
        spike_wr = sum(1 for d in spike if d["spy_oc_pct"] > 0) / len(spike) * 100
        calm_wr = sum(1 for d in calm if d["spy_oc_pct"] > 0) / len(calm) * 100
        spike_oc = mean([d["spy_oc_pct"] for d in spike])
        calm_oc = mean([d["spy_oc_pct"] for d in calm])

        spike_next = [d["next_spy_oc"] for d in spike if d["next_spy_oc"] is not None]
        calm_next = [d["next_spy_oc"] for d in calm if d["next_spy_oc"] is not None]
        spike_next_avg = mean(spike_next) if spike_next else 0
        calm_next_avg = mean(calm_next) if calm_next else 0

        print(f"  >> OIL_SPIKE vs OIL_CALM:")
        print(f"     Same-day SPY OC:  {spike_oc:+.2f}% (vs {calm_oc:+.2f}% calm, delta {spike_oc - calm_oc:+.2f}pp)")
        print(f"     Same-day WR:      {spike_wr:.1f}%   (vs {calm_wr:.1f}% calm, delta {spike_wr - calm_wr:+.1f}pp)")
        print(f"     Next-day SPY OC:  {spike_next_avg:+.2f}% (vs {calm_next_avg:+.2f}% calm, delta {spike_next_avg - calm_next_avg:+.2f}pp)")


def print_recent_spikes(regime_stats: dict) -> None:
    """Show recent OIL_SPIKE days with full context."""
    spikes = sorted(regime_stats.get("OIL_SPIKE", []), key=lambda d: d["date"], reverse=True)[:15]
    if not spikes:
        print()
        print("  No OIL_SPIKE days in lookback window.")
        return

    print()
    print("  Recent OIL_SPIKE days (USO +4%+ intraday):")
    print(f"  {'Date':<12} {'USO':>9} {'XLE':>9} {'BNO':>9} {'SPY OC':>9} {'SPY Next':>10}")
    for d in spikes:
        uso_str = f"{d['uso_pct']:+.2f}%"
        xle_str = f"{d['xle_oc_pct']:+.2f}%" if d.get('xle_oc_pct') is not None else "   -"
        bno_str = f"{d['bno_oc_pct']:+.2f}%" if d.get('bno_oc_pct') is not None else "   -"
        spy_str = f"{d['spy_oc_pct']:+.2f}%"
        next_str = f"{d['next_spy_oc']:+.2f}%" if d.get('next_spy_oc') is not None else "   -"
        print(f"  {d['date']:<12} {uso_str:>9} {xle_str:>9} {bno_str:>9} {spy_str:>9} {next_str:>10}")


def print_crash_days(regime_stats: dict) -> None:
    """Show recent OIL_CRASH days (demand destruction)."""
    crashes = sorted(regime_stats.get("OIL_CRASH", []), key=lambda d: d["date"], reverse=True)[:10]
    if not crashes:
        return

    print()
    print("  Recent OIL_CRASH days (USO -4%+ intraday):")
    print(f"  {'Date':<12} {'USO':>9} {'XLE':>9} {'SPY OC':>9} {'SPY Next':>10}")
    for d in crashes:
        uso_str = f"{d['uso_pct']:+.2f}%"
        xle_str = f"{d['xle_oc_pct']:+.2f}%" if d.get('xle_oc_pct') is not None else "   -"
        spy_str = f"{d['spy_oc_pct']:+.2f}%"
        next_str = f"{d['next_spy_oc']:+.2f}%" if d.get('next_spy_oc') is not None else "   -"
        print(f"  {d['date']:<12} {uso_str:>9} {xle_str:>9} {spy_str:>9} {next_str:>10}")


async def main():
    days = 365
    for i, a in enumerate(sys.argv[1:]):
        if a == "--days" and i + 1 < len(sys.argv[1:]):
            days = int(sys.argv[1:][i + 1])

    print(f"Oil Regime Backtest")
    print(f"Lookback: {days} days")
    print(f"Spike threshold: +{OIL_SPIKE_PCT}% USO intraday")
    print(f"Crash threshold: {OIL_CRASH_PCT}% USO intraday")

    regime_stats = await analyze(days)
    print_regime_report(regime_stats, days)
    print_recent_spikes(regime_stats)
    print_crash_days(regime_stats)


if __name__ == "__main__":
    asyncio.run(main())
