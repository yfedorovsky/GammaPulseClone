"""Quick health check on snapshot writes.

Use after a backend restart to confirm the snapshots persist path is healed.
Expect 50-200 rows in the last 2 minutes if the worker is scanning.
"""
import sqlite3
import time

conn = sqlite3.connect("snapshots.db")
try:
    now = time.time()

    n_2min = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE ts > ?", (now - 120,)
    ).fetchone()[0]
    n_5min = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE ts > ?", (now - 300,)
    ).fetchone()[0]
    last_ts = conn.execute("SELECT MAX(ts) FROM snapshots").fetchone()[0]

    ago_min = (now - last_ts) / 60 if last_ts else None
    last_et = conn.execute(
        "SELECT datetime(MAX(ts), 'unixepoch', '-4 hours') FROM snapshots"
    ).fetchone()[0]

    print(f"snapshots last 2 min:  {n_2min}")
    print(f"snapshots last 5 min:  {n_5min}")
    print(f"most recent row ET:    {last_et}   ({ago_min:.1f} min ago)" if ago_min else "no rows")

    # Verdict
    print()
    if n_2min >= 50:
        print("OK — persist path is healed, snapshots resuming.")
    elif n_2min > 0:
        print("PARTIAL — some writes, but lower than expected. Wait 60s and rerun.")
    else:
        print("STILL BROKEN — restart didn't fix it. Need code-level dig.")
finally:
    conn.close()
