"""Phase 0 analysis: address the convergent LLM critiques.

Runs the following on the existing 2374 unified_setup_backtest.db:

1. SLIPPAGE HAIRCUT — parametric model. For each trade, apply spread cost on
   entry (buy at ask) and exit (sell at bid). Spreads modeled as fraction of mid.
2. WALK-FORWARD SPLIT — rank setups on first 3 months, evaluate on last 3.
3. SIGNAL COLLISION DEDUP — collapse same-direction signals within 10 min into
   one trade idea. Re-rank.
4. MFE/MAE DISTRIBUTIONS — for top 5 setups, distribution of (% hit +30/+50/+
   100/+150 before -30) to validate TP+100 edge.
5. M/W/F vs T/Th filter — does day-of-week matter?
6. PARTIAL EXIT POLICY — 50% at +50, 50% at +100. Compare to full TP+100.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = "unified_setup_backtest.db"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM unified_trades", conn)
    conn.close()
    df["dow"] = pd.to_datetime(df["day"]).dt.dayofweek  # 0=Mon, 4=Fri
    df["month"] = df["day"].str[:7]
    df["win50"] = (df["mfe_pct"] >= 50).astype(int)
    df["win100"] = (df["mfe_pct"] >= 100).astype(int)
    return df


def apply_slippage_haircut(mfe_pct: float, eod_pct: float,
                           spread_pct: float, tp: float, stop: float) -> float:
    """Apply parametric slippage to TP+X/Stop-Y exit.

    spread_pct = full spread as fraction of mid (e.g., 0.05 = 5% spread)
    Entry at ask = mid * (1 + spread/2). Exit at bid = mid * (1 - spread/2).

    For TP exit: option mid touches (1+tp/100) * entry_ask.
        At exit: option mid = entry_ask * (1+tp/100). Exit at bid = mid*(1-spread/2).
        Net P&L = (exit_bid - entry_ask) / entry_ask
                = ((1+tp/100)*(1-spread/2) - 1)
                = tp/100 - spread/2 - tp*spread/200

    Approximation for small spread:
        TP_realized = tp - 100*spread (round-trip cost = spread)

    For stop: similar, stop is hit at lower price, exit at bid.
    For EOD: option mid at close, exit at bid.
    """
    rt_cost = 100.0 * spread_pct  # round-trip cost in pp
    if mfe_pct >= tp:
        return tp - rt_cost
    if eod_pct <= stop:
        return stop - rt_cost
    return eod_pct - rt_cost


def slippage_table(df: pd.DataFrame) -> None:
    print("=" * 110)
    print("SLIPPAGE-HAIRCUT TABLE: TP+100/Stop-30 mean P&L per setup, varying spread")
    print("=" * 110)
    print(f"{'setup':<25} {'n':<5} "
          f"{'mid (raw)':<11} {'5% spread':<11} {'8% spread':<11} {'10% spread':<11}")
    print("-" * 110)
    rows = []
    for setup, sub in df.groupby("setup"):
        n = len(sub)
        # Mid (raw)
        raw = sub.apply(
            lambda r: 100.0 if r["mfe_pct"] >= 100 else (
                -30.0 if r["eod_pct"] <= -30 else r["eod_pct"]),
            axis=1).mean()
        # Apply haircuts
        h5 = sub.apply(
            lambda r: apply_slippage_haircut(r["mfe_pct"], r["eod_pct"], 0.05, 100, -30),
            axis=1).mean()
        h8 = sub.apply(
            lambda r: apply_slippage_haircut(r["mfe_pct"], r["eod_pct"], 0.08, 100, -30),
            axis=1).mean()
        h10 = sub.apply(
            lambda r: apply_slippage_haircut(r["mfe_pct"], r["eod_pct"], 0.10, 100, -30),
            axis=1).mean()
        rows.append((setup, n, raw, h5, h8, h10))
    rows.sort(key=lambda x: -x[3])  # sort by 5% spread realistic
    for setup, n, raw, h5, h8, h10 in rows:
        print(f"{setup:<25} {n:<5} {raw:>+6.1f}%    {h5:>+6.1f}%    "
              f"{h8:>+6.1f}%    {h10:>+6.1f}%")
    print()
    print("Realistic SPY 0DTE ATM spread is ~3-8% of mid (depends on time of day).")
    print("Conservative deployment estimate: use the 8% column.")


def walk_forward_split(df: pd.DataFrame) -> None:
    print()
    print("=" * 90)
    print("WALK-FORWARD: rank setups on first half, evaluate on second half")
    print("=" * 90)
    days = sorted(df["day"].unique())
    split_idx = len(days) // 2
    split_day = days[split_idx]
    train = df[df["day"] < split_day]
    test = df[df["day"] >= split_day]
    print(f"Train: {len(train)} trades, days {days[0]} to {days[split_idx-1]}")
    print(f"Test:  {len(test)} trades, days {split_day} to {days[-1]}")
    print()
    print(f"{'setup':<25} {'train_n':<8} {'train_mean':<12} "
          f"{'test_n':<8} {'test_mean':<12} {'delta':<10}")
    print("-" * 90)
    rows = []
    for setup in df["setup"].unique():
        tr = train[train["setup"] == setup]["pol_tp50_s30"]
        te = test[test["setup"] == setup]["pol_tp50_s30"]
        if len(tr) < 10 or len(te) < 10:
            continue
        rows.append((setup, len(tr), tr.mean(), len(te), te.mean()))
    # Sort by train mean to see if top setups stay top
    rows.sort(key=lambda x: -x[2])
    for setup, ntr, mtr, nte, mte in rows:
        delta = mte - mtr
        flag = "OK" if abs(delta) < 8 else ("DEGRADED" if delta < 0 else "IMPROVED")
        print(f"{setup:<25} {ntr:<8} {mtr:>+6.1f}%      "
              f"{nte:<8} {mte:>+6.1f}%      {delta:>+5.1f}pp  {flag}")
    print()
    # Top-5 in train: how do they rank in test?
    top5_train = sorted(rows, key=lambda x: -x[2])[:5]
    print("Top 5 setups in TRAIN sample:")
    train_top = [r[0] for r in top5_train]
    rows_test_sorted = sorted(rows, key=lambda x: -x[4])
    test_rank = {r[0]: i+1 for i, r in enumerate(rows_test_sorted)}
    for r in top5_train:
        print(f"  {r[0]:<25}: train={r[2]:+.1f}%, test={r[4]:+.1f}%, "
              f"test_rank={test_rank.get(r[0], '?')}/{len(rows)}")


def signal_collision_dedup(df: pd.DataFrame) -> None:
    print()
    print("=" * 90)
    print("SIGNAL COLLISION ANALYSIS: same-day same-direction signals within 10 min")
    print("=" * 90)
    # Convert cross_hhmm to minute-of-day
    df = df.copy()
    df["minute_of_day"] = df["cross_hhmm"].apply(
        lambda x: int(x[:2]) * 60 + int(x[3:5]) if len(x) >= 5 else 0)
    # Priority: sweep > pmh/pml > orb > vwap > ema
    SETUP_PRIORITY = {
        "sweep_pmh": 1, "sweep_pml": 1,
        "pmh_break": 2, "pml_break": 2,
        "failed_pmh_break": 3, "failed_pml_break": 3,
        "failed_pdh_break": 3, "failed_pdl_break": 3,
        "orb5_break": 4, "orb15_break": 4, "orb30_break": 4,
        "orb15_break_vwap": 4, "orb30_break_vwap": 4,
        "vwap_lose": 5, "vwap_reclaim": 5, "vwap_2sd_fade": 5,
        "ema_cross_imm": 6, "ema_cross_pullback": 6,
    }
    df["priority"] = df["setup"].map(SETUP_PRIORITY).fillna(99).astype(int)

    # For each day + direction, find collisions
    n_total = len(df)
    keep_mask = pd.Series(True, index=df.index)
    n_collisions = 0
    for (day, direction), grp in df.groupby(["day", "direction"]):
        g = grp.sort_values(["minute_of_day", "priority"]).reset_index()
        if len(g) <= 1:
            continue
        last_kept_min = -999
        for _, r in g.iterrows():
            if r["minute_of_day"] - last_kept_min < 10:
                keep_mask.loc[r["index"]] = False
                n_collisions += 1
            else:
                last_kept_min = r["minute_of_day"]
    deduped = df[keep_mask]
    print(f"Total trades: {n_total}, after 10-min cooldown dedup: {len(deduped)} "
          f"(removed {n_collisions}, {n_collisions/n_total*100:.0f}%)")
    print()
    print("Per-setup count change after dedup:")
    print(f"{'setup':<25} {'before':<8} {'after':<8} {'kept_pct':<10} "
          f"{'pre_mean':<10} {'post_mean':<10}")
    print("-" * 80)
    for setup in sorted(df["setup"].unique()):
        before = len(df[df["setup"] == setup])
        after = len(deduped[deduped["setup"] == setup])
        pre_mean = df[df["setup"] == setup]["pol_tp50_s30"].mean()
        post_mean = (deduped[deduped["setup"] == setup]["pol_tp50_s30"].mean()
                     if after > 0 else 0)
        print(f"{setup:<25} {before:<8} {after:<8} {after/before*100:.0f}%      "
              f"{pre_mean:>+6.1f}%   {post_mean:>+6.1f}%")


def mfe_distribution(df: pd.DataFrame, top_setups: list[str]) -> None:
    print()
    print("=" * 90)
    print("MFE DISTRIBUTION (top 5 setups): is TP+100 outlier-driven or sustainable?")
    print("=" * 90)
    print(f"{'setup':<22} {'n':<5} "
          f"{'%hit_+30':<10} {'%hit_+50':<10} {'%hit_+100':<10} {'%hit_+150':<10} "
          f"{'med_min_to_50':<14} {'med_min_to_100':<14}")
    print("-" * 110)
    for setup in top_setups:
        sub = df[df["setup"] == setup]
        if len(sub) == 0:
            continue
        n = len(sub)
        h30 = (sub["mfe_pct"] >= 30).mean() * 100
        h50 = (sub["mfe_pct"] >= 50).mean() * 100
        h100 = (sub["mfe_pct"] >= 100).mean() * 100
        h150 = (sub["mfe_pct"] >= 150).mean() * 100
        med_to_50 = sub[sub["mfe_pct"] >= 50]["mins_to_peak"].median() \
            if (sub["mfe_pct"] >= 50).sum() > 0 else 0
        med_to_100 = sub[sub["mfe_pct"] >= 100]["mins_to_peak"].median() \
            if (sub["mfe_pct"] >= 100).sum() > 0 else 0
        print(f"{setup:<22} {n:<5} {h30:>5.0f}%    {h50:>5.0f}%    "
              f"{h100:>5.0f}%    {h150:>5.0f}%    "
              f"{int(med_to_50):>5} min       {int(med_to_100):>5} min")
    print()
    print("Read: if % hit +100 is roughly half of % hit +50, the runners are real")
    print("(each TP+50 winner has ~50% chance of also reaching +100). If much less,")
    print("then TP+100 mean is outlier-driven.")
    print()
    print(f"{'setup':<22} {'condit':<25}")
    print("-" * 50)
    for setup in top_setups:
        sub = df[df["setup"] == setup]
        if len(sub) == 0:
            continue
        n50 = (sub["mfe_pct"] >= 50).sum()
        n100 = (sub["mfe_pct"] >= 100).sum()
        if n50 == 0:
            continue
        cond = n100 / n50 * 100
        print(f"{setup:<22} P(hit+100 | hit+50) = {cond:.0f}%")


def day_of_week_filter(df: pd.DataFrame) -> None:
    print()
    print("=" * 90)
    print("M/W/F vs T/Th DAY-OF-WEEK SPLIT (TP+50/Stop-30)")
    print("=" * 90)
    df = df.copy()
    DOW_NAME = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri"}
    df["dow_name"] = df["dow"].map(DOW_NAME)
    df["mwf"] = df["dow"].isin([0, 2, 4])  # M=0, W=2, F=4
    print(f"{'setup':<25} {'MWF_n':<8} {'MWF_mean':<10} "
          f"{'TTh_n':<8} {'TTh_mean':<10} {'delta':<10}")
    print("-" * 80)
    rows = []
    for setup in sorted(df["setup"].unique()):
        sub = df[df["setup"] == setup]
        mwf = sub[sub["mwf"]]
        tth = sub[~sub["mwf"]]
        if len(mwf) < 5 or len(tth) < 5:
            continue
        mwfm = mwf["pol_tp50_s30"].mean()
        tthm = tth["pol_tp50_s30"].mean()
        delta = mwfm - tthm
        rows.append((setup, len(mwf), mwfm, len(tth), tthm, delta))
    # sort by delta to find biggest M/W/F advantage
    rows.sort(key=lambda x: -x[5])
    for setup, n_mwf, m_mwf, n_tth, m_tth, delta in rows:
        flag = " ← MWF FAVOURED" if delta > 5 else (" ← TTh FAVOURED" if delta < -5 else "")
        print(f"{setup:<25} {n_mwf:<8} {m_mwf:>+6.1f}%   {n_tth:<8} {m_tth:>+6.1f}%   "
              f"{delta:>+5.1f}pp{flag}")


def partial_exit_policy(df: pd.DataFrame, top_setups: list[str]) -> None:
    print()
    print("=" * 90)
    print("PARTIAL EXIT POLICY: 50% at +50 / 50% at +100 vs pure TP+100")
    print("=" * 90)
    df = df.copy()
    # Pure TP+100/Stop-30
    df["pol_tp100"] = df.apply(
        lambda r: 100.0 if r["mfe_pct"] >= 100 else (
            -30.0 if r["eod_pct"] <= -30 else r["eod_pct"]),
        axis=1)
    # Partial: 50% size at +50, 50% size at +100 (or stop -30 if neither)
    def partial(r):
        # half exits at +50 if MFE >= 50, else stops with rest
        # other half exits at +100 if MFE >= 100, else stops or EOD
        # Stop -30% applies to both halves
        if r["eod_pct"] <= -30 and r["mfe_pct"] < 50:
            return -30.0
        # Half 1: exits at +50 if hit, else stop -30 if hit, else EOD
        if r["mfe_pct"] >= 50:
            half1 = 50.0
        elif r["eod_pct"] <= -30:
            half1 = -30.0
        else:
            half1 = r["eod_pct"]
        # Half 2: exits at +100 if hit, else stop -30 if hit, else EOD
        if r["mfe_pct"] >= 100:
            half2 = 100.0
        elif r["eod_pct"] <= -30:
            half2 = -30.0
        else:
            half2 = r["eod_pct"]
        return (half1 + half2) / 2
    df["pol_partial"] = df.apply(partial, axis=1)
    # Trail: take +50 partial, runner with breakeven stop after
    def trail_breakeven(r):
        if r["mfe_pct"] >= 50:
            half1 = 50.0
            # Half 2: breakeven stop after +50; if MFE went higher, exit at peak
            half2 = max(0.0, r["mfe_pct"] - 20)  # give 20% pullback off peak
        elif r["eod_pct"] <= -30:
            return -30.0
        else:
            return r["eod_pct"]
        return (half1 + half2) / 2
    df["pol_trail"] = df.apply(trail_breakeven, axis=1)

    print(f"{'setup':<22} {'n':<5} {'pure_TP100':<12} "
          f"{'partial_50/100':<16} {'trail_BE':<12}")
    print("-" * 80)
    for setup in top_setups:
        sub = df[df["setup"] == setup]
        if len(sub) == 0:
            continue
        print(f"{setup:<22} {len(sub):<5} "
              f"{sub['pol_tp100'].mean():>+6.1f}%      "
              f"{sub['pol_partial'].mean():>+6.1f}%          "
              f"{sub['pol_trail'].mean():>+6.1f}%")


def main() -> int:
    df = load_data()
    print(f"Loaded {len(df)} trades, {df['setup'].nunique()} setups, "
          f"{df['day'].nunique()} days")

    slippage_table(df)
    walk_forward_split(df)
    signal_collision_dedup(df)

    top5 = ["vwap_lose", "sweep_pmh", "pml_break", "pmh_break", "orb15_break"]
    mfe_distribution(df, top5)
    day_of_week_filter(df)
    partial_exit_policy(df, top5 + ["orb30_break", "orb5_break", "ema_cross_imm"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
