"""Backfill breadth A/D history from Massive grouped daily.

Run once to seed 50+ days of NYSE/NASDAQ advance-decline data.
Rate-limited to 5 calls/minute to stay under Massive Starter limits.

Usage:
    cd C:/Dev/GammaPulse
    .venv/Scripts/python scripts/backfill_breadth.py

After completion, NYMO/NAMO will be fully operational.
"""
import asyncio
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, ".")

from server.breadth import (
    init_breadth_db,
    _load_exchange_map,
    compute_daily_breadth,
    _store_daily,
    _get_oscillator_history,
    _ema,
)


async def main():
    init_breadth_db()
    await _load_exchange_map()

    today = date.today()
    days_to_fetch = 60  # ~50 trading days
    dates: list[str] = []

    for i in range(days_to_fetch, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            dates.append(d.isoformat())

    print(f"Backfilling {len(dates)} trading days of breadth data...")
    print(f"Rate: 1 call every 15 seconds = ~{len(dates) * 15 / 60:.0f} minutes")
    print()

    success = 0
    for i, date_str in enumerate(dates):
        print(f"  [{i+1}/{len(dates)}] {date_str}...", end=" ", flush=True)

        try:
            counts = await compute_daily_breadth(date_str)
            if counts:
                for exchange in ("NYSE", "NASDAQ"):
                    ec = counts.get(exchange, {})
                    adv = ec.get("adv", 0)
                    dec = ec.get("dec", 0)
                    unch = ec.get("unch", 0)
                    net = ec.get("net", 0)

                    # Get history so far to compute running EMAs
                    history = _get_oscillator_history(exchange, limit=60)
                    all_net = [h["net_advances"] for h in history] + [net]
                    ema19 = _ema(all_net, 19)
                    ema39 = _ema(all_net, 39)
                    osc = ema19[-1] - ema39[-1] if ema19 and ema39 else 0

                    _store_daily(date_str, exchange, adv, dec, unch, net,
                                 ema19[-1] if ema19 else 0,
                                 ema39[-1] if ema39 else 0,
                                 osc)

                nyse = counts["NYSE"]
                print(f"NYSE A/D: {nyse['adv']}/{nyse['dec']} ({nyse['net']:+d})")
                success += 1
            else:
                print("no data (holiday/weekend?)")
        except Exception as e:
            print(f"error: {e}")

        # Rate limit: 1 call per 15 seconds (4/min, well under Starter limits)
        if i < len(dates) - 1:
            time.sleep(15)

    print(f"\nDone! {success}/{len(dates)} days loaded.")

    # Show current oscillator state
    from server.breadth import _compute_oscillator_from_history
    for exchange in ("NYSE", "NASDAQ"):
        history = _get_oscillator_history(exchange, limit=60)
        if history:
            osc = _compute_oscillator_from_history(history)
            label = "NYMO" if exchange == "NYSE" else "NAMO"
            print(f"  {label}: {osc['value']} | {osc['regime']} | 5d: {osc.get('history_5d')}")


if __name__ == "__main__":
    asyncio.run(main())
