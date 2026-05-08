"""Scan for AMD-pattern king migration candidates.

The AMD pattern (from the 4/13-5/5 run that produced +900% on May 15 260C):
  - Multiple qualified king migrations in a short window (≤30 days)
  - Each migration has floor-leapfrog (new floor >= old king)
  - Net delta growing across migrations
  - Spot trending UP into the king (not below by too far)

Output: ranked list of tickers currently exhibiting this pattern.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(lookback_days: int = 30) -> int:
    cutoff = datetime.now() - timedelta(days=lookback_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%d")

    conn_km = sqlite3.connect("king_migrations.db")
    conn_kb = sqlite3.connect("king_breakouts.db")
    conn_sn = sqlite3.connect("snapshots.db")

    # All king migrations in the lookback window
    km = pd.read_sql(f"""
        SELECT ticker, migration_iso, old_king, new_king, delta_pts,
               old_floor, new_floor, spot, signal,
               ratio_before, ratio_after, qualified, qualified_reasons
        FROM king_migrations
        WHERE migration_iso >= '{cutoff_iso}'
        ORDER BY ticker, migration_ts
    """, conn_km)

    # All king breakouts in the lookback window
    kb = pd.read_sql(f"""
        SELECT ticker, breakout_iso, king, spot_break, breakout_pct,
               qualified, fwd_return_4h
        FROM king_breakouts
        WHERE breakout_iso >= '{cutoff_iso}'
        ORDER BY ticker, breakout_ts
    """, conn_kb)

    print(f"=" * 100)
    print(f"KING MIGRATION SCAN — last {lookback_days} days "
          f"(since {cutoff_iso})")
    print(f"=" * 100)
    print(f"Total migrations: {len(km)}, qualified: {km['qualified'].sum()}")
    print(f"Total breakouts: {len(kb)}, qualified: {kb['qualified'].sum()}")
    print()

    # Per-ticker aggregation
    rows = []
    for ticker, grp in km.groupby("ticker"):
        n_total = len(grp)
        n_qual = int(grp["qualified"].sum())
        # Migrations with floor-leapfrog
        n_leapfrog = int(grp["qualified_reasons"].str.contains(
            "leapfrog", na=False, regex=False).sum())
        # Compute king march: max new_king - min old_king
        king_march = grp["new_king"].max() - grp["old_king"].min()
        # Latest king
        latest_king = grp.iloc[-1]["new_king"]
        latest_spot = grp.iloc[-1]["spot"]
        # Distance from spot to king
        dist_to_king_pct = (latest_king - latest_spot) / latest_spot * 100 \
            if latest_spot > 0 else 0
        # Days span
        first_iso = grp.iloc[0]["migration_iso"][:10]
        last_iso = grp.iloc[-1]["migration_iso"][:10]

        # Get current spot from snapshots
        try:
            cur_spot = conn_sn.execute(
                """SELECT spot FROM snapshots WHERE ticker = ?
                   ORDER BY ts DESC LIMIT 1""",
                (ticker,)).fetchone()
            cur_spot = float(cur_spot[0]) if cur_spot and cur_spot[0] else None
        except Exception:
            cur_spot = None

        rows.append({
            "ticker": ticker,
            "n_total": n_total,
            "n_qual": n_qual,
            "n_leapfrog": n_leapfrog,
            "king_march_pts": round(king_march, 1),
            "first_migration": first_iso,
            "last_migration": last_iso,
            "latest_old_king": grp.iloc[-1]["old_king"],
            "latest_new_king": latest_king,
            "latest_spot": round(latest_spot, 2) if latest_spot else None,
            "current_spot": round(cur_spot, 2) if cur_spot else None,
            "dist_to_king_pct": round(dist_to_king_pct, 1),
        })
    summary = pd.DataFrame(rows)

    # SCORE: AMD pattern = many qualified migrations + leapfrog + king march
    summary["score"] = (
        summary["n_qual"] * 5
        + summary["n_leapfrog"] * 3
        + summary["king_march_pts"] / 10
    ).round(1)

    summary = summary.sort_values("score", ascending=False)

    print("TOP CANDIDATES (sorted by AMD-pattern score):")
    print()
    print(f"{'#':<3} {'tkr':<6} {'qual':<5} {'leap':<5} {'march':<7} "
          f"{'last_mig':<12} {'old→new_king':<14} {'cur_spot':<10} "
          f"{'dist_pct':<10} {'score':<6}")
    print("-" * 100)
    for i, r in summary.head(20).iterrows():
        kingstr = f"${int(r['latest_old_king'])}→${int(r['latest_new_king'])}"
        print(f"{i+1:<3} {r['ticker']:<6} {int(r['n_qual']):<5} "
              f"{int(r['n_leapfrog']):<5} ${int(r['king_march_pts']):<6} "
              f"{r['last_migration']:<12} {kingstr:<14} "
              f"${r['current_spot']:<9} {r['dist_to_king_pct']:>+5.1f}%   "
              f"{r['score']:<6}")
    print()

    # Save full table
    summary.to_csv("docs/research/king_migration_scan.csv", index=False)
    print(f"Full scan ({len(summary)} tickers) saved to "
          f"docs/research/king_migration_scan.csv")

    # Spotlight: the top 5 with current_spot trending toward king
    print()
    print("=" * 100)
    print("SPOTLIGHT — top 5 with king migrations + spot below king (room to run)")
    print("=" * 100)
    spotlight = summary[
        (summary["current_spot"].notna())
        & (summary["dist_to_king_pct"] > 0)
        & (summary["dist_to_king_pct"] < 15)  # within reach
        & (summary["n_qual"] >= 1)
    ].head(10)
    for _, r in spotlight.iterrows():
        kingstr = f"${int(r['latest_old_king'])}→${int(r['latest_new_king'])}"
        print(f"  ${r['ticker']:<5} qual={int(r['n_qual'])} "
              f"leap={int(r['n_leapfrog'])} king_march=${int(r['king_march_pts'])} "
              f"king_now={kingstr} spot=${r['current_spot']} "
              f"({r['dist_to_king_pct']:+.1f}% to king)")

    conn_km.close(); conn_kb.close(); conn_sn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
