"""Test #6 — Spread-regime classifier.

Hypothesis: when bid-ask spread is anomalously wide, conditions are
"toxic" (high uncertainty, dealers backing off, retail on the wrong
side). Buying 0DTE long-premium during such conditions is mechanically
disadvantaged because:
  - Wider spread = larger cost-to-trade penalty (entry ask − exit bid)
  - Wider spread often correlates with high realized vol → option vega
    risk — but not necessarily directional move

If our gates fire MORE often during spread spikes than at random
moments, that's a problem. If they avoid spread spikes, that's
self-selection working in our favor.

For each of the 27 fires (SPY+QQQ):
  - Compute fire-time and 30-min-pre-fire spread distribution
  - Compare to that day's overall session spread distribution
  - Flag fires where fire-window mean spread is in the day's top 10%

Aggregate: of the fires flagged as high-spread, what's the gated outcome
distribution vs non-flagged fires?

Output:
  docs/research/spread_regime_audit.md
  docs/research/spread_regime_audit.csv

Run:
  python scripts/spread_regime_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import load_window, _cache_path  # noqa: E402

FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "spread_regime_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "spread_regime_audit.csv"

SUPPORTED_TICKERS = {"SPY", "QQQ"}
WINDOW_MIN = 30


def _hhmm_minus_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


def compute_day_spread_distribution(ticker: str, day: str) -> dict:
    """Pull session-wide quote events, compute per-minute spread stats."""
    df = load_window(ticker, day, "09:30", "16:00")
    if df.empty:
        return {}
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    if quotes.empty:
        return {}
    quotes["_spread"] = quotes["ask_px_00"] - quotes["bid_px_00"]
    quotes = quotes[quotes["_spread"] > 0]
    if quotes.empty:
        return {}
    ts_et = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes = quotes.assign(_minute=ts_et.dt.strftime("%H:%M"))
    minute_mean = quotes.groupby("_minute")["_spread"].mean()
    return {
        "day_p50_spread": float(minute_mean.quantile(0.50)),
        "day_p90_spread": float(minute_mean.quantile(0.90)),
        "day_p99_spread": float(minute_mean.quantile(0.99)),
        "day_mean_spread": float(minute_mean.mean()),
    }


def compute_window_spread(ticker: str, day: str,
                          start_hhmm: str, end_hhmm: str) -> float | None:
    df = load_window(ticker, day, start_hhmm, end_hhmm)
    if df.empty:
        return None
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    if quotes.empty:
        return None
    quotes["_spread"] = quotes["ask_px_00"] - quotes["bid_px_00"]
    quotes = quotes[quotes["_spread"] > 0]
    if quotes.empty:
        return None
    return float(quotes["_spread"].mean())


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    target = fires[fires["ticker"].isin(SUPPORTED_TICKERS)].copy()
    print(f"Auditing {len(target)} fires (SPY+QQQ from {len(fires)} total)\n",
          flush=True)

    # Cache day-level distributions to avoid re-computing for multiple
    # fires on the same (ticker, day)
    day_dist_cache: dict[tuple, dict] = {}
    rows = []
    for _, fire in target.iterrows():
        ticker = fire["ticker"]
        day = fire["day"]
        fire_hhmm = fire["time"]
        if not _cache_path(ticker, day).exists():
            continue
        key = (ticker, day)
        if key not in day_dist_cache:
            day_dist_cache[key] = compute_day_spread_distribution(ticker, day)
        day_dist = day_dist_cache[key]
        if not day_dist:
            continue
        start = _hhmm_minus_minutes(fire_hhmm, WINDOW_MIN)
        win_spread = compute_window_spread(ticker, day, start, fire_hhmm)
        if win_spread is None:
            continue
        # How does this fire-window's mean spread compare to the day's distro?
        # 0 = equal to day p50, 1 = day p90, etc.
        ratio_to_p50 = win_spread / day_dist["day_p50_spread"]
        flagged_high_spread = win_spread > day_dist["day_p90_spread"]
        rows.append({
            "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
            "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
            "direction": fire["direction"], "tier": fire.get("tier"),
            "opt_eod_pnl": fire.get("opt_eod_pnl"),
            "window_mean_spread": win_spread,
            **day_dist,
            "ratio_to_day_p50": ratio_to_p50,
            "flagged_high_spread": int(flagged_high_spread),
        })
        flag_str = "HIGH_SPREAD" if flagged_high_spread else "ok"
        print(f"  {day} {ticker} {fire_hhmm}: "
              f"win_spread={win_spread:.4f}  "
              f"day_p90={day_dist['day_p90_spread']:.4f}  "
              f"ratio_to_p50={ratio_to_p50:.2f}  {flag_str}",
              flush=True)

    if not rows:
        print("No rows produced.")
        return 1

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nPer-fire CSV -> {OUT_CSV}")

    # Aggregate
    n_high = int(df["flagged_high_spread"].sum())
    print(f"\n=== Aggregate ===")
    print(f"  Fires flagged HIGH_SPREAD: {n_high}/{len(df)}")
    print(f"  Mean window_mean_spread / day_p50: "
          f"{df['ratio_to_day_p50'].mean():.2f}")
    print(f"  Mean window_mean_spread / day_p90: "
          f"{(df['window_mean_spread'] / df['day_p90_spread']).mean():.2f}")

    # Outcome split
    if df["opt_eod_pnl"].notna().any():
        with_pnl = df.dropna(subset=["opt_eod_pnl"])
        high = with_pnl[with_pnl["flagged_high_spread"] == 1]
        normal = with_pnl[with_pnl["flagged_high_spread"] == 0]
        print(f"\n=== Outcome by spread regime ===")
        print(f"  Normal-spread fires:  n={len(normal)}, "
              f"mean PnL={normal['opt_eod_pnl'].mean():>+7.1f}%, "
              f"WR={(normal['opt_eod_pnl']>0).mean()*100:>5.1f}%")
        if len(high):
            print(f"  HIGH-spread fires:    n={len(high)}, "
                  f"mean PnL={high['opt_eod_pnl'].mean():>+7.1f}%, "
                  f"WR={(high['opt_eod_pnl']>0).mean()*100:>5.1f}%")

    md = ["# Test #6 — Spread regime audit\n"]
    md.append(f"Sample: {len(df)} fires (SPY+QQQ).")
    md.append(f"For each fire: compare 30-min-pre-fire mean spread to "
              f"that day's session-wide minute-spread distribution.\n")
    md.append("\n## Aggregate\n")
    md.append(f"- Fires flagged HIGH_SPREAD (window mean > day p90): "
              f"{n_high}/{len(df)} ({n_high/len(df)*100:.0f}%)")
    md.append(f"- Mean ratio of fire-window spread to day p50: "
              f"{df['ratio_to_day_p50'].mean():.2f}")
    md.append(f"  (1.0 = at the day's median; >1.5 = significantly elevated)")

    if df["opt_eod_pnl"].notna().any():
        with_pnl = df.dropna(subset=["opt_eod_pnl"])
        high = with_pnl[with_pnl["flagged_high_spread"] == 1]
        normal = with_pnl[with_pnl["flagged_high_spread"] == 0]
        md.append("\n## Outcome by spread regime\n")
        md.append("| Regime | n | mean PnL | win rate |")
        md.append("|---|---|---|---|")
        if len(normal):
            md.append(f"| Normal | {len(normal)} | "
                      f"{normal['opt_eod_pnl'].mean():+.1f}% | "
                      f"{(normal['opt_eod_pnl']>0).mean()*100:.1f}% |")
        if len(high):
            md.append(f"| HIGH spread | {len(high)} | "
                      f"{high['opt_eod_pnl'].mean():+.1f}% | "
                      f"{(high['opt_eod_pnl']>0).mean()*100:.1f}% |")

        md.append("\n## Verdict\n")
        if len(high) >= 3 and len(normal) >= 3:
            diff = normal["opt_eod_pnl"].mean() - high["opt_eod_pnl"].mean()
            if diff > 30:
                md.append(
                    f"Normal-spread fires outperform HIGH-spread fires by "
                    f"{diff:.0f}pp avg PnL. **Consider a 'do not fire when "
                    "30-min spread > day p90' gate** for v2 — this filters "
                    "the worst-expectancy subset before they cost capital."
                )
            elif diff < -30:
                md.append(
                    "Counter-intuitively, HIGH-spread fires outperform "
                    "normal-spread fires here. The widening spread might "
                    "be capturing real volatility-of-opportunity — could "
                    "be a SIGNAL not a filter. Investigate further."
                )
            else:
                md.append(
                    "Outcome difference between spread regimes is small "
                    f"(<30pp). Spread regime doesn't strongly differentiate "
                    "fire quality in this sample. No spread-based gate "
                    "justified yet."
                )
        else:
            md.append("Insufficient sample sizes per regime for a verdict.")

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
