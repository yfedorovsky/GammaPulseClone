"""Close ALL active tracked_trades — full queue reset.

Rationale: every flow alert auto-creates a tracked trade
(flow_alerts.py:795). With 2,000+ alerts per cycle, the table grew to
448K active rows, blocking the trade_tracker exit-signal loop. After
the >24h GC pass we still had 22K active, all from today's flow alerts
— overwhelmingly noise.

This script closes them all. Safe because:
  - These weren't real positions, just auto-tracked flow alerts
  - The fix to flow_alerts.py (only track HIGH conviction) will prevent
    re-accumulation
"""
import sqlite3
import time
import sys

DB = "snapshots.db"
now = int(time.time())

c = sqlite3.connect(DB)
try:
    before = c.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()[0]

    n_closed = c.execute(
        "UPDATE tracked_trades "
        "SET status = 'CLOSED', closed_ts = ?, close_reason = ? "
        "WHERE status = 'ACTIVE'",
        (now, "AUTO_FULL_RESET_2026-05-26"),
    ).rowcount
    c.commit()

    after = c.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()[0]

    print(f"Before: {before:,} ACTIVE", file=sys.stderr)
    print(f"Closed: {n_closed:,}", file=sys.stderr)
    print(f"After:  {after:,} ACTIVE remaining", file=sys.stderr)
finally:
    c.close()
