"""Backfill daily close prices into the snapshots table from Tradier history.

This gives IVP/RV/IVHV/RTS enough history to compute immediately, instead of
waiting 14+ more trading days for snapshots to accumulate organically.

SAFE: Only inserts real market close prices (spot column). Does NOT insert
synthetic IV, GEX, or signal data — those fields are left NULL.
IVP still needs ~14 days of live IV snapshots to unlock.

Usage:
    python -m server.backfill_closes          # Backfill Tier 1+2 (187 tickers)
    python -m server.backfill_closes --all    # Backfill all 328 tickers
    python -m server.backfill_closes SPY TSLA # Backfill specific tickers
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from datetime import datetime, timedelta

from .config import get_settings
from .tradier import TradierClient
from .tickers import TIER_1, TIER_2, all_tickers


async def backfill(tickers: list[str] | None = None, days: int = 252) -> dict[str, int]:
    """Backfill daily closes for the given tickers.

    Args:
        tickers: List of ticker symbols. If None, uses Tier 1+2.
        days: How many calendar days of history (default 252 = ~1 year trading days)

    Returns:
        Dict of {ticker: rows_inserted}
    """
    if tickers is None:
        tickers = list(TIER_1) + list(TIER_2)

    s = get_settings()
    conn = sqlite3.connect(s.snapshot_db)
    conn.row_factory = sqlite3.Row

    # Find existing backfill markers to avoid duplicates
    existing = set()
    rows = conn.execute(
        "SELECT DISTINCT ticker || ':' || date(ts, 'unixepoch') as key FROM snapshots"
    ).fetchall()
    for r in rows:
        existing.add(r["key"])
    print(f"[BACKFILL] {len(existing)} existing snapshot days in DB")

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    tradier = TradierClient()
    results: dict[str, int] = {}
    total_inserted = 0

    # Batch in groups to respect rate limits
    batch_size = 10
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        tasks = [tradier.history(t, interval="daily", start=start_date, end=end_date) for t in batch]
        bars_list = await asyncio.gather(*tasks, return_exceptions=True)

        for ticker, bars in zip(batch, bars_list):
            if isinstance(bars, Exception) or not bars:
                results[ticker] = 0
                continue

            inserted = 0
            for bar in bars:
                date_str = bar.get("time", "")
                close = bar.get("close", 0)
                if not date_str or not close:
                    continue

                # Check duplicate
                key = f"{ticker}:{date_str}"
                if key in existing:
                    continue

                # Convert date to unix timestamp (use 16:00 ET as market close)
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=16, minute=0)
                    ts = int(dt.timestamp())
                except ValueError:
                    continue

                # Insert as snapshot with only spot filled — no synthetic data
                conn.execute(
                    "INSERT INTO snapshots (ticker, ts, spot) VALUES (?, ?, ?)",
                    (ticker, ts, close),
                )
                existing.add(key)
                inserted += 1

            results[ticker] = inserted
            total_inserted += inserted

        conn.commit()
        done = min(i + batch_size, len(tickers))
        print(f"[BACKFILL] {done}/{len(tickers)} tickers processed, {total_inserted} rows inserted")

    await tradier.close()
    conn.close()

    return results


async def main():
    args = sys.argv[1:]

    if "--all" in args:
        tickers = list(all_tickers())
        args.remove("--all")
    elif args:
        tickers = [t.upper() for t in args]
    else:
        tickers = list(TIER_1) + list(TIER_2)

    print(f"[BACKFILL] Starting backfill for {len(tickers)} tickers (1 year daily closes)")
    start = time.time()

    results = await backfill(tickers)

    elapsed = time.time() - start
    filled = sum(1 for v in results.values() if v > 0)
    total = sum(results.values())
    print(f"\n[BACKFILL] Done in {elapsed:.1f}s — {total} rows inserted for {filled}/{len(tickers)} tickers")

    # Verify
    from .snapshots import get_daily_closes, compute_ivp, compute_realized_vol
    spy_closes = get_daily_closes("SPY", 365)
    spy_rv = compute_realized_vol(spy_closes, 20)
    print(f"[VERIFY] SPY daily closes: {len(spy_closes)} days")
    print(f"[VERIFY] SPY 20-day RV: {spy_rv}")
    print(f"[VERIFY] IVP still needs ~14 more days of live IV snapshots")


if __name__ == "__main__":
    asyncio.run(main())
