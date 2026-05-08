"""Replay-harness for the tick-level side detector — historical audit only.

Pulls one contract's trade_quote tape from ThetaData history for one date
and one time window, then walks it through the SAME 60s rolling window the
live tracker uses. Prints a per-minute audit of what side dominates.

Use this to verify the live detector against past misclassifications, e.g.:
    python scripts/replay_tick_side.py \
        --ticker INTC --strike 120 --right call --exp 2026-05-15 \
        --date 2026-05-08 --start 10:00 --end 12:00

Caveats:
- ThetaData history/trade_quote returns reliable data only after EOD on the
  current trading day. Don't expect "today" intraday queries to work mid-day.
- This harness does NOT write to the live flow_alerts DB. Audit-only.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
from collections import deque
from typing import Any

from server.thetadata import ThetaDataClient, classify_side
from server.tick_side_tracker import (
    DOMINANCE_RATIO,
    MIN_WINDOW_SIZE,
    WINDOW_SECONDS,
)


def _parse_hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def _ms_of_day(t: dt.time) -> int:
    return ((t.hour * 60 + t.minute) * 60 + t.second) * 1000


def _evaluate(ask: int, bid: int, mid: int) -> str | None:
    """Same logic as TickSideTracker.latest_side, mid-volume insensitive."""
    total = ask + bid + mid
    if total < MIN_WINDOW_SIZE:
        return None
    if ask > DOMINANCE_RATIO * max(bid, 1):
        return "ASK"
    if bid > DOMINANCE_RATIO * max(ask, 1):
        return "BID"
    return "MID"


def replay(rows: list[dict[str, Any]], start_ms: int, end_ms: int) -> None:
    """Walk the trade_quote rows in time order, replaying the 60s window.

    Emits one line per minute boundary inside [start, end) reporting the
    dominant side, total ASK/BID/MID volumes in the trailing 60s, and the
    raw print count. Lets you eyeball mismatches against the legacy tagger.
    """
    # Sort defensively — historical CSV is usually in order, but don't rely.
    rows.sort(key=lambda r: int(r.get("trade_timestamp") or r.get("ms_of_day") or 0))

    window: deque[tuple[int, int, str]] = deque()
    ask_v = bid_v = mid_v = 0
    next_emit_ms = start_ms

    print(
        f"# replay window={WINDOW_SECONDS:.0f}s "
        f"min_size={MIN_WINDOW_SIZE} dominance={DOMINANCE_RATIO}x"
    )
    print("# time  side  total  ask  bid  mid  prints")

    def _drop_old(now_ms: int) -> None:
        nonlocal ask_v, bid_v, mid_v
        cutoff = now_ms - int(WINDOW_SECONDS * 1000)
        while window and window[0][0] < cutoff:
            _, sz, sd = window.popleft()
            if sd == "ASK":
                ask_v -= sz
            elif sd == "BID":
                bid_v -= sz
            else:
                mid_v -= sz

    def _emit(at_ms: int) -> None:
        side = _evaluate(ask_v, bid_v, mid_v)
        hh = at_ms // 3_600_000
        mm = (at_ms // 60_000) % 60
        label = side if side is not None else "FALLBACK"
        print(
            f"{hh:02d}:{mm:02d}  {label:<8}  "
            f"total={ask_v + bid_v + mid_v:<6} "
            f"ask={ask_v:<5} bid={bid_v:<5} mid={mid_v:<5} "
            f"prints={len(window)}"
        )

    for r in rows:
        ts_ms = int(r.get("trade_timestamp") or r.get("ms_of_day") or 0)
        if ts_ms < start_ms:
            continue
        if ts_ms >= end_ms:
            break

        # Emit any minute boundaries we crossed since the last print.
        while next_emit_ms <= ts_ms:
            _drop_old(next_emit_ms)
            _emit(next_emit_ms)
            next_emit_ms += 60_000

        try:
            price = float(r["price"])
            bid = float(r.get("bid") or 0)
            ask = float(r.get("ask") or 0)
            size = int(r.get("size") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if size <= 0:
            continue

        side_raw = classify_side(price, bid, ask)
        sd = "ASK" if side_raw == "BUY" else "BID" if side_raw == "SELL" else "MID"

        _drop_old(ts_ms)
        window.append((ts_ms, size, sd))
        if sd == "ASK":
            ask_v += size
        elif sd == "BID":
            bid_v += size
        else:
            mid_v += size

    # Final emit for the tail window.
    while next_emit_ms < end_ms:
        _drop_old(next_emit_ms)
        _emit(next_emit_ms)
        next_emit_ms += 60_000


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--strike", required=True, type=float)
    ap.add_argument("--right", required=True, choices=["call", "put"])
    ap.add_argument("--exp", required=True, help="YYYY-MM-DD")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--start", default="09:30", help="HH:MM ET, default 09:30")
    ap.add_argument("--end", default="16:00", help="HH:MM ET, default 16:00")
    args = ap.parse_args()

    start_ms = _ms_of_day(_parse_hhmm(args.start))
    end_ms = _ms_of_day(_parse_hhmm(args.end))

    client = ThetaDataClient()
    rows = await client.history_trade_quote(
        ticker=args.ticker,
        expiration=args.exp,
        strike=args.strike,
        right=args.right,
        date=args.date,
    )
    print(
        f"# {args.ticker} ${args.strike:g} {args.right.upper()} {args.exp} "
        f"on {args.date}: {len(rows)} prints fetched"
    )
    if not rows:
        return
    replay(rows, start_ms, end_ms)


if __name__ == "__main__":
    asyncio.run(main())
