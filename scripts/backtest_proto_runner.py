"""60-day backtest of the PROTO_RUNNER signature across TIER_1 + RECLAIM_EXTRA.

The question this answers: if we ran the PROTO_RUNNER detection every EOD for
the last 60 trading sessions, what fraction of detections would have been
followed by a real +3% day on rising volume within 5 sessions (= "promoted")?

Interpretation guide:
  hit_rate < 30%  → kill the signature, too noisy
  hit_rate 30-40% → keep in observation mode, collect more data
  hit_rate > 40%  → promote to alert / proto-DAY1 in next version
  hit_rate > 55%  → consider wiring into paper trading with size penalty

Run:
    python -m scripts.backtest_proto_runner
    python -m scripts.backtest_proto_runner --days 120
    python -m scripts.backtest_proto_runner --tickers AMD NVDA MRVL
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.runner_tracker import (
    RECLAIM_EXTRA_TICKERS, _detect_proto_signature,
)
from server.tradier import TradierClient


# Promotion window: how many trading sessions after detection do we allow
# for follow-through before calling it FADED.
PROMOTION_WINDOW_SESSIONS = 5

# Minimum follow-through to count as "real runner":
#   - single session ≥ +3% close-to-close
#   - OR cumulative +5% across the window
#   - AND that day has RVOL ≥ 1.1x (volume expansion — the signature we waited for)
PROMOTION_DAY_GAIN_MIN = 3.0
PROMOTION_CUM_GAIN_MIN = 5.0
PROMOTION_RVOL_MIN = 1.1


def evaluate_promotion(bars: list[dict], detection_idx: int, avg_vol: float) -> dict:
    """Given bars and a detection at index `detection_idx`, look forward
    `PROMOTION_WINDOW_SESSIONS` sessions and classify the outcome.

    Returns {outcome: PROMOTED|FADED|EXPIRED|PENDING, day_offset: N,
             peak_gain_pct: X, promoted_by: DAY_GAIN|CUM_GAIN|None}
    """
    detection_close = bars[detection_idx]["close"]
    cum_gain = 0.0
    peak_gain = 0.0
    end = min(len(bars), detection_idx + 1 + PROMOTION_WINDOW_SESSIONS)

    for i in range(detection_idx + 1, end):
        b = bars[i]
        day_gain = (b["close"] - bars[i - 1]["close"]) / bars[i - 1]["close"] * 100
        cum_total = (b["close"] - detection_close) / detection_close * 100
        peak_gain = max(peak_gain, cum_total)
        cum_gain = cum_total
        rvol = b["volume"] / avg_vol if avg_vol > 0 else 0

        if day_gain >= PROMOTION_DAY_GAIN_MIN and rvol >= PROMOTION_RVOL_MIN:
            return {
                "outcome": "PROMOTED",
                "day_offset": i - detection_idx,
                "promoted_by": "DAY_GAIN",
                "trigger_gain_pct": round(day_gain, 2),
                "trigger_rvol": round(rvol, 2),
                "peak_gain_pct": round(peak_gain, 2),
                "cum_gain_pct": round(cum_total, 2),
            }
        if cum_total >= PROMOTION_CUM_GAIN_MIN and rvol >= PROMOTION_RVOL_MIN:
            return {
                "outcome": "PROMOTED",
                "day_offset": i - detection_idx,
                "promoted_by": "CUM_GAIN",
                "trigger_gain_pct": round(cum_total, 2),
                "trigger_rvol": round(rvol, 2),
                "peak_gain_pct": round(peak_gain, 2),
                "cum_gain_pct": round(cum_total, 2),
            }

    if end - (detection_idx + 1) < PROMOTION_WINDOW_SESSIONS:
        return {
            "outcome": "PENDING",
            "day_offset": None,
            "promoted_by": None,
            "peak_gain_pct": round(peak_gain, 2),
            "cum_gain_pct": round(cum_gain, 2),
        }
    return {
        "outcome": "FADED",
        "day_offset": PROMOTION_WINDOW_SESSIONS,
        "promoted_by": None,
        "peak_gain_pct": round(peak_gain, 2),
        "cum_gain_pct": round(cum_gain, 2),
    }


async def backtest_ticker(tc: TradierClient, ticker: str, start: str, end: str) -> list[dict]:
    """Scan a single ticker's history for PROTO_RUNNER signatures, evaluating
    each one's forward outcome. Returns a list of result dicts."""
    bars = await tc.history(ticker, interval="daily", start=start, end=end)
    if len(bars) < 50:
        return []

    results = []
    # Start iterating once we have enough history for avg_vol + EMA21 + window
    for i in range(30, len(bars)):
        # Compute avg_vol from 20 sessions prior to the window
        window_start = max(0, i - 3)
        pre = bars[max(0, window_start - 20):window_start]
        if len(pre) < 10:
            continue
        avg_vol = sum(b["volume"] for b in pre) / len(pre)
        if avg_vol <= 0:
            continue

        sig = _detect_proto_signature(bars[: i + 1], lookback_idx=i)
        if not sig:
            continue

        outcome_data = evaluate_promotion(bars, i, avg_vol)
        results.append({
            "ticker": ticker,
            "detection_date": bars[i]["time"],
            "detection_close": bars[i]["close"],
            "window_days": sig["window_days"],
            "total_gain_pct": sig["total_gain_pct"],
            "close_pcts": sig["close_pcts"],
            "rvols": sig["rvols"],
            "gains": sig["gains"],
            "ema21_dist_pct": sig["ema21_dist_pct"],
            "sma20_slope_pct": sig["sma20_slope_pct"],
            **outcome_data,
        })
    return results


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=60, help="calendar days lookback")
    p.add_argument("--tickers", nargs="+", help="override universe with specific tickers")
    args = p.parse_args()

    try:
        from server.tickers import TIER_1
    except ImportError:
        TIER_1 = []

    if args.tickers:
        universe = sorted(set(args.tickers))
    else:
        universe = sorted(set(TIER_1) | RECLAIM_EXTRA_TICKERS)

    end = datetime.date.today()
    # Add buffer for the forward promotion window + lookback for EMA/avg-vol
    start = (end - datetime.timedelta(days=args.days + 60)).isoformat()
    end_iso = end.isoformat()

    print("=" * 78)
    print(f"PROTO_RUNNER backtest — {len(universe)} tickers, {args.days}d lookback")
    print(f"Window: {start} to {end_iso}")
    print(f"Promotion: +{PROMOTION_DAY_GAIN_MIN}% day OR +{PROMOTION_CUM_GAIN_MIN}% cum  "
          f"on RVOL ≥ {PROMOTION_RVOL_MIN}x  within {PROMOTION_WINDOW_SESSIONS} sessions")
    print("=" * 78)
    print()

    tc = TradierClient()
    all_results: list[dict] = []
    errors = 0
    try:
        for i, ticker in enumerate(universe, 1):
            try:
                results = await backtest_ticker(tc, ticker, start, end_iso)
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  [{ticker}] error: {e}")
                continue
            if results:
                # Only keep detections within the requested lookback (exclude buffer)
                cutoff = (end - datetime.timedelta(days=args.days)).isoformat()
                results = [r for r in results if r["detection_date"] >= cutoff]
                all_results.extend(results)
                promoted = sum(1 for r in results if r["outcome"] == "PROMOTED")
                faded = sum(1 for r in results if r["outcome"] == "FADED")
                pending = sum(1 for r in results if r["outcome"] == "PENDING")
                print(f"  [{i:3}/{len(universe)}] {ticker:6s}: {len(results)} detections "
                      f"(P={promoted} F={faded} Pend={pending})")
    finally:
        await tc.close()

    if not all_results:
        print("\nNo detections in backtest window.")
        return

    # ── Summary ────────────────────────────────────────────────────────
    total = len(all_results)
    outcomes = Counter(r["outcome"] for r in all_results)
    resolved = outcomes["PROMOTED"] + outcomes["FADED"]
    hit_rate = outcomes["PROMOTED"] / resolved * 100 if resolved > 0 else 0

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"Total detections: {total}")
    print(f"  PROMOTED: {outcomes['PROMOTED']:4d} ({outcomes['PROMOTED']/total*100:.1f}%)")
    print(f"  FADED:    {outcomes['FADED']:4d} ({outcomes['FADED']/total*100:.1f}%)")
    print(f"  PENDING:  {outcomes['PENDING']:4d} ({outcomes['PENDING']/total*100:.1f}%)")
    print(f"Resolved:  {resolved}  →  HIT RATE: {hit_rate:.1f}%")

    # Baseline: what's the raw probability of a +3% day on RVOL>=1.1x within 5 sessions
    # for a random day in the universe? (we need this to know if detection adds value)
    # For now we just print the signature-gated rate; baseline can be computed in v2.

    # Breakdown by window_days
    print()
    print("By detection window:")
    for w in sorted(set(r["window_days"] for r in all_results)):
        sub = [r for r in all_results if r["window_days"] == w]
        s_promoted = sum(1 for r in sub if r["outcome"] == "PROMOTED")
        s_resolved = sum(1 for r in sub if r["outcome"] in ("PROMOTED", "FADED"))
        rate = s_promoted / s_resolved * 100 if s_resolved > 0 else 0
        print(f"  {w}d grind: {len(sub)} total  |  {s_promoted}/{s_resolved} promoted ({rate:.1f}%)")

    # Breakdown by total_gain_pct tier
    print()
    print("By grind strength (total gain across window):")
    tiers = [("< 2%", 0, 2), ("2-4%", 2, 4), ("4-6%", 4, 6), ("6%+", 6, 999)]
    for label, lo, hi in tiers:
        sub = [r for r in all_results if lo <= r["total_gain_pct"] < hi]
        if not sub:
            continue
        s_promoted = sum(1 for r in sub if r["outcome"] == "PROMOTED")
        s_resolved = sum(1 for r in sub if r["outcome"] in ("PROMOTED", "FADED"))
        rate = s_promoted / s_resolved * 100 if s_resolved > 0 else 0
        print(f"  {label:>6}: {len(sub):3d} total  |  {s_promoted}/{s_resolved} promoted ({rate:.1f}%)")

    # Promoted — average peak gain and days to trigger
    promoted_rows = [r for r in all_results if r["outcome"] == "PROMOTED"]
    if promoted_rows:
        avg_offset = sum(r["day_offset"] for r in promoted_rows) / len(promoted_rows)
        avg_peak = sum(r["peak_gain_pct"] for r in promoted_rows) / len(promoted_rows)
        max_peak = max(r["peak_gain_pct"] for r in promoted_rows)
        print()
        print("Promoted detections — follow-through stats:")
        print(f"  avg days to promotion: {avg_offset:.1f}")
        print(f"  avg peak gain:         +{avg_peak:.2f}%")
        print(f"  max peak gain:         +{max_peak:.2f}%")

    # Faded — what did they do?
    faded_rows = [r for r in all_results if r["outcome"] == "FADED"]
    if faded_rows:
        avg_peak_f = sum(r["peak_gain_pct"] for r in faded_rows) / len(faded_rows)
        avg_cum_f = sum(r["cum_gain_pct"] for r in faded_rows) / len(faded_rows)
        print()
        print("Faded detections — what happened instead:")
        print(f"  avg peak gain:     +{avg_peak_f:.2f}%")
        print(f"  avg 5-day cum:     {avg_cum_f:+.2f}%")

    # Top 10 ticker hit rates
    print()
    print("Top detections by ticker (only tickers with ≥2 resolved):")
    by_ticker: dict[str, list[dict]] = {}
    for r in all_results:
        by_ticker.setdefault(r["ticker"], []).append(r)
    ticker_stats = []
    for t, rows in by_ticker.items():
        t_promoted = sum(1 for r in rows if r["outcome"] == "PROMOTED")
        t_resolved = sum(1 for r in rows if r["outcome"] in ("PROMOTED", "FADED"))
        if t_resolved >= 2:
            rate = t_promoted / t_resolved * 100
            ticker_stats.append((t, len(rows), t_promoted, t_resolved, rate))
    for t, tot, prm, res, rate in sorted(ticker_stats, key=lambda x: -x[4])[:15]:
        print(f"  {t:6s}: {tot:2d} detections  |  {prm}/{res} promoted ({rate:.1f}%)")

    # ── Decision framework ─────────────────────────────────────────────
    # Note: `resolved` was the total across all tickers (computed up top).
    # Do NOT overwrite it in the per-ticker loop above.
    print()
    print("=" * 78)
    print("DECISION")
    print("=" * 78)
    if resolved < 20:
        print(f"INSUFFICIENT DATA ({resolved} resolved) — widen window or wait for more")
    elif hit_rate < 30:
        print(f"KILL: {hit_rate:.1f}% < 30% — signature does not outperform noise")
    elif hit_rate < 40:
        print(f"KEEP OBSERVING: {hit_rate:.1f}% in 30-40% band — continue logging, no promotion")
    elif hit_rate < 55:
        print(f"PROMOTE TO ALERTS: {hit_rate:.1f}% > 40% — ship Telegram alerts + UI badge")
    else:
        print(f"STRONG SIGNAL: {hit_rate:.1f}% > 55% — consider paper-trade wiring with size penalty")


if __name__ == "__main__":
    asyncio.run(main())
