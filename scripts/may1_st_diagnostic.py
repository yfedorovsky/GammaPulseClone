"""Deep diagnostic on why ZERO structural-turn fires occurred on May 1.

Re-computes the volume_absorption gate per minute using Databento's
trade-level data (high precision) instead of yfinance bars. Also checks
the regime_match gate's behavior on SPY (only 9% pass) and the
structural_event gate's behavior on IWM (0% pass).

Outputs a forensic report to stdout.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import load_window  # noqa: E402

DAY = "2026-05-01"
DAY_T0 = int(datetime(2026, 5, 1, 9, 30).timestamp())
DAY_T1 = int(datetime(2026, 5, 1, 16, 0).timestamp())


def session_minute_bars(ticker: str, day: str) -> pd.DataFrame:
    """Aggregate Databento trades to per-minute OHLCV bars."""
    df = load_window(ticker, day, start_hhmm="09:30", end_hhmm="16:00",
                     actions=["T"])
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["ts_event"], utc=True) \
              .dt.tz_convert("America/New_York")
    df["minute"] = df["t"].dt.floor("min")
    g = df.groupby("minute").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
        n_trades=("price", "count"),
    ).reset_index()
    g["hhmm"] = g["minute"].dt.strftime("%H:%M")
    return g


def vol_absorption_per_minute(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute the gate's two key metrics per minute:
       - vol_ratio = bar.volume / 20-min trailing avg volume
       - dist_from_lod_pct = abs(bar.low - session_lod) / session_lod
    Plus would_pass_gate = vol_ratio >= 2.0 AND dist_from_lod_pct <= 0.002
    """
    bars = bars.sort_values("minute").reset_index(drop=True).copy()
    bars["session_lod"] = bars["low"].cummin()
    bars["dist_from_lod_pct"] = (bars["low"] - bars["session_lod"]).abs() \
        / bars["session_lod"]

    # 20-min trailing avg vol (excluding current bar)
    avg_vols = []
    for i, row in bars.iterrows():
        if i < 5:
            avg_vols.append(None)
            continue
        prior = bars.iloc[max(0, i - 20):i]
        avg_vols.append(prior["volume"].mean() if len(prior) >= 5 else None)
    bars["avg_20m_vol"] = avg_vols
    bars["vol_ratio"] = bars["volume"] / bars["avg_20m_vol"]
    bars["near_lod_strict"] = bars["dist_from_lod_pct"] <= 0.002
    bars["high_vol_strict"] = bars["vol_ratio"] >= 2.0
    bars["would_pass"] = bars["near_lod_strict"] & bars["high_vol_strict"]
    return bars


def gate_signature_summary(ticker: str, day: str) -> dict:
    """Pull all gate evaluations for the ticker and summarize."""
    conn = sqlite3.connect("structural_turns.db")
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT ts, spot, regime, ratio,
                  gate_floor_proximity g1, gate_floor_event g2,
                  gate_volume_absorption g3, gate_agg_flow g4,
                  gate_ncp_corroboration g5, gate_magnitude g6,
                  gate_regime_match g7, gate_cvd_divergence g8,
                  reasons
           FROM structural_turns
           WHERE ticker = ? AND ts BETWEEN ? AND ?
           ORDER BY ts""",
        (ticker, DAY_T0, DAY_T1),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def analyze_ticker(ticker: str) -> dict:
    """Full diagnostic for one ticker on May 1."""
    print(f"\n{'='*70}")
    print(f"  {ticker} forensic — May 1 2026")
    print(f"{'='*70}\n")

    rows = gate_signature_summary(ticker, DAY)
    if not rows:
        print("  No structural_turn evaluations found")
        return {}

    n = len(rows)
    print(f"Total evaluations: {n}")

    # Gate pass rates
    gate_names = ['proximity', 'event', 'volabs', 'aggflow', 'ncp', 'magnitude',
                  'regime', 'cvd']
    pass_rates = {}
    for gi, gname in enumerate(gate_names, start=1):
        n_pass = sum(r[f'g{gi}'] or 0 for r in rows)
        pass_rates[gname] = n_pass / n
        print(f"  Gate {gi} ({gname:<10}): {n_pass}/{n} = {n_pass/n*100:5.1f}%")

    # Best evaluation (most gates passed)
    best = max(rows, key=lambda r: sum(r[f'g{i}'] or 0 for i in range(1, 9)))
    best_score = sum(best[f'g{i}'] or 0 for i in range(1, 9))
    best_t = datetime.fromtimestamp(best['ts']).strftime('%H:%M')
    print(f"\nBest evaluation: {best_t} — {best_score}/8 gates")
    failed = [n for n, gi in zip(gate_names, range(1, 9))
              if not (best[f'g{gi}'] or 0)]
    print(f"  failed: {failed}")
    print(f"  spot=${best['spot']:.2f} regime={best['regime']} ratio={(best['ratio'] or 0):.2f}")

    # Volume absorption deep-dive (the most common failure point)
    if ticker in ("SPY", "QQQ"):
        print(f"\n--- volume_absorption (gate 3) deep-dive ---")
        try:
            bars = session_minute_bars(ticker, DAY)
            print(f"  per-minute bars: {len(bars)} (Databento, true 1-min)")
            va = vol_absorption_per_minute(bars)

            # How often did each criterion pass alone?
            n_near = va["near_lod_strict"].sum()
            n_volh = va["high_vol_strict"].sum()
            n_both = va["would_pass"].sum()
            print(f"  bars near LOD (within 0.2%):  {n_near}/{len(va)}")
            print(f"  bars with vol >= 2.0x avg:    {n_volh}/{len(va)}")
            print(f"  bars meeting BOTH (would fire): {n_both}/{len(va)}")

            # Show the closest near-LOD bars by vol_ratio
            near = va[va["near_lod_strict"]].copy()
            if not near.empty:
                near = near.nlargest(5, "vol_ratio")[
                    ["hhmm", "low", "session_lod", "volume", "avg_20m_vol",
                     "vol_ratio", "would_pass"]
                ]
                print(f"\n  Top 5 near-LOD bars by vol-ratio:")
                print(near.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        except FileNotFoundError as e:
            print(f"  Databento data missing: {e}")

    # Regime gate deep-dive (SPY-specific concern, only 9% pass)
    if ticker == "SPY":
        print(f"\n--- regime_match (gate 7) deep-dive ---")
        regimes = pd.Series([r['regime'] for r in rows]).value_counts()
        print(f"  Regime distribution: {regimes.to_dict()}")
        ratios = [r['ratio'] for r in rows if r['ratio'] is not None]
        if ratios:
            ratios = pd.Series(ratios)
            print(f"  Pos/neg ratio: min={ratios.min():.2f} median={ratios.median():.2f} "
                  f"max={ratios.max():.2f}")
            print(f"  ratio < 1.0 (neg dominant): {(ratios < 1.0).sum()}")
            print(f"  ratio > 2.0 (pos dominant): {(ratios > 2.0).sum()}")

        # When did regime gate pass vs fail?
        passed = [r for r in rows if r['g7']]
        failed = [r for r in rows if not r['g7']]
        if passed:
            ratios_p = [r['ratio'] for r in passed if r['ratio']]
            print(f"  Passing rows: ratio range "
                  f"{min(ratios_p):.2f}-{max(ratios_p):.2f} (n={len(passed)})")
        if failed:
            ratios_f = [r['ratio'] for r in failed if r['ratio']]
            print(f"  Failing rows: ratio range "
                  f"{min(ratios_f):.2f}-{max(ratios_f):.2f} (n={len(failed)})")

    return {
        "ticker": ticker, "n_evals": n, "pass_rates": pass_rates,
        "best_score": best_score,
    }


def main() -> int:
    print(f"=" * 70)
    print(f"  MAY 1 STRUCTURAL TURN FORENSIC")
    print(f"  Why zero qualified fires across 1131 evaluations × 3 tickers?")
    print(f"=" * 70)

    summaries = {}
    for ticker in ("SPY", "QQQ", "IWM"):
        try:
            summaries[ticker] = analyze_ticker(ticker)
        except Exception as e:
            print(f"\n{ticker}: FAILED — {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    for ticker, s in summaries.items():
        if not s:
            continue
        prs = s["pass_rates"]
        bottlenecks = [g for g, r in prs.items() if r < 0.30]
        print(f"\n{ticker}: best 7day-eval = {s['best_score']}/8 "
              f"(bottlenecks: {bottlenecks})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
