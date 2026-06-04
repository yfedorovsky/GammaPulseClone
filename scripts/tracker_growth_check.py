"""Quick tracker growth-rate check.

Compares tracker ACTIVE count to creation rate over last 60min.
Used to validate the conviction filter / index-ETF exclusion fix.

Healthy: <500 active, <10/min creation rate
Warning: 500-2000 active, 10-20/min
Runaway: >2000 active or >20/min sustained

Usage:
    python scripts/tracker_growth_check.py
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime


def main() -> int:
    conn = sqlite3.connect("snapshots.db", timeout=5)
    now = int(time.time())

    print(f"\n[TRACKER] @ {datetime.now().strftime('%H:%M:%S ET')}")
    print("-" * 55)

    r = conn.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()
    active = r[0] if r else 0

    # Creation rate over multiple windows
    rates = {}
    for label, sec in [("1min", 60), ("5min", 300), ("15min", 900), ("1hr", 3600)]:
        r = conn.execute(
            "SELECT COUNT(*) FROM tracked_trades WHERE created_ts >= ?",
            (now - sec,),
        ).fetchone()
        n = r[0] if r else 0
        per_min = n / (sec / 60)
        rates[label] = (n, per_min)

    # Index ETF carve-out check — confirm fix is working
    index_tickers = ("SPY", "SPX", "SPXW", "QQQ", "IWM", "DIA", "VIX", "NDX")
    placeholders = ",".join("?" * len(index_tickers))
    r = conn.execute(
        f"SELECT COUNT(*) FROM tracked_trades "
        f"WHERE created_ts >= ? AND ticker IN ({placeholders})",
        (now - 3600, *index_tickers),
    ).fetchone()
    index_recent = r[0] if r else 0

    print(f"  ACTIVE total:           {active:,}")
    print()
    for label, (n, per_min) in rates.items():
        print(f"  Last {label:<6} created: {n:>5,}  ({per_min:>5.1f}/min)")
    print()
    print(f"  Last 1hr index ETF:     {index_recent:>5,}  "
          f"(should be near 0 with fix)")

    # Verdict
    print("-" * 55)
    rate_1hr = rates["1hr"][1]
    if active >= 2000 or rate_1hr >= 20:
        print(f"  STATUS: RUNAWAY — fix not working or already drifted")
        result = 1
    elif active >= 500 or rate_1hr >= 10:
        print(f"  STATUS: ELEVATED — watch trend")
        result = 0
    else:
        print(f"  STATUS: HEALTHY")
        result = 0

    conn.close()
    return result


if __name__ == "__main__":
    import sys
    sys.exit(main())
