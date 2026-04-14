"""Mir's Trading Rulebook — extracted from 23,866 RAG chunks.

Codified from years of @OptionsMir's Discord + Twitter trading history.
Each rule is sourced from specific RAG query results (April 13, 2026).

Usage:
  score = score_mir_pattern(state, contract_dte, conviction, ...)
  Returns a pattern match % and list of rule checks.

This is NOT a replacement for GEX scoring. It answers:
  "Would Mir take this trade based on his historical patterns?"
"""
from __future__ import annotations

import time
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# RULE 1: DTE PREFERENCES (from RAG Query 1)
#
# Source: Feb 14 2025, Dec 26 2023, Apr 8 2025, Jul 17 2024, Dec 12 2025
#
# - 0DTE: "lottos" only, size for zero, quick scalps
# - 1-7 DTE: preferred minimum for day trades / short swings
# - 14-21 DTE: earnings plays, thematic swings
# - 30+ DTE: macro bets, year-end thesis
# - CRITICAL: "size consistently, the moment you go big it gets crushed"
# ═══════════════════════════════════════════════════════════════════════

DTE_RULES = {
    "0DTE_LOTTO": {
        "dte_range": (0, 0),
        "trade_type": "SCALP",
        "sizing": "MINIMAL",  # "size for zero"
        "max_pct": 1.0,  # 1% of account max
        "notes": "Quick hits from open or EOD. Expect to lose premium.",
    },
    "SHORT_SWING": {
        "dte_range": (1, 7),
        "trade_type": "DAY_TRADE",
        "sizing": "STANDARD",
        "max_pct": 3.0,
        "notes": "1DTE minimum preferred over 0DTE for buffer. Scale in/out.",
    },
    "EARNINGS_CATALYST": {
        "dte_range": (14, 21),
        "trade_type": "SWING",
        "sizing": "STANDARD",
        "max_pct": 5.0,
        "notes": "Capture the event + post-event move. 2-3 weeks out.",
    },
    "THEMATIC_SWING": {
        "dte_range": (21, 45),
        "trade_type": "SWING",
        "sizing": "FULL",
        "max_pct": 10.0,
        "notes": "Monthly+ for macro bets and sector themes.",
    },
}

def score_dte_alignment(dte: int, trade_type: str = "SWING") -> tuple[float, str]:
    """Score how well the DTE matches Mir's preferences.
    Returns (score 0-1, reason).
    """
    if dte == 0:
        return 0.5, "0DTE lotto — Mir says 'size for zero, expect to lose premium'"
    if 1 <= dte <= 7:
        if trade_type in ("SCALP", "DAY_TRADE"):
            return 1.0, f"{dte}DTE — Mir's preferred range for short swings (1DTE min for buffer)"
        return 0.7, f"{dte}DTE — short for a swing, better for day trades"
    if 7 < dte <= 14:
        return 0.9, f"{dte}DTE — good sweet spot between swing and catalyst"
    if 14 < dte <= 28:
        return 1.0, f"{dte}DTE — Mir's preferred range for earnings/catalyst plays"
    if 28 < dte <= 45:
        return 0.8, f"{dte}DTE — thematic swing, monthly timeframe"
    if dte > 45:
        return 0.6, f"{dte}DTE — long-dated, Mir prefers these for LEAPS/macro only"
    return 0.5, "Unknown DTE range"


# ═══════════════════════════════════════════════════════════════════════
# RULE 2: TIME OF DAY (from RAG Query 2)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

def score_time_of_day() -> tuple[float, str]:
    """Score current time against Mir's preferred entry windows.

    Source: RAG Query 2 (years of Discord data)
    Key rules:
      - "Wait an hour after the opening bell" (Jan 6, 2023)
      - Three volatility windows: opening (watch only), mid-day (~1:30PM), power hour
      - "Our biggest plays are ones taken in those final minutes when whales enter" (Sep 9, 2024)
      - Give a setup 30 min into a volatility period to start moving, else cut (May 22, 2025)
    """
    import datetime
    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute

    if mins < 570:  # Before 9:30
        return 0.0, "Pre-market — no entries"
    if mins < 630:  # 9:30-10:30
        return 0.2, "AVOID — Mir's rule: 'wait an hour after the opening bell'"
    if 630 <= mins < 690:  # 10:30-11:30
        return 0.7, "Post-open settled — watch for pullback to 15min 20 SMA"
    if 690 <= mins < 810:  # 11:30-1:30
        return 0.4, "Midday chop — Mir advises patience, low probability"
    if 810 <= mins < 840:  # 1:30-2:00
        return 0.9, "Mid-day volatility window — Mir's 2nd key period"
    if 840 <= mins < 900:  # 2:00-3:00
        return 0.7, "Afternoon — give setup 30 min to work or cut"
    if 900 <= mins < 960:  # 3:00-4:00
        return 1.0, "POWER HOUR — Mir's top window: 'biggest plays in final minutes'"
    return 0.0, "Market closed"


# ═══════════════════════════════════════════════════════════════════════
# RULE 3: STOP LOSS BEHAVIOR (from RAG Query 3)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

def score_stop_loss(pnl_pct: float, dte: int) -> tuple[float, str]:
    """Score whether current P&L aligns with Mir's exit rules.

    Source: RAG Query 3 (years of Discord data)
    Key rules:
      - "Set a stop when I enter so I never lose more than acceptable" (Mar 16, 2024)
      - "Keep a 50% stop unless it's a lotto" (May 14, 2025)
      - Lottos (0DTE): sized for zero, let run
      - Move to breakeven quickly once possible
      - Trail stops "just outside of last flagging action" (Mar 14, 2024)
      - "Be generous at first to let the trade work"
      - If thesis invalidated → exit regardless of P&L
    """
    if dte == 0:
        # 0DTE lottos: sized for zero, don't stop out
        if pnl_pct <= -80:
            return 0.2, "0DTE lotto near worthless — Mir says 'sized for zero'"
        return 1.0, "0DTE lotto — let ride to target or zero"

    if dte <= 7:
        # Weeklies: 50% stop
        if pnl_pct <= -50:
            return 0.0, "Mir rule: weeklies -50% = 'let it go' (May 14, 2025)"
        if pnl_pct <= -30:
            return 0.3, "Approaching -50% cut for weeklies"
        return 1.0, "Within Mir's weekly tolerance"

    # Longer dated: more room
    if pnl_pct <= -50:
        return 0.1, "Mir rule: -50% cut unless thesis still valid and chart looks fine"
    if pnl_pct <= -30:
        return 0.5, "Losing but Mir would check: 'is the setup still valid?'"
    return 1.0, "Within acceptable drawdown — Mir gives longer-dated trades room"


def get_mir_stop_management(dte: int) -> dict[str, Any]:
    """Get Mir's stop management approach by DTE.

    From RAG: "enter with hard stop → breakeven quickly → trail outside flagging"
    """
    if dte == 0:
        return {
            "initial": "Sized for zero — no stop needed",
            "management": "Let ride to target or expiry",
            "cut_rule": "N/A — lotto",
        }
    if dte <= 7:
        return {
            "initial": "Set hard stop at -50% of premium",
            "management": "Move to breakeven once 'there is wiggle room' (Mar 14, 2024)",
            "cut_rule": "-50% = exit (May 14, 2025)",
            "trail": "Outside last flagging action — 'be generous at first'",
        }
    return {
        "initial": "Set hard stop at max acceptable loss",
        "management": "Breakeven quickly → trail outside consolidation",
        "cut_rule": "-50% unless thesis valid and chart intact",
        "trail": "If it doubles, raise stop to protect profits (Nov 23, 2024)",
        "regime_note": "In strong trend, be generous — 'too tight wastes capital' (Nov 1, 2025)",
    }


# ═══════════════════════════════════════════════════════════════════════
# RULE 4: POSITION SIZING (from RAG Query 4)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

def get_mir_sizing(conviction: str, dte: int, trade_type: str = "SWING") -> dict[str, Any]:
    """Get Mir's sizing guidance.

    Source: RAG Query 4 (years of Discord data)
    Key rules:
      - Baseline: "5 or sometimes 10% size" (Jan 4, 2024)
      - Scale in 3 parts (Dec 1, 2025)
      - Heavy = high conviction, harvest quickly
      - Rollup = 1/3 of original to capture continuation (Dec 1, 2025)
      - "Never full port 80% unless account is tiny" (Apr 29, 2025)
      - "Must learn to size up with account growth" (Dec 26, 2024)
    """
    if dte == 0:
        return {
            "max_pct": 2.0,
            "entry_method": "ALL_AT_ONCE",
            "note": "0DTE lotto: size for zero, max 2% of account",
        }
    if conviction == "HIGH":
        return {
            "max_pct": 10.0,
            "entry_method": "SCALE_3_PARTS",
            "note": "HIGH conviction: up to 10%, scale in 3 parts, harvest heavy position quickly",
            "rollup": "1/3 of original size for continuation after taking profits",
        }
    if conviction == "MEDIUM":
        return {
            "max_pct": 5.0,
            "entry_method": "SCALE_3_PARTS",
            "note": "MEDIUM: standard 5% size, scale in 3 parts",
            "rollup": "1/3 of original for continuation",
        }
    return {
        "max_pct": 2.0,
        "entry_method": "SINGLE",
        "note": "LOW/WATCH: minimal size, single entry, prove the setup first",
    }


# ═══════════════════════════════════════════════════════════════════════
# RULE 5: TICKER SELECTION (from RAG Query 5)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

# ── Mir's Scanner Filters (from RAG Query 5) ─────────────────────
#
# Source: Mar 9 2026 (TradingView), Nov 23 2025 (Finviz)
#
# Breakout/UnR scanner:
#   Price > $3, Market Cap > $300M, Avg Vol > 500K
#   ADR% > 2%, EMA 21 & 50 below price
#
# Swing/RS scanner:
#   Market Cap > $2B, Price > $5, Avg Vol > 500K, Current Vol > 1M
#   Price above SMA 20, 50, 200 (strict)
#   Relative Volume > 1
#
# Post-screen: group by leading sector, select liquid leaders with RS
# "I like concentrated bets into what I feel can move the most" (Mar 6, 2024)

MIR_SCANNER_FILTERS = {
    "breakout": {
        "min_price": 3.0,
        "min_market_cap": 300_000_000,
        "min_avg_volume": 500_000,
        "min_adr_pct": 2.0,
        "ema_filter": "price > EMA21 > EMA50",
    },
    "swing_rs": {
        "min_price": 5.0,
        "min_market_cap": 2_000_000_000,
        "min_avg_volume": 500_000,
        "min_current_volume": 1_000_000,
        "min_relative_volume": 1.0,
        "ma_filter": "price > SMA20 > SMA50 > SMA200",
    },
}

MIR_PREFERRED_SECTORS = {
    "PHOTONICS": ["AAOI", "LITE", "COHR", "GLW", "CIEN", "AXTI"],
    "SEMI_EQUIPMENT": ["AEHR", "TER", "AMAT", "LRCX", "KLAC"],
    "SPACE": ["RKLB", "ASTS"],
    "AI_COMPUTE": ["NBIS", "OKLO", "IREN", "VRT", "ANET"],
    "MEMORY": ["MU", "WDC"],
}

def is_mir_sector(ticker: str) -> tuple[bool, str]:
    """Check if ticker is in one of Mir's preferred sector baskets."""
    for sector, tickers in MIR_PREFERRED_SECTORS.items():
        if ticker in tickers:
            return True, f"In Mir's {sector} basket"
    return False, "Not in a Mir thematic basket"


def score_ticker_quality(
    ticker: str,
    spot: float = 0,
    avg_volume: float = 0,
    ema21: float = 0,
    ema50: float = 0,
    ema200: float = 0,
    adr_pct: float = 0,
) -> tuple[float, list[str]]:
    """Score ticker against Mir's scanner criteria.

    Source: RAG Query 5
    Process: 1) Screen for liquidity & trend, 2) Group by leading sector,
    3) Select liquid leaders with highest RS, 4) Wait for entry model
    """
    score = 0.0
    checks: list[str] = []

    # Price filter
    if spot >= 5:
        score += 0.2
        checks.append(f"Price ${spot:.2f} > $5")
    elif spot >= 3:
        score += 0.1
        checks.append(f"Price ${spot:.2f} > $3 (breakout scanner)")
    else:
        checks.append(f"Price ${spot:.2f} — below Mir's minimum")

    # Volume
    if avg_volume >= 1_000_000:
        score += 0.2
        checks.append(f"Volume {avg_volume:,.0f} — liquid")
    elif avg_volume >= 500_000:
        score += 0.1
        checks.append(f"Volume {avg_volume:,.0f} — meets minimum")
    else:
        checks.append(f"Volume {avg_volume:,.0f} — below 500K filter")

    # EMA alignment (Mir's strict filter)
    if ema21 and ema50 and spot:
        if spot > ema21 > ema50:
            score += 0.3
            checks.append("EMA aligned: price > EMA21 > EMA50 (Mir's breakout filter)")
        elif spot > ema50:
            score += 0.1
            checks.append("Above EMA50 but EMA21 not aligned")
        else:
            checks.append("Below EMAs — Mir would skip")

    # SMA200 (swing RS scanner requires it)
    if ema200 and spot and spot > ema200:
        score += 0.1
        checks.append("Above 200MA — qualifies for Mir's swing RS scanner")

    # Sector basket
    in_sector, sector_note = is_mir_sector(ticker)
    if in_sector:
        score += 0.2
        checks.append(sector_note)
    else:
        checks.append("Not in a current Mir thematic basket")

    return min(score, 1.0), checks


# ═══════════════════════════════════════════════════════════════════════
# RULE 6: PROFIT TAKING (from RAG Query 6)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

def get_mir_exit_plan(dte: int, regime: str = "BULL") -> dict[str, Any]:
    """Get Mir's exit ladder.

    Source: RAG Query 6 (years of Discord data)
    Key rules:
      - "Scale out half at 100%" (Mar 31, 2024)
      - Primary target: 1.618 Fibonacci extension (Mar 16, 2024)
      - After 100% gain: trail stop on remainder
      - Runners: let ride if >30 DTE and chart looks fine (May 14, 2025)
      - Weeklies: 50% stop on profits (May 14, 2025)
      - Rollups (1/3 size): let run to expiration unless position gets too large
      - "Regime matters — grand slams in trends, base hits in chop" (Nov 1, 2025)
    """
    if dte == 0:
        return {
            "phase_1": {"trigger": "TARGET", "action": "Exit at target — 0DTE lotto"},
            "stop": {"pct": -100, "action": "Sized for zero, accept total loss"},
            "note": "0DTE: quick hits, no runners",
        }
    if dte <= 7:
        return {
            "phase_1": {"trigger": "+100%", "action": "Scale out 50% — Mir's doubling rule"},
            "phase_2": {"trigger": "1.618 fib", "action": "Exit rest or tight trail"},
            "stop": {"pct": -50, "action": "Cut — 'keep a 50% stop on weeklies'"},
            "runner": "NOT recommended for short-dated unless lotto",
        }
    if regime == "BULL":
        return {
            "phase_1": {"trigger": "+100%", "action": "Scale out 50% — de-risk the position"},
            "phase_2": {"trigger": "1.618 fib", "action": "Target zone — set alert slightly below fib"},
            "phase_3": {"trigger": "POST-TARGET", "action": "Trail stop, let runner work — 'waste of capital not to let contracts grow in a trend'"},
            "stop": {"pct": -50, "action": "Cut unless thesis still valid"},
            "rollup": "After taking profits: re-enter with 1/3 size for continuation",
            "runner": "YES — >30 DTE and chart intact, let it ride",
        }
    else:
        # Choppy / weak regime
        return {
            "phase_1": {"trigger": "+50%", "action": "Take base hit — 'time for base hits not grand slams'"},
            "phase_2": {"trigger": "+100%", "action": "Exit majority, small runner only"},
            "stop": {"pct": -30, "action": "Tighter stop in weak regime"},
            "runner": "SMALL — regime doesn't support holding",
        }


# ═══════════════════════════════════════════════════════════════════════
# RULE 7: REGIME / MACRO (from RAG Query 7)
# Populated after query results come in
# ═══════════════════════════════════════════════════════════════════════

def score_macro_alignment(
    vix: float = 0,
    nymo: float = 0,
    vix_structure: str = "",
    market_trend: str = "BULL",
) -> tuple[float, list[str]]:
    """Score macro environment against Mir's rules.

    Source: RAG Query 7 (years of Discord data)
    Key rules:
      - VIX elevated = "institutional risk management forces deleveraging" (Oct 15, 2025)
      - Binary events at highs = "risk/reward not great, hold cash" (Dec 8, 2025)
      - Dollar strength + market weakness = reduce beta (Mar 11, 2026)
      - Post-event clarity + key levels holding = aggressive (Dec 8, 2025)
      - Stocks bucking bad news = bullish (Dec 12, 2025)
      - "I don't trade based off FED commentary" (Nov 14, 2024)

    Defensive: VIX elevated, at resistance pre-event, dollar strong, risks clustering
    Aggressive: support holds post-event, strong RS names bucking trend
    """
    score = 1.0
    reasons: list[str] = []

    # VIX assessment
    if vix > 35:
        score -= 0.6
        reasons.append(f"VIX {vix:.0f} — EXTREME: Mir goes to cash, 'institutional risk forces deleveraging'")
    elif vix > 30:
        score -= 0.4
        reasons.append(f"VIX {vix:.0f} — HIGH: Mir reduces beta, waits for clarity")
    elif vix > 22:
        score -= 0.2
        reasons.append(f"VIX {vix:.0f} — Mir's warning zone: 'have cash for correction'")
    elif vix > 15:
        reasons.append(f"VIX {vix:.0f} — normal, Mir comfortable")
    elif vix > 0:
        score += 0.1
        reasons.append(f"VIX {vix:.0f} — low vol, complacency can be a risk but Mir is aggressive here")

    # VIX term structure
    if vix_structure == "BACKWARDATION":
        score -= 0.2
        reasons.append("VIX backwardation — fear elevated, Mir would be defensive")
    elif vix_structure == "CONTANGO":
        score += 0.1
        reasons.append("VIX contango — normal structure, Mir comfortable")

    # NYMO/breadth
    if nymo:
        if nymo < -60:
            score += 0.2
            reasons.append(f"NYMO {nymo:.0f} — extreme oversold, Mir looks for 'rotation into individual names that can move bigly'")
        elif nymo < -40:
            score += 0.1
            reasons.append(f"NYMO {nymo:.0f} — oversold, potential bounce setup")
        elif nymo > 80:
            score -= 0.1
            reasons.append(f"NYMO {nymo:.0f} — stretched, Mir takes base hits not grand slams")

    return max(0, min(1, score)), reasons


def get_mir_regime_action(
    vix: float = 0,
    nymo: float = 0,
    vix_structure: str = "",
) -> dict[str, Any]:
    """Get Mir's regime-based action plan.

    Returns posture (AGGRESSIVE/STANDARD/DEFENSIVE/CASH) and guidance.
    """
    if vix > 35:
        return {
            "posture": "CASH",
            "action": "Hold cash, wait for clarity. 'All you can do is prepare for the possibility'",
            "sizing": "MINIMAL — equity beta at 1 or lower",
            "focus": "Wait for key levels to hold post-event, then re-enter aggressively",
        }
    if vix > 22 or vix_structure == "BACKWARDATION":
        return {
            "posture": "DEFENSIVE",
            "action": "Reduce beta, book gains on index ETFs, keep cash ready",
            "sizing": "REDUCED — base hits not grand slams",
            "focus": "Rotate into high-RS individual names that buck the trend",
        }
    if nymo and nymo < -40:
        return {
            "posture": "AGGRESSIVE",
            "action": "Oversold bounce — size up in liquid leaders with RS",
            "sizing": "FULL — 'when stocks break out, waste of capital not to let contracts grow'",
            "focus": "Concentrated bets in leading sectors: photonics, semi equip, space",
        }
    return {
        "posture": "STANDARD",
        "action": "Normal operations — follow the setups",
        "sizing": "STANDARD — 5-10% per trade, scale in 3 parts",
        "focus": "Scan for breakouts and UnR setups in leading groups",
    }


# ═══════════════════════════════════════════════════════════════════════
# MASTER SCORING: "Would Mir take this trade?"
# ═══════════════════════════════════════════════════════════════════════

def score_mir_pattern(
    ticker: str,
    dte: int,
    conviction: str = "MEDIUM",
    trade_type: str = "SWING",
    vix: float = 0,
    nymo: float = 0,
    ema21: float = 0,
    ema50: float = 0,
    spot: float = 0,
) -> dict[str, Any]:
    """Score a potential trade against Mir's historical patterns.

    Returns {
        match_pct: 0-100,
        checks: [{rule, passed, score, reason}, ...],
        sizing: {max_pct, note},
        exit_plan: {...},
    }
    """
    checks: list[dict[str, Any]] = []
    total = 0
    max_total = 0

    # 1. DTE alignment
    dte_score, dte_reason = score_dte_alignment(dte, trade_type)
    checks.append({"rule": "DTE Preference", "passed": dte_score >= 0.7, "score": dte_score, "reason": dte_reason})
    total += dte_score
    max_total += 1

    # 2. Time of day
    tod_score, tod_reason = score_time_of_day()
    checks.append({"rule": "Time of Day", "passed": tod_score >= 0.7, "score": tod_score, "reason": tod_reason})
    total += tod_score
    max_total += 1

    # 3. Ticker quality (Mir's scanner criteria — price, volume, EMAs, sector)
    tq_score, tq_checks = score_ticker_quality(ticker, spot=spot, ema21=ema21, ema50=ema50)
    checks.append({"rule": "Ticker Quality", "passed": tq_score >= 0.6, "score": tq_score,
                    "reason": "; ".join(tq_checks)})
    total += tq_score
    max_total += 1

    # 5. Macro alignment
    if vix or nymo:
        macro_score, macro_reasons = score_macro_alignment(vix, nymo)
        checks.append({"rule": "Macro/VIX", "passed": macro_score >= 0.7, "score": macro_score,
                        "reason": "; ".join(macro_reasons)})
        total += macro_score
        max_total += 1

    # Compute match percentage
    match_pct = round((total / max_total * 100) if max_total else 0)

    return {
        "match_pct": match_pct,
        "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]),
        "total_checks": len(checks),
        "sizing": get_mir_sizing(conviction, dte, trade_type),
        "exit_plan": get_mir_exit_plan(dte),
    }
