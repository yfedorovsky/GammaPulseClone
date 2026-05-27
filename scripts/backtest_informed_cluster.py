"""Backtest INFORMED CLUSTER detector against today's flow_alerts.

Replays today's rows through the v2 classifier and then through the
cluster detector to count:
  - Total unique CLUSTER fires per day
  - Distribution by cluster size (2-strike, 3-strike, 4+)
  - Top clusters by total notional
  - Verify META 5/27 0DTE ladder fires as a cluster

Run from project root:
    python -m scripts.backtest_informed_cluster
"""
from __future__ import annotations

import sqlite3
import sys
import io
from collections import Counter
from datetime import datetime, date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.flow_alerts import (  # noqa: E402
    _classify_insider_signature,
    _INFORMED_FLOW_DEDUP,
    _is_informed_flow_duplicate,
)
from server.informed_cluster import (  # noqa: E402
    record_and_check, _recent_fires, _cluster_dedup,
)

DB = ROOT / "snapshots.db"


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    today_start = int(datetime(date.today().year, date.today().month,
                                date.today().day, 0, 0).timestamp())
    rows = conn.execute(
        """SELECT * FROM flow_alerts WHERE ts >= ? ORDER BY ts""",
        (today_start,),
    ).fetchall()

    print(f"=== Backtesting INFORMED CLUSTER on {len(rows):,} flow_alerts ===")
    print()

    # Reset state
    _INFORMED_FLOW_DEDUP.clear()
    _recent_fires.clear()
    _cluster_dedup.clear()

    cluster_fires: list[dict] = []
    informed_flow_fires = 0

    for r in rows:
        alert = dict(r)
        oi = alert.get("oi", 0) or 0
        vol = alert.get("volume", 0) or 0
        notional = alert.get("notional", 0) or 0
        if oi < 100 and vol < 500:
            continue
        if notional < 10_000:
            continue

        score, _reasons = _classify_insider_signature(alert)
        if score < 5:
            continue
        if _is_informed_flow_duplicate(alert):
            continue

        # Single-fire INFORMED FLOW
        alert["is_insider"] = 1
        alert["insider_score"] = score
        informed_flow_fires += 1

        # Override timestamp for the cluster module's internal "now"
        # to use the alert's real ts (otherwise backtest collapses everything
        # to current real time). Monkey-patch time.time briefly.
        import time as _time
        real_time = _time.time
        _time.time = lambda alert_ts=alert["ts"]: float(alert_ts)
        try:
            cluster = record_and_check(alert)
        finally:
            _time.time = real_time

        if cluster:
            cluster_fires.append(cluster)

    print(f"Total INFORMED FLOW fires (post-dedup): {informed_flow_fires:,}")
    print(f"Total INFORMED CLUSTER fires: {len(cluster_fires):,}")
    print(f"  Compression ratio: {(1 - len(cluster_fires)/max(informed_flow_fires, 1))*100:.1f}%")
    print()

    print("=== CLUSTER SIZE DISTRIBUTION ===")
    size_counts = Counter(c["n_strikes"] for c in cluster_fires)
    for size in sorted(size_counts.keys()):
        bar = "█" * min(size_counts[size], 40)
        print(f"  {size}-strike: {size_counts[size]:>4}  {bar}")
    print()

    print("=== TOP CLUSTERS BY TOTAL NOTIONAL ===")
    for c in sorted(cluster_fires, key=lambda x: -x["total_notional"])[:15]:
        t1 = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M")
        t2 = datetime.fromtimestamp(c["last_ts"]).strftime("%H:%M")
        strikes = "/".join(f"${s:g}" for s, *_ in c["strikes"])
        if len(strikes) > 50:
            strikes = strikes[:47] + "..."
        print(f"  {c['ticker']:>6} {c['expiration']} {c['direction']:>4} "
              f"({c['n_strikes']} strikes) | ${c['total_notional']:>13,.0f} | "
              f"{t1}-{t2} | max={c['max_score']}/6 | {strikes}")
    print()

    print("=== META 5/27 0DTE CLUSTER VERIFICATION ===")
    meta_clusters = [c for c in cluster_fires
                     if c["ticker"] == "META" and c["expiration"] == "2026-05-27"]
    if meta_clusters:
        for c in meta_clusters:
            t1 = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M:%S")
            t2 = datetime.fromtimestamp(c["last_ts"]).strftime("%H:%M:%S")
            print(f"  {c['direction']} cluster: {c['n_strikes']} strikes "
                  f"{t1}-{t2} ({c['duration_min']:.0f}min)")
            for s, ts, sc, n, voi in c["strikes"]:
                t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                print(f"    {t} ${s:g}  score={sc}/6  V/OI={voi:.1f}x  ${n:,.0f}")
            print(f"    TOTAL: ${c['total_notional']:,.0f} | max score {c['max_score']}/6")
            print()
    else:
        print("  ⚠️ No META 5/27 0DTE clusters found — investigate!")
    print()

    print("=== ALL CLUSTERS (chronological) ===")
    for c in sorted(cluster_fires, key=lambda x: x["first_ts"]):
        t1 = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M")
        strikes = "/".join(f"${s:g}" for s, *_ in c["strikes"][:5])
        if len(c["strikes"]) > 5:
            strikes += f" +{len(c['strikes'])-5}"
        print(f"  {t1} {c['ticker']:>6} {c['expiration']} {c['direction']:>4} "
              f"({c['n_strikes']}) ${c['total_notional']/1e6:.2f}M [{strikes}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
