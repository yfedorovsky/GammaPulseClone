"""GEX/VEX math and node classification.

Given a flat list of options contracts from Tradier (calls + puts, across
strikes and expirations), compute per-strike:
  - net_gex  (dollar gamma exposure, calls positive, puts negative)
  - net_vex  (dollar vanna exposure)
  - net_delta (dealer delta exposure proxy)
  - intensity (|net_gex|)
  - node_type: king | gatekeeper | floor | ceiling | normal
  - is_air (very small relative intensity)
  - confluence (top GEX AND top VEX)

Also compute:
  - king, zgl, floor, ceiling strikes
  - gatekeepers (top-6 by intensity excluding the king)
  - pos_gex total, neg_gex total
  - air_pockets list
  - iv (average of at-the-money IV across calls/puts)
  - net_delta total, net_vanna total
  - signal + regime

This implementation is written from scratch using the standard dealer-hedging
GEX model: dealers are assumed short calls and long puts, so positive call
gamma absorbs volatility while positive put gamma (which we flip in sign)
amplifies it. This matches the public convention used by SpotGamma / Menthor Q.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

CONTRACT_SIZE = 100  # shares per contract


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _opt_fields(opt: dict[str, Any], spot: float = 0.0) -> dict[str, float]:
    """Extract the fields we need from a Tradier option quote.

    Tradier does NOT provide vanna directly.  We approximate it from the
    other greeks that *are* available:

        vanna ≈ vega / spot  (first-order approximation from BSM)

    This is the same identity used by most retail GEX dashboards when the
    data provider omits vanna.
    """
    greeks = opt.get("greeks") or {}
    vega = _safe_float(greeks.get("vega"))
    # Approximate vanna from vega/spot if provider doesn't supply it
    raw_vanna = _safe_float(greeks.get("vanna"))
    if raw_vanna == 0.0 and vega != 0.0 and spot > 0:
        raw_vanna = vega / spot
    return {
        "strike": _safe_float(opt.get("strike")),
        "oi": _safe_float(opt.get("open_interest")),
        "volume": _safe_float(opt.get("volume")),
        "bid": _safe_float(opt.get("bid")),
        "ask": _safe_float(opt.get("ask")),
        "last": _safe_float(opt.get("last")),
        "iv": _safe_float(greeks.get("mid_iv") or greeks.get("smv_vol") or greeks.get("bid_iv")),
        "delta": _safe_float(greeks.get("delta")),
        "gamma": _safe_float(greeks.get("gamma")),
        "vanna": raw_vanna,
        "theta": _safe_float(greeks.get("theta")),
        "vega": vega,
    }


def _classify_strike(
    strike: float,
    net_gex: float,
    spot: float,
    king_strike: float,
    floor_strike: float | None,
    ceiling_strike: float | None,
    gatekeeper_set: set[float],
) -> str:
    if strike == king_strike:
        return "king"
    if floor_strike is not None and strike == floor_strike:
        return "floor"
    if ceiling_strike is not None and strike == ceiling_strike:
        return "ceiling"
    if strike in gatekeeper_set:
        return "gatekeeper"
    return "normal"


def _compute_signal(
    spot: float, king: float, king_is_positive: bool, floor: float, ceiling: float
) -> tuple[str, bool]:
    """Return (signal, king_pos_bool)."""
    if spot <= 0 or king <= 0:
        return "PINNING", king_is_positive

    dist_pct = abs(spot - king) / spot

    if dist_pct < 0.003:
        if king_is_positive:
            return "PINNING", True
        return "DANGER", False

    if king_is_positive:
        if king > spot:
            return "MAGNET UP", True
        return "SUPPORT", True

    # king is negative (-GEX)
    if king < spot:
        return "AIR POCKET", False
    return "RESISTANCE", False


def compute_exp_data(
    contracts: list[dict[str, Any]], spot: float
) -> dict[str, Any]:
    """Given a list of Tradier option dicts (for one expiration OR merged across
    many), compute the full expData structure our frontend expects."""
    per_strike: dict[float, dict[str, float]] = defaultdict(
        lambda: {
            "net_gex": 0.0,
            "net_vex": 0.0,
            "net_delta": 0.0,
            "volume": 0.0,
            "oi": 0.0,
            "iv_sum": 0.0,
            "iv_count": 0.0,
        }
    )

    for opt in contracts:
        f = _opt_fields(opt, spot=spot)
        strike = f["strike"]
        if strike <= 0 or f["oi"] <= 0:
            continue
        otype = (opt.get("option_type") or "").lower()
        sign = 1.0 if otype == "call" else -1.0
        # GEX = gamma * OI * 100 * spot^2 * 0.01 (per 1% move), signed by dealer side
        gamma_dollar = (
            f["gamma"] * f["oi"] * CONTRACT_SIZE * spot * spot * 0.01 * sign
        )
        # VEX = vanna * OI * 100 * spot * 1 (per 1 vol point); signed likewise
        vanna_dollar = f["vanna"] * f["oi"] * CONTRACT_SIZE * spot * sign
        # Net delta (dealer hedge)
        delta_shares = f["delta"] * f["oi"] * CONTRACT_SIZE * sign

        bucket = per_strike[strike]
        bucket["net_gex"] += gamma_dollar
        bucket["net_vex"] += vanna_dollar
        bucket["net_delta"] += delta_shares
        bucket["volume"] += f["volume"]
        bucket["oi"] += f["oi"]
        if f["iv"] > 0:
            bucket["iv_sum"] += f["iv"]
            bucket["iv_count"] += 1

    if not per_strike:
        return {
            "strikes": [],
            "king": 0,
            "zgl": 0,
            "iv": 0,
            "net_delta": 0,
            "net_vanna": 0,
            "ceiling": 0,
            "floor": 0,
            "gatekeepers": [],
            "pos_gex": 0,
            "neg_gex": 0,
            "air_pockets": [],
        }

    strikes_sorted = sorted(per_strike.keys())

    # Totals
    total_pos = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] > 0)
    total_neg = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] < 0)
    total_delta = sum(b["net_delta"] for b in per_strike.values())
    total_vanna = sum(b["net_vex"] for b in per_strike.values())

    # Intensity
    max_intensity = max((abs(b["net_gex"]) for b in per_strike.values()), default=1.0) or 1.0

    # King = strike with greatest |net_gex|
    king_strike = max(per_strike.keys(), key=lambda s: abs(per_strike[s]["net_gex"]))
    king_val = per_strike[king_strike]["net_gex"]
    king_is_positive = king_val >= 0

    # Floor = strongest +GEX BELOW spot (excluding king).
    # Ceiling = HIGHEST strike above spot with significant +GEX.
    #
    # Ceiling uses "highest significant" rather than "strongest near spot"
    # because the ceiling represents the upper bound of the expected range —
    # the last strike where dealers provide meaningful resistance via hedging.
    # A strike is "significant" if its +GEX exceeds 3% of king's GEX.
    king_gex_abs = abs(per_strike[king_strike]["net_gex"]) or 1
    significance_threshold = king_gex_abs * 0.03  # 3% of king

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
        elif s > spot and g >= significance_threshold:
            # Track the HIGHEST significant +GEX (not the strongest)
            ceiling_strike = s  # keeps updating to higher strikes

    # Fallbacks if nothing found
    if ceiling_strike is None:
        # Fall back to strongest +GEX above spot
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

    # Zero Gamma Line (ZGL): the structural dividing line between the negative-
    # gamma zone (below) and the positive-gamma zone (above).
    #
    # We use the gamma-weighted center of the negative-GEX zone: the average
    # strike of all negative-GEX positions, weighted by their magnitude.  This
    # is stable across data providers and always lands inside the "danger zone"
    # where dealer hedging amplifies moves.
    #
    # If there's no negative GEX at all, ZGL = lowest relevant strike.
    neg_strikes = [
        (s, abs(per_strike[s]["net_gex"]))
        for s in strikes_sorted
        if per_strike[s]["net_gex"] < 0 and s < spot
    ]
    if neg_strikes:
        wt_sum = sum(s * w for s, w in neg_strikes)
        wt_total = sum(w for _, w in neg_strikes)
        zgl = round(wt_sum / wt_total, 1) if wt_total else strikes_sorted[0]
        # Snap to nearest actual strike
        zgl = min(strikes_sorted, key=lambda s: abs(s - zgl))
    else:
        zgl = strikes_sorted[0]

    # Average ATM IV (use 5 strikes closest to spot that have IV data)
    iv_candidates = [
        (s, per_strike[s])
        for s in strikes_sorted
        if per_strike[s]["iv_count"] > 0
    ]
    iv_candidates.sort(key=lambda pair: abs(pair[0] - spot))
    closest = iv_candidates[:5]
    iv_avg = 0.0
    if closest:
        num = sum(b["iv_sum"] for _, b in closest)
        den = sum(b["iv_count"] for _, b in closest)
        if den > 0:
            iv_avg = (num / den) * 100  # convert from fraction to percent

    # Build strikes list
    strikes_out: list[dict[str, Any]] = []
    air_pockets: list[float] = []
    for s in strikes_sorted:
        b = per_strike[s]
        intensity = abs(b["net_gex"])
        ratio = intensity / max_intensity if max_intensity else 0.0
        node_type = _classify_strike(
            s, b["net_gex"], spot, king_strike, floor_strike, ceiling_strike, gatekeeper_set
        )
        is_air = ratio < 0.02 and node_type == "normal"
        if is_air:
            air_pockets.append(s)
        strikes_out.append(
            {
                "strike": s,
                "net_gex": b["net_gex"],
                "net_vex": b["net_vex"],
                "net_delta": b["net_delta"],
                "node_type": node_type,
                "is_air": is_air,
                "confluence": abs(b["net_gex"]) > 0.5 * max_intensity
                and abs(b["net_vex"]) > 0,
                "intensity": intensity,
                "ratio": ratio,
            }
        )

    return {
        "strikes": strikes_out,
        "king": king_strike,
        "zgl": zgl,
        "iv": iv_avg,
        "net_delta": total_delta,
        "net_vanna": total_vanna,
        "ceiling": ceiling_strike or 0,
        "floor": floor_strike or 0,
        "gatekeepers": sorted(gk),
        "pos_gex": total_pos,
        "neg_gex": total_neg,
        "air_pockets": air_pockets,
        "_king_is_positive": king_is_positive,
    }


def build_signal(exp_data: dict[str, Any], spot: float) -> tuple[str, str, bool]:
    """Return (signal, regime, king_is_positive)."""
    king = exp_data.get("king") or 0
    floor = exp_data.get("floor") or 0
    ceiling = exp_data.get("ceiling") or 0
    king_pos = exp_data.get("_king_is_positive", True)
    pos_gex = exp_data.get("pos_gex") or 0
    neg_gex = exp_data.get("neg_gex") or 0
    # Regime: POS if total positive > |total negative|, otherwise NEG
    regime = "POS" if pos_gex > abs(neg_gex) else "NEG"
    signal, _ = _compute_signal(spot, king, king_pos, floor, ceiling)
    return signal, regime, king_pos


def one_percent_move_dollars(strikes: list[dict[str, Any]]) -> float:
    return sum(s["net_gex"] for s in strikes)
