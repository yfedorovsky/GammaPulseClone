"""Unified market read — the bear-day ensemble capstone (AION-teardown roadmap).

Synthesizes the three market-context layers we built into ONE glanceable posture
+ summary line:

  1. STRUCTURE   (#54) — dealer short-gamma tape (mechanical, amplifies down-moves)
  2. BASE-RATE   (#55b) — index analogue forward-return bias (historical frequency)
  3. DIRECTIONAL (#57) — walk-forward forecast P(up) + its honest AUC (benchmark only)

Posture is driven by the two legs with real edge (structure + base-rate); the
directional prior is shown as a calibrated benchmark with its trustworthy flag,
never as a driver (its live AUC ~0.5 = no standalone edge).

The synthesis core is pure (testable); get_market_read() gathers the three from
their warm caches and calls it.
"""
from __future__ import annotations

from typing import Any


def synthesize(
    structure: dict[str, Any], base_rate: dict[str, Any],
    directional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine the three context layers into a posture + one-line summary.

    posture:
      RISK_OFF  — short-gamma tape (structure) OR bearish base-rate dominates
      RISK_ON   — calm/long-gamma tape AND bullish base-rate
      NEUTRAL   — mixed / no decisive context
    """
    s_risk_off = bool(structure.get("risk_off"))
    s_regime = structure.get("regime", "UNKNOWN")
    s_stale = bool(structure.get("stale"))
    br_bias = base_rate.get("bias", "NEUTRAL")
    br_n = base_rate.get("n_patterns", 0)

    if s_risk_off:
        posture = "RISK_OFF"
        why = f"short-gamma index tape ({s_regime})"
    elif br_bias == "BEARISH" and br_n:
        posture = "RISK_OFF"
        why = f"bearish index base-rate (score {base_rate.get('score')})"
    elif br_bias == "BULLISH" and br_n and not s_stale and s_regime in (
            "PINNED", "LEAN_PIN", "NEUTRAL", "UNKNOWN", "INFLECTION"):
        posture = "RISK_ON"
        why = f"bullish base-rate + non-short-gamma tape ({s_regime})"
    else:
        posture = "NEUTRAL"
        why = "mixed context"

    # long-flow advisory: on a RISK_OFF posture, fading bullish flow is the play
    long_flow_note = (
        "down-weight long flow / respect downside" if posture == "RISK_OFF"
        else ("tailwind for long flow" if posture == "RISK_ON" else "no strong tilt")
    )

    d_txt = ""
    if directional and directional.get("ok"):
        trust = "trusted" if directional.get("trustworthy") else "benchmark only"
        d_txt = (f" · fcast P(up {directional.get('horizon')}d) "
                 f"{directional.get('prob_up')}% [{trust}, AUC {directional.get('wf_auc')}]")

    emoji = {"RISK_OFF": "🔴", "RISK_ON": "🟢", "NEUTRAL": "🟡"}[posture]
    summary = f"{emoji} MARKET {posture} — {why}{d_txt}"

    return {
        "posture": posture,
        "summary": summary,
        "long_flow_note": long_flow_note,
        "structure": {"regime": s_regime, "risk_off": s_risk_off,
                      "score": structure.get("score"), "stale": s_stale},
        "base_rate": {"bias": br_bias, "score": base_rate.get("score"),
                      "n_patterns": br_n, "top": base_rate.get("top", [])[:3]},
        "directional": directional or {},
    }


def get_market_read(symbol: str = "SPX") -> dict[str, Any]:
    """Gather the three layers from their caches/loaders and synthesize.
    structure + base-rate are instant (warm caches); directional trains (1h
    cached) — call via asyncio.to_thread from async contexts."""
    from .structure_regime import get_market_structure
    from .analogue_confluence import get_market_bias
    structure = get_market_structure()
    base_rate = get_market_bias()
    directional = None
    try:
        from .directional_prior import get_directional
        directional = get_directional(symbol, 3)
    except Exception:
        directional = None
    out = synthesize(structure, base_rate, directional)
    out["symbol"] = symbol.upper()
    return out
