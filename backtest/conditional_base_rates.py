"""Conditional base rate forecast engine.

Phase 4 #3 — the highest-value item per Perplexity synthesis. Builds a
historical conditional probability table for SPY forward returns by
regime cell, with N-display and Bayesian shrinkage.

Approach (per Timmermann 2011 + Ang-Bekaert 2003 regime-switching
literature):
  1. Pull SPY full history (yfinance, free, ~30 years)
  2. For each daily bar, classify regime by SPY-only signals:
        a. SPY trend stack (above 20/50/200 in order)
        b. VIX bucket (<15, 15-20, 20-30, 30+)
        c. SPY drawdown from trailing 252d high (0 to -3%, -3 to -8%, -8 to -15%, <-15%)
  3. For each forward horizon (3, 10, 20 trading days), compute returns
  4. Group by (trend, vix, dd) cell and tabulate hit rate + avg return
  5. Apply Bayesian shrinkage when N < 100:
        adjusted_p = (N × cell_p + k × pooled_p) / (N + k)
        with k = 30 and pooled_p = unconditional hit rate

Per-bar lookup: given today's regime cell, return forward probabilities
with N-display so the user knows whether to trust the estimate.

Build cache:
    python -m backtest.conditional_base_rates --build

Live lookup:
    from backtest.conditional_base_rates import lookup_today
    f = lookup_today()  # current SPY regime + forecast probabilities
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "conditional_base_rates.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

HORIZONS = [3, 10, 20]
SHRINKAGE_K = 30                    # Bayesian prior strength
SHRINKAGE_THRESHOLD = 100          # below this N, shrink

# Bucket definitions
VIX_BUCKETS = ["<15", "15-20", "20-30", ">=30"]
DD_BUCKETS = ["0_-3", "-3_-8", "-8_-15", "<-15"]
TREND_BUCKETS = ["STACKED_BULL", "MIXED_BULL", "MIXED_BEAR", "STACKED_BEAR"]


def vix_bucket(vix: float) -> str:
    if vix < 15:
        return "<15"
    if vix < 20:
        return "15-20"
    if vix < 30:
        return "20-30"
    return ">=30"


def dd_bucket(dd_pct: float) -> str:
    """dd_pct is negative (e.g. -7.5 = -7.5% from 252d high)."""
    a = abs(dd_pct)
    if a < 3:
        return "0_-3"
    if a < 8:
        return "-3_-8"
    if a < 15:
        return "-8_-15"
    return "<-15"


def trend_bucket(close: float, sma20: float, sma50: float, sma200: float) -> str:
    if pd.isna(sma200):
        return "STACKED_BEAR"  # fallback for early bars
    if close > sma20 > sma50 > sma200:
        return "STACKED_BULL"
    if close > sma200 and (close > sma50 or close > sma20):
        return "MIXED_BULL"
    if close < sma20 < sma50 < sma200:
        return "STACKED_BEAR"
    return "MIXED_BEAR"


def build_cache() -> dict[str, Any]:
    """Build the conditional base rate cache from yfinance history."""
    print("Pulling SPY (since 1990) and VIX (since inception 1990)...")
    spy = yf.download("SPY", start="1993-02-01", end=datetime.date.today(),
                      progress=False, auto_adjust=True, threads=False)
    vix = yf.download("^VIX", start="1993-02-01", end=datetime.date.today(),
                      progress=False, auto_adjust=True, threads=False)

    if hasattr(spy.columns, "get_level_values"):
        spy.columns = spy.columns.get_level_values(0)
    if hasattr(vix.columns, "get_level_values"):
        vix.columns = vix.columns.get_level_values(0)

    spy.index = pd.to_datetime(spy.index).tz_localize(None)
    vix.index = pd.to_datetime(vix.index).tz_localize(None)

    print(f"  SPY: {len(spy)} bars from {spy.index[0].date()} to {spy.index[-1].date()}")
    print(f"  VIX: {len(vix)} bars")

    df = spy[["Close"]].copy()
    df["sma20"] = df["Close"].rolling(20).mean()
    df["sma50"] = df["Close"].rolling(50).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    df["high_252"] = df["Close"].rolling(252).max()
    df["dd_pct"] = -100.0 * (df["high_252"] - df["Close"]) / df["high_252"]
    df = df.join(vix["Close"].rename("vix"), how="left")
    df["vix"] = df["vix"].ffill()  # forward-fill VIX gaps

    # Forward returns
    for h in HORIZONS:
        df[f"fwd_{h}d"] = df["Close"].shift(-h) / df["Close"] - 1.0

    # Bucket assignments
    df["trend"] = df.apply(
        lambda r: trend_bucket(r["Close"], r["sma20"], r["sma50"], r["sma200"]),
        axis=1,
    )
    df["vix_b"] = df["vix"].apply(vix_bucket)
    df["dd_b"] = df["dd_pct"].apply(dd_bucket)

    # Drop early bars without 200d MA
    df = df.dropna(subset=["sma200", "vix"])
    print(f"  After warmup: {len(df)} bars")

    # Pooled (unconditional) baseline
    pooled = {}
    for h in HORIZONS:
        col = f"fwd_{h}d"
        s = df[col].dropna()
        pooled[f"hit_{h}d"] = float((s > 0).mean() * 100)
        pooled[f"avg_{h}d"] = float(s.mean() * 100)
        pooled[f"med_{h}d"] = float(s.median() * 100)
        pooled[f"n_{h}d"] = int(len(s))

    # Per-cell tabulation
    cells: dict[str, dict[str, Any]] = {}
    for trend in TREND_BUCKETS:
        for vb in VIX_BUCKETS:
            for db in DD_BUCKETS:
                key = f"{trend}|{vb}|{db}"
                sub = df[(df["trend"] == trend) & (df["vix_b"] == vb)
                         & (df["dd_b"] == db)]
                if sub.empty:
                    continue
                cell = {"n_bars": int(len(sub)), "trend": trend,
                        "vix_b": vb, "dd_b": db}
                for h in HORIZONS:
                    s = sub[f"fwd_{h}d"].dropna()
                    if s.empty:
                        cell[f"hit_{h}d"] = None
                        cell[f"avg_{h}d"] = None
                        cell[f"shrunk_hit_{h}d"] = None
                        cell[f"n_{h}d"] = 0
                        continue
                    raw_hit = (s > 0).mean() * 100
                    raw_avg = s.mean() * 100
                    n = len(s)
                    if n < SHRINKAGE_THRESHOLD:
                        # Shrink toward pooled
                        adj_hit = (n * raw_hit + SHRINKAGE_K * pooled[f"hit_{h}d"]) / (n + SHRINKAGE_K)
                        adj_avg = (n * raw_avg + SHRINKAGE_K * pooled[f"avg_{h}d"]) / (n + SHRINKAGE_K)
                    else:
                        adj_hit = raw_hit
                        adj_avg = raw_avg
                    # Standard error of proportion (Wilson approximation)
                    p = raw_hit / 100
                    if n > 1:
                        se = 100 * (p * (1 - p) / n) ** 0.5
                    else:
                        se = 50.0
                    cell[f"hit_{h}d"] = round(raw_hit, 1)
                    cell[f"shrunk_hit_{h}d"] = round(adj_hit, 1)
                    cell[f"avg_{h}d"] = round(raw_avg, 2)
                    cell[f"shrunk_avg_{h}d"] = round(adj_avg, 2)
                    cell[f"se_hit_{h}d"] = round(se, 1)
                    cell[f"n_{h}d"] = n
                cells[key] = cell

    out = {
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "horizons": HORIZONS,
        "shrinkage_k": SHRINKAGE_K,
        "shrinkage_threshold": SHRINKAGE_THRESHOLD,
        "n_total_bars": int(len(df)),
        "date_range": [str(df.index[0].date()), str(df.index[-1].date())],
        "pooled": {k: round(v, 2) for k, v in pooled.items()},
        "cells": cells,
    }
    CACHE_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {len(cells)} cells to {CACHE_PATH.name}")
    return out


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def lookup_today() -> dict[str, Any]:
    """Return forecast for current SPY regime cell."""
    cache = _load_cache()
    if not cache:
        return {"error": "cache not built. Run with --build first."}

    # Compute today's regime
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=400)
    spy = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                      progress=False, auto_adjust=True, threads=False)
    if hasattr(spy.columns, "get_level_values"):
        spy.columns = spy.columns.get_level_values(0)
    spy["sma20"] = spy["Close"].rolling(20).mean()
    spy["sma50"] = spy["Close"].rolling(50).mean()
    spy["sma200"] = spy["Close"].rolling(200).mean()
    spy["high_252"] = spy["Close"].rolling(252).max()
    spy["dd_pct"] = -100.0 * (spy["high_252"] - spy["Close"]) / spy["high_252"]

    last = spy.iloc[-1]
    vix = yf.download("^VIX", start=start.isoformat(), end=end.isoformat(),
                       progress=False, auto_adjust=True, threads=False)
    if hasattr(vix.columns, "get_level_values"):
        vix.columns = vix.columns.get_level_values(0)
    vix_now = float(vix["Close"].iloc[-1])

    trend = trend_bucket(float(last["Close"]), float(last["sma20"]),
                          float(last["sma50"]), float(last["sma200"]))
    vb = vix_bucket(vix_now)
    db = dd_bucket(float(last["dd_pct"]))
    key = f"{trend}|{vb}|{db}"

    cell = cache["cells"].get(key)
    pooled = cache["pooled"]

    out = {
        "as_of": str(last.name.date()),
        "spy_close": round(float(last["Close"]), 2),
        "vix": round(vix_now, 2),
        "drawdown_pct": round(float(last["dd_pct"]), 2),
        "trend_bucket": trend,
        "vix_bucket": vb,
        "dd_bucket": db,
        "cell_key": key,
        "pooled_baseline": pooled,
    }

    if not cell:
        out["forecast"] = {"error": f"no historical data for cell {key}"}
        return out

    forecast = {"n_bars_in_cell": cell["n_bars"]}
    for h in HORIZONS:
        n = cell.get(f"n_{h}d", 0)
        raw_hit = cell.get(f"hit_{h}d")
        adj_hit = cell.get(f"shrunk_hit_{h}d")
        raw_avg = cell.get(f"avg_{h}d")
        adj_avg = cell.get(f"shrunk_avg_{h}d")
        se = cell.get(f"se_hit_{h}d")
        forecast[f"{h}d"] = {
            "n": n,
            "hit_raw_pct": raw_hit,
            "hit_shrunk_pct": adj_hit,
            "avg_raw_pct": raw_avg,
            "avg_shrunk_pct": adj_avg,
            "hit_se_pct": se,
            "is_shrunk": n < SHRINKAGE_THRESHOLD,
            "vs_baseline_hit": (
                round(adj_hit - pooled[f"hit_{h}d"], 1)
                if adj_hit is not None else None
            ),
            "vs_baseline_avg": (
                round(adj_avg - pooled[f"avg_{h}d"], 2)
                if adj_avg is not None else None
            ),
        }
    out["forecast"] = forecast
    return out


if __name__ == "__main__":
    if "--build" in sys.argv:
        build_cache()
    if "--lookup" in sys.argv or "--build" in sys.argv:
        f = lookup_today()
        print()
        print(f"As of {f.get('as_of')}: SPY ${f.get('spy_close')}  VIX {f.get('vix')}  "
              f"DD {f.get('drawdown_pct')}%")
        print(f"Cell: {f.get('cell_key')}")
        if "forecast" in f and "error" not in f["forecast"]:
            fc = f["forecast"]
            pooled = f["pooled_baseline"]
            print(f"\nN={fc['n_bars_in_cell']} historical bars in this cell")
            print(f"\n{'Horizon':<8}  {'N':>5}  {'Hit %':>7}  {'(±SE)':>7}  "
                  f"{'Avg %':>7}  {'vs Baseline Hit':>15}  {'vs Baseline Avg':>15}  Note")
            for h in HORIZONS:
                d = fc[f"{h}d"]
                shr = " (shrunk)" if d["is_shrunk"] else ""
                print(f"  {h:<6}d  {d['n']:>5}  "
                      f"{d['hit_shrunk_pct']:>6.1f}%  ±{d['hit_se_pct']:>4.1f}%  "
                      f"{d['avg_shrunk_pct']:>+6.2f}%  "
                      f"{d['vs_baseline_hit']:>+13.1f}pp  "
                      f"{d['vs_baseline_avg']:>+14.2f}pp"
                      f"{shr}")
            print(f"\nUnconditional baselines (n={pooled['n_3d']}):")
            for h in HORIZONS:
                print(f"  {h}d: hit={pooled[f'hit_{h}d']:.1f}%  "
                      f"avg={pooled[f'avg_{h}d']:+.2f}%")
    if not any(arg in sys.argv for arg in ("--build", "--lookup")):
        print("Usage: python -m backtest.conditional_base_rates [--build] [--lookup]")
