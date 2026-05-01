"""Test #7 — SPY ↔ QQQ lead-lag at minute resolution.

Index-family confirmation in the live system is currently a same-second
cross-check (a fire on SPY is "confirmed" if QQQ is also fireable in
the same direction within seconds). This test asks: at the
microstructure level, does one ETF systematically *lead* the other? If
yes, lag-aligned cross-confirmation could be a stronger v2 signal than
same-second alignment.

Method:
  - For each cached day, build per-minute OFI series for SPY and QQQ
  - Compute Pearson correlation of SPY OFI(t) vs QQQ OFI(t + lag)
    for lag ∈ {-5, -3, -1, 0, +1, +3, +5} minutes
  - Pool across days; report mean correlation per lag

Interpretation:
  - Peak at lag = 0 → simultaneous; same-second cross-confirm is fine
  - Peak at positive lag (e.g., +1, +3) → SPY leads QQQ; v2 should
    use a lagged QQQ confirmation when firing on SPY signal
  - Peak at negative lag → QQQ leads SPY; reverse the asymmetry
  - Flat / no peak → no useful lead-lag structure; cross-confirm
    is just noise

Output:
  docs/research/lead_lag_audit.md
  docs/research/lead_lag_audit.csv

Run:
  python scripts/lead_lag_audit.py
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

OUT_REPORT = ROOT / "docs" / "research" / "lead_lag_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "lead_lag_audit.csv"

LAGS_MIN = [-5, -3, -2, -1, 0, 1, 2, 3, 5]


def build_minute_ofi(ticker: str, day: str) -> pd.Series | None:
    """Per-minute summed OFI series for one (ticker, day), indexed by HH:MM."""
    df = load_window(ticker, day, "09:30", "16:00")
    if df.empty:
        return None
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    if quotes.empty:
        return None
    quotes["ofi_event"] = compute_ofi_per_event(quotes).values
    ts_et = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes = quotes.assign(_minute=ts_et.dt.strftime("%H:%M"))
    minute_ofi = quotes.groupby("_minute")["ofi_event"].sum()
    del df, quotes, ts_et  # free the multi-million-row source
    return minute_ofi


def main() -> int:
    status = cache_status()
    if status.empty:
        print("Cache empty.")
        return 1

    # Find days where BOTH SPY and QQQ are cached
    spy_days = set(status[status["ticker"] == "SPY"]["date"])
    qqq_days = set(status[status["ticker"] == "QQQ"]["date"])
    common_days = sorted(spy_days & qqq_days)
    print(f"Common cached days for SPY+QQQ: {len(common_days)}\n", flush=True)

    per_day_corrs = []
    for i, day in enumerate(common_days):
        spy = build_minute_ofi("SPY", day)
        qqq = build_minute_ofi("QQQ", day)
        if spy is None or qqq is None:
            continue
        # Align indexes
        merged = pd.DataFrame({"spy": spy, "qqq": qqq}).dropna()
        # Free the per-day Series so they don't accumulate
        del spy, qqq
        if len(merged) < 50:
            del merged
            continue
        # Compute correlations at each lag
        row = {"day": day, "n_minutes": len(merged)}
        for lag in LAGS_MIN:
            shifted_qqq = merged["qqq"].shift(-lag)  # positive lag = QQQ later
            valid = pd.concat([merged["spy"], shifted_qqq], axis=1).dropna()
            if len(valid) < 30:
                row[f"corr_lag{lag:+d}"] = np.nan
                continue
            row[f"corr_lag{lag:+d}"] = float(valid.iloc[:, 0]
                                              .corr(valid.iloc[:, 1]))
        per_day_corrs.append(row)
        # Concise per-day output
        c0 = row.get("corr_lag+0", np.nan)
        c1 = row.get("corr_lag+1", np.nan)
        cm1 = row.get("corr_lag-1", np.nan)
        print(f"  {day}: n={len(merged):>3}  "
              f"corr@lag-1={cm1:>+.3f}  corr@lag0={c0:>+.3f}  "
              f"corr@lag+1={c1:>+.3f}",
              flush=True)
        # Release per-day frames; gc periodically
        del merged
        if (i + 1) % 25 == 0:
            gc.collect()

    if not per_day_corrs:
        print("No usable days.")
        return 1

    df = pd.DataFrame(per_day_corrs)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nPer-day CSV -> {OUT_CSV}")

    # Aggregate across days
    print("\n=== Pooled lead-lag correlations (mean across days) ===")
    print(f"  {'lag (min)':>10}  {'mean corr':>10}  {'std':>10}  {'n_days':>7}")
    pooled = []
    for lag in LAGS_MIN:
        col = f"corr_lag{lag:+d}"
        vals = df[col].dropna()
        if vals.empty:
            continue
        m = vals.mean()
        s = vals.std()
        pooled.append({"lag_min": lag, "mean_corr": m,
                       "std_corr": s, "n_days": len(vals)})
        print(f"  {lag:>+10}  {m:>+10.4f}  {s:>10.4f}  {len(vals):>7}")

    # Find peak lag
    peak = max(pooled, key=lambda r: r["mean_corr"])
    print(f"\n  Peak correlation: lag={peak['lag_min']:+d}min, "
          f"mean corr={peak['mean_corr']:+.4f}")

    md = ["# Test #7 — SPY/QQQ minute-OFI lead-lag\n"]
    md.append(f"Sample: {len(df)} cached days where both SPY and QQQ have data.")
    md.append("Per minute: summed quote-event OFI for each ticker, then "
              "Pearson correlation of SPY(t) vs QQQ(t + lag).\n")
    md.append("\n## Pooled correlation by lag\n")
    md.append("| Lag (min) | Mean corr | Std | n days |")
    md.append("|---|---|---|---|")
    for r in pooled:
        md.append(f"| {r['lag_min']:+d} | {r['mean_corr']:+.4f} | "
                  f"{r['std_corr']:.4f} | {r['n_days']} |")
    md.append("\n## Verdict\n")
    same_sec = next((r["mean_corr"] for r in pooled if r["lag_min"] == 0), 0)
    if peak["lag_min"] == 0 and abs(same_sec) > 0.3:
        md.append(
            f"Peak at lag=0 ({same_sec:+.3f}). SPY and QQQ OFI move "
            "simultaneously at minute resolution. The current same-second "
            "cross-confirmation logic is appropriate; no v2 lag adjustment "
            "needed."
        )
    elif abs(peak["mean_corr"] - same_sec) > 0.05 and peak["lag_min"] != 0:
        md.append(
            f"Peak at lag={peak['lag_min']:+d}min ({peak['mean_corr']:+.3f}) "
            f"vs lag=0 at {same_sec:+.3f}. **One ETF leads the other at "
            "minute resolution.** "
            + ("SPY leads QQQ" if peak["lag_min"] > 0 else "QQQ leads SPY")
            + f" by {abs(peak['lag_min'])}min. v2 cross-confirmation should "
            "use lag-aligned OFI from the leading ticker rather than "
            "same-second snapshots."
        )
    else:
        md.append(
            f"No strong lead-lag structure (peak {peak['mean_corr']:+.3f} at "
            f"lag {peak['lag_min']:+d}; vs lag-0 {same_sec:+.3f}). "
            "Same-second cross-confirm is fine, no lagged v2 logic justified."
        )
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
