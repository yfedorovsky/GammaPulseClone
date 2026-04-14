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

        # Tier assignment (per ChatGPT: 10 trades not enough for PROVEN, raised to 25)
        if trades >= 25 and wr >= 50:
            tier = "PROVEN"
        elif trades >= 10 and wr >= 25:
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

# Payoff ratios by tier — CALIBRATED from 569 closed MirBot challenge trades
# Generated by calibrate_kelly.py on April 12, 2026
#
# Key findings:
#   - PROVEN (10.75x) has LOWER payoff than DEVELOPING/UNPROVEN — its edge
#     is win rate stability (TSLA 33.3%), not raw payoff magnitude
#   - UNPROVEN (29.67x) is inflated by survivorship bias (AAPL 35x on 18 trades)
#     — the 5% UNPROVEN hard cap is correct and must stay
#   - QQQ: 19 trades, 0% WR — flagged for review, do not Kelly-size QQQ
#   - SPY: 32.53x payoff is tail-driven (few +500% lottery tickets)
#   - DTE bucket calibration pending (contract field needs parsing)
# Per ChatGPT final review: UNPROVEN 29.67 is survivorship bias / outlier inflation.
# Cap UNPROVEN at DEVELOPING level to prevent oversizing on small samples.
PAYOFF_RATIOS = {
    "PROVEN": 10.75,      # n=171, WR=22.2%, avg_win=+242%, avg_loss=-23%
    "DEVELOPING": 17.13,  # n=217, WR=21.2%, avg_win=+266%, avg_loss=-16%
    "UNPROVEN": 17.13,    # CAPPED at DEVELOPING (was 29.67 — outlier inflated)
    "BELOW_FLOOR": 1.0,   # n=16, 12.5% WR — skip recommended
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

    # Win probability from base rate, floored at account-wide 22.8%
    # (calibrated from 569 closed MirBot trades, Apr 2026)
    p = tier_info["win_rate"] / 100
    if p <= 0:
        p = 0.228  # account-wide base rate (569 trades)
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

    # Circuit breaker adjustment (check highest level first)
    cb = get_circuit_breaker()
    if cb["level"] >= 3:
        size_pct = 0
        capped_by = "CIRCUIT_BREAKER_STOP"
    elif cb["level"] >= 2:
        size_pct *= 0.5
        capped_by = f"CIRCUIT_BREAKER_L{cb['level']}"

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
    """Rolling drawdown circuit breaker.

    Uses a 20-trade rolling window instead of simple consecutive losses.
    A single lucky win no longer resets the breaker — you need sustained
    positive expectancy to recover.

    Levels:
      L0: Normal
      L1: Rolling 10-trade WR < 20% — reduce size (soft brake)
      L2: Rolling 10-trade WR < 10% OR weekly drawdown > 5R — half size
      L3: Rolling 10-trade WR = 0% OR weekly drawdown > 8R — full stop
    """
    with _conn() as c:
        # Get last 20 trades
        rows = c.execute(
            "SELECT outcome, pnl_pct, ts FROM trade_log ORDER BY ts DESC LIMIT 20"
        ).fetchall()

        if not rows:
            return {"consecutive_losses": 0, "level": 0, "reset_after": None,
                    "rolling_trades": 0, "rolling_wr": 0, "rolling_expectancy": 0}

        # Rolling 20-trade stats (main health metric per ChatGPT)
        recent_20 = rows[:20]
        wins_20 = sum(1 for r in recent_20 if r["outcome"] == "WIN")
        wr_20 = wins_20 / len(recent_20) * 100 if recent_20 else 0

        # Rolling 10-trade stats (early warning)
        recent_10 = rows[:10]
        wins_10 = sum(1 for r in recent_10 if r["outcome"] == "WIN")
        wr_10 = wins_10 / len(recent_10) * 100 if recent_10 else 0

        # Rolling expectancy (avg P&L across last 20)
        pnls = [r["pnl_pct"] for r in recent_20 if r["pnl_pct"] is not None]
        expectancy = sum(pnls) / len(pnls) if pnls else 0

        # Consecutive losses (still tracked for display)
        consec = 0
        for r in rows:
            if r["outcome"] == "LOSS":
                consec += 1
            else:
                break

        # Weekly drawdown (sum of losses this week)
        import datetime
        week_start = datetime.datetime.now() - datetime.timedelta(days=7)
        week_ts = int(week_start.timestamp())
        week_rows = c.execute(
            "SELECT pnl_pct FROM trade_log WHERE ts > ? AND outcome = 'LOSS'",
            (week_ts,)
        ).fetchall()
        weekly_drawdown = abs(sum(r["pnl_pct"] for r in week_rows if r["pnl_pct"]))

        # Determine level (per ChatGPT: 20-trade main, 10-trade warning, 5-day DD overlay)
        level = 0
        reset_after = None
        warning = None

        # 10-trade early warning
        if len(recent_10) >= 10 and wr_10 < 20:
            warning = f"Early warning: 10-trade WR at {wr_10:.0f}%"

        # L3: full stop
        if len(recent_20) >= 20 and wr_20 == 0:
            level = 3
            today = datetime.date.today()
            next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
            reset_after = next_monday.isoformat()
        elif weekly_drawdown > 800:
            level = 3
            today = datetime.date.today()
            next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
            reset_after = next_monday.isoformat()
        # L2: half size (main 20-trade metric)
        elif (len(recent_20) >= 10 and wr_20 < 10) or weekly_drawdown > 500:
            level = 2
        # L1: soft brake (expectancy negative over 20 trades)
        elif len(recent_20) >= 10 and expectancy < 0:
            level = 1

        return {
            "consecutive_losses": consec,
            "level": level,
            "reset_after": reset_after,
            "warning": warning,
            "rolling_trades_20": len(recent_20),
            "rolling_wr_20": round(wr_20, 1),
            "rolling_trades_10": len(recent_10),
            "rolling_wr_10": round(wr_10, 1),
            "rolling_expectancy": round(expectancy, 1),
            "weekly_drawdown": round(weekly_drawdown, 1),
        }


def _update_circuit_breaker(outcome: str) -> None:
    """No-op — circuit breaker is now computed dynamically from trade_log.
    Kept for backward compatibility with log_trade() calls."""
    pass


def reset_circuit_breaker() -> None:
    """Manual reset — clears the old static breaker table."""
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
        if soe_score >= 5.0:  # 5/6 = 83%, very high conviction in 5-factor system
            return {"allowed": True, "reason": "Chop zone — high score overrides ⚠️", "window": "CHOP_ZONE"}
        return {"allowed": False, "reason": "Chop zone (11:30-1:30) — need max score to enter", "window": "CHOP_ZONE"}
    if minute_of_day < 900:  # 1:30-3:00
        return {"allowed": True, "reason": "Afternoon momentum window ✅", "window": "PM_MOMENTUM"}
    if minute_of_day < 960:  # 3:00-4:00
        return {"allowed": True, "reason": "Power hour — gamma squeezes possible ⚡", "window": "POWER_HOUR"}
    if minute_of_day < 975:  # 4:00-4:15
        return {"allowed": True, "reason": "Final 15 min — high gamma, trade with caution", "window": "CLOSE"}

    return {"allowed": False, "reason": "Market closed", "window": "CLOSED"}


# ── 5-Factor Gate (PLAYBOOK) ───────────────────────────────────────────
#
# SOE 5-factor scoring = WHERE the levels are (signal generator, max 6 pts)
# PLAYBOOK 5-factor gate = WHETHER to take the trade (decision layer)
# Both coexist. A signal can be SOE A+ but fail the gate.

def run_five_factor_gate(
    signal: dict[str, Any],
    flow_confirmed: bool | None = None,
    mir_signal: dict[str, Any] | None = None,
    earnings_dates: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Evaluate the PLAYBOOK 5-factor entry gate.

    Returns {score, max: 5, factors: [...], label, action}.
    SOE score is NOT touched — this is a separate layer.
    """
    import datetime

    ticker = signal.get("ticker", "")
    factors: list[dict[str, Any]] = []
    score = 0

    # Factor 1 — Mir Conviction (or SOE grade as proxy when no Mir signal)
    if mir_signal:
        conv = mir_signal.get("conviction", "LOW")
        if conv == "HIGH":
            score += 1
            factors.append({"name": "Mir Conviction", "pass": True, "detail": f"HIGH — {mir_signal.get('raw', '')[:60]}"})
        elif conv == "MEDIUM":
            score += 1
            factors.append({"name": "Mir Conviction", "pass": True, "detail": "MEDIUM — clean entry"})
        else:
            factors.append({"name": "Mir Conviction", "pass": False, "detail": "LOW — watch only"})
    else:
        # No Mir signal: use SOE grade as proxy (A+/A = pass, B+/B/C = fail)
        soe_grade = signal.get("grade", "C")
        if soe_grade in ("A+", "A"):
            score += 1
            factors.append({"name": "Mir Conviction (SOE proxy)", "pass": True, "detail": f"SOE grade {soe_grade} used as conviction proxy"})
        else:
            factors.append({"name": "Mir Conviction (SOE proxy)", "pass": False, "detail": f"SOE grade {soe_grade} — not high enough to substitute for Mir"})

    # Factor 2 — Technical Setup (GEX structure = dealer-defined S/R)
    # SOE already scored this via 5 independent factors (max 6 pts).
    # Pass if score ≥ 3.75/6 (62.5% = B+ or better).
    soe_score = signal.get("score", 0)
    max_soe = signal.get("max_score", 6)
    if soe_score >= 3.75:
        score += 1
        factors.append({"name": "Technical Setup", "pass": True, "detail": f"GEX structure score {soe_score}/{max_soe} — levels confirmed"})
    else:
        factors.append({"name": "Technical Setup", "pass": False, "detail": f"GEX structure score {soe_score}/{max_soe} — weak setup"})

    # Factor 3 — Options Flow Confirmation
    if flow_confirmed is True:
        score += 1
        factors.append({"name": "Options Flow", "pass": True, "detail": "Unusual volume confirmed direction"})
    elif flow_confirmed is None:
        # No data = NEUTRAL, not fail
        score += 0.5
        factors.append({"name": "Options Flow", "pass": True, "detail": "No flow data — neutral (not disqualifying)"})
    else:
        factors.append({"name": "Options Flow", "pass": False, "detail": "Flow neutral or opposite direction"})

    # Factor 4 — Macro Context (earnings proximity + day-of-week)
    macro_pass = True
    macro_details = []

    # Earnings proximity check (TOXIC LIST RULE)
    if earnings_dates:
        today = datetime.date.today()
        ticker_earnings = earnings_dates.get(ticker.upper(), [])
        for ed_str in ticker_earnings:
            try:
                ed = datetime.date.fromisoformat(ed_str)
                days_to_earnings = (ed - today).days
                exp_str = signal.get("expiration", "")
                if exp_str:
                    try:
                        exp_date = datetime.date.fromisoformat(exp_str)
                        days_exp_to_earnings = (ed - exp_date).days
                        # Toxic: options expiring day of or day before earnings
                        if -1 <= days_exp_to_earnings <= 0:
                            macro_pass = False
                            macro_details.append(f"TOXIC: {ticker} earnings {ed_str}, option expires {exp_str} — IV crush risk")
                    except ValueError:
                        pass
                # Also flag same-day 0DTE into earnings
                if days_to_earnings == 0 and (signal.get("dte") or 999) == 0:
                    macro_pass = False
                    macro_details.append(f"TOXIC: {ticker} earnings TODAY — no 0DTE entries")
            except ValueError:
                pass

    # Day-of-week modifiers
    dow = datetime.date.today().weekday()
    if dow == 4:  # Friday
        macro_details.append("Friday: theta acceleration on 0DTE, be cautious")
    # OPEX week check (3rd Friday of month)
    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    first_friday = first_of_month + datetime.timedelta(days=(4 - first_of_month.weekday()) % 7)
    opex_friday = first_friday + datetime.timedelta(weeks=2)
    if abs((today - opex_friday).days) <= 2:
        macro_details.append("OPEX week — elevated pin risk and gamma")

    if not macro_details:
        macro_details.append("No macro event risk in trade window")

    if macro_pass:
        score += 1
        factors.append({"name": "Macro Context", "pass": True, "detail": "; ".join(macro_details)})
    else:
        factors.append({"name": "Macro Context", "pass": False, "detail": "; ".join(macro_details)})

    # Factor 5 — Catalyst Timing
    # For now: pass if DTE > 3 (multi-week has time for catalyst) or if earnings confirmed as catalyst
    dte = signal.get("dte") or 0
    if dte == 0:
        # 0DTE: momentum is the catalyst
        score += 0.5
        factors.append({"name": "Catalyst Timing", "pass": True, "detail": "0DTE — intraday momentum is the catalyst"})
    elif dte >= 7:
        score += 1
        factors.append({"name": "Catalyst Timing", "pass": True, "detail": f"{dte} DTE — time for catalyst to develop"})
    else:
        score += 0.5
        factors.append({"name": "Catalyst Timing", "pass": True, "detail": f"{dte} DTE — short window, momentum dependent"})

    # Label
    if score >= 4:
        label = "VALID"
        action = "Full Quarter-Kelly size"
    elif score >= 3:
        label = "WEAK"
        action = "Half size — requires user override"
    else:
        label = "INVALID"
        action = "Do not trade — log only"

    # ── Mir Override ─────────────────────────────────────────────
    # Backtest proved: Mir momentum alone = 54.9% WR, +27.5% avg.
    # GEX alone on single stocks = negative EV.
    #
    # Per ChatGPT final review: Mir HIGH may bypass "GEX not ideal"
    # but may NOT bypass:
    #   - stale data (freshness gates)
    #   - spread/contract quality gates
    #   - earnings blackout
    #   - hard circuit breaker state
    #   - catastrophic GEX conflict (score 0 = outright hostile)
    mir_override = False
    if mir_signal:
        mir_conv = mir_signal.get("conviction", "LOW")
        old_label = label

        # Safety gates that Mir cannot override
        can_override = True
        if not macro_pass:  # Earnings blocked
            can_override = False
        cb = get_circuit_breaker()
        if cb.get("level", 0) >= 3:  # Hard breaker
            can_override = False
        if soe_score <= 0:  # Catastrophic GEX conflict (zero structure)
            can_override = False

        if can_override and mir_conv == "HIGH" and label in ("WEAK", "INVALID"):
            mir_override = True
            label = "VALID"
            action = "Mir HIGH override — GEX advisory only"
            factors.append({
                "name": "Mir Override",
                "pass": True,
                "detail": f"Mir HIGH conviction overrides GEX gate (was {old_label}). "
                          f"Freshness/spread/earnings/breaker gates still enforced.",
            })
        elif can_override and mir_conv == "MEDIUM" and label == "INVALID":
            mir_override = True
            label = "WEAK"
            action = "Mir MEDIUM — promoted from INVALID to WEAK"
            factors.append({
                "name": "Mir Override",
                "pass": True,
                "detail": "Mir MEDIUM conviction promotes INVALID to WEAK (half size).",
            })
        elif not can_override and mir_conv == "HIGH":
            factors.append({
                "name": "Mir Override",
                "pass": False,
                "detail": f"Mir HIGH conviction blocked by safety gate "
                          f"({'earnings' if not macro_pass else 'circuit breaker' if cb.get('level',0)>=3 else 'hostile GEX'}).",
            })

    return {
        "score": round(score, 1),
        "max": 5,
        "factors": factors,
        "label": label,
        "action": action,
        "earnings_blocked": not macro_pass,
        "mir_override": mir_override,
    }


# ── 0DTE Power Hour Conditional Rules ──────────────────────────────────

def check_0dte_power_hour(signal: dict[str, Any]) -> dict[str, Any]:
    """Stricter conditions for 3:00-4:15 0DTE entries.

    Power hour is ALLOWED but only for:
    - PROVEN tickers
    - SOE grade A or A+
    - Regime aligned with direction
    """
    tier_info = get_tier(signal.get("ticker", ""))
    soe_grade = signal.get("grade", "C")
    regime = signal.get("regime", "")
    direction = signal.get("direction", "")
    is_bull = direction == "▲"

    conditions = []
    allowed = True

    if tier_info["tier"] != "PROVEN":
        conditions.append(f"Ticker is {tier_info['tier']} — PROVEN required for power hour")
        allowed = False

    if soe_grade not in ("A+", "A"):
        conditions.append(f"SOE grade {soe_grade} — need A or A+ for power hour")
        allowed = False

    regime_aligned = (is_bull and regime == "POS") or (not is_bull and regime == "NEG")
    if not regime_aligned:
        conditions.append(f"Regime {regime} not aligned with {direction} direction")
        allowed = False

    if allowed:
        conditions.append("Power hour conditions met: PROVEN + A grade + regime aligned ✅")

    return {"allowed": allowed, "conditions": conditions}


# ── Enrichment: Add discipline fields to SOE signal ────────────────────

def enrich_signal(
    signal: dict[str, Any],
    account_value: float = 10000,
    flow_confirmed: bool | None = None,
    mir_signal: dict[str, Any] | None = None,
    earnings_dates: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Add discipline layer fields to a raw SOE signal. Non-destructive — only adds keys."""
    ticker = signal.get("ticker", "")
    is_0dte = (signal.get("dte") or 999) == 0
    enriched = dict(signal)

    # Mir signal metadata (if available — fetched by caller)
    if mir_signal:
        enriched["_mir_conviction"] = mir_signal.get("conviction")
        enriched["_mir_channel"] = mir_signal.get("channel")
        enriched["_mir_signal_type"] = mir_signal.get("signal_type")

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

    # 4. 0DTE time gate
    if is_0dte:
        gate = check_0dte_time_gate(signal.get("score", 0))
        enriched["time_gate_allowed"] = gate["allowed"]
        enriched["time_gate_reason"] = gate["reason"]
        enriched["time_gate_window"] = gate["window"]

        # Power hour conditional gates (3:00-4:15)
        if gate.get("window") in ("POWER_HOUR", "CLOSE"):
            ph = check_0dte_power_hour(signal)
            enriched["power_hour_allowed"] = ph["allowed"]
            enriched["power_hour_conditions"] = ph["conditions"]
            if not ph["allowed"]:
                enriched["time_gate_allowed"] = False
                enriched["time_gate_reason"] = "Power hour — " + "; ".join(ph["conditions"])

    # 4b. 0DTE Experimental Mode restrictions
    #   When Greeks freshness is unverified (EXPERIMENTAL), restrict:
    #   - No Kelly sizing (fixed 2% max)
    #   - Grade capped at B+ (cannot be A/A+)
    #   - No Telegram alerts
    dte_0_status = signal.get("_0dte_status")
    if dte_0_status == "EXPERIMENTAL":
        enriched["kelly_size_pct"] = min(enriched.get("kelly_size_pct", 2), 2.0)
        enriched["kelly_capped_by"] = "0DTE_EXPERIMENTAL"
        enriched["kelly_reason"] = "0DTE EXPERIMENTAL — Greeks freshness unverified, fixed 2% max"
        # Cap grade
        if enriched.get("grade") in ("A+", "A"):
            enriched["grade"] = "B+"
            enriched["_grade_capped"] = True
        enriched["_0dte_experimental"] = True
        enriched["_suppress_telegram"] = True
        if enriched.get("reasoning"):
            enriched["reasoning"] += "\n⚠ EXPERIMENTAL: 0DTE Greeks freshness not fully verified"
    elif dte_0_status == "TRADEABLE":
        enriched["_0dte_experimental"] = False

    # 5. Exit ladder
    enriched["exit_ladder"] = EXIT_LADDER_0DTE if is_0dte else EXIT_LADDER_MULTI

    # 6. 5-Factor Gate (PLAYBOOK decision layer)
    gate_result = run_five_factor_gate(
        signal,
        flow_confirmed=flow_confirmed,
        mir_signal=mir_signal,
        earnings_dates=earnings_dates,
    )
    enriched["gate_score"] = gate_result["score"]
    enriched["gate_max"] = gate_result["max"]
    enriched["gate_factors"] = gate_result["factors"]
    enriched["gate_label"] = gate_result["label"]
    enriched["gate_action"] = gate_result["action"]
    enriched["earnings_blocked"] = gate_result.get("earnings_blocked", False)

    # 7. Day-of-week modifier
    import datetime
    dow = datetime.date.today().weekday()
    enriched["day_of_week"] = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dow]
    if dow == 4 and is_0dte:
        enriched["friday_warning"] = "Friday 0DTE: accelerated theta, tight stops"

    # 8. Combined discipline grade
    # SOE grade stays as-is. Discipline grade = min(SOE adjustments, gate outcome)
    soe_grade = signal.get("grade", "C")
    downgrade = {"A+": "A", "A": "B+", "B+": "B", "B": "C", "C": "C"}

    discipline_grade = soe_grade
    discipline_notes: list[str] = []

    if gate_result.get("earnings_blocked"):
        discipline_grade = "SKIP"
        discipline_notes.append("TOXIC: earnings proximity violation")
    elif tier_info["tier"] == "BELOW_FLOOR":
        discipline_grade = "SKIP"
        discipline_notes.append("Below floor base rate — skip or justify")
    elif cb["level"] >= 3:
        discipline_grade = "BLOCKED"
        discipline_notes.append(f"Circuit breaker L3 — no trades until {cb.get('reset_after', 'next week')}")
    elif gate_result["label"] == "INVALID":
        discipline_grade = "SKIP"
        discipline_notes.append(f"5-factor gate: {gate_result['score']}/5 INVALID")
    elif gate_result["label"] == "WEAK":
        discipline_grade = downgrade.get(soe_grade, "C")
        discipline_notes.append(f"5-factor gate: {gate_result['score']}/5 WEAK — half size")
    elif cb["level"] >= 1:
        discipline_grade = downgrade.get(soe_grade, "C")
        discipline_notes.append(f"Circuit breaker L{cb['level']} — grade reduced")

    enriched["discipline_grade"] = discipline_grade
    enriched["discipline_note"] = "; ".join(discipline_notes) if discipline_notes else None

    return enriched


# ── Mir-only Decision (A/B Test Control Book) ────────────────────────
#
# Computes what a Mir-only system (no GEX) would decide.
# Same contract quality gates, same time gates, same Kelly.
# Removes: GEX score threshold, regime filter, king/floor targets.

def compute_mir_only_decision(
    ticker: str,
    direction: str,
    spot: float,
    contract: dict[str, Any] | None,
    mir_signal: dict[str, Any] | None = None,
    is_0dte: bool = False,
    account_value: float = 10_000,
) -> dict[str, Any]:
    """Compute Book B (Mir-only) decision for AB test.

    Returns {would_trade, blocked_by, target, stop, rr_ratio, kelly_pct, gate_label, gate_score}.
    """
    result: dict[str, Any] = {
        "would_trade": 0,
        "blocked_by": None,
        "target": None,
        "stop": None,
        "rr_ratio": None,
        "kelly_pct": 0,
        "gate_label": "INVALID",
        "gate_score": 0,
    }

    # Fixed % targets (no GEX king/floor/ceiling)
    if spot:
        if direction == "BULL":
            result["target"] = round(spot * 1.02, 2)  # +2%
            result["stop"] = round(spot * 0.99, 2)     # -1%
        else:
            result["target"] = round(spot * 0.98, 2)   # -2%
            result["stop"] = round(spot * 1.01, 2)     # +1%
        result["rr_ratio"] = 2.0  # 2% reward / 1% risk = 2.0

    # Simplified 3-factor gate (no GEX)
    gate_score = 0
    factors = []

    # Factor 1: Mir conviction
    conv = (mir_signal or {}).get("conviction", "").upper() if mir_signal else ""
    if conv in ("HIGH", "MEDIUM"):
        gate_score += 1
        factors.append(f"Mir {conv} (+1)")
    else:
        factors.append(f"No Mir conviction (+0)")

    # Factor 2: Time gate (0DTE only)
    if is_0dte:
        tg = check_0dte_time_gate()
        if tg["allowed"]:
            gate_score += 1
            factors.append(f"Time OK: {tg['window']} (+1)")
        else:
            factors.append(f"Time blocked: {tg['reason']} (+0)")
    else:
        gate_score += 1  # Non-0DTE always passes time gate
        factors.append("Non-0DTE time pass (+1)")

    # Factor 3: Contract available
    if contract:
        gate_score += 1
        factors.append("Contract quality OK (+1)")
    else:
        factors.append("No valid contract (+0)")

    result["gate_score"] = gate_score

    if gate_score >= 2:
        result["gate_label"] = "VALID"
    elif gate_score == 1:
        result["gate_label"] = "WEAK"
    else:
        result["gate_label"] = "INVALID"

    # Determine would_trade
    if not mir_signal or conv not in ("HIGH", "MEDIUM"):
        result["blocked_by"] = "no_mir_conviction"
    elif not contract:
        result["blocked_by"] = "no_contract"
    elif is_0dte:
        tg = check_0dte_time_gate()
        if not tg["allowed"]:
            result["blocked_by"] = f"time_gate_{tg['window']}"
        else:
            result["would_trade"] = 1
    else:
        result["would_trade"] = 1

    # Kelly sizing (Mir-based, no GEX modifier)
    if result["would_trade"]:
        kelly = compute_kelly_size(ticker, is_0dte=is_0dte, account_value=account_value)
        # Scale by conviction: HIGH = full, MEDIUM = half
        pct = kelly.get("size_pct", 0)
        if conv == "MEDIUM":
            pct *= 0.5
        result["kelly_pct"] = round(pct, 2)

    return result
