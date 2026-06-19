"""Detector B — OPEX-pin ARMING gate (the context around Detector A).

Detector A (opex_velocity_detector) fires on a fresh-spot 1-min velocity break,
but a −1.5%/min drop is common on single names as ordinary volatility — only
meaningful when the name is sitting in a tight positive-gamma OPEX pin that can
CASCADE when it breaks (the MRVL 6/18 case). This detector identifies that ARMED
state so A's single-name fires can be qualified: armed + velocity-break = a real
pin-break cascade; un-armed velocity = noise.

ARMING SIGNATURE — derived from the MRVL 6/18 forensic (the final ~25 min before
the 15:50 break, data/mrvl_forensic_20260618.json):
  - OPEX day (holiday-shift aware, via opex_velocity_detector.is_opex_day).
  - net_GEX > 0 — long-gamma / dealer-pinning regime (was +180..+223M into the
    break; net_GEX PEAKS right before the break, so it is a FALSE all-clear — we
    use only its SIGN as the pin-regime gate, never its level as a safety signal).
  - Spot SANDWICHED: a +GEX call wall (ceiling) within ~1.2% above spot AND a
    +GEX floor within ~1.0% below spot. (At 15:25-15:45 MRVL sat at 328 with
    ceiling 330 / floor stepped up to 327.5 — ceil ~0.5% above, floor ~0.2%
    below.) Sandwich generalizes across strike spacings; a fixed band-width does
    not.

DISCIPLINE: this is NECESSARY-NOT-SUFFICIENT CONTEXT, not a predictor. Most armed
pins HOLD — that is what pins do (structure DETECTS, does not PREDICT, per
session-jun18-findings). B never fires an alert on its own; it maintains a silent
armed registry that Detector A consults to qualify single-name velocity breaks.
"""
from __future__ import annotations

import time
from typing import Any

from .opex_velocity_detector import is_opex_day

CEIL_MAX_PCT = 1.2     # call wall must sit within this % ABOVE spot
FLOOR_MAX_PCT = 1.0    # floor must sit within this % BELOW spot
ARM_TTL_S = 600        # an arm is fresh for 10 min (covers the GEX recompute gap)


def evaluate_pin_arm(spot: float, ceiling: float | None, floor: float | None,
                     net_gex: float, is_opex: bool) -> dict[str, Any]:
    """Pure arming evaluation. Returns {armed, reasons, ...metrics}."""
    out: dict[str, Any] = {
        "armed": False, "ceil_dist_pct": None, "floor_dist_pct": None,
        "band_pct": None, "call_wall": ceiling, "floor": floor, "reasons": [],
    }
    if not is_opex:
        out["reasons"].append("not_opex")
        return out
    if not spot or spot <= 0:
        out["reasons"].append("no_spot")
        return out
    if net_gex <= 0:
        out["reasons"].append("not_long_gamma")
        return out
    if not ceiling or not floor:
        out["reasons"].append("missing_wall_or_floor")
        return out

    ceil_dist = (ceiling - spot) / spot * 100
    floor_dist = (spot - floor) / spot * 100
    out["ceil_dist_pct"] = round(ceil_dist, 3)
    out["floor_dist_pct"] = round(floor_dist, 3)
    if ceiling > floor:
        out["band_pct"] = round((ceiling - floor) / spot * 100, 3)

    # Spot must be SANDWICHED: wall close above, floor close below.
    if not (0 < ceil_dist <= CEIL_MAX_PCT):
        out["reasons"].append("wall_not_above_or_too_far")
        return out
    if not (0 <= floor_dist <= FLOOR_MAX_PCT):
        out["reasons"].append("floor_not_below_or_too_far")
        return out

    out["armed"] = True
    out["reasons"].append("sandwiched_long_gamma_opex")
    return out


# ── Armed registry (worker writes at GEX cadence, Detector A reads at 5s) ──

_ARMED: dict[str, tuple[dict, float]] = {}


def arm_from_state(ticker: str, state: dict, now: float | None = None) -> dict:
    """Evaluate arming from a worker GEX `state` and update the registry. Cheap
    no-op off-OPEX. Never raises. Returns the evaluation dict."""
    now = now if now is not None else time.time()
    tk = (ticker or "").upper()
    try:
        is_opex = is_opex_day()
        if not is_opex:
            _ARMED.pop(tk, None)
            return {"armed": False, "reasons": ["not_opex"]}
        spot = state.get("actual_spot") or state.get("_spot") or state.get("spot") or 0
        # net_GEX from the MACRO panel: pos_gex (>=0) + neg_gex (<=0)
        net_gex = (state.get("pos_gex") or 0) + (state.get("neg_gex") or 0)
        res = evaluate_pin_arm(
            spot, state.get("ceiling"), state.get("floor"), net_gex, is_opex)
        if res["armed"]:
            res["spot"] = round(spot, 4)
            _ARMED[tk] = (res, now)
        else:
            _ARMED.pop(tk, None)
        return res
    except Exception:
        return {"armed": False, "reasons": ["error"]}


def is_armed(ticker: str, now: float | None = None) -> bool:
    return armed_details(ticker, now) is not None


def armed_details(ticker: str, now: float | None = None) -> dict | None:
    now = now if now is not None else time.time()
    hit = _ARMED.get((ticker or "").upper())
    if not hit:
        return None
    details, ts = hit
    if now - ts > ARM_TTL_S:
        _ARMED.pop((ticker or "").upper(), None)
        return None
    return details


def armed_tickers(now: float | None = None) -> list[str]:
    return [t for t in list(_ARMED) if is_armed(t, now)]
