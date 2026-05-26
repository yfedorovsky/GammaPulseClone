"""GC trade_signals table — orphaned + >7d old rows.

Context: 2026-05-26 — diagnostic revealed 4,065,168 rows in trade_signals
table. 1,488,267 are orphaned (linked to tracked_trades closed by
AUTO_BULK_GC_* close_reason — i.e. signals fired for runaway-auto-
tracked trades that were never real positions).

Cleanup strategy:
  1. Delete signals linked to auto-GC'd trades (orphaned cruft)
  2. Delete signals older than 7 days (historical, no current use)
  3. Keep last 7 days for any post-mortem analysis
  4. VACUUM to reclaim disk

Safe to run while backend is live — SQLite WAL handles concurrent reads.
"""
import sqlite3
import time
import sys

DB = "snapshots.db"
KEEP_DAYS = 7

now = int(time.time())
cutoff_age = now - (KEEP_DAYS * 86400)

c = sqlite3.connect(DB)
try:
    before = c.execute("SELECT COUNT(*) FROM trade_signals").fetchone()[0]
    print(f"Before: {before:,} rows", file=sys.stderr)

    # Step 1: delete orphaned signals (linked to AUTO_* closed trades)
    print("Step 1: deleting orphaned signals (linked to AUTO_* trades)...", file=sys.stderr)
    n_orphan = c.execute("""
        DELETE FROM trade_signals
        WHERE trade_id IN (
            SELECT id FROM tracked_trades
            WHERE status = 'CLOSED' AND close_reason LIKE 'AUTO_%'
        )
    """).rowcount
    c.commit()
    print(f"  Deleted {n_orphan:,} orphaned signals", file=sys.stderr)

    # Step 2: delete anything older than 7 days
    print(f"Step 2: deleting signals older than {KEEP_DAYS} days...", file=sys.stderr)
    n_stale = c.execute(
        "DELETE FROM trade_signals WHERE ts < ?", (cutoff_age,)
    ).rowcount
    c.commit()
    print(f"  Deleted {n_stale:,} stale signals", file=sys.stderr)

    after = c.execute("SELECT COUNT(*) FROM trade_signals").fetchone()[0]
    print(f"After: {after:,} rows remaining", file=sys.stderr)
    print(f"Total deleted: {before - after:,} ({(before-after)/before*100:.1f}%)",
          file=sys.stderr)

    # Step 3: VACUUM to reclaim disk space
    # Note: VACUUM requires no other connections + temp space = source DB size.
    # If backend is live and writing, VACUUM may fail. Skip if so — user can
    # run it manually during a quiet window.
    print("Step 3: attempting VACUUM to reclaim disk...", file=sys.stderr)
    try:
        c.execute("VACUUM")
        print("  VACUUM complete", file=sys.stderr)
    except sqlite3.OperationalError as e:
        print(f"  VACUUM skipped: {e} (run manually when backend is idle)",
              file=sys.stderr)
finally:
    c.close()
