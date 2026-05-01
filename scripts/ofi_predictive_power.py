"""Test #2 — OFI predictive power on raw tape (Cont 2014 replication).

The published claim: "The price impact of order book events" (Cont,
Kukanov, Stoikov 2014) finds that OFI in a short rolling window has
linear predictive power on next-N-minute returns with R² ~0.05-0.15
on liquid index ETFs.

Replication: across all cached SPY+QQQ days, build minute-bar series of:
  - 5-min trailing OFI ending at minute t
  - return from t to t+5min (via mid prices)
  - return from t to t+15min
  - return from t to t+30min

Pool across days, run per-ticker linear regressions:
  return_{t,t+H} = α + β · OFI_{t-5,t} + ε

Report β, t-stat, R², N. Per-ticker, per-horizon.

Decision rule:
  - R² ≈ 0 across all horizons: OFI doesn't predict in this regime.
    Don't build OFI gates; the academic claim doesn't transfer here.
  - R² 0.05-0.15 (literature range): consistent with published findings.
    Foundation for an OFI-based v2 gate exists.
  - R² > 0.20: unusually predictive — suspect data leak, in-sample
    overfit, or genuine regime where flow leads strongly.

Run:
  python scripts/ofi_predictive_power.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import (  # noqa: E402
    cache_status, load_window,
)
from scripts.microstructure_features import compute_ofi_per_event  # noqa: E402

OUT_REPORT = ROOT / "docs" / "research" / "ofi_predictive_power.md"
OUT_CSV = ROOT / "docs" / "research" / "ofi_predictive_power.csv"

WINDOW_MIN = 5
HORIZONS_MIN = [5, 15, 30]
SUPPORTED_TICKERS = ["SPY", "QQQ"]
SESSION_START_HHMM = "09:30"
SESSION_END_HHMM = "15:30"  # leave room for 30-min horizons before close


def build_minute_series(ticker: str, day: str) -> pd.DataFrame | None:
    """Build a minute-indexed series with mid_close and per-minute OFI."""
    df = load_window(ticker, day, SESSION_START_HHMM, "16:00")
    if df.empty:
        return None
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    if quotes.empty:
        return None
    # Per-event OFI
    quotes["ofi_event"] = compute_ofi_per_event(quotes).values
    # Bucket to minute (use ts_event in ET)
    ts_et = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes = quotes.assign(_minute=ts_et.dt.strftime("%H:%M"))
    # Per-minute aggregation: sum of OFI events, last mid quote
    quotes["_mid"] = (quotes["bid_px_00"] + quotes["ask_px_00"]) / 2
    minute = quotes.groupby("_minute").agg(
        ofi_sum=("ofi_event", "sum"),
        mid_close=("_mid", "last"),
        n_quotes=("ofi_event", "size"),
    ).reset_index().rename(columns={"_minute": "hhmm"})
    minute = minute[(minute["hhmm"] >= SESSION_START_HHMM)
                    & (minute["hhmm"] <= "15:59")].reset_index(drop=True)
    # Forward-fill mid for empty minutes (shouldn't happen for SPY/QQQ but safe)
    minute["mid_close"] = minute["mid_close"].ffill()
    return minute


def attach_features(minute: pd.DataFrame, window_min: int = WINDOW_MIN,
                    horizons: list[int] = None) -> pd.DataFrame:
    horizons = horizons or HORIZONS_MIN
    df = minute.copy()
    # Trailing-window OFI: sum of last `window_min` minutes (inclusive)
    df["ofi_trailing"] = (df["ofi_sum"]
                          .rolling(window_min, min_periods=window_min).sum())
    for h in horizons:
        df[f"ret_h{h}"] = df["mid_close"].shift(-h) / df["mid_close"] - 1
    return df


def regress_pool(rows: pd.DataFrame, x_col: str, y_col: str) -> dict:
    """Plain OLS via numpy.polyfit deg=1, plus R² and t-stat on slope."""
    sub = rows[[x_col, y_col]].dropna()
    if len(sub) < 30:
        return {"n": len(sub), "beta": np.nan, "alpha": np.nan,
                "r_sq": np.nan, "t_stat": np.nan}
    x = sub[x_col].values
    y = sub[y_col].values
    n = len(x)
    x_mean, y_mean = x.mean(), y.mean()
    sxx = ((x - x_mean) ** 2).sum()
    sxy = ((x - x_mean) * (y - y_mean)).sum()
    if sxx == 0:
        return {"n": n, "beta": np.nan, "alpha": np.nan,
                "r_sq": np.nan, "t_stat": np.nan}
    beta = sxy / sxx
    alpha = y_mean - beta * x_mean
    y_hat = alpha + beta * x
    ss_res = ((y - y_hat) ** 2).sum()
    ss_tot = ((y - y_mean) ** 2).sum()
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    # t-stat on beta (standard error from residual variance)
    if n - 2 > 0:
        sigma_sq = ss_res / (n - 2)
        se_beta = np.sqrt(sigma_sq / sxx) if sxx > 0 else np.nan
        t_stat = beta / se_beta if se_beta > 0 else np.nan
    else:
        t_stat = np.nan
    return {"n": n, "beta": beta, "alpha": alpha,
            "r_sq": r_sq, "t_stat": t_stat}


def main() -> int:
    status = cache_status()
    if status.empty:
        print("Cache empty — run databento_loader.py --build-cache first")
        return 1

    out_rows = []
    pooled = {ticker: [] for ticker in SUPPORTED_TICKERS}

    days_per_ticker = status.groupby("ticker")["date"].apply(list).to_dict()
    print(f"Pooling minute series across "
          f"{sum(len(v) for v in days_per_ticker.values())} ticker-days...",
          flush=True)

    for ticker in SUPPORTED_TICKERS:
        days = days_per_ticker.get(ticker, [])
        for day in days:
            minute = build_minute_series(ticker, day)
            if minute is None or len(minute) < 30:
                continue
            feat = attach_features(minute)
            feat = feat[(feat["hhmm"] >= SESSION_START_HHMM)
                        & (feat["hhmm"] <= SESSION_END_HHMM)]
            feat["ticker"] = ticker
            feat["day"] = day
            pooled[ticker].append(feat)
        print(f"  {ticker}: {len(pooled[ticker])} days pooled", flush=True)

    print("\n=== Per-ticker OFI predictive regressions ===")
    for ticker in SUPPORTED_TICKERS:
        if not pooled[ticker]:
            print(f"  {ticker}: no data")
            continue
        big = pd.concat(pooled[ticker], ignore_index=True)
        for h in HORIZONS_MIN:
            r = regress_pool(big, "ofi_trailing", f"ret_h{h}")
            r.update({"ticker": ticker, "horizon_min": h})
            out_rows.append(r)
            print(f"  {ticker} h={h}min: n={r['n']:>6,}  "
                  f"β={r['beta']:>+.3e}  R²={r['r_sq']:.4f}  "
                  f"t={r['t_stat']:>+6.2f}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows).to_csv(OUT_CSV, index=False)

    md = ["# Test #2 — OFI predictive power on raw tape\n"]
    md.append("Replication of Cont/Kukanov/Stoikov (2014). Pool minute-bar "
              "observations across all cached days; for each ticker and each "
              f"horizon, regress next-H-minute mid return on trailing "
              f"{WINDOW_MIN}-minute OFI.\n")
    md.append("Literature R²: 0.05-0.15 on liquid index ETFs.\n")
    md.append("\n## Per-ticker, per-horizon\n")
    md.append("| Ticker | Horizon (min) | n | β | R² | t-stat |")
    md.append("|---|---|---|---|---|---|")
    for r in out_rows:
        md.append(
            f"| {r['ticker']} | {r['horizon_min']} | {r['n']:,} | "
            f"{r['beta']:+.3e} | {r['r_sq']:.4f} | {r['t_stat']:+.2f} |"
        )
    md.append("\n## Verdict\n")
    max_r2 = max((r["r_sq"] for r in out_rows
                  if not pd.isna(r["r_sq"])), default=0)
    if max_r2 < 0.02:
        md.append(
            f"Maximum R² across all (ticker × horizon) cells is {max_r2:.4f}. "
            "OFI does not show meaningful predictive power on next-N-minute "
            "returns in this 6-month sample. The Cont 2014 result does not "
            "transfer to this regime. **Do not build OFI gates** — the "
            "academic foundation isn't there for SPY/QQQ in 2025-26."
        )
    elif max_r2 < 0.05:
        md.append(
            f"Maximum R² across all cells is {max_r2:.4f}. Weakly positive "
            "but below the published 5-15% range. Could indicate regime "
            "differences from Cont's 2014 sample (post-decimalization, "
            "pre-0DTE proliferation). Foundation for OFI gate is shaky; "
            "consider Tier-1 monitoring before committing to a v2 build."
        )
    elif max_r2 < 0.20:
        md.append(
            f"Maximum R² across all cells is {max_r2:.4f}, in the literature "
            "range. **OFI predictive power confirmed**. Foundation for an "
            "OFI gate in v2 is solid. Pre-commit thresholds against the "
            "background distribution (Test #4) before building."
        )
    else:
        md.append(
            f"Maximum R² is {max_r2:.4f}, ABOVE the literature range. "
            "Suspect: in-sample overfit, sample-period regime, or feature "
            "leakage. Sanity-check the regression before treating this as "
            "robust evidence."
        )

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
