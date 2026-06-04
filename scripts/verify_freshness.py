"""Verify backend health using multiple signals.

Old version only checked the `snapshots` SQLite table refresh rate, which
misses Theta WS streaming data and is misleadingly pessimistic. This version
checks multiple signals to give a real health verdict.

Usage:
    python scripts/verify_freshness.py
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime


TIER_GROUPS = {
    "CRITICAL": ["SPY", "QQQ", "IWM", "VIX", "NVDA", "TSLA"],
    "TIER_1":   ["MSFT", "META", "AAPL", "AMZN", "GOOGL", "AMD", "MU"],
    "WATCH":    ["DELL", "HPE", "INTC", "MRVL", "QCOM", "LITE", "NBIS"],
}

# Relaxed ceilings — snapshots table is spot price refresh, not live alerts
EXPECTED_MAX_S = {
    "CRITICAL": 180,
    "TIER_1":   300,
    "WATCH":    600,
}


def tail_log(path: str, n: int = 200) -> list[str]:
    """Tail last n lines of backend.log."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        chunk = min(size, 64 * 1024)
        f.seek(size - chunk)
        data = f.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    return lines[-n:] if len(lines) > n else lines


def main() -> int:
    conn = sqlite3.connect("snapshots.db", timeout=5)
    now = int(time.time())

    print(f"\n[VERIFY] Backend health @ {datetime.now().strftime('%H:%M:%S ET')}")
    print("=" * 70)

    # === 1. Snapshot tier freshness (spot price refresh) ===
    print("\n[SNAPSHOTS] Tier freshness (spot price refresh path)")
    overall_ok = True
    for grp, tks in TIER_GROUPS.items():
        ceiling = EXPECTED_MAX_S[grp]
        ages = []
        for tk in tks:
            r = conn.execute(
                "SELECT MAX(ts) FROM snapshots WHERE ticker = ?", (tk,)
            ).fetchone()
            if r and r[0]:
                ages.append(now - r[0])
        if not ages:
            print(f"  {grp:<10}  no data")
            continue
        avg = sum(ages) / len(ages)
        mx = max(ages)
        status = "OK" if mx <= ceiling else "STALE"
        if mx > ceiling:
            overall_ok = False
        print(
            f"  {grp:<10} n={len(ages):<2} avg={avg:>4.0f}s max={mx:>4.0f}s "
            f"[ceil={ceiling}s] [{status}]"
        )

    # === 2. Flow alerts firing (live signal — independent of snapshots) ===
    cnt_60s = conn.execute(
        "SELECT COUNT(*) FROM flow_alerts WHERE ts >= ?", (now - 60,)
    ).fetchone()[0]
    cnt_300s = conn.execute(
        "SELECT COUNT(*) FROM flow_alerts WHERE ts >= ?", (now - 300,)
    ).fetchone()[0]
    print(f"\n[FLOW] alerts last 60s: {cnt_60s}   last 5min: {cnt_300s}")
    if cnt_300s == 0:
        print("[WARN] No flow alerts in 5 min — scanner may be down")
        overall_ok = False

    # === 3. SOE evaluator firing ===
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM soe_signals WHERE ts >= ?", (now - 600,)
        ).fetchone()
        print(f"[SOE] signals last 10min: {r[0]}")
    except sqlite3.OperationalError:
        pass

    # === 4. Tracker health ===
    r = conn.execute(
        "SELECT COUNT(*) FROM tracked_trades WHERE status = 'ACTIVE'"
    ).fetchone()
    n_active = r[0] if r else 0
    rate_hint = ""
    if n_active > 5000:
        rate_hint = " [WARN runaway risk]"
        overall_ok = False
    elif n_active > 1000:
        rate_hint = " [growing — task #34]"
    print(f"[TRACKER] ACTIVE: {n_active:,}{rate_hint}")

    # === 5. Backend log heartbeats (real source of truth) ===
    log_path = os.path.join("logs", "backend.log")
    if os.path.exists(log_path):
        lines = tail_log(log_path, 300)
        recent = "\n".join(lines)
        signals = {
            "THETA WS streaming": "[THETA_STREAM]" in recent,
            "Flow scanner cycle": "[FLOW]" in recent,
            "Priority refresh":   "[priority] heartbeat" in recent,
            "Sweep detector":     "[SWEEP] heartbeat" in recent,
            "Net flow fast":      "[net_flow_fast] heartbeat" in recent,
            "Tracker exit signals": "[TRACKER]" in recent,
        }
        print("\n[BACKEND_LOG] heartbeats in last ~300 lines:")
        for name, present in signals.items():
            mark = "OK" if present else "MISSING"
            print(f"  {'OK' if present else '!! '} {name:<25} [{mark}]")
            if not present:
                overall_ok = False

        # Check for actual errors
        errors = [l for l in lines if "Traceback" in l or "ERROR" in l.upper()
                  or "exception" in l.lower()]
        if errors:
            print(f"\n[WARN] {len(errors)} error/traceback lines in log:")
            for e in errors[-5:]:
                print(f"  > {e[:120]}")
    else:
        print("\n[BACKEND_LOG] logs/backend.log not found")

    conn.close()

    print()
    print("=" * 70)
    print(f"[VERIFY] Overall: {'PASS' if overall_ok else 'FAIL — investigate above'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
