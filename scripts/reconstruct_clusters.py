"""Historical INFORMED CLUSTER reconstruction -> markout verdict (2026-06-29 audit).

The dedup-at-2 bug meant the crown-jewel detector logged 0 outcome rows in 60 days,
so its "~89% WR" was never tested on realized option P&L. The live fix is
forward-only; this reconstructs the history so we get the verdict NOW.

Method: replay is_insider=1 flow_alerts (snapshots.db) CHRONOLOGICALLY through the
REAL record_and_check (time-injected via now=ts) — so reconstructed clusters match
exactly what the fixed live detector would produce, with zero reimplementation
drift. Each fired 3+ -strike cluster is logged as alert_type='CLUSTER' (idempotent).
Then option-P&L + short-horizon MID-to-MID markout is backfilled (ThetaData) and the
LEADS-vs-EXHAUST verdict printed.

  LEADS   (median +5m markout > 0): the move is in front of the flow (real edge)
  EXHAUST (median <= 0): the mid falls right after entry (Gemini's "buying exhaust")

Writes to a SCRATCH db by default (no risk to the live alert_outcomes.db). Requires
the ThetaData Terminal for --backfill.

Run:
  python scripts/reconstruct_clusters.py --days 60                       # replay + count
  python scripts/reconstruct_clusters.py --days 60 --backfill --report   # + verdict
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import informed_cluster as ic  # noqa: E402
from server.alert_outcomes import (  # noqa: E402
    _ensure_schema,
    get_markout_by_type,
    run_option_pnl_backfill,
)

SNAP_DB = os.environ.get("SNAPSHOTS_DB", "snapshots.db")
_COLS = ("ticker", "strike", "option_type", "expiration", "sentiment",
         "insider_score", "notional", "vol_oi", "ts")


def _load_insider(days: int) -> list[dict]:
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(f"file:{SNAP_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT {','.join(_COLS)} FROM flow_alerts
                WHERE is_insider=1 AND ts > ?
                  AND ticker IS NOT NULL AND expiration IS NOT NULL
                  AND strike IS NOT NULL AND option_type IS NOT NULL
                ORDER BY ts ASC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def reconstruct(days: int, db: str) -> dict:
    """Replay the insider stream through record_and_check; it logs each fired
    cluster to `db` as alert_type='CLUSTER'. Returns counts."""
    alerts = _load_insider(days)
    ic._recent_fires.clear()
    ic._cluster_dedup.clear()
    fires = 0
    for a in alerts:
        r = ic.record_and_check(a, db_path=db, now=float(a["ts"]))
        if r is not None and r.get("n_strikes", 0) >= ic.MIN_CLUSTER_TELEGRAM_STRIKES:
            fires += 1
    return {"insider_legs": len(alerts), "cluster_fires": fires}


def _fmt(a: dict) -> str:
    if not a or a.get("median") is None:
        return "n/a"
    return f"med={a['median']:+.2f}%  mean={a['mean']:+.2f}%  pos={a['pct_pos']:.0f}%  n={a['n']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--db", default="cluster_recon.db", help="scratch DB (default; safe)")
    ap.add_argument("--backfill", action="store_true", help="fetch option-P&L + markout (ThetaData)")
    ap.add_argument("--limit", type=int, default=None, help="cap markout fetches (newest-first)")
    ap.add_argument("--report", action="store_true", help="print the LEADS/EXHAUST verdict")
    args = ap.parse_args()

    print(f"[recon] replaying is_insider flow_alerts, last {args.days}d -> {args.db}", flush=True)
    t0 = time.time()
    stats = reconstruct(args.days, args.db)
    _ensure_schema(args.db)  # guarantee the table exists even if 0 clusters fired

    conn = sqlite3.connect(args.db)
    n_rows = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    n_clusters = conn.execute("SELECT COUNT(DISTINCT fired_at) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    by_grade = conn.execute(
        "SELECT grade, COUNT(DISTINCT fired_at||ticker||expiration) FROM alert_outcomes "
        "WHERE alert_type='CLUSTER' GROUP BY grade ORDER BY grade").fetchall()
    top = conn.execute(
        "SELECT ticker, COUNT(DISTINCT fired_at) c FROM alert_outcomes WHERE alert_type='CLUSTER' "
        "GROUP BY ticker ORDER BY c DESC LIMIT 12").fetchall()
    conn.close()

    print(f"[recon] insider legs replayed : {stats['insider_legs']:,}  ({time.time()-t0:.0f}s)")
    print(f"[recon] cluster fires (>=3)   : {stats['cluster_fires']:,}")
    print(f"[recon] CLUSTER leg-rows      : {n_rows:,}  across {n_clusters:,} distinct fires")
    print(f"[recon] by grade (fires)      : {dict(by_grade)}")
    print(f"[recon] top tickers (fires)   : {dict(top)}")

    if args.backfill:
        print(f"\n[recon] backfilling option-P&L + markout (ThetaData) for CLUSTER rows ...", flush=True)
        t1 = time.time()
        s = asyncio.run(run_option_pnl_backfill(
            db_path=args.db, max_age_days=args.days + 2, limit=args.limit, alert_type="CLUSTER"))
        print(f"[recon] backfill: {s}  ({time.time()-t1:.0f}s)")

    if args.report:
        rep = get_markout_by_type(days=args.days + 2, db_path=args.db, alert_type="CLUSTER")
        print("\n========== INFORMED CLUSTER — markout verdict ==========")
        if not rep:
            print("(no markout rows yet — run with --backfill; needs the ThetaData Terminal)")
        for r in rep:
            print(f"  {r['alert_type']}:  N={r['n']}   VERDICT = {r['verdict_5m']}")
            print(f"     +1m   {_fmt(r['mark_1m'])}")
            print(f"     +5m   {_fmt(r['mark_5m'])}   <- headline")
            print(f"     +15m  {_fmt(r['mark_15m'])}")
        print("\nMID-to-MID markout = information content (adverse selection), independent of")
        print("the spread you pay. Cross-check opt_mfe/opt_mae (ask-in/bid-out) for tradability.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
