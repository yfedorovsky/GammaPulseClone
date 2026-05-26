"""Delete AUTO_GC closed rows from tracked_trades.

Companion to bulk_gc_trade_signals.py. Yesterday's GC closed 448,575
runaway-tracked trades with close_reason='AUTO_BULK_GC_2026-05-26' /
'AUTO_FULL_RESET_2026-05-26'. These rows have no analytical value
(they were never real positions, just flow alerts auto-tracked).
Their trade_signals have already been deleted. Delete the parent rows.

KEEP the ~849K legitimately-closed trades (close_reason NULL or set by
the tracker's normal exit-signal flow) — those are real history.

Safe to run while backend is live.
"""
import sqlite3
import sys

c = sqlite3.connect("snapshots.db")
try:
    before = c.execute("SELECT COUNT(*) FROM tracked_trades").fetchone()[0]
    auto_before = c.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE close_reason LIKE 'AUTO_%'"
    ).fetchone()[0]
    print(f"Before: {before:,} total, {auto_before:,} AUTO_*", file=sys.stderr)

    n = c.execute(
        "DELETE FROM tracked_trades WHERE close_reason LIKE 'AUTO_%'"
    ).rowcount
    c.commit()

    after = c.execute("SELECT COUNT(*) FROM tracked_trades").fetchone()[0]
    print(f"Deleted: {n:,} AUTO_* rows", file=sys.stderr)
    print(f"After: {after:,} total", file=sys.stderr)

    try:
        c.execute("VACUUM")
        print("VACUUM complete", file=sys.stderr)
    except sqlite3.OperationalError as e:
        print(f"VACUUM skipped: {e}", file=sys.stderr)
finally:
    c.close()
