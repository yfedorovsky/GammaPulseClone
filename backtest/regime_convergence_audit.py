"""Backtest harness — convergence bonus + macro regime tag validation.

The keystone analysis Perplexity called out: without this, every regime/
convergence change is vibes. Joins soe_signals + signal_outcomes +
macro_regime_tag + factors blob and emits the WR slices that decide
whether to flip MACRO_REGIME_LIVE=true.

Slices produced (in priority order):

  1. PROMOTED A's by regime tag + time-of-day
     The single most diagnostic cut — answers "did convergence-promoted
     A's underperform original A's, and was the underperformance worse
     in HARD regime?"

  2. WR by regime tag (NONE/SOFT/HARD/A_ONLY) for all SOE
     Validates the regime tag itself

  3. WR by signal_type × regime tag
     Some setup types may be more chop-sensitive than others

  4. Convergence factor decomposition
     Did net_flow vs flow_alert convergence behave differently?

Promoted A definition:
  An A or A+ signal where convergence_bonus > 0. Currently we don't
  persist the original score, so we infer "promoted" from the presence
  of the convergence reason in the reasoning text.

Run:
    python backtest/regime_convergence_audit.py
    python backtest/regime_convergence_audit.py --days 14
    python backtest/regime_convergence_audit.py --csv data/audit.csv
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.config import get_settings


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14,
                   help="Lookback in days (default 14)")
    p.add_argument("--csv", type=str, default=None,
                   help="Optional path to write the joined DataFrame")
    p.add_argument("--utf8", action="store_true",
                   help="Force utf-8 stdout (Windows)")
    p.add_argument("--min-n", type=int, default=5,
                   help="Suppress slices with n<min-n (noise floor)")
    return p.parse_args()


def load(days: int) -> pd.DataFrame:
    """Join soe_signals to signal_outcomes + add convergence/regime fields.
    Returns a single DataFrame ready for slicing."""
    s = get_settings()
    cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
    c = sqlite3.connect(s.snapshot_db)
    # Try to join trade_journal too (created by scripts/trade_journal.py).
    # Optional — table may not exist yet in this DB.
    has_journal = False
    try:
        c.execute("SELECT 1 FROM trade_journal LIMIT 1")
        has_journal = True
    except sqlite3.OperationalError:
        pass

    journal_join = """
        LEFT JOIN trade_journal j
          ON j.source_type = 'soe_signal' AND j.source_id = CAST(s.id AS TEXT)
    """ if has_journal else ""
    journal_cols = (
        ", j.felt_quality AS journal_quality, j.reason_taken AS journal_reason"
        if has_journal else
        ", NULL AS journal_quality, NULL AS journal_reason"
    )

    df = pd.read_sql_query(f"""
        SELECT s.id, s.ts, s.ticker, s.direction, s.signal_type, s.grade,
               s.score, s.max_score, s.dte, s.regime, s.iv, s.rr_ratio,
               s.spot, s.king, s.zgl, s.reasoning,
               s.macro_regime_tag, s.macro_regime_factors,
               o.return_1d, o.return_3d, o.return_1w,
               o.hit_1d, o.hit_3d, o.hit_1w
               {journal_cols}
        FROM soe_signals s
        LEFT JOIN signal_outcomes o
          ON o.source_id = CAST(s.id AS TEXT) AND o.source_type = 'soe_signal'
        {journal_join}
        WHERE s.ts >= ?
    """, c, params=(cutoff,))
    c.close()

    if df.empty:
        return df

    df["dt"] = pd.to_datetime(df["ts"], unit="s")
    df["hour_et"] = df["dt"].dt.tz_localize("UTC").dt.tz_convert(
        "US/Eastern").dt.hour

    # Time-of-day buckets (ET)
    def _tod(h):
        if h < 11:
            return "OPEN_90M"
        if h < 14:
            return "MIDDAY"
        return "PM"
    df["time_of_day"] = df["hour_et"].apply(_tod)

    # Promoted A inference: A/A+ signal with "convergence" in reasoning
    df["is_a_grade"] = df["grade"].isin(["A", "A+"])
    df["was_promoted"] = (
        df["is_a_grade"]
        & df["reasoning"].fillna("").str.contains("convergence", case=False)
    )
    df["a_class"] = df.apply(
        lambda r: "PROMOTED_A" if r["is_a_grade"] and r["was_promoted"]
        else ("ORIGINAL_A" if r["is_a_grade"] else "NOT_A"),
        axis=1,
    )

    # Direction-aware hit (for BULL: ret > 0; BEAR: ret < 0). Default to
    # BULL since the engine fires mostly bullish.
    def _dir_hit(row, h):
        ret = row[f"return_{h}"]
        if pd.isna(ret):
            return None
        d = (row.get("direction") or "").upper()
        if d in ("BEAR", "▼", "SHORT"):
            return 1 if ret < 0 else 0
        return 1 if ret > 0 else 0

    for h in ("1d", "3d", "1w"):
        df[f"dhit_{h}"] = df.apply(lambda r: _dir_hit(r, h), axis=1)

    # Regime tag normalization
    df["macro_regime_tag"] = df["macro_regime_tag"].fillna("NONE")

    return df


def _slice_summary(sub: pd.DataFrame, label: str, min_n: int) -> dict | None:
    valid = sub.dropna(subset=["dhit_1d"])
    if len(valid) < min_n:
        return None
    return {
        "label": label,
        "n": len(sub),
        "n_with_outcome": len(valid),
        "hit_1d_pct": valid["dhit_1d"].mean() * 100,
        "hit_3d_pct": (valid["dhit_3d"].dropna().mean() * 100
                        if len(valid["dhit_3d"].dropna()) else None),
        "avg_ret_1d_pct": valid["return_1d"].mean() * 100,
        "avg_ret_3d_pct": valid["return_3d"].dropna().mean() * 100,
    }


def print_table(rows: list[dict], title: str) -> None:
    print(f"\n{title}")
    print("-" * 100)
    print(f"  {'slice':<48}{'n':>5}{'n+ret':>7}{'1d_hit':>9}"
          f"{'3d_hit':>9}{'avg_1d':>9}{'avg_3d':>9}")
    for r in rows:
        avg_3d_str = (f"{r['avg_ret_3d_pct']:+.2f}%"
                      if r['avg_ret_3d_pct'] is not None else "—")
        hit_3d_str = (f"{r['hit_3d_pct']:>5.0f}%"
                      if r['hit_3d_pct'] is not None else "  —  ")
        print(f"  {r['label'][:48]:<48}{r['n']:>5}{r['n_with_outcome']:>7}"
              f"{r['hit_1d_pct']:>8.0f}%"
              f"  {hit_3d_str}"
              f"{r['avg_ret_1d_pct']:>+8.2f}%"
              f"  {avg_3d_str:>7}")


def main():
    args = parse_args()
    if args.utf8:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 100)
    print(f"REGIME × CONVERGENCE AUDIT — last {args.days}d, {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 100)

    df = load(args.days)
    if df.empty:
        print("No signals in window.")
        return 0

    print(f"\nLoaded {len(df)} SOE signals "
          f"({df.dropna(subset=['return_1d']).shape[0]} with 1d outcomes)")
    print(f"  Grade dist: {dict(df['grade'].value_counts())}")
    print(f"  Regime dist: {dict(df['macro_regime_tag'].value_counts())}")
    print(f"  A class dist: {dict(df['a_class'].value_counts())}")

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nWrote {len(df)} rows to {args.csv}")

    # ── Slice 1: PROMOTED vs ORIGINAL A's by regime tag ──────────────
    print("\n" + "=" * 100)
    print("SLICE 1: A-grade outcomes by promotion status × regime tag")
    print("This is the keystone — answers if convergence promotion adds or hurts edge.")
    print("=" * 100)
    a_only = df[df["is_a_grade"]]
    if a_only.empty:
        print("  No A-grade signals in window.")
    else:
        rows = []
        for (a_class, tag), sub in a_only.groupby(["a_class", "macro_regime_tag"]):
            r = _slice_summary(sub, f"{a_class} | {tag}", args.min_n)
            if r:
                rows.append(r)
        if rows:
            print_table(rows, "Promoted vs Original A by macro_regime_tag:")
        else:
            print(f"  No slices with n >= {args.min_n} forward outcomes yet.")

    # ── Slice 2: All SOE WR by regime tag ────────────────────────────
    print("\n" + "=" * 100)
    print("SLICE 2: All SOE outcomes by regime tag")
    print("Validates the regime tag itself.")
    print("=" * 100)
    rows = []
    for tag, sub in df.groupby("macro_regime_tag"):
        r = _slice_summary(sub, f"regime={tag}", args.min_n)
        if r:
            rows.append(r)
    print_table(rows, "All SOE by regime:")

    # ── Slice 3: WR by signal_type × regime tag ──────────────────────
    print("\n" + "=" * 100)
    print("SLICE 3: WR by signal_type × regime tag")
    print("Does some setup type degrade more in HARD?")
    print("=" * 100)
    rows = []
    for (st, tag), sub in df.groupby(["signal_type", "macro_regime_tag"]):
        r = _slice_summary(sub, f"{st[:30]} | {tag}", args.min_n)
        if r:
            rows.append(r)
    print_table(rows, "Signal type × regime:")

    # ── Slice 4: Convergence-promoted vs untouched A's by time-of-day ──
    print("\n" + "=" * 100)
    print("SLICE 4: Promoted A's by time-of-day")
    print("Late-day convergence is often hedging/closing, not initiation.")
    print("=" * 100)
    promoted = df[df["a_class"] == "PROMOTED_A"]
    if promoted.empty:
        print("  No promoted A's in window yet (zero convergence fires).")
    else:
        rows = []
        for tod, sub in promoted.groupby("time_of_day"):
            r = _slice_summary(sub, f"PROMOTED_A | {tod}", args.min_n)
            if r:
                rows.append(r)
        print_table(rows, "Promoted A's by time-of-day:")

    # ── Headline verdict ─────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("HEADLINE VERDICT")
    print("=" * 100)
    valid_a = a_only.dropna(subset=["dhit_1d"])
    if not valid_a.empty:
        prom = valid_a[valid_a["a_class"] == "PROMOTED_A"]
        orig = valid_a[valid_a["a_class"] == "ORIGINAL_A"]
        if len(prom) >= args.min_n and len(orig) >= args.min_n:
            prom_hit = prom["dhit_1d"].mean() * 100
            orig_hit = orig["dhit_1d"].mean() * 100
            delta = prom_hit - orig_hit
            print(f"  Promoted A's 1d hit: {prom_hit:.1f}% (n={len(prom)})")
            print(f"  Original A's 1d hit: {orig_hit:.1f}% (n={len(orig)})")
            print(f"  Delta: {delta:+.1f}pp")
            if delta < -5:
                print(f"\n  → CONVERGENCE IS HURTING. Disable bonus.")
            elif delta > 5:
                print(f"\n  → CONVERGENCE IS HELPING.")
            else:
                print(f"\n  → INCONCLUSIVE (within ±5pp). Need more data.")
        else:
            print(f"  Need ≥{args.min_n} samples in each bucket. "
                  f"Have promoted={len(prom)}, original={len(orig)}.")
    else:
        print("  No A-grade signals with outcomes yet.")

    # Same for HARD regime
    valid_hard = df[df["macro_regime_tag"] == "HARD"].dropna(subset=["dhit_1d"])
    valid_none = df[df["macro_regime_tag"] == "NONE"].dropna(subset=["dhit_1d"])
    if len(valid_hard) >= args.min_n and len(valid_none) >= args.min_n:
        hard_hit = valid_hard["dhit_1d"].mean() * 100
        none_hit = valid_none["dhit_1d"].mean() * 100
        delta = hard_hit - none_hit
        print(f"\n  HARD-regime SOE 1d hit: {hard_hit:.1f}% (n={len(valid_hard)})")
        print(f"  NONE-regime SOE 1d hit: {none_hit:.1f}% (n={len(valid_none)})")
        print(f"  Delta: {delta:+.1f}pp")
        if delta < -5:
            print(f"\n  → REGIME RULE JUSTIFIED. Flip MACRO_REGIME_LIVE=true.")
        else:
            print(f"\n  → REGIME RULE NOT YET JUSTIFIED. Keep shadow.")
    else:
        print(f"\n  Regime comparison needs ≥{args.min_n} samples in each bucket.")
        print(f"  Have HARD={len(valid_hard)}, NONE={len(valid_none)}.")

    # ── Slice 5: Self-rated quality vs realized outcomes (if journal data) ──
    journal_present = "journal_quality" in df.columns and df["journal_quality"].notna().any()
    if journal_present:
        print("\n" + "=" * 100)
        print("SLICE 5: Self-rated felt_quality vs realized 1d outcomes")
        print("Are your gut quality calls predictive? (1=worst, 5=best)")
        print("=" * 100)
        rows = []
        journaled = df[df["journal_quality"].notna()]
        for q, sub in journaled.groupby("journal_quality"):
            r = _slice_summary(sub, f"felt_quality={int(q)}", args.min_n)
            if r:
                rows.append(r)
        if rows:
            print_table(rows, "Self-rated quality vs outcome:")
        else:
            print(f"  Need >= {args.min_n} journaled trades per quality bucket.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
