"""0DTE Telegram alert formatter + sender.

Separated from zero_dte_loop.py for clean delegation — the loop decides
WHETHER to fire, this module formats + sends. Same pattern as
live_flow_aggregator's send_golden_telegram.

## Format

Example output:
  🎯 0DTE ALERT · SPX · A+
  🟢 BUY 7050 CALL 2026-04-22

  Entry: $3.20 (bid 3.15 / ask 3.25)
  Target: $9.60  (4.0R)
  Stop:   $1.60  (-50%)
  Time stop: 90min

  Confluence 17/20:
    ★★★★ GEX     MAGNET UP with 0.64% to king $7065
    ★★★★ Flow    NCP +$2.5M/2m · 30s burst +$800K
    ★★★★ Regime  FLOW_LEADS_UP high
    ★★★☆ Sweeps  3 aligned sweeps in 2min, $1.65M aggregate
    ★★☆☆ Golden  1 aligned GOLDEN (B+)

  SPX $7020.00 → target $7065 (0.64% away)
  GEX: MAGNET UP · Flow: FLOW_LEADS_UP
"""
from __future__ import annotations

from typing import Any


def _star_bar(pts: int, max_pts: int = 4) -> str:
    """Render pts/4 as filled/empty stars: 3 → ★★★☆"""
    filled = "★" * pts
    empty = "☆" * (max_pts - pts)
    return f"{filled}{empty}"


def _grade_emoji(grade: str) -> str:
    return {
        "A+": "🎯",
        "A": "🎯",
        "B+": "⚡",
        "B": "•",
        "C": "·",
    }.get(grade, "·")


def _direction_emoji(direction: str) -> str:
    return "🟢" if direction == "bullish" else "🔴" if direction == "bearish" else "⚪"


def format_zero_dte_alert(alert: Any) -> str:
    """Format a ZeroDTEAlert into a Telegram-ready string."""
    # Strike display
    strike = alert.strike
    if strike is not None:
        strike_str = f"${int(strike)}" if strike == int(strike) else f"${strike:.2f}"
    else:
        strike_str = "?"

    right = (alert.right or "call").upper()
    exp = alert.expiration or "?"

    action = "BUY" if alert.direction == "bullish" else "BUY"  # always "BUY" for 0DTE long-premium
    # (Future: support put selling / credit spreads with different action verbs.)

    # Header
    header = (
        f"{_grade_emoji(alert.grade)} 0DTE ALERT · {alert.ticker} · {alert.grade}\n"
        f"{_direction_emoji(alert.direction)} {action} {strike_str} {right} {exp}\n"
    )

    # Pricing block
    entry = alert.est_entry_price
    bid = alert.est_bid
    ask = alert.est_ask
    target = alert.target_mid
    stop = alert.stop_mid
    target_r = alert.target_r

    pricing_lines = []
    if entry is not None:
        quote_detail = ""
        if bid is not None and ask is not None:
            quote_detail = f" (bid {bid:.2f} / ask {ask:.2f})"
        pricing_lines.append(f"Entry:  ${entry:.2f}{quote_detail}")
    if target is not None:
        r_str = f"  ({target_r}R)" if target_r else ""
        pricing_lines.append(f"Target: ${target:.2f}{r_str}")
    if stop is not None and entry is not None:
        loss_pct = (stop - entry) / entry * 100
        pricing_lines.append(f"Stop:   ${stop:.2f}  ({loss_pct:+.0f}%)")
    pricing_lines.append(f"Time stop: {alert.time_stop_minutes}min")
    pricing = "\n".join(pricing_lines)

    # Management reminder — added after Apr 27 audit of 5 0DTE alerts
    # showed avg MFE +90% in ~42min but avg end-of-window -38% (128pp
    # giveback). 100% of alerts gave a +50% scalp at some point; 0/5
    # reached target_mid (3x). Buy-and-hold to time-stop is structurally
    # losing; active management is the entire game.
    manage = (
        "⚠ MANAGE: scalp at +50%, trail rest. "
        "MFE usually in 20-70min — don't hold to time-stop"
    )

    # Confluence breakdown
    conf_header = f"Confluence {alert.total_points}/{alert.max_points}:"
    conf_lines = []
    factor_labels = {
        "gex": "GEX",
        "fast_flow": "Flow",
        "regime": "Regime",
        "sweep": "Sweeps",
        "golden": "Golden",
    }
    for f in alert.factors:
        name = f.get("name", "?")
        pts = f.get("points", 0)
        label = factor_labels.get(name, name)
        reasoning = f.get("reasoning", "")
        conf_lines.append(f"  {_star_bar(pts)} {label:<7} {reasoning}")

    # Context footer
    ctx_lines = []
    if alert.spot is not None and alert.target_level is not None:
        dist_pct = abs(alert.target_level - alert.spot) / alert.spot * 100
        arrow = "→" if alert.direction == "bullish" else "←"
        ctx_lines.append(
            f"{alert.ticker} ${alert.spot:.2f} {arrow} target ${alert.target_level:g} "
            f"({dist_pct:.2f}% away)"
        )
    if alert.gex_signal or alert.flow_regime:
        ctx_lines.append(
            f"GEX: {alert.gex_signal or '—'}  ·  Flow: {alert.flow_regime or '—'}"
        )

    # Strike quality note (if degraded)
    quality_note = ""
    if alert.strike_quality == "degraded":
        quality_note = "\n⚠ Liquidity degraded — check spread + OI before entry"
    elif alert.strike_quality == "acceptable":
        quality_note = ""  # no warning

    # Assemble
    return (
        f"{header}\n"
        f"{pricing}\n"
        f"{manage}\n\n"
        f"{conf_header}\n"
        f"{chr(10).join(conf_lines)}"
        f"{quality_note}\n\n"
        f"{chr(10).join(ctx_lines)}"
    )


async def send_zero_dte_alert(alert: Any) -> None:
    """Send a 0DTE alert to Telegram. Errors logged but swallowed —
    alerting failures should never break the eval loop."""
    try:
        from .telegram import send
    except ImportError:
        print("[ZERO_DTE] telegram module not available")
        return
    text = format_zero_dte_alert(alert)
    try:
        await send(text, ticker=alert.ticker, force=True)
    except Exception as e:
        print(f"[ZERO_DTE] telegram send failed: {e}")
