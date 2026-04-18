"""Backfill ISO sweep data from ThetaData history into the flow_alerts DB.

The live sweep detector only writes from the WebSocket stream, which runs
during market hours. This script uses the `/v3/option/history/trade`
endpoint to pull historical sweeps for past sessions and feed them into
the same table — so the SWEEPS UI tab is populated immediately.

Usage
-----
    # Backfill today's session for the MVP watchlist
    python scripts/backfill_sweeps.py --date 2026-04-17

    # Backfill last 5 trading days
    python scripts/backfill_sweeps.py --days-back 5

    # Backfill for specific tickers only
    python scripts/backfill_sweeps.py --days-back 3 --tickers SPY,QQQ,NVDA

    # Dry-run: print what it would insert without touching DB
    python scripts/backfill_sweeps.py --date 2026-04-17 --dry-run

What it does
------------
1. For each ticker, pulls the current (or last-cached) spot from Theta.
2. For each (ticker × date × expiration × strike × right) in the watchlist:
   GET /v3/option/history/trade?symbol=...&date=...&expiration=...&strike=...&right=...
3. Filters prints where `condition IN (95, 126, 128)` (ISO sweep family).
4. Groups prints into 30-second contract-level windows (same rule as live).
5. Skips rollups below MIN_SWEEP_NOTIONAL ($50K) to match live behavior.
6. Inserts into `flow_alerts` table via `insert_sweep_alert()`.

Caveats
-------
- Uses TODAY'S spot price to pick ATM strikes for all historical dates.
  If a ticker has drifted materially (>10%) since the backfill day, some
  far-OTM sweeps won't be fetched. Acceptable for MVP — most sweep
  activity clusters near ATM anyway.
- Concurrent-request cap on Standard tier is 4. We respect it via a
  semaphore in ThetaDataClient. Expect ~90-120s per ticker per day.
- Idempotency: the `flow_alerts` table has no unique constraint on the
  (ts, ticker, strike, expiration) tuple, so re-running a backfill
  DUPLICATES rows. Pass --clean-first to truncate existing sweep rows
  before inserting.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Make `server.` package importable when running from the scripts/ dir
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.config import get_settings
from server.flow_alerts import init_alert_db, insert_sweep_alert
from server.thetadata import (
    ISO_SWEEP_CONDITIONS,
    NON_ISO_AUCTION_CONDITIONS,
    EXCLUDE_CONDITIONS,
    ThetaDataClient,
)
from server.sweep_detector import (
    ROLLUP_SECONDS,
    MIN_SWEEP_NOTIONAL,
    MVP_WATCHLIST_ROOTS,
)


# ── Args ────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill ISO sweeps from ThetaData history")
    p.add_argument(
        "--date", type=str, default=None,
        help="Single date YYYY-MM-DD (defaults to today). Mutually exclusive with --days-back.",
    )
    p.add_argument(
        "--days-back", type=int, default=0,
        help="Backfill the last N trading days (weekends skipped). Ignores --date.",
    )
    p.add_argument(
        "--tickers", type=str, default=None,
        help="Comma-separated tickers. Defaults to MVP watchlist (14 names).",
    )
    p.add_argument(
        "--strikes", type=int, default=10,
        help="ATM ± this many strikes (per right). Default 10.",
    )
    p.add_argument(
        "--expirations", type=int, default=3,
        help="Number of upcoming M/W/F expirations per date. Default 3.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be inserted without writing to DB.",
    )
    p.add_argument(
        "--clean-first", action="store_true",
        help="DELETE existing sweep rows for the date range before inserting (idempotent reruns).",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Log per-contract progress.",
    )
    return p.parse_args()


# ── Date planning ───────────────────────────────────────────────────


def resolve_date_range(args: argparse.Namespace) -> list[dt.date]:
    """Expand --date OR --days-back into a concrete list of trading dates."""
    today = dt.date.today()
    if args.days_back > 0:
        dates: list[dt.date] = []
        d = today
        while len(dates) < args.days_back:
            if d.weekday() < 5:  # Mon=0..Fri=4
                dates.append(d)
            d -= dt.timedelta(days=1)
        return sorted(dates)

    if args.date:
        parsed = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        parsed = today

    if parsed.weekday() >= 5:
        print(f"[BACKFILL] {parsed} is a weekend — no OPRA data. Skipping.")
        return []
    return [parsed]


def expirations_after(d: dt.date, n: int) -> list[dt.date]:
    """Next N M/W/F expirations at or after date d (SPY/QQQ-style cadence)."""
    out: list[dt.date] = []
    cursor = d
    # Include the date itself if it's M/W/F (0DTE scenario)
    # Walk up to 21 days forward
    for i in range(0, 21):
        c = cursor + dt.timedelta(days=i)
        if c >= d and c.weekday() in (0, 2, 4):
            out.append(c)
            if len(out) >= n:
                break
    return out


# ── Spot lookup (for ATM strike planning) ───────────────────────────


async def get_spot_price(client: ThetaDataClient, ticker: str) -> float | None:
    """Pull spot via Theta's Greeks snapshot (the bulk endpoint returns
    underlying_price inline on every row). Falls back to None if the call
    errors or returns no data.

    We don't need absolute precision here — only ATM ± 10 strike bucket.
    """
    rows, spot = await client.snapshot_chain_greeks(ticker, expiration="*")
    return spot


def atm_strikes(spot: float, step: float, radius: int) -> list[float]:
    atm = round(spot / step) * step
    return [atm + i * step for i in range(-radius, radius + 1)]


def infer_strike_step(spot: float) -> float:
    """Heuristic: larger-priced tickers need larger strike steps.

    SPY $700  → $1
    NVDA $150 → $1
    AAPL $200 → $2.5
    BKNG $5000 → $50
    """
    if spot < 50:
        return 0.5
    if spot < 200:
        return 1.0
    if spot < 500:
        return 2.5
    if spot < 1000:
        return 5.0
    if spot < 5000:
        return 25.0
    return 50.0


# ── Rollup (mirrors sweep_detector.SweepRollup behavior) ────────────


class BackfillRollup:
    """Per-contract sweep aggregation window for backfill.

    We reimplement (rather than import) because the live detector's
    SweepRollup is designed for streaming where window_start = wall time;
    in backfill the window boundaries come from the trade timestamps.
    """

    def __init__(self, ticker: str, strike: float, expiration: str, option_type: str, window_start_ts: int):
        self.ticker = ticker
        self.strike = strike
        self.expiration = expiration
        self.option_type = option_type
        self.window_start_ts = window_start_ts   # epoch seconds

        self.total_contracts = 0
        self.total_notional = 0.0
        self.print_count = 0
        self.exchanges: set[int] = set()
        self.prices: list[float] = []
        self.first_price = 0.0
        self.last_price = 0.0

    def add(self, size: int, price: float, exchange: int) -> None:
        if self.print_count == 0:
            self.first_price = price
        self.print_count += 1
        self.total_contracts += size
        self.total_notional += size * price * 100.0
        self.exchanges.add(exchange)
        self.prices.append(price)
        self.last_price = price

    @property
    def venue_count(self) -> int:
        return len(self.exchanges)

    @property
    def avg_price(self) -> float:
        return sum(self.prices) / len(self.prices) if self.prices else 0.0

    def to_payload(self, spot: float | None, oi: int | None, iv: float | None, delta: float | None, bid: float | None, ask: float | None) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strike": self.strike,
            "expiration": self.expiration,
            "option_type": self.option_type,
            "sweep_notional": round(self.total_notional, 2),
            "sweep_contracts": self.total_contracts,
            "sweep_venues": self.venue_count,
            "sweep_prints": self.print_count,
            "sweep_side": "NEUTRAL",   # same as live detector MVP — classifier is follow-up
            "sweep_window_s": ROLLUP_SECONDS,
            "last": self.last_price,
            "bid": bid,
            "ask": ask,
            "iv": iv,
            "delta": delta,
            "oi": oi,
            "spot": spot,
        }


# ── Trade parsing ───────────────────────────────────────────────────


def parse_ms_timestamp(ts_str: str, date_obj: dt.date) -> int:
    """Parse Theta's ISO timestamp into epoch seconds.

    Theta returns timestamps like '2026-04-16T09:30:02.109' (ET, no tz
    suffix). We treat as ET since that's what OPRA always uses.
    """
    try:
        # Ignore sub-second + treat as ET wall time
        main = ts_str.split(".")[0]  # strip milliseconds
        d = dt.datetime.strptime(main, "%Y-%m-%dT%H:%M:%S")
        return int(d.timestamp())
    except (ValueError, TypeError):
        # Fallback: use the date at market open
        return int(dt.datetime.combine(date_obj, dt.time(9, 30)).timestamp())


def rollup_trades(
    ticker: str, strike: float, expiration: str, option_type: str,
    rows: list[dict[str, str]], date_obj: dt.date,
) -> list[BackfillRollup]:
    """Bucket raw trade prints into 30s rollup windows, ISO-only.

    Returns only rollups that meet the live detector's minimum criteria.
    """
    buckets: dict[int, BackfillRollup] = {}  # bucket_start_ts -> rollup

    for r in rows:
        try:
            cond = int(r.get("condition") or 0)
        except ValueError:
            continue
        # Same filter order as live detector
        if cond in EXCLUDE_CONDITIONS:
            continue
        if cond in NON_ISO_AUCTION_CONDITIONS:
            continue
        if cond not in ISO_SWEEP_CONDITIONS:
            continue

        try:
            size = int(r.get("size") or 0)
            price = float(r.get("price") or 0)
            exch = int(r.get("exchange") or 0)
        except (ValueError, TypeError):
            continue
        if size <= 0 or price <= 0:
            continue

        ts_str = r.get("timestamp", "")
        ts_epoch = parse_ms_timestamp(ts_str, date_obj)
        # Quantize to 30-second bucket
        bucket_start = (ts_epoch // ROLLUP_SECONDS) * ROLLUP_SECONDS

        rollup = buckets.get(bucket_start)
        if rollup is None:
            rollup = BackfillRollup(
                ticker=ticker,
                strike=strike,
                expiration=expiration,
                option_type=option_type,
                window_start_ts=bucket_start,
            )
            buckets[bucket_start] = rollup
        rollup.add(size, price, exch)

    return [r for r in buckets.values() if r.total_notional >= MIN_SWEEP_NOTIONAL]


# ── Clean helper ────────────────────────────────────────────────────


@contextmanager
def _db_conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def clean_existing_sweeps(dates: list[dt.date], tickers: list[str]) -> int:
    """Delete existing sweep rows in the given date range (for idempotent reruns).

    Uses the `ts` column (epoch seconds). Each date's window is [00:00 ET, 23:59 ET).
    """
    if not dates:
        return 0
    start = int(dt.datetime.combine(dates[0], dt.time.min).timestamp())
    end = int(dt.datetime.combine(dates[-1], dt.time.max).timestamp())
    ticker_filter = ",".join(f"'{t}'" for t in tickers)
    with _db_conn() as c:
        cur = c.execute(
            f"DELETE FROM flow_alerts WHERE is_sweep = 1 AND ts BETWEEN ? AND ? "
            f"AND ticker IN ({ticker_filter})",
            (start, end),
        )
        return cur.rowcount


# ── Insert helper that honors the ORIGINAL sweep timestamp ──────────
#
# The existing `insert_sweep_alert()` stamps `ts = int(time.time())`, which
# is wrong for backfill — the alert would show as "just now" in the UI.
# We duplicate its SQL here with a configurable ts.


def insert_sweep_with_ts(rollup_payload: dict[str, Any], ts_epoch: int) -> None:
    with _db_conn() as c:
        c.execute(
            """INSERT INTO flow_alerts
            (ts, ticker, strike, expiration, option_type, volume, oi, vol_oi,
             last_price, bid, ask, side, sentiment, iv, delta, notional, spot,
             conviction, status, is_sweep, sweep_side, sweep_notional,
             sweep_contracts, sweep_venues, sweep_prints, sweep_window_s)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts_epoch,
                rollup_payload["ticker"],
                rollup_payload["strike"],
                rollup_payload["expiration"],
                rollup_payload["option_type"],
                rollup_payload.get("sweep_contracts"),
                rollup_payload.get("oi"),
                None,
                rollup_payload.get("last"),
                rollup_payload.get("bid"),
                rollup_payload.get("ask"),
                rollup_payload.get("sweep_side"),
                rollup_payload.get("sweep_side"),
                rollup_payload.get("iv"),
                rollup_payload.get("delta"),
                rollup_payload.get("sweep_notional"),
                rollup_payload.get("spot"),
                "SWEEP",
                "OPEN",
                1,
                rollup_payload.get("sweep_side"),
                rollup_payload.get("sweep_notional"),
                rollup_payload.get("sweep_contracts"),
                rollup_payload.get("sweep_venues"),
                rollup_payload.get("sweep_prints"),
                rollup_payload.get("sweep_window_s"),
            ),
        )


# ── Main pipeline ───────────────────────────────────────────────────


async def backfill_contract(
    client: ThetaDataClient,
    ticker: str, strike: float, expiration: dt.date, right: str,
    date_obj: dt.date, spot: float | None, verbose: bool = False,
) -> list[BackfillRollup]:
    """Fetch one contract's trades for one date and return ISO rollups."""
    exp_str = expiration.strftime("%Y-%m-%d")
    right_long = "call" if right == "C" else "put"
    date_str = date_obj.strftime("%Y-%m-%d")

    rows = await client.history_trades(
        ticker=ticker,
        expiration=exp_str,
        strike=strike,
        right=right_long,
        date=date_str,
    )

    if not rows:
        return []

    rollups = rollup_trades(
        ticker=ticker, strike=strike, expiration=exp_str,
        option_type=right_long, rows=rows, date_obj=date_obj,
    )

    if verbose and rollups:
        total = sum(r.total_notional for r in rollups)
        print(
            f"  {ticker} ${strike:.0f}{right} {exp_str} {date_str}: "
            f"{len(rollups)} sweeps, ${total:,.0f} notional",
            flush=True,
        )

    return rollups


async def backfill_ticker_date(
    client: ThetaDataClient, ticker: str, date_obj: dt.date,
    strikes_radius: int, expirations_n: int, verbose: bool,
) -> tuple[int, float]:
    """Backfill one (ticker, date) pair. Returns (rollup_count, total_notional)."""
    spot = await get_spot_price(client, ticker)
    if not spot or spot <= 0:
        print(f"[BACKFILL] {ticker}: no spot available, skipping {date_obj}")
        return 0, 0.0

    step = infer_strike_step(spot)
    strikes = atm_strikes(spot, step, strikes_radius)
    exps = expirations_after(date_obj, expirations_n)
    if not exps:
        return 0, 0.0

    if verbose:
        print(f"[BACKFILL] {ticker} {date_obj}: spot=${spot:.2f} step=${step} strikes={strikes[0]:.0f}-{strikes[-1]:.0f} exps={[e.isoformat() for e in exps]}")

    # Build tasks — but honor the REST concurrency cap via the client's semaphore
    tasks = []
    for exp in exps:
        for strike in strikes:
            for right in ("C", "P"):
                tasks.append(backfill_contract(
                    client, ticker, strike, exp, right, date_obj, spot, verbose,
                ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    rollup_count = 0
    total_notional = 0.0
    for res in results:
        if isinstance(res, Exception):
            continue
        for rollup in res:
            payload = rollup.to_payload(
                spot=spot, oi=None, iv=None, delta=None, bid=None, ask=None,
            )
            insert_sweep_with_ts(payload, rollup.window_start_ts)
            rollup_count += 1
            total_notional += rollup.total_notional

    return rollup_count, total_notional


async def main() -> int:
    args = parse_args()

    dates = resolve_date_range(args)
    if not dates:
        print("[BACKFILL] No dates to process.")
        return 1

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else MVP_WATCHLIST_ROOTS
    )

    print(f"[BACKFILL] Plan: {len(tickers)} tickers × {len(dates)} dates")
    print(f"[BACKFILL] Tickers: {', '.join(tickers)}")
    print(f"[BACKFILL] Dates:   {', '.join(d.isoformat() for d in dates)}")
    print(f"[BACKFILL] Strikes: ATM ±{args.strikes} | Expirations: next {args.expirations} M/W/F")

    init_alert_db()

    if args.clean_first and not args.dry_run:
        removed = clean_existing_sweeps(dates, tickers)
        print(f"[BACKFILL] Cleaned {removed} existing sweep rows for range.")

    if args.dry_run:
        print("[BACKFILL] DRY-RUN — would write to DB; inserting nothing.")
        # Still exercise the pipeline for validation; substitute a no-op insert.
        global insert_sweep_with_ts
        _real_insert = insert_sweep_with_ts
        def _noop(payload, ts):
            pass
        insert_sweep_with_ts = _noop  # type: ignore

    client = ThetaDataClient()
    t0 = time.time()
    total_rollups = 0
    total_notional = 0.0
    try:
        for date_obj in dates:
            print(f"\n[BACKFILL] === {date_obj.isoformat()} ===")
            for ticker in tickers:
                n, notional = await backfill_ticker_date(
                    client, ticker, date_obj,
                    strikes_radius=args.strikes,
                    expirations_n=args.expirations,
                    verbose=args.verbose,
                )
                total_rollups += n
                total_notional += notional
                if n:
                    print(f"[BACKFILL]   {ticker}: {n} sweeps, ${notional:,.0f} notional")
    finally:
        await client.close()

    elapsed = time.time() - t0
    print(f"\n[BACKFILL] Done in {elapsed:.1f}s")
    print(f"[BACKFILL] Total: {total_rollups} sweep alerts, ${total_notional:,.0f} aggregate notional")
    if args.dry_run:
        print("[BACKFILL] (dry-run — nothing was written)")
    else:
        print(f"[BACKFILL] Hit http://localhost:8000/api/sweeps to see them in the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
