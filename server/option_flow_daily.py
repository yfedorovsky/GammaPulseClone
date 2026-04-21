"""Per-contract daily option flow aggregation — broader than ISO sweeps.

The SWEEPS tab (server/sweep_detector.py) captures only OPRA-tagged ISO
prints (condition 95/126/128) — the narrowest, highest-signal subset.
This module captures ALL aggressive flow per contract per day, matching
the view that UW and similar tools show:

  NVDA $200C 04-20 (3d)  vol=84,694  notional=$22.2M  Bought  sweep%=7%

Differences vs sweep_detector:
  - Aggregation grain: one row per (date, ticker, strike, exp, type)
    (vs sweep's 30s time-bucket rollups)
  - Filter: includes BOTH sweep (cond 95/126/128) AND non-ISO aggressive
    prints (any trade with price >= ask or price <= bid)
  - Output: total daily flow with buy/sell/neutral splits + sweep share

Architecture:
  - Backfill: scripts/backfill_option_flow.py pulls trade_quote history
    per contract, aggregates into this table
  - Live: not implemented in this first version — data is populated
    daily via backfill. Live streaming is a follow-up (needs broader
    WebSocket subscription than the narrow sweep ATM watchlist).
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings


# ── Schema ─────────────────────────────────────────────────────────

FLOW_DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_flow_daily (
  date TEXT NOT NULL,                      -- YYYY-MM-DD (trade date)
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,                -- YYYY-MM-DD
  option_type TEXT NOT NULL,               -- 'call' | 'put'

  -- Totals (includes ALL non-cancelled prints)
  total_volume INTEGER DEFAULT 0,
  total_notional REAL DEFAULT 0,
  trade_count INTEGER DEFAULT 0,

  -- Side split (strict NBBO classification: price >= ask = BUY, price <= bid = SELL)
  buy_volume INTEGER DEFAULT 0,
  buy_notional REAL DEFAULT 0,
  sell_volume INTEGER DEFAULT 0,
  sell_notional REAL DEFAULT 0,
  neutral_volume INTEGER DEFAULT 0,
  neutral_notional REAL DEFAULT 0,

  -- Sweep share (subset of the above; ISO condition 95/126/128)
  sweep_volume INTEGER DEFAULT 0,
  sweep_notional REAL DEFAULT 0,
  sweep_prints INTEGER DEFAULT 0,

  -- Block trade share (condition 75; off-exchange institutional blocks)
  block_volume INTEGER DEFAULT 0,
  block_notional REAL DEFAULT 0,

  -- Biggest single print of the day (for UW-style "detail" field)
  largest_print_size INTEGER DEFAULT 0,
  largest_print_price REAL DEFAULT 0,
  largest_print_time TEXT,                 -- ISO timestamp
  largest_print_venue INTEGER,
  largest_print_side TEXT,
  largest_print_is_sweep INTEGER DEFAULT 0,

  -- Static context (latest snapshot values; approximate for historical dates)
  oi INTEGER,
  iv REAL,
  delta REAL,
  spot REAL,

  -- When this row was written/refreshed
  updated_ts INTEGER DEFAULT 0,

  PRIMARY KEY (date, ticker, strike, expiration, option_type)
);
CREATE INDEX IF NOT EXISTS idx_flow_daily_date ON option_flow_daily(date);
CREATE INDEX IF NOT EXISTS idx_flow_daily_ticker ON option_flow_daily(ticker, date);
CREATE INDEX IF NOT EXISTS idx_flow_daily_notional ON option_flow_daily(total_notional DESC);
"""


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db, timeout=30.0)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ── GOLDEN FLOW classifier ─────────────────────────────────────────
#
# Pattern targeted: the SPY 647P 03/24/2026 trade that hit 15 min before
# market-moving headlines — $1.49M premium, 76% bought at ask, V/OI ~10x,
# 1% OTM, 1DTE. All the classic insider-flow fingerprints.
#
# Rules (all must match):
#   1. Notional        >= $500K          (material size)
#   2. Bought%         >= 70%            (aggressive at-ask, not mid)
#   3. Volume / OI     >= 3.0            (opening position, not closing)
#   4. |strike-spot|/spot <= 2.5%        (just OTM / near-ATM)
#   5. DTE             <= 2              (short-dated = high leverage)

GOLDEN_FLOW_RULES = {
    "min_notional": 500_000,
    "min_bought_pct": 0.65,     # calibrated vs UW screenshot (SPY 647P 3/23: our 65% vs UW's 76%)
    "min_vol_oi_ratio": 3.0,
    "max_otm_pct": 0.025,
    "max_dte": 2,
    # Symmetric: for SELL-dominant (puts for upside fade, etc.), use min_sold_pct.
    # Handled as separate threshold so bullish + bearish insider flows both catch.
    "min_sold_pct": 0.65,
}


# Mag7-tier GOLDEN: same conviction bars, lower notional threshold.
#
# Justification mirrors UPSIDE_BET_RULES_MAG7: Mag7 options are deep enough
# that $200K at ATM 0-2 DTE is still institutional positioning (not retail
# lottery), because the absolute dollar floor to move these contracts is
# genuinely higher. A $200K 0DTE AMZN sweep in 30 seconds is a footprint.
GOLDEN_FLOW_RULES_MAG7 = {
    "min_notional": 200_000,       # 2.5x lower (same ratio as UPSIDE_BET tier)
    "min_bought_pct": 0.65,        # same conviction
    "min_vol_oi_ratio": 3.0,       # same
    "max_otm_pct": 0.025,          # same tight ATM band
    "max_dte": 2,                  # same
    "min_sold_pct": 0.65,          # same
}


def _golden_flow_rules_for(row: dict) -> dict:
    """Select GOLDEN_FLOW ruleset: Mag7 tier or default. See _upside_bet_rules_for."""
    ticker = (row.get("ticker") or "").upper()
    if ticker in MAG7_ROOTS:
        return GOLDEN_FLOW_RULES_MAG7
    return GOLDEN_FLOW_RULES


# TAIL FLOW — the cheap-far-OTM-longer-dated-lottery insider pattern.
#
# Distinct from GOLDEN (urgent, ATM, 1-2 DTE). This pattern is:
#   - Cheap premium (< $2 avg fill) — defining trait
#   - Far OTM (5-20%) — not ATM, betting on significant break
#   - Longer DTE (5-45 trading days) — weeks of runway
#   - Directional conviction (65%+ one side)
#
# Real-world example (user flagged 2026-04-17):
#   SPY 620P exp 5/8 — 21 DTE, 13% OTM, $0.43 avg, $838K notional, 82% bought
#
# Who trades this:
#   - Fund managers buying downside insurance on their book
#   - Insiders with info about an event within a ~month window but uncertain timing
#   - Event-driven funds positioning for earnings/regulatory/M&A ruptures
#
# Why clusters matter:
#   One alert = noise (hedge). Two+ on same underlying = signal (someone knows).
TAIL_FLOW_RULES = {
    "min_notional": 500_000,
    "min_bought_pct": 0.65,
    "min_sold_pct": 0.65,
    "max_avg_fill": 2.0,          # < $2 per contract = cheap lotto
    "min_otm_pct": 0.04,          # >4% OTM — far enough to be a bet, not a hedge-next-to-spot
    "max_otm_pct": 0.25,          # <25% OTM — avoid out-there noise
    "min_dte": 3,                 # >2 trading days (else it overlaps GOLDEN)
    "max_dte": 45,                # ~2 months max — keep it focused
    # Note: no V/OI rule. TAIL trades often ADD to existing hedges, so
    # V/OI can be well below 1. The cheap premium + far OTM + conviction
    # combo is the signal, not fresh-position-open bias.
}


# UPSIDE_BET — the "institutional bull thesis, 3-20 DTE, ATM-to-moderate-OTM" pattern.
#
# Fills the gap between GOLDEN (≤2 DTE, ATM-only, expensive-OK) and TAIL
# (3-45 DTE, far-OTM, cheap-only). Real cases that failed BOTH today:
#
#   MRVL 165C 5/8 (2026-04-20):
#     13.3% OTM, 18 DTE, $318K, V/OI 75x, 97% bought @ $2.58 avg
#     → FAILED GOLDEN (OTM too far, DTE too long, notional too small)
#     → FAILED TAIL (premium too expensive at $2.58 > $2 cap)
#     → This is the pattern UPSIDE_BET catches.
#
#   FSLR 192.5C 4/24 (2026-04-20):
#     0.6% OTM, 4 DTE, $1M, V/OI 14x, ~97% bought
#     → FAILED GOLDEN (DTE 4 > 2)
#     → Doesn't fit TAIL (not cheap, not far-OTM)
#     → UPSIDE_BET catches.
#
# Strategic signal: "someone is positioning for a specific move in the next
# few weeks." Distinct from GOLDEN (imminent) and TAIL (catastrophic lottery).
UPSIDE_BET_RULES = {
    "min_notional": 250_000,       # Lower than GOLDEN — catches mid-cap flows
    "min_bought_pct": 0.70,        # Higher than GOLDEN — stricter conviction
    "min_vol_oi_ratio": 10.0,      # Much higher than GOLDEN's 3x — pure new positioning
    "min_otm_pct": 0.0,            # ATM OK
    "max_otm_pct": 0.15,           # 0-15% OTM (wider than GOLDEN's 2.5%, narrower than TAIL)
    "min_dte": 2,                  # Just past 0-1 DTE (gamma gamble zone)
    "max_dte": 20,                 # 4 trading weeks — catches earnings run-ups + catalyst windows
    # Note: asymmetric — UPSIDE_BET is BULLISH-for-stock ONLY.
    # CALL + BUY = bullish (fires), PUT + SELL = bullish (fires).
    # CALL + SELL (covered calls) and PUT + BUY (protective puts) do NOT fire.
    # This is by design — GOLDEN's "symmetric" bug we fixed 2026-04-20 taught us
    # that direction semantics matter more than raw conviction on any side.
}


# ── Mag7 tier ──────────────────────────────────────────────────────
#
# Why a separate tier for Mag7 names:
#
# Mag7 options trade billions in daily notional. $250K is a rounding error
# in AMZN/NVDA/AAPL options — meaningful institutional positioning routinely
# sizes at $100-200K per strike to stay under detection thresholds while
# still being consequential relative to average retail flow.
#
# Real case that motivated this (2026-04-20):
#   AMZN 5/1 $250C loaded in multiple prints throughout the day:
#     9:56 AM: 200 @ $8.40 = $168K
#     11:05 AM: 100 @ $7.65 = $76K
#     12:38 PM: 100 @ $8.20 = $82K
#     2:11 PM:  131 @ $8.75 = $114K
#   → Anthropic investment news broke AH same day → +2.72% AH
#   → Current $250K threshold misses the 9:56 AM print (would have
#     given 6+ hours of runway before news)
#
# Tier tradeoffs:
#   - LOWER notional ($100K): catches institutional-size but sub-threshold flows
#   - TIGHTER OTM (5%): in Mag7, real conviction = near-ATM; wide OTM = retail
#   - ALLOW 0DTE: Mag7 liquidity supports 0DTE informational flow (not just gamma noise)
#
# Roots: "Mag7 + high-liquidity AI-adjacent mega-caps." Despite the historical
# name, this set has grown past the literal Mag7 — it's the list of names
# where extreme options liquidity justifies lower absolute-dollar thresholds
# because institutional positioning routinely sizes at $100-200K per strike
# to stay under detection while still being consequential vs retail flow.
#
# Expand deliberately — this is the highest-signal list, not a general index.
# Each addition should have (a) >$1B avg daily options notional, (b) a track
# record of producing clean insider footprints we've observed ourselves.
#
# Added 2026-04-20:
#   ARM — AI chip-licensing play, $16.2M cross-strike footprint on 4/20
#         (multiple $200K+ prints within 14-min window, clear coordination)
MAG7_ROOTS = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN",
    "META", "NVDA", "TSLA",
    "ARM",
})


UPSIDE_BET_RULES_MAG7 = {
    "min_notional": 100_000,       # 2.5x lower than default — Mag7 liquidity supports it
    "min_bought_pct": 0.70,        # same conviction bar
    "min_vol_oi_ratio": 10.0,      # same new-positioning bar
    "min_otm_pct": 0.0,            # ATM OK
    "max_otm_pct": 0.05,           # TIGHTER: 5% max (Mag7 real conviction is near-ATM)
    "min_dte": 0,                  # Allow 0DTE for Mag7 (liquidity supports it as signal)
    "max_dte": 20,                 # same 4-week horizon
}


def _upside_bet_rules_for(row: dict) -> dict:
    """Select the right UPSIDE_BET ruleset: Mag7 tier or default.

    Mag7 names get lower notional threshold (institutional flows size smaller
    to stay under detection) and tighter OTM (real conviction is near-ATM in
    mega-cap liquid names, not far-OTM lottery).
    """
    ticker = (row.get("ticker") or "").upper()
    if ticker in MAG7_ROOTS:
        return UPSIDE_BET_RULES_MAG7
    return UPSIDE_BET_RULES


def is_golden_flow(row: dict) -> tuple[bool, list[str]]:
    """Return (is_golden, list_of_failed_rules).

    Row is a dict matching option_flow_daily columns (or close). Missing
    fields fail their rule. Enables "show me what's ALMOST golden" UI later.

    Mag7 names get GOLDEN_FLOW_RULES_MAG7 (lower notional floor). See
    _golden_flow_rules_for().
    """
    rules = _golden_flow_rules_for(row)
    failed: list[str] = []

    notional = row.get("total_notional") or 0
    if notional < rules["min_notional"]:
        failed.append(f"notional(${notional/1000:.0f}K<${rules['min_notional']/1000:.0f}K)")

    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    # UW methodology: % of DIRECTIONAL flow (neutral/mid-market prints excluded).
    # Neutral prints are mostly MM hedging + paired trades — not informational
    # about direction — so they shouldn't dilute the conviction metric.
    directional = buy + sell
    bought_pct = (buy / directional) if directional > 0 else 0
    sold_pct = (sell / directional) if directional > 0 else 0
    # Symmetric conviction: bullish buying OR bearish selling (both possible
    # for insider flow depending on whether they're loading puts or selling calls).
    side_ok = (
        bought_pct >= rules["min_bought_pct"]
        or sold_pct >= rules["min_sold_pct"]
    )
    if not side_ok:
        failed.append(f"side_conv(B{bought_pct*100:.0f}%/S{sold_pct*100:.0f}% both below {rules['min_bought_pct']*100:.0f}%)")

    vol = row.get("total_volume") or 0
    oi = row.get("oi") or 0
    vol_oi = (vol / oi) if oi > 0 else float("inf")  # no OI = definitely new
    if oi > 0 and vol_oi < rules["min_vol_oi_ratio"]:
        failed.append(f"vol/oi({vol_oi:.1f}x<{rules['min_vol_oi_ratio']}x)")

    strike = row.get("strike") or 0
    spot = row.get("spot") or 0
    otm_pct = abs(strike - spot) / spot if (strike > 0 and spot > 0) else 1.0
    if otm_pct > rules["max_otm_pct"]:
        failed.append(f"OTM({otm_pct*100:.1f}%>{rules['max_otm_pct']*100:.1f}%)")

    # DTE = TRADING days between trade date and expiration (weekdays only).
    # Calendar-day DTE overcounts Fri-trade/Mon-exp as 3 days when it's
    # really 1 trading day — causing a common insider-flow setup (Fri
    # afternoon → Mon morning) to fail the ≤2 DTE rule spuriously.
    from datetime import date as _date, timedelta as _td
    trade_date = row.get("date") or ""
    exp = row.get("expiration") or ""
    try:
        td = _date.fromisoformat(trade_date)
        ed = _date.fromisoformat(exp)
        # Count weekdays strictly between td and ed, inclusive of exp day.
        # 4/17 Fri → 4/20 Mon: Sat skip, Sun skip, Mon count = 1 trading day.
        dte = 0
        d = td
        while d < ed:
            d = d + _td(days=1)
            if d.weekday() < 5:
                dte += 1
    except (ValueError, TypeError):
        dte = 999
    if dte > GOLDEN_FLOW_RULES["max_dte"]:
        failed.append(f"dte({dte}td>{GOLDEN_FLOW_RULES['max_dte']})")

    return (len(failed) == 0), failed


def get_golden_flow(
    since_date: str | None = None, ticker: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query flow_daily + apply Golden Flow classifier. Returns only matches."""
    from .option_flow_daily import get_flow_daily  # self-ref for import clarity
    rows = get_flow_daily(
        since_date=since_date, ticker=ticker,
        min_notional=GOLDEN_FLOW_RULES["min_notional"],
        limit=limit * 5,  # fetch more, filter down
    )
    golden: list[dict] = []
    for r in rows:
        is_gold, _failed = is_golden_flow(r)
        if is_gold:
            r["_golden"] = True
            golden.append(r)
    return golden[:limit]


def is_tail_flow(row: dict) -> tuple[bool, list[str]]:
    """TAIL FLOW classifier — cheap far-OTM longer-dated insider pattern.

    Returns (is_tail, failed_rules). Complements is_golden_flow which
    catches urgent ATM 0-2 DTE. TAIL catches cheap-lotto 5-20% OTM 3-45 DTE.
    """
    failed: list[str] = []

    notional = row.get("total_notional") or 0
    if notional < TAIL_FLOW_RULES["min_notional"]:
        failed.append(f"notional(${notional/1000:.0f}K<${TAIL_FLOW_RULES['min_notional']/1000:.0f}K)")

    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    directional = buy + sell
    bought_pct = (buy / directional) if directional > 0 else 0
    sold_pct = (sell / directional) if directional > 0 else 0
    side_ok = (
        bought_pct >= TAIL_FLOW_RULES["min_bought_pct"]
        or sold_pct >= TAIL_FLOW_RULES["min_sold_pct"]
    )
    if not side_ok:
        failed.append(f"side_conv(B{bought_pct*100:.0f}%/S{sold_pct*100:.0f}%)")

    # Avg fill price — the defining "cheap lotto" trait
    vol = row.get("total_volume") or 0
    avg_fill = (notional / (vol * 100)) if vol > 0 else 0
    if avg_fill > TAIL_FLOW_RULES["max_avg_fill"] or avg_fill <= 0:
        failed.append(f"avg_fill(${avg_fill:.2f}>${TAIL_FLOW_RULES['max_avg_fill']:.2f})")

    strike = row.get("strike") or 0
    spot = row.get("spot") or 0
    otm_pct = abs(strike - spot) / spot if (strike > 0 and spot > 0) else 1.0
    if otm_pct < TAIL_FLOW_RULES["min_otm_pct"]:
        failed.append(f"OTM({otm_pct*100:.1f}%<{TAIL_FLOW_RULES['min_otm_pct']*100:.1f}%)")
    if otm_pct > TAIL_FLOW_RULES["max_otm_pct"]:
        failed.append(f"OTM({otm_pct*100:.1f}%>{TAIL_FLOW_RULES['max_otm_pct']*100:.1f}%)")

    # Trading-day DTE — same methodology as GOLDEN
    from datetime import date as _date, timedelta as _td
    trade_date = row.get("date") or ""
    exp = row.get("expiration") or ""
    try:
        td = _date.fromisoformat(trade_date)
        ed = _date.fromisoformat(exp)
        dte = 0
        d = td
        while d < ed:
            d = d + _td(days=1)
            if d.weekday() < 5:
                dte += 1
    except (ValueError, TypeError):
        dte = 999
    if dte < TAIL_FLOW_RULES["min_dte"]:
        failed.append(f"dte({dte}td<{TAIL_FLOW_RULES['min_dte']})")
    if dte > TAIL_FLOW_RULES["max_dte"]:
        failed.append(f"dte({dte}td>{TAIL_FLOW_RULES['max_dte']})")

    return (len(failed) == 0), failed


def get_tail_flow(
    since_date: str | None = None, ticker: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query flow_daily + apply TAIL classifier. Returns only matches."""
    rows = get_flow_daily(
        since_date=since_date, ticker=ticker,
        min_notional=TAIL_FLOW_RULES["min_notional"],
        limit=limit * 5,
    )
    out: list[dict] = []
    for r in rows:
        is_tail, _failed = is_tail_flow(r)
        if is_tail:
            r["_tail"] = True
            out.append(r)
    return out[:limit]


def is_upside_bet(row: dict) -> tuple[bool, list[str]]:
    """UPSIDE_BET classifier — institutional bull thesis 2-20 DTE, ATM-to-moderate-OTM.

    Returns (is_upside_bet, failed_rules). Fills the gap between GOLDEN (≤2 DTE,
    ATM-only) and TAIL (cheap-only). Asymmetric — fires ONLY on bullish-for-stock
    flow (CALL+BUY or PUT+SELL dominant).

    Mag7 names get a separate (looser notional, tighter OTM) ruleset — see
    UPSIDE_BET_RULES_MAG7 and _upside_bet_rules_for().
    """
    rules = _upside_bet_rules_for(row)
    failed: list[str] = []

    notional = row.get("total_notional") or 0
    if notional < rules["min_notional"]:
        failed.append(f"notional(${notional/1000:.0f}K<${rules['min_notional']/1000:.0f}K)")

    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    directional = buy + sell
    bought_pct = (buy / directional) if directional > 0 else 0
    sold_pct = (sell / directional) if directional > 0 else 0

    # Asymmetric bullish-for-stock requirement
    option_type = (row.get("option_type") or "").lower()
    if option_type == "call":
        # CALL + BUY = institutions loading upside (bullish for stock)
        if bought_pct < rules["min_bought_pct"]:
            failed.append(f"call_buy_conv({bought_pct*100:.0f}%<{rules['min_bought_pct']*100:.0f}%)")
    elif option_type == "put":
        # PUT + SELL = institutions selling puts for premium (bullish for stock)
        if sold_pct < rules["min_bought_pct"]:
            failed.append(f"put_sell_conv({sold_pct*100:.0f}%<{rules['min_bought_pct']*100:.0f}%)")
    else:
        failed.append("unknown_option_type")

    vol = row.get("total_volume") or 0
    oi = row.get("oi") or 0
    vol_oi = (vol / oi) if oi > 0 else float("inf")
    if oi > 0 and vol_oi < rules["min_vol_oi_ratio"]:
        failed.append(f"vol_oi({vol_oi:.1f}x<{rules['min_vol_oi_ratio']:.0f}x)")

    spot = row.get("spot") or 0
    strike = row.get("strike") or 0
    if spot > 0 and strike > 0:
        if option_type == "call":
            otm_pct = max(0.0, (strike - spot) / spot)
        else:  # put
            otm_pct = max(0.0, (spot - strike) / spot)
        if otm_pct < rules["min_otm_pct"]:
            failed.append(f"otm({otm_pct*100:.1f}%<{rules['min_otm_pct']*100:.1f}%)")
        if otm_pct > rules["max_otm_pct"]:
            failed.append(f"otm({otm_pct*100:.1f}%>{rules['max_otm_pct']*100:.1f}%)")

    dte = row.get("dte")
    if dte is None:
        try:
            import datetime as _dt
            exp = row.get("expiration")
            date_str = row.get("date")
            if exp and date_str:
                ed = _dt.date.fromisoformat(exp)
                td = _dt.date.fromisoformat(date_str)
                dte = max(0, (ed - td).days)
        except Exception:
            dte = 999
    if dte is not None:
        if dte < rules["min_dte"]:
            failed.append(f"dte({dte}<{rules['min_dte']})")
        if dte > rules["max_dte"]:
            failed.append(f"dte({dte}>{rules['max_dte']})")

    return (len(failed) == 0), failed


def get_upside_bet(
    since_date: str | None = None, ticker: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query flow_daily + apply UPSIDE_BET classifier. Returns only matches."""
    # Pre-filter at DB level with the LOWER threshold so Mag7-tier candidates
    # aren't dropped before the classifier can route them to the correct rules.
    pre_filter_min = min(
        UPSIDE_BET_RULES["min_notional"],
        UPSIDE_BET_RULES_MAG7["min_notional"],
    )
    rows = get_flow_daily(
        since_date=since_date, ticker=ticker,
        min_notional=pre_filter_min,
        limit=limit * 5,
    )
    out: list[dict] = []
    for r in rows:
        is_ub, _failed = is_upside_bet(r)
        if is_ub:
            r["_upside_bet"] = True
            out.append(r)
    return out[:limit]


# ── GRADING ────────────────────────────────────────────────────────
#
# Each alert gets an A+/A/B/C/D grade from a 0-20 composite score.
# Grading is cohort-aware: cluster_size is passed in (how many other
# GOLDEN/TAIL alerts fired on the same ticker in the same session).
# More confluence = higher grade.


def _tier_score(value: float, ladder: list[tuple[float, int]]) -> int:
    """Return first matching tier's points. Ladder is [(threshold, points), ...]
    sorted by threshold DESC — the first threshold the value meets/exceeds wins."""
    for thresh, pts in ladder:
        if value >= thresh:
            return pts
    return 0


def _grade_from_score(score: int, max_score: int = 20) -> str:
    """Map 0-max score to A+/A/B/C/D grade."""
    if max_score <= 0:
        return "—"
    pct = score / max_score
    if pct >= 0.80: return "A+"
    if pct >= 0.60: return "A"
    if pct >= 0.40: return "B"
    if pct >= 0.25: return "C"
    return "D"


def score_golden_flow(row: dict, cluster_size: int = 1) -> dict:
    """Grade a GOLDEN FLOW match on 5 factors, each 0-4 points, total 0-20.

    cluster_size: how many other GOLDEN/TAIL alerts fired on this ticker
    in this session (1 = solo, 2+ = confluence tell).
    """
    notional = row.get("total_notional") or 0
    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    directional = buy + sell
    bought_pct = (buy / directional) if directional > 0 else 0
    sold_pct = (sell / directional) if directional > 0 else 0
    side_pct = max(bought_pct, sold_pct)  # symmetric — BUY or SELL conviction

    vol = row.get("total_volume") or 0
    oi = row.get("oi") or 0
    vol_oi = (vol / oi) if oi > 0 else 999  # no OI = treat as maxed-out opening position
    sweep_share = ((row.get("sweep_notional") or 0) / notional) if notional > 0 else 0

    notional_pts = _tier_score(notional, [
        (25_000_000, 4), (10_000_000, 3), (5_000_000, 2), (1_000_000, 1), (500_000, 0),
    ])
    conviction_pts = _tier_score(side_pct, [
        (0.95, 4), (0.85, 3), (0.75, 2), (0.70, 1), (0.65, 0),
    ])
    voi_pts = _tier_score(vol_oi, [
        (20.0, 4), (10.0, 3), (5.0, 2), (3.0, 1), (0.0, 0),
    ])
    sweep_pts = _tier_score(sweep_share, [
        (0.30, 4), (0.20, 3), (0.10, 2), (0.05, 1), (0.0, 0),
    ])
    cluster_pts = _tier_score(float(cluster_size), [
        (5.0, 4), (3.0, 3), (2.0, 2), (1.5, 1), (1.0, 0),
    ])

    score = notional_pts + conviction_pts + voi_pts + sweep_pts + cluster_pts
    return {
        "grade": _grade_from_score(score),
        "score": score,
        "max_score": 20,
        "factors": {
            "notional": {"pts": notional_pts, "value": notional},
            "conviction": {"pts": conviction_pts, "value": side_pct, "side": "BUY" if bought_pct >= sold_pct else "SELL"},
            "vol_oi": {"pts": voi_pts, "value": vol_oi},
            "sweep_share": {"pts": sweep_pts, "value": sweep_share},
            "cluster": {"pts": cluster_pts, "value": cluster_size},
        },
    }


def score_tail_flow(row: dict, cluster_size: int = 1) -> dict:
    """Grade a TAIL FLOW match. Same 5-factor template as GOLDEN but with
    TAIL-appropriate ladders:
      - V/OI is less important for TAIL (hedges add to existing OI)
      - Sweep share less relevant (TAIL trades often aren't sweeps)
      - Cheapness of premium swaps in as the 5th factor instead of cluster
        — but we keep cluster since it's the primary "they know something" tell

    For TAIL, V/OI is weaker signal, so we score it more generously.
    """
    notional = row.get("total_notional") or 0
    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    directional = buy + sell
    bought_pct = (buy / directional) if directional > 0 else 0
    sold_pct = (sell / directional) if directional > 0 else 0
    side_pct = max(bought_pct, sold_pct)
    vol = row.get("total_volume") or 0
    avg_fill = (notional / (vol * 100)) if vol > 0 else 0
    strike = row.get("strike") or 0
    spot = row.get("spot") or 0
    otm_pct = abs(strike - spot) / spot if (strike > 0 and spot > 0) else 0

    notional_pts = _tier_score(notional, [
        (10_000_000, 4), (5_000_000, 3), (2_000_000, 2), (1_000_000, 1), (500_000, 0),
    ])
    conviction_pts = _tier_score(side_pct, [
        (0.95, 4), (0.85, 3), (0.75, 2), (0.70, 1), (0.65, 0),
    ])
    # Cheaper premium = stronger lotto signal (closer to pure optionality)
    cheapness_pts = _tier_score(-avg_fill, [
        (-0.30, 4), (-0.60, 3), (-1.00, 2), (-1.50, 1), (-2.00, 0),
    ]) if avg_fill > 0 else 0
    # Deeper OTM within range = stronger black-swan signal (up to a point)
    otm_pts = _tier_score(otm_pct, [
        (0.15, 4), (0.10, 3), (0.07, 2), (0.05, 1), (0.04, 0),
    ])
    cluster_pts = _tier_score(float(cluster_size), [
        (5.0, 4), (3.0, 3), (2.0, 2), (1.5, 1), (1.0, 0),
    ])

    score = notional_pts + conviction_pts + cheapness_pts + otm_pts + cluster_pts
    return {
        "grade": _grade_from_score(score),
        "score": score,
        "max_score": 20,
        "factors": {
            "notional": {"pts": notional_pts, "value": notional},
            "conviction": {"pts": conviction_pts, "value": side_pct, "side": "BUY" if bought_pct >= sold_pct else "SELL"},
            "cheapness": {"pts": cheapness_pts, "value": avg_fill},
            "otm": {"pts": otm_pts, "value": otm_pct},
            "cluster": {"pts": cluster_pts, "value": cluster_size},
        },
    }


def init_flow_daily_db() -> None:
    with _conn() as c:
        c.executescript(FLOW_DAILY_SCHEMA)


# ── Aggregator ─────────────────────────────────────────────────────

# Block trade condition
COND_BLOCK_TRADE = 75


class DailyFlowAggregate:
    """Per-contract daily accumulator.

    Consume each trade print via `add()`. When all trades for a contract-day
    have been consumed, call `.to_row()` to get the dict for DB upsert.
    """

    def __init__(self, date: str, ticker: str, strike: float, expiration: str, option_type: str):
        self.date = date
        self.ticker = ticker
        self.strike = strike
        self.expiration = expiration
        self.option_type = option_type

        self.total_volume = 0
        self.total_notional = 0.0
        self.trade_count = 0

        self.buy_volume = 0
        self.buy_notional = 0.0
        self.sell_volume = 0
        self.sell_notional = 0.0
        self.neutral_volume = 0
        self.neutral_notional = 0.0

        self.sweep_volume = 0
        self.sweep_notional = 0.0
        self.sweep_prints = 0

        self.block_volume = 0
        self.block_notional = 0.0

        self.largest_print_size = 0
        self.largest_print_price = 0.0
        self.largest_print_time = ""
        self.largest_print_venue = 0
        self.largest_print_side = "NEUTRAL"
        self.largest_print_is_sweep = False

    def add(
        self, *, size: int, price: float, exchange: int, condition: int,
        side: str, is_sweep: bool, timestamp: str,
    ) -> None:
        notional = size * price * 100.0

        self.total_volume += size
        self.total_notional += notional
        self.trade_count += 1

        if side == "BUY":
            self.buy_volume += size
            self.buy_notional += notional
        elif side == "SELL":
            self.sell_volume += size
            self.sell_notional += notional
        else:
            self.neutral_volume += size
            self.neutral_notional += notional

        if is_sweep:
            self.sweep_volume += size
            self.sweep_notional += notional
            self.sweep_prints += 1

        if condition == COND_BLOCK_TRADE:
            self.block_volume += size
            self.block_notional += notional

        # Track biggest single print by size (could also be by notional — size
        # is simpler and matches UW's "N blocks" semantic)
        if size > self.largest_print_size:
            self.largest_print_size = size
            self.largest_print_price = price
            self.largest_print_time = timestamp
            self.largest_print_venue = exchange
            self.largest_print_side = side
            self.largest_print_is_sweep = is_sweep

    @property
    def dominant_side(self) -> str:
        """Aggregate side determined by notional majority (>55% threshold)."""
        total = self.buy_notional + self.sell_notional + self.neutral_notional
        if total <= 0:
            return "NEUTRAL"
        if self.buy_notional / total >= 0.55:
            return "BUY"
        if self.sell_notional / total >= 0.55:
            return "SELL"
        return "NEUTRAL"

    @property
    def bought_pct(self) -> float:
        """Fraction of notional at/above ask."""
        total = self.buy_notional + self.sell_notional + self.neutral_notional
        return self.buy_notional / total if total > 0 else 0.0

    @property
    def sweep_share(self) -> float:
        """Fraction of notional that was ISO sweep."""
        return self.sweep_notional / self.total_notional if self.total_notional > 0 else 0.0

    def to_db_tuple(self, oi: int | None, iv: float | None, delta: float | None, spot: float | None) -> tuple:
        """Build the tuple for INSERT OR REPLACE INTO option_flow_daily."""
        return (
            self.date, self.ticker, self.strike, self.expiration, self.option_type,
            self.total_volume, round(self.total_notional, 2), self.trade_count,
            self.buy_volume, round(self.buy_notional, 2),
            self.sell_volume, round(self.sell_notional, 2),
            self.neutral_volume, round(self.neutral_notional, 2),
            self.sweep_volume, round(self.sweep_notional, 2), self.sweep_prints,
            self.block_volume, round(self.block_notional, 2),
            self.largest_print_size, self.largest_print_price,
            self.largest_print_time, self.largest_print_venue,
            self.largest_print_side, 1 if self.largest_print_is_sweep else 0,
            oi, iv, delta, spot,
            int(time.time()),
        )


# ── Batch insert ───────────────────────────────────────────────────


UPSERT_SQL = """
INSERT OR REPLACE INTO option_flow_daily (
  date, ticker, strike, expiration, option_type,
  total_volume, total_notional, trade_count,
  buy_volume, buy_notional, sell_volume, sell_notional,
  neutral_volume, neutral_notional,
  sweep_volume, sweep_notional, sweep_prints,
  block_volume, block_notional,
  largest_print_size, largest_print_price, largest_print_time,
  largest_print_venue, largest_print_side, largest_print_is_sweep,
  oi, iv, delta, spot, updated_ts
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def upsert_flow_daily_batch(rows: list[tuple]) -> int:
    """Upsert a list of flow-daily tuples in a single transaction."""
    if not rows:
        return 0
    with _conn() as c:
        c.executemany(UPSERT_SQL, rows)
    return len(rows)


def clean_flow_daily_range(dates: list[str], tickers: list[str]) -> int:
    """Delete rows for date range × ticker list (for idempotent re-backfill)."""
    if not dates or not tickers:
        return 0
    ticker_filter = ",".join(f"'{t.upper()}'" for t in tickers)
    date_filter = ",".join(f"'{d}'" for d in dates)
    with _conn() as c:
        cur = c.execute(
            f"DELETE FROM option_flow_daily "
            f"WHERE date IN ({date_filter}) AND ticker IN ({ticker_filter})"
        )
        return cur.rowcount


def get_flow_daily(
    since_date: str | None = None, ticker: str | None = None,
    min_notional: float = 0, min_oi: int = 0, side: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Query per-contract daily flow, sorted by total_notional desc."""
    clauses = ["1=1"]
    args: list[Any] = []
    if since_date:
        clauses.append("date >= ?")
        args.append(since_date)
    if ticker:
        clauses.append("ticker = ?")
        args.append(ticker.upper())
    if min_notional > 0:
        clauses.append("total_notional >= ?")
        args.append(min_notional)
    if min_oi > 0:
        clauses.append("COALESCE(oi, 0) >= ?")
        args.append(min_oi)
    if side and side != "ALL":
        # Dominant side computed client-side from buy/sell/neutral notional
        # but we can pre-filter with heuristic: majority side > 55%
        if side == "BUY":
            clauses.append("buy_notional > sell_notional AND buy_notional > neutral_notional")
        elif side == "SELL":
            clauses.append("sell_notional > buy_notional AND sell_notional > neutral_notional")
        elif side == "NEUTRAL":
            clauses.append("neutral_notional >= buy_notional AND neutral_notional >= sell_notional")

    sql = (
        f"SELECT * FROM option_flow_daily WHERE {' AND '.join(clauses)} "
        f"ORDER BY total_notional DESC LIMIT ?"
    )
    args.append(limit)

    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]
