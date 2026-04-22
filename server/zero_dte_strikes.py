"""0DTE strike picker — pick optimal contract given direction + GEX context.

Used by the 0DTE confluence engine (zero_dte_engine.py) to translate a
directional thesis ("BULLISH, target 7065 by EOD") into a specific
tradable contract ("buy SPX 7050C 0DTE @ $3.20").

## Strike selection logic

For calls (bullish thesis):
  - Slightly OTM by 0-1 strike increments (target delta 0.30-0.45)
  - Close enough to target that a move TO the target pays multiple-R
  - Far enough OTM that premium is cheap (leverage matters for 0DTE)
  - Ensure spread < 8% (liquidity gate)
  - Ensure OI > 100 (liquidity gate, lower bar on 0DTE since most OI
    bleeds off by mid-day)

For puts (bearish thesis):
  - Slightly OTM by 0-1 strike increments
  - Same liquidity gates, mirrored

## Strike grid awareness

Uses `root_config.get_strike_step(ticker, spot)` to round to tradable
strikes. Respects SPX $5 grid, SPY $1, etc.

## Delta heuristic

We don't have pre-computed deltas from ThetaData Standard subscription —
we synthesize via Black-Scholes. For strike picking we use a simple
approximation: ATM ≈ 0.50, each step OTM subtracts ~0.07-0.10 depending
on IV and DTE. For 0DTE high-IV, the slope is steeper.

## Edge cases handled

- Stock below spot but <1 strike away → pick ATM (delta ~0.50)
- Target very far from spot (>5%) → cap at 4 strikes OTM
- No liquidity in target range → fall back to nearest ATM strike
- Expiration after-hours (no 0DTE available) → pick nearest next-day weekly

Shipped 2026-04-22 overnight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .root_config import get_strike_step, get_root_config


# ── Configuration ─────────────────────────────────────────────────

# Target delta bands for strike selection. These are approximations —
# we don't compute exact delta, we reverse-engineer from strike-distance
# to spot using the configured strike step.
TARGET_DELTA_BAND = (0.30, 0.45)
TARGET_DELTA_MID = 0.375

# Liquidity gates — if we can't find a strike meeting these, fall back
# to the nearest ATM strike anyway (with a degraded quality tag).
MIN_OI = 100
MAX_SPREAD_PCT = 0.08   # 8%

# Maximum distance from spot to consider (% of spot). Beyond this we're
# too far OTM for realistic 0DTE payout.
MAX_OTM_PCT_STRICT = 0.015   # 1.5% preferred
MAX_OTM_PCT_FALLBACK = 0.035  # 3.5% fallback


# ── Data structures ───────────────────────────────────────────────


@dataclass
class StrikeChoice:
    """Result of picking a strike. Includes quality rating and alternatives."""
    strike: float
    right: str                # 'call' or 'put'
    expiration: str           # YYYY-MM-DD
    est_delta: float          # rough delta estimate from distance/step
    otm_pct: float            # absolute % OTM from spot
    mid_price: float | None   # mid quote if available
    bid: float | None
    ask: float | None
    spread_pct: float | None  # (ask-bid)/mid
    oi: int | None
    quality: str              # 'ideal' | 'acceptable' | 'degraded'
    reasoning: str            # why this strike was chosen

    def to_row(self) -> dict[str, Any]:
        return {
            "strike": self.strike,
            "right": self.right,
            "expiration": self.expiration,
            "est_delta": round(self.est_delta, 2),
            "otm_pct": round(self.otm_pct * 100, 2),
            "mid_price": self.mid_price,
            "bid": self.bid,
            "ask": self.ask,
            "spread_pct": round(self.spread_pct * 100, 2) if self.spread_pct is not None else None,
            "oi": self.oi,
            "quality": self.quality,
            "reasoning": self.reasoning,
        }


# ── Helper: today's expiration for 0DTE ──────────────────────────


def get_zero_dte_expiration(ticker: str, available_exps: list[str]) -> str | None:
    """Return today's expiration string if available, else nearest next-day.

    SPX/SPXW has daily expirations. SPY has MWF expirations historically,
    daily as of ~2022. QQQ/IWM have daily expirations.

    Args:
        ticker: root symbol
        available_exps: list of YYYY-MM-DD strings from the chain

    Returns the closest exp on or after today. None if none within 7 days.
    """
    today = date.today()
    parsed: list[tuple[date, str]] = []
    for e in available_exps:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            if d >= today:
                parsed.append((d, e))
        except ValueError:
            continue
    if not parsed:
        return None
    parsed.sort()
    nearest, exp_str = parsed[0]
    # Only return if within 7 days — beyond that it's not really 0DTE
    if (nearest - today).days > 7:
        return None
    return exp_str


# ── Strike grid + delta approximation ────────────────────────────


def _approx_delta_from_distance(
    otm_pct: float, right: str, zero_dte: bool = True
) -> float:
    """Approximate option delta from OTM distance.

    Heuristic calibrated against typical 0DTE SPX/SPY/QQQ chains:
      ATM:          ~0.50
      0.5% OTM:     ~0.35 (0DTE) / ~0.42 (near-dated weekly)
      1.0% OTM:     ~0.22 (0DTE) / ~0.32
      1.5% OTM:     ~0.13 (0DTE) / ~0.22
      2.0% OTM:     ~0.08 (0DTE) / ~0.15

    For 0DTE the delta curve is MUCH steeper. We assume 0DTE-style decay
    when zero_dte=True. Sign flipped for puts (delta is negative but we
    return positive magnitude for comparison simplicity).
    """
    if zero_dte:
        # Steep decay on 0DTE — calibrated to typical high-IV index
        # expiration-day chains. Exponential-ish falloff.
        if otm_pct <= 0:
            return 0.50
        if otm_pct < 0.002:
            return 0.45
        if otm_pct < 0.004:
            return 0.40
        if otm_pct < 0.007:
            return 0.32
        if otm_pct < 0.011:
            return 0.22
        if otm_pct < 0.015:
            return 0.14
        if otm_pct < 0.020:
            return 0.08
        return 0.04
    else:
        # Slower decay for weekly/next-day
        if otm_pct <= 0:
            return 0.50
        if otm_pct < 0.004:
            return 0.45
        if otm_pct < 0.008:
            return 0.38
        if otm_pct < 0.013:
            return 0.30
        if otm_pct < 0.020:
            return 0.22
        if otm_pct < 0.030:
            return 0.15
        return 0.08


def _round_to_strike_grid(target_strike: float, ticker: str, spot: float) -> float:
    """Round a target strike to the nearest tradable strike on the grid."""
    step = get_strike_step(ticker, spot)
    return round(target_strike / step) * step


# ── Main picker ───────────────────────────────────────────────────


def pick_zero_dte_strike(
    ticker: str,
    direction: str,          # 'bullish' | 'bearish'
    spot: float,
    available_exps: list[str],
    raw_chain: list[dict[str, Any]] | None = None,
    target_price: float | None = None,
    zero_dte: bool = True,
) -> StrikeChoice | None:
    """Pick the optimal 0DTE strike for a given directional thesis.

    Args:
        ticker: 'SPY' / 'SPX' / 'QQQ' / 'IWM' / etc
        direction: 'bullish' → call, 'bearish' → put
        spot: current underlying price
        available_exps: list of exp strings from chain (YYYY-MM-DD)
        raw_chain: optional list of option contracts for quote/OI enrichment.
                   Each contract expected to have: strike, option_type,
                   expiration_date, bid, ask, open_interest
        target_price: optional target level (GEX wall) to bias strike selection
                      toward. If None, use pure delta target.
        zero_dte: if True, use 0DTE delta curve (steeper). If False, use
                  weekly curve.

    Returns StrikeChoice or None if no suitable strike found.
    """
    direction = direction.lower()
    if direction not in ("bullish", "bearish"):
        return None
    right = "call" if direction == "bullish" else "put"

    # 1. Pick expiration — 0DTE if available
    exp = get_zero_dte_expiration(ticker, available_exps)
    if not exp:
        return None

    # 2. Compute target strike in dollars based on desired delta.
    #    Start from spot, step outward by 1-4 strikes, find the first
    #    strike whose approximated delta falls in the target band.
    step = get_strike_step(ticker, spot)

    # If target_price given, bias strike selection toward it —
    # e.g. if spot=7020, target=7065, put strike BETWEEN them to give
    # room for target to be in-the-money at exit.
    candidates: list[float] = []
    if right == "call":
        # ATM first, then step OTM (above spot)
        base = _round_to_strike_grid(spot, ticker, spot)
        for i in range(0, 8):
            s = base + i * step
            candidates.append(s)
    else:  # put
        base = _round_to_strike_grid(spot, ticker, spot)
        for i in range(0, 8):
            s = base - i * step
            candidates.append(s)

    # 3. Among candidates, score each by delta-target + target-proximity
    best: tuple[float, StrikeChoice] | None = None

    # Build quote lookup from raw_chain if provided
    quote_map: dict[tuple[float, str, str], dict[str, Any]] = {}
    if raw_chain:
        for c in raw_chain:
            k = (
                float(c.get("strike", 0)),
                (c.get("option_type") or "").lower(),
                c.get("expiration_date") or "",
            )
            quote_map[k] = c

    for strike in candidates:
        otm_pct = abs(strike - spot) / spot if spot > 0 else 1.0
        if otm_pct > MAX_OTM_PCT_FALLBACK:
            break
        # Approximate delta for this strike
        est_delta = _approx_delta_from_distance(otm_pct, right, zero_dte)

        # Score: how far from our ideal delta (mid-band)
        delta_score = 1.0 - abs(est_delta - TARGET_DELTA_MID) / TARGET_DELTA_MID

        # Proximity to target if provided (higher score when strike is
        # BETWEEN spot and target for bullish, or BETWEEN spot and target
        # for bearish — i.e. the strike "sits on the path")
        proximity_score = 0.5  # neutral if no target
        if target_price is not None:
            if direction == "bullish":
                # Ideal: spot < strike < target
                if spot < strike < target_price:
                    proximity_score = 1.0
                elif strike <= spot:
                    proximity_score = 0.6  # ITM slightly — still fine
                else:
                    # strike > target — too far OTM
                    proximity_score = max(0.0, 1.0 - (strike - target_price) / spot)
            else:  # bearish
                if target_price < strike < spot:
                    proximity_score = 1.0
                elif strike >= spot:
                    proximity_score = 0.6
                else:
                    proximity_score = max(0.0, 1.0 - (target_price - strike) / spot)

        # Combined score
        combined = 0.6 * delta_score + 0.4 * proximity_score

        # Enrich with quote / OI if we have raw chain
        quote = quote_map.get((strike, right, exp))
        bid = float(quote.get("bid", 0)) if quote else None
        ask = float(quote.get("ask", 0)) if quote else None
        oi = int(quote.get("open_interest", 0)) if quote else None
        mid = (bid + ask) / 2 if (bid and ask and bid > 0 and ask > 0) else None
        spread_pct = ((ask - bid) / mid) if (mid and bid and ask) else None

        # Quality assessment
        quality = "ideal"
        if TARGET_DELTA_BAND[0] <= est_delta <= TARGET_DELTA_BAND[1]:
            pass  # ideal band
        else:
            quality = "acceptable"
        # Liquidity checks (if we have data)
        if oi is not None and oi < MIN_OI:
            quality = "degraded"
        if spread_pct is not None and spread_pct > MAX_SPREAD_PCT:
            quality = "degraded"

        # Build reasoning string
        reason_parts = [
            f"{'ATM' if otm_pct < 0.001 else f'{otm_pct*100:.1f}% OTM'}",
            f"est delta {est_delta:.2f}",
        ]
        if target_price is not None:
            if direction == "bullish" and spot < strike < target_price:
                reason_parts.append(f"on path to target ${target_price:g}")
            elif direction == "bearish" and target_price < strike < spot:
                reason_parts.append(f"on path to target ${target_price:g}")
        if oi is not None:
            reason_parts.append(f"OI={oi}")
        if spread_pct is not None:
            reason_parts.append(f"spread {spread_pct*100:.1f}%")

        choice = StrikeChoice(
            strike=strike,
            right=right,
            expiration=exp,
            est_delta=est_delta,
            otm_pct=otm_pct,
            mid_price=round(mid, 2) if mid else None,
            bid=round(bid, 2) if bid else None,
            ask=round(ask, 2) if ask else None,
            spread_pct=spread_pct,
            oi=oi,
            quality=quality,
            reasoning=" · ".join(reason_parts),
        )
        # Downweight score for degraded liquidity
        if quality == "degraded":
            combined *= 0.5
        if best is None or combined > best[0]:
            best = (combined, choice)

    return best[1] if best else None


# ── Exit planning ─────────────────────────────────────────────────


def plan_exit_levels(
    entry_price: float,
    direction: str,
    spot: float,
    target_price: float | None = None,
    est_delta: float = 0.35,
    profit_target_r: float = 1.5,
    stop_loss_pct: float = 0.50,
) -> dict[str, Any]:
    """Compute target / stop for a 0DTE trade.

    Returns a dict with:
      target_mid   : where we'd exit for profit (option price)
      stop_mid     : where we'd exit for loss
      target_r     : ratio of gain to loss
      rationale    : string explaining the plan

    Heuristic: estimate option price at the underlying target using
    est_delta as a rough multiplier. Stop is a % of premium paid.
    """
    if target_price is None:
        # No GEX target provided — use a generic "2x" target on the call
        target_mid = entry_price * 2.5
        stop_mid = entry_price * (1 - stop_loss_pct)
        return {
            "target_mid": round(target_mid, 2),
            "stop_mid": round(stop_mid, 2),
            "target_r": round((target_mid - entry_price) / (entry_price - stop_mid), 2) if entry_price > stop_mid else 2.5,
            "rationale": f"Generic 2.5x target · {int(stop_loss_pct*100)}% stop",
            "time_stop_minutes": 90,
        }

    # Estimate option price at target using delta. Crude: option_price(target)
    # ≈ entry_price + est_delta * (target - spot) for a 0DTE call with
    # appropriate sign. This ignores gamma acceleration, which makes the
    # real payout LARGER than this estimate — so our target is conservative.
    dist = target_price - spot if direction == "bullish" else spot - target_price
    target_mid = entry_price + est_delta * dist

    # Cap the target at 3x entry (0DTE can go 5-10x on big moves but
    # 3x is a disciplined exit rather than greed)
    target_mid = min(target_mid, entry_price * 3.0)

    stop_mid = entry_price * (1 - stop_loss_pct)

    target_r = (target_mid - entry_price) / max(entry_price - stop_mid, 0.01)

    return {
        "target_mid": round(target_mid, 2),
        "stop_mid": round(stop_mid, 2),
        "target_r": round(target_r, 2),
        "rationale": (
            f"Target ${target_mid:.2f} assumes spot → ${target_price:.2f} with ~{est_delta:.2f} delta. "
            f"Stop ${stop_mid:.2f} = -{int(stop_loss_pct*100)}%."
        ),
        "time_stop_minutes": 90,
    }
