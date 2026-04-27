"""Historical gate-replay attribution for Phase 1 + Phase 2 rules.

Replays the 7-gate cascade against the 16-month cohort dataset and
measures, for each gate, what would have been blocked and what the
forward returns of those would-be-blocked positions actually were.

Gates evaluated:
  G1  Phase 1 #1 — Breadth gate (BEAR -> all blocked, TRANSITIONAL -> B/B+ blocked)
  G2  Phase 2 #2 — IV-rank gate (BEAR/TRANS + iv_rank > 0.66 -> blocked)
  G3  Phase 2 #3 — Zone-A bonus (1.2x size; for measurement, just count Zone-A bars)
  G4  Phase 2 #4 — Sector cap (skipped — needs concurrent-position simulation)
  G5  Phase 2 #5 — Conditional time stop (close at day 21 if not running)

What we measure per gate:
  - n_signals: number of historical bars where the gate had a chance to fire
  - n_blocked: number actually blocked
  - blocked_hit_rate_21d: hit rate of the BLOCKED bars (would have been a loss?)
  - blocked_avg_21d: avg return of blocked bars
  - passed_hit_rate_21d / passed_avg_21d: same for non-blocked
  - delta_avg_21d: passed - blocked  (positive = gate added edge)

Datasets used:
  data/zone_iv_validation_full.csv  — 3,726 bars across 19 names, 16 months
                                       (already has zone, iv_rank, fwd_5/10/21d)

For the breadth gate we need historical SPY %above-200d-MA, which we
compute from yfinance on the cohort universe (used as a proxy — the
real production breadth gate runs on the full 400-ticker universe but
the directional signal will be similar).

Run:
    python -m backtest.gate_replay_attribution
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

DATA = Path(__file__).resolve().parent.parent / "data" / "zone_iv_validation_full.csv"
COHORT = [
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "RES", "CAMT", "TROX",
    "LAR", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
    "AAOI", "CIEN", "GLW", "MU",
]
BIOTECH_EXCLUDED = {"ANAB", "CAPR", "GHRS"}


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")
    df.index.name = "date"
    df = df.dropna(subset=["atm_iv", "iv_rank"])
    return df


def compute_historical_breadth(start: str, end: str) -> pd.DataFrame:
    """Daily % of cohort above 200d MA — proxy for regime gate."""
    rows = []
    cache = {}
    for t in COHORT:
        try:
            df = yf.download(t, start=start, end=end, progress=False,
                             auto_adjust=True, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df["sma200"] = df["Close"].rolling(200).mean()
            df["above"] = (df["Close"] > df["sma200"]).astype(int)
            cache[t] = df["above"]
        except Exception:
            continue
    big = pd.DataFrame(cache).dropna(how="all")
    big["pct_above"] = big.sum(axis=1) / big.notna().sum(axis=1) * 100
    big["regime"] = pd.cut(
        big["pct_above"], bins=[-1, 40, 60, 101],
        labels=["BEAR", "TRANSITIONAL", "FULL_BULL"],
    )
    return big[["pct_above", "regime"]]


def fmt_block(label: str, df: pd.DataFrame, mask: pd.Series, horizons=(5, 10, 21)) -> None:
    blocked = df[mask]
    passed = df[~mask]
    print(f"\n  {label}")
    print(f"    n_blocked: {len(blocked):>5}   n_passed: {len(passed):>5}   "
          f"block_pct: {100*len(blocked)/len(df):.1f}%")
    for h in horizons:
        col = f"fwd_{h}d"
        bh = blocked[col].dropna()
        ph = passed[col].dropna()
        if bh.empty or ph.empty:
            continue
        b_hit = (bh > 0).mean() * 100
        b_avg = bh.mean() * 100
        p_hit = (ph > 0).mean() * 100
        p_avg = ph.mean() * 100
        delta = p_avg - b_avg
        delta_hit = p_hit - b_hit
        print(f"    {h:>2}d:  blocked hit={b_hit:5.1f}% avg={b_avg:+6.2f}%   "
              f"passed hit={p_hit:5.1f}% avg={p_avg:+6.2f}%   "
              f"delta avg={delta:+5.2f}pp  delta hit={delta_hit:+5.1f}pp")


def main() -> int:
    df = load_data()
    print(f"Loaded {len(df):,} cohort bars")

    # Compute historical breadth from cohort-as-proxy
    start_str = df.index.min().date().isoformat()
    end_str = (df.index.max().date() + pd.Timedelta(days=2)).isoformat()
    print(f"Computing breadth proxy from {start_str} to {end_str}...")
    breadth = compute_historical_breadth(start_str, end_str)

    # Join breadth onto df by date (may have multiple ticker rows per date)
    df = df.join(breadth, how="left")
    df = df.dropna(subset=["regime"])
    print(f"After breadth join: {len(df):,} bars\n")
    print("Regime distribution:")
    print(df["regime"].value_counts().to_string())
    print()

    # Restrict to BULL-direction-equivalent: in-uptrend bars only
    # (the gates are designed for BULL longs; BEAR signals are outside scope)
    df = df.dropna(subset=["fwd_5d", "fwd_10d", "fwd_21d"])

    print("\n" + "=" * 78)
    print("GATE 1 — Phase 1 #1 — Breadth gate (BEAR all-block + TRANSITIONAL B+/B-block)")
    print("=" * 78)
    # We don't have grade in this dataset (it's a daily bar dataset, not a
    # signal dataset). Approximate "would have been blocked" as:
    # BEAR regime → 100% blocked
    # TRANSITIONAL regime → roughly 60% blocked (A+/A pass, B+/B blocked).
    #   Use random sampling proxy at 60% for the count, but show pure
    #   regime-level results (BEAR vs not).
    bear_block = df["regime"] == "BEAR"
    fmt_block("BEAR-only block (skip all longs in BEAR regime):", df, bear_block)

    print("\n" + "=" * 78)
    print("GATE 2 — Phase 2 #2 — IV-rank regime gate (block HIGH-IV in BEAR/TRANS)")
    print("=" * 78)
    # Block: regime in (BEAR, TRANSITIONAL) AND iv_rank > 0.66 AND not biotech
    not_biotech = ~df["ticker"].isin(BIOTECH_EXCLUDED)
    iv_block = (
        (df["regime"].isin(["BEAR", "TRANSITIONAL"]))
        & (df["iv_rank"] > 0.66)
        & not_biotech
    )
    fmt_block("Block HIGH-IV in BEAR/TRANS (cohort, non-biotech):", df, iv_block)

    print("\n  Per-regime breakdown:")
    for r in ["BEAR", "TRANSITIONAL", "FULL_BULL"]:
        sub = df[df["regime"] == r]
        if sub.empty:
            continue
        m = (sub["iv_rank"] > 0.66) & ~sub["ticker"].isin(BIOTECH_EXCLUDED)
        fmt_block(f"   regime={r}", sub, m, horizons=(21,))

    print("\n" + "=" * 78)
    print("GATE 3 — Phase 2 #3 — Zone-A bonus (count: how many Zone-A bars existed?)")
    print("=" * 78)
    # This isn't a block — it's a size multiplier. Measure Zone-A vs other forward returns.
    zone_a_mask = df["zone"] == "A"
    zone_b_mask = df["zone"] == "B"
    other_mask = df["zone"] == "Other"
    print(f"\n  Bar counts: Zone-A {zone_a_mask.sum()}, Zone-B {zone_b_mask.sum()}, "
          f"Other {other_mask.sum()}")
    for h in (5, 10, 21):
        col = f"fwd_{h}d"
        a = df.loc[zone_a_mask, col].dropna()
        b = df.loc[zone_b_mask, col].dropna()
        o = df.loc[other_mask, col].dropna()
        if a.empty:
            continue
        print(f"    {h:>2}d:  Zone-A hit={100*(a>0).mean():5.1f}% avg={a.mean()*100:+6.2f}%   "
              f"Zone-B hit={100*(b>0).mean():5.1f}% avg={b.mean()*100:+6.2f}%   "
              f"Other hit={100*(o>0).mean():5.1f}% avg={o.mean()*100:+6.2f}%")

    print("\n" + "=" * 78)
    print("GATE 4 — Combined Phase 1+2 — what % of would-be entries do gates block in each regime?")
    print("=" * 78)
    for r in ["BEAR", "TRANSITIONAL", "FULL_BULL"]:
        sub = df[df["regime"] == r]
        if sub.empty:
            continue
        breadth_block = (r == "BEAR")
        iv_block_in_r = ((r in ("BEAR", "TRANSITIONAL"))
                         & (sub["iv_rank"] > 0.66)
                         & (~sub["ticker"].isin(BIOTECH_EXCLUDED)))
        any_block = breadth_block or iv_block_in_r
        if r == "BEAR":
            mask = pd.Series(True, index=sub.index)  # all blocked by breadth
        else:
            mask = iv_block_in_r
        n_blocked = mask.sum()
        pct_blocked = 100 * n_blocked / len(sub)
        print(f"\n  {r} (n={len(sub):>5}): "
              f"{n_blocked} bars blocked ({pct_blocked:.1f}%)")
        if n_blocked > 0:
            fmt_block(f"   blocked vs passed within {r}", sub, mask, horizons=(21,))

    print("\n" + "=" * 78)
    print("GATE 5 — Conditional time stop (close losers at day 21)")
    print("=" * 78)
    # Approximate: bars where fwd_21d <= 0 are "losers" that would close at day 21.
    # Bars where fwd_21d > +0.5 (50% return = +1R proxy on equity-equivalent at
    # 5x options leverage) and fwd_5d > 0 (winning early) might extend.
    losers_at_21 = df["fwd_21d"] <= 0
    print(f"\n  Bars where 21d return <= 0%: {losers_at_21.sum()} / {len(df)} "
          f"({100*losers_at_21.mean():.1f}%)")
    # The time stop captures these; without it, some would have continued lower.
    # Crude proxy: assume avg additional decline = -2% (since these were already losing).
    # Real value of the rule is reducing exposure to chop, not preventing the catastrophic case
    # which is already handled by stop-loss.
    print("  (Time-stop value is reduced exposure to chop, not catastrophe — "
          "which is handled by spot stop. Hard to measure without simulator.)")

    df.to_csv("data/gate_replay_results.csv")
    print(f"\nWrote {len(df)} attribution rows to data/gate_replay_results.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
