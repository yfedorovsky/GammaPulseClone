"""VEX (Vanna Exposure) state analyzer for SPX/SPY.

Phase 5. Builds on top of existing per-strike VEX computation in
`server/gex.py:compute_exp_data` (which already aggregates net_vex via
the same pipeline as net_gex). This module adds the higher-level
analysis layer:

  - VEX direction at spot (positive = vol-compression rally fuel)
  - VEX flip level (where cumulative VEX crosses zero)
  - Dominant VEX strikes (by magnitude)
  - GEX-VEX alignment classification

Used by:
  1. macro_pivot_detector G3 — VEX at spot is a 4th confirming signal
     for the contango-flip gate (positive VEX below spot = mechanical
     buy support during vol compression).
  2. macro_context dashboard — surfaces "GEX wall + VEX alignment" read

Per the design constraint (avoid frankenstein):
  - SPX/SPY only. Single-name dealer positioning is less mechanical.
  - Confluence layer with GEX, NOT a standalone scored component.
  - Used as a CONFIRMATION in existing gates, not a new gate.

Vanna semantics (signed):
  net_vex > 0 below spot → dealers BUY when IV drops (vol-compression rally)
  net_vex < 0 below spot → dealers SELL when IV drops (no support)
  net_vex > 0 above spot → dealers SELL when IV drops (resistance to rally)
  net_vex < 0 above spot → dealers BUY when IV drops (rally support)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VEXState:
    ticker: str
    spot: float
    vex_at_spot: float                      # net VEX at the spot strike (or interpolated)
    vex_below_spot: float                   # cumulative net VEX at strikes < spot
    vex_above_spot: float                   # cumulative net VEX at strikes > spot
    vex_flip_strike: float | None           # strike where cumulative VEX crosses zero
    total_vex: float                        # sum across all strikes
    top_pos_vex_strikes: list[tuple]        # (strike, vex) sorted desc
    top_neg_vex_strikes: list[tuple]        # (strike, vex) sorted asc
    direction_below_spot: str               # "BUY_ON_IV_DROP" | "SELL_ON_IV_DROP" | "NEUTRAL"
    direction_above_spot: str               # same labels
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "spot": self.spot,
            "vex_at_spot": round(self.vex_at_spot, 0),
            "vex_below_spot": round(self.vex_below_spot, 0),
            "vex_above_spot": round(self.vex_above_spot, 0),
            "vex_flip_strike": self.vex_flip_strike,
            "total_vex": round(self.total_vex, 0),
            "top_pos_vex_strikes": [(k, round(v, 0)) for k, v in self.top_pos_vex_strikes],
            "top_neg_vex_strikes": [(k, round(v, 0)) for k, v in self.top_neg_vex_strikes],
            "direction_below_spot": self.direction_below_spot,
            "direction_above_spot": self.direction_above_spot,
            "summary": self.summary,
        }


def _classify_vex_direction(vex_value: float, threshold: float = 1e6) -> str:
    """Classify a region's VEX direction relative to dealer flow on IV drop.

    Positive VEX in a region = positive vanna exposure = dealers BUY underlying
    when IV drops (vol-compression rally fuel below spot).
    """
    if abs(vex_value) < threshold:
        return "NEUTRAL"
    if vex_value > 0:
        return "BUY_ON_IV_DROP"
    return "SELL_ON_IV_DROP"


def _find_vex_flip(per_strike: dict[float, dict[str, float]],
                   spot: float) -> float | None:
    """Strike where cumulative VEX (from low to high) crosses zero, near spot."""
    if not per_strike:
        return None
    sorted_strikes = sorted(per_strike.keys())
    cum = 0.0
    prev_cum = 0.0
    prev_strike = sorted_strikes[0]
    for s in sorted_strikes:
        v = per_strike[s].get("net_vex", 0.0)
        prev_cum = cum
        cum += v
        if prev_cum * cum < 0:  # sign flip
            # Linear interp between prev_strike and s
            denom = abs(prev_cum) + abs(cum)
            if denom > 0:
                fraction = abs(prev_cum) / denom
                return round(prev_strike + fraction * (s - prev_strike), 2)
            return s
        prev_strike = s
    return None


def analyze_vex(per_strike: dict[float, dict[str, float]],
                spot: float, ticker: str) -> VEXState:
    """Build a VEXState from per-strike net_vex data.

    Args:
        per_strike: dict mapping strike → {net_vex, ...} (from compute_exp_data)
        spot: current underlying spot price
        ticker: symbol label

    Returns: VEXState with directional analysis.
    """
    if not per_strike or spot <= 0:
        return VEXState(
            ticker=ticker, spot=spot,
            vex_at_spot=0, vex_below_spot=0, vex_above_spot=0,
            vex_flip_strike=None, total_vex=0,
            top_pos_vex_strikes=[], top_neg_vex_strikes=[],
            direction_below_spot="NEUTRAL", direction_above_spot="NEUTRAL",
            summary="no per-strike VEX data",
        )

    # Find the strike closest to spot, take its VEX as "at spot"
    closest = min(per_strike.keys(), key=lambda k: abs(k - spot))
    vex_at_spot = per_strike[closest].get("net_vex", 0.0)

    # Cumulative below/above
    vex_below = sum(b.get("net_vex", 0.0) for s, b in per_strike.items() if s < spot)
    vex_above = sum(b.get("net_vex", 0.0) for s, b in per_strike.items() if s > spot)
    total = vex_below + vex_above + vex_at_spot

    # Top 5 positive / negative strikes
    by_strike = [(s, b.get("net_vex", 0.0)) for s, b in per_strike.items()]
    by_strike_pos = sorted([x for x in by_strike if x[1] > 0],
                            key=lambda x: -x[1])[:5]
    by_strike_neg = sorted([x for x in by_strike if x[1] < 0],
                            key=lambda x: x[1])[:5]

    # Adaptive threshold for "neutral" classification: 5% of |total VEX|
    threshold = max(1e5, abs(total) * 0.05)
    dir_below = _classify_vex_direction(vex_below, threshold)
    dir_above = _classify_vex_direction(vex_above, threshold)

    flip = _find_vex_flip(per_strike, spot)

    # Summary: focus on below-spot (matters for vol-compression rally support)
    if dir_below == "BUY_ON_IV_DROP":
        sub = ("dealers BUY below spot on IV drop "
               "(vol-compression rally fuel)")
    elif dir_below == "SELL_ON_IV_DROP":
        sub = ("dealers SELL below spot on IV drop "
               "(NO mechanical support if VIX falls)")
    else:
        sub = "VEX neutral below spot"

    summary = (f"{ticker} spot ${spot:.2f}, VEX at spot {vex_at_spot/1e6:+.1f}M, "
               f"below {vex_below/1e6:+.1f}M / above {vex_above/1e6:+.1f}M, "
               f"flip {flip} → {sub}")

    return VEXState(
        ticker=ticker, spot=spot,
        vex_at_spot=vex_at_spot,
        vex_below_spot=vex_below,
        vex_above_spot=vex_above,
        vex_flip_strike=flip,
        total_vex=total,
        top_pos_vex_strikes=by_strike_pos,
        top_neg_vex_strikes=by_strike_neg,
        direction_below_spot=dir_below,
        direction_above_spot=dir_above,
        summary=summary,
    )


def gex_vex_alignment(gex_king: float | None, gex_floor: float | None,
                     gex_ceiling: float | None, vex_state: VEXState) -> dict[str, Any]:
    """Compare GEX dominant levels with VEX direction to detect confluence.

    Returns a dict describing whether GEX and VEX agree or diverge.

    Cases:
      - GEX call wall above + VEX-positive above spot
        → ALIGNED RESISTANCE (wall holds because dealers also resist on IV drop)
      - GEX call wall above + VEX-negative above spot
        → DIVERGENT (wall could break if VIX falls; vanna flow unwinds the wall)
      - GEX put wall below + VEX-positive below spot
        → ALIGNED SUPPORT (mechanical buy if vol compresses)
      - GEX put wall below + VEX-negative below spot
        → DIVERGENT (support is fragile; vanna flow could remove it)
    """
    if not vex_state or vex_state.total_vex == 0:
        return {"alignment": "NO_DATA", "reason": "VEX state empty"}

    notes = []
    aligned_count = 0
    divergent_count = 0

    spot = vex_state.spot
    if gex_ceiling and gex_ceiling > spot:
        if vex_state.direction_above_spot == "BUY_ON_IV_DROP":
            notes.append(f"GEX ceiling ${gex_ceiling} + VEX>0 above → "
                         "ALIGNED resistance (wall held by vanna)")
            aligned_count += 1
        elif vex_state.direction_above_spot == "SELL_ON_IV_DROP":
            notes.append(f"GEX ceiling ${gex_ceiling} + VEX<0 above → "
                         "DIVERGENT (wall fragile if VIX drops)")
            divergent_count += 1

    if gex_floor and gex_floor < spot:
        if vex_state.direction_below_spot == "BUY_ON_IV_DROP":
            notes.append(f"GEX floor ${gex_floor} + VEX>0 below → "
                         "ALIGNED support (mechanical buy if vol compresses)")
            aligned_count += 1
        elif vex_state.direction_below_spot == "SELL_ON_IV_DROP":
            notes.append(f"GEX floor ${gex_floor} + VEX<0 below → "
                         "DIVERGENT (support fragile, vanna unwinds it)")
            divergent_count += 1

    if aligned_count > divergent_count:
        alignment = "ALIGNED"
    elif divergent_count > aligned_count:
        alignment = "DIVERGENT"
    elif aligned_count == 0 and divergent_count == 0:
        alignment = "NEUTRAL"
    else:
        alignment = "MIXED"

    return {
        "alignment": alignment,
        "aligned_count": aligned_count,
        "divergent_count": divergent_count,
        "notes": notes,
        "spot": spot,
        "gex_ceiling": gex_ceiling,
        "gex_floor": gex_floor,
        "gex_king": gex_king,
    }


async def get_spy_vex_state() -> dict[str, Any] | None:
    """Convenience: pull SPY's per-strike VEX from the live cache and analyze.

    Reads from the existing cache populated by the live worker (which already
    runs compute_exp_data on each scan cycle). If cache miss, returns None.
    """
    try:
        from .cache import cache
        snap = await cache.snapshot()
        spy_state = snap.get("SPY") or {}
        per_strike = spy_state.get("per_strike") or {}
        spot = spy_state.get("actual_spot") or spy_state.get("_spot") or 0
        if not per_strike or not spot:
            return None
        # Convert per_strike from cache format {strike_str: {...}} to {float: {...}}
        ps = {}
        for k, v in per_strike.items():
            try:
                ps[float(k)] = v
            except (ValueError, TypeError):
                continue
        if not ps:
            return None
        vex_state = analyze_vex(ps, float(spot), "SPY")
        return vex_state.as_dict()
    except Exception as e:
        return {"error": f"vex_state lookup failed: {e}"}


def vex_below_spot_supports_pivot(vex_dict: dict[str, Any] | None) -> bool | None:
    """For macro_pivot G3 confirmation: does VEX support a vol-compression rally?

    Returns:
      True  if VEX-positive below spot (mechanical buy support on IV drop)
      False if VEX-negative below spot (no mechanical support)
      None  if no data
    """
    if not vex_dict or "direction_below_spot" not in vex_dict:
        return None
    return vex_dict["direction_below_spot"] == "BUY_ON_IV_DROP"


if __name__ == "__main__":
    state = asyncio.run(get_spy_vex_state())
    if not state:
        print("No SPY VEX data in cache (live worker may not be running)")
    elif "error" in state:
        print(state["error"])
    else:
        print(f"\nSPY VEX state:")
        for k, v in state.items():
            if k in ("top_pos_vex_strikes", "top_neg_vex_strikes"):
                print(f"  {k}:")
                for s, vex in v[:5]:
                    print(f"    ${s}: {vex/1e6:+.2f}M")
            else:
                print(f"  {k}: {v}")
