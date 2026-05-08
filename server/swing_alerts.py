"""Telegram alerts for new swing-watchlist entrants.

Purpose: When a ticker enters the swing scanner Top 10 for the first time
this session (crosses the hysteresis threshold), send a Telegram with
score + contract ladder so the user doesn't miss early-session leaders
while away from the screen.

## Architecture

- Swing scanner already marks `_new_entry = True` on tickers that cross
  INTO the Top 10 this cycle (natural dedup via `_prev_top`).
- This module adds a SECOND dedup layer: per-ticker-per-day. A ticker
  that flickers in/out of Top 10 only alerts once per trading day.
- Market-hours gate: alerts only fire 9:45 AM - 4:00 PM ET (skip
  pre-open noise and post-close stale data).
- Reuses `runner_tracker._build_contract_ladder` for shape-agnostic
  contract suggestions (DRY with runner Day 1 alerts).

## Distinction from runner tracker alerts

Runner tracker fires on DAY1_BREAKOUT which requires:
  - gain ≥ max(1.5%, 0.6 × ADR)
  - RVOL ≥ 1.1x
  - RTS ≥ 50 (SWING path)
  - Close above EMA21
  - Close in top 35% of range (RECLAIM path)

Swing watchlist entry is SOFTER — ranks top 10 by continuous score
(RS 40% + RVOL 30% + ADR% 20% + sector 10%). A ticker can enter the
watchlist without yet satisfying runner criteria.

So this alert is "early interest" signal, not "confirmed breakout".
Complementary to runner tracker, not redundant.
"""
from __future__ import annotations

import datetime
from typing import Any


# ── Dedup state ───────────────────────────────────────────────────────

# date_iso -> set of tickers alerted today
_alerted_today: dict[str, set[str]] = {}

# Last cleanup date — prevents unbounded memory growth across sessions
_last_prune_date: str = ""


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _prune_if_date_rolled() -> None:
    """Drop fired-ticker records older than 2 days."""
    global _last_prune_date
    today = _today_iso()
    if _last_prune_date == today:
        return
    cutoff = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    dead = [d for d in _alerted_today if d < cutoff]
    for d in dead:
        del _alerted_today[d]
    _last_prune_date = today


def _is_market_hours() -> bool:
    """Only fire alerts 9:45 AM - 4:00 PM ET on weekdays.

    The 15-min buffer after open lets the swing scanner stabilize — the
    first few cycles have bogus RVOL (volume accumulates from 0) which
    would flag everyone as a new entrant.
    """
    try:
        import pytz
        et = datetime.datetime.now(pytz.timezone("America/New_York"))
    except ImportError:
        et = datetime.datetime.now()

    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 45 <= minutes < 16 * 60


# ── Main hook ─────────────────────────────────────────────────────────

async def maybe_alert_new_entrants(
    results: list[dict[str, Any]], meta: dict[str, Any]
) -> None:
    """Scan swing scanner results for `_new_entry == True` and fire Telegram
    alerts for any ticker not already alerted today.

    Safe to call every cycle — the natural dedup via `_prev_top` in the
    scanner means `_new_entry` is only True on the transition cycle.
    This module adds a day-level dedup on top so flicker-in/out doesn't
    re-alert.

    `results` is the full list from compute_swing_watchlist (already sorted
    by score). `meta` has spy_regime, sector_ranks, etc. for context.
    """
    _prune_if_date_rolled()

    if not _is_market_hours():
        return

    today = _today_iso()
    alerted = _alerted_today.setdefault(today, set())

    new_entries = [r for r in results if r.get("_new_entry") and r.get("_in_watchlist")]
    if not new_entries:
        return

    # Pull fresh snapshot once for contract lookup (shared across all alerts)
    try:
        from .cache import cache
        snapshot = await cache.snapshot()
    except Exception:
        snapshot = {}

    for r in new_entries:
        ticker = r.get("ticker")
        if not ticker or ticker in alerted:
            continue

        # Basic quality gate: require real data (avoid 0 RVOL pre-open edge cases
        # that slip past time gate on weird clock conditions)
        rvol = r.get("rvol") or 0
        if rvol < 0.5:
            continue  # data not accumulated yet

        alerted.add(ticker)
        await _fire_alert(r, meta, snapshot.get(ticker) or {})


# ── Conviction read ───────────────────────────────────────────────────
# Plain-English translation of (RVOL, today_gain%, EXTENDED) into a
# single-line bullishness/skepticism marker shown above the contract
# ladder. Motivated by May 8 2026 alerts where AMD (+9.78%, RVOL 0.77x)
# looked stronger than DDOG (+4.85%, RVOL 3.07x) on first read but was
# actually weaker — RVOL <1 on a +10% day is short cover, not demand.
#
# Tuple values: (level, emoji, message)
#   level: 'HIGH' | 'MEDIUM' | 'LOW' | 'NEUTRAL' — also drives the
#          AGGRESSIVE-tier suppression below.

def _conviction_read(
    rvol: float, gain_pct: float, has_extended: bool
) -> tuple[str, str, str]:
    """Classify the (volume, move size, extension) trifecta into a
    plain-English conviction read.

    Rules tuned against three May 8 2026 reference alerts:
      DDOG (+4.85%, RVOL 3.07x, EXTENDED) → HIGH
      QCOM (+7.58%, RVOL 2.11x, EXTENDED) → MEDIUM
      AMD  (+9.78%, RVOL 0.77x, EXTENDED) → LOW (suspicious)
    """
    # LOW (suspicious) — large move on weak volume = short cover, not demand
    if rvol < 1.0 and gain_pct >= 5.0:
        return (
            "LOW",
            "⚠️",
            f"LOW: large +{gain_pct:.1f}% move on RVOL {rvol:.2f}x "
            "— likely short cover, not demand",
        )
    # LOW (chase risk) — extended + already big move (chasing risk)
    if has_extended and gain_pct >= 8.0:
        return (
            "LOW",
            "⚠️",
            f"LOW: extended +{gain_pct:.1f}% — chase risk, wait for pullback",
        )
    # HIGH — strong volume confirmation with modest gain. Note: we don't
    # require `not EXTENDED` because a stock can be "extended from base"
    # AND still have the cleanest signal if volume is overwhelming and the
    # day's gain is small (DDOG May 8: RVOL 3.07x + only +4.85% = HIGH
    # even though tagged EXTENDED).
    if rvol >= 2.5 and gain_pct <= 6.0:
        return (
            "HIGH",
            "✅",
            f"HIGH: strong volume (RVOL {rvol:.2f}x) + modest extension "
            "— cleanest signal",
        )
    # MEDIUM — volume confirms but stretched. Require gain >= 2.5% so we
    # don't flag a tiny +1% move with mild RVOL as "MEDIUM setup" — those
    # are noise, not setups.
    if rvol >= 1.5 and 2.5 <= gain_pct <= 8.0:
        return (
            "MEDIUM",
            "✓",
            f"MEDIUM: RVOL {rvol:.2f}x confirms but stretched "
            "— wait for pullback to base",
        )
    return ("NEUTRAL", "·", f"NEUTRAL: RVOL {rvol:.2f}x · +{gain_pct:.2f}%")


def _suppress_aggressive_tier(ladder_block: str) -> str:
    """Drop the AGGRESSIVE line from a contract-ladder block when the
    conviction read is LOW. Rationale: when our own RVOL+extension signal
    says 'low conviction breakout', recommending the highest-leverage
    short-DTE contract in the same alert is contradictory. The CORE and
    SAFE tiers stay — they survive a 1-2 day pullback that the
    AGGRESSIVE 5-7 DTE 35Δ contract would not."""
    if not ladder_block:
        return ladder_block
    lines = ladder_block.split("\n")
    out: list[str] = []
    suppressed = False
    for line in lines:
        # The formatter writes "  AGGRESSIVE: $TICKER $STRIKEC ..." — match
        # on the leading "  AGGRESSIVE:" so we don't accidentally eat user
        # text that mentions the word.
        if line.lstrip().startswith("AGGRESSIVE:"):
            suppressed = True
            continue
        out.append(line)
    if suppressed:
        out.append("  [AGGRESSIVE tier hidden — RVOL<1.5 with EXTENDED tag]")
    return "\n".join(out)


async def _fire_alert(
    r: dict[str, Any], meta: dict[str, Any], state: dict[str, Any]
) -> None:
    try:
        from .telegram import send
    except ImportError:
        return

    ticker = r["ticker"]
    score = r.get("swing_score") or 0
    rts = r.get("rts_score") or 0
    rvol = r.get("rvol") or 0
    adr = r.get("adr_pct") or 0
    gain_pct = r.get("today_gain_pct") or r.get("pct_change") or 0
    tags = r.get("tags") or []
    rank = r.get("rank")
    dist_high = r.get("dist_to_high_pct")
    sector = r.get("sector")

    # Contract ladder (reuse runner tracker's logic)
    ladder_block = ""
    try:
        from .runner_tracker import _build_contract_ladder, _format_contract_ladder
        # For new watchlist entries we default to MEASURED shape — we don't
        # yet have multi-day OHLCV evidence that it's a SQUEEZE, so the
        # measured contract ladder (aggressive / core / safe) is the right
        # default. User can upgrade to SQUEEZE framing if it confirms as
        # a runner later.
        if state:
            ladder = _build_contract_ladder(state, "MEASURED")
            if ladder:
                ladder_block = _format_contract_ladder(ladder, ticker)
    except Exception as e:
        print(f"[swing_alerts] contract ladder error for {ticker}: {e}")

    # Tag emojis for visual parseability
    tag_line = ""
    has_extended = "EXTENDED" in (tags or [])
    if tags:
        tag_emojis = {
            "LEADER": "👑", "TOP_SECTOR": "🏆", "FIRST_PULLBACK": "🎯",
            "NEAR_BREAKOUT": "⚡", "CHEAP_IV": "💎", "EXTENDED": "⚠️",
            "MIR_BASKET": "🪣",
        }
        tag_line = "Tags: " + " ".join(
            f"{tag_emojis.get(t, '•')} {t}" for t in tags
        ) + "\n"

    # Plain-English conviction read — reads RVOL+gain+extended as a single
    # signal. Drives the AGGRESSIVE-tier suppression below when LOW.
    level, emoji, conv_msg = _conviction_read(
        float(rvol), float(gain_pct), has_extended,
    )
    conviction_line = f"{emoji} {conv_msg}\n"

    # Suppress AGGRESSIVE contract tier when conviction is LOW. Rationale
    # documented in _suppress_aggressive_tier docstring.
    if level == "LOW":
        ladder_block = _suppress_aggressive_tier(ladder_block)

    # Build the alert
    rank_str = f"#{rank} " if rank is not None else ""
    # NB: dist_high is computed against `high_20d` in swing_scanner, NOT the
    # 52-week high — keep label accurate.
    dist_str = f" | {dist_high:+.1f}% from 20d high" if dist_high is not None else ""

    msg = (
        f"🔍 <b>NEW SWING WATCHLIST ENTRY {rank_str}</b>\n"
        f"<b>${ticker}</b>"
        + (f" ({sector})" if sector else "")
        + f"\n"
        f"SwingScore: {score:.1f} | RTS: {rts:.0f} | RVOL: {rvol:.2f}x\n"
        f"Today: {gain_pct:+.2f}% | ADR: {adr:.1f}%{dist_str}\n"
        f"{tag_line}"
        f"{conviction_line}"
    )

    # Context: SPY regime
    spy_regime = meta.get("spy_regime")
    if spy_regime:
        msg += f"Market: SPY {spy_regime}\n"

    msg += (
        f"\n<i>Soft signal — watchlist entry, not a confirmed breakout.\n"
        f"Runner tracker requires Day 1 gain + RVOL + close quality.</i>\n"
    )
    msg += ladder_block

    try:
        await send(msg, ticker=ticker, force=True)
        print(f"[swing_alerts] NEW WATCHLIST [{ticker}] score={score:.1f} rts={rts:.0f}")
    except Exception as e:
        print(f"[swing_alerts] telegram send failed for {ticker}: {e}")


# ── Diagnostic ────────────────────────────────────────────────────────

def stats() -> dict[str, Any]:
    today = _today_iso()
    return {
        "today": today,
        "alerted_today": sorted(_alerted_today.get(today, set())),
        "count_today": len(_alerted_today.get(today, set())),
        "is_market_hours": _is_market_hours(),
    }


def reset_today() -> int:
    """Clear today's fired tickers so alerts can re-trigger.
    Returns count of cleared entries."""
    today = _today_iso()
    fired = _alerted_today.get(today, set())
    count = len(fired)
    fired.clear()
    return count
