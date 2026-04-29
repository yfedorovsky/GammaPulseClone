"""Replay floor_migrations + structural_turn detectors against Apr 28 data.

Validates that the new detectors would have caught the 13:30 SPY/QQQ
bounce that today's audit identified as the trade of the day (+99-270%
on 0DTE calls).

Steps:
  1. Backfill floor_migrations on snapshots.db for the past 7 days
  2. Pull Apr 28 minute bars for SPY/QQQ from yfinance
  3. Walk through each minute (12:30-14:30) evaluating structural_turn
  4. Print a timeline showing gate-by-gate evolution + when 5/5 hits
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.floor_migration import run_backfill as floor_backfill
from server.structural_turn import (
    evaluate_turn, persist_event, STRUCTURAL_TURN_DB_PATH,
)

SNAPSHOTS_DB = "./snapshots.db"
FLOOR_DB = "./floor_migrations.db"
TICKERS = ["SPY", "QQQ"]


def load_snapshots(ticker: str, day: str = "2026-04-28") -> list[dict]:
    """Load all snapshots for a ticker on a given session day."""
    start_ts = int(datetime.fromisoformat(f"{day} 04:00:00").timestamp())
    end_ts = int(datetime.fromisoformat(f"{day} 20:00:00").timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT ts, spot, king, floor, ceiling, regime, signal,
                      pos_gex, neg_gex, net_delta
               FROM snapshots
               WHERE ticker = ? AND ts BETWEEN ? AND ?
               ORDER BY ts""",
            (ticker, start_ts, end_ts),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def load_minute_bars(ticker: str) -> list[dict]:
    """Pull 1-min bars from yfinance for today (regular session)."""
    df = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=False)
    df.index = df.index.tz_convert("America/New_York")
    out = []
    for t, row in df.iterrows():
        out.append({
            "ts": int(t.timestamp()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })
    return out


def main() -> int:
    print("=" * 70)
    print("Step 1: Backfill floor_migrations on past 7 days of snapshots")
    print("=" * 70)
    summary = floor_backfill(snapshot_db_path=SNAPSHOTS_DB, since_days=7)
    print(f"  Tickers scanned: {summary['tickers_scanned']}")
    print(f"  Total events:    {summary['events_total']}")
    print(f"  UP migrations:   {summary['up']}")
    print(f"  DOWN migrations: {summary['down']}")
    print(f"  Qualified UP:    {summary['qualified_up']}")
    print(f"  Reclaims:        {summary['reclaims']}")
    print()

    # Show today's qualified UP migrations on SPY/QQQ
    conn = sqlite3.connect(FLOOR_DB)
    conn.row_factory = sqlite3.Row
    today_start = int(datetime(2026, 4, 28, 0, 0).timestamp())
    today_end = int(datetime(2026, 4, 28, 23, 59).timestamp())
    print("=" * 70)
    print("Today's floor migrations on SPY/QQQ:")
    print("=" * 70)
    cur = conn.execute(
        """SELECT * FROM floor_migrations
           WHERE ticker IN ('SPY','QQQ') AND migration_ts BETWEEN ? AND ?
           ORDER BY migration_ts""",
        (today_start, today_end),
    )
    for r in cur:
        t = datetime.fromtimestamp(r["migration_ts"]).strftime("%H:%M:%S")
        rec = "RECLAIM" if r["is_reclaim"] else "      "
        qual = "Q" if r["qualified"] else "·"
        print(f"  {t}  {r['ticker']}  {r['direction']}  "
              f"${r['old_floor']:.0f}→${r['new_floor']:.0f}  "
              f"spot=${r['spot']:.2f}  {rec} [{qual}]  {r['qualified_reasons']}")
    conn.close()
    print()

    print("=" * 70)
    print("Step 2: Walk through 12:30-14:30 evaluating structural_turn each minute")
    print("=" * 70)

    for ticker in TICKERS:
        print(f"\n--- {ticker} ---")
        snaps = load_snapshots(ticker)
        if not snaps:
            print(f"  no snapshots for {ticker}")
            continue
        try:
            bars = load_minute_bars(ticker)
        except Exception as e:
            print(f"  yfinance error: {e}")
            continue

        # Walk through each minute from 12:30 to 14:30
        start = int(datetime(2026, 4, 28, 12, 30).timestamp())
        end = int(datetime(2026, 4, 28, 14, 30).timestamp())

        first_qualified_ts = None
        max_gates = 0
        max_gates_ts = None
        results = []
        for ts in range(start, end + 1, 60):
            ev = evaluate_turn(
                ticker, ts, direction="BULLISH",
                snapshots_in_window=snaps,
                minute_bars=bars,
                snapshots_db=SNAPSHOTS_DB,
                floor_migrations_db=FLOOR_DB,
            )
            persist_event(ev)
            if ev.gate_count > max_gates:
                max_gates = ev.gate_count
                max_gates_ts = ts
            if ev.qualified and first_qualified_ts is None:
                first_qualified_ts = ts
            results.append(ev)

        # Print the timeline summary
        print(f"  Best gate count: {max_gates}/5 at "
              f"{datetime.fromtimestamp(max_gates_ts).strftime('%H:%M') if max_gates_ts else 'N/A'}")
        if first_qualified_ts:
            print(f"  ✅ FIRST QUALIFIED 5/5: "
                  f"{datetime.fromtimestamp(first_qualified_ts).strftime('%H:%M:%S')}")
        else:
            print("  ❌ never reached 5/5")

        # Print every minute that had ≥3 gates active
        print()
        print(f"  Minutes with ≥3 gates passing:")
        print(f"  {'time':<8} {'gates':<7} {'spot':<8} {'floor':<6} {'short_reasons'}")
        for ev in results:
            if ev.gate_count < 3:
                continue
            t_str = datetime.fromtimestamp(ev.ts).strftime("%H:%M:%S")
            # Compact reasons
            short = []
            if ev.gate_floor_proximity:    short.append("flr-prox")
            if ev.gate_floor_event:        short.append("flr-evt")
            if ev.gate_volume_absorption:  short.append("vol-abs")
            if ev.gate_agg_flow:           short.append("agg-flow")
            if ev.gate_ncp_corroboration:  short.append("ncp")
            qstar = "⭐" if ev.qualified else "  "
            print(f"  {t_str:<8} {ev.gate_count}/5 {qstar} ${ev.spot:<7.2f} "
                  f"${ev.floor or 0:<5.0f} {','.join(short)}")

        # Show full reasons at the qualified moment
        if first_qualified_ts:
            qual_ev = next(e for e in results if e.ts == first_qualified_ts)
            print()
            print(f"  Full evidence at first 5/5 ({datetime.fromtimestamp(first_qualified_ts).strftime('%H:%M:%S')}):")
            for r in qual_ev.reasons:
                print(f"    {r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
