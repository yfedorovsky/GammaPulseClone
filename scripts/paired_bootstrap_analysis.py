"""Paired bootstrap analysis for the falsification experiment.

Reads paired_trades.db (built by server/paired_trades.py) and computes:
  - Per-source summary stats (gated vs random_minute_atm vs naive_open_atm)
  - PRIMARY paired difference: gated - random_minute_atm
      (isolates timing alpha — same direction, ATM-at-entry strike rule,
       same exit logic; varies entry minute only)
  - SECONDARY paired difference: gated - naive_open_atm
      (the whole-package test: did the strategy beat a fixed-time morning bet?)
  - Cluster-bootstrap by day for both
  - 95% CI on each mean paired difference

Stopping rule per Perplexity Apr 30 #2: at least 30 paired observations
across at least 5 distinct day clusters before declaring a verdict; small
cluster counts make bootstrap intervals look more stable than they are.

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
    pivot: pd.DataFrame, control_col: str,
    B: int = 10000, seed: int = 42,
) -> dict:
    """Cluster-bootstrap by day on (gated - control_col). Returns CI + stats."""
    df = pivot.dropna(subset=["gated", control_col]).copy()
    df["diff"] = df["gated"] - df[control_col]
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
        "control": control_col,
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
    for source in ["gated", "random_minute_atm", "naive_open_atm"]:
        sub = df[df["source"] == source]["pnl_pct"].dropna()
        if len(sub) == 0:
            continue
        wr = (sub > 0).mean() * 100
        print(f"  {source:18s}  n={len(sub):>3}  WR={wr:>5.1f}%  "
              f"avg={sub.mean():>+7.1f}%  median={sub.median():>+7.1f}%  "
              f"min={sub.min():>+7.1f}%  max={sub.max():>+7.1f}%")

    # PRIMARY: gated - random_minute_atm (timing alpha)
    print(f"\n=== PRIMARY: gated - random_minute_atm (timing alpha), "
          f"cluster-bootstrap by day, B={args.bootstrap} ===")
    boot_p = cluster_bootstrap_diff(pivot, "random_minute_atm",
                                    B=args.bootstrap)
    if boot_p:
        print(f"  n fires:        {boot_p['n_fires']}")
        print(f"  n day clusters: {boot_p['n_days']}")
        print(f"  mean diff:      {boot_p['mean_diff']:+.1f}pp")
        print(f"  median diff:    {boot_p['median_diff']:+.1f}pp")
        print(f"  95% CI:         [{boot_p['ci_low']:+.1f}pp, {boot_p['ci_high']:+.1f}pp]")
        print(f"  fires gated > random: {boot_p['wins']}/{boot_p['n_fires']}")
        if boot_p["n_days"] < 5:
            print(f"  ⚠ only {boot_p['n_days']} day clusters — minimum 5 for "
                  "verdict per Perplexity Apr 30 #2")
        elif boot_p["ci_low"] > 0:
            print("  ✅ VERDICT (primary): gated has statistically significant "
                  "TIMING alpha over random-minute ATM (95% CI excludes 0)")
        elif boot_p["ci_high"] < 0:
            print("  ❌ VERDICT (primary): gated underperforms random-minute ATM")
        else:
            print("  ⚪ VERDICT (primary): cannot reject null — CI includes 0")

    # SECONDARY: gated - naive_open_atm (whole-package alpha)
    print(f"\n=== SECONDARY: gated - naive_open_atm (whole-package alpha), "
          f"cluster-bootstrap by day, B={args.bootstrap} ===")
    boot_s = cluster_bootstrap_diff(pivot, "naive_open_atm",
                                    B=args.bootstrap)
    if boot_s:
        print(f"  n fires:        {boot_s['n_fires']}")
        print(f"  n day clusters: {boot_s['n_days']}")
        print(f"  mean diff:      {boot_s['mean_diff']:+.1f}pp")
        print(f"  median diff:    {boot_s['median_diff']:+.1f}pp")
        print(f"  95% CI:         [{boot_s['ci_low']:+.1f}pp, {boot_s['ci_high']:+.1f}pp]")
        print(f"  fires gated > naive_open_atm: {boot_s['wins']}/{boot_s['n_fires']}")

    # Per-day breakdown
    print("\n=== Per-day breakdown (gated vs random_minute_atm) ===")
    valid = pivot.dropna(subset=["gated", "random_minute_atm"]).copy()
    valid["diff_primary"] = valid["gated"] - valid["random_minute_atm"]
    if "naive_open_atm" in valid.columns:
        valid["diff_secondary"] = valid["gated"] - valid["naive_open_atm"]
    for day, sub in valid.groupby("day"):
        gated = sub["gated"].mean()
        rmin = sub["random_minute_atm"].mean()
        d_p = sub["diff_primary"].mean()
        d_s_str = ""
        if "diff_secondary" in sub.columns and not sub["diff_secondary"].isna().all():
            d_s = sub["diff_secondary"].mean()
            d_s_str = f"  vs_naive={d_s:>+7.1f}pp"
        print(f"  {day}  n={len(sub):>2}  gated={gated:>+7.1f}%  "
              f"rmin={rmin:>+7.1f}%  vs_rmin={d_p:>+7.1f}pp{d_s_str}")

    # Per-direction breakdown
    print("\n=== Per-direction breakdown (primary control) ===")
    for direction, sub in valid.groupby("direction"):
        gated = sub["gated"].mean()
        rmin = sub["random_minute_atm"].mean()
        d = sub["diff_primary"].mean()
        wr_g = (sub["gated"] > 0).mean() * 100
        wr_r = (sub["random_minute_atm"] > 0).mean() * 100
        print(f"  {direction:8s}  n={len(sub):>2}  "
              f"gated WR={wr_g:>5.1f}% avg={gated:>+6.1f}%  "
              f"rmin WR={wr_r:>5.1f}% avg={rmin:>+6.1f}%  "
              f"diff={d:>+6.1f}pp")

    return 0


if __name__ == "__main__":
    sys.exit(main())
