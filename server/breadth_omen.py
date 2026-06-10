"""Breadth Omen Watch (v1) — CLEAR / WATCH / DANGER crash posture.

The regime context layer's "is the tape internally healthy?" gauge. AION-inspired
(its Breadth Omen Watch); v1 uses the McClellan oscillators (NYMO/NAMO) we already
compute in breadth.py + a price/breadth FRACTURE detector. The fracture is the key
signal the flow engine is blind to and the one that flagged 6/9: the INDEX holding
above trend while BREADTH (McClellan) is negative — narrow leadership rolling over
under a green-looking tape.

v2 (separate task) adds the full Hindenburg Omen (52-week New-High/New-Low), which
needs a 252-day history fetch+cache pipeline we don't yet have.

Severity = count of corroborating internal-deterioration signals:
  NYMO<0 · NAMO<0 · NYMO bearish divergence · price/breadth fracture ·
  VIX backwardation · McClellan deeply negative · McClellan rolling over from high
Posture: DANGER >=4 · WATCH >=2 · CLEAR <2.  Offline/contextual only.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

_CACHE: dict[str, Any] = {}
_CACHE_TTL = 900  # 15 min
_INDEX = "SPY"
_INDEX_MA = 50


def classify_posture(
    *,
    nymo: float,
    namo: float,
    bearish_div: bool,
    turning_down: bool,
    vix_structure: str,
    index_above_trend: Optional[bool],
    has_data: bool,
) -> dict:
    """Pure classifier (testable). Returns posture + severity + reasons."""
    if not has_data:
        return {"posture": "UNKNOWN", "severity": None,
                "reasons": ["breadth history still building"]}

    reasons: list[str] = []
    sev = 0
    nyse_neg = nymo < 0
    nas_neg = namo < 0
    fracture = bool(index_above_trend) and (nyse_neg or nas_neg)

    if nyse_neg:
        sev += 1
        reasons.append(f"NYMO {nymo:.0f} < 0 (NYSE breadth negative)")
    if nas_neg:
        sev += 1
        reasons.append(f"NAMO {namo:.0f} < 0 (NASDAQ breadth negative)")
    if bearish_div:
        sev += 1
        reasons.append("NYMO bearish divergence")
    if fracture:
        sev += 1
        reasons.append("price/breadth FRACTURE — index above trend while breadth negative")
    if vix_structure == "BACKWARDATION":
        sev += 1
        reasons.append("VIX backwardation (fear elevated)")
    if nymo < -50 or namo < -50:
        sev += 1
        reasons.append("McClellan deeply negative (< -50)")
    if turning_down and (nymo > 40 or namo > 40):
        sev += 1
        reasons.append("McClellan rolling over from elevated")

    posture = "DANGER" if sev >= 4 else "WATCH" if sev >= 2 else "CLEAR"
    if not reasons:
        reasons.append(f"breadth healthy (NYMO {nymo:.0f}, NAMO {namo:.0f})")
    return {"posture": posture, "severity": sev, "reasons": reasons,
            "nymo": round(nymo, 1), "namo": round(namo, 1),
            "fracture": fracture, "vix_structure": vix_structure,
            "index_above_trend": (None if index_above_trend is None else bool(index_above_trend))}


def _sma(vals: list[float], period: int) -> Optional[float]:
    return sum(vals[-period:]) / period if len(vals) >= period else None


async def _index_above_trend(
    fetch: Optional[Callable[[str, int], Awaitable[list[float]]]] = None,
) -> Optional[bool]:
    """SPY last close above its 50d SMA? None if data unavailable."""
    if fetch is None:
        from .conviction_booster import _fetch_daily_closes as fetch  # type: ignore
    try:
        closes = await fetch(_INDEX, 100)
    except Exception:
        return None
    ma = _sma(closes, _INDEX_MA)
    if ma is None or not closes:
        return None
    return closes[-1] > ma


async def compute_breadth_omen(
    breadth_ctx: Optional[dict] = None,
    index_above_trend: Optional[bool] = None,
    fetch: Optional[Callable[[str, int], Awaitable[list[float]]]] = None,
) -> dict:
    """Compute the breadth posture. `breadth_ctx`/`index_above_trend` injectable
    for tests; otherwise pulled from breadth.get_breadth_context() + SPY trend."""
    if breadth_ctx is None:
        from .breadth import get_breadth_context
        breadth_ctx = await get_breadth_context()
    if index_above_trend is None:
        index_above_trend = await _index_above_trend(fetch)

    nymo = breadth_ctx.get("nymo", {}) or {}
    namo = breadth_ctx.get("namo", {}) or {}
    vix_ts = breadth_ctx.get("vix_term_structure", {}) or {}
    regime = nymo.get("regime", "NO_DATA")
    has_data = regime not in ("NO_DATA", "INSUFFICIENT_DATA")

    out = classify_posture(
        nymo=float(nymo.get("value", 0) or 0),
        namo=float(namo.get("value", 0) or 0),
        bearish_div=bool(nymo.get("bearish_divergence")),
        turning_down=bool(nymo.get("turning_down") or namo.get("turning_down")),
        vix_structure=vix_ts.get("structure", "NO_DATA"),
        index_above_trend=index_above_trend,
        has_data=has_data,
    )
    out["ts"] = time.time()
    out["note"] = f"{out['posture']}" + (
        f" (sev {out['severity']}) — " + "; ".join(out["reasons"])
        if out.get("severity") is not None else f" — {out['reasons'][0]}")
    return out


async def get_breadth_omen(max_age: int = _CACHE_TTL) -> dict:
    c = _CACHE.get("v")
    if c and (time.time() - c["ts"]) < max_age:
        return c
    try:
        r = await compute_breadth_omen()
    except Exception as e:
        return {"posture": "UNKNOWN", "severity": None, "reasons": [repr(e)],
                "ts": time.time()}
    _CACHE["v"] = r
    return r


__all__ = ["classify_posture", "compute_breadth_omen", "get_breadth_omen"]
