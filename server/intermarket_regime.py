"""Cross-asset INTERMARKET regime gate — risk-on/off from inter-market ratios.

NOTE: distinct from `macro_regime.py` (which tags FOMC/earnings calendar pressure +
VIX term structure → NONE/SOFT/HARD). THIS module is the cross-asset / inter-market
layer: risk-asset vs safe-haven price ratios vs their trend, → RISK-ON/OFF.

Why it exists: the 6/9 defensive rotation and the dead-whale verdict both pointed at
the same hole — GammaPulse has world-class flow + GEX detection but no "is the broad
tape healthy enough to be long this?" filter. This is that filter, from STANDARD
public inter-market ratios (the concept is classic risk-on/off analysis; the
periods/thresholds here are ours).

Three legs — each a risk-asset / safe-haven ratio vs its own trend SMA:
  QQQ/GLD   stocks vs gold         (flight-to-safety unwind = risk-on)
  QQQ/DBC   stocks vs commodities  (growth/disinflation vs hard assets)
  SPY/UUP   stocks vs the dollar   (weak USD = risk-on)
A ratio ABOVE its trend SMA => that leg is RISK-ON. The composite blends how far
above/below trend each leg sits into a 0–100 score (50 = exactly at trend).

Offline/contextual: reads daily closes (Tradier) only; never touches scoring/dispatch.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

# (numerator, denominator, label, trend SMA period in trading days)
# Gold/commodity ratios are slow regime signals (SMA50 medium trend). The DOLLAR
# leg uses a faster SMA20: FX regimes shift quickly, and a slow trend would lag the
# exact risk-off rotations this gate exists to flag (6/9: dollar strengthened on the
# defensive rotation; a 50d trend stayed risk-on while a reactive MA caught it).
_LEGS: list[tuple[str, str, str, int]] = [
    ("QQQ", "GLD", "stocks/gold", 50),
    ("QQQ", "DBC", "stocks/commodities", 50),
    ("SPY", "UUP", "stocks/dollar", 20),
]

_CACHE: dict[str, Any] = {}
_CACHE_TTL = 1800  # 30 min

# How many % above/below trend maps a leg to the 0/100 sub-score extremes.
_FULL_SCALE_PCT = 10.0


def _sma(vals: list[float], period: int) -> Optional[float]:
    if len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def _ratio_series(num: list[float], den: list[float]) -> list[float]:
    """Align by recency (both liquid ETFs trade the same sessions) and divide."""
    n = min(len(num), len(den))
    if n == 0:
        return []
    return [a / b for a, b in zip(num[-n:], den[-n:]) if b]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


async def _default_fetch(ticker: str, days: int) -> list[float]:
    from .conviction_booster import _fetch_daily_closes
    return await _fetch_daily_closes(ticker, days_back=days)


async def compute_intermarket_regime(
    fetch: Optional[Callable[[str, int], Awaitable[list[float]]]] = None,
    days: int = 320,
) -> dict:
    """Compute the cross-asset regime. `fetch(ticker, days)->closes` is injectable
    for tests; defaults to the Tradier daily-close fetcher."""
    fetch = fetch or _default_fetch
    tickers = {t for leg in _LEGS for t in (leg[0], leg[1])}
    closes: dict[str, list[float]] = {}
    for t in tickers:
        try:
            closes[t] = await fetch(t, days)
        except Exception:
            closes[t] = []

    legs: list[dict] = []
    subs: list[float] = []
    on = 0
    for num, den, label, period in _LEGS:
        series = _ratio_series(closes.get(num, []), closes.get(den, []))
        ma = _sma(series, period)
        if not series or ma is None or ma == 0:
            legs.append({"pair": f"{num}/{den}", "label": label, "state": "NO_DATA",
                         "ratio": None, "ma": None, "pct_vs_trend": None,
                         "ma_period": period})
            continue
        ratio = series[-1]
        pct = (ratio / ma - 1.0) * 100.0
        is_on = ratio > ma
        on += int(is_on)
        subs.append(_clamp(50.0 + pct * (50.0 / _FULL_SCALE_PCT), 0.0, 100.0))
        legs.append({"pair": f"{num}/{den}", "label": label,
                     "state": "RISK-ON" if is_on else "RISK-OFF",
                     "ratio": round(ratio, 4), "ma": round(ma, 4),
                     "pct_vs_trend": round(pct, 2), "ma_period": period})

    usable = len(subs)
    composite = round(sum(subs) / usable, 1) if usable else None
    if composite is None:
        regime = "UNKNOWN"
    elif composite >= 55:
        regime = "RISK-ON"
    elif composite <= 45:
        regime = "RISK-OFF"
    else:
        regime = "NEUTRAL"

    detail = ", ".join(f"{l['pair']} {l['state']}" for l in legs if l["state"] != "NO_DATA")
    return {
        "regime": regime,
        "composite": composite,        # 0-100, 50 = at trend
        "legs_on": on,
        "legs_usable": usable,
        "legs": legs,
        "note": f"{regime} ({composite}) — {detail}" if detail else regime,
        "ts": time.time(),
    }


async def get_intermarket_regime(max_age: int = _CACHE_TTL) -> dict:
    """Cached accessor (30-min TTL). Never raises — returns UNKNOWN on error."""
    c = _CACHE.get("v")
    if c and (time.time() - c["ts"]) < max_age:
        return c
    try:
        r = await compute_intermarket_regime()
    except Exception as e:
        return {"regime": "UNKNOWN", "composite": None, "legs": [],
                "ts": time.time(), "error": repr(e)}
    _CACHE["v"] = r
    return r


__all__ = ["compute_intermarket_regime", "get_intermarket_regime"]
