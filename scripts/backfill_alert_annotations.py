"""Backfill annotation features on existing 0DTE alerts.

For every alert in zero_dte_alerts.db, computes the alert_annotations
feature set and UPDATEs the row with the new values. Idempotent —
safe to re-run.

Per cross-LLM round 5 consensus (Gemini + OpenAI deep research):
these annotations let us validate which day-state and feasibility
features have predictive power once we have ≥50 forward alerts.

Run:
  python scripts/backfill_alert_annotations.py
  python scripts/backfill_alert_annotations.py --date 2026-05-01
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_annotations import (  # noqa: E402
    annotate_alert, apply_migrations, assign_episode_ids,
)

ALERT_DB = "zero_dte_alerts.db"


def fetch_alerts(day: str | None = None) -> list[dict]:
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    if day:
        d = datetime.fromisoformat(day)
        t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
        t1 = int(d.replace(hour=23, minute=59, second=59).timestamp())
        cur = conn.execute(
            "SELECT * FROM zero_dte_alerts WHERE fired_at BETWEEN ? AND ? "
            "ORDER BY fired_at", (t0, t1),
        )
    else:
        cur = conn.execute("SELECT * FROM zero_dte_alerts ORDER BY fired_at")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_alert(alert_id: str, annotations: dict, episode_id: str) -> None:
    conn = sqlite3.connect(ALERT_DB)
    annotations = dict(annotations)
    annotations["episode_id"] = episode_id
    cols = ", ".join(f"{k} = ?" for k in annotations.keys())
    vals = list(annotations.values()) + [alert_id]
    conn.execute(
        f"UPDATE zero_dte_alerts SET {cols} WHERE alert_id = ?", vals
    )
    conn.commit()
    conn.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD; if omitted, backfill all alerts")
    args = p.parse_args()

    print("[backfill] applying schema migrations...", flush=True)
    n_migr = apply_migrations()
    print(f"[backfill] {n_migr} new columns added (others already exist)",
          flush=True)

    alerts = fetch_alerts(args.date)
    print(f"[backfill] {len(alerts)} alerts to annotate", flush=True)
    if not alerts:
        return 0

    # Compute episode_ids in bulk (needs full alert list to detect groupings)
    episode_ids = assign_episode_ids(alerts)
    print(f"[backfill] assigned {len(set(episode_ids))} unique episode_ids "
          f"across {len(alerts)} alerts", flush=True)

    n_done = 0
    n_failed = 0
    for alert, ep_id in zip(alerts, episode_ids):
        try:
            ann = annotate_alert(alert)
            update_alert(alert["alert_id"], ann, ep_id)
            n_done += 1
            fire_dt = datetime.fromtimestamp(alert["fired_at"]).strftime("%m-%d %H:%M")
            tape = ann.get("tape_regime_at_fire") or "?"
            reach = ann.get("strike_reachability_ratio")
            reach_str = f"{reach:.2f}" if reach is not None else "?"
            jump = ann.get("jump_share")
            jump_str = f"{jump:.2f}" if jump is not None else "?"
            print(f"  {fire_dt} {alert['ticker']:<4} {alert['direction'][:4]} "
                  f"K={alert['strike']:.0f}  reach={reach_str}  "
                  f"tape={tape:<10}  jump={jump_str}  ep={ep_id}",
                  flush=True)
        except Exception as e:
            n_failed += 1
            print(f"  ! {alert['alert_id']}: {type(e).__name__}: {e}",
                  flush=True)

    print(f"\n[backfill] {n_done} updated, {n_failed} failed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
