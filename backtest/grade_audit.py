"""Grade audit — find why A grade underperforms B+ at 1d horizon.

Phase 6 critical investigation. The user's intuition was correct:
A grade has 41% 1d hit rate vs B+ 62%. This is ass-backwards.

Hypotheses to test:
  H1: A grade is biased toward specific signal_types that fail short-term
  H2: A grade is concentrated in BEAR-direction signals (which we
      know underperform in current bull tape per breadth gate logic)
  H3: A grade is biased toward 0DTE/short-DTE which is theta-heavy
  H4: A grade fires more in NEG_GAMMA regime (volatile, whipsaw-prone)
  H5: A grade fires near king/floor walls where short-term reversal is
      common (the "wall reverts then breaks" pattern)
  H6: A grade signals have wider stops/targets (worse R:R when hit)
  H7: A grade fires for specific tickers that systematically underperform
      (e.g., already-extended cohort names)

Run:
    python -m backtest.grade_audit
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

from server.config import get_settings


def load() -> pd.DataFrame:
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    # Join soe_signals to signal_outcomes for forward returns
    df = pd.read_sql_query("""
        SELECT s.id, s.ts, s.ticker, s.direction, s.signal_type, s.grade,
               s.score, s.max_score, s.dte, s.regime, s.iv, s.rr_ratio,
               s.option_type, s.spot, s.king, s.floor_level, s.ceiling_level,
               o.return_1d, o.return_3d, o.hit_1d, o.hit_3d
        FROM soe_signals s
        LEFT JOIN signal_outcomes o
          ON o.source_id = CAST(s.id AS TEXT) AND o.source_type = 'soe_signal'
        WHERE s.grade IN ('A+', 'A', 'B+', 'B', 'C')
          AND o.return_1d IS NOT NULL
    """, c)
    c.close()
    return df


def slice_compare(df: pd.DataFrame, dim: str, horizon: str = "1d") -> None:
    print(f"\n--- By {dim} ({horizon} forward) ---")
    col = f"return_{horizon}"
    grouped = df.groupby([dim, "grade"]).agg(
        n=(col, "count"),
        avg_ret=(col, "mean"),
        hit=(col, lambda x: (x > 0).mean()),
    ).reset_index()
    # Pivot to side-by-side
    pivot = grouped.pivot(index=dim, columns="grade", values=["n", "avg_ret", "hit"])
    if not pivot.empty:
        with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
            print(pivot.to_string())


def main() -> int:
    df = load()
    print(f"Loaded {len(df)} SOE signals with 1d outcomes\n")
    print(f"Grade distribution: {dict(df['grade'].value_counts())}")
    print(f"Date range: {pd.to_datetime(df['ts'], unit='s').min()} to {pd.to_datetime(df['ts'], unit='s').max()}")

    # Baseline by grade
    print("\n=== BASELINE: 1d outcomes by grade ===")
    baseline = df.groupby("grade").agg(
        n=("return_1d", "count"),
        avg_ret_1d=("return_1d", "mean"),
        hit_1d=("return_1d", lambda x: (x > 0).mean()),
        avg_ret_3d=("return_3d", "mean"),
        hit_3d=("return_3d", lambda x: (x > 0).mean()),
        avg_score=("score", "mean"),
    ).round(3)
    print(baseline.to_string())

    # H1: signal_type
    print("\n\n=== H1: A vs B+ by signal_type ===")
    for stype, sub in df.groupby("signal_type"):
        if len(sub) < 30:
            continue
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            print(f"  {stype:<35}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H2: direction
    print("\n=== H2: A vs B+ by direction ===")
    for d, sub in df.groupby("direction"):
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            print(f"  {d:<8}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H3: DTE
    print("\n=== H3: A vs B+ by DTE bucket ===")
    df["dte_bucket"] = pd.cut(df["dte"].fillna(99), bins=[-1, 1, 7, 30, 999],
                                labels=["0-1d", "2-7d", "8-30d", ">30d"])
    for b, sub in df.groupby("dte_bucket", observed=True):
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            print(f"  {b:<8}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H4: GEX regime
    print("\n=== H4: A vs B+ by regime ===")
    for r, sub in df.groupby("regime"):
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            print(f"  {r:<6}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H5: near king (proxy for "at structural wall")
    df["near_king"] = (df["spot"] - df["king"]).abs() / df["spot"] < 0.005
    print("\n=== H5: A vs B+ — near king (within 0.5% of king node) ===")
    for nk, sub in df.groupby("near_king"):
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            label = "near_king" if nk else "away_from_king"
            print(f"  {label:<16}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H6: option_type
    print("\n=== H6: A vs B+ by option_type ===")
    for ot, sub in df.groupby("option_type"):
        a = sub[sub["grade"].isin(["A", "A+"])]
        bp = sub[sub["grade"] == "B+"]
        if len(a) >= 5 and len(bp) >= 5:
            print(f"  {ot:<6}  A: n={len(a):>3} hit={a['return_1d'].gt(0).mean()*100:.0f}% avg={a['return_1d'].mean()*100:+5.2f}%   "
                  f"B+: n={len(bp):>3} hit={bp['return_1d'].gt(0).mean()*100:.0f}% avg={bp['return_1d'].mean()*100:+5.2f}%")

    # H7: top tickers for A grade
    print("\n=== H7: Top 15 tickers for A grade — outcomes ===")
    a_only = df[df["grade"].isin(["A", "A+"])]
    by_ticker = a_only.groupby("ticker").agg(
        n=("return_1d", "count"),
        hit_1d=("return_1d", lambda x: (x > 0).mean()),
        avg_1d=("return_1d", "mean"),
    )
    top = by_ticker.sort_values("n", ascending=False).head(15)
    print(top.round(3).to_string())

    # Cross — score percentile within grade
    print("\n=== Score breakdown: A signals are score X, B+ are score Y ===")
    print(df.groupby("grade")["score"].describe().round(2).to_string())

    # Save the full slice
    df.to_csv("data/grade_audit.csv", index=False)
    print(f"\nWrote {len(df)} rows to data/grade_audit.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
