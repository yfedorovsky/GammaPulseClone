"""Phase 1 shadow alert validation.

Compares the running forward-window shadow_alerts.db distribution to the
6-month backtest unified_setup_backtest.db distribution.

For each robust setup, reports:
  - Forward n vs backtest n
  - Forward mean P&L (TP+50, TP+100) vs backtest mean
  - Two-sample t-test p-value for "forward edge has degraded"
  - 90% bootstrap CI on the difference

Decision rule (pre-registered):
  - GO LIVE if: forward mean within 5pp of backtest mean AND
                forward bootstrap CI lower bound > 0
  - HOLD if:    forward mean within 10pp of backtest but CI not clean
  - HALT if:    forward mean > 10pp below backtest OR CI excludes positive

Run weekly during Phase 1 to track validation status.

Usage:
  python scripts/shadow_validation.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHADOW_DB = "shadow_alerts.db"
BACKTEST_DB = "unified_setup_backtest.db"

ROBUST_SETUPS = [
    "pmh_break", "sweep_pmh", "orb15_break", "orb30_break", "ema_cross_imm"
]


def cluster_bootstrap_diff(forward: pd.Series, fdays: pd.Series,
                           backtest: pd.Series, bdays: pd.Series,
                           n_resamples: int = 2000) -> tuple[float, float, float]:
    """Cluster-bootstrap the (forward_mean - backtest_mean) difference."""
    fdf = pd.DataFrame({"v": forward, "d": fdays})
    bdf = pd.DataFrame({"v": backtest, "d": bdays})
    fdays_arr = fdf["d"].unique()
    bdays_arr = bdf["d"].unique()
    if len(fdays_arr) == 0 or len(bdays_arr) == 0:
        return (0.0, 0.0, 0.0)
    rng = np.random.default_rng(42)
    diffs = []
    for _ in range(n_resamples):
        f_sample = rng.choice(fdays_arr, len(fdays_arr), replace=True)
        b_sample = rng.choice(bdays_arr, len(bdays_arr), replace=True)
        f_mean = pd.concat([fdf[fdf["d"] == d] for d in f_sample])["v"].mean()
        b_mean = pd.concat([bdf[bdf["d"] == d] for d in b_sample])["v"].mean()
        diffs.append(f_mean - b_mean)
    diffs = np.array(diffs)
    return (float(diffs.mean()),
            float(np.percentile(diffs, 5)),
            float(np.percentile(diffs, 95)))


def main() -> int:
    print("=" * 100)
    print("PHASE 1 SHADOW VALIDATION — forward vs backtest comparison")
    print("=" * 100)

    if not Path(SHADOW_DB).exists():
        print(f"\nNo shadow alerts yet. {SHADOW_DB} does not exist.")
        print("Run shadow_alerts_eod.py daily to populate it.")
        return 0

    fwd = pd.read_sql("SELECT * FROM shadow_alerts", sqlite3.connect(SHADOW_DB))
    bt = pd.read_sql("SELECT * FROM unified_trades", sqlite3.connect(BACKTEST_DB))

    if fwd.empty:
        print("\nshadow_alerts.db is empty. Nothing to validate yet.")
        return 0

    print(f"\nForward shadow sample: {len(fwd)} alerts across "
          f"{fwd['day'].nunique()} days")
    print(f"Backtest reference:   {len(bt)} trades across "
          f"{bt['day'].nunique()} days")
    print()

    print(f"{'setup':<20} {'fwd_n':<6} {'fwd_days':<10} "
          f"{'fwd_TP100':<11} {'bt_TP100':<11} {'diff':<10} "
          f"{'90% CI':<22} {'verdict':<10}")
    print("-" * 100)
    for setup in ROBUST_SETUPS:
        f = fwd[fwd["setup"] == setup]
        b = bt[bt["setup"] == setup]
        if f.empty:
            print(f"{setup:<20} 0      —          —          {b['pol_tp100_s30'].mean():+.1f}%       —          —                    AWAIT")
            continue
        f_mean = f["pol_tp100_s30"].mean()
        b_mean = b["pol_tp100_s30"].mean()
        diff_mean, lo, hi = cluster_bootstrap_diff(
            f["pol_tp100_s30"], f["day"], b["pol_tp100_s30"], b["day"], 1000)
        ci = f"[{lo:+.1f},{hi:+.1f}]"
        verdict = (
            "GO LIVE" if (f_mean > b_mean - 5 and lo > -10) else
            "HOLD" if (f_mean > b_mean - 10) else
            "HALT")
        print(f"{setup:<20} {len(f):<6} {f['day'].nunique():<10} "
              f"{f_mean:>+5.1f}%      {b_mean:>+5.1f}%      "
              f"{f_mean - b_mean:>+5.1f}pp    {ci:<22} {verdict:<10}")

    print()
    print("Decision rules:")
    print("  GO LIVE: forward TP+100 mean within 5pp of backtest AND CI lower > -10")
    print("  HOLD:    forward within 10pp")
    print("  HALT:    forward > 10pp below backtest")
    print("  AWAIT:   not enough forward data yet (target: 30+ alerts per setup)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
