"""Backtest the triple confluence detector against historical data.

Replays the detector against snapshots over a window and reports every
confluence that would have fired. Used to:
  (a) verify the MRVL 5/28 setup fires (regression test for our case study)
  (b) measure how many confluences fire per day in production
  (c) cross-check against forward returns to estimate hit rate

Usage:
    python scripts/backtest_triple_confluence.py
    python scripts/backtest_triple_confluence.py --start 2026-05-28 --end 2026-06-02
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent so we can import server modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.triple_confluence import detect_confluences  # noqa: E402


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-28", help="YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--step-minutes", type=int, default=60,
                    help="how often to re-evaluate (minutes)")
    args = ap.parse_args()

    start = _parse_iso(args.start)
    end = _parse_iso(args.end) if args.end else datetime.now()

    print(f"=== Triple Confluence Backtest ===")
    print(f"Window: {start.isoformat()} -> {end.isoformat()}")
    print(f"Step: every {args.step_minutes} min")
    print()

    # Walk forward at each step, calling detect_confluences with that
    # timestamp as the "now". The detector looks back 4 hours from now_ts.
    fired_seen: set[tuple[str, str, str]] = set()  # (ticker, dir, date)
    total_unique = 0
    timeline = []

    cur = start
    while cur <= end:
        now_ts = int(cur.timestamp())
        try:
            results = detect_confluences(now_ts=now_ts)
        except Exception as e:
            print(f"  [{cur.strftime('%m-%d %H:%M')}] err: {e!r}")
            cur += timedelta(minutes=args.step_minutes)
            continue
        for r in results:
            key = (r["ticker"], r["direction"], cur.date().isoformat())
            if key in fired_seen:
                continue
            fired_seen.add(key)
            total_unique += 1
            timeline.append({
                "first_seen_ts": cur,
                "ticker": r["ticker"],
                "direction": r["direction"],
                "flow": r["flow_strike_count"],
                "soe_aplus": r["soe_aplus_count"],
                "soe_a": r["soe_a_count"],
                "kmig": len(r["kingmig_events"]),
            })
        cur += timedelta(minutes=args.step_minutes)

    print(f"Total unique (ticker, direction, day) confluences: {total_unique}")
    print()
    print("Timeline of first-fire moments:")
    print(f"{'first_seen':<18} {'tkr':<6} {'dir':<5} {'fstk':>4} {'A+':>3} {'A':>3} {'km':>3}")
    print("-" * 55)
    for t in timeline:
        ts_str = t["first_seen_ts"].strftime("%m-%d %H:%M ET")
        print(
            f"{ts_str:<18} {t['ticker']:<6} {t['direction']:<5} "
            f"{t['flow']:>4} {t['soe_aplus']:>3} {t['soe_a']:>3} {t['kmig']:>3}"
        )

    # Specific MRVL check
    mrvl_fires = [t for t in timeline if t["ticker"] == "MRVL"]
    print()
    print("=== MRVL regression check (case study) ===")
    if mrvl_fires:
        for f in mrvl_fires:
            print(
                f"  MRVL {f['direction']} first fired "
                f"{f['first_seen_ts'].strftime('%m-%d %H:%M ET')} "
                f"(strikes={f['flow']} A+={f['soe_aplus']} A={f['soe_a']} kmig={f['kmig']})"
            )
    else:
        print("  NO MRVL confluence fired in window — detector may be too tight")
    return 0


if __name__ == "__main__":
    sys.exit(main())
