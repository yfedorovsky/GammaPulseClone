"""Confluence backtest — Grok's suggestion.

Tests whether adding a single confluence filter to top setups improves
expected value. Reads from existing unified_setup_backtest.db (so no
ThetaData re-pull needed).

Confluences tested:
  - PMH break + above VWAP filter
  - PML break + below VWAP filter
  - ORB15 break + EMA8>EMA20 alignment
  - ORB30 break + EMA8>EMA20 alignment
  - VWAP lose + below 9 EMA filter
  - sweep_pmh + above VWAP filter
  - sweep_pml + below VWAP filter

To do this without re-running ThetaData, we re-derive whether each existing
trade had the confluence filter active by re-computing 5-min bar state at
the cross_hhmm.

Compares filtered vs unfiltered on TP+50/Stop-30 and TP+100/Stop-30.
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

from scripts.unified_setup_backtest import bars_5min_with_indicators

DB = "unified_setup_backtest.db"


def load_trades_for_setup(setup_name: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT * FROM unified_trades WHERE setup = ?",
        conn, params=(setup_name,))
    conn.close()
    return df


def add_confluence_flags(df: pd.DataFrame) -> pd.DataFrame:
    """For each trade, look up SPY 5-min state at cross_hhmm and add
    confluence flags."""
    df = df.copy()
    flags = {
        "above_vwap": [],
        "below_vwap": [],
        "ema8_above_ema20": [],
        "ema8_below_ema20": [],
        "vwap_slope_pos": [],
    }
    for _, r in df.iterrows():
        b5 = bars_5min_with_indicators(r["day"])
        if b5.empty:
            for k in flags: flags[k].append(False)
            continue
        bar = b5[b5["hhmm"] == r["cross_hhmm"]]
        if bar.empty:
            for k in flags: flags[k].append(False)
            continue
        bar = bar.iloc[0]
        flags["above_vwap"].append(bool(bar["close"] > bar["vwap"]))
        flags["below_vwap"].append(bool(bar["close"] < bar["vwap"]))
        flags["ema8_above_ema20"].append(bool(bar["ema8"] > bar["ema20"]))
        flags["ema8_below_ema20"].append(bool(bar["ema8"] < bar["ema20"]))
        flags["vwap_slope_pos"].append(bool(bar["vwap_slope"] > 0))
    for k, v in flags.items():
        df[k] = v
    return df


def report_confluence(setup: str, df: pd.DataFrame, filter_col: str,
                      filter_label: str) -> None:
    if df.empty:
        return
    total = len(df)
    yes = df[df[filter_col]]
    no = df[~df[filter_col]]
    yes_n = len(yes)
    no_n = len(no)

    def s(sub, pol):
        if len(sub) == 0:
            return None, None
        m = sub[pol].mean()
        return m, len(sub)

    y50, _ = s(yes, "pol_tp50_s30")
    y100, _ = s(yes, "pol_tp100_s30")
    n50, _ = s(no, "pol_tp50_s30")
    n100, _ = s(no, "pol_tp100_s30")

    base50 = df["pol_tp50_s30"].mean()
    base100 = df["pol_tp100_s30"].mean()

    print(f"  {filter_label:<35} "
          f"unfilter={base50:+.1f}/{base100:+.1f}%  "
          f"WITH={y50:+.1f}/{y100:+.1f}% (n={yes_n})  "
          f"WITHOUT={n50:+.1f}/{n100:+.1f}% (n={no_n})  "
          f"delta={y100 - n100:+.1f}pp" if y100 is not None and n100 is not None else "")


def main() -> int:
    print("=" * 110)
    print("CONFLUENCE BACKTEST — does adding a single filter improve top setups?")
    print("(format: TP+50/Stop-30 mean / TP+100/Stop-30 mean per cell)")
    print("=" * 110)

    test_cases = [
        ("pmh_break", "above_vwap", "above VWAP"),
        ("pmh_break", "ema8_above_ema20", "9>21 EMA"),
        ("pmh_break", "vwap_slope_pos", "VWAP slope rising"),
        ("pml_break", "below_vwap", "below VWAP"),
        ("pml_break", "ema8_below_ema20", "9<21 EMA"),
        ("orb15_break", "above_vwap", "above VWAP (bull only)"),
        ("orb15_break", "ema8_above_ema20", "9>21 EMA"),
        ("orb30_break", "above_vwap", "above VWAP (bull only)"),
        ("orb30_break", "ema8_above_ema20", "9>21 EMA"),
        ("vwap_lose", "below_vwap", "below VWAP at fire"),
        ("sweep_pmh", "above_vwap", "above VWAP"),
        ("sweep_pml", "below_vwap", "below VWAP"),
        ("ema_cross_imm", "vwap_slope_pos", "VWAP slope rising"),
    ]

    cache: dict[str, pd.DataFrame] = {}
    for setup, filt, label in test_cases:
        if setup not in cache:
            df = load_trades_for_setup(setup)
            df = add_confluence_flags(df)
            cache[setup] = df
        df = cache[setup]
        # For directional setups, only apply the filter to that direction
        # (e.g., pmh_break is always BULL, pml_break is always BEAR; orb has both)
        if "below_vwap" in filt and df["direction"].iloc[0] == "BULL":
            print(f"  SKIP {setup} + {label}: filter direction mismatch")
            continue
        if "above_vwap" in filt and (df["direction"] == "BEAR").all():
            print(f"  SKIP {setup} + {label}: filter direction mismatch")
            continue
        # For ORB which has both directions, only filter the BULL leg with above_vwap
        if setup.startswith("orb") and filt in ("above_vwap", "ema8_above_ema20"):
            sub = df[df["direction"] == "BULL"]
            print(f"\n{setup} (BULL leg only, n={len(sub)}):")
            report_confluence(setup, sub, filt, label)
            continue
        print(f"\n{setup} (n={len(df)}):")
        report_confluence(setup, df, filt, label)

    print()
    print("=" * 110)
    print("Save trades with confluence flags for future analysis...")
    # Write out for downstream analysis
    all_with_flags = pd.concat(list(cache.values()))
    all_with_flags.to_csv(
        "docs/research/unified_with_confluence_flags.csv", index=False)
    print(f"  Saved {len(all_with_flags)} rows to docs/research/unified_with_confluence_flags.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
