"""Analogues base-rate scanner CLI (task #55).

Loads free daily OHLC for an index/ETF, runs server/analogues.py, and prints
which technical patterns are firing right now plus each one's historical
forward-return distribution ("this fired N times; here's what happened next").

Data sources (tried in order):
  1. Stooq CSV  (stdlib only, long history — ^spx/^ndx back to the 80s)
  2. yfinance   (if installed)
  3. --csv PATH (local Date,Open,High,Low,Close[,Volume] file)

Usage:
  python scripts/analogue_scan.py SPX
  python scripts/analogue_scan.py NDX --horizon-sort 20
  python scripts/analogue_scan.py SPY --csv data/spy.csv

Pairs with flow: a rare bullish pattern (e.g. Zweig RSI thrust) firing the
same day as informed call flow is a higher-conviction setup than either alone.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.analogues import scan, PATTERNS  # noqa: E402
from server.analogue_data import load_bars  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Analogues base-rate scanner")
    ap.add_argument("symbol", nargs="?", default="SPX",
                    help="SPX/NDX/SPY/QQQ/DJI/RUT/IWM/VIX or a Stooq symbol")
    ap.add_argument("--csv", help="local OHLC CSV (Date,Open,High,Low,Close[,Volume])")
    ap.add_argument("--horizon-sort", type=int, default=0,
                    help="if set (5/10/20), sort active patterns by that horizon's mean")
    args = ap.parse_args()

    # Windows consoles default to cp1252; our box/bullet glyphs need UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    bars, source = load_bars(args.symbol, args.csv)
    res = scan(bars)

    print(f"\n{'='*70}")
    print(f"  ANALOGUES — {args.symbol.upper()}   [{source}]   "
          f"{res['bars']} bars, as of {res['as_of']}")
    print(f"  {res['active_count']} pattern(s) firing on the latest bar")
    print(f"{'='*70}")

    active = res["active"]
    if args.horizon_sort in (5, 10, 20):
        active = sorted(
            active,
            key=lambda a: (a["forward"].get(args.horizon_sort, {}).get("mean_pct") or -999),
            reverse=True,
        )

    for a in active:
        bias = a["bias"].upper()
        print(f"\n▸ {a['pattern']}  [{bias}]   "
              f"{a['occurrences']} prior occurrences   last: {a['last_occurrence']}")
        hdr = f"    {'horizon':>8} {'n':>5} {'mean%':>8} {'median%':>8} {'hit%':>6}"
        print(hdr)
        for h in (5, 10, 20):
            f = a["forward"].get(h, {})
            if f.get("n"):
                print(f"    {('+' + str(h) + 'd'):>8} {f['n']:>5} "
                      f"{f['mean_pct']:>8} {f['median_pct']:>8} {f['hit_rate']:>6}")
            else:
                print(f"    {('+' + str(h) + 'd'):>8} {'—':>5}")

    if not active:
        print("\n  No patterns active today (calm/typical tape).")
    print(f"\n  ({len(PATTERNS)} patterns in registry)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
