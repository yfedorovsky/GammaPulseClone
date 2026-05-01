"""Test #4 — Background distributions for v2 gate thresholds.

The whole point of this script: provide PRE-COMMITTED, EXTERNAL-DATA
threshold percentiles that any future v2 gate (OFI, microprice, spread)
can use without contaminating its design with the strategy's outcomes.

Perplexity's contamination concern (Apr 30 critique #4.5): "If gate
thresholds were tuned looking at data overlapping with the test window,
the backtest is in-sample parameter optimization." The fix is to
calibrate thresholds against a separate background distribution NEVER
joined to the strategy outcome data — exactly what this script
produces.

Method:
For each cached (ticker, day), compute per-MINUTE features:
  - 5-min trailing OFI
  - microprice deviation (mp − mid)
  - spread (ask − bid)
  - per-minute aggressor ratio (Lee-Ready)
  - per-minute volume

Pool ALL minutes across ALL days, by ticker AND by time-of-day bucket.
Compute distribution percentiles (1, 5, 10, 25, 50, 75, 90, 95, 99).

These percentiles are the *priors* for any v2 threshold. e.g. an "OFI
gate fires when OFI exceeds the 95th percentile of historical 5-min OFI
for this ticker × this TOD bucket" — a pre-committed, externally
calibrated threshold that doesn't peek at outcomes.

TOD buckets:
  09:30-10:00  (open hour)
  10:00-12:00  (morning)
  12:00-14:00  (lunch / midday)
  14:00-15:30  (afternoon)
  15:30-16:00  (close)

Output:
  docs/research/background_distributions.md
  docs/research/background_distributions.csv (long format: ticker, tod, feature, percentile, value)

Run:
  python scripts/background_distributions.py
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
from scripts.lee_ready_classifier import lee_ready_classify  # noqa: E402
from scripts.microstructure_features import compute_ofi_per_event  # noqa: E402

OUT_REPORT = ROOT / "docs" / "research" / "background_distributions.md"
OUT_CSV = ROOT / "docs" / "research" / "background_distributions.csv"

SUPPORTED_TICKERS = ["SPY", "QQQ"]
TRAILING_WIN_MIN = 5
PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]
TOD_BUCKETS = [
    ("open",       "09:30", "10:00"),
    ("morning",    "10:00", "12:00"),
    ("midday",     "12:00", "14:00"),
    ("afternoon",  "14:00", "15:30"),
    ("close",      "15:30", "16:00"),
]


def hhmm_to_min(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def assign_tod(hhmm: str) -> str:
    m = hhmm_to_min(hhmm)
    for name, lo, hi in TOD_BUCKETS:
        if hhmm_to_min(lo) <= m < hhmm_to_min(hi):
            return name
    return "outside"


def build_minute_features(ticker: str, day: str) -> pd.DataFrame | None:
    """Per-minute aggregations: ofi_sum, mid_close, mean_spread,
    aggressor_volume_pct, total_volume."""
    df = load_window(ticker, day, "09:30", "16:00")
    if df.empty:
        return None
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    trades = df[df["action"] == "T"].copy()
    if quotes.empty or trades.empty:
        return None

    # Compute OFI per quote event
    quotes["ofi_event"] = compute_ofi_per_event(quotes).values
    # Spread per event
    quotes["_spread"] = quotes["ask_px_00"] - quotes["bid_px_00"]
    # Mid per event
    quotes["_mid"] = (quotes["bid_px_00"] + quotes["ask_px_00"]) / 2
    # Microprice deviation
    bid_sz = quotes["bid_sz_00"].astype(float)
    ask_sz = quotes["ask_sz_00"].astype(float)
    bid_px = quotes["bid_px_00"].astype(float)
    ask_px = quotes["ask_px_00"].astype(float)
    total = bid_sz + ask_sz
    with np.errstate(divide="ignore", invalid="ignore"):
        mp = np.where(total > 0,
                      (bid_sz * ask_px + ask_sz * bid_px) / total,
                      np.nan)
    quotes["_mp_dev"] = mp - quotes["_mid"]

    # Per-minute aggregation of quote-side
    qts = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes["_minute"] = qts.dt.strftime("%H:%M")
    q_agg = quotes.groupby("_minute").agg(
        ofi_sum=("ofi_event", "sum"),
        mid_close=("_mid", "last"),
        mean_spread=("_spread", "mean"),
        mean_mp_dev=("_mp_dev", "mean"),
        n_quotes=("ofi_event", "size"),
    ).reset_index().rename(columns={"_minute": "hhmm"})

    # Per-minute aggregation of trade-side (with Lee-Ready labels)
    if not trades.empty:
        lr = lee_ready_classify(trades)
        trades = trades.assign(_lr=lr.values)
        tts = pd.to_datetime(trades["ts_event"], utc=True) \
            .dt.tz_convert("America/New_York")
        trades = trades.assign(_minute=tts.dt.strftime("%H:%M"))
        t_agg = trades.groupby("_minute").apply(
            lambda g: pd.Series({
                "total_volume": float(g["size"].sum()),
                "buy_volume": float(g.loc[g["_lr"] == "BUY", "size"].sum()),
                "n_trades": len(g),
            }),
            include_groups=False,
        ).reset_index().rename(columns={"_minute": "hhmm"})
        t_agg["aggressor_ratio"] = np.where(
            t_agg["total_volume"] > 0,
            t_agg["buy_volume"] / t_agg["total_volume"], np.nan,
        )
    else:
        t_agg = pd.DataFrame(columns=["hhmm", "total_volume", "buy_volume",
                                       "n_trades", "aggressor_ratio"])

    out = q_agg.merge(t_agg, on="hhmm", how="left")
    out["total_volume"] = out["total_volume"].fillna(0)
    out["n_trades"] = out["n_trades"].fillna(0).astype(int)
    out["ofi_trailing_5m"] = (out["ofi_sum"]
                              .rolling(TRAILING_WIN_MIN, min_periods=TRAILING_WIN_MIN)
                              .sum())
    out["tod_bucket"] = out["hhmm"].apply(assign_tod)
    out["ticker"] = ticker
    out["day"] = day
    # Free the multi-million-row source DataFrames before returning;
    # otherwise pandas/arrow's lazy allocation can keep them resident
    # across loop iterations and accumulate into OOM territory.
    del df, quotes, trades, q_agg, t_agg
    return out


def percentile_table(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-(ticker, tod_bucket, feature) percentile distribution."""
    feature_cols = [
        "ofi_trailing_5m", "mean_spread", "mean_mp_dev",
        "aggressor_ratio", "total_volume", "n_trades",
    ]
    rows = []
    for (ticker, tod), sub in df.groupby(["ticker", "tod_bucket"]):
        if tod == "outside":
            continue
        for col in feature_cols:
            vals = sub[col].dropna().values
            if len(vals) < 50:
                continue
            for p in PERCENTILES:
                rows.append({
                    "ticker": ticker, "tod_bucket": tod,
                    "feature": col,
                    "percentile": p,
                    "value": float(np.percentile(vals, p)),
                    "n_obs": int(len(vals)),
                })
    return pd.DataFrame(rows)


def main() -> int:
    status = cache_status()
    if status.empty:
        print("Cache empty — run databento_loader.py --build-cache first")
        return 1

    days = sorted(status["date"].unique())
    print(f"Computing background distributions across "
          f"{len(days)} days × {len(SUPPORTED_TICKERS)} tickers...\n",
          flush=True)

    all_minutes = []
    for ticker in SUPPORTED_TICKERS:
        ticker_days = status[status["ticker"] == ticker]["date"].tolist()
        n_processed = 0
        for day in ticker_days:
            mf = build_minute_features(ticker, day)
            if mf is not None and not mf.empty:
                all_minutes.append(mf)
                n_processed += 1
            # Aggressive GC every 25 days — prevents accumulating per-day
            # DataFrame baggage that the OFI v1 + day_regime scripts hit OOM on
            if n_processed % 25 == 0 and n_processed > 0:
                gc.collect()
                print(f"  {ticker}: {n_processed}/{len(ticker_days)} days, "
                      f"pooled {len(all_minutes)} chunks", flush=True)
        print(f"  {ticker}: {n_processed} days processed", flush=True)
        gc.collect()

    if not all_minutes:
        print("No minute features built.")
        return 1

    big = pd.concat(all_minutes, ignore_index=True)
    print(f"\nTotal minute observations: {len(big):,} across "
          f"{big['day'].nunique()} unique dates")

    pct = percentile_table(big)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pct.to_csv(OUT_CSV, index=False)
    print(f"Long-format percentile CSV -> {OUT_CSV}")

    # Wide pivot for the markdown report
    md = ["# Test #4 — Background distributions for v2 gate thresholds\n"]
    md.append(f"Source: {len(big):,} per-minute observations across "
              f"{big['day'].nunique()} cached days × "
              f"{len(SUPPORTED_TICKERS)} tickers.\n")
    md.append(f"These percentiles are the **pre-committed external "
              f"thresholds** for any future v2 gate (OFI, microprice, "
              f"spread, aggressor). Calibrating against them avoids the "
              f"in-sample contamination Perplexity flagged.\n")

    for feature in ["ofi_trailing_5m", "mean_spread", "mean_mp_dev",
                    "aggressor_ratio", "total_volume", "n_trades"]:
        sub = pct[pct["feature"] == feature]
        if sub.empty:
            continue
        wide = sub.pivot_table(
            index=["ticker", "tod_bucket"],
            columns="percentile",
            values="value",
        ).reset_index()
        n_obs = sub.groupby(["ticker", "tod_bucket"])["n_obs"].first() \
            .reset_index()
        wide = wide.merge(n_obs, on=["ticker", "tod_bucket"])
        md.append(f"\n## `{feature}` percentiles\n")
        md.append("| Ticker | TOD | n_obs | "
                  + " | ".join(f"p{p}" for p in PERCENTILES) + " |")
        md.append("|" + "---|" * (3 + len(PERCENTILES)))
        for _, r in wide.iterrows():
            md.append(
                f"| {r['ticker']} | {r['tod_bucket']} | "
                f"{int(r['n_obs']):,} | "
                + " | ".join(f"{r[p]:.4g}" for p in PERCENTILES) + " |"
            )

    md.append("\n## Usage\n")
    md.append("Example: an OFI-spike gate that fires only when "
              "trailing-5min OFI exceeds the historical p95 for the "
              "current (ticker, TOD) cell. Look up the value from this "
              "table at v2 design time, freeze it, and never tune. The "
              "gate is then externally calibrated and the strategy "
              "result is testable out-of-sample without contamination.")

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"Report -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
