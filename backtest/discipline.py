"""Portable discipline layer — 5-factor gate, Kelly sizing, exit ladder, circuit breaker.

No SQLite, no server dependencies. All state is in-memory.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

# ── Base Rate Tiers ────────────────────────────────────────────────────

PAYOFF_RATIOS = {"PROVEN": 12.0, "DEVELOPING": 4.4, "UNPROVEN": 2.2, "BELOW_FLOOR": 1.0}
TIER_SIZE_MOD = {"PROVEN": 1.0, "DEVELOPING": 0.75, "UNPROVEN": 0.5, "BELOW_FLOOR": 0.0}
KELLY_BASE_RATE = 0.239  # 23.9% account-wide floor

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
            if self.consecutive_losses >= 7:
                self.level = 3
                today = datetime.date.today()
                self.reset_after = today + datetime.timedelta(days=(7 - today.weekday()))
            elif self.consecutive_losses >= 5:
                self.level = 2
            elif self.consecutive_losses >= 3:
                self.level = 1

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
) -> dict[str, Any]:
    """Compute Quarter-Kelly position size.

    Args:
        win_rate: historical win rate as percentage (e.g. 52.6)
        tier: PROVEN / DEVELOPING / UNPROVEN / BELOW_FLOOR
        is_0dte: whether this is a 0DTE trade
        cb_level: circuit breaker level (0-3)

    Returns: {size_pct, capped_by, kelly_raw, quarter_kelly}
    """
    if tier == "BELOW_FLOOR":
        return {"size_pct": 0, "capped_by": "BELOW_FLOOR", "kelly_raw": 0, "quarter_kelly": 0}

    p = max(win_rate / 100, KELLY_BASE_RATE)
    q = 1 - p
    b = PAYOFF_RATIOS.get(tier, 2.2)

    kelly_raw = max(0, (p * b - q) / b)
    quarter_kelly = kelly_raw * 0.25
    size_pct = quarter_kelly * 100 * TIER_SIZE_MOD.get(tier, 0.5)

    capped_by = None
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

    return {
        "size_pct": round(size_pct, 1),
        "capped_by": capped_by,
        "kelly_raw": round(kelly_raw * 100, 2),
        "quarter_kelly": round(quarter_kelly * 100, 2),
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

    # Factor 1 — Conviction (SOE grade as proxy)
    soe_grade = signal.get("grade", "C")
    if soe_grade in ("A+", "A"):
        score += 1
        factors.append({"name": "Conviction", "pass": True, "detail": f"SOE {soe_grade}"})
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


# ── Exit Ladder ────────────────────────────────────────────────────────

EXIT_LADDER_0DTE = [
    {"gain_pct": 50, "sell_pct": 50, "label": "Sell 50%, stop → breakeven"},
    {"gain_pct": 100, "sell_pct": 75, "label": "Sell 75%, let rest ride"},
]
EXIT_LADDER_MULTI = [
    {"gain_pct": 50, "sell_pct": 25, "label": "Sell 25%, stop → breakeven"},
    {"gain_pct": 100, "sell_pct": 50, "label": "Sell 50%, trail → +50%"},
    {"gain_pct": 150, "sell_pct": 75, "label": "Sell 75%"},
    {"gain_pct": 200, "sell_pct": 100, "label": "Trail at +100%"},
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
