"""Short-horizon MID-to-MID markout report — the 2026-06-29 4-LLM audit's
adverse-selection / "exhaust" test for INFORMED CLUSTER (and every detector).

Gemini's existential claim was that the cluster ~89% WR is "delayed hedging
exhaust" — i.e. by the time we'd buy, the option mid has already topped and falls
right after. The MID-to-MID markout at +1/+5/+15 min adjudicates it directly:

    median > 0  -> the move is IN FRONT of the flow (the signal LEADS price = real)
    median <= 0 -> the mid falls right after we'd buy (we're buying EXHAUST)

Mid-to-mid (not ask-in) isolates information content from the spread we pay, so
this is the clean signal test; the ask-in opt_mfe/mae columns answer the separate
"is it tradable net of spread?" question.

Run (reads alert_outcomes.db; needs the markout columns populated by the option-
P&L backfill loop or `--backfill`, which needs the ThetaData Terminal):
  python scripts/markout_report.py                 # last 30 days, all detectors
  python scripts/markout_report.py --days 60       # wider window
  python scripts/markout_report.py --type CLUSTER  # isolate the crown jewel
  python scripts/markout_report.py --backfill 30   # fill markout backlog, then report
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_outcomes import (  # noqa: E402
    get_markout_by_type,
    run_option_pnl_backfill,
)


def _fmt(agg: dict) -> str:
    if not agg or agg.get("n", 0) == 0 or agg.get("median") is None:
        return f"{'—':>8} {'—':>8} {'—':>6}"
    return f"{agg['median']:>+8.2f} {agg['mean']:>+8.2f} {agg['pct_pos']:>5.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="lookback window (days)")
    ap.add_argument("--type", dest="alert_type", default=None,
                    help="isolate one alert_type (e.g. CLUSTER)")
    ap.add_argument("--backfill", nargs="?", type=int, const=30, default=None,
                    metavar="DAYS", help="run the option-P&L/markout backfill first "
                    "(needs ThetaData Terminal); optional lookback days (default 30)")
    args = ap.parse_args()

    if args.backfill is not None:
        print(f"[markout] backfilling markout columns, lookback={args.backfill}d "
              "(needs ThetaData Terminal) ...", flush=True)
        stats = asyncio.run(run_option_pnl_backfill(max_age_days=args.backfill))
        print(f"[markout] backfill done: {stats}\n", flush=True)

    rows = get_markout_by_type(days=args.days, alert_type=args.alert_type)
    title = f"MARKOUT - last {args.days}d" + (f"  [{args.alert_type}]" if args.alert_type else "")
    print(title)
    print("=" * len(title))
    if not rows:
        print("\n(no rows with a +5m markout yet — run with --backfill, or wait for "
              "the backfill loop to fill the markout columns)")
        return 0

    # header: each horizon shows median / mean / %positive
    print(f"\n{'detector':<18}{'n':>5}   "
          f"{'+1m  med    mean  pos':>24}   "
          f"{'+5m  med    mean  pos':>24}   "
          f"{'+15m med    mean  pos':>24}   verdict")
    print("-" * 128)
    for r in rows:
        print(f"{r['alert_type']:<18}{r['n']:>5}   "
              f"{_fmt(r['mark_1m'])}   {_fmt(r['mark_5m'])}   {_fmt(r['mark_15m'])}   "
              f"{r['verdict_5m'] or '—'}")

    print("\nverdict = sign of the +5m median markout.  LEADS = signal is in front "
          "of price (real edge).  EXHAUST = mid falls right after entry (Gemini's claim).")
    print("Reminder: this is MID-to-MID (information content). Cross-check the ask-in "
          "opt_mfe/opt_mae columns for tradability net of the spread you actually pay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
