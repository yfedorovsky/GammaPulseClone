"""King Compression Scanner — feeder for the king-migration runner thesis.

Reads king_migrations.db and surfaces tickers where the +King level has
been pinned at the same strike for ≥ N trading days while spot grinds
toward it. The AMD-precursor pattern (pre-earnings 4/29 → +20% AH on
5/6) showed this loaded-coil setup; per the king-migration runner
backtest (n=174, 60% win rate at 4-6 migrations) these are upstream
candidates.

Run as part of the EOD routine:

    python scripts/king_compression_scanner.py [--min-days 5] [--out FILE]

Output CSV columns:
    ticker, king_level, days_pinned, last_seen, current_spot,
    distance_to_king_pct, loaded_coil

`loaded_coil` is 1 when |distance_to_king_pct| < 3%.

Sources
-------
king_migrations.db ........ pinned-run discovery (last migration → today)
snapshots.db (optional) ... fresher current_spot lookup; falls back to
                            the spot recorded on the last migration row.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys
import time
from typing import Iterable

DEFAULT_KING_DB = os.environ.get("KING_MIGRATION_DB_PATH", "./king_migrations.db")
DEFAULT_SNAPSHOTS_DB = os.environ.get("SNAPSHOTS_DB_PATH", "./snapshots.db")

MIN_DAYS_PINNED = 5
LOADED_COIL_PCT = 3.0  # |distance_to_king| < 3% = loaded


def _trading_days_between(start_ts: int, end_ts: int) -> int:
    """Weekday count between two UTC timestamps. Holidays are not
    excluded — close enough at the resolution this scanner cares about
    (5+ days). Both ends inclusive of start, exclusive of end."""
    if end_ts <= start_ts:
        return 0
    d0 = dt.datetime.fromtimestamp(start_ts, dt.timezone.utc).date()
    d1 = dt.datetime.fromtimestamp(end_ts, dt.timezone.utc).date()
    days = 0
    cur = d0
    while cur < d1:
        if cur.weekday() < 5:
            days += 1
        cur = cur + dt.timedelta(days=1)
    return days


def _latest_migration_per_ticker(king_db: str) -> list[dict]:
    """Most recent king_migrations row per ticker. Each row's `new_king`
    is the king level the ticker has been pinned at since `migration_ts`."""
    conn = sqlite3.connect(king_db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT k.ticker, k.migration_ts, k.migration_iso,
                   k.new_king, k.spot AS migration_spot
            FROM king_migrations k
            JOIN (
                SELECT ticker, MAX(migration_ts) AS max_ts
                FROM king_migrations
                GROUP BY ticker
            ) m ON m.ticker = k.ticker AND m.max_ts = k.migration_ts
            ORDER BY k.ticker
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _latest_spots(snapshots_db: str, tickers: Iterable[str]) -> dict[str, float]:
    """Most recent spot per ticker from snapshots.db; empty dict if the
    file is missing (scanner still works using migration_spot as fallback)."""
    if not os.path.exists(snapshots_db):
        return {}
    conn = sqlite3.connect(snapshots_db)
    conn.row_factory = sqlite3.Row
    out: dict[str, float] = {}
    try:
        for t in tickers:
            r = conn.execute(
                "SELECT spot FROM snapshots WHERE ticker = ? AND spot IS NOT NULL "
                "ORDER BY ts DESC LIMIT 1",
                (t.upper(),),
            ).fetchone()
            if r and r["spot"]:
                out[t.upper()] = float(r["spot"])
        return out
    finally:
        conn.close()


def scan(
    king_db: str = DEFAULT_KING_DB,
    snapshots_db: str = DEFAULT_SNAPSHOTS_DB,
    min_days: int = MIN_DAYS_PINNED,
) -> list[dict]:
    """Return one row per ticker whose king has been pinned ≥ min_days."""
    rows = _latest_migration_per_ticker(king_db)
    if not rows:
        return []
    spots = _latest_spots(snapshots_db, [r["ticker"] for r in rows])
    now_ts = int(time.time())

    out: list[dict] = []
    for r in rows:
        king = r["new_king"]
        if king is None:
            continue
        days = _trading_days_between(int(r["migration_ts"]), now_ts)
        if days < min_days:
            continue
        spot = spots.get(r["ticker"], r["migration_spot"])
        if not spot:
            continue
        dist_pct = (spot - king) / king * 100.0
        out.append({
            "ticker": r["ticker"],
            "king_level": round(float(king), 2),
            "days_pinned": days,
            "last_seen": r["migration_iso"],
            "current_spot": round(float(spot), 2),
            "distance_to_king_pct": round(dist_pct, 2),
            "loaded_coil": 1 if abs(dist_pct) < LOADED_COIL_PCT else 0,
        })
    out.sort(key=lambda x: (-x["loaded_coil"], abs(x["distance_to_king_pct"])))
    return out


def write_csv(rows: list[dict], path: str) -> None:
    fields = [
        "ticker", "king_level", "days_pinned", "last_seen",
        "current_spot", "distance_to_king_pct", "loaded_coil",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="King compression scanner — EOD feeder.")
    p.add_argument("--king-db", default=DEFAULT_KING_DB)
    p.add_argument("--snapshots-db", default=DEFAULT_SNAPSHOTS_DB)
    p.add_argument("--min-days", type=int, default=MIN_DAYS_PINNED)
    p.add_argument("--out", default=None,
                   help="CSV output path (default: ./king_compression_YYYYMMDD.csv)")
    args = p.parse_args(argv)

    rows = scan(args.king_db, args.snapshots_db, args.min_days)
    out_path = args.out or f"./king_compression_{dt.date.today():%Y%m%d}.csv"
    write_csv(rows, out_path)

    coils = sum(1 for r in rows if r["loaded_coil"])
    print(f"Wrote {len(rows)} pinned tickers ({coils} loaded coils <{LOADED_COIL_PCT:.0f}%) -> {out_path}")
    for r in rows[:10]:
        flag = "**" if r["loaded_coil"] else "  "
        print(
            f"  {flag} {r['ticker']:<6} king ${r['king_level']:>8.2f}  "
            f"spot ${r['current_spot']:>8.2f}  dist {r['distance_to_king_pct']:>+6.2f}%  "
            f"pinned {r['days_pinned']}d (since {r['last_seen'][:10]})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
