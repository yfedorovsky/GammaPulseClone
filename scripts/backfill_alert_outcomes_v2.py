"""One-time backfill: import 5/19 + 5/20 fired alerts into alert_outcomes.

V2 (2026-05-20 night). Pulls from:
  - snapshots.db::soe_signals (SOE A/A+/B+)
  - snapshots.db::flow_alerts (single-direction, HIGH/MEDIUM/SWEEP)
  - snapshots.db::setup_forming
  - snapshots.db::mir_message_log (Mir Discord signals)
  - zero_dte_alerts.db::zero_dte_alerts

Then triggers the outcome backfill (intraday history walk via Tradier).

Usage:
    python -m scripts.backfill_alert_outcomes_v2
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.alert_outcomes import log_alert, backfill_outcomes, DB_PATH


SNAPSHOTS_DB = "./snapshots.db"
ZERO_DTE_DB = "./zero_dte_alerts.db"


def backfill_soe_signals() -> int:
    cutoff = time.time() - 7 * 86400
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT * FROM soe_signals
               WHERE ts > ?
                 AND grade IN ('A', 'A+', 'B+')
               ORDER BY ts ASC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for r in rows:
        d = dict(r)
        direction = d.get("direction", "")
        is_bull = direction in ("▲", "BULL", "LONG", "BUY")
        grade = d.get("grade", "?")
        try:
            log_alert(
                alert_type=f"SOE_{grade.replace('+','P')}",
                ticker=d.get("ticker", ""),
                fired_at=float(d.get("ts", 0)),
                direction="BULL" if is_bull else "BEAR",
                grade=grade,
                score=d.get("score"),
                strike=d.get("strike"),
                expiration=d.get("expiration"),
                option_type=(d.get("option_type") or "").lower(),
                dte=d.get("dte"),
                spot_at_alert=d.get("spot"),
                entry_price=d.get("mid_price") or d.get("entry_price"),
                target_spot=d.get("target"),
                stop_spot=d.get("stop"),
                gex_regime=d.get("regime"),
                king=d.get("king"),
                floor=d.get("floor_level"),
                ceiling=d.get("ceiling_level"),
                ivr_at_alert=d.get("iv_rank"),
                raw_alert={"source": "soe_signals_backfill"},
            )
            n += 1
        except Exception as e:
            print(f"[backfill] SOE row failed: {e}")
    return n


def backfill_flow_alerts() -> int:
    cutoff = time.time() - 7 * 86400
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT * FROM flow_alerts
               WHERE ts > ?
                 AND conviction IN ('HIGH', 'SWEEP', 'MEDIUM')
                 AND sentiment IN ('BULLISH', 'BEARISH')
               ORDER BY ts ASC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for r in rows:
        d = dict(r)
        sentiment = d.get("sentiment", "")
        try:
            log_alert(
                alert_type=f"FLOW_{d.get('conviction', '')}",
                ticker=d.get("ticker", ""),
                fired_at=float(d.get("ts", 0)),
                direction="BULL" if sentiment == "BULLISH" else "BEAR",
                score=d.get("vol_oi"),
                strike=d.get("strike"),
                expiration=d.get("expiration"),
                option_type=(d.get("option_type") or "").lower(),
                spot_at_alert=d.get("spot"),
                entry_price=d.get("last"),
                raw_alert={
                    "source": "flow_alerts_backfill",
                    "notional": d.get("notional"),
                    "vol": d.get("volume"),
                    "oi": d.get("oi"),
                },
            )
            n += 1
        except Exception:
            pass
    return n


def backfill_setup_forming() -> int:
    cutoff = time.time() - 7 * 86400
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM setup_forming WHERE ts > ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for r in rows:
        d = dict(r)
        try:
            spot = d.get("spot", 0) or 0
            king = d.get("king", 0) or 0
            direction = (
                "BULL" if king > spot
                else "BEAR" if king < spot
                else "NEUTRAL"
            )
            log_alert(
                alert_type="SETUP_FORMING",
                ticker=d.get("ticker", ""),
                fired_at=float(d.get("ts", 0)),
                direction=direction,
                score=d.get("score"),
                spot_at_alert=spot,
                target_spot=king,
                stop_spot=d.get("floor"),
                king=king,
                floor=d.get("floor"),
                gex_regime=d.get("regime"),
                ivr_at_alert=d.get("ivp"),
                raw_alert={"source": "setup_forming_backfill"},
            )
            n += 1
        except Exception:
            pass
    return n


def backfill_mir_signals() -> int:
    cutoff = time.time() - 7 * 86400
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT * FROM mir_message_log
               WHERE created_ts > ?
                 AND signal_type IN ('ENTRY', 'ADD', 'WATCH')
                 AND ticker IS NOT NULL
               ORDER BY created_ts ASC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for r in rows:
        d = dict(r)
        try:
            otype = (d.get("option_type") or "").lower()
            direction = (
                "BULL" if otype.startswith("c")
                else "BEAR" if otype.startswith("p")
                else "NEUTRAL"
            )
            log_alert(
                alert_type=f"MIR_{d.get('signal_type', '?')}",
                ticker=d.get("ticker", ""),
                fired_at=float(d.get("created_ts", 0)),
                direction=direction,
                grade=d.get("conviction"),
                strike=d.get("strike"),
                option_type=otype,
                raw_alert={"source": "mir_message_log_backfill"},
            )
            n += 1
        except Exception:
            pass
    return n


def backfill_zero_dte_alerts() -> int:
    if not Path(ZERO_DTE_DB).exists():
        return 0
    cutoff = time.time() - 7 * 86400
    conn = sqlite3.connect(ZERO_DTE_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM zero_dte_alerts WHERE fired_at > ? ORDER BY fired_at ASC",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for r in rows:
        d = dict(r)
        try:
            grade = d.get("grade", "?")
            log_alert(
                alert_type=f"ZERO_DTE_{grade.replace('+','P')}",
                ticker=d.get("ticker", ""),
                fired_at=float(d.get("fired_at", 0)),
                direction="BULL" if d.get("direction") == "bullish" else "BEAR",
                grade=grade,
                score=d.get("total_points"),
                strike=d.get("strike"),
                expiration=d.get("expiration"),
                option_type=(d.get("right") or "").lower(),
                dte=0,
                spot_at_alert=d.get("spot"),
                entry_price=d.get("est_entry_price"),
                target_premium=d.get("target_mid"),
                stop_premium=d.get("stop_mid"),
                gex_signal=d.get("gex_signal"),
                king=d.get("king_pos"),
                floor=d.get("king_neg"),
                raw_alert={"source": "zero_dte_alerts_backfill"},
            )
            n += 1
        except Exception:
            pass
    return n


async def main():
    print("=" * 60)
    print("ALERT OUTCOMES - HISTORICAL BACKFILL (V2)")
    print("=" * 60)
    print()

    print("[1/5] Backfilling SOE A/A+/B+ from soe_signals...")
    n_soe = backfill_soe_signals()
    print(f"      -> {n_soe} SOE alerts imported")

    print("[2/5] Backfilling directional flow_alerts (HIGH/MEDIUM/SWEEP)...")
    n_flow = backfill_flow_alerts()
    print(f"      -> {n_flow} flow alerts imported")

    print("[3/5] Backfilling SETUP_FORMING alerts...")
    n_setup = backfill_setup_forming()
    print(f"      -> {n_setup} setup_forming alerts imported")

    print("[4/5] Backfilling Mir signals from mir_message_log...")
    n_mir = backfill_mir_signals()
    print(f"      -> {n_mir} Mir signals imported")

    print("[5/5] Backfilling 0DTE engine alerts...")
    n_0dte = backfill_zero_dte_alerts()
    print(f"      -> {n_0dte} 0DTE alerts imported")

    total = n_soe + n_flow + n_setup + n_mir + n_0dte
    print()
    print(f"Total alerts logged: {total}")
    print()

    print("Running outcome backfill (Tradier history walk)...")
    stats = await backfill_outcomes(max_age_days=10)
    print(f"Outcome backfill stats: {stats}")
    print()

    from server.alert_outcomes import get_win_rate_by_type, get_win_rate_by_type_and_regime

    print("=" * 60)
    print("WIN RATE BY TYPE (last 30 days, EOD verdict)")
    print("=" * 60)
    print(f"{'Type':30s} {'n':>5s}  {'W':>4s}  {'L':>4s}  {'F':>4s}  {'WR%':>6s}  {'MFE%':>7s}  {'MAE%':>7s}")
    for r in get_win_rate_by_type(days=30):
        wr_str = f"{r['win_rate_eod']:.0f}" if r['win_rate_eod'] is not None else "-"
        mfe = f"{r['avg_mfe_pct']:+.2f}" if r['avg_mfe_pct'] is not None else "-"
        mae = f"{r['avg_mae_pct']:+.2f}" if r['avg_mae_pct'] is not None else "-"
        print(f"  {r['alert_type']:28s} {r['n']:>5d}  {r['wins_eod']:>4d}  "
              f"{r['losses_eod']:>4d}  {r['flat_eod']:>4d}  {wr_str:>5s}  {mfe:>7s}  {mae:>7s}")

    print()
    print(f"Data at: {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
