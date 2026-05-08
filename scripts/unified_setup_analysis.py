"""Analysis & comparison of unified setup backtest results.

Reads from `unified_setup_backtest.db` and produces:
  1. Per-setup summary (n, mean MFE, win50, policy P&L, bootstrap CI)
  2. Best exit policy per setup
  3. Day-type segmentation (gap up/down/flat × inside/outside PDR × trend/range)
  4. Per-month performance (regime stability)
  5. Top-N setup-exit-daytype combinations
  6. Forward-window deployment recommendations

Run after the full backtest completes:
  python scripts/unified_setup_analysis.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = "unified_setup_backtest.db"

POLICIES = ["pol_tp50_s30", "pol_tp100_s30", "pol_tp50_und_inv",
            "pol_tp50_ts5", "pol_tp50_ts10", "pol_tp50_ts30"]
POL_LABELS = {
    "pol_tp50_s30": "TP+50/Stop-30",
    "pol_tp100_s30": "TP+100/Stop-30",
    "pol_tp50_und_inv": "TP+50/UndInv",
    "pol_tp50_ts5": "TP+50/TS-5min",
    "pol_tp50_ts10": "TP+50/TS-10min",
    "pol_tp50_ts30": "TP+50/TS-30min",
}


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM unified_trades", conn)
    conn.close()
    df["month"] = df["day"].str[:7]
    df["win50"] = (df["mfe_pct"] >= 50).astype(int)
    df["win25"] = (df["mfe_pct"] >= 25).astype(int)
    return df


def cluster_bootstrap_ci(values: pd.Series, days: pd.Series,
                         n_resamples: int = 1000) -> tuple[float, float, float]:
    """Day-clustered bootstrap. Returns (mean, lo90, hi90)."""
    if len(values) == 0:
        return (0.0, 0.0, 0.0)
    df_local = pd.DataFrame({"v": values, "d": days})
    days_arr = df_local["d"].unique()
    if len(days_arr) < 2:
        return (float(values.mean()), float("nan"), float("nan"))
    means = []
    rng = np.random.default_rng(42)
    for _ in range(n_resamples):
        sample_days = rng.choice(days_arr, size=len(days_arr), replace=True)
        # Vectorized: sum per day, weight by sample count
        from collections import Counter
        c = Counter(sample_days)
        # Build sample by repeating per day's trades
        chunks = [df_local[df_local["d"] == d].assign(w=cnt)
                  for d, cnt in c.items()]
        if not chunks:
            continue
        s = pd.concat(chunks)
        # Weighted mean by replication count
        means.append((s["v"] * s["w"]).sum() / s["w"].sum())
    means = np.array(means)
    return (float(means.mean()),
            float(np.percentile(means, 5)),
            float(np.percentile(means, 95)))


def per_setup_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for setup, sub in df.groupby("setup"):
        n = len(sub)
        days = sub["day"].nunique()
        for pol in POLICIES:
            mean, lo, hi = cluster_bootstrap_ci(sub[pol], sub["day"], 500)
            rows.append({
                "setup": setup,
                "n": n,
                "days": days,
                "policy": pol,
                "mean_pnl": mean,
                "ci_lo": lo,
                "ci_hi": hi,
                "median_pnl": float(sub[pol].median()),
                "win50_rate": float(sub["win50"].mean()),
                "mean_mfe": float(sub["mfe_pct"].mean()),
                "mean_eod": float(sub["eod_pct"].mean()),
            })
    return pd.DataFrame(rows)


def per_setup_per_month(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    rows = []
    for (setup, month), sub in df.groupby(["setup", "month"]):
        rows.append({
            "setup": setup,
            "month": month,
            "n": len(sub),
            "mean": float(sub[policy].mean()),
            "win50": float(sub["win50"].mean()),
        })
    return pd.DataFrame(rows)


def per_setup_per_daytype(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    rows = []
    for (setup, daytype), sub in df.groupby(["setup", "daytype"]):
        rows.append({
            "setup": setup,
            "daytype": daytype,
            "n": len(sub),
            "days": sub["day"].nunique(),
            "mean": float(sub[policy].mean()),
            "win50": float(sub["win50"].mean()),
        })
    return pd.DataFrame(rows)


def best_exit_per_setup(summary: pd.DataFrame) -> pd.DataFrame:
    """For each setup, return the exit policy with highest mean P&L."""
    return (summary.sort_values(["setup", "mean_pnl"], ascending=[True, False])
            .groupby("setup").first().reset_index())


def top_setups(summary: pd.DataFrame, min_n: int = 30, top_k: int = 10) -> pd.DataFrame:
    sub = summary[summary["n"] >= min_n].copy()
    return sub.sort_values("mean_pnl", ascending=False).head(top_k)


def main() -> int:
    df = load_data()
    if df.empty:
        print("No data — backtest hasn't produced output yet.")
        return 0
    print(f"Total trades: {len(df)} across {df['day'].nunique()} days, "
          f"{df['setup'].nunique()} setups")
    print()

    print("=" * 110)
    print("PER-SETUP SUMMARY (across all days, for each exit policy)")
    print("=" * 110)
    print(f"{'setup':<25} {'pol':<18} {'n':<5} {'days':<5} "
          f"{'mean_pnl':<12} {'CI_90':<22} {'win50':<8} {'mfe':<8}")
    print("-" * 110)
    summary = per_setup_summary(df)
    for setup in sorted(summary["setup"].unique()):
        sub = summary[summary["setup"] == setup]
        for _, r in sub.iterrows():
            ci_str = f"[{r['ci_lo']:+.1f},{r['ci_hi']:+.1f}]"
            print(f"{r['setup']:<25} {POL_LABELS[r['policy']]:<18} "
                  f"{int(r['n']):<5} {int(r['days']):<5} "
                  f"{r['mean_pnl']:>+7.1f}%    {ci_str:<22} "
                  f"{r['win50_rate']*100:>4.0f}%   {r['mean_mfe']:>+5.0f}%")
        print()

    print()
    print("=" * 90)
    print("BEST EXIT POLICY PER SETUP")
    print("=" * 90)
    best = best_exit_per_setup(summary)
    print(f"{'setup':<25} {'best_policy':<18} {'mean_pnl':<10} "
          f"{'CI_90':<22} {'n':<5}")
    print("-" * 90)
    for _, r in best.sort_values("mean_pnl", ascending=False).iterrows():
        ci_str = f"[{r['ci_lo']:+.1f},{r['ci_hi']:+.1f}]"
        print(f"{r['setup']:<25} {POL_LABELS[r['policy']]:<18} "
              f"{r['mean_pnl']:>+7.1f}%    {ci_str:<22} "
              f"{int(r['n']):<5}")

    print()
    print("=" * 90)
    print("TOP-10 SETUPS (n>=30) by mean P&L (using best exit)")
    print("=" * 90)
    top = top_setups(summary, min_n=30, top_k=10)
    if not top.empty:
        print(f"{'rank':<5} {'setup':<25} {'pol':<18} {'mean':<10} "
              f"{'CI_90':<22} {'n':<5} {'win50':<6}")
        print("-" * 90)
        for i, (_, r) in enumerate(top.iterrows(), 1):
            ci_str = f"[{r['ci_lo']:+.1f},{r['ci_hi']:+.1f}]"
            print(f"{i:<5} {r['setup']:<25} {POL_LABELS[r['policy']]:<18} "
                  f"{r['mean_pnl']:>+7.1f}%    {ci_str:<22} "
                  f"{int(r['n']):<5} {r['win50_rate']*100:>4.0f}%")

    # Best per-policy in TP+50/Stop-30 (the canonical comparison)
    print()
    print("=" * 90)
    print("ALL SETUPS UNDER STANDARD TP+50/STOP-30 EXIT")
    print("=" * 90)
    pol_main = "pol_tp50_s30"
    main_view = summary[summary["policy"] == pol_main].sort_values(
        "mean_pnl", ascending=False)
    print(f"{'setup':<25} {'n':<5} {'days':<5} {'mean':<10} "
          f"{'CI_90':<22} {'win50':<6}")
    print("-" * 90)
    for _, r in main_view.iterrows():
        ci_str = f"[{r['ci_lo']:+.1f},{r['ci_hi']:+.1f}]"
        print(f"{r['setup']:<25} {int(r['n']):<5} {int(r['days']):<5} "
              f"{r['mean_pnl']:>+7.1f}%    {ci_str:<22} "
              f"{r['win50_rate']*100:>4.0f}%")

    # Per-month for top 5 setups
    print()
    print("=" * 90)
    print("PER-MONTH STABILITY (for top 5 setups under TP+50/Stop-30)")
    print("=" * 90)
    top5 = main_view.head(5)["setup"].tolist()
    monthly = per_setup_per_month(df, pol_main)
    pivot = monthly[monthly["setup"].isin(top5)].pivot_table(
        index="month", columns="setup", values="mean").round(1)
    print(pivot.to_string())

    # Day-type segmentation
    print()
    print("=" * 90)
    print("DAY-TYPE SEGMENTATION (TP+50/Stop-30)")
    print("=" * 90)
    daytype_view = per_setup_per_daytype(df, pol_main)
    pivot_dt = daytype_view.pivot_table(index="setup", columns="daytype",
                                        values="mean").round(1)
    print(pivot_dt.to_string())
    print()
    print("Sample sizes:")
    pivot_dt_n = daytype_view.pivot_table(index="setup", columns="daytype",
                                          values="n", aggfunc="sum")
    print(pivot_dt_n.to_string())

    # Save key tables to CSV
    summary.to_csv("docs/research/unified_setup_per_pol_summary.csv", index=False)
    monthly.to_csv("docs/research/unified_setup_per_month.csv", index=False)
    daytype_view.to_csv("docs/research/unified_setup_per_daytype.csv", index=False)

    print()
    print("Saved CSVs to docs/research/unified_setup_*.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
