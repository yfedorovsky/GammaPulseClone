"""Re-runnable historical backfill of realized OPTION P&L into alert_outcomes.db.

Populates opt_high_after / opt_low_after / opt_mfe_pct / opt_mae_pct /
opt_close_eod / opt_close_next_day on every contract-bearing alert from REAL
ThetaData OPRA NBBO 1-min bars (ask-in / bid-out). Idempotent + self-limiting
(only fills rows where opt_mfe_pct IS NULL), so it is safe to re-run.

This is the #92 keystone: the cross-LLM audit (2026-06-23) found these columns
100% NULL, which blocks validating INFORMED CLUSTER on real option P&L (audit
C10) and activating the #95 conviction-v2 filter. Requires the local ThetaData
Terminal at http://127.0.0.1:25503 (override with THETA_BASE_URL).

Run:
  python scripts/backfill_option_pnl.py            # last 14 days
  python scripts/backfill_option_pnl.py 60         # last 60 days (full backlog)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_outcomes import run_option_pnl_backfill  # noqa: E402


async def _main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(f"[backfill_option_pnl] filling opt_* columns, lookback={days}d ...", flush=True)
    stats = await run_option_pnl_backfill(max_age_days=days)
    print(f"[backfill_option_pnl] done: {stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
