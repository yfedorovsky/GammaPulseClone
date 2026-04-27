"""MA tightening detector + VCP-lite signal.

Phase 6 — the actual Qullamaggie entry trigger we've been missing.

Per user's Apr 27 weekend review:
    "wait for lower risk entries where the MAs tighten up"

This is the Volatility Contraction Pattern (VCP) Minervini codified:
- Stock makes a strong move (already filtered by QM × Minervini gates)
- Then consolidates: daily range narrows, MAs converge
- Breakout from tight range = lower-risk entry vs chasing extension

Two detectable patterns:

1. MA TIGHTNESS:
   tightness = (max(SMA20, SMA50) - min(SMA20, SMA50, SMA100)) / spot
   < 0.05 (5%)  → tight
   < 0.03 (3%)  → very tight (Qullamaggie A+ entry)

2. RANGE CONTRACTION (VCP-lite):
   Compare last 5d daily range avg to last 20d avg
   contraction_ratio = avg_range_5d / avg_range_20d
   < 0.7 → meaningful contraction (range narrowed >30%)
   < 0.5 → strong VCP

Combined "tight setup" signal fires when BOTH conditions met.

Usage:
    from server.ma_tightening import detect_tight_setup
    state = detect_tight_setup("MU")
    # {"is_tight": True, "tightness_pct": 2.4, "range_contraction": 0.55,
    #  "grade": "A", "details": "..."}

Wires into:
  - paper_trading.py as an entry-quality bonus (DEMOTE if loose)
  - signals.py as a confluence flag for Zone-A entries
  - macro_context dashboard as a per-ticker readout
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "ma_tightening_cache.json"
TTL_SEC = 4 * 3600  # 4 hours

# Thresholds
TIGHTNESS_VERY_TIGHT = 0.03      # MAs within 3% of spot — A+ tight
TIGHTNESS_TIGHT = 0.05            # MAs within 5% — A tight
RANGE_CONTRACTION_STRONG = 0.50   # 5d range < 50% of 20d → strong VCP
RANGE_CONTRACTION_MILD = 0.70     # 5d range < 70% → mild contraction


@dataclass
class TightSetup:
    ticker: str
    spot: float
    tightness_pct: float
    range_contraction: float
    sma20: float
    sma50: float
    sma100: float
    is_tight: bool
    grade: str           # "A+" / "A" / "B" / "NONE"
    details: str
    as_of: str


def _fetch_ohlc(ticker: str, days: int = 130) -> pd.DataFrame:
    """Pull recent daily OHLC for ticker."""
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days * 2)  # buffer
    try:
        df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                         progress=False, auto_adjust=True, threads=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty or len(df) < 100:
        return pd.DataFrame()
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def detect_tight_setup(ticker: str, ohlc: pd.DataFrame | None = None) -> TightSetup | None:
    """Compute tightness + VCP signal for a ticker.

    Args:
        ticker: symbol
        ohlc: optional pre-fetched OHLC (for batch processing)

    Returns: TightSetup or None if data insufficient
    """
    if ohlc is None:
        ohlc = _fetch_ohlc(ticker)
    if ohlc.empty:
        return None

    spot = float(ohlc["Close"].iloc[-1])
    sma20 = float(ohlc["Close"].rolling(20).mean().iloc[-1])
    sma50 = float(ohlc["Close"].rolling(50).mean().iloc[-1])
    sma100 = float(ohlc["Close"].rolling(100).mean().iloc[-1])

    # MA tightness — how far apart are the MAs as % of spot
    ma_max = max(sma20, sma50, sma100)
    ma_min = min(sma20, sma50, sma100)
    tightness_abs = ma_max - ma_min
    tightness_pct = tightness_abs / spot if spot > 0 else 1.0

    # Range contraction (VCP)
    daily_range = ohlc["High"] - ohlc["Low"]
    avg_5d = float(daily_range.tail(5).mean())
    avg_20d = float(daily_range.tail(20).mean())
    range_contraction = avg_5d / avg_20d if avg_20d > 0 else 1.0

    # Grade the setup
    if tightness_pct <= TIGHTNESS_VERY_TIGHT and range_contraction <= RANGE_CONTRACTION_STRONG:
        grade = "A+"
        is_tight = True
    elif tightness_pct <= TIGHTNESS_TIGHT and range_contraction <= RANGE_CONTRACTION_MILD:
        grade = "A"
        is_tight = True
    elif tightness_pct <= TIGHTNESS_TIGHT or range_contraction <= RANGE_CONTRACTION_MILD:
        grade = "B"
        is_tight = False  # only one criterion met
    else:
        grade = "NONE"
        is_tight = False

    details = (f"tightness {tightness_pct*100:.1f}%, "
               f"range contraction {range_contraction:.2f} "
               f"(5d/20d), grade {grade}")

    return TightSetup(
        ticker=ticker, spot=spot,
        tightness_pct=round(tightness_pct * 100, 2),
        range_contraction=round(range_contraction, 2),
        sma20=round(sma20, 2), sma50=round(sma50, 2), sma100=round(sma100, 2),
        is_tight=is_tight, grade=grade, details=details,
        as_of=datetime.datetime.now().isoformat(timespec="seconds"),
    )


def scan_cohort(tickers: list[str]) -> dict[str, TightSetup]:
    """Batch detect across a list of tickers."""
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=260)
    df = yf.download(tickers, start=start.isoformat(), end=end.isoformat(),
                     progress=False, auto_adjust=True, threads=True,
                     group_by="ticker")
    out = {}
    for t in tickers:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                if t not in df.columns.get_level_values(0):
                    continue
                sub = df[t].dropna(how="all")
            else:
                sub = df.dropna(how="all")
            if len(sub) < 100:
                continue
            sub.index = pd.to_datetime(sub.index).tz_localize(None)
            ts = detect_tight_setup(t, sub)
            if ts:
                out[t] = ts
        except (KeyError, IndexError):
            continue
    return out


def to_dict(ts: TightSetup) -> dict:
    return {
        "ticker": ts.ticker, "spot": ts.spot,
        "tightness_pct": ts.tightness_pct,
        "range_contraction": ts.range_contraction,
        "sma20": ts.sma20, "sma50": ts.sma50, "sma100": ts.sma100,
        "is_tight": ts.is_tight, "grade": ts.grade,
        "details": ts.details, "as_of": ts.as_of,
    }


def refresh_and_save(tickers: list[str]) -> dict:
    """Scan + persist to JSON cache."""
    setups = scan_cohort(tickers)
    cache = {t: to_dict(s) for t, s in setups.items()}
    CACHE_PATH.write_text(json.dumps(cache, indent=2, default=str))
    return cache


def get_cached(ticker: str) -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(CACHE_PATH.read_text())
        return cache.get(ticker.upper())
    except (json.JSONDecodeError, OSError):
        return None


if __name__ == "__main__":
    # Scan the 7 LIQUID+MEDIUM cohort + a few QM-screen-passing names
    targets = ["MU", "SNDK", "AAOI", "CAMT", "CIEN", "GLW", "VICR",
               "MXL", "AXTI", "ALAB", "CRDO"]
    print(f"Scanning {len(targets)} tickers for tight setups...\n")
    setups = scan_cohort(targets)

    # Sort by grade then tightness
    grade_order = {"A+": 0, "A": 1, "B": 2, "NONE": 3}
    sorted_setups = sorted(setups.values(),
                            key=lambda s: (grade_order.get(s.grade, 99),
                                           s.tightness_pct))

    print(f"{'Ticker':<8} {'Spot':>8} {'Tight%':>7} {'Range5d/20d':>12} {'Grade':<6} Details")
    print("-" * 80)
    for s in sorted_setups:
        marker = " ✓" if s.is_tight else ""
        print(f"{s.ticker:<8} {s.spot:>8.2f} {s.tightness_pct:>6.2f}% "
              f"{s.range_contraction:>11.2f} {s.grade:<6}{marker}")

    refresh_and_save(targets)
    print(f"\nCached to {CACHE_PATH.name}")

    tight_names = [s.ticker for s in sorted_setups if s.is_tight]
    print(f"\nTight setups (Qullamaggie low-risk entry candidates): "
          f"{', '.join(tight_names) if tight_names else 'none currently'}")
