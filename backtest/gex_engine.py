"""Portable GEX math engine — no server, API, or DB dependencies.

Reproduces the exact math from server/gex.py for use in backtesting.

Input: list of option contract dicts with {strike, oi, gamma, delta, vega, option_type}
Output: GEX levels dict with {king, floor, ceiling, zgl, signal, regime, strikes, ...}
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

CONTRACT_SIZE = 100  # shares per contract

# Thresholds (must match server/gex.py)
PINNING_THRESHOLD = 0.003   # 0.3% distance = pinning
SIGNIFICANCE_PCT = 0.03     # 3% of king for ceiling significance
AIR_POCKET_RATIO = 0.02     # <2% intensity = air pocket


def compute_strike_gex(
    gamma: float, oi: float, spot: float, option_type: str
) -> float:
    """GEX for a single contract: gamma * OI * 100 * spot^2 * 0.01 * sign."""
    sign = 1.0 if option_type == "call" else -1.0
    return gamma * oi * CONTRACT_SIZE * spot * spot * 0.01 * sign


def compute_levels(
    contracts: list[dict[str, Any]], spot: float
) -> dict[str, Any]:
    """Compute full GEX level structure from a list of option contracts.

    Each contract dict needs: strike, oi, gamma, delta, vega, option_type
    Optional: iv, vanna, bid, ask, last, volume

    Returns the same structure as server/gex.py compute_exp_data().
    """
    per_strike: dict[float, dict[str, float]] = defaultdict(
        lambda: {
            "net_gex": 0.0, "net_vex": 0.0, "net_delta": 0.0,
            "volume": 0.0, "oi": 0.0, "iv_sum": 0.0, "iv_count": 0.0,
        }
    )

    for opt in contracts:
        strike = float(opt.get("strike", 0))
        oi = float(opt.get("oi") or opt.get("open_interest") or 0)
        if strike <= 0 or oi <= 0:
            continue

        gamma = float(opt.get("gamma", 0))
        delta = float(opt.get("delta", 0))
        vega = float(opt.get("vega", 0))
        iv = float(opt.get("iv") or opt.get("mid_iv") or 0)
        volume = float(opt.get("volume", 0))
        otype = str(opt.get("option_type", "")).lower()
        sign = 1.0 if otype == "call" else -1.0

        # Vanna approximation: vega / spot (BSM first-order)
        vanna = float(opt.get("vanna", 0))
        if vanna == 0 and vega != 0 and spot > 0:
            vanna = vega / spot

        gex = gamma * oi * CONTRACT_SIZE * spot * spot * 0.01 * sign
        vex = vanna * oi * CONTRACT_SIZE * spot * sign
        delta_shares = delta * oi * CONTRACT_SIZE * sign

        b = per_strike[strike]
        b["net_gex"] += gex
        b["net_vex"] += vex
        b["net_delta"] += delta_shares
        b["volume"] += volume
        b["oi"] += oi
        if iv > 0:
            b["iv_sum"] += iv
            b["iv_count"] += 1

    if not per_strike:
        return _empty_result()

    strikes_sorted = sorted(per_strike.keys())

    # Totals
    total_pos = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] > 0)
    total_neg = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] < 0)
    total_delta = sum(b["net_delta"] for b in per_strike.values())
    total_vanna = sum(b["net_vex"] for b in per_strike.values())

    max_intensity = max((abs(b["net_gex"]) for b in per_strike.values()), default=1.0) or 1.0

    # King = strike with greatest |net_gex|
    king_strike = max(per_strike.keys(), key=lambda s: abs(per_strike[s]["net_gex"]))
    king_val = per_strike[king_strike]["net_gex"]
    king_is_positive = king_val >= 0
    king_gex_abs = abs(king_val) or 1

    # Floor = strongest +GEX below spot (excluding king)
    # Ceiling = HIGHEST strike above spot with significant +GEX (≥3% of king)
    significance = king_gex_abs * SIGNIFICANCE_PCT
    floor_strike = None
    ceiling_strike = None
    best_below = 0.0

    for s in strikes_sorted:
        if s == king_strike:
            continue
        g = per_strike[s]["net_gex"]
        if g <= 0:
            continue
        if s < spot and g > best_below:
            best_below = g
            floor_strike = s
        elif s > spot and g >= significance:
            ceiling_strike = s  # keeps updating to the highest significant strike

    # Fallbacks
    if ceiling_strike is None:
        best_above = 0.0
        for s in strikes_sorted:
            if s > spot and s != king_strike and per_strike[s]["net_gex"] > best_above:
                best_above = per_strike[s]["net_gex"]
                ceiling_strike = s
    if floor_strike is None and king_strike < spot:
        for s in sorted(per_strike.keys(), reverse=True):
            if s < spot and s != king_strike and per_strike[s]["net_gex"] > 0:
                floor_strike = s
                break

    # Gatekeepers: top 6 by |net_gex| excluding king
    gk = sorted(
        (s for s in strikes_sorted if s != king_strike),
        key=lambda s: abs(per_strike[s]["net_gex"]),
        reverse=True,
    )[:6]
    gatekeeper_set = set(gk)

    # ZGL: gamma-weighted center of negative-GEX strikes below spot
    neg_strikes = [
        (s, abs(per_strike[s]["net_gex"]))
        for s in strikes_sorted
        if per_strike[s]["net_gex"] < 0 and s < spot
    ]
    if neg_strikes:
        wt_sum = sum(s * w for s, w in neg_strikes)
        wt_total = sum(w for _, w in neg_strikes)
        zgl = round(wt_sum / wt_total, 1) if wt_total else strikes_sorted[0]
        zgl = min(strikes_sorted, key=lambda s: abs(s - zgl))
    else:
        zgl = strikes_sorted[0]

    # Average ATM IV (5 closest strikes with IV data)
    iv_candidates = [
        (s, per_strike[s]) for s in strikes_sorted if per_strike[s]["iv_count"] > 0
    ]
    iv_candidates.sort(key=lambda pair: abs(pair[0] - spot))
    closest = iv_candidates[:5]
    iv_avg = 0.0
    if closest:
        num = sum(b["iv_sum"] for _, b in closest)
        den = sum(b["iv_count"] for _, b in closest)
        if den > 0:
            iv_avg = num / den  # keep as fraction (0.25 = 25%)

    # Regime
    regime = "POS" if total_pos > abs(total_neg) else "NEG"

    # Signal
    signal = compute_signal(spot, king_strike, king_is_positive, floor_strike, ceiling_strike)

    # Build strikes list
    strikes_out = []
    air_pockets = []
    for s in strikes_sorted:
        b = per_strike[s]
        intensity = abs(b["net_gex"])
        ratio = intensity / max_intensity if max_intensity else 0
        node_type = _classify(s, king_strike, floor_strike, ceiling_strike, gatekeeper_set)
        is_air = ratio < AIR_POCKET_RATIO and node_type == "normal"
        if is_air:
            air_pockets.append(s)
        strikes_out.append({
            "strike": s,
            "net_gex": b["net_gex"],
            "net_vex": b["net_vex"],
            "net_delta": b["net_delta"],
            "node_type": node_type,
            "is_air": is_air,
            "confluence": abs(b["net_gex"]) > 0.5 * max_intensity and abs(b["net_vex"]) > 0,
            "intensity": intensity,
            "ratio": ratio,
            "delta": 0,  # per-contract delta not available in aggregate
            "gamma": 0,
        })

    return {
        "strikes": strikes_out,
        "king": king_strike,
        "floor": floor_strike or 0,
        "ceiling": ceiling_strike or 0,
        "zgl": zgl,
        "gatekeepers": sorted(gk),
        "pos_gex": total_pos,
        "neg_gex": total_neg,
        "net_delta": total_delta,
        "net_vanna": total_vanna,
        "iv": iv_avg,
        "regime": regime,
        "signal": signal,
        "king_is_positive": king_is_positive,
        "air_pockets": air_pockets,
        "max_intensity": max_intensity,
    }


def compute_signal(
    spot: float, king: float, king_is_positive: bool,
    floor: float | None, ceiling: float | None,
) -> str:
    """Derive the GEX signal from king position relative to spot."""
    if spot <= 0 or king <= 0:
        return "PINNING"
    dist_pct = abs(spot - king) / spot
    if dist_pct < PINNING_THRESHOLD:
        return "PINNING" if king_is_positive else "DANGER"
    if king_is_positive:
        return "MAGNET UP" if king > spot else "SUPPORT"
    return "AIR POCKET" if king < spot else "RESISTANCE"


def _classify(strike, king, floor, ceiling, gatekeeper_set) -> str:
    if strike == king:
        return "king"
    if floor and strike == floor:
        return "floor"
    if ceiling and strike == ceiling:
        return "ceiling"
    if strike in gatekeeper_set:
        return "gatekeeper"
    return "normal"


def _empty_result() -> dict[str, Any]:
    return {
        "strikes": [], "king": 0, "floor": 0, "ceiling": 0, "zgl": 0,
        "gatekeepers": [], "pos_gex": 0, "neg_gex": 0, "net_delta": 0,
        "net_vanna": 0, "iv": 0, "regime": "POS", "signal": "PINNING",
        "king_is_positive": True, "air_pockets": [], "max_intensity": 0,
    }
