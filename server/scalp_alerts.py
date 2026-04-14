"""SPY/QQQ Scalp Alert System — Structure-based intraday alerts.

Separate from SOE signal engine. Runs every 30 seconds and fires
Telegram alerts when price interacts with GEX structural levels.

No scoring, no grades. Just fast, actionable structure alerts with
0DTE contract suggestions.

Trigger conditions:
  - FLOOR BOUNCE: spot within 0.5% of floor (BUY CALLS)
  - KING APPROACH: spot within 0.3% of king (TAKE PROFIT zone)
  - FLOOR BREAK: spot drops below floor (BUY PUTS)
  - ZGL CROSS UP: spot crosses above ZGL (regime improving)
  - ZGL CROSS DOWN: spot crosses below ZGL (regime deteriorating)
  - CEILING TEST: spot within 0.3% of ceiling (potential rejection)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .cache import cache

# Which tickers get scalp alerts
SCALP_TICKERS = {"SPY", "QQQ"}

# Cooldowns: prevent alert spam
_last_alert: dict[str, float] = {}  # "ticker:alert_type" -> timestamp
ALERT_COOLDOWN = 900  # 15 minutes per ticker per alert type

# Track previous state for cross detection
_prev_state: dict[str, dict[str, Any]] = {}


def _can_alert(ticker: str, alert_type: str) -> bool:
    key = f"{ticker}:{alert_type}"
    last = _last_alert.get(key, 0)
    return (time.time() - last) > ALERT_COOLDOWN


def _record_alert(ticker: str, alert_type: str) -> None:
    _last_alert[f"{ticker}:{alert_type}"] = time.time()


def _suggest_contract(ticker: str, spot: float, direction: str, king: float = 0) -> str:
    """Suggest a 0DTE contract based on direction."""
    import datetime
    today = datetime.date.today().isoformat()

    if direction == "CALLS":
        # ATM or slightly OTM call
        strike = round(spot / 1) if spot < 50 else round(spot / 5) * 5
        return f"{ticker} ${strike}C {today}"
    else:
        strike = round(spot / 1) if spot < 50 else round(spot / 5) * 5
        return f"{ticker} ${strike}P {today}"


async def _check_scalp_alerts() -> list[dict[str, Any]]:
    """Check all scalp tickers for structure alerts. Returns list of alerts."""
    import datetime

    now = datetime.datetime.now()
    # Only during market hours
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return []
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return []

    # Mir rule + backtest confirmed: only PM momentum and power hour have edge
    # AM_MOMENTUM: 48% WR, 0% EV — disabled for live per ChatGPT final review
    # CHOP: not tested, Mir avoids — disabled
    # PM_MOMENTUM: 58% WR, +0.24% — enabled
    # POWER_HOUR: 62% WR, +0.37% — enabled (best window)
    mins = now.hour * 60 + now.minute
    if mins < 810:  # Before 1:30 PM — no scalp alerts
        return []

    alerts: list[dict[str, Any]] = []

    for ticker in SCALP_TICKERS:
        state = await cache.get(ticker)
        if not state:
            continue

        spot = state.get("actual_spot") or state.get("_spot") or 0
        king = state.get("king") or 0
        floor_val = state.get("floor") or 0
        ceiling = state.get("ceiling") or 0
        zgl = state.get("zgl") or 0
        signal = state.get("signal", "")
        regime = state.get("regime", "")
        king_pos = state.get("king_pos", True)

        if not spot or not king:
            continue

        prev = _prev_state.get(ticker, {})
        prev_spot = prev.get("spot", spot)

        # Volume confirmation: skip transitions in dead tape
        # (ChatGPT: "add lightweight second confirmation — VWAP, volume expansion")
        ed = state.get("exp_data", {}).get("MACRO (ALL 200D)", {})
        # Use total GEX magnitude as a proxy for options activity
        gex_magnitude = abs(ed.get("pos_gex", 0)) + abs(ed.get("neg_gex", 0))
        if gex_magnitude < 1_000_000:  # Less than $1M total GEX = dead tape
            continue

        # Only fire on STATE TRANSITIONS — not proximity persistence.
        # "Cream of the crop" = the moment price CROSSES a level or
        # BOUNCES off it with confirmation, not while it sits near it.

        prev_floor = prev.get("floor", floor_val)
        prev_king = prev.get("king", king)

        # ── BUY THE DIP: price dipped to floor and is now bouncing ─
        # Trigger: prev was within 0.3% of floor (or below), now moving away up
        if floor_val and spot > floor_val:
            was_at_floor = prev_spot and prev_spot <= floor_val * 1.003
            now_bouncing = spot > floor_val * 1.003
            if was_at_floor and now_bouncing and _can_alert(ticker, "BUY_DIP"):
                contract = _suggest_contract(ticker, spot, "CALLS", king)
                king_dist = ((king - spot) / spot * 100) if king > spot else 0
                alerts.append({
                    "ticker": ticker,
                    "type": "BUY_DIP",
                    "emoji": "🟢",
                    "headline": "BUY THE DIP — Floor held, bouncing",
                    "detail": (
                        f"Spot ${spot:.2f} bounced off Floor ${floor_val}\n"
                        f"King magnet: ${king} ({king_dist:+.1f}%)\n"
                        f"Regime: {regime} | Signal: {signal}\n"
                        f"Stop below floor, target king"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": king,
                    "stop": floor_val * 0.997,  # Just below floor
                })
                _record_alert(ticker, "BUY_DIP")

        # ── BREAKOUT: price crosses above king ────────────────────
        # Trigger: prev was below king, now above — breakout above magnet
        if king and king_pos and prev_spot and prev_spot < king and spot >= king:
            if _can_alert(ticker, "BREAKOUT"):
                # Target: next gatekeeper or ceiling
                target = ceiling if ceiling and ceiling > king else king * 1.01
                contract = _suggest_contract(ticker, spot, "CALLS", target)
                alerts.append({
                    "ticker": ticker,
                    "type": "BREAKOUT",
                    "emoji": "🚀",
                    "headline": "BREAKOUT — Price cleared King",
                    "detail": (
                        f"Spot ${spot:.2f} broke above King ${king}\n"
                        f"Dealers now chasing — momentum accelerating\n"
                        f"Next target: ${target:.2f}\n"
                        f"Stop: King retest ${king}"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": target,
                    "stop": king,
                })
                _record_alert(ticker, "BREAKOUT")

        # ── RETEST: price pulled back to king from above (buy the retest)
        if king and king_pos and prev_spot and prev_spot > king * 1.003 and spot <= king * 1.003 and spot >= king * 0.997:
            if _can_alert(ticker, "RETEST"):
                contract = _suggest_contract(ticker, spot, "CALLS", ceiling or king * 1.02)
                alerts.append({
                    "ticker": ticker,
                    "type": "RETEST",
                    "emoji": "🔄",
                    "headline": "RETEST — King pullback entry",
                    "detail": (
                        f"Spot ${spot:.2f} retesting King ${king} from above\n"
                        f"King is +GEX — dealers support at this level\n"
                        f"Classic breakout-retest entry\n"
                        f"Stop below king, target ceiling"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": ceiling or king * 1.02,
                    "stop": king * 0.995,
                })
                _record_alert(ticker, "RETEST")

        # ── SELL THE POP: price hit ceiling and rejecting ──────────
        if ceiling and ceiling > spot and prev_spot and prev_spot >= ceiling * 0.997 and spot < ceiling * 0.997:
            if _can_alert(ticker, "SELL_POP"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "SELL_POP",
                    "emoji": "🔴",
                    "headline": "SELL THE POP — Ceiling rejection",
                    "detail": (
                        f"Spot ${spot:.2f} rejected at Ceiling ${ceiling}\n"
                        f"GEX resistance confirmed — dealers selling\n"
                        f"Target: King ${king} | Stop: above ceiling"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": king,
                    "stop": ceiling * 1.003,
                })
                _record_alert(ticker, "SELL_POP")

        # ── FLOOR BREAK: breakdown below support ──────────────────
        if floor_val and spot < floor_val and prev_spot and prev_spot >= floor_val:
            if _can_alert(ticker, "FLOOR_BREAK"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "FLOOR_BREAK",
                    "emoji": "💥",
                    "headline": "FLOOR BREAK — Air pocket below",
                    "detail": (
                        f"Spot ${spot:.2f} broke Floor ${floor_val}\n"
                        f"Entering negative gamma — dealers amplifying\n"
                        f"Next support: ZGL ${zgl}\n"
                        f"Let runners ride, stop above floor"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": zgl,
                    "stop": floor_val * 1.003,
                })
                _record_alert(ticker, "FLOOR_BREAK")

        # ── ZGL CROSS: regime change ──────────────────────────────
        if zgl and spot > zgl and prev_spot and prev_spot <= zgl:
            if _can_alert(ticker, "ZGL_CROSS_UP"):
                contract = _suggest_contract(ticker, spot, "CALLS", king)
                alerts.append({
                    "ticker": ticker,
                    "type": "ZGL_CROSS_UP",
                    "emoji": "⚡",
                    "headline": "REGIME CHANGE — Positive gamma zone",
                    "detail": (
                        f"Spot ${spot:.2f} crossed above ZGL ${zgl}\n"
                        f"Dealers now stabilizing — buy dips supported\n"
                        f"King target: ${king}"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": king,
                    "stop": zgl * 0.997,
                })
                _record_alert(ticker, "ZGL_CROSS_UP")

        if zgl and spot < zgl and prev_spot and prev_spot >= zgl:
            if _can_alert(ticker, "ZGL_CROSS_DOWN"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "ZGL_CROSS_DOWN",
                    "emoji": "⚡",
                    "headline": "REGIME CHANGE — Negative gamma zone",
                    "detail": (
                        f"Spot ${spot:.2f} crossed below ZGL ${zgl}\n"
                        f"Dealers amplifying moves — momentum trades\n"
                        f"Floor: ${floor_val}"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": floor_val,
                    "stop": zgl * 1.003,
                })
                _record_alert(ticker, "ZGL_CROSS_DOWN")

        # Store state for next cycle
        _prev_state[ticker] = {"spot": spot, "king": king, "floor": floor_val, "zgl": zgl}

    return alerts


def _get_window() -> tuple[str, str]:
    """Get current time window and quality label."""
    import datetime
    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute

    if mins < 630:
        return "AVOID", "First hour — Mir: 'wait an hour after the bell'"
    if 630 <= mins < 690:
        return "AM_SETTLED", "Post-open settled"
    if 690 <= mins < 810:
        return "CHOP", "Midday chop — low probability"
    if 810 <= mins < 900:
        return "PM_MOMENTUM", "Afternoon momentum"
    if 900 <= mins < 960:
        return "POWER_HOUR", "Mir's top window — 'biggest plays in final minutes'"
    return "CLOSED", "Market closed"


def format_scalp_alert(alert: dict[str, Any]) -> str:
    """Format a scalp alert for Telegram."""
    window, window_note = _get_window()

    lines = [
        f"{alert['emoji']} <b>{alert['ticker']} {alert['headline']}</b>",
        f"",
        alert['detail'],
    ]
    if alert.get('contract'):
        lines.append(f"")
        lines.append(f">> <b>{alert['contract']}</b>")
    if alert.get('target') and alert.get('stop'):
        lines.append(f"Target: ${alert['target']:.2f} | Stop: ${alert['stop']:.2f}")

    # Window quality from Mir + backtest
    lines.append(f"")
    if window == "POWER_HOUR":
        lines.append(f"⏰ POWER HOUR — highest EV window (backtest: +0.43%/trade)")
    elif window == "PM_MOMENTUM":
        lines.append(f"⏰ PM momentum — good window (backtest: +0.15%/trade)")
    elif window == "AM_SETTLED":
        lines.append(f"⏰ Morning — lower EV, be selective")
    elif window == "CHOP":
        lines.append(f"⚠️ Midday chop — Mir avoids this window")

    lines.append(f"🔥 0DTE HIGH RISK | 1DTE preferred for buffer")
    return "\n".join(lines)


async def run_scalp_scanner(stop_event: asyncio.Event) -> None:
    """Background loop: check structure alerts every 30 seconds."""
    await asyncio.sleep(90)  # Wait for first GEX cycle to populate cache

    while not stop_event.is_set():
        try:
            alerts = await _check_scalp_alerts()
            if alerts:
                from .telegram import send
                for a in alerts:
                    msg = format_scalp_alert(a)
                    await send(msg, ticker=a["ticker"], priority=True)
                    print(f"[SCALP] {a['ticker']} {a['type']}: {a['headline']}")
        except Exception as e:
            print(f"[SCALP] error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
