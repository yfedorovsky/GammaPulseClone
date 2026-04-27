"""Zone-A / Zone-B classifier — live ticker context.

Phase 2 dependency. Classifies a ticker's current daily bar as a
Zone-A (pullback) or Zone-B (breakout) entry context. Validated edge:

    Zone A entries had +13pp 5d hit-rate edge vs Zone B
    (77.6% vs 64.5%) and +12pp at 10d (80.2% vs 67.7%).
    See iv_zone_validation_FINAL.md.

Daily classification rules (mirroring zone_iv_inversion_full.py):

    in_uptrend = Close > SMA50 > SMA200, SMA50 rising over 10 bars
    Zone A (pullback)  = uptrend + price within ±2.5% above EMA10
                         + lower 55% of 20d range + volume <= 1.30x 20d avg
    Zone B (breakout)  = uptrend + close >= 99% of 20d high
                         + volume >= 1.30x 20d avg

Cache file:
    data/zone_classifier_cache.json:
        {
          "<ticker>": {
            "date": "YYYY-MM-DD", "zone": "A" | "B" | "Other",
            "in_uptrend": bool,
            "ema10_dist_pct": float, "range_pos": float, "vol_ratio": float,
            "updated_at": ISO timestamp
          }
        }
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "zone_classifier_cache.json"
TTL_SEC = 6 * 3600  # refresh at most every 6 hours

# All 19 cohort names get the Zone-A bonus.
COHORT_ZONED = [
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "RES", "CAMT", "TROX",
    "LAR", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
    "AAOI", "CIEN", "GLW", "MU",
]


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.write_text(json.dumps(data, indent=2, default=str))


def _classify(ohlc: pd.DataFrame) -> dict[str, Any]:
    """Compute zone for the latest bar of a single ticker."""
    df = ohlc.copy()
    df["ema10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["sma50"] = df["Close"].rolling(50).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    df["high_20"] = df["High"].rolling(20).max()
    df["low_20"] = df["Low"].rolling(20).min()
    df["range_pos"] = (df["Close"] - df["low_20"]) / (df["high_20"] - df["low_20"])
    df["vol_avg_20"] = df["Volume"].rolling(20).mean()
    df["vol_ratio"] = df["Volume"] / df["vol_avg_20"]
    df["pct_above_ema10"] = (df["Close"] - df["ema10"]) / df["ema10"]
    df["sma50_slope"] = df["sma50"].diff(10)

    last = df.iloc[-1]
    in_uptrend = (
        last["Close"] > last["sma50"] > last["sma200"]
        and last["sma50_slope"] > 0
    )
    zone = "Other"
    if in_uptrend:
        if (-0.015 <= last["pct_above_ema10"] <= 0.025
                and last["range_pos"] <= 0.55
                and last["vol_ratio"] <= 1.30):
            zone = "A"
        elif (last["Close"] >= last["high_20"] * 0.99
              and last["vol_ratio"] >= 1.30):
            zone = "B"
    return {
        "date": last.name.date().isoformat() if hasattr(last.name, "date") else str(last.name),
        "zone": zone,
        "in_uptrend": bool(in_uptrend),
        "ema10_dist_pct": round(float(last["pct_above_ema10"] * 100), 2),
        "range_pos": round(float(last["range_pos"]), 3) if not pd.isna(last["range_pos"]) else None,
        "vol_ratio": round(float(last["vol_ratio"]), 2) if not pd.isna(last["vol_ratio"]) else None,
    }


def update_ticker(ticker: str) -> dict[str, Any] | None:
    """Refresh one ticker's zone classification using yfinance OHLC."""
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=320)
    try:
        df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                         progress=False, auto_adjust=True, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if len(df) < 200:
        return None
    z = _classify(df)
    z["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    return z


def update_all(force: bool = False) -> dict[str, Any]:
    """Refresh all cohort tickers; persist cache. Skips if recently updated."""
    cache = _load_cache()
    now = time.time()
    n_updated = 0
    n_skipped = 0
    for ticker in COHORT_ZONED:
        existing = cache.get(ticker, {})
        if not force and existing.get("updated_at"):
            try:
                ts = datetime.datetime.fromisoformat(existing["updated_at"]).timestamp()
                if now - ts < TTL_SEC:
                    n_skipped += 1
                    continue
            except ValueError:
                pass
        z = update_ticker(ticker)
        if z:
            cache[ticker] = z
            n_updated += 1
    _save_cache(cache)
    print(f"[ZONE] Updated {n_updated}, skipped {n_skipped} (TTL fresh)")
    return cache


def get_zone(ticker: str) -> str | None:
    cache = _load_cache()
    e = cache.get(ticker.upper())
    if not e:
        return None
    return e.get("zone")


def is_zone_a(ticker: str) -> bool:
    return get_zone(ticker) == "A"


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    cache = update_all(force=force)
    print("\nCurrent zone classifications:")
    for t in COHORT_ZONED:
        e = cache.get(t)
        if e:
            zone = e.get("zone", "?")
            d = e.get("ema10_dist_pct")
            rp = e.get("range_pos")
            vr = e.get("vol_ratio")
            print(f"  {t:<6} zone={zone:<5} ema10±%={d}  range_pos={rp}  "
                  f"vol×20d={vr}  asof={e.get('date')}")
