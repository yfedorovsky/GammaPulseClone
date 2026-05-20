"""Centralized Telegram notification manager.

Prevents alert spam by enforcing:
  - Global rate limit: max 6 messages per 5 minutes
  - Per-ticker cooldown: max 1 alert per ticker per 15 minutes
  - Priority system: A/A+ SOE signals always get through, flow alerts throttled

All modules should use send() instead of their own Telegram calls.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx

from .config import get_settings

# ── Rate limiting ─────────────────────────────────────────────────────
MAX_MESSAGES_PER_WINDOW = 3      # max messages in the window
WINDOW_SECONDS = 600              # 10 minute window
TICKER_COOLDOWN_SECONDS = 3600    # 1 hour per ticker

# Per-ticker DAILY cap (added 2026-05-20 per Perplexity recommendation —
# alert density vs quality). Max 5 alerts per ticker per session for
# normal alerts; 10 for priority/force alerts (SOE A+, Mir ENTRY,
# GEX MAGNET). Resets each calendar day at midnight ET.
PER_TICKER_DAILY_CAP = 5
PER_TICKER_DAILY_CAP_PRIORITY = 10

_message_times: deque[float] = deque()
_ticker_last_sent: dict[str, float] = {}
# (ticker, day_str) -> count
_ticker_daily_count: dict[tuple[str, str], int] = {}


def _today_str() -> str:
    """ET calendar day (server assumed ET)."""
    import datetime as _dt
    return _dt.datetime.now().date().isoformat()


def _can_send(ticker: str = "", priority: bool = False, force: bool = False) -> bool:
    """Check if we can send a message without being spammy."""
    now = time.time()

    # Per-ticker DAILY cap — applies to ALL alerts including force,
    # but priority/force gets the higher cap (10/day vs 5/day).
    # Without this gate, force=True alerts in the same ticker can spam
    # 20+ times in a session.
    if ticker:
        day = _today_str()
        key = (ticker, day)
        cap = PER_TICKER_DAILY_CAP_PRIORITY if (priority or force) else PER_TICKER_DAILY_CAP
        if _ticker_daily_count.get(key, 0) >= cap:
            return False

    if force:
        return True  # Mir Discord signals bypass per-message rate limits

    # Priority messages (A/A+ signals) bypass rate limit but not ticker cooldown
    if not priority:
        # Trim old timestamps
        while _message_times and _message_times[0] < now - WINDOW_SECONDS:
            _message_times.popleft()
        if len(_message_times) >= MAX_MESSAGES_PER_WINDOW:
            return False

    # Per-ticker cooldown
    if ticker:
        last = _ticker_last_sent.get(ticker, 0)
        if now - last < TICKER_COOLDOWN_SECONDS:
            return False

    return True


def _record_sent(ticker: str = "") -> None:
    now = time.time()
    _message_times.append(now)
    if ticker:
        _ticker_last_sent[ticker] = now
        # Bump daily counter
        key = (ticker, _today_str())
        _ticker_daily_count[key] = _ticker_daily_count.get(key, 0) + 1


async def send(
    text: str,
    ticker: str = "",
    priority: bool = False,
    suppress: bool = False,
    force: bool = False,
) -> bool:
    """Send a Telegram message with rate limiting.

    Args:
        text: Message text
        ticker: Ticker symbol for per-ticker cooldown
        priority: If True, bypass global rate limit (still respects ticker cooldown)
        suppress: If True, skip entirely (used by 0DTE experimental)
        force: If True, bypass ALL rate limits (for Mir Discord signals)

    Returns True if sent, False if rate-limited or suppressed.
    """
    if suppress:
        return False

    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return False

    if not _can_send(ticker, priority, force):
        return False

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": s.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        _record_sent(ticker)
        return True
    except Exception as e:
        print(f"[TELEGRAM] send failed: {e}")
        return False


# ── Pre-formatted message builders ───────────────────────────────────

def format_flow_alert(alert: dict[str, Any]) -> str:
    sentiment = alert.get("sentiment", "NEUTRAL")
    emoji = "🟢" if sentiment == "BULLISH" else "🔴" if sentiment == "BEARISH" else "🟡"
    conv = alert.get("conviction", "")
    conv_badge = f" [{conv}]" if conv else ""
    otype = (alert.get("option_type") or "").upper()
    side = alert.get("side", "?")

    # What to do — follow the smart money
    spot = alert.get('spot', 0)
    king = alert.get('king', 0)
    exp = alert.get('expiration', '')
    strike_val = alert.get('strike', 0)
    ticker = alert['ticker']

    # Suggest a contract based on the flow direction
    # For calls: ATM or slightly OTM call near king
    # For puts: ATM or slightly OTM put near floor
    if spot:
        call_strike = round(spot / 5) * 5 if spot > 50 else round(spot)
        put_strike = call_strike
    else:
        call_strike = strike_val
        put_strike = strike_val

    # Signal quality tiers based on V/OI (volume vs open interest ratio):
    #   V/OI < 1.0x   → existing OI dominates (weakest — mostly OI noise)
    #   V/OI 1.0-1.5x → moderate new positioning (confirm with other signals)
    #   V/OI >= 1.5x  → strong new positioning (prescribe trade)
    # Extreme notional ($10M+) bypasses V/OI — meaningful regardless.
    vol_oi = alert.get('vol_oi', 0) or 0
    notional = alert.get('notional', 0) or 0
    strong_signal = vol_oi >= 1.5 or notional >= 10_000_000
    moderate_signal = (1.0 <= vol_oi < 1.5) and not strong_signal

    def _tier_suffix() -> str:
        if strong_signal:
            return ""
        if moderate_signal:
            return " — moderate new positioning (confirm)"
        return " — existing OI dominates (weak signal)"

    if otype == "CALL" and side == "ASK":
        action = "🟢 BUY CALLS — big money buying" if strong_signal else f"🟢 CALL BUYING{_tier_suffix()}"
        trade = f">> {ticker} ${call_strike}C {exp}" if strong_signal else ""
    elif otype == "CALL" and side == "BID":
        # CALL + BID is ambiguous: bearish shorting OR covered-call income OR rolling.
        if strong_signal:
            action = "🔴 BEARISH CALL SELLING — new positioning (verify vs. put flow)"
            trade = f">> {ticker} ${put_strike}P {exp}"
        elif moderate_signal:
            action = "🔴 CALL SELLING — moderate new positioning (may be bearish OR covered-call)"
            trade = ""
        else:
            action = "🔴 CALL SELLING — existing OI dominates; likely covered-call / roll"
            trade = ""
    elif otype == "PUT" and side == "ASK":
        action = "🔴 BUY PUTS — big money buying protection" if strong_signal else f"🔴 PUT BUYING{_tier_suffix()}"
        trade = f">> {ticker} ${put_strike}P {exp}" if strong_signal else ""
    elif otype == "PUT" and side == "BID":
        # PUT + BID: bullish cash-secured OR hedge unwind.
        if strong_signal:
            action = "🟢 BUY CALLS — big money selling puts (bullish)"
            trade = f">> {ticker} ${call_strike}C {exp}"
        elif moderate_signal:
            action = "🟢 PUT SELLING — moderate new positioning (bullish cash-secured or hedge unwind)"
            trade = ""
        else:
            action = "🟢 PUT SELLING — existing OI dominates; likely hedge unwind"
            trade = ""
    else:
        action = f"🟡 NEUTRAL — {side}"
        trade = ""

    # P0.7: earnings badge — read from sync cache (hydrated by
    # flow_alerts._send_telegram before calling here, so cache is warm).
    er_line = ""
    try:
        from .earnings_calendar import earnings_badge_sync
        er = earnings_badge_sync(ticker)
        if er:
            er_line = f"\n{er}"
    except Exception:
        pass

    # P0.8: Fidget-style tag taxonomy (WHALE / PREM $XM / LEAPS / etc).
    tag_line = ""
    try:
        from .alert_tags import tags_for_flow_alert, format_tags
        tags = tags_for_flow_alert(alert)
        if tags:
            tag_line = f"\n{format_tags(tags)}"
    except Exception:
        pass

    return (
        f"{emoji} <b>FLOW{conv_badge}</b>: {alert['ticker']}\n"
        f"<b>{action}</b>\n"
        f"${alert['strike']} {otype} {alert.get('expiration', '')}\n"
        f"Vol: {alert.get('volume', 0):,} | OI: {alert.get('oi', 0):,} | {alert.get('vol_oi', 0)}x\n"
        f"Notional: ${alert.get('notional', 0):,.0f} | Spot: ${alert.get('spot', 0):.2f}\n"
        f"{trade}"
        f"{tag_line}"
        f"{er_line}"
    )


def format_soe_signal(sig: dict[str, Any]) -> str:
    grade = sig.get("grade", "?")
    direction = sig.get("direction", "?")
    ticker = sig.get("ticker", "?")
    signal_type = sig.get("signal_type", "?")
    strike = sig.get("strike", 0)
    otype = (sig.get("option_type") or "").upper()
    exp = sig.get("expiration", "")
    score = sig.get("score", 0)
    max_score = sig.get("max_score", 6)
    rr = sig.get("rr_ratio", 0)
    source = sig.get("greeks_source", "tradier")
    spot = sig.get("spot", 0)
    target = sig.get("target", 0)
    stop = sig.get("stop", 0)
    target_label = sig.get("target_label", "")
    stop_label = sig.get("stop_label", "")
    mid = sig.get("mid_price", 0)
    kelly = sig.get("kelly_size_pct")

    dte = sig.get("dte")
    is_0dte = dte is not None and dte == 0
    emoji = "🔥" if grade == "A+" else "⚡" if grade == "A" else "📊"
    dte_badge = "🔥 0DTE HIGH RISK" if is_0dte else f"{dte}d" if dte else ""
    # Rule #3b — contract-drift warning for B+ alerts.
    # Last week's attribution: SOE_B+ MEDIUM matches (same ticker+type,
    # different strike/exp) = 10 trades, 30% WR, -$777. STRONG matches
    # (exact contract) = 14 trades, 86% WR, +$4,386. The contract IS
    # the signal — drifting to a nearby strike kills the thesis.
    drift_warning = (
        "⚠️ TRADE THIS EXACT CONTRACT — drift = -$777 last wk (30% WR)"
        if grade == "B+" else None
    )

    # Convergence FLAG (Apr 27 v2 — was a score bonus, now informational
    # only after 4-LLM critique on concentration risk). When system signals
    # agree, surface them but DO NOT promote the grade. Reader's job to
    # decide if convergence adds confidence or signals crowding.
    conv_reasons = sig.get("convergence_reasons", []) or []
    convergence_block = None
    if conv_reasons:
        convergence_block = (
            f"🔎 <b>CONVERGENCE FLAG</b> (informational, not score-boosted)\n"
            + "\n".join(f"  ↳ {r}" for r in conv_reasons)
        )

    # High-score FADE WATCH — Apr 27 (4-LLM consensus). Phase 6 audit
    # shows score >= 4.8 historically inverts (5.0+ = 20% 1d hit). When
    # the SOE engine fires above this threshold, auto-trade is blocked
    # and we surface a prominent fade-watch warning with recommended size.
    high_score_fade_block = None
    if sig.get("is_high_score_fade"):
        size_mult = sig.get("high_score_fade_size_mult", 0.25)
        high_score_fade_block = (
            f"⚠ <b>HIGH-SCORE FADE WATCH</b> — score {score} ≥ 4.8\n"
            f"  ↳ historical: 5.0+ = 20% 1d hit, 3.75-4.1 = 67%\n"
            f"  ↳ AUTO-TRADE BLOCKED. If taking manually: size at "
            f"<b>{size_mult}× base</b> (mean-reversion risk dominates)"
        )

    # Earnings + IVR block (2026-05-20 — Perplexity recommendation #2).
    # Surfaces ER-in-window risk + IV rank percentile so the trader knows
    # the structural IV crush + premium-pay exposure at entry. Multi-day
    # alerts only (0DTE/1DTE are different setups).
    er_ivr_block = None
    if dte is not None and dte >= 2:
        try:
            from .earnings_calendar import er_in_window_sync
            er_in_win, days_to_er = er_in_window_sync(ticker, dte)
            ivr = sig.get("iv_rank") or sig.get("ivp")
            parts = []
            if er_in_win:
                parts.append(f"⚠️ <b>EARNINGS IN WINDOW</b>: ER in {days_to_er}d "
                            f"(within {dte}-day DTE) — IV crush risk on close")
            if ivr is not None:
                try:
                    ivr_v = float(ivr)
                    ivr_pct = ivr_v if ivr_v <= 100 else ivr_v / 100
                    if ivr_pct > 75:
                        parts.append(f"⚠️ <b>IVR: {ivr_pct:.0f}</b> (>75th pct) — "
                                    "long premium structurally expensive")
                    elif ivr_pct < 25:
                        parts.append(f"✅ <b>IVR: {ivr_pct:.0f}</b> (<25th pct) — "
                                    "long premium cheap")
                    else:
                        parts.append(f"IVR: {ivr_pct:.0f}")
                except (ValueError, TypeError):
                    pass
            if parts:
                er_ivr_block = "\n".join(parts)
        except Exception:
            pass

    # Macro regime footer — Apr 27 shadow mode. Compact one-liner so
    # the trader sees regime context at the moment of decision, not just
    # in postmortem. NONE = no badge (avoid clutter on normal days).
    regime_tag = sig.get("macro_regime_tag", "NONE") or "NONE"
    regime_reasons = sig.get("macro_regime_reasons", []) or []
    regime_footer = None
    if regime_tag != "NONE":
        # Visual badge by severity
        badge = {"SOFT": "⚪", "HARD": "⚠", "A_ONLY": "🛑"}.get(regime_tag, "·")
        # Compact reason — first 2 reasons joined with ' | ', max ~60 chars
        reason_str = " | ".join(regime_reasons[:2])[:60]
        regime_footer = (
            f"{badge} <b>Regime: {regime_tag}</b>"
            + (f" — {reason_str}" if reason_str else "")
            + " <i>(shadow)</i>"
        )

    lines = [
        f"{emoji} <b>SOE {grade}</b>: {direction} {ticker}",
        f"<b>{signal_type}</b>",
        f"${strike} {otype} {exp}" + (f"  <b>{dte_badge}</b>" if dte_badge else ""),
        f"",
        f"Entry: ${spot:.2f}" if spot else None,
        f"Target: ${target:.2f} ({target_label})" if target else None,
        f"Stop: ${stop:.2f} ({stop_label})" if stop else None,
        f"R:R: {rr}x | Score: {score}/{max_score}",
        f"Mid: ${mid:.2f}" if mid else None,
        f"Size: {kelly}%" if kelly else None,
        f"Greeks: {source.upper()}",
        er_ivr_block,  # ER-in-window + IVR pct (2026-05-20)
        high_score_fade_block,  # Above convergence so the warning lands first
        convergence_block,
        drift_warning,
        regime_footer,
    ]
    return "\n".join(l for l in lines if l is not None)


def format_basket_alert(alert: dict[str, Any]) -> str:
    """Format a multi-strike basket alert for Telegram (Bug #6 2026-05-12).

    Example output:
      🟢 BASKET — MU 2026-05-15 CALL
      12 strikes 800–1000 | ASK-dominant
      Aggregate: 18,432 vol | $3.5M premium
      Spot: $766.28
      Strikes:
        $800C: 1,247 vol @ $20.49  ($2.56M)
        $850C: 612 vol @ $9.73  ($595K)
        ... (10 more)
    """
    ticker = alert.get("ticker", "?")
    exp = alert.get("expiration", "?")
    otype = alert.get("option_type", "").upper()
    sentiment = alert.get("sentiment", "NEUTRAL")
    emoji = "🟢" if sentiment == "BULLISH" else "🔴" if sentiment == "BEARISH" else "🟡"
    side_label = "ASK-dominant" if (
        (otype == "CALL" and sentiment == "BULLISH")
        or (otype == "PUT" and sentiment == "BEARISH")
    ) else "BID-dominant"

    n = alert.get("strike_count", 0)
    lo = alert.get("strike_low", 0)
    hi = alert.get("strike_high", 0)
    vol = alert.get("aggregate_vol", 0)
    notional = alert.get("aggregate_notional", 0)
    spot = alert.get("spot", 0)

    strikes = alert.get("strikes", []) or []
    # Sort by notional desc and show top 6
    top_strikes = sorted(strikes, key=lambda x: -x.get("notional", 0))[:6]
    strike_lines = []
    for s in top_strikes:
        strike_lines.append(
            f"  ${int(s['strike']) if s['strike'].is_integer() else s['strike']}{otype[0]}: "
            f"{s['vol']:,} @ ${s['last']:.2f}  (${s['notional']/1_000_000:.2f}M)"
            if s.get('notional', 0) >= 1_000_000
            else
            f"  ${int(s['strike']) if s['strike'].is_integer() else s['strike']}{otype[0]}: "
            f"{s['vol']:,} @ ${s['last']:.2f}  (${s['notional']/1_000:.0f}K)"
        )
    extra = len(strikes) - len(top_strikes)
    if extra > 0:
        strike_lines.append(f"  + {extra} more strike{'s' if extra != 1 else ''}")

    # P0.7 earnings badge (sync cache read — assumed hydrated by caller).
    er_line = ""
    try:
        from .earnings_calendar import earnings_badge_sync
        er = earnings_badge_sync(ticker)
        if er:
            er_line = f"\n{er}"
    except Exception:
        pass

    # P0.8 tag taxonomy
    tag_line = ""
    try:
        from .alert_tags import tags_for_basket, format_tags
        tags = tags_for_basket(alert)
        if tags:
            tag_line = f"\n{format_tags(tags)}"
    except Exception:
        pass

    return (
        f"{emoji} <b>BASKET</b> — {ticker} {exp} {otype}\n"
        f"<b>{n} strikes ${lo:g}–{hi:g}</b> | {side_label}\n"
        f"Aggregate: {vol:,} vol | ${notional:,.0f} premium\n"
        f"Spot: ${spot:.2f}{er_line}{tag_line}\n"
        f"Top strikes by notional:\n"
        + "\n".join(strike_lines)
    )


def format_exit_signal(signal: dict[str, Any]) -> str:
    sig_type = signal.get("signal_type", "?")
    ticker = signal.get("ticker", "?")
    spot = signal.get("spot") or signal.get("option_price") or 0
    msg = signal.get("message", "")
    emoji = "🎯" if "PROFIT" in sig_type or "KING_HIT" in sig_type else "🚨"
    spot_str = f"${spot:.2f}" if spot else "N/A"
    return (
        f"{emoji} <b>EXIT: {sig_type}</b>\n"
        f"{ticker} @ {spot_str}\n"
        f"{msg}"
    )
