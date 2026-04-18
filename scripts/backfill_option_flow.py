"""Backfill per-contract DAILY option flow — captures ALL aggressive trades,
not just ISO sweeps. Populates the `option_flow_daily` table with UW-style
aggregates for the BIG FLOW tab.

Usage
-----
    # Backfill today's full flow for the MVP watchlist
    python scripts/backfill_option_flow.py --date 2026-04-17

    # Backfill last 5 trading days
    python scripts/backfill_option_flow.py --days-back 5

    # Specific tickers, 3 days back
    python scripts/backfill_option_flow.py --days-back 3 --tickers SPY,QQQ,NVDA

    # Dry-run — print aggregate summary, no DB writes
    python scripts/backfill_option_flow.py --date 2026-04-17 --dry-run

Pipeline
--------
For each (ticker × date × expiration × strike × right):
  1. Call /v3/option/history/trade_quote — returns every trade paired with
     NBBO at trade time
  2. For each print:
     - Skip cancellations (conditions 40-44)
     - Classify side: price>=ask=BUY, price<=bid=SELL, else=NEUTRAL
     - Flag is_sweep if condition in {95, 126, 128}
     - Accumulate into DailyFlowAggregate
  3. Pull OI/IV/delta from today's snapshot for context
  4. Upsert one row per contract-day into option_flow_daily

Runtime estimate
----------------
Similar to backfill_sweeps.py — same number of REST calls. The difference is
parsing (many more trades per call) and aggregation (in-memory only). DB
writes are FEWER since we upsert one row per contract-day, not one per 30s
window.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.option_flow_daily import (
    DailyFlowAggregate,
    clean_flow_daily_range,
    init_flow_daily_db,
    upsert_flow_daily_batch,
)
from server.thetadata import (
    EXCLUDE_CONDITIONS,
    ISO_SWEEP_CONDITIONS,
    ThetaDataClient,
    classify_side,
)
from server.sweep_detector import MVP_WATCHLIST_ROOTS


# ── Args ────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill per-contract daily option flow")
    p.add_argument("--date", type=str, default=None)
    p.add_argument("--days-back", type=int, default=0)
    p.add_argument("--tickers", type=str, default=None)
    p.add_argument("--strikes", type=int, default=10)
    p.add_argument("--expirations", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--clean-first", action="store_true",
                   help="Delete existing rows for date×ticker range before inserting")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


# ── Date + strike planning (mirrors backfill_sweeps) ───────────────


def resolve_date_range(args: argparse.Namespace) -> list[dt.date]:
    today = dt.date.today()
    if args.days_back > 0:
        dates: list[dt.date] = []
        d = today
        while len(dates) < args.days_back:
            if d.weekday() < 5:
                dates.append(d)
            d -= dt.timedelta(days=1)
        return sorted(dates)
    if args.date:
        parsed = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        parsed = today
    if parsed.weekday() >= 5:
        print(f"[BIGFLOW] {parsed} is a weekend — skipping.")
        return []
    return [parsed]


def expirations_after(d: dt.date, n: int) -> list[dt.date]:
    out: list[dt.date] = []
    for i in range(0, 21):
        c = d + dt.timedelta(days=i)
        if c.weekday() in (0, 2, 4):
            out.append(c)
            if len(out) >= n:
                break
    return out


def infer_strike_step(spot: float) -> float:
    if spot < 50: return 0.5
    if spot < 200: return 1.0
    if spot < 500: return 2.5
    if spot < 1000: return 5.0
    if spot < 5000: return 25.0
    return 50.0


def atm_strikes(spot: float, step: float, radius: int) -> list[float]:
    atm = round(spot / step) * step
    return [atm + i * step for i in range(-radius, radius + 1)]


# ── Chain enrichment (spot + OI/IV/delta lookup) ───────────────────


async def build_chain_enrichment(
    client: ThetaDataClient, ticker: str,
) -> tuple[float | None, dict[tuple[float, str, str], dict[str, Any]]]:
    rows, spot = await client.snapshot_chain_greeks(ticker, expiration="*")
    lookup: dict[tuple[float, str, str], dict[str, Any]] = {}
    for r in rows:
        try:
            k_strike = float(r.get("strike") or 0)
            k_exp = r.get("expiration") or ""
            k_right = (r.get("right") or "").lower()
            if not k_strike or not k_exp or k_right not in ("call", "put"):
                continue
            lookup[(k_strike, k_exp, k_right)] = {
                "delta": float(r.get("delta") or 0) or None,
                "iv": float(r.get("implied_vol") or 0) or None,
                "oi": None,
            }
        except (ValueError, TypeError):
            continue

    oi_rows = await client.snapshot_chain_oi(ticker, expiration="*")
    for r in oi_rows:
        try:
            k_strike = float(r.get("strike") or 0)
            k_exp = r.get("expiration") or ""
            k_right = (r.get("right") or "").lower()
            if not k_strike or not k_exp or k_right not in ("call", "put"):
                continue
            oi_val = int(float(r.get("open_interest") or 0))
            key = (k_strike, k_exp, k_right)
            if key in lookup:
                lookup[key]["oi"] = oi_val or None
            else:
                lookup[key] = {"oi": oi_val or None, "iv": None, "delta": None}
        except (ValueError, TypeError):
            continue

    return spot, lookup


# ── Aggregation per contract-day ───────────────────────────────────


def aggregate_trades(
    ticker: str, strike: float, expiration: str, option_type: str,
    rows: list[dict[str, str]], date_obj: dt.date,
) -> DailyFlowAggregate:
    """Ingest all trade_quote rows for one contract on one date into a single
    DailyFlowAggregate (regardless of ISO status)."""
    agg = DailyFlowAggregate(
        date=date_obj.strftime("%Y-%m-%d"),
        ticker=ticker, strike=strike, expiration=expiration, option_type=option_type,
    )

    for r in rows:
        try:
            cond = int(r.get("condition") or 0)
        except ValueError:
            continue
        # Skip cancellations / out-of-sequence only; include everything else
        if cond in EXCLUDE_CONDITIONS:
            continue

        try:
            size = int(r.get("size") or 0)
            price = float(r.get("price") or 0)
            exch = int(r.get("exchange") or 0)
            bid = float(r.get("bid") or 0)
            ask = float(r.get("ask") or 0)
        except (ValueError, TypeError):
            continue
        if size <= 0 or price <= 0:
            continue

        ts_str = r.get("trade_timestamp") or r.get("timestamp", "")
        side = classify_side(price, bid, ask)
        is_sweep = cond in ISO_SWEEP_CONDITIONS

        agg.add(
            size=size, price=price, exchange=exch, condition=cond,
            side=side, is_sweep=is_sweep, timestamp=ts_str,
        )

    return agg


# ── Backfill pipeline ──────────────────────────────────────────────


async def backfill_contract(
    client: ThetaDataClient, ticker: str, strike: float, expiration: dt.date,
    right: str, date_obj: dt.date, verbose: bool = False,
) -> DailyFlowAggregate | None:
    exp_str = expiration.strftime("%Y-%m-%d")
    right_long = "call" if right == "C" else "put"
    date_str = date_obj.strftime("%Y-%m-%d")

    rows = await client.history_trade_quote(
        ticker=ticker, expiration=exp_str, strike=strike,
        right=right_long, date=date_str,
    )
    if not rows:
        return None

    agg = aggregate_trades(ticker, strike, exp_str, right_long, rows, date_obj)
    if agg.total_volume == 0:
        return None

    if verbose:
        print(
            f"  {ticker} ${strike:.0f}{right} {exp_str} {date_str}: "
            f"vol={agg.total_volume:,} notional=${agg.total_notional:,.0f} "
            f"sweep={agg.sweep_share*100:.0f}% bought={agg.bought_pct*100:.0f}%"
        )
    return agg


async def backfill_ticker_date(
    client: ThetaDataClient, ticker: str, date_obj: dt.date,
    strikes_radius: int, expirations_n: int, verbose: bool,
    chain_lookup: dict[tuple[float, str, str], dict[str, Any]],
    spot: float,
) -> tuple[int, float]:
    step = infer_strike_step(spot)
    strikes = atm_strikes(spot, step, strikes_radius)
    exps = expirations_after(date_obj, expirations_n)
    if not exps:
        return 0, 0.0

    tasks = []
    for exp in exps:
        for strike in strikes:
            for right in ("C", "P"):
                tasks.append(backfill_contract(
                    client, ticker, strike, exp, right, date_obj, verbose,
                ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    batch: list[tuple] = []
    total_notional = 0.0
    for res in results:
        if isinstance(res, Exception) or res is None:
            continue
        meta = chain_lookup.get((res.strike, res.expiration, res.option_type)) or {}
        batch.append(res.to_db_tuple(
            oi=meta.get("oi"), iv=meta.get("iv"),
            delta=meta.get("delta"), spot=spot,
        ))
        total_notional += res.total_notional

    row_count = upsert_flow_daily_batch(batch)
    return row_count, total_notional


# ── Main ───────────────────────────────────────────────────────────


async def main() -> int:
    args = parse_args()

    dates = resolve_date_range(args)
    if not dates:
        print("[BIGFLOW] No dates to process.")
        return 1

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else MVP_WATCHLIST_ROOTS
    )

    print(f"[BIGFLOW] Plan: {len(tickers)} tickers × {len(dates)} dates")
    print(f"[BIGFLOW] Tickers: {', '.join(tickers)}")
    print(f"[BIGFLOW] Dates:   {', '.join(d.isoformat() for d in dates)}")
    print(f"[BIGFLOW] Strikes: ATM ±{args.strikes} | Expirations: next {args.expirations} M/W/F")

    init_flow_daily_db()

    if args.clean_first and not args.dry_run:
        date_strs = [d.isoformat() for d in dates]
        removed = clean_flow_daily_range(date_strs, tickers)
        print(f"[BIGFLOW] Cleaned {removed} existing rows for range.")

    if args.dry_run:
        print("[BIGFLOW] DRY-RUN — no DB writes.")
        global upsert_flow_daily_batch
        def _noop(rows):
            return len(rows)
        upsert_flow_daily_batch = _noop  # type: ignore

    client = ThetaDataClient()
    t0 = time.time()
    total_rows = 0
    total_notional = 0.0

    try:
        for ticker in tickers:
            print(f"\n[BIGFLOW] === {ticker} ===")
            try:
                spot, lookup = await build_chain_enrichment(client, ticker)
                if not spot or spot <= 0:
                    print(f"[BIGFLOW] {ticker}: no spot, skipping")
                    continue
                print(f"[BIGFLOW] {ticker}: spot=${spot:.2f} lookup={len(lookup)} contracts")
            except Exception as e:
                print(f"[BIGFLOW] {ticker}: enrichment failed ({e}), skipping")
                continue

            for date_obj in dates:
                n, notional = await backfill_ticker_date(
                    client, ticker, date_obj,
                    strikes_radius=args.strikes,
                    expirations_n=args.expirations,
                    verbose=args.verbose,
                    chain_lookup=lookup,
                    spot=spot,
                )
                total_rows += n
                total_notional += notional
                if n:
                    print(f"[BIGFLOW]   {date_obj.isoformat()}: {n} contracts, ${notional:,.0f} notional")
    finally:
        await client.close()

    elapsed = time.time() - t0
    print(f"\n[BIGFLOW] Done in {elapsed:.1f}s")
    print(f"[BIGFLOW] Total: {total_rows} contract-day rows, ${total_notional:,.0f} aggregate notional")
    if args.dry_run:
        print("[BIGFLOW] (dry-run — nothing written)")
    else:
        print(f"[BIGFLOW] Hit http://localhost:8000/api/flow/daily to see them in the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
