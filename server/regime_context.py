"""Unified regime context (v1) — annotate + stamp every flow alert with the macro
backdrop it's firing into.

Aggregates the three #65 regime panels (intermarket gate, breadth omen, sector
rotation) into ONE cached snapshot, and produces a per-alert annotation: the
backdrop + whether it ALIGNS with the alert's direction. v1 ONLY annotates the
Telegram message and stamps a compact string into snapshots.db::flow_alerts so we
can later MEASURE regime-conditioned outcomes. NO gating/suppression — that waits on
the data showing regime-conditioning actually improves flow R (same discipline the
dead-whale verdict forced). alert_outcomes is dead for flow, so we stamp the alive
flow_alerts table instead.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .basket import STOCK_SECTORS

_CACHE: dict[str, Any] = {}
_TTL = 1200  # 20 min — regimes move slowly; this is way off the hot path

# bullishness of each regime state, for the alignment score
_IM_BULL = {"RISK-ON": 1, "NEUTRAL": 0, "RISK-OFF": -1}
_BREADTH_BULL = {"CLEAR": 1, "WATCH": 0, "DANGER": -1}
_SECTOR_BULL = {"RISK-ON": 1, "CONSTRUCTIVE": 1, "NEUTRAL": 0,
                "DEFENSIVE": -1, "MAX-DEFENSIVE": -1}


async def get_regime_context(max_age: int = _TTL) -> dict:
    """Cached aggregate of the 3 regime panels. Never raises; missing panels stay
    None/empty so callers degrade gracefully."""
    c = _CACHE.get("v")
    if c and (time.time() - c["ts"]) < max_age:
        return c
    out: dict[str, Any] = {"intermarket": None, "breadth": None, "sectors": {},
                           "ts": time.time()}
    try:
        from .intermarket_regime import get_intermarket_regime
        out["intermarket"] = await get_intermarket_regime()
    except Exception:
        pass
    try:
        from .breadth_omen import get_breadth_omen
        out["breadth"] = await get_breadth_omen()
    except Exception:
        pass
    try:
        from .sector_rotation import get_sector_rotation
        sr = await get_sector_rotation()
        out["sectors"] = {s["etf"]: s.get("regime")
                          for s in sr.get("sectors", []) if s.get("etf")}
    except Exception:
        pass
    _CACHE["v"] = out
    return out


def cached_regime_ctx() -> dict:
    """Sync, no-fetch accessor — returns the last aggregated snapshot (or empty).
    Lets the per-alert annotate() stay synchronous while an async caller refreshes
    the cache once per scan cycle via get_regime_context()."""
    return _CACHE.get("v") or {}


def annotate(ctx: dict, ticker: str, sentiment: str) -> dict:
    """Per-alert regime annotation. Returns the components + a compact DB stamp
    (`im|breadth|ETF:sector|alignment`) + a short Telegram `banner` line.

    Alignment: does the macro backdrop SUPPORT the alert's direction? A bullish
    alert wants a positive backdrop; a bearish one wants negative. ALIGNED /
    MIXED / COUNTER. Pure context — never suppresses.
    """
    im = (ctx.get("intermarket") or {}).get("regime", "UNKNOWN")
    br = (ctx.get("breadth") or {}).get("posture", "UNKNOWN")
    etf = STOCK_SECTORS.get((ticker or "").upper())
    sec = (ctx.get("sectors") or {}).get(etf, "UNKNOWN") if etf else "UNKNOWN"

    backdrop = (_IM_BULL.get(im, 0) + _BREADTH_BULL.get(br, 0)
                + _SECTOR_BULL.get(sec, 0))  # -3 .. +3
    s = (sentiment or "").upper()
    aligned: Optional[str] = None
    if s in ("BULLISH", "BEARISH"):
        signed = backdrop if s == "BULLISH" else -backdrop
        aligned = "ALIGNED" if signed >= 2 else "COUNTER" if signed <= -2 else "MIXED"

    compact = f"{im}|{br}|{etf or '?'}:{sec}|{aligned or '-'}"
    icon = {"ALIGNED": "✅", "COUNTER": "⚠️"}.get(aligned or "", "🌐")
    sec_str = f" · {etf} {sec}" if etf else ""
    align_str = f" [{aligned}]" if aligned and aligned != "MIXED" else ""
    banner = f"{icon} regime: {im} · breadth {br}{sec_str}{align_str}"
    return {"im": im, "breadth": br, "sector_etf": etf, "sector_regime": sec,
            "aligned": aligned, "backdrop": backdrop,
            "compact": compact, "banner": banner}


__all__ = ["get_regime_context", "annotate"]
