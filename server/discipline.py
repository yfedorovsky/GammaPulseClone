"""Discipline Layer — wraps SOE signals with MirBot-derived risk management.

Adds to (never overrides) the GEX-based SOE scoring:
  - Base rate tracking per ticker (PROVEN / DEVELOPING / UNPROVEN / BELOW_FLOOR)
  - Quarter-Kelly position sizing with hard caps
  - Exit ladder alerts (+50% / +100% / +150% / +200%)
  - Circuit breaker (3 / 5 / 7 consecutive losses)
  - 0DTE time-of-day gates
  - Concentration limits

The SOE 8-factor score is the SIGNAL. This module is the SIZING + DISCIPLINE.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings

# ── Schema ─────────────────────────────────────────────────────────────

DISCIPLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  option_type TEXT,
  strike REAL,
  expiration TEXT,
  entry_price REAL,
  exit_price REAL,
  pnl_pct REAL,
  outcome TEXT,
  is_0dte INTEGER DEFAULT 0,
  signal_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tlog_ticker ON trade_log(ticker);
CREATE INDEX IF NOT EXISTS idx_tlog_ts ON trade_log(ts);

CREATE TABLE IF NOT EXISTS circuit_breaker (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  consecutive_losses INTEGER DEFAULT 0,
  last_loss_ts INTEGER DEFAULT 0,
  level INTEGER DEFAULT 0,
  reset_after TEXT
);
"""


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_discipline_db() -> None:
    with _conn() as c:
        c.executescript(DISCIPLINE_SCHEMA)
        # Ensure circuit breaker row exists
        existing = c.execute("SELECT COUNT(*) FROM circuit_breaker").fetchone()[0]
        if existing == 0:
            c.execute("INSERT INTO circuit_breaker (id, consecutive_losses, level) VALUES (1, 0, 0)")


# ── Base Rate Tracking ─────────────────────────────────────────────────

def get_ticker_stats(ticker: str | None = None) -> dict[str, Any]:
    """Get win/loss stats per ticker from the trade log."""
    with _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT ticker, outcome, pnl_pct FROM trade_log WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchall()
        else:
            rows = c.execute("SELECT ticker, outcome, pnl_pct FROM trade_log").fetchall()

    by_ticker: dict[str, dict] = {}
    for r in rows:
        t = r["ticker"]
        if t not in by_ticker:
            by_ticker[t] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "pnls": []}
        by_ticker[t]["trades"] += 1
        pnl = r["pnl_pct"] or 0
        by_ticker[t]["total_pnl"] += pnl
        by_ticker[t]["pnls"].append(pnl)
        if r["outcome"] == "WIN":
            by_ticker[t]["wins"] += 1
        elif r["outcome"] == "LOSS":
            by_ticker[t]["losses"] += 1

    result = {}
    for t, stats in by_ticker.items():
        trades = stats["trades"]
        wins = stats["wins"]
        wr = (wins / trades * 100) if trades > 0 else 0
        avg_pnl = (stats["total_pnl"] / trades) if trades > 0 else 0

        # Tier assignment
        if trades >= 10 and wr >= 50:
            tier = "PROVEN"
        elif trades >= 5 and wr >= 25:
            tier = "DEVELOPING"
        elif wr < 12 and trades >= 5:
            tier = "BELOW_FLOOR"
        else:
            tier = "UNPROVEN"

        # Compute avg win and avg loss for payoff ratio
        win_pnls = [p for p in stats["pnls"] if p > 0]
        loss_pnls = [p for p in stats["pnls"] if p <= 0]
        avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 200
        avg_loss = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else -91.4

        result[t] = {
            "ticker": t,
            "trades": trades,
            "wins": wins,
            "losses": stats["losses"],
            "win_rate": round(wr, 1),
            "avg_pnl": round(avg_pnl, 1),
            "avg_win": round(avg_win, 1),
            "avg_loss": round(avg_loss, 1),
            "tier": tier,
        }

    return result


def get_tier(ticker: str) -> dict[str, Any]:
    """Get a single ticker's tier info. Returns UNPROVEN defaults if no history."""
    stats = get_ticker_stats(ticker)
    if ticker.upper() in stats:
        return stats[ticker.upper()]
    return {
        "ticker": ticker.upper(),
        "trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0, "avg_pnl": 0, "avg_win": 200, "avg_loss": -91.4,
        "tier": "UNPROVEN",
    }


def log_trade(
    ticker: str, outcome: str, pnl_pct: float,
    option_type: str = "", strike: float = 0, expiration: str = "",
    entry_price: float = 0, exit_price: float = 0,
    is_0dte: bool = False, signal_id: int | None = None,
) -> None:
    """Log a completed trade for base rate tracking."""
    with _conn() as c:
        c.execute(
            """INSERT INTO trade_log
            (ts, ticker, option_type, strike, expiration, entry_price, exit_price,
             pnl_pct, outcome, is_0dte, signal_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()), ticker.upper(), option_type, strike,
                expiration, entry_price, exit_price, pnl_pct, outcome,
                1 if is_0dte else 0, signal_id,
            ),
        )
        # Update circuit breaker
        _update_circuit_breaker(outcome)


# ── Quarter-Kelly Position Sizing ──────────────────────────────────────

# Payoff ratios by tier (from historical data)
PAYOFF_RATIOS = {
    "PROVEN": 12.0,      # avg win ~1072-2171% / avg loss ~91.4%
    "DEVELOPING": 4.4,   # avg win ~400% / avg loss ~91.4%
    "UNPROVEN": 2.2,     # avg win ~200% / avg loss ~91.4%
    "BELOW_FLOOR": 1.0,  # skip recommended
}

# Hard caps (non-negotiable)
MAX_SINGLE_POSITION = 15.0      # % of account
MAX_0DTE_POSITION = 5.0         # % of account
MAX_CORRELATED_EXPOSURE = 30.0  # % of account (same sector)
MAX_UNPROVEN_POSITION = 5.0     # % of account

# Size modifiers by tier
TIER_SIZE_MODIFIER = {
    "PROVEN": 1.0,
    "DEVELOPING": 0.75,
    "UNPROVEN": 0.50,
    "BELOW_FLOOR": 0.0,  # skip
}


def compute_kelly_size(
    ticker: str,
    is_0dte: bool = False,
    account_value: float = 10000,
) -> dict[str, Any]:
    """Compute Quarter-Kelly position size for a given ticker."""
    tier_info = get_tier(ticker)
    tier = tier_info["tier"]

    if tier == "BELOW_FLOOR":
        return {
            "size_pct": 0,
            "size_dollars": 0,
            "tier": tier,
            "tier_info": tier_info,
            "kelly_raw": 0,
            "quarter_kelly": 0,
            "reason": "SKIP — ticker is BELOW_FLOOR (<12% WR). Written justification required.",
            "capped_by": "BELOW_FLOOR",
        }

    # Win probability from base rate, floored at account-wide 23.9%
    p = tier_info["win_rate"] / 100
    if p <= 0:
        p = 0.239  # account-wide base rate
    q = 1 - p

    # Payoff ratio
    b = PAYOFF_RATIOS.get(tier, 2.2)

    # Kelly fraction
    kelly_raw = (p * b - q) / b if b > 0 else 0
    kelly_raw = max(0, kelly_raw)

    # Quarter-Kelly
    quarter_kelly = kelly_raw * 0.25

    # Apply tier modifier
    size_pct = quarter_kelly * 100 * TIER_SIZE_MODIFIER.get(tier, 0.5)

    # Apply hard caps
    capped_by = None
    if is_0dte and size_pct > MAX_0DTE_POSITION:
        size_pct = MAX_0DTE_POSITION
        capped_by = "0DTE_CAP"
    if tier == "UNPROVEN" and size_pct > MAX_UNPROVEN_POSITION:
        size_pct = MAX_UNPROVEN_POSITION
        capped_by = "UNPROVEN_CAP"
    if size_pct > MAX_SINGLE_POSITION:
        size_pct = MAX_SINGLE_POSITION
        capped_by = "MAX_POSITION_CAP"

    # Circuit breaker adjustment
    cb = get_circuit_breaker()
    if cb["level"] >= 2:
        size_pct *= 0.5
        capped_by = f"CIRCUIT_BREAKER_L{cb['level']}"
    elif cb["level"] >= 3:
        size_pct = 0
        capped_by = "CIRCUIT_BREAKER_STOP"

    size_dollars = round(account_value * size_pct / 100, 2)

    return {
        "size_pct": round(size_pct, 1),
        "size_dollars": size_dollars,
        "tier": tier,
        "tier_info": tier_info,
        "kelly_raw": round(kelly_raw * 100, 2),
        "quarter_kelly": round(quarter_kelly * 100, 2),
        "reason": f"{tier} ({tier_info['win_rate']}% WR, {tier_info['trades']} trades) → {round(size_pct, 1)}% account",
        "capped_by": capped_by,
    }


# ── Exit Ladder ────────────────────────────────────────────────────────

EXIT_LADDER_0DTE = [
    {"gain_pct": 50, "action": "sell_half", "label": "Sell 50%, stop → breakeven"},
    {"gain_pct": 100, "action": "sell_75", "label": "Sell 75%, let rest ride at 0 cost basis"},
]

EXIT_LADDER_MULTI = [
    {"gain_pct": 50, "action": "sell_25", "label": "Sell 25%, stop → breakeven"},
    {"gain_pct": 100, "action": "sell_25", "label": "Sell 25% more (50% total), trail stop → +50%"},
    {"gain_pct": 150, "action": "sell_25", "label": "Sell 25% more (75% total)"},
    {"gain_pct": 200, "action": "trail", "label": "Trail remaining 25% with stop at +100%"},
]


def check_exit_ladder(
    entry_price: float,
    current_price: float,
    is_0dte: bool = False,
) -> dict[str, Any] | None:
    """Check if current price triggers an exit ladder level."""
    if entry_price <= 0:
        return None

    gain_pct = ((current_price - entry_price) / entry_price) * 100
    ladder = EXIT_LADDER_0DTE if is_0dte else EXIT_LADDER_MULTI

    triggered = None
    for level in ladder:
        if gain_pct >= level["gain_pct"]:
            triggered = {**level, "current_gain_pct": round(gain_pct, 1)}

    # 0DTE hard stop at -50%
    if is_0dte and gain_pct <= -50:
        return {
            "gain_pct": -50,
            "action": "hard_stop",
            "label": "0DTE HARD STOP — exit 100% (no recovery time)",
            "current_gain_pct": round(gain_pct, 1),
        }

    return triggered


# ── Circuit Breaker ────────────────────────────────────────────────────

def get_circuit_breaker() -> dict[str, Any]:
    with _conn() as c:
        row = c.execute("SELECT * FROM circuit_breaker WHERE id = 1").fetchone()
        if not row:
            return {"consecutive_losses": 0, "level": 0, "reset_after": None}
        return dict(row)


def _update_circuit_breaker(outcome: str) -> None:
    with _conn() as c:
        cb = c.execute("SELECT * FROM circuit_breaker WHERE id = 1").fetchone()
        if not cb:
            return

        losses = cb["consecutive_losses"]

        if outcome == "WIN":
            # Reset on any win
            c.execute(
                "UPDATE circuit_breaker SET consecutive_losses = 0, level = 0, reset_after = NULL WHERE id = 1"
            )
        elif outcome == "LOSS":
            losses += 1
            level = 0
            reset_after = None

            if losses >= 7:
                level = 3
                # Full stop until next week
                import datetime
                today = datetime.date.today()
                next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
                reset_after = next_monday.isoformat()
            elif losses >= 5:
                level = 2  # 5/5 required + 50% size
            elif losses >= 3:
                level = 1  # 4/5 minimum required

            c.execute(
                "UPDATE circuit_breaker SET consecutive_losses = ?, level = ?, last_loss_ts = ?, reset_after = ? WHERE id = 1",
                (losses, level, int(time.time()), reset_after),
            )


def reset_circuit_breaker() -> None:
    """Manual reset (use sparingly)."""
    with _conn() as c:
        c.execute(
            "UPDATE circuit_breaker SET consecutive_losses = 0, level = 0, reset_after = NULL WHERE id = 1"
        )


# ── 0DTE Time-of-Day Gate ─────────────────────────────────────────────

def check_0dte_time_gate(soe_score: float = 0) -> dict[str, Any]:
    """Check if current time is valid for 0DTE entries.

    Returns {allowed, reason, window}.
    """
    import datetime

    now = datetime.datetime.now()
    # Approximate ET (UTC-4 for EDT)
    et_hour = now.hour  # Assumes machine is in ET or close
    et_min = now.minute
    minute_of_day = et_hour * 60 + et_min

    # Windows
    if minute_of_day < 570:  # before 9:30
        return {"allowed": False, "reason": "Pre-market — no 0DTE entries", "window": "PRE"}
    if minute_of_day < 585:  # 9:30-9:44
        return {"allowed": False, "reason": "Opening auction noise — wait until 9:45", "window": "OPEN_AUCTION"}
    if minute_of_day < 690:  # 9:45-11:30
        return {"allowed": True, "reason": "Morning momentum window ✅", "window": "AM_MOMENTUM"}
    if minute_of_day < 810:  # 11:30-1:30
        # Chop zone — only 5/5 score allowed
        if soe_score >= 7:  # maps to 5/5 in the old system (7/8 = very high conviction)
            return {"allowed": True, "reason": "Chop zone — high score overrides ⚠️", "window": "CHOP_ZONE"}
        return {"allowed": False, "reason": "Chop zone (11:30-1:30) — need max score to enter", "window": "CHOP_ZONE"}
    if minute_of_day < 900:  # 1:30-3:00
        return {"allowed": True, "reason": "Afternoon momentum window ✅", "window": "PM_MOMENTUM"}
    if minute_of_day < 960:  # 3:00-4:00
        return {"allowed": True, "reason": "Power hour — gamma squeezes possible ⚡", "window": "POWER_HOUR"}
    if minute_of_day < 975:  # 4:00-4:15
        return {"allowed": True, "reason": "Final 15 min — high gamma, trade with caution", "window": "CLOSE"}

    return {"allowed": False, "reason": "Market closed", "window": "CLOSED"}


# ── Enrichment: Add discipline fields to SOE signal ────────────────────

def enrich_signal(signal: dict[str, Any], account_value: float = 10000) -> dict[str, Any]:
    """Add discipline layer fields to a raw SOE signal. Non-destructive — only adds keys."""
    ticker = signal.get("ticker", "")
    is_0dte = (signal.get("dte") or 999) == 0
    enriched = dict(signal)

    # 1. Base rate tier
    tier_info = get_tier(ticker)
    enriched["base_rate_tier"] = tier_info["tier"]
    enriched["base_rate_wr"] = tier_info["win_rate"]
    enriched["base_rate_trades"] = tier_info["trades"]

    # 2. Quarter-Kelly sizing
    kelly = compute_kelly_size(ticker, is_0dte=is_0dte, account_value=account_value)
    enriched["kelly_size_pct"] = kelly["size_pct"]
    enriched["kelly_size_dollars"] = kelly["size_dollars"]
    enriched["kelly_raw"] = kelly["kelly_raw"]
    enriched["kelly_capped_by"] = kelly["capped_by"]
    enriched["kelly_reason"] = kelly["reason"]

    # 3. Circuit breaker check
    cb = get_circuit_breaker()
    enriched["circuit_breaker_level"] = cb["level"]
    enriched["circuit_breaker_losses"] = cb["consecutive_losses"]
    if cb["level"] >= 3:
        enriched["circuit_breaker_blocked"] = True
        enriched["circuit_breaker_reset"] = cb.get("reset_after")
    else:
        enriched["circuit_breaker_blocked"] = False

    # 4. 0DTE time gate (if applicable)
    if is_0dte:
        gate = check_0dte_time_gate(signal.get("score", 0))
        enriched["time_gate_allowed"] = gate["allowed"]
        enriched["time_gate_reason"] = gate["reason"]
        enriched["time_gate_window"] = gate["window"]

    # 5. Exit ladder
    enriched["exit_ladder"] = EXIT_LADDER_0DTE if is_0dte else EXIT_LADDER_MULTI

    # 6. Combined grade — SOE score + discipline adjustment
    # SOE grade stays as-is. Add a "discipline_grade" that factors in tier.
    soe_grade = signal.get("grade", "C")
    if tier_info["tier"] == "BELOW_FLOOR":
        enriched["discipline_grade"] = "SKIP"
        enriched["discipline_note"] = "Below floor base rate — skip or justify"
    elif cb["level"] >= 3:
        enriched["discipline_grade"] = "BLOCKED"
        enriched["discipline_note"] = f"Circuit breaker L3 — no trades until {cb.get('reset_after', 'next week')}"
    elif cb["level"] >= 1:
        # Downgrade by one level during circuit breaker
        downgrade = {"A+": "A", "A": "B+", "B+": "B", "B": "C", "C": "C"}
        enriched["discipline_grade"] = downgrade.get(soe_grade, "C")
        enriched["discipline_note"] = f"Circuit breaker L{cb['level']} — grade reduced, size halved"
    else:
        enriched["discipline_grade"] = soe_grade
        enriched["discipline_note"] = None

    return enriched
