"""Backfill INFORMED FLOW tags onto today's flow_alerts rows.

Today's 334K flow_alerts were captured before the v1 INSIDER PATTERN
schema migration (commit a2809c4) was applied — the migration runs at
backend boot, which hasn't happened yet. So even after restart, today's
historical rows will show is_insider=0 by default.

This script:
  1. Adds the 3 informed-flow columns to flow_alerts table if missing
     (mirrors what the auto-migration does on next boot)
  2. Re-runs the v2 classifier (Batch 1+2+3a + V/OI hard gate + dedup)
     over today's rows
  3. Persists is_insider, insider_score, insider_reasons on qualifying rows
     so the InsiderStrip UI populates with today's catches

Idempotent: safe to run multiple times. Uses widened-window dedup so all
META 5/27 0DTE fires across the day are tagged (not just the first).

Run from project root:
    python -m scripts.backfill_informed_flow_today
"""
from __future__ import annotations

import sqlite3
import sys
import io
from datetime import datetime, date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.flow_alerts import (  # noqa: E402
    _classify_insider_signature,
    _detect_side, _detect_sentiment,
)


DB = ROOT / "snapshots.db"


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # (A) Ensure schema columns exist
    print("=== Step 1: Schema migration ===")
    migrations = [
        "ALTER TABLE flow_alerts ADD COLUMN insider_score INTEGER DEFAULT 0",
        "ALTER TABLE flow_alerts ADD COLUMN is_insider INTEGER DEFAULT 0",
        "ALTER TABLE flow_alerts ADD COLUMN insider_reasons TEXT",
    ]
    for m in migrations:
        try:
            conn.execute(m)
            print(f"  + applied: {m}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  · already present: {m.split('COLUMN')[1].split()[0]}")
            else:
                print(f"  ! error: {e}")
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_insider ON flow_alerts(is_insider, ts) WHERE is_insider = 1"
        )
        print("  + index idx_flow_insider")
    except sqlite3.OperationalError as e:
        print(f"  · index: {e}")
    conn.commit()
    print()

    # (B) Re-classify today's rows
    today_start = int(datetime(date.today().year, date.today().month,
                                date.today().day, 0, 0).timestamp())
    rows = conn.execute(
        """SELECT * FROM flow_alerts WHERE ts >= ? ORDER BY ts""",
        (today_start,),
    ).fetchall()
    print(f"=== Step 2: Re-classify {len(rows):,} flow_alerts from today ===")

    # Backfill DOES NOT dedup — we want every qualifying historical fire
    # to be tagged. (Live runtime dedup is for Telegram suppression, not
    # for DB persistence — every qualifying alert should be findable in
    # the UI strip regardless of repeat-fire status.)
    qualified = 0
    sanity_gate = 0
    notional_gate = 0
    vol_oi_gate = 0
    expired_gate = 0
    per_ticker: dict[str, int] = {}

    updates: list[tuple] = []
    for r in rows:
        alert = dict(r)
        oi = alert.get("oi", 0) or 0
        vol = alert.get("volume", 0) or 0
        notional = alert.get("notional", 0) or 0
        if oi < 100 and vol < 500:
            sanity_gate += 1
            continue
        if notional < 10_000:
            notional_gate += 1
            continue
        if (alert.get("vol_oi", 0) or 0) < 10:
            vol_oi_gate += 1
            continue
        # Re-derive side (post-P0 fix). Historical sentiment column has
        # the MID-of-spread bias for many fires.
        bid = alert.get("bid", 0) or 0
        ask = alert.get("ask", 0) or 0
        last = alert.get("last_price") or alert.get("last") or 0
        side_now = _detect_side(bid, ask, last,
                                 delta=alert.get("delta", 0) or 0,
                                 vol=vol, oi=oi, notional=notional)
        sent_now = _detect_sentiment(
            (alert.get("option_type") or "").lower(), side_now)
        alert["side"] = side_now
        alert["sentiment"] = sent_now

        score, reasons = _classify_insider_signature(alert)
        if score < 5:
            continue
        qualified += 1
        per_ticker[alert.get("ticker", "?")] = per_ticker.get(alert.get("ticker", "?"), 0) + 1
        updates.append((
            1,                          # is_insider
            score,                      # insider_score
            ",".join(reasons),          # insider_reasons (comma-joined)
            sent_now,                   # updated sentiment (post-P0 fix)
            side_now,                   # updated side
            alert["id"],
        ))

    print(f"  Filtered (sanity oi<100 AND vol<500): {sanity_gate:,}")
    print(f"  Filtered (notional < $10K):           {notional_gate:,}")
    print(f"  Filtered (V/OI < 10x):                {vol_oi_gate:,}")
    print(f"  QUALIFIED (score >= 5):               {qualified:,}")
    print()

    # (C) Write the updates
    if updates:
        print(f"=== Step 3: Persisting {len(updates):,} tag updates ===")
        conn.executemany(
            """UPDATE flow_alerts
               SET is_insider = ?, insider_score = ?, insider_reasons = ?,
                   sentiment = ?, side = ?
               WHERE id = ?""",
            updates,
        )
        conn.commit()
        print(f"  + wrote {len(updates)} rows to DB")
    else:
        print("=== Step 3: Nothing to persist ===")
    print()

    # (D) Top tickers tagged
    print(f"=== Top tickers by INFORMED FLOW tags today ===")
    for t, n in sorted(per_ticker.items(), key=lambda x: -x[1])[:15]:
        print(f"  {t:>8}: {n:>4}")
    print()

    # (E) Verify META catches are findable
    print(f"=== META 5/27 0DTE catches now visible to UI ===")
    meta_rows = conn.execute(
        """SELECT ts, strike, option_type, sentiment, side, vol_oi, ask, spot,
                  notional, insider_score, insider_reasons
           FROM flow_alerts
           WHERE ticker = 'META' AND expiration = '2026-05-27'
             AND is_insider = 1
           ORDER BY ts""",
    ).fetchall()
    print(f"  Total: {len(meta_rows)}")
    for r in meta_rows[:20]:
        dt = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        print(f"  {dt} ${r['strike']}{(r['option_type'] or '')[0].upper()} "
              f"V/OI={r['vol_oi']:.1f}x ask=${r['ask'] or 0:.2f} "
              f"spot=${r['spot'] or 0:.2f} "
              f"{r['sentiment']:>9} score={r['insider_score']}/6 "
              f"${r['notional']:,.0f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
