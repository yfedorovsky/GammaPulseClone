"""Regime breadth gate — % of universe above 200-day SMA.

Phase 1 #1 from the cross-LLM synthesis (docs/feedback/strategy_0425/SYNTHESIS.md):
all three LLMs converged that macro/regime should be a hard pre-filter, not a
5% scoring tweak. The specific metric they agreed on is the percent of stocks
above their 200-day moving average.

Thresholds (consensus across ChatGPT, Grok, Perplexity):
    > 60%   FULL_BULL       normal operation, all grades eligible
    40-60%  TRANSITIONAL    A/A+ only, B/B+ suspended, cohort cap tightened
    < 40%   BEAR            no new momentum longs

This module:
    - Computes %above200 daily from yfinance (free, no extra cost)
    - Caches the result to data/regime_breadth.json per date
    - Exposes get_breadth_regime() returning the classification + raw metric

Usage:
    from server.regime_breadth import get_breadth_regime, regime_allows_grade

    regime = get_breadth_regime()
    if not regime_allows_grade(regime, "B+"):
        return  # block this entry

    # or as a hard cohort cap adjuster:
    cohort_cap_pct = regime["cohort_cap_pct"]

Refresh cadence: once per day after market close, or lazily on first read.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "regime_breadth.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Thresholds (consensus from cross-LLM synthesis Apr 25 2026)
BREADTH_BULL_FLOOR = 60.0     # >60% → full bull
BREADTH_BEAR_CEILING = 40.0   # <40% → no new longs

# Phase 3: McClellan early-warning thresholds.
# Perplexity-unique recommendation: NYMO turning persistently negative for
# 10+ days typically PRECEDES the breadth break by 1-3 weeks. Use as a
# WARNING state to throttle new entries before the full TRANSITIONAL gate
# trips. Does not modify allowed_grades — that's the breadth gate's job.
MCCLELLAN_WARNING_NEG_DAYS = 10
MCCLELLAN_WARNING_THRESHOLD = -25.0   # NYMO median over the last N days

# Cohort cap by regime (consensus Apr 25)
COHORT_CAP = {
    "FULL_BULL": 8.0,         # current default
    "FULL_BULL_WARNING": 6.0, # tightened when McClellan early warning trips
    "TRANSITIONAL": 5.0,      # tighter when breadth deteriorating
    "BEAR": 0.0,              # no new exposure
    "INSUFFICIENT_DATA": 5.0, # conservative default
}

# Grade eligibility by regime
ALLOWED_GRADES = {
    "FULL_BULL": {"A+", "A", "B+", "B"},
    "FULL_BULL_WARNING": {"A+", "A", "B+"},  # B suspended on early warning
    "TRANSITIONAL": {"A+", "A"},  # B/B+ suspended
    "BEAR": set(),                # nothing
    "INSUFFICIENT_DATA": {"A+", "A"},  # treat as transitional, conservative
}


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.write_text(json.dumps(data, indent=2, default=str))


def _universe_tickers() -> list[str]:
    """Pull the live scanner universe from server.tickers."""
    try:
        from .tickers import all_tickers
    except ImportError:
        from server.tickers import all_tickers
    return all_tickers()


def _filter_invalid_for_yf(tickers: list[str]) -> list[str]:
    """Drop tickers that yfinance cannot resolve (indices, BRK.B, etc.).

    These are excluded from the breadth count because they either don't trade
    as common stock or yfinance can't quote them. Excluding ~5-10 of 400 names
    has negligible impact on the percentage.
    """
    skip = {"VIX", "SPX", "NDX", "RUT", "DRAM", "EWY"}
    out = []
    for t in tickers:
        if t in skip:
            continue
        if "." in t:
            # yfinance uses BRK-B not BRK.B; we'll skip rather than translate
            continue
        out.append(t)
    return out


def compute_pct_above_200d(force: bool = False) -> dict[str, Any]:
    """Compute % of universe above 200-day SMA.

    Caches by date — only re-fetches if today's date is not yet cached.
    Uses yfinance batch download for efficiency.

    Args:
        force: if True, recompute even if today is cached.

    Returns:
        {
            "date": "YYYY-MM-DD",
            "n_above": int,
            "n_total": int,
            "pct_above_200d": float (0-100),
            "regime": "FULL_BULL" | "TRANSITIONAL" | "BEAR" | "INSUFFICIENT_DATA",
            "cohort_cap_pct": float,
            "allowed_grades": list[str],
        }
    """
    today = datetime.date.today().isoformat()
    cache = _load_cache()

    if not force and cache.get("date") == today:
        return cache

    import yfinance as yf

    tickers = _filter_invalid_for_yf(_universe_tickers())
    if not tickers:
        return _build_result(today, 0, 0, "INSUFFICIENT_DATA")

    end = datetime.date.today()
    start = end - datetime.timedelta(days=320)  # 200 trading days + buffer

    try:
        df = yf.download(
            tickers, start=start, end=end + datetime.timedelta(days=1),
            progress=False, auto_adjust=True, threads=True, group_by="ticker",
        )
    except Exception as e:
        print(f"[REGIME_BREADTH] yf.download failed: {e}")
        return cache or _build_result(today, 0, 0, "INSUFFICIENT_DATA")

    if df is None or df.empty:
        return cache or _build_result(today, 0, 0, "INSUFFICIENT_DATA")

    n_above = 0
    n_total = 0
    failures: list[str] = []

    for t in tickers:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                if t not in df.columns.get_level_values(0):
                    failures.append(t)
                    continue
                close = df[t]["Close"].dropna()
            else:
                close = df["Close"].dropna()
            if len(close) < 200:
                failures.append(t)
                continue
            sma200 = close.rolling(200).mean().iloc[-1]
            last = close.iloc[-1]
            if pd.isna(sma200) or pd.isna(last):
                failures.append(t)
                continue
            n_total += 1
            if last > sma200:
                n_above += 1
        except (KeyError, IndexError):
            failures.append(t)
            continue

    if n_total == 0:
        return cache or _build_result(today, 0, 0, "INSUFFICIENT_DATA")

    pct = 100.0 * n_above / n_total
    mcc = check_mcclellan_warning()
    regime = classify_regime(pct, mcclellan_warning=mcc["warning_active"])
    result = _build_result(today, n_above, n_total, regime, pct=pct,
                           failures=len(failures))
    result["mcclellan"] = mcc
    _save_cache(result)
    return result


def classify_regime(pct_above: float, mcclellan_warning: bool = False) -> str:
    """Classify breadth regime, optionally promoting FULL_BULL to WARNING state.

    Args:
        pct_above: percent of universe above 200d MA
        mcclellan_warning: True if McClellan persistently negative (early warning)

    Returns: regime label (FULL_BULL, FULL_BULL_WARNING, TRANSITIONAL, BEAR)
    """
    if pct_above >= BREADTH_BULL_FLOOR:
        return "FULL_BULL_WARNING" if mcclellan_warning else "FULL_BULL"
    if pct_above >= BREADTH_BEAR_CEILING:
        return "TRANSITIONAL"
    return "BEAR"


def check_mcclellan_warning() -> dict:
    """Phase 3: detect McClellan-Oscillator early-warning state.

    Per Perplexity (cross-LLM synthesis): NYMO turning persistently
    negative (10+ days median < -25) precedes the breadth break by
    1-3 weeks. Returns:

        {
            "warning_active": bool,
            "n_recent_negative_days": int,
            "median_recent": float,
            "latest": float,
            "reason": str,
        }
    """
    try:
        from .breadth import _get_oscillator_history
        history = _get_oscillator_history("NYSE", limit=MCCLELLAN_WARNING_NEG_DAYS)
        if not history or len(history) < MCCLELLAN_WARNING_NEG_DAYS // 2:
            return {
                "warning_active": False,
                "n_recent_negative_days": 0,
                "median_recent": 0.0,
                "latest": 0.0,
                "reason": "insufficient NYMO history",
            }
        oscillators = [h.get("oscillator", 0) for h in history]
        n_neg = sum(1 for v in oscillators if v < 0)
        median_recent = sorted(oscillators)[len(oscillators) // 2]
        latest = oscillators[-1] if oscillators else 0.0
        warning_active = (
            n_neg >= MCCLELLAN_WARNING_NEG_DAYS - 2  # tolerance: 8 of 10
            and median_recent < MCCLELLAN_WARNING_THRESHOLD
        )
        reason = (
            f"NYMO median (last {len(oscillators)}d) = {median_recent:.1f}, "
            f"{n_neg}/{len(oscillators)} negative"
        )
        return {
            "warning_active": warning_active,
            "n_recent_negative_days": n_neg,
            "median_recent": round(median_recent, 1),
            "latest": round(latest, 1),
            "reason": reason,
        }
    except Exception as e:
        return {
            "warning_active": False,
            "n_recent_negative_days": 0,
            "median_recent": 0.0,
            "latest": 0.0,
            "reason": f"error: {e}",
        }


def _build_result(date: str, n_above: int, n_total: int, regime: str,
                  pct: float | None = None, failures: int = 0) -> dict[str, Any]:
    if pct is None:
        pct = 100.0 * n_above / n_total if n_total else 0.0
    return {
        "date": date,
        "n_above": n_above,
        "n_total": n_total,
        "pct_above_200d": round(pct, 2),
        "regime": regime,
        "cohort_cap_pct": COHORT_CAP[regime],
        "allowed_grades": sorted(ALLOWED_GRADES[regime]),
        "failures": failures,
    }


def get_breadth_regime(force: bool = False) -> dict[str, Any]:
    """Convenience accessor — same as compute_pct_above_200d."""
    return compute_pct_above_200d(force=force)


def regime_allows_grade(regime: dict[str, Any], grade: str) -> bool:
    """Hard gate: should this grade be allowed under the current regime?"""
    return grade in regime.get("allowed_grades", [])


def regime_blocks_new_longs(regime: dict[str, Any]) -> bool:
    """Hard kill switch — True when no new momentum longs should be opened."""
    return regime.get("regime") == "BEAR"


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    r = compute_pct_above_200d(force=force)
    print(json.dumps(r, indent=2))
