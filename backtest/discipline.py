"""Portable discipline layer — 5-factor gate, Kelly sizing, exit ladder, circuit breaker.

No SQLite, no server dependencies. All state is in-memory.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

# ── Base Rate Tiers ────────────────────────────────────────────────────

# OLD payoff ratios from leverage model -- DO NOT USE for Kelly
# PAYOFF_RATIOS = {"PROVEN": 12.0, "DEVELOPING": 4.4, "UNPROVEN": 2.2, "BELOW_FLOOR": 1.0}

# BSM-calibrated default payoff ratios (avg_win / avg_loss)
# These are fallbacks -- actual per-ticker ratios computed from trade log when available
PAYOFF_RATIOS = {"PROVEN": 0.8, "DEVELOPING": 0.6, "UNPROVEN": 0.5, "BELOW_FLOOR": 0.3}
TIER_SIZE_MOD = {"PROVEN": 1.0, "DEVELOPING": 0.75, "UNPROVEN": 0.5, "BELOW_FLOOR": 0.0}
KELLY_BASE_RATE = 0.60  # 60% -- BSM-calibrated A+ base rate (was 23.9% from old model)

MAX_SINGLE = 15.0
MAX_0DTE = 5.0
MAX_CORRELATED = 30.0
MAX_UNPROVEN = 5.0


@dataclass
class TickerStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    pnls: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades * 100) if self.trades > 0 else 0

    @property
    def tier(self) -> str:
        if self.trades >= 10 and self.win_rate >= 50:
            return "PROVEN"
        if self.trades >= 5 and self.win_rate >= 25:
            return "DEVELOPING"
        if self.win_rate < 12 and self.trades >= 5:
            return "BELOW_FLOOR"
        return "UNPROVEN"

    def record(self, pnl_pct: float, won: bool) -> None:
        self.trades += 1
        self.pnls.append(pnl_pct)
        self.total_pnl += pnl_pct
        if won:
            self.wins += 1
        else:
            self.losses += 1


# ── Circuit Breaker ────────────────────────────────────────────────────

@dataclass
class CircuitBreaker:
    consecutive_losses: int = 0
    level: int = 0
    reset_after: datetime.date | None = None

    def record_outcome(self, won: bool) -> None:
        if won:
            self.consecutive_losses = 0
            self.level = 0
            self.reset_after = None
        else:
            self.consecutive_losses += 1
            # Tighter thresholds: with BSM-sized losses (-78% avg),
            # each loss costs ~2-6% of account. Can't afford long streaks.
            if self.consecutive_losses >= 5:
                self.level = 3
                today = datetime.date.today()
                self.reset_after = today + datetime.timedelta(days=(7 - today.weekday()))
            elif self.consecutive_losses >= 3:
                self.level = 2  # half size
            elif self.consecutive_losses >= 2:
                self.level = 1  # reduced (was 3 -- now 2 for BSM-calibrated losses)

    def is_blocked(self) -> bool:
        if self.level >= 3:
            if self.reset_after and datetime.date.today() >= self.reset_after:
                self.level = 0
                self.consecutive_losses = 0
                self.reset_after = None
                return False
            return True
        return False


# ── Kelly Sizing ───────────────────────────────────────────────────────

def kelly_size(
    win_rate: float,
    tier: str,
    is_0dte: bool = False,
    cb_level: int = 0,
    avg_win: float = 0,
    avg_loss: float = 0,
    n_trades: int = 0,
    pooled_win_rate: float | None = None,
    pooled_payoff: float | None = None,
    shrinkage: bool = False,
    clip_inputs: bool = False,
) -> dict[str, Any]:
    """Compute Quarter-Kelly position size using actual BSM payoff ratios.

    Args:
        win_rate: historical win rate as percentage (e.g. 65.3)
        tier: PROVEN / DEVELOPING / UNPROVEN / BELOW_FLOOR
        is_0dte: whether this is a 0DTE trade
        cb_level: circuit breaker level (0-3)
        avg_win: actual average win % from trade log (e.g. 46.3)
        avg_loss: actual average loss % from trade log (e.g. 78.7, positive number)
        n_trades: per-ticker historical trade count (for shrinkage). Defaults to 0.
        pooled_win_rate: pooled win-rate across cohort, percent. Required when
            shrinkage=True.
        pooled_payoff: pooled avg-win/avg-loss ratio across cohort. Required
            when shrinkage=True and avg_win/avg_loss provided.
        shrinkage: apply Bayesian shrinkage to win_rate (Phase 1 #2). Off by
            default for backward compat with existing callers.
        clip_inputs: clip win-rate to [45,65] and payoff to [0.8,2.5] before
            Kelly (Phase 1 #3). Off by default for backward compat.

    Returns: {size_pct, capped_by, kelly_raw, quarter_kelly, debias_reason}
    """
    if tier == "BELOW_FLOOR":
        return {"size_pct": 0, "capped_by": "BELOW_FLOOR", "kelly_raw": 0, "quarter_kelly": 0}

    debias_reason = "raw"

    # Phase 1 #2: Bayesian shrinkage — pull thin-sample ticker rates toward pooled.
    effective_wr = win_rate
    if shrinkage and pooled_win_rate is not None and n_trades > 0:
        from .shrinkage import shrunk_win_rate
        wins = round(win_rate / 100 * n_trades)
        effective_wr = shrunk_win_rate(wins, n_trades, pooled_win_rate)
        debias_reason = f"shrunk(n={n_trades})"

    # Use actual payoff ratio if available, else fallback to tier defaults
    if avg_win > 0 and avg_loss > 0:
        b = avg_win / avg_loss  # actual BSM-calibrated payoff
        if shrinkage and pooled_payoff is not None and n_trades > 0:
            from .shrinkage import shrunk_payoff
            b = shrunk_payoff(avg_win, avg_loss, n_trades, pooled_payoff)
    else:
        b = PAYOFF_RATIOS.get(tier, 0.5)

    # Phase 1 #3: clip inputs to prevent freak rates from blowing up Kelly.
    if clip_inputs:
        from .shrinkage import clip_kelly_inputs
        effective_wr, b, clip_reason = clip_kelly_inputs(effective_wr, b)
        if clip_reason != "OK":
            debias_reason = f"{debias_reason}+clip({clip_reason})"

    p = max(effective_wr / 100, KELLY_BASE_RATE)
    q = 1 - p

    kelly_raw = max(0, (p * b - q) / b)
    quarter_kelly = kelly_raw * 0.25
    size_pct = quarter_kelly * 100 * TIER_SIZE_MOD.get(tier, 0.5)

    # Safety cap when payoff ratio < 1 (losses bigger than wins)
    if b < 1.0 and size_pct > 2.5:
        size_pct = 2.5
        capped_by_reason = f"LOW_PAYOFF_CAP (b={b:.2f})"
    else:
        capped_by_reason = None

    capped_by = capped_by_reason
    if is_0dte and size_pct > MAX_0DTE:
        size_pct = MAX_0DTE
        capped_by = "0DTE_CAP"
    if tier == "UNPROVEN" and size_pct > MAX_UNPROVEN:
        size_pct = MAX_UNPROVEN
        capped_by = "UNPROVEN_CAP"
    if size_pct > MAX_SINGLE:
        size_pct = MAX_SINGLE
        capped_by = "MAX_POSITION_CAP"

    if cb_level >= 3:
        size_pct = 0
        capped_by = "CIRCUIT_BREAKER_STOP"
    elif cb_level >= 2:
        size_pct *= 0.5
        capped_by = f"CIRCUIT_BREAKER_L{cb_level}"
    # Tighter circuit breaker when losses are bigger than wins
    elif cb_level >= 1 and b < 1.0:
        size_pct *= 0.5
        capped_by = f"CB_L{cb_level}_LOW_PAYOFF"

    return {
        "size_pct": round(size_pct, 1),
        "capped_by": capped_by,
        "kelly_raw": round(kelly_raw * 100, 2),
        "quarter_kelly": round(quarter_kelly * 100, 2),
        "debias_reason": debias_reason,
        "effective_win_rate": round(effective_wr, 2),
        "effective_payoff": round(b, 3),
    }


# ── 5-Factor Gate ──────────────────────────────────────────────────────

def five_factor_gate(
    signal: dict[str, Any],
    flow_confirmed: bool | None = None,
    earnings_dates: dict[str, list[str]] | None = None,
    trade_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Evaluate the PLAYBOOK 5-factor entry gate.

    Returns {score, max: 5, label, factors, earnings_blocked}.
    """
    today = trade_date or datetime.date.today()
    ticker = signal.get("ticker", "")
    factors = []
    score = 0.0

    # Factor 1 — Conviction (A+ only — BSM-validated, non-negotiable)
    soe_grade = signal.get("grade", "C")
    if soe_grade == "A+":
        score += 1
        factors.append({"name": "Conviction", "pass": True, "detail": "SOE A+ (BSM-validated edge)"})
    else:
        factors.append({"name": "Conviction", "pass": False, "detail": f"SOE {soe_grade} — low"})

    # Factor 2 — Technical (GEX structure score)
    soe_score = signal.get("score", 0)
    if soe_score >= 5:
        score += 1
        factors.append({"name": "Technical", "pass": True, "detail": f"GEX {soe_score}/8"})
    else:
        factors.append({"name": "Technical", "pass": False, "detail": f"GEX {soe_score}/8 — weak"})

    # Factor 3 — Flow
    if flow_confirmed is True:
        score += 1
        factors.append({"name": "Flow", "pass": True, "detail": "Confirmed"})
    elif flow_confirmed is None:
        score += 0.5
        factors.append({"name": "Flow", "pass": True, "detail": "No data (neutral)"})
    else:
        factors.append({"name": "Flow", "pass": False, "detail": "Opposite"})

    # Factor 4 — Macro (earnings proximity check)
    earnings_blocked = False
    exp_str = signal.get("expiration", "")
    if earnings_dates and ticker in earnings_dates:
        for ed_str in earnings_dates[ticker]:
            try:
                ed = datetime.date.fromisoformat(ed_str)
                if exp_str:
                    exp_date = datetime.date.fromisoformat(exp_str)
                    if -1 <= (ed - exp_date).days <= 0:
                        earnings_blocked = True
                if (ed - today).days == 0 and signal.get("dte", 999) == 0:
                    earnings_blocked = True
            except ValueError:
                pass

    if earnings_blocked:
        factors.append({"name": "Macro", "pass": False, "detail": "TOXIC: earnings proximity"})
    else:
        score += 1
        factors.append({"name": "Macro", "pass": True, "detail": "No event risk"})

    # Factor 5 — Catalyst
    dte = signal.get("dte", 0)
    if dte == 0:
        score += 0.5
        factors.append({"name": "Catalyst", "pass": True, "detail": "0DTE momentum"})
    elif dte >= 7:
        score += 1
        factors.append({"name": "Catalyst", "pass": True, "detail": f"{dte} DTE"})
    else:
        score += 0.5
        factors.append({"name": "Catalyst", "pass": True, "detail": f"{dte} DTE — short"})

    label = "VALID" if score >= 4 else "WEAK" if score >= 3 else "INVALID"
    return {
        "score": round(score, 1),
        "max": 5,
        "label": label,
        "factors": factors,
        "earnings_blocked": earnings_blocked,
    }


# ── Grade-Based Size Modifier ──────────────────────────────────────────
#
# Phase 1 #5 from the cross-LLM synthesis. Two of three LLMs (ChatGPT, Grok)
# explicitly recommended dropping B+ from 2/3 to 1/2 of intended size; the
# third (Perplexity) noted the 3% cap dominates so the dollar difference
# is small but did not object.
#
# Rationale (Grok): half-Kelly logic implies B+ at ~57-58% real win-rate
# is closer to half-size than two-thirds. ~15-20% portfolio variance
# reduction with negligible expectancy hit per Grok backtest claim.
#
# Returns the multiplier applied to intended-full-size (Kelly-derived).
# Use this as a multiplier on top of kelly_size() output, not as a
# replacement for it.

GRADE_SIZE_MULTIPLIER = {
    "A+": 1.0,
    "A":  1.0,
    "B+": 0.5,   # was 0.667 (2/3); cross-LLM consensus dropped to 1/2
    "B":  0.33,  # 1/3 — runner mentality, conviction-light
    "C":  0.0,   # watch-only
    "D":  0.0,   # watch-only
}


def grade_size_modifier(grade: str) -> float:
    """Return the size multiplier for a Layer-3 letter grade.

    Phase 1 #5 update: B+ moved from 0.667 to 0.5.

    Use as: final_size_pct = kelly_size_pct * grade_size_modifier(grade)
    Returns 0 for ineligible grades (C/D and any unknown grade).
    """
    return GRADE_SIZE_MULTIPLIER.get(grade.upper() if grade else "", 0.0)


# ── ATR-Based Hard Stop ────────────────────────────────────────────────
#
# Phase 1 #4 from the cross-LLM synthesis. All three LLMs flagged the legacy
# fixed -9.1% equity stop as instrument-agnostic: for cohort names with
# 4-6% ATR, 9.1% is only ~1.5-2x ATR — within normal noise.
#
# Consensus: drive the equity-side stop off ATR (2.5x default), capped at
# -12% so a temporarily inflated ATR (post-earnings gap) doesn't generate
# an absurd stop. The -50% premium stop on the options leg is unchanged
# (gamma/theta non-linearity validates that one).
#
# Reference: Minervini uses 7-8% below pivot, Qullamaggie uses ~1x ADR/ATR.
# 2.5x ATR is the cross-LLM compromise.

ATR_STOP_MULTIPLE = 2.5
ATR_STOP_CAP_PCT = 12.0  # never wider than -12%


def atr_based_stop(
    entry_price: float,
    atr: float,
    direction: str = "BULL",
    multiple: float = ATR_STOP_MULTIPLE,
    cap_pct: float = ATR_STOP_CAP_PCT,
) -> dict[str, Any]:
    """Compute hard stop price using ATR-multiple, capped at fixed pct.

    Args:
        entry_price: entry price of the underlying.
        atr: current ATR (e.g. ATR(14) on entry day).
        direction: "BULL" (long, stop below) or "BEAR" (short, stop above).
        multiple: ATR multiplier (default 2.5).
        cap_pct: maximum stop distance as percent of entry (default 12.0).

    Returns:
        {
            "stop_price": float,
            "stop_pct": float,        # absolute % from entry, signed by direction
            "atr_distance": float,    # multiple * atr
            "cap_distance": float,    # cap_pct% of entry
            "binding": "ATR" | "CAP", # which one bound
        }
    """
    if entry_price <= 0 or atr <= 0:
        return {
            "stop_price": 0.0,
            "stop_pct": 0.0,
            "atr_distance": 0.0,
            "cap_distance": 0.0,
            "binding": "INVALID",
        }

    atr_distance = multiple * atr
    cap_distance = entry_price * (cap_pct / 100.0)

    if atr_distance <= cap_distance:
        distance = atr_distance
        binding = "ATR"
    else:
        distance = cap_distance
        binding = "CAP"

    if direction.upper() == "BULL":
        stop_price = entry_price - distance
        stop_pct = -100.0 * distance / entry_price
    else:
        stop_price = entry_price + distance
        stop_pct = 100.0 * distance / entry_price

    return {
        "stop_price": round(stop_price, 4),
        "stop_pct": round(stop_pct, 2),
        "atr_distance": round(atr_distance, 4),
        "cap_distance": round(cap_distance, 4),
        "binding": binding,
    }


# ── Exit Ladder ────────────────────────────────────────────────────────

EXIT_LADDER_0DTE = [
    {"gain_pct": 35, "sell_pct": 50, "label": "Sell 50%, stop to breakeven"},
    {"gain_pct": 75, "sell_pct": 75, "label": "Sell 75%, let rest ride"},
]
EXIT_LADDER_MULTI = [
    {"gain_pct": 35, "sell_pct": 25, "label": "Sell 25%, stop to breakeven"},
    {"gain_pct": 75, "sell_pct": 50, "label": "Sell 50%, trail to +35%"},
    {"gain_pct": 125, "sell_pct": 75, "label": "Sell 75%"},
    {"gain_pct": 175, "sell_pct": 100, "label": "Trail at +75%"},
]


def check_exit_ladder(
    entry_spot: float,
    current_spot: float,
    direction: str,
    is_0dte: bool = False,
) -> dict[str, Any] | None:
    """Check if current price triggers an exit ladder level.

    Uses SPOT price movement (not option price) for backtesting simplicity.
    Returns the highest triggered ladder level, or None.
    """
    if entry_spot <= 0:
        return None

    if direction == "BULL":
        gain_pct = ((current_spot - entry_spot) / entry_spot) * 100
    else:
        gain_pct = ((entry_spot - current_spot) / entry_spot) * 100

    # 0DTE hard stop
    if is_0dte and gain_pct <= -50:
        return {"gain_pct": -50, "sell_pct": 100, "label": "0DTE HARD STOP", "triggered": True}

    ladder = EXIT_LADDER_0DTE if is_0dte else EXIT_LADDER_MULTI
    triggered = None
    for level in ladder:
        if gain_pct >= level["gain_pct"]:
            triggered = {**level, "triggered": True, "actual_gain": round(gain_pct, 1)}

    return triggered
