"""Before/after analysis on this week's alerts (Apr 28 - May 1).

⚠️  Reads peak_pnl_pct / eod_pnl_pct from `zero_dte_alerts`, which were
populated by the deprecated `backfill_alert_outcomes.py` and are
contaminated (intrinsic-based, SPY×10 proxy for SPX). Findings from this
script before May 4 2026 should be re-run by joining to
`zero_dte_alerts_nbbo_outcomes` (built by
`scripts/backfill_alert_outcomes_nbbo.py`) which is the canonical source.

See `docs/research/EXIT_POLICY_NBBO_FINDING.md` for context on why the old
columns are wrong.

Original docstring:

Compares baseline outcomes vs filtered outcomes under the new
annotation-driven filter combinations. All filters are applied
RETROSPECTIVELY using the columns we just shipped.

Filter combinations tested:
  BASELINE         : all alerts, hold-to-EOD
  EXIT_TP50        : all alerts, peak-of-window if peak >= +50% (proxy
                     for TP-at-+50% exit; otherwise EOD)
  EXIT_TP25        : same with +25% threshold
  WORKFLOW         : require ST same-direction within 90min (Apr 29 rule)
  REGIME_FILTER    : skip NOISY tape regime
  REACHABILITY     : skip alerts with reach < 1.0
  MACRO_OR_ALIGNED : take only alerts in macro window OR cross-ticker aligned
  COMPOSITE_BEST   : combine reachability + non-NOISY + (macro OR aligned)

Each combination reports: n_taken, hit_rate, mean_pnl, median_pnl, total_pnl
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALERT_DB = "zero_dte_alerts.db"

# This week = Apr 28 (Mon) → May 1 (Fri)
WEEK_START = datetime(2026, 4, 28).timestamp()
WEEK_END = datetime(2026, 5, 1, 23, 59, 59).timestamp()


def fetch_week_alerts() -> pd.DataFrame:
    conn = sqlite3.connect(ALERT_DB)
    df = pd.read_sql(
        """SELECT alert_id, ticker, fired_at,
                  datetime(fired_at, 'unixepoch') as fired_iso,
                  direction, grade, strike, est_entry_price,
                  spot, target_level,
                  -- annotations
                  strike_reachability_ratio, expected_move_pct_to_eod,
                  open_to_spot_pct, path_efficiency, jump_share,
                  open_cross_count, directional_change_count,
                  tape_regime_at_fire, episode_id,
                  cross_ticker_aligned, cross_ticker_corr_30m,
                  in_macro_window, macro_event_label,
                  -- outcomes
                  peak_pnl_pct, peak_hhmm, mins_to_peak,
                  eod_pnl_pct, reached_itm,
                  mins_above_entry, mins_2x_entry,
                  outcome_category, st_confirmation_within_90m
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ?
           ORDER BY fired_at""",
        conn, params=(int(WEEK_START), int(WEEK_END)),
    )
    conn.close()
    df = df[df["peak_pnl_pct"].notna()].copy()
    return df


def policy_pnl(row: pd.Series, policy: str) -> float:
    """Return P&L per the named policy. None for filtered-out."""
    peak = row["peak_pnl_pct"]
    eod = row["eod_pnl_pct"]
    if pd.isna(peak) or pd.isna(eod):
        return None

    if policy == "EOD_HOLD":
        return float(eod)
    if policy == "TP25":
        return 25.0 if peak >= 25 else float(eod)
    if policy == "TP50":
        return 50.0 if peak >= 50 else float(eod)
    if policy == "TP50_STOP30":
        # If peak >= 50, take +50%. If eod < -30, assume stopped at -30.
        # Otherwise take eod.
        if peak >= 50:
            return 50.0
        if eod < -30:
            return -30.0
        return float(eod)
    if policy == "TP100_STOP30":
        if peak >= 100:
            return 100.0
        if eod < -30:
            return -30.0
        return float(eod)
    return None


def aggregate(df: pd.DataFrame, policy: str) -> dict:
    """Compute summary stats for a (filtered) df under a P&L policy."""
    if df.empty:
        return {"n": 0, "hit_rate": None, "mean_pnl": None,
                "median_pnl": None, "total_pnl": 0, "winners": 0}
    pnls = df.apply(lambda r: policy_pnl(r, policy), axis=1).dropna()
    if pnls.empty:
        return {"n": len(df), "hit_rate": None, "mean_pnl": None,
                "median_pnl": None, "total_pnl": 0, "winners": 0}
    winners = (pnls > 0).sum()
    return {
        "n": len(pnls),
        "hit_rate": float(winners / len(pnls)),
        "mean_pnl": float(pnls.mean()),
        "median_pnl": float(pnls.median()),
        "total_pnl": float(pnls.sum()),
        "winners": int(winners),
    }


def filter_combinations(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return named filter slices."""
    out = {"BASELINE": df.copy()}

    # WORKFLOW: require ST confirmation
    out["WORKFLOW (ST confirm)"] = df[df["st_confirmation_within_90m"] == 1].copy()

    # REGIME_FILTER: exclude NOISY (we have no NOISY tags this week, so this is a no-op)
    out["regime != NOISY"] = df[df["tape_regime_at_fire"] != "NOISY"].copy()

    # REACHABILITY: reach >= 1.0 (filter the obvious garbage)
    out["reach >= 1.0"] = df[df["strike_reachability_ratio"] >= 1.0].copy()

    # REACHABILITY 2.0: tighter threshold (winners cluster in 2.0-3.5)
    out["reach 2.0-4.0"] = df[
        (df["strike_reachability_ratio"] >= 2.0)
        & (df["strike_reachability_ratio"] <= 4.0)
    ].copy()

    # MACRO: take only macro-window alerts
    out["macro window only"] = df[df["in_macro_window"] == 1].copy()

    # ALIGNED: take only cross-ticker aligned
    out["cross-ticker aligned"] = df[df["cross_ticker_aligned"] == 1].copy()

    # COMPOSITE: macro OR aligned
    out["macro OR aligned"] = df[
        (df["in_macro_window"] == 1) | (df["cross_ticker_aligned"] == 1)
    ].copy()

    # FIRST_OF_EPISODE: only the first alert per episode (de-duplicate chases)
    first_per_ep = df.sort_values("fired_at").drop_duplicates(
        subset=["episode_id"], keep="first"
    )
    out["first of episode"] = first_per_ep.copy()

    # COMPOSITE BEST: reach in 2-4 AND first-of-episode AND non-NOISY
    keep_eps = set(first_per_ep["episode_id"])
    out["BEST: reach 2-4 + first-of-ep + non-NOISY"] = df[
        df["episode_id"].isin(keep_eps)
        & (df["strike_reachability_ratio"] >= 2.0)
        & (df["strike_reachability_ratio"] <= 4.0)
        & (df["tape_regime_at_fire"] != "NOISY")
    ].copy()

    # FIRST_OF_EP + macro_or_aligned
    out["BEST 2: first-of-ep + (macro OR aligned)"] = first_per_ep[
        (first_per_ep["in_macro_window"] == 1)
        | (first_per_ep["cross_ticker_aligned"] == 1)
    ].copy()

    return out


def report(df: pd.DataFrame) -> str:
    lines = []
    lines.append("# Week Analysis — Before/After WR with New Annotation Filters")
    lines.append("")
    lines.append(f"Window: Apr 28 (Mon) – May 1 (Fri). Apr 30 (Thu) had no "
                 f"backend running, so 0 alerts that day.")
    lines.append("")
    lines.append(f"**Sample**: {len(df)} alerts (SPY/QQQ/SPX, all bullish, "
                 f"all B+ grade)")
    lines.append("")

    # Per-day breakdown
    df["day"] = pd.to_datetime(df["fired_iso"]).dt.strftime("%Y-%m-%d")
    lines.append("## Per-day breakdown")
    lines.append("")
    lines.append("Day | Alerts | Winners | Tape regime | Macro | Days "
                 "summary")
    lines.append("---|---|---|---|---|---")
    for day, sub in df.groupby("day"):
        n = len(sub)
        winners = (sub["peak_pnl_pct"] > 0).sum()
        tape = sub["tape_regime_at_fire"].mode()
        tape_str = tape.iloc[0] if len(tape) else "?"
        macro = sub["macro_event_label"].dropna().mode()
        macro_str = macro.iloc[0] if len(macro) else "—"
        lines.append(f"{day} | {n} | {winners}/{n} | {tape_str} | {macro_str} | "
                     f"mean peak {sub['peak_pnl_pct'].mean():+.0f}%")
    lines.append("")

    # Filter combinations table
    lines.append("## Filter combinations × exit policies")
    lines.append("")
    filters = filter_combinations(df)

    policies = ["EOD_HOLD", "TP50", "TP50_STOP30", "TP100_STOP30"]

    # Big table: rows = filters, cols = policies, cells = mean P&L
    lines.append("Mean P&L per trade, per filter × policy combination:")
    lines.append("")
    header = "Filter (n trades) | " + " | ".join(policies)
    sep = "---|" + "|".join("---" for _ in policies)
    lines.append(header)
    lines.append(sep)
    for filter_name, fdf in filters.items():
        n = len(fdf)
        cells = []
        for p in policies:
            agg = aggregate(fdf, p)
            if agg["mean_pnl"] is None:
                cells.append("n/a")
            else:
                cells.append(f"{agg['mean_pnl']:+.0f}%")
        lines.append(f"{filter_name} (n={n}) | " + " | ".join(cells))
    lines.append("")

    # Hit rate table: same shape but cell = hit_rate
    lines.append("Hit rate (% trades with P&L > 0), per filter × policy:")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for filter_name, fdf in filters.items():
        n = len(fdf)
        cells = []
        for p in policies:
            agg = aggregate(fdf, p)
            if agg["hit_rate"] is None:
                cells.append("n/a")
            else:
                cells.append(f"{agg['hit_rate']*100:.0f}%")
        lines.append(f"{filter_name} (n={n}) | " + " | ".join(cells))
    lines.append("")

    # Detail: total P&L per filter (assuming 1 trade unit each)
    lines.append("Total P&L (sum across all alerts taken under that filter, "
                 "%-of-entry units):")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for filter_name, fdf in filters.items():
        n = len(fdf)
        cells = []
        for p in policies:
            agg = aggregate(fdf, p)
            if agg["total_pnl"] == 0 and n == 0:
                cells.append("n/a")
            else:
                cells.append(f"{agg['total_pnl']:+.0f}%")
        lines.append(f"{filter_name} (n={n}) | " + " | ".join(cells))
    lines.append("")

    # Per-alert table (best filter combination)
    lines.append("## Per-alert detail (this week)")
    lines.append("")
    lines.append("Day fire | tkr | strike | reach | tape | macro | aligned | "
                 "peak | category | EOD | TP50_S30")
    lines.append("---|---|---|---|---|---|---|---|---|---|---")
    for _, r in df.sort_values("fired_at").iterrows():
        day = r["fired_iso"][5:10]  # MM-DD
        time = r["fired_iso"][11:16]
        reach = r["strike_reachability_ratio"]
        reach_str = f"{reach:.2f}" if pd.notna(reach) else "?"
        tape = r["tape_regime_at_fire"] or "?"
        macro = r["macro_event_label"] or "—"
        aligned = "✓" if r["cross_ticker_aligned"] == 1 else (
            "✗" if r["cross_ticker_aligned"] == 0 else "?"
        )
        peak = r["peak_pnl_pct"]
        cat = r["outcome_category"]
        eod = r["eod_pnl_pct"]
        tp50_stop30 = policy_pnl(r, "TP50_STOP30")
        lines.append(
            f"{day} {time} | {r['ticker']} | {r['strike']:.0f} | "
            f"{reach_str} | {tape} | {macro} | {aligned} | "
            f"{peak:+.0f}% | {cat} | {eod:+.0f}% | "
            f"{tp50_stop30:+.0f}% "
        )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    df = fetch_week_alerts()
    print(f"Loaded {len(df)} alerts with outcomes")
    out = report(df)
    out_path = ROOT / "docs" / "research" / "WEEK_ANALYSIS_BEFORE_AFTER.md"
    out_path.write_text(out, encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
