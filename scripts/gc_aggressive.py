"""AGGRESSIVE pre-restart cleanup.

Closes ALL ACTIVE tracked_trades regardless of age. Use this when the
runaway condition is severe (>5K ACTIVE) and the standard 24-hour GC
isn't enough.

Safe in the sense that tracked_trades is an internal performance-tracking
table — closing rows here does NOT affect any real-money positions or
broker orders. Today's alerts re-fire and re-register normally.

CRITICAL: Stop the backend FIRST. If the worker is running, it will write
new ACTIVE rows during cleanup, racing this script.

Usage:
    python scripts/gc_aggressive.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime


DB_PATH = "snapshots.db"


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"[ERR] {DB_PATH} not found — run from C:/Dev/GammaPulse")
        return 1

    db_size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"[GC-AGGR] DB pre-cleanup: {db_size_mb:.1f} MB")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    now = int(time.time())

    # 1. Pre-count
    r = conn.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()
    n_pre = r[0] if r else 0
    print(f"[GC-AGGR] tracked_trades ACTIVE before: {n_pre:,}")

    if n_pre == 0:
        print("[GC-AGGR] Nothing to close.")
    else:
        # 2. Close EVERYTHING ACTIVE
        cur = conn.execute(
            "UPDATE tracked_trades SET status = 'CLOSED', "
            "close_reason = 'GC_AGGRESSIVE', "
            "closed_ts = ? "
            "WHERE status = 'ACTIVE'",
            (now,),
        )
        n_closed = cur.rowcount
        conn.commit()
        print(f"[GC-AGGR] Closed {n_closed:,} tracked_trades")

    # 3. Verify
    r = conn.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()
    n_post = r[0] if r else 0
    print(f"[GC-AGGR] tracked_trades ACTIVE after: {n_post:,}")
    if n_post > 0:
        print(f"[WARN] {n_post} ACTIVE rows remain — backend may still be writing!")
        print(f"[WARN] STOP the backend process and re-run this script.")

    # 4. Trade signals cleanup (24h+)
    cutoff = now - 24 * 3600
    cur = conn.execute(
        "DELETE FROM trade_signals WHERE ts < ?", (cutoff,)
    )
    print(f"[GC-AGGR] Deleted {cur.rowcount:,} trade_signals >24h old")
    conn.commit()

    # 5. WAL checkpoint
    r = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    print(f"[GC-AGGR] WAL checkpoint: busy={r[0]} log={r[1]} ckpt={r[2]}")

    conn.close()

    db_size_after = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"[GC-AGGR] DB post-cleanup: {db_size_after:.1f} MB")
    print(f"[GC-AGGR] Done @ {datetime.now().strftime('%H:%M:%S')}")

    if n_post > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
