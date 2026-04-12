"""SOE 8-Factor Scoring — portable, no server dependencies.

Reproduces the exact scoring from server/signals.py.
Input: GEX state dict (from gex_engine.compute_levels) + confluence data.
Output: score, grade, direction, reasons, contract selection.
"""
from __future__ import annotations

import datetime
from typing import Any


# Grade thresholds (score / 8)
def score_to_grade(score: float, max_score: float = 8.0) -> str:
    pct = score / max_score
    if pct >= 0.9:
        return "A+"
    if pct >= 0.75:
        return "A"
    if pct >= 0.625:
        return "B+"
    if pct >= 0.5:
        return "B"
    return "C"


MIN_SCORE_THRESHOLD = 7.2  # A+ only (was 3.5 / B grade — BSM proved only A+ is profitable)
PARABOLIC_THRESHOLD = 20.0  # 20% gain in 20 days = parabolic
PARABOLIC_MIN_GRADE = "A"   # require A or A+ on parabolic names

# Signal type historical performance (from initial backtest)
# Higher-performing signals get a score boost, underperformers get penalized
SIGNAL_TYPE_MODIFIER = {
    "BREAKDOWN_ACCELERATOR": +0.5,   # 72.4% WR — strong edge
    "PINNING_PREMIUM_SELL": +0.5,    # 68.2% WR — strong edge
    "RESISTANCE_FADE": +0.25,        # high WR (small sample)
    "SUPPORT_BOUNCE": 0.0,           # neutral
    "POST_BOTTOM_LAUNCH": 0.0,       # keep neutral — don't suppress
    "MAGNET_BREAKOUT": -0.25,        # slight penalty, don't kill
    "DIRECTIONAL": 0.0,
}


def is_parabolic(spot_history: list[float] | None = None, threshold: float = PARABOLIC_THRESHOLD) -> bool:
    """Check if a ticker is in parabolic mode (up >20% in last 20 trading days).

    Args:
        spot_history: list of recent closing prices (most recent last), at least 20 entries
        threshold: percentage gain that qualifies as parabolic
    """
    if not spot_history or len(spot_history) < 20:
        return False
    old = spot_history[-20]
    current = spot_history[-1]
    if old <= 0:
        return False
    gain_pct = ((current - old) / old) * 100
    return gain_pct > threshold


def dynamic_pinning_threshold(iv: float) -> float:
    """Dynamic pinning threshold: 0.3% * (IV / 0.25).

    Higher IV = wider pinning zone (volatile stocks need more room).
    At 25% IV -> 0.3% (default). At 50% IV -> 0.6%. At 100% IV -> 1.2%.
    """
    base = 0.003  # 0.3%
    if iv <= 0:
        return base
    return base * (iv / 0.25)


def determine_direction(state: dict[str, Any]) -> str | None:
    """Determine trade direction from GEX structure.

    PINNING excluded: it's a premium-selling structure (iron condors/butterflies),
    NOT a directional single-leg trade. Buying ATM call/put when pinned = theta bleed.
    ChatGPT correctly flagged this as conceptually inconsistent with single-leg only.
    """
    signal = state.get("signal", "")
    if signal in ("AIR POCKET", "RESISTANCE"):
        return "BEAR"
    # BREAKDOWN_ACCELERATOR + RESISTANCE_FADE are the only surviving signals.
    # Everything else killed for cause:
    # MAGNET UP / POST_BOTTOM_LAUNCH / MAGNET_BREAKOUT = weak WR, unproven edge
    # SUPPORT_BOUNCE = 0% WR
    # PINNING = conceptually broken for single-leg (needs spreads)
    # DANGER = too risky
    return None


def determine_signal_type(state: dict[str, Any], direction: str) -> str:
    """Determine the named signal type."""
    signal = state.get("signal", "")
    spot = state.get("spot", 0)
    king = state.get("king", 0)
    king_dist = abs(king - spot) / spot if spot else 0

    if signal == "PINNING":
        return "PINNING_PREMIUM_SELL"
    if signal == "MAGNET UP":
        return "MAGNET_BREAKOUT" if king_dist > 0.02 else "POST_BOTTOM_LAUNCH"
    if signal == "SUPPORT":
        return "SUPPORT_BOUNCE"
    if signal == "AIR POCKET":
        return "BREAKDOWN_ACCELERATOR"
    if signal == "RESISTANCE":
        return "RESISTANCE_FADE"
    return "DIRECTIONAL"


def score_signal(
    state: dict[str, Any],
    direction: str,
    confluence: dict[str, Any] | None = None,
    spot_history: list[float] | None = None,
) -> tuple[float, str, list[str]]:
    """Score a potential signal using the 8-factor SOE system.

    Args:
        state: GEX levels dict from gex_engine.compute_levels()
               Must also contain 'spot' key.
        direction: "BULL" or "BEAR"
        confluence: dict of {SPY: state, QQQ: state, IWM: state} for factor 7
        spot_history: list of recent closing prices for parabolic detection

    Returns: (score, grade, reasons)
    """
    score = 0.0
    reasons: list[str] = []

    king = state.get("king", 0)
    floor_val = state.get("floor", 0)
    ceiling_val = state.get("ceiling", 0)
    zgl = state.get("zgl", 0)
    spot = state.get("spot", 0)
    regime = state.get("regime", "")
    iv = state.get("iv", 0)
    king_is_positive = state.get("king_is_positive", True)
    strikes_list = state.get("strikes", [])

    if not spot or not king:
        return 0, "C", []

    king_dist_pct = abs(king - spot) / spot if spot else 0

    # 1. Regime alignment
    if direction == "BULL" and regime == "POS":
        score += 1
        reasons.append("Positive gamma — dealers buy dips, supporting upside")
    elif direction == "BEAR" and regime == "NEG":
        score += 1
        reasons.append("Negative gamma — dealers amplify moves, confirming downside")

    # 2. King polarity alignment
    if direction == "BULL" and king_is_positive and king > spot:
        score += 1
        reasons.append(f"King ${king} above acts as magnet (+{king_dist_pct*100:.1f}%)")
    elif direction == "BEAR" and not king_is_positive and king < spot:
        score += 1
        reasons.append(f"-GEX King ${king} below = breakdown target (-{king_dist_pct*100:.1f}%)")
    elif direction == "BULL" and king_is_positive and king <= spot:
        score += 0.5
        reasons.append(f"+GEX King ${king} acts as support below")
    elif direction == "BEAR" and not king_is_positive and king >= spot:
        score += 0.5
        reasons.append(f"-GEX King ${king} above = resistance")

    # 3. King distance (0.5-3% sweet spot) with dynamic pinning threshold
    pin_thresh = dynamic_pinning_threshold(iv)
    if 0.005 <= king_dist_pct <= 0.03:
        score += 1
        reasons.append(f"King distance {king_dist_pct*100:.1f}% in sweet spot")
    elif king_dist_pct < pin_thresh:
        score += 0.5

    # 4. Floor/ceiling confirmation
    if direction == "BULL" and floor_val and floor_val < spot:
        score += 1
        reasons.append(f"Floor at ${floor_val} provides support below")
    elif direction == "BEAR" and ceiling_val and ceiling_val > spot:
        score += 1
        reasons.append(f"Ceiling at ${ceiling_val} caps upside")

    # 5. ZGL position
    if zgl:
        if direction == "BULL" and spot > zgl:
            score += 1
            reasons.append("Above ZGL — stable regime supports long positions")
        elif direction == "BEAR" and spot < zgl:
            score += 1
            reasons.append("Below ZGL — volatile regime supports short positions")

    # 6. IV level
    if iv:
        if iv < 0.25:
            score += 1
            reasons.append(f"IV low at {iv*100:.0f}% — options are cheap")
        elif iv < 0.35:
            score += 0.5
            reasons.append(f"IV moderate at {iv*100:.0f}%")

    # 7. Confluence alignment
    if confluence:
        bull_count = 0
        for t in ["SPY", "QQQ", "IWM"]:
            cd = confluence.get(t, {})
            c_king = cd.get("king", 0)
            c_king_pos = cd.get("king_is_positive", True)
            if c_king_pos:
                bull_count += 1
        if direction == "BULL" and bull_count >= 2:
            score += 1
            reasons.append(f"Macro confluence: {bull_count}/3 bullish")
        elif direction == "BEAR" and bull_count <= 1:
            score += 1
            reasons.append(f"Macro confluence: {3 - bull_count}/3 bearish")

    # 8. Call/Put wall alignment
    calls_above = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] > spot]
    puts_below = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] < spot]
    call_wall = max(calls_above, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if calls_above else None
    put_wall = min(puts_below, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if puts_below else None

    if direction == "BULL" and call_wall and call_wall > king:
        score += 1
        reasons.append(f"Call wall at ${call_wall} (+{((call_wall-spot)/spot)*100:.1f}%) = upside runway")
    elif direction == "BEAR" and put_wall and put_wall < king:
        score += 1
        reasons.append(f"Put wall at ${put_wall} (-{((spot-put_wall)/spot)*100:.1f}%) = downside target")

    # 9. Signal-type historical performance modifier
    # Determines signal type to apply the modifier
    signal = state.get("signal", "")
    kd = abs(king - spot) / spot if spot else 0
    if signal == "PINNING":
        sig_type = "PINNING_PREMIUM_SELL"
    elif signal == "MAGNET UP":
        sig_type = "MAGNET_BREAKOUT" if kd > 0.02 else "POST_BOTTOM_LAUNCH"
    elif signal == "SUPPORT":
        sig_type = "SUPPORT_BOUNCE"
    elif signal == "AIR POCKET":
        sig_type = "BREAKDOWN_ACCELERATOR"
    elif signal == "RESISTANCE":
        sig_type = "RESISTANCE_FADE"
    else:
        sig_type = "DIRECTIONAL"

    modifier = SIGNAL_TYPE_MODIFIER.get(sig_type, 0)
    if modifier != 0:
        score += modifier
        if modifier > 0:
            reasons.append(f"Signal type {sig_type} historically strong (+{modifier})")
        else:
            reasons.append(f"Signal type {sig_type} historically weak ({modifier})")

    # 10. Parabolic regime filter
    # On stocks up >20% in 20 days, bullish GEX signals don't add edge — it's just beta.
    # Don't penalize, but don't give extra credit either. Require higher minimum grade.
    parabolic = is_parabolic(spot_history)
    if parabolic:
        if direction == "BULL":
            # Neutral — don't suppress but note the regime
            reasons.append(f"PARABOLIC: ticker up >{PARABOLIC_THRESHOLD:.0f}% in 20d — bullish signal may be beta, not GEX edge")
        else:
            # Counter-trend on a moonshot = dangerous, penalize
            score -= 1.0
            reasons.append(f"PARABOLIC: shorting a >{PARABOLIC_THRESHOLD:.0f}% runner — high risk")

    score = max(0, score)  # don't go below 0
    grade = score_to_grade(score)

    # On parabolic names, enforce minimum grade for entry
    if parabolic and direction == "BULL" and grade not in ("A+", "A"):
        reasons.append(f"PARABOLIC GATE: requires {PARABOLIC_MIN_GRADE}+ grade, got {grade}")
        grade = "C"  # force below threshold so it won't trade

    return score, grade, reasons


def select_contract(
    state: dict[str, Any],
    direction: str,
    available_expirations: list[str],
    trade_date: datetime.date | None = None,
) -> dict[str, Any] | None:
    """Select the optimal contract for the signal.

    Args:
        state: GEX levels dict with 'spot', 'king', 'floor', 'ceiling'
        direction: "BULL" or "BEAR"
        available_expirations: list of "YYYY-MM-DD" strings
        trade_date: the date of the trade (default: today)

    Returns: {strike, expiration, option_type, dte, target, stop, rr_ratio, ...}
    """
    spot = state.get("spot", 0)
    king = state.get("king", 0)
    if not spot:
        return None

    today = trade_date or datetime.date.today()

    # Find expiration 7-28 DTE (sweet spot: 14 DTE)
    target_exp = None
    target_dte = 0

    for exp_str in available_expirations:
        if exp_str.startswith("MACRO"):
            continue
        try:
            exp_date = datetime.date.fromisoformat(exp_str)
            dte = (exp_date - today).days
            if 7 <= dte <= 28:
                if target_exp is None or abs(dte - 14) < abs(target_dte - 14):
                    target_exp = exp_str
                    target_dte = dte
        except ValueError:
            continue

    if not target_exp:
        for exp_str in available_expirations:
            if exp_str.startswith("MACRO"):
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp_str)
                dte = (exp_date - today).days
                if dte >= 3:
                    target_exp = exp_str
                    target_dte = dte
                    break
            except ValueError:
                continue

    if not target_exp:
        return None

    # Detect if this is a PINNING signal — needs different contract logic
    signal = state.get("signal", "")
    is_pinning = signal == "PINNING"

    # Select strike
    otype = "CALL" if direction == "BULL" else "PUT"
    strikes = state.get("strikes", [])

    if is_pinning:
        # PINNING: buy ATM (highest theta capture when price stays pinned)
        # Use the nearest ATM strike for maximum theta decay profit
        atm_candidates = sorted(strikes, key=lambda s: abs(s["strike"] - spot))
        if not atm_candidates:
            return None
        selected = atm_candidates[0]
        strike = selected["strike"]
        # For pinning, direction doesn't matter much — pick call if king above, put if below
        king = state.get("king", spot)
        otype = "CALL" if king >= spot else "PUT"
    else:
        # Standard: slightly OTM directional
        if direction == "BULL":
            candidates = sorted([s for s in strikes if s["strike"] >= spot], key=lambda s: s["strike"])
        else:
            candidates = sorted([s for s in strikes if s["strike"] <= spot], key=lambda s: s["strike"], reverse=True)

        idx = min(2, len(candidates) - 1) if candidates else -1
        if idx < 0:
            return None

        selected = candidates[idx]
        strike = selected["strike"]

    # Targets and stops — IV-derived expected move
    # 1-day expected move = spot * IV * sqrt(1/252)
    # Multi-day EM = spot * IV * sqrt(DTE/252)
    # Stop = 1.5x daily EM (gives room for normal noise)
    # Target = king if >= 2x daily EM, else 2x daily EM
    king = state.get("king", 0)
    iv = state.get("iv", 0) or 0.25  # fallback 25%

    import math
    daily_em = spot * iv * math.sqrt(1 / 252)       # 1-day expected move in $
    daily_em_pct = daily_em / spot                    # as fraction
    hold_em = spot * iv * math.sqrt(max(target_dte, 1) / 252)  # hold-period EM

    if is_pinning:
        # PINNING: range-bound trade. Target is price staying near king (theta profit).
        # Use tight target (0.5x daily EM) and wider stop (floor/ceiling break = pin failed).
        floor = state.get("floor", 0)
        ceiling = state.get("ceiling", 0)
        target = spot + daily_em * 0.3 if otype == "CALL" else spot - daily_em * 0.3
        target_label = f"Pin hold (+/-{daily_em*0.3/spot*100:.1f}%)"
        # Stop = floor or ceiling break (structural level violated = pin broke)
        if floor and ceiling and floor < spot and ceiling > spot:
            stop = floor if otype == "CALL" else ceiling
            stop_label = f"Pin break at ${stop}"
        else:
            stop = spot - daily_em * 2 if otype == "CALL" else spot + daily_em * 2
            stop_label = f"Pin break (2x EM)"

        reward = abs(target - spot)
        risk = abs(stop - spot) or 1
        rr = reward / risk

        return {
            "strike": strike,
            "expiration": target_exp,
            "option_type": otype,
            "dte": target_dte,
            "target": target,
            "target_label": target_label,
            "stop": stop,
            "stop_label": stop_label,
            "rr_ratio": round(rr, 1),
            "is_pinning": True,
        }

    # DIRECTIONAL trades (non-pinning):
    # Minimum target = 1.5x daily EM (reachable within a few days)
    min_target_dist = max(daily_em * 1.5, spot * 0.012)  # at least 1.2%
    # Stop = 2.5x daily EM (wide enough to survive normal intraday noise)
    stop_dist = max(daily_em * 2.5, spot * 0.015)        # at least 1.5%

    if direction == "BULL":
        king_dist_abs = king - spot if king > spot else 0
        if king > spot and king_dist_abs >= min_target_dist:
            target = king
            target_label = f"King ${king} (+{king_dist_abs/spot*100:.1f}%)"
        else:
            target = spot + min_target_dist
            target_label = f"+{min_target_dist/spot*100:.1f}% (2x EM)"

        floor = state.get("floor", 0)
        # Use floor if it's between spot and stop_dist (structural support)
        if floor and (spot - floor) <= stop_dist * 1.2 and floor < spot and floor > spot * 0.95:
            stop = floor
            stop_label = f"Floor ${floor} (-{(spot-floor)/spot*100:.1f}%)"
        else:
            stop = spot - stop_dist
            stop_label = f"-{stop_dist/spot*100:.1f}% (1.5x EM)"
    else:
        king_dist_abs = spot - king if king < spot else 0
        if king < spot and king_dist_abs >= min_target_dist:
            target = king
            target_label = f"King ${king} (-{king_dist_abs/spot*100:.1f}%)"
        else:
            target = spot - min_target_dist
            target_label = f"-{min_target_dist/spot*100:.1f}% (2x EM)"

        ceiling = state.get("ceiling", 0)
        if ceiling and (ceiling - spot) <= stop_dist * 1.2 and ceiling > spot and ceiling < spot * 1.05:
            stop = ceiling
            stop_label = f"Ceiling ${ceiling} (+{(ceiling-spot)/spot*100:.1f}%)"
        else:
            stop = spot + stop_dist
            stop_label = f"+{stop_dist/spot*100:.1f}% (1.5x EM)"

    reward = abs(target - spot)
    risk = abs(stop - spot) or 1
    rr = reward / risk

    return {
        "strike": strike,
        "expiration": target_exp,
        "option_type": otype,
        "dte": target_dte,
        "target": target,
        "target_label": target_label,
        "stop": stop,
        "stop_label": stop_label,
        "rr_ratio": round(rr, 1),
    }
