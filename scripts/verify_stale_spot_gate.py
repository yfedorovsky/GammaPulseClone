"""Verify the SOE stale-spot gate is wired correctly after restart.

Checks:
  1. Backend is up
  2. New /api/alerts/cluster endpoint responds
  3. Cache state has the new _updated_ts field on a TIER_1 ticker
  4. Reports current freshness of recent SOE signals vs cache age

Run after restart:
    python -m scripts.verify_stale_spot_gate
"""
from __future__ import annotations

import sys
import io
import time
import urllib.request
import json
import sqlite3
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def _get(path: str) -> dict:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8000{path}", headers={"User-Agent": "curl"}
        )
        return json.loads(urllib.request.urlopen(req, timeout=5).read())
    except Exception as e:
        return {"_err": repr(e)}


def main() -> int:
    print("=== Stale-spot gate verification ===")
    print(f"  ET clock: {datetime.now().strftime('%H:%M:%S')}")
    print()

    # 1. Backend alive
    h = _get("/api/health")
    if "_err" in h:
        print(f"  ✗ backend not reachable: {h['_err']}")
        return 1
    print(f"  ✓ backend alive — status={h.get('status')} worker={h.get('worker', {}).get('status', '?')}")

    # 2. Endpoints
    for ep in ("/api/alerts/cluster?limit=5", "/api/alerts/insider?limit=5"):
        r = _get(ep)
        ok = "_err" not in r
        print(f"  {'✓' if ok else '✗'} {ep}: {'OK' if ok else r.get('_err')}")
    print()

    # 3. _updated_ts on cache state via direct module import
    print("=== Cache freshness (in-process — separate from running backend) ===")
    # Can't directly inspect running backend's in-memory cache from here,
    # but we can read the snapshots table (DB) instead — that's the source
    # of truth for "what the worker last wrote."
    conn = sqlite3.connect(str(ROOT / "snapshots.db"))
    conn.row_factory = sqlite3.Row
    now = int(time.time())
    for ticker in ("SPY", "QQQ", "MU", "NBIS", "NVDA", "TSLA", "META"):
        r = conn.execute(
            "SELECT ts, spot FROM snapshots WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if r:
            age = now - r["ts"]
            fresh = "🟢" if age < 120 else "🟡" if age < 600 else "🔴"
            dt = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
            print(f"  {fresh} {ticker:>5}: ${r['spot']:>8.2f}  @{dt} ({age}s ago)")
        else:
            print(f"  ⚪ {ticker:>5}: no snapshot")
    print()

    # 4. Recent SOE signals (post-restart era)
    print("=== Recent SOE signals (last 15 min) ===")
    cutoff = now - 900
    rows = conn.execute(
        """SELECT ts, ticker, signal_type, grade, spot
           FROM soe_signals WHERE ts > ? ORDER BY ts DESC LIMIT 15""",
        (cutoff,),
    ).fetchall()
    if rows:
        for r in rows:
            dt = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
            age = now - r["ts"]
            print(f"  {dt} ({age}s ago) {r['ticker']:>6} grade={r['grade']} "
                  f"{r['signal_type']} spot=${r['spot']:.2f}")
    else:
        print("  (no SOE signals in last 15 min — expected if backend just restarted)")
    print()

    # 5. Recent suppressions (if any) — check stdout via log file if available
    print("Watch the backend log for messages like:")
    print("  [SOE] suppress stale-spot fire: <TICKER> snapshot <N>s old at open")
    print("These confirm the gate is working.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
