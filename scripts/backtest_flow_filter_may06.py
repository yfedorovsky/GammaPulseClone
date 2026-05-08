"""Replay May 6 2026 flow_alerts through FlowAlertFilter and report
how many would actually have hit Telegram under each level (OFF/LIGHT/FULL).

Read directly from snapshots.db.flow_alerts ORDER BY ts so the cluster
window logic sees alerts in real chronological order.
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

# Force UTF-8 stdout on Windows so emoji in cluster summaries don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.flow_alert_filter import (
    FlowAlertFilter,
    format_cluster_summary,
    format_hot_flow_summary,
    set_level,
)

DB = ROOT / "snapshots.db"

START_TS_SQL = "strftime('%s','2026-05-06')"
END_TS_SQL = "strftime('%s','2026-05-07')"


def load_alerts() -> list[dict]:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        f"""SELECT ts, ticker, strike, expiration, option_type, volume, oi,
                  vol_oi, last_price, bid, ask, side, sentiment, iv, delta,
                  notional, spot, conviction, is_sweep, macro_regime_tag,
                  king, signal, regime
             FROM flow_alerts
            WHERE ts >= {START_TS_SQL} AND ts < {END_TS_SQL}
            ORDER BY ts ASC"""
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def replay_at_level(alerts: list[dict], level: str) -> dict:
    set_level(level)
    f = FlowAlertFilter()
    fired_singles = 0
    fired_summaries = 0
    fired_hotflow = 0
    drop_reasons: Counter[str] = Counter()
    sample_summaries: list[dict] = []
    sample_singles: list[dict] = []

    last_ts = 0
    for a in alerts:
        ts = int(a["ts"])
        last_ts = ts

        # Periodic flush at every minute boundary so cluster windows close
        # in the right order. (In live, this is driven by the 30s scan loop.)
        for decision, payload in f.flush(now=ts):
            if decision == "FIRE":
                fired_singles += 1
                if len(sample_singles) < 3:
                    sample_singles.append(payload)
            elif decision == "FIRE_SUMMARY":
                if payload.get("kind") == "CLUSTER":
                    fired_summaries += 1
                    if len(sample_summaries) < 3:
                        sample_summaries.append(payload)
                elif payload.get("kind") == "HOT_FLOW":
                    fired_hotflow += 1

        for decision, payload in f.process(a, now=ts):
            if decision == "DROP":
                drop_reasons[payload] += 1
            elif decision == "FIRE":
                fired_singles += 1
                if len(sample_singles) < 3:
                    sample_singles.append(payload)
            elif decision == "FIRE_SUMMARY":
                if payload.get("kind") == "CLUSTER":
                    fired_summaries += 1
                    if len(sample_summaries) < 3:
                        sample_summaries.append(payload)
                elif payload.get("kind") == "HOT_FLOW":
                    fired_hotflow += 1

    # Final drain — push any open clusters / suppressed buckets out
    final_now = last_ts + 7200  # +2 hr to force all hour buckets to close
    for decision, payload in f.flush(now=final_now):
        if decision == "FIRE":
            fired_singles += 1
        elif decision == "FIRE_SUMMARY":
            if payload.get("kind") == "CLUSTER":
                fired_summaries += 1
                if len(sample_summaries) < 3:
                    sample_summaries.append(payload)
            elif payload.get("kind") == "HOT_FLOW":
                fired_hotflow += 1
                if level == "FULL":
                    sample_summaries.append(payload)

    # Drain anything still in cluster buffer
    for decision, payload in f._cluster.force_flush_all():
        if decision == "FIRE":
            fired_singles += 1
        elif decision == "FIRE_SUMMARY":
            fired_summaries += 1
            if len(sample_summaries) < 5:
                sample_summaries.append(payload)

    return {
        "level": level,
        "input": len(alerts),
        "fired_singles": fired_singles,
        "fired_summaries": fired_summaries,
        "fired_hotflow": fired_hotflow,
        "fired_total": fired_singles + fired_summaries + fired_hotflow,
        "drop_reasons": dict(drop_reasons),
        "stats": dict(f.stats),
        "sample_summaries": sample_summaries[:3],
        "sample_singles": sample_singles[:3],
    }


def main() -> None:
    alerts = load_alerts()
    print(f"Loaded {len(alerts)} flow_alerts for May 6 2026\n")

    for level in ("OFF", "LIGHT", "FULL"):
        r = replay_at_level(alerts, level)
        # Reduction = how much smaller the output is. Show as a negative
        # delta so -78% reads as "78% reduction in alerts."
        reduction = -((1 - r["fired_total"] / r["input"]) * 100) if r["input"] else 0
        print(f"=== Level: {level} ===")
        print(f"  Input:        {r['input']}")
        print(f"  Singles:      {r['fired_singles']}")
        print(f"  Cluster sums: {r['fired_summaries']}")
        print(f"  Hot-flow:     {r['fired_hotflow']}")
        print(f"  TOTAL fired:  {r['fired_total']}  ({reduction:+.1f}% vs input)")
        if r["drop_reasons"]:
            print(f"  Drop reasons: {r['drop_reasons']}")
        print()

    # Show example unified alerts under FULL
    r_full = replay_at_level(alerts, "FULL")
    print("\n=== Example CLUSTER summaries (FULL) ===\n")
    for c in r_full["sample_summaries"][:3]:
        if c.get("kind") == "CLUSTER":
            print(format_cluster_summary(c))
            print("---")
        elif c.get("kind") == "HOT_FLOW":
            print(format_hot_flow_summary(c))
            print("---")


if __name__ == "__main__":
    main()
