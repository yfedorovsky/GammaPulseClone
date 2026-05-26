"""One-shot script: close all tracked_trades rows older than 1 day.

Context: 2026-05-26 — diagnostic revealed 448,575 ACTIVE trades in DB,
causing the trade_tracker exit-signal loop to iterate all of them every
30s, blocking the asyncio event loop and triggering ThetaData WebSocket
heartbeat timeout + reconnect storm.

Safe to run while backend is live — SQLite WAL handles concurrent reads.
"""
import sqlite3
import time
import sys

DB = "snapshots.db"
STALE_AGE_SECONDS = 86400  # 1 day

now = int(time.time())
cutoff = now - STALE_AGE_SECONDS

c = sqlite3.connect(DB)
try:
    before_active = c.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()[0]

    n_closed = c.execute(
        "UPDATE tracked_trades "
        "SET status = 'CLOSED', closed_ts = ?, close_reason = ? "
        "WHERE status = 'ACTIVE' AND created_ts < ?",
        (now, "AUTO_BULK_GC_2026-05-26", cutoff),
    ).rowcount
    c.commit()

    after_active = c.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()[0]

    print(f"Before: {before_active:,} ACTIVE", file=sys.stderr)
    print(f"Closed: {n_closed:,} stale (>1 day old)", file=sys.stderr)
    print(f"After:  {after_active:,} ACTIVE remaining", file=sys.stderr)
finally:
    c.close()
