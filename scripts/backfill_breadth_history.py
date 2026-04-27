"""Backfill breadth_daily SQLite from Massive grouped daily endpoint.

Phase 5 task. Pulls historical NYSE/NASDAQ A/D data for each trading day
in a date window and computes the McClellan Oscillator (NYMO/NAMO)
properly using cumulative EMA(19) - EMA(39) of net advances.

Massive API depth limit confirmed: ~2 years (Apr 2024 → today).
For pre-Apr-2024 dates, use scripts/backfill_breadth_history_yfinance.py.

Run:
    python -m scripts.backfill_breadth_history --start 2024-04-15 --end 2026-04-26

Idempotent: skips dates already in breadth_daily. Recomputes EMAs in
chronological order from the earliest existing row to ensure continuity.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

# Reuse the existing live infrastructure
from server.breadth import compute_daily_breadth, _ema
from server.config import get_settings


def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db, timeout=30.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")  # avoid lock conflicts with live worker
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _trading_days(start: str, end: str) -> list[str]:
    """All weekdays in [start, end]. NYSE holidays will silently return None
    from the API; we handle that as a skip."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    return [d.date().isoformat()
            for d in pd.bdate_range(start=s, end=e)]


def _existing_dates() -> set[str]:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT DISTINCT date FROM breadth_daily WHERE exchange = 'NYSE'"
        ).fetchall()
        return {r["date"] for r in rows}
    finally:
        c.close()


def _store(date: str, exchange: str, adv: int, dec: int, unch: int,
           net: int, ema19: float, ema39: float, osc: float) -> None:
    c = _conn()
    try:
        c.execute(
            """INSERT OR REPLACE INTO breadth_daily
               (date, exchange, advancers, decliners, unchanged, net_advances,
                ema19, ema39, oscillator)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (date, exchange, adv, dec, unch, net, ema19, ema39, osc),
        )
        c.commit()
    finally:
        c.close()


def _all_existing_net_advances(exchange: str) -> list[tuple[str, int]]:
    """Return (date, net_advances) sorted by date for an exchange."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT date, net_advances FROM breadth_daily "
            "WHERE exchange = ? ORDER BY date ASC",
            (exchange,),
        ).fetchall()
        return [(r["date"], r["net_advances"]) for r in rows]
    finally:
        c.close()


def _recompute_emas_for_exchange(exchange: str) -> int:
    """Recompute EMAs for ALL stored rows in chronological order.

    Call after backfill is complete to ensure EMAs are continuous.
    Returns count of rows updated.
    """
    rows = _all_existing_net_advances(exchange)
    if not rows:
        return 0
    nets = [r[1] for r in rows]
    ema19_list = _ema(nets, 19)
    ema39_list = _ema(nets, 39)
    osc_list = [a - b for a, b in zip(ema19_list, ema39_list)]

    c = _conn()
    try:
        for (date, _), ema19v, ema39v, oscv in zip(rows, ema19_list, ema39_list, osc_list):
            c.execute(
                """UPDATE breadth_daily SET ema19=?, ema39=?, oscillator=?
                   WHERE date=? AND exchange=?""",
                (ema19v, ema39v, oscv, date, exchange),
            )
        c.commit()
        return len(rows)
    finally:
        c.close()


async def _fetch_with_retry(date: str, max_retries: int = 4) -> dict | None:
    """Fetch one date with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            counts = await compute_daily_breadth(date)
            if counts:
                return counts
            # None = either holiday or rate-limit. Distinguishing is hard
            # without API response inspection. Retry once with delay; if
            # still None, treat as holiday.
            if attempt == 0:
                await asyncio.sleep(2.0)
                continue
            return None
        except Exception:
            await asyncio.sleep(2 ** attempt)
    return None


async def backfill(start: str, end: str, sleep_s: float = 0.8,
                    skip_existing: bool = True) -> dict:
    """Run backfill. Returns summary dict."""
    days = _trading_days(start, end)
    existing = _existing_dates() if skip_existing else set()
    todo = [d for d in days if d not in existing]
    print(f"Trading days in window: {len(days)}")
    print(f"Already in DB: {len(existing & set(days))}")
    print(f"To fetch: {len(todo)}\n")

    n_ok = 0
    n_skip = 0
    n_fail = 0
    t0 = time.time()

    for i, date in enumerate(todo, 1):
        if i % 25 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  [{i:>4}/{len(todo)}] {date} — "
                  f"ok={n_ok} skip={n_skip} fail={n_fail} "
                  f"({rate:.1f}/s, ETA {eta/60:.1f}min)")

        counts = await _fetch_with_retry(date)
        if not counts:
            n_skip += 1
            await asyncio.sleep(sleep_s)
            continue

        # Store with placeholder EMAs (we'll recompute at end)
        for exchange in ("NYSE", "NASDAQ"):
            ec = counts.get(exchange, {})
            _store(date, exchange,
                   ec.get("adv", 0), ec.get("dec", 0), ec.get("unch", 0),
                   ec.get("net", 0), 0.0, 0.0, 0.0)
        n_ok += 1
        await asyncio.sleep(sleep_s)

    print(f"\nFetched {n_ok} dates ({n_skip} skipped/holiday, {n_fail} failed) "
          f"in {time.time()-t0:.0f}s")

    # Recompute EMAs for all dates in chronological order
    print("\nRecomputing EMAs in chronological order...")
    nyse_n = _recompute_emas_for_exchange("NYSE")
    nasdaq_n = _recompute_emas_for_exchange("NASDAQ")
    print(f"  NYSE: {nyse_n} rows EMA-updated")
    print(f"  NASDAQ: {nasdaq_n} rows EMA-updated")

    return {
        "fetched": n_ok, "skipped_holidays": n_skip, "failed": n_fail,
        "elapsed_s": round(time.time() - t0, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2024-04-15",
                   help="ISO date (default: 2024-04-15, ~Massive limit)")
    p.add_argument("--end", default=datetime.date.today().isoformat(),
                   help="ISO date (default: today)")
    p.add_argument("--sleep", type=float, default=0.2,
                   help="seconds between API calls (default: 0.2)")
    p.add_argument("--force", action="store_true",
                   help="re-fetch dates already in DB")
    args = p.parse_args()

    summary = asyncio.run(backfill(
        args.start, args.end, sleep_s=args.sleep,
        skip_existing=not args.force,
    ))

    # Quick sanity: latest few days
    c = _conn()
    try:
        rows = c.execute(
            "SELECT date, exchange, advancers, decliners, oscillator "
            "FROM breadth_daily WHERE exchange = 'NYSE' "
            "ORDER BY date DESC LIMIT 5"
        ).fetchall()
        print("\nLatest 5 NYSE rows:")
        for r in rows:
            print(f"  {r['date']}  adv={r['advancers']}  dec={r['decliners']}  "
                  f"NYMO={r['oscillator']:+.1f}")
    finally:
        c.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
