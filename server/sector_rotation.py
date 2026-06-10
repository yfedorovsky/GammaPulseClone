"""Sector Rotation ranking — cross-sector composite map (#65c).

The "which sectors to be in" context the flow engine lacks: #56 scores per-TICKER
but never ranks SECTORS. AION-inspired sector ranking; here over the 11 SPDR sectors
with 5d/20d momentum + an EMA-trend stack -> a 0-100 composite + a regime label,
ranked best-to-worst. The honest, deeper version of the TrendSpider 1D sector chart
(it shows one day; this shows trend + momentum + a risk regime per sector).

Offline/contextual: daily closes (Tradier) only; never touches scoring/dispatch.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

from .basket import SECTOR_ETFS

_CACHE: dict[str, Any] = {}
_CACHE_TTL = 1800  # 30 min


def _ema(vals: list[float], period: int) -> Optional[float]:
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = (v - e) * k + e
    return e


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _trend_score(closes: list[float]) -> tuple[int, bool]:
    """0-100 EMA-stack trend score (same recipe as conviction_booster) + above-50d."""
    last = closes[-1]
    e8 = _ema(closes, 8) or 0
    e21 = _ema(closes, 21) or 0
    e50 = _ema(closes, 50) or 0
    s = 0
    if last > e8:
        s += 25
    if last > e21:
        s += 25
    if last > e50:
        s += 20
    if e8 > e21:
        s += 15
    if e21 > e50:
        s += 15
    return s, (e50 > 0 and last > e50)


def _regime(ret_5d: float, ret_20d: float, trend: int, above_50: bool) -> str:
    if ret_20d < 0 and ret_5d < 0 and not above_50:
        return "MAX-DEFENSIVE"
    if trend < 40 or ret_20d < 0:
        return "DEFENSIVE"
    if trend >= 80 and ret_20d > 0 and ret_5d > 0:
        return "RISK-ON"
    if trend >= 60 and ret_20d > 0:
        return "CONSTRUCTIVE"
    return "NEUTRAL"


async def _default_fetch(ticker: str, days: int) -> list[float]:
    from .conviction_booster import _fetch_daily_closes
    return await _fetch_daily_closes(ticker, days_back=days)


async def compute_sector_rotation(
    fetch: Optional[Callable[[str, int], Awaitable[list[float]]]] = None,
    days: int = 80,
) -> dict:
    """Rank the 11 SPDR sectors by composite (trend + 20d momentum). `fetch` is
    injectable for tests."""
    fetch = fetch or _default_fetch
    rows: list[dict] = []
    for etf, name in SECTOR_ETFS.items():
        try:
            closes = await fetch(etf, days)
        except Exception:
            closes = []
        if len(closes) < 21:
            rows.append({"etf": etf, "name": name, "regime": "NO_DATA",
                         "composite": None, "ret_5d": None, "ret_20d": None,
                         "trend_score": None, "above_50d": None})
            continue
        last = closes[-1]
        ret_5d = (last / closes[-6] - 1) * 100
        ret_20d = (last / closes[-21] - 1) * 100
        trend, above50 = _trend_score(closes)
        composite = round(0.6 * trend + 0.4 * _clamp(50 + ret_20d * 4, 0, 100), 1)
        rows.append({"etf": etf, "name": name,
                     "ret_5d": round(ret_5d, 2), "ret_20d": round(ret_20d, 2),
                     "trend_score": trend, "above_50d": above50,
                     "composite": composite,
                     "regime": _regime(ret_5d, ret_20d, trend, above50)})

    ranked = sorted((r for r in rows if r["composite"] is not None),
                    key=lambda r: -r["composite"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    nodata = [r for r in rows if r["composite"] is None]
    constructive = sum(1 for r in ranked if r["regime"] in ("RISK-ON", "CONSTRUCTIVE"))

    return {
        "sectors": ranked + nodata,
        "top": ranked[0]["etf"] if ranked else None,
        "bottom": ranked[-1]["etf"] if ranked else None,
        "n_constructive": constructive,
        "n_ranked": len(ranked),
        "ts": time.time(),
    }


async def get_sector_rotation(max_age: int = _CACHE_TTL) -> dict:
    c = _CACHE.get("v")
    if c and (time.time() - c["ts"]) < max_age:
        return c
    try:
        r = await compute_sector_rotation()
    except Exception as e:
        return {"sectors": [], "error": repr(e), "ts": time.time()}
    _CACHE["v"] = r
    return r


__all__ = ["compute_sector_rotation", "get_sector_rotation"]
