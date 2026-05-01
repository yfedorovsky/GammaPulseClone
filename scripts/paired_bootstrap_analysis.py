"""Paired bootstrap analysis for the falsification experiment.

Reads paired_trades.db (built by server/paired_trades.py) and computes:
  - Per-source summary stats (gated vs naive_open_atm)
  - Paired difference (gated_pnl - naive_pnl) per fire
  - Cluster-bootstrap by day (Perplexity recommendation)
  - 95% CI on the mean paired difference

The cluster-bootstrap by day handles the within-day correlation Perplexity
flagged: fires that share a day share the macro setup and are not
independent draws.

Run:
  python scripts/paired_bootstrap_analysis.py [--bootstrap 10000]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PAIRED_DB = ROOT / "paired_trades.db"


def load_paired(path: Path = PAIRED_DB) -> pd.DataFrame:
    if not path.exists():
        print(f"  ! {path} does not exist — run server/paired_trades.py first")
        sys.exit(1)
    conn = sqlite3.connect(path)
    df = pd.read_sql_query("SELECT * FROM paired_trades", conn)
    conn.close()
    return df


def pivot_paired(df: pd.DataFrame) -> pd.DataFrame:
    """Wide format: one row per fire_id with both gated_pnl and naive_pnl."""
    sub = df[["fire_id", "source", "ticker", "day", "direction",
              "regime_at_fire", "pnl_pct"]].copy()
    # Pivot pnl_pct across source; bring metadata back via a separate join.
    p = sub.pivot_table(index="fire_id", columns="source",
                        values="pnl_pct", aggfunc="first").reset_index()
    meta = sub[["fire_id", "ticker", "day", "direction", "regime_at_fire"]] \
            .drop_duplicates(subset=["fire_id"])
    return p.merge(meta, on="fire_id", how="left")


def cluster_bootstrap_diff(
    pivot: pd.DataFrame, B: int = 10000, seed: int = 42,
) -> dict:
    """Cluster-bootstrap by day on (gated - naive). Returns CI + stats."""
    df = pivot.dropna(subset=["gated", "naive_open_atm"]).copy()
    df["diff"] = df["gated"] - df["naive_open_atm"]
    if df.empty:
        return {}
    days = df["day"].unique()
    if len(days) < 2:
        # Not enough day clusters — fall back to per-fire bootstrap
        rng = np.random.default_rng(seed)
        diffs = df["diff"].values
        means = np.array([
            rng.choice(diffs, size=len(diffs), replace=True).mean()
            for _ in range(B)
        ])
    else:
        rng = np.random.default_rng(seed)
        day_groups = {d: df[df["day"] == d]["diff"].values for d in days}
        means = np.empty(B)
        for i in range(B):
            sampled_days = rng.choice(days, size=len(days), replace=True)
            sample = np.concatenate([day_groups[d] for d in sampled_days])
            means[i] = sample.mean()
    ci_low, ci_high = np.percentile(means, [2.5, 97.5])
    return {
        "n_fires": len(df),
        "n_days": len(days),
        "mean_diff": float(df["diff"].mean()),
        "median_diff": float(df["diff"].median()),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "wins": int((df["diff"] > 0).sum()),
        "losses": int((df["diff"] < 0).sum()),
        "ties": int((df["diff"] == 0).sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000,
                    help="Bootstrap iterations (default 10000)")
    ap.add_argument("--db", default=str(PAIRED_DB))
    args = ap.parse_args()

    df = load_paired(Path(args.db))
    print(f"Loaded {len(df)} rows from {args.db}")
    print(f"  unique fires: {df['fire_id'].nunique()}")
    print(f"  unique days:  {df['day'].nunique()}")

    pivot = pivot_paired(df)
    print(f"  paired rows after pivot: {len(pivot)}")

    # Per-source summary
    print("\n=== Per-source summary ===")
    for source in ["gated", "naive_open_atm"]:
        sub = df[df["source"] == source]["pnl_pct"].dropna()
        if len(sub) == 0:
            continue
        wr = (sub > 0).mean() * 100
        print(f"  {source:18s}  n={len(sub):>3}  WR={wr:>5.1f}%  "
              f"avg={sub.mean():>+7.1f}%  median={sub.median():>+7.1f}%  "
              f"min={sub.min():>+7.1f}%  max={sub.max():>+7.1f}%")

    # Paired difference
    valid = pivot.dropna(subset=["gated", "naive_open_atm"]).copy()
    valid["diff"] = valid["gated"] - valid["naive_open_atm"]
    print(f"\n=== Paired difference (gated - naive_open_atm), n={len(valid)} ===")
    print(f"  mean diff:    {valid['diff'].mean():+.1f}pp")
    print(f"  median diff:  {valid['diff'].median():+.1f}pp")
    print(f"  fires where gated > naive: {(valid['diff'] > 0).sum()}/{len(valid)}")
    print(f"  fires where gated < naive: {(valid['diff'] < 0).sum()}/{len(valid)}")

    # Bootstrap
    print(f"\n=== Cluster-bootstrap by day, B={args.bootstrap} ===")
    boot = cluster_bootstrap_diff(pivot, B=args.bootstrap)
    print(f"  n fires:      {boot['n_fires']}")
    print(f"  n day clusters: {boot['n_days']}")
    print(f"  mean diff:    {boot['mean_diff']:+.1f}pp")
    print(f"  95% CI:       [{boot['ci_low']:+.1f}pp, {boot['ci_high']:+.1f}pp]")
    if boot["ci_low"] > 0:
        print("  VERDICT: gated has statistically significant alpha over naive "
              "(95% CI excludes 0 on positive side)")
    elif boot["ci_high"] < 0:
        print("  VERDICT: gated underperforms naive (95% CI excludes 0 on negative side)")
    else:
        print("  VERDICT: cannot reject null — CI includes 0")

    # Per-day breakdown
    print("\n=== Per-day breakdown ===")
    for day, sub in valid.groupby("day"):
        gated = sub["gated"].mean()
        naive = sub["naive_open_atm"].mean()
        d = sub["diff"].mean()
        print(f"  {day}  n={len(sub):>2}  gated_avg={gated:>+6.1f}%  "
              f"naive_avg={naive:>+6.1f}%  diff={d:>+6.1f}pp")

    # Per-direction breakdown
    print("\n=== Per-direction breakdown ===")
    for direction, sub in valid.groupby("direction"):
        gated = sub["gated"].mean()
        naive = sub["naive_open_atm"].mean()
        d = sub["diff"].mean()
        wr_g = (sub["gated"] > 0).mean() * 100
        wr_n = (sub["naive_open_atm"] > 0).mean() * 100
        print(f"  {direction:8s}  n={len(sub):>2}  "
              f"gated WR={wr_g:>5.1f}% avg={gated:>+6.1f}%  "
              f"naive WR={wr_n:>5.1f}% avg={naive:>+6.1f}%  "
              f"diff={d:>+6.1f}pp")

    return 0


if __name__ == "__main__":
    sys.exit(main())
