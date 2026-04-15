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

_message_times: deque[float] = deque()
_ticker_last_sent: dict[str, float] = {}


def _can_send(ticker: str = "", priority: bool = False, force: bool = False) -> bool:
    """Check if we can send a message without being spammy."""
    if force:
        return True  # Mir Discord signals bypass all rate limits

    now = time.time()

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

    if otype == "CALL" and side == "ASK":
        action = "🟢 BUY CALLS — big money buying"
        trade = f">> {ticker} ${call_strike}C {exp}"
    elif otype == "CALL" and side == "BID":
        action = "🔴 BUY PUTS — big money dumping calls"
        trade = f">> {ticker} ${put_strike}P {exp}"
    elif otype == "PUT" and side == "ASK":
        action = "🔴 BUY PUTS — big money buying protection"
        trade = f">> {ticker} ${put_strike}P {exp}"
    elif otype == "PUT" and side == "BID":
        action = "🟢 BUY CALLS — big money selling puts (bullish)"
        trade = f">> {ticker} ${call_strike}C {exp}"
    else:
        action = f"🟡 NEUTRAL — {side}"
        trade = ""

    return (
        f"{emoji} <b>FLOW{conv_badge}</b>: {alert['ticker']}\n"
        f"<b>{action}</b>\n"
        f"${alert['strike']} {otype} {alert.get('expiration', '')}\n"
        f"Vol: {alert.get('volume', 0):,} | OI: {alert.get('oi', 0):,} | {alert.get('vol_oi', 0)}x\n"
        f"Notional: ${alert.get('notional', 0):,.0f} | Spot: ${alert.get('spot', 0):.2f}\n"
        f"{trade}"
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
    ]
    return "\n".join(l for l in lines if l is not None)


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
