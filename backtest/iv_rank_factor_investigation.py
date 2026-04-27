"""IV-Rank as an independent factor — deeper investigation.

The Apr 26 full-validation surfaced an unexpected pattern: low-IV-rank days
have +11pp better hit rate at 21d than high-IV-rank days, while high-IV days
have larger average returns (right-tail expansion). The question now is:

  - Is the LOW-IV hit-rate edge robust, or is it a regime artifact (LOW-IV
    periods correlate with bull tapes where everything works)?
  - Does the HIGH-IV right tail survive options vega decay (theoretical
    long-call PnL net of IV mean reversion)?
  - Is the pattern stable across tickers, or driven by a few outliers?
  - Does it interact with our existing zone classification?
  - Is it stable over time (H1 2025 vs late 2025 vs Q1 2026)?

Tests run:
  T1: Per-ticker IV-rank-tertile pattern stability
  T2: SPY-regime conditioned analysis (above/below 200d MA)
  T3: Zone × IV-tertile cross-tab
  T4: Net-of-vega forward return (theoretical ATM call PnL)
  T5: Time-period split (Jan-Jul 2025 vs Aug 2025-Apr 2026)
  T6: ATR% conditioning (does IV-rank just proxy realized vol regime?)

Run:
    python -m backtest.iv_rank_factor_investigation
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "zone_iv_validation_full.csv"
FWD_HORIZONS = [5, 10, 21]


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["Date"], index_col="Date")
    df.index.name = "date"
    df = df.dropna(subset=["atm_iv", "iv_rank"])
    df["iv_tertile"] = pd.qcut(df["iv_rank"], 3, labels=["LOW", "MID", "HIGH"])
    return df


def add_spy_regime(df: pd.DataFrame) -> pd.DataFrame:
    spy = yf.download("SPY", start="2024-06-01", end="2026-05-01",
                       progress=False, auto_adjust=True, threads=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy.index = pd.to_datetime(spy.index).tz_localize(None)
    spy["sma200"] = spy["Close"].rolling(200).mean()
    spy["regime"] = np.where(spy["Close"] > spy["sma200"], "SPY_BULL", "SPY_BEAR")
    out = df.join(spy["regime"].rename("spy_regime"), how="left")
    return out


def hit_avg(s: pd.Series) -> tuple[int, float, float, float]:
    s = s.dropna()
    if s.empty:
        return 0, np.nan, np.nan, np.nan
    return len(s), (s > 0).mean() * 100, s.mean() * 100, s.median() * 100


def t1_per_ticker(df: pd.DataFrame) -> None:
    print("=" * 70)
    print("T1: Per-ticker IV-tertile 21d hit-rate pattern (LOW vs HIGH delta)")
    print("=" * 70)
    rows = []
    for ticker, sub in df.groupby("ticker"):
        sub = sub.dropna(subset=["fwd_21d"])
        if len(sub) < 60:
            continue
        # Re-tertile within this ticker (fair per-ticker comparison)
        sub = sub.copy()
        sub["iv_tertile_local"] = pd.qcut(sub["iv_rank"], 3,
                                           labels=["LOW", "MID", "HIGH"],
                                           duplicates="drop")
        low = sub[sub["iv_tertile_local"] == "LOW"]["fwd_21d"]
        high = sub[sub["iv_tertile_local"] == "HIGH"]["fwd_21d"]
        if len(low) < 10 or len(high) < 10:
            continue
        rows.append({
            "ticker": ticker,
            "n": len(sub),
            "low_n": len(low),
            "high_n": len(high),
            "low_hit_21d": (low > 0).mean() * 100,
            "high_hit_21d": (high > 0).mean() * 100,
            "delta_hit_21d": (low > 0).mean() * 100 - (high > 0).mean() * 100,
            "low_avg_21d": low.mean() * 100,
            "high_avg_21d": high.mean() * 100,
        })
    pt = pd.DataFrame(rows).sort_values("delta_hit_21d", ascending=False)
    with pd.option_context("display.max_rows", None, "display.width", 130,
                           "display.float_format", "{:.2f}".format):
        print(pt.to_string(index=False))
    print(f"\n  Tickers where LOW-IV beats HIGH-IV on 21d hit rate: "
          f"{(pt['delta_hit_21d'] > 0).sum()} / {len(pt)}")
    print(f"  Average delta_hit_21d: {pt['delta_hit_21d'].mean():+.1f}pp")
    print(f"  Median delta_hit_21d:  {pt['delta_hit_21d'].median():+.1f}pp")


def t2_spy_regime(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("T2: IV-tertile pattern conditioned on SPY regime (above/below 200d)")
    print("=" * 70)
    for regime in ["SPY_BULL", "SPY_BEAR"]:
        sub = df[df["spy_regime"] == regime]
        if sub.empty:
            print(f"\n  {regime}: no rows")
            continue
        print(f"\n  --- {regime} (n={len(sub)}) ---")
        for h in [5, 10, 21]:
            print(f"    {h}d:")
            for t in ["LOW", "MID", "HIGH"]:
                s = sub[sub["iv_tertile"] == t][f"fwd_{h}d"].dropna()
                if s.empty:
                    continue
                hit = (s > 0).mean() * 100
                print(f"      {t:<4} n={len(s):>4} hit={hit:5.1f}% "
                      f"avg={s.mean()*100:+5.2f}%")


def t3_zone_x_iv(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("T3: Zone x IV-tertile cross-tab (21d forward returns)")
    print("=" * 70)
    for zone in ["A", "B", "Other"]:
        print(f"\n  Zone {zone}:")
        for t in ["LOW", "MID", "HIGH"]:
            s = df[(df["zone"] == zone) & (df["iv_tertile"] == t)]["fwd_21d"].dropna()
            if s.empty:
                print(f"    IV {t:<4} n=0")
                continue
            hit = (s > 0).mean() * 100
            print(f"    IV {t:<4} n={len(s):>5}  hit={hit:5.1f}%  "
                  f"avg={s.mean()*100:+6.2f}%  med={s.median()*100:+6.2f}%")


def t4_vega_adjusted(df: pd.DataFrame) -> None:
    """Approximate options PnL net of vega decay.

    For an ATM call at IV0:
        new IV after 21d ~= IV0 + 0.4 * (median_IV - IV0)   (mean reversion ~40%)
        delta_iv = new_iv - iv0
        vega_pnl_pct ~= (vega / option_price) * delta_iv * 100  ~= 100 * delta_iv / iv0
                                                                  for ATM ~= 1 vol point ≈ 1%
        delta_pnl_pct ~= delta * fwd_return * (spot/option_price) ~= ~5x leverage
                       Approximation: 5 * fwd_return - vega_pnl_pct

    This is a crude approximation but captures the *direction* of vega decay's
    impact on long-call PnL. Useful for ranking, not for absolute claims.
    """
    print("\n" + "=" * 70)
    print("T4: Approximate vega-adjusted long-call PnL (21d ATM hold)")
    print("=" * 70)
    print("  Formula: approx_call_pnl = 5 * fwd_21d - vega_decay_pct")
    print("  where vega_decay_pct ~= 40 * (median_iv - atm_iv)/atm_iv  (mean rev)")
    print("  This is APPROXIMATE — captures direction not magnitude.\n")

    median_iv = df["atm_iv"].median()
    df = df.copy()
    df["vega_decay_pct"] = 40 * (median_iv - df["atm_iv"]) / df["atm_iv"]
    df["approx_call_pnl_21d"] = 5 * df["fwd_21d"] * 100 - df["vega_decay_pct"]

    for t in ["LOW", "MID", "HIGH"]:
        s = df[df["iv_tertile"] == t]["approx_call_pnl_21d"].dropna()
        if s.empty:
            continue
        hit = (s > 0).mean() * 100
        print(f"  IV {t:<4} n={len(s):>5}  approx call PnL: "
              f"hit={hit:5.1f}%  avg={s.mean():+7.2f}%  "
              f"med={s.median():+7.2f}%")


def t5_time_split(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("T5: Time stability — H1 2025 vs H2 2025-Q1 2026")
    print("=" * 70)
    midpoint = pd.Timestamp("2025-08-01")
    for label, mask in [
        ("BEFORE 2025-08-01", df.index < midpoint),
        ("ON/AFTER 2025-08-01", df.index >= midpoint),
    ]:
        sub = df[mask]
        if sub.empty:
            continue
        print(f"\n  --- {label} (n={len(sub)}) ---")
        for t in ["LOW", "MID", "HIGH"]:
            s = sub[sub["iv_tertile"] == t]["fwd_21d"].dropna()
            if s.empty:
                continue
            hit = (s > 0).mean() * 100
            print(f"    IV {t:<4} n={len(s):>5}  hit={hit:5.1f}%  "
                  f"avg={s.mean()*100:+6.2f}%")


def t6_atr_conditioning(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("T6: Does IV-rank just proxy realized-vol regime?")
    print("=" * 70)
    print("  Cross-tab IV-tertile (real) vs RV-rank-tertile (proxy)")
    print()
    df = df.copy()
    df["rv_tertile"] = pd.qcut(df["rv_rank"], 3,
                                labels=["LOW", "MID", "HIGH"],
                                duplicates="drop")
    ct = pd.crosstab(df["iv_tertile"], df["rv_tertile"], normalize="index") * 100
    print(ct.round(1).to_string())
    print("\n  If IV and RV tertiles were identical, diagonal would be 100/100/100.")
    print("  Read off-diagonals as: 'how often IV says LOW when RV says HIGH'")

    # 21d hit by joint cell
    print("\n  21d hit rate by (IV-tertile, RV-tertile) cell:")
    rows = []
    for iv_t in ["LOW", "MID", "HIGH"]:
        for rv_t in ["LOW", "MID", "HIGH"]:
            s = df[(df["iv_tertile"] == iv_t)
                   & (df["rv_tertile"] == rv_t)]["fwd_21d"].dropna()
            if len(s) < 20:
                continue
            rows.append({
                "iv_tertile": iv_t, "rv_tertile": rv_t,
                "n": len(s), "hit_21d": round((s > 0).mean() * 100, 1),
                "avg_21d": round(s.mean() * 100, 2),
            })
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> int:
    df = load()
    print(f"Loaded {len(df):,} rows across {df['ticker'].nunique()} tickers\n")
    df = add_spy_regime(df)

    t1_per_ticker(df)
    t2_spy_regime(df)
    t3_zone_x_iv(df)
    t4_vega_adjusted(df)
    t5_time_split(df)
    t6_atr_conditioning(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
