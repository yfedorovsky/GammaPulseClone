"""Re-runnable validation for the sector ROTATION alert (#123).

Replays server/sector_rotation_alert across recent trading days from snapshots.db
and reports the firing rate + per-pair breakdown — so you can confirm it isn't
spamming once live data accrues, or recalibrate the gates if it is. READ-ONLY.

Usage:
    python scripts/rotation_validation.py [--days 22] [--db PATH] [--leaderboard]

A healthy rate is a handful of fires across ~20 sessions (genuine rotations,
once/day max). >50% of sessions firing = the gates are too loose; raise
GAP_MIN_PCT or tighten breadth / SPY-separation in sector_rotation_alert.py.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")  # render the leaderboard emoji
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server import sector_rotation_alert as R          # noqa: E402
from server.industry import INDUSTRY_GROUPS            # noqa: E402


def trading_days(db: str, n: int) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT date(ts,'unixepoch','localtime') d FROM snapshots "
            "WHERE ticker='SPY' ORDER BY d DESC LIMIT ?", (n,)).fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=22, help="trading sessions to replay")
    ap.add_argument("--db", default=os.environ.get(
        "SNAPSHOTS_DB_PATH", r"C:\Dev\GammaPulse\snapshots.db"))
    ap.add_argument("--leaderboard", action="store_true",
                    help="print the full Telegram leaderboard for each fire")
    args = ap.parse_args()

    days = trading_days(args.db, args.days)
    if not days:
        print("No trading days found in snapshots.db"); return 1
    print(f"Sector ROTATION validation — {len(days)} sessions "
          f"({days[0]}..{days[-1]})\n")

    fires = 0
    pairs: Counter = Counter()
    for d in days:
        R.reset()
        rets = R.returns_from_prev_close(d, db=args.db)
        if not rets:
            print(f"  {d}: (no data)"); continue
        spy = rets.get("SPY", 0.0)
        stats = R.sector_table(rets, INDUSTRY_GROUPS)
        ev = R.find_rotation(stats, spy)
        if not ev:
            print(f"  {d}:  -")
            continue
        fires += 1
        pairs[(ev["green"], ev["red"])] += 1
        ld = (ev.get("leader") or {}).get("ticker", "-")
        print(f"  {d}:  FIRE  {ev['green']} {ev['green_mean']:+.1f}% vs "
              f"{ev['red']} {ev['red_mean']:+.1f}%  gap {ev['gap']:+.1f}  "
              f"SPY {ev['spy']:+.1f}  leader={ld}")
        if args.leaderboard:
            ev["leaderboard"] = R.leaderboard(stats, spy, etf_ret=rets)
            for line in R.format_rotation(ev).splitlines():
                print("        " + line)

    rate = 100 * fires / len(days)
    print(f"\n=== {fires} fires / {len(days)} sessions = {rate:.0f}% ===")
    if pairs:
        print("Pairs fired (bid sector <- dumped sector):")
        for (g, r), c in pairs.most_common():
            print(f"  {c}x  {g}  <-  {r}")
    if rate > 50:
        print("\n** WARNING: firing on >50% of sessions — gates too loose. "
              "Raise GAP_MIN_PCT or tighten breadth / SPY-separation. **")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
