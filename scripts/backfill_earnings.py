"""Backfill earnings_in_window + earnings_days_to into alert_outcomes.db (#119).

Fills whether each contract-bearing alert spanned a scheduled earnings date
(Tradier corporate_calendars). Unblocks the De Silva (2022) test: is flow INTO
binary catalysts negative-EV? Idempotent; one fetch per distinct ticker.

  python scripts/backfill_earnings.py        # last 45 days
  python scripts/backfill_earnings.py 60
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_outcomes import run_earnings_backfill  # noqa: E402


async def _main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    print(f"[backfill_earnings] lookback={days}d ...", flush=True)
    stats = await run_earnings_backfill(max_age_days=days)
    print(f"[backfill_earnings] done: {stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
