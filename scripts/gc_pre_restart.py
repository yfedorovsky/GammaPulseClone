"""Pre-restart cleanup script.

Run this BEFORE every backend restart to prevent the tracked_trades runaway
(documented in session_may26_runaway_trades_root_cause.md). Closes stale
ACTIVE tracked_trades, deletes old trade_signals, and truncates the WAL.

Usage:
    python scripts/gc_pre_restart.py

Safe to run during trading hours — uses short timeouts and does not touch
anything fresh (<24h old). Logs row counts so you can verify the cleanup
worked before bringing the backend back up.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime


DB_PATH = "snapshots.db"
STALE_THRESHOLD_S = 24 * 3600  # 1 day


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"[ERR] {DB_PATH} not found — run from C:/Dev/GammaPulse")
        return 1

    db_size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"[GC] DB pre-cleanup: {db_size_mb:.1f} MB")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    cutoff_ts = int(time.time()) - STALE_THRESHOLD_S

    # 1. Close stale ACTIVE tracked_trades
    #    Schema: created_ts (epoch int), close_reason (text), closed_ts (int)
    try:
        cur = conn.execute(
            "UPDATE tracked_trades SET status = 'CLOSED', "
            "close_reason = 'GC_PRE_RESTART', "
            "closed_ts = ? "
            "WHERE status = 'ACTIVE' AND created_ts < ?",
            (int(time.time()), cutoff_ts),
        )
        n_closed = cur.rowcount
        conn.commit()
        print(f"[GC] Closed {n_closed:,} stale ACTIVE tracked_trades")
    except sqlite3.OperationalError as e:
        print(f"[GC] tracked_trades skipped: {e!r}")

    # 2. Verify current ACTIVE count post-close
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
        ).fetchone()
        print(f"[GC] tracked_trades ACTIVE remaining: {r[0]:,}")
    except sqlite3.OperationalError:
        pass

    # 3. Delete old trade_signals
    try:
        cur = conn.execute(
            "DELETE FROM trade_signals WHERE ts < ?",
            (cutoff_ts,),
        )
        n_deleted = cur.rowcount
        conn.commit()
        print(f"[GC] Deleted {n_deleted:,} old trade_signals")
    except sqlite3.OperationalError as e:
        print(f"[GC] trade_signals skipped: {e!r}")

    # 4. Verify trade_signals remaining
    try:
        r = conn.execute("SELECT COUNT(*) FROM trade_signals").fetchone()
        print(f"[GC] trade_signals remaining: {r[0]:,}")
    except sqlite3.OperationalError:
        pass

    # 5. WAL checkpoint truncate
    try:
        r = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"[GC] WAL checkpoint: busy={r[0]} log={r[1]} ckpt={r[2]}")
    except sqlite3.OperationalError as e:
        print(f"[GC] WAL checkpoint failed: {e!r}")

    conn.close()

    db_size_after = os.path.getsize(DB_PATH) / 1024 / 1024
    delta = db_size_mb - db_size_after
    print(f"[GC] DB post-cleanup: {db_size_after:.1f} MB ({delta:+.1f} MB)")
    print(f"[GC] Done @ {datetime.now().strftime('%H:%M:%S')} — safe to restart backend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
