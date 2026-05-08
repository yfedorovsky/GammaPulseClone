"""Backtest: 'Buy on first qualified king-migration leapfrog, hold until
king stops migrating' rule.

Simplification: rather than backtest option pricing across hundreds of
contracts, we measure the SPOT return from entry (first qualified leapfrog)
to exit (king stable for >= STABLE_DAYS).

The rule:
  ENTRY: first qualified leapfrog migration in the lookback window
  HOLD: while subsequent qualified migrations occur
  EXIT: when no qualified migration occurs for STABLE_DAYS consecutive days
        OR (fallback) when ticker has been in trade for MAX_HOLD_DAYS

Output: per-trade spot return, aggregate stats, ranking by setup quality.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STABLE_DAYS = 5  # if no qualified migration for 5 days, exit
MAX_HOLD_DAYS = 30  # never hold longer than 30 days
EXCLUDE = {"NDX", "RUT", "SPX", "VIX", "UVXY", "XMAG", "RSP", "QQQE",
           "IBIT", "SLV", "GLD", "USO"}


def get_spot_at(ticker: str, day: str, conn) -> float | None:
    """Last snapshot of `day` for `ticker`."""
    r = conn.execute(
        """SELECT spot FROM snapshots WHERE ticker = ?
           AND date(ts, 'unixepoch', '-4 hours') = ?
           ORDER BY ts DESC LIMIT 1""",
        (ticker, day)).fetchone()
    return float(r[0]) if r and r[0] else None


def main() -> int:
    conn_km = sqlite3.connect("king_migrations.db")
    conn_sn = sqlite3.connect("snapshots.db")

    # All qualified leapfrog migrations
    km = pd.read_sql("""
        SELECT ticker, migration_iso, migration_ts, old_king, new_king,
               spot, qualified, qualified_reasons
        FROM king_migrations
        WHERE qualified = 1
          AND qualified_reasons LIKE '%leapfrog%'
        ORDER BY ticker, migration_ts
    """, conn_km)
    km["day"] = km["migration_iso"].str[:10]
    km = km[~km["ticker"].isin(EXCLUDE)]
    print(f"[runner-bt] {len(km)} qualified leapfrog migrations across "
          f"{km['ticker'].nunique()} tickers")
    print()

    # Build trades per ticker
    trades = []
    for ticker, grp in km.groupby("ticker"):
        if len(grp) == 0:
            continue
        grp = grp.sort_values("migration_ts").reset_index(drop=True)
        # Entry: day of FIRST qualified leapfrog
        entry_day = grp.iloc[0]["day"]
        entry_spot = get_spot_at(ticker, entry_day, conn_sn)
        if not entry_spot:
            continue

        # Find exit: walk forward looking for STABLE_DAYS gap
        last_migration_day = entry_day
        for i in range(1, len(grp)):
            this_day = grp.iloc[i]["day"]
            d_prev = datetime.strptime(last_migration_day, "%Y-%m-%d")
            d_this = datetime.strptime(this_day, "%Y-%m-%d")
            if (d_this - d_prev).days > STABLE_DAYS:
                break
            last_migration_day = this_day
        # Exit day = last_migration_day + STABLE_DAYS
        exit_day_dt = datetime.strptime(last_migration_day, "%Y-%m-%d") \
            + timedelta(days=STABLE_DAYS)
        # Cap at max hold
        max_exit_dt = datetime.strptime(entry_day, "%Y-%m-%d") \
            + timedelta(days=MAX_HOLD_DAYS)
        if exit_day_dt > max_exit_dt:
            exit_day_dt = max_exit_dt
        exit_day = exit_day_dt.strftime("%Y-%m-%d")

        # Get exit spot — try the exit day, walk back if no data
        exit_spot = None
        for back in range(0, 10):
            day_try = (exit_day_dt - timedelta(days=back)).strftime("%Y-%m-%d")
            exit_spot = get_spot_at(ticker, day_try, conn_sn)
            if exit_spot:
                exit_day = day_try
                break
        if not exit_spot:
            continue

        days_held = (datetime.strptime(exit_day, "%Y-%m-%d")
                     - datetime.strptime(entry_day, "%Y-%m-%d")).days
        ret_pct = (exit_spot - entry_spot) / entry_spot * 100
        n_migrations_in_trade = len(grp[
            (grp["day"] >= entry_day) & (grp["day"] <= last_migration_day)])

        trades.append({
            "ticker": ticker,
            "entry_day": entry_day,
            "entry_spot": round(entry_spot, 2),
            "exit_day": exit_day,
            "exit_spot": round(exit_spot, 2),
            "days_held": days_held,
            "n_migrations": n_migrations_in_trade,
            "spot_return_pct": round(ret_pct, 1),
        })

    conn_km.close(); conn_sn.close()
    df = pd.DataFrame(trades)
    if df.empty:
        print("No trades.")
        return 0

    df = df.sort_values("spot_return_pct", ascending=False)

    print("=" * 100)
    print(f"KING-MIGRATION-RUNNER BACKTEST — {len(df)} trades")
    print("=" * 100)
    print()
    print(f"{'ticker':<8} {'entry':<12} {'entry_$':<10} {'exit':<12} "
          f"{'exit_$':<10} {'days':<5} {'n_mig':<6} {'spot_ret':<10}")
    print("-" * 100)
    for _, r in df.iterrows():
        print(f"{r['ticker']:<8} {r['entry_day']:<12} ${r['entry_spot']:<9} "
              f"{r['exit_day']:<12} ${r['exit_spot']:<9} "
              f"{r['days_held']:<5} {r['n_migrations']:<6} "
              f"{r['spot_return_pct']:>+5.1f}%")

    print()
    print("=" * 70)
    print("AGGREGATE STATS")
    print("=" * 70)
    print(f"Total trades: {len(df)}")
    print(f"Mean spot return: {df['spot_return_pct'].mean():+.1f}%")
    print(f"Median spot return: {df['spot_return_pct'].median():+.1f}%")
    print(f"Win rate (positive return): {(df['spot_return_pct'] > 0).mean()*100:.0f}%")
    print(f"Mean days held: {df['days_held'].mean():.1f}")
    print(f"Mean migrations during trade: {df['n_migrations'].mean():.1f}")
    print()
    # By migration count: more migrations → bigger move?
    print("By # migrations during trade:")
    for n_bucket in [(1, 1), (2, 3), (4, 6), (7, 100)]:
        sub = df[(df["n_migrations"] >= n_bucket[0])
                 & (df["n_migrations"] <= n_bucket[1])]
        if len(sub):
            print(f"  {n_bucket[0]}-{n_bucket[1]} migrations (n={len(sub)}): "
                  f"mean ret={sub['spot_return_pct'].mean():+.1f}%, "
                  f"median={sub['spot_return_pct'].median():+.1f}%, "
                  f"win%={(sub['spot_return_pct']>0).mean()*100:.0f}%")

    # Bootstrap CI on mean
    np.random.seed(42)
    means = []
    for _ in range(2000):
        s = df["spot_return_pct"].sample(len(df), replace=True)
        means.append(s.mean())
    means = np.array(means)
    print()
    print(f"Bootstrap (2000 resamples) on mean spot return:")
    print(f"  Mean: {means.mean():+.1f}%")
    print(f"  90% CI: [{np.percentile(means, 5):+.1f}, "
          f"{np.percentile(means, 95):+.1f}]")
    print(f"  P(mean > 0): {(means > 0).mean()*100:.0f}%")
    print(f"  P(mean > +5%): {(means > 5).mean()*100:.0f}%")
    print(f"  P(mean > +10%): {(means > 10).mean()*100:.0f}%")

    # Approximate option leverage estimate
    # ATM call with 30 DTE typically has delta ~0.50, gamma adds during run
    # For a +X% spot move, deep ITM call ≈ +X*spot/strike (delta climbs to 1)
    # Rough estimate: 5-10× leverage on ATM 30-DTE for +20% spot moves
    print()
    print("=" * 70)
    print("APPROX OPTION LEVERAGE ESTIMATE")
    print("=" * 70)
    print("ATM call with 30 DTE typically has delta ~0.5 at entry, climbing")
    print("to ~1.0 as spot moves higher (gamma kicks in). Rough estimate of")
    print("option return at typical leverage (8x) for the spot moves above:")
    print()
    print(f"  Mean spot return:   {df['spot_return_pct'].mean():+.1f}%")
    print(f"  Estimated option return at 8x leverage: "
          f"{df['spot_return_pct'].mean() * 8:+.0f}%")
    print(f"  Median spot return: {df['spot_return_pct'].median():+.1f}%")
    print(f"  Estimated option return at 8x leverage: "
          f"{df['spot_return_pct'].median() * 8:+.0f}%")

    df.to_csv("docs/research/king_migration_runner_backtest.csv", index=False)
    print()
    print("Saved to docs/research/king_migration_runner_backtest.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
