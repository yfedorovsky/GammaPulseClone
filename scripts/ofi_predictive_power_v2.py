"""Test #2 v2 — memory-efficient OFI predictive power on raw tape.

The v1 script (ofi_predictive_power.py) blew up to 6 GB RAM trying to
concat 125 days × 2 tickers of minute-bar data into a single DataFrame
before regressing. Killed mid-run.

v2 approach: maintain running sums Σx, Σy, Σxy, Σx², Σy² per ticker ×
horizon and compute regression at the end via the closed-form OLS
formulas. O(1) memory per ticker × horizon regardless of how many
days are pooled.

For each (ticker, day):
  build minute-series (small, only the day's worth)
  attach trailing 5-min OFI + future-return at horizons 5/15/30
  add (x_i, y_i) to per-(ticker, horizon) running sums
  release the day's DataFrame

At the end:
  β = (n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)
  α = (Σy − β·Σx) / n
  R² = (n·Σxy − Σx·Σy)² / [(n·Σx² − Σx²)(n·Σy² − Σy²)]
  t-stat from residual variance — needs Σ((y − ŷ)²) which we compute
  from the same running sums

Output: same docs/research/ofi_predictive_power.md / .csv as v1.

Run:
  python scripts/ofi_predictive_power_v2.py
"""
from __future__ import annotations

import gc
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
SESSION_END_HHMM = "15:30"


class RunningOLS:
    """Streaming OLS sufficient statistics for one (ticker, horizon)."""

    __slots__ = ("n", "sum_x", "sum_y", "sum_xx", "sum_yy", "sum_xy")

    def __init__(self):
        self.n = 0
        self.sum_x = 0.0
        self.sum_y = 0.0
        self.sum_xx = 0.0
        self.sum_yy = 0.0
        self.sum_xy = 0.0

    def update(self, x: np.ndarray, y: np.ndarray) -> None:
        """Add a batch of (x, y) observations to the running sums."""
        # Drop NaN pairs
        mask = ~(np.isnan(x) | np.isnan(y))
        if not mask.any():
            return
        x = x[mask].astype(np.float64)
        y = y[mask].astype(np.float64)
        self.n += len(x)
        self.sum_x += float(x.sum())
        self.sum_y += float(y.sum())
        self.sum_xx += float((x * x).sum())
        self.sum_yy += float((y * y).sum())
        self.sum_xy += float((x * y).sum())

    def regress(self) -> dict:
        if self.n < 30:
            return {"n": self.n, "beta": np.nan, "alpha": np.nan,
                    "r_sq": np.nan, "t_stat": np.nan}
        n = self.n
        x_mean = self.sum_x / n
        y_mean = self.sum_y / n
        sxx = self.sum_xx - n * x_mean * x_mean
        syy = self.sum_yy - n * y_mean * y_mean
        sxy = self.sum_xy - n * x_mean * y_mean
        if sxx <= 0:
            return {"n": n, "beta": np.nan, "alpha": np.nan,
                    "r_sq": np.nan, "t_stat": np.nan}
        beta = sxy / sxx
        alpha = y_mean - beta * x_mean
        # ss_tot = syy
        # ss_res = syy − beta * sxy   (closed-form residual sum of squares)
        ss_res = syy - beta * sxy
        r_sq = 1 - ss_res / syy if syy > 0 else np.nan
        # t-stat
        if n - 2 > 0:
            sigma_sq = ss_res / (n - 2)
            se_beta = np.sqrt(sigma_sq / sxx) if sxx > 0 else np.nan
            t_stat = beta / se_beta if se_beta > 0 else np.nan
        else:
            t_stat = np.nan
        return {"n": n, "beta": beta, "alpha": alpha,
                "r_sq": r_sq, "t_stat": t_stat}


def build_minute_series(ticker: str, day: str) -> pd.DataFrame | None:
    df = load_window(ticker, day, SESSION_START_HHMM, "16:00")
    if df.empty:
        return None
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    if quotes.empty:
        return None
    quotes["ofi_event"] = compute_ofi_per_event(quotes).values
    ts_et = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes["_minute"] = ts_et.dt.strftime("%H:%M")
    quotes["_mid"] = (quotes["bid_px_00"] + quotes["ask_px_00"]) / 2
    minute = quotes.groupby("_minute").agg(
        ofi_sum=("ofi_event", "sum"),
        mid_close=("_mid", "last"),
    ).reset_index().rename(columns={"_minute": "hhmm"})
    # Restrict to session window
    minute = minute[(minute["hhmm"] >= SESSION_START_HHMM)
                    & (minute["hhmm"] <= "15:59")].reset_index(drop=True)
    minute["mid_close"] = minute["mid_close"].ffill()
    # Trailing-window OFI
    minute["ofi_trailing"] = (minute["ofi_sum"]
                               .rolling(WINDOW_MIN, min_periods=WINDOW_MIN)
                               .sum())
    # Future returns at each horizon
    for h in HORIZONS_MIN:
        minute[f"ret_h{h}"] = (minute["mid_close"].shift(-h)
                                / minute["mid_close"] - 1)
    # Restrict to range where both x and y are defined
    minute = minute[(minute["hhmm"] >= SESSION_START_HHMM)
                    & (minute["hhmm"] <= SESSION_END_HHMM)]
    return minute


def main() -> int:
    status = cache_status()
    if status.empty:
        print("Cache empty.")
        return 1

    runners: dict[tuple, RunningOLS] = {
        (t, h): RunningOLS()
        for t in SUPPORTED_TICKERS for h in HORIZONS_MIN
    }

    days_per_ticker = status.groupby("ticker")["date"].apply(list).to_dict()
    print(f"Streaming OFI regression across "
          f"{sum(len(v) for v in days_per_ticker.values())} ticker-days...",
          flush=True)

    for ticker in SUPPORTED_TICKERS:
        days = days_per_ticker.get(ticker, [])
        n_processed = 0
        for day in days:
            try:
                minute = build_minute_series(ticker, day)
            except Exception as e:
                print(f"  {ticker} {day}: error — {e}", flush=True)
                continue
            if minute is None or len(minute) < 30:
                if minute is not None:
                    del minute
                continue
            x = minute["ofi_trailing"].values
            for h in HORIZONS_MIN:
                y = minute[f"ret_h{h}"].values
                runners[(ticker, h)].update(x, y)
            n_processed += 1
            del minute
            # Aggressive GC every 25 days to keep memory flat
            if n_processed % 25 == 0:
                gc.collect()
                print(f"  {ticker}: {n_processed}/{len(days)} days, "
                      f"running n@h5={runners[(ticker, 5)].n:,}", flush=True)
        print(f"  {ticker}: {n_processed} days complete", flush=True)
        gc.collect()

    print("\n=== Per-ticker OFI predictive regressions ===")
    out_rows = []
    for ticker in SUPPORTED_TICKERS:
        for h in HORIZONS_MIN:
            r = runners[(ticker, h)].regress()
            r.update({"ticker": ticker, "horizon_min": h})
            out_rows.append(r)
            print(f"  {ticker} h={h}min: n={r['n']:>7,}  "
                  f"β={r['beta']:>+.3e}  R²={r['r_sq']:.4f}  "
                  f"t={r['t_stat']:>+6.2f}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows).to_csv(OUT_CSV, index=False)

    # Markdown report
    md = ["# Test #2 — OFI predictive power on raw tape (v2 streaming OLS)\n"]
    md.append("Streaming closed-form OLS over per-minute observations across "
              "all cached days. Memory is O(1) per (ticker × horizon) — no "
              "DataFrame concat, no in-memory pooling. Kills the 6 GB blow-up "
              "that crashed the v1 script.\n")
    md.append("Literature R² (Cont 2014, liquid index ETFs): 0.05-0.15\n")
    md.append("\n## Per-ticker, per-horizon\n")
    md.append("| Ticker | Horizon (min) | n | β | R² | t-stat |")
    md.append("|---|---|---|---|---|---|")
    for r in out_rows:
        md.append(
            f"| {r['ticker']} | {r['horizon_min']} | {r['n']:,} | "
            f"{r['beta']:+.3e} | {r['r_sq']:.4f} | {r['t_stat']:+.2f} |"
        )

    md.append("\n## Verdict\n")
    valid_r2 = [r["r_sq"] for r in out_rows if not pd.isna(r["r_sq"])]
    max_r2 = max(valid_r2) if valid_r2 else 0
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
            "differences from Cont's 2014 sample. Foundation for OFI gate "
            "is shaky; consider Tier-1 monitoring before committing to v2."
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
            "Suspect: regime artifact or feature leakage. Sanity-check the "
            "regression before treating this as robust evidence."
        )

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
