"""ZBT / Whaley validation against our NYMO backfill data.

Phase 6A.0a — fastest validation step. Confirms that our yfinance-based
NYMO backfill (1,838 days, 5x scaled) actually captures the well-known
breadth thrust events Perplexity cited. If the Apr 24-25 2025 ZBT is
visible in our data, the backfill is structurally sound. If not, the
data quality is too low for further breadth-based work.

Tests:
  Z1. Compute ZBT from breadth_daily (NYSE A/D ratio, 10-day EMA crossing
      40% → 61.5% within 10 days)
  Z2. Compute Whaley (5-day adv > 2x dec AND adv vol > 2x dec vol — but
      we only have adv/dec counts, not volumes, so use simpler 5d ratio)
  Z3. Check both against historical fires Perplexity listed:
      - Jan 2019  (post-Dec 2018)
      - Oct 2020  (mid-pullback)
      - Nov 2020  (ZBT coincident)
      - Mar 2021
      - Oct 2022  (near-miss ZBT)
      - Nov 2023  (ZBT coincident)
      - Apr 24-25 2025 (CONFIRMED REAL ZBT — primary validation target)

Run:
    python -m backtest.zbt_validation
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from server.config import get_settings


# Per Perplexity Apr 26 evening follow-up:
EXPECTED_FIRES = [
    ("2019-01-04", "2019-01-31", "Jan 2019 post-Dec 2018 selloff", "near-miss ZBT"),
    ("2020-10-09", "2020-10-23", "Oct 2020 mid-pullback recovery", "WBT only"),
    ("2020-11-04", "2020-11-30", "Nov 2020 post-election rally", "ZBT coincident"),
    ("2021-03-08", "2021-03-31", "Mar 2021 continuation", "WBT only"),
    ("2022-10-13", "2022-10-31", "Oct 2022 late-year recovery", "near-miss ZBT"),
    ("2023-10-30", "2023-11-30", "Nov 2023 post-Oct correction", "ZBT coincident"),
    ("2025-04-09", "2025-04-30", "Apr 2025 post-tariff-shock recovery", "ZBT confirmed Apr 24-25"),
]


def load_breadth() -> pd.DataFrame:
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    rows = c.execute(
        "SELECT date, advancers, decliners, unchanged, net_advances "
        "FROM breadth_daily WHERE exchange = 'NYSE' ORDER BY date ASC"
    ).fetchall()
    c.close()
    df = pd.DataFrame(rows, columns=["date", "adv", "dec", "unch", "net"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df["total"] = df["adv"] + df["dec"] + df["unch"]
    df["ad_ratio"] = df["adv"] / (df["adv"] + df["dec"])  # for ZBT
    df["adv_dec_ratio"] = df["adv"] / df["dec"].replace(0, np.nan)  # for WBT
    return df


def compute_zbt(df: pd.DataFrame) -> pd.DataFrame:
    """ZBT: 10-day EMA of A/(A+D) crossing 40% to 61.5% within 10 trading days."""
    out = df.copy()
    out["ad_ratio_ema10"] = out["ad_ratio"].ewm(span=10, adjust=False).mean()
    # Find days where ema crossed below 0.40 in the last 10 days, then today >= 0.615
    out["below_40_10d_ago"] = out["ad_ratio_ema10"].rolling(10).min() < 0.40
    out["above_615_today"] = out["ad_ratio_ema10"] >= 0.615
    out["zbt_fire"] = out["below_40_10d_ago"] & out["above_615_today"]
    # Filter to first fire in any 30-day window (no double-counting)
    out["zbt_fire_clean"] = False
    last_fire = pd.Timestamp("1900-01-01")
    for date, row in out.iterrows():
        if row["zbt_fire"] and (date - last_fire).days >= 30:
            out.at[date, "zbt_fire_clean"] = True
            last_fire = date
    return out


def compute_whaley(df: pd.DataFrame) -> pd.DataFrame:
    """Whaley 2:1: 5-day cum advancing > 2x cum declining."""
    out = df.copy()
    out["adv_5d"] = out["adv"].rolling(5).sum()
    out["dec_5d"] = out["dec"].rolling(5).sum()
    out["wbt_ratio_5d"] = out["adv_5d"] / out["dec_5d"].replace(0, np.nan)
    out["wbt_fire"] = out["wbt_ratio_5d"] >= 1.97  # Whaley's threshold
    # Dedupe to monthly
    out["wbt_fire_clean"] = False
    last_fire = pd.Timestamp("1900-01-01")
    for date, row in out.iterrows():
        if row["wbt_fire"] and (date - last_fire).days >= 30:
            out.at[date, "wbt_fire_clean"] = True
            last_fire = date
    return out


def check_fires_in_window(fires: pd.DataFrame, fire_col: str,
                          win_start: str, win_end: str) -> list:
    """Return dates where fire_col=True in [win_start, win_end]."""
    sub = fires[(fires.index >= pd.Timestamp(win_start))
                & (fires.index <= pd.Timestamp(win_end))]
    return [d.date().isoformat() for d in sub[sub[fire_col]].index]


def main() -> int:
    print("ZBT / Whaley Breadth Thrust validation against NYMO backfill\n")
    df = load_breadth()
    print(f"Breadth data: {len(df)} days, {df.index[0].date()} to {df.index[-1].date()}")
    print(f"  ad_ratio range: {df['ad_ratio'].min():.3f} to {df['ad_ratio'].max():.3f}")
    print(f"  ad_ratio mean:  {df['ad_ratio'].mean():.3f}\n")

    zbt = compute_zbt(df)
    wbt = compute_whaley(df)

    print(f"All ZBT fires across {len(df)} days:")
    zbt_fires = zbt[zbt["zbt_fire_clean"]].index.date.tolist()
    if not zbt_fires:
        print("  NONE — ZBT may need looser threshold OR data issue")
    else:
        for d in zbt_fires:
            print(f"  {d}")

    print(f"\nAll Whaley (>1.97) fires across {len(df)} days:")
    wbt_fires = wbt[wbt["wbt_fire_clean"]].index.date.tolist()
    if not wbt_fires:
        print("  NONE — WBT may need looser threshold OR data issue")
    else:
        for d in wbt_fires[:30]:  # cap display
            print(f"  {d}")
        if len(wbt_fires) > 30:
            print(f"  ... and {len(wbt_fires)-30} more")

    # Check vs Perplexity's expected events
    print("\n" + "=" * 78)
    print("Validation against Perplexity-cited historical events:")
    print("=" * 78)
    print(f"  {'Window':<35}  {'Expected':<22}  ZBT in window  WBT in window")
    print(f"  {'-'*35}  {'-'*22}  {'-'*15}  {'-'*15}")

    pass_count = 0
    primary_pass = False  # Apr 2025 specifically
    for win_start, win_end, label, expected in EXPECTED_FIRES:
        zbt_hits = check_fires_in_window(zbt, "zbt_fire_clean", win_start, win_end)
        wbt_hits = check_fires_in_window(wbt, "wbt_fire_clean", win_start, win_end)
        zbt_str = ",".join(zbt_hits) if zbt_hits else "—"
        wbt_str = ",".join(wbt_hits) if wbt_hits else "—"
        is_apr_2025 = "Apr 2025" in label
        marker = " *" if is_apr_2025 else ""
        print(f"  {label:<35}{marker}  {expected:<22}  {zbt_str:<15}  {wbt_str}")
        if zbt_hits or wbt_hits:
            pass_count += 1
        if is_apr_2025 and (zbt_hits or wbt_hits):
            primary_pass = True

    print(f"\nValidation summary:")
    print(f"  Events with at least one signal fire: {pass_count}/{len(EXPECTED_FIRES)}")
    print(f"  Apr 2025 ZBT (primary validation):    {'PASS' if primary_pass else 'FAIL'}")

    if primary_pass:
        print("\n  → Backfill data is structurally sound. Whaley/ZBT signals visible.")
        print("  → Safe to proceed with WBT integration into macro_pivot detector.")
    else:
        print("\n  → Apr 2025 ZBT not detected — possible data quality issue.")
        print("  → Investigate before building on this data.")
        print("  → Possible causes: 288-name universe too narrow; 5x scaling off;")
        print("     ad_ratio computation needs refinement.")

    # Diagnostic: what was the actual ad_ratio_ema10 around Apr 24-25 2025?
    print(f"\n--- Diagnostic: ad_ratio_ema10 values around Apr 24-25 2025 ---")
    apr_window = zbt.loc["2025-04-15":"2025-05-02"]
    if not apr_window.empty:
        print(f"  {'Date':<12} {'adv':>5} {'dec':>5} {'A/(A+D)':>8} {'EMA10':>8} {'Below40 10d ago':>16} {'>=61.5 today':>13}")
        for date, row in apr_window.iterrows():
            print(f"  {date.date()}   {int(row['adv']):>5} {int(row['dec']):>5} "
                  f"{row['ad_ratio']:>7.3f}  {row['ad_ratio_ema10']:>7.3f}  "
                  f"{str(bool(row['below_40_10d_ago'])):>16}  {str(bool(row['above_615_today'])):>13}")

    return 0 if primary_pass else 1


if __name__ == "__main__":
    sys.exit(main())
