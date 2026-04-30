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

import datetime as dt
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


# Apr 29 evening: index-family cross-confirmation. ST on SPY confirms
# 0DTE Engine on QQQ/SPX (and vice versa) since they all track broad
# market direction. Empirical day: 14:09 ST SPY ⚡A fired 1min before
# 14:10 0DTE Engine QQQ B+ — should have shown CONFIRMED, not WATCHING.
INDEX_FAMILY = {"SPY", "QQQ", "IWM", "SPX", "SPXW", "NDX", "RUT"}


def _check_recent_structural_turn(
    ticker: str, direction: str, ts: float,
    lookback_sec: int = 90 * 60,
    db_path: str = "./structural_turns.db",
) -> dict | None:
    """Cross-confirmation rule (Apr 29): if a Structural Turn already fired
    same-direction within 90min on this ticker OR any index-family member,
    upgrade the 0DTE banner from 'WATCHING' to 'CONFIRMED — execute now'.

    Workflow:
      0DTE Engine alone → 👁 WATCHING (wait for ST within 90min)
      0DTE Engine + ST already fired (same family) → ✅ CONFIRMED (act now)
      ST after 0DTE Engine → ST alert prepends 🔗 CONFIRMS banner (other side)
    """
    import sqlite3
    cutoff = ts - lookback_sec
    target_dir = direction.upper()
    target_dir_full = "BULLISH" if target_dir == "BULLISH" or direction.lower() == "bullish" else "BEARISH"
    if ticker in INDEX_FAMILY:
        family = sorted(INDEX_FAMILY)
    else:
        family = [ticker]
    placeholders = ",".join("?" * len(family))
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f"""SELECT ts, ticker AS st_ticker, tier, spot, qualified
                FROM structural_turns
                WHERE ticker IN ({placeholders}) AND direction = ?
                  AND ts BETWEEN ? AND ?
                  AND qualified = 1
                ORDER BY ts DESC LIMIT 1""",
            (*family, target_dir_full, cutoff, ts),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return None
        return dict(row)
    except sqlite3.Error:
        return None


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

    # Cross-confirmation rule (Apr 29 workflow):
    # Check if Structural Turn already confirmed this direction within 90min.
    # If yes → ✅ CONFIRMED banner (execute now).
    # If no → 👁 WATCHING banner (wait for ST or skip if ST never fires).
    fired_at = getattr(alert, "fired_at", None) or 0
    st_confirm = _check_recent_structural_turn(
        alert.ticker, alert.direction, fired_at,
    ) if fired_at else None

    if st_confirm:
        st_t = dt.datetime.fromtimestamp(int(st_confirm["ts"])).strftime("%H:%M")
        st_age_min = max(0, int((fired_at - st_confirm["ts"]) / 60))
        # Surface the source ticker if cross-family (e.g. ST SPY confirms 0DTE QQQ)
        st_tkr = st_confirm.get("st_ticker", alert.ticker)
        family_tag = f" [{st_tkr}]" if st_tkr != alert.ticker else ""
        banner = (
            f"✅ CONFIRMED — Structural Turn TIER {st_confirm['tier']}{family_tag} fired at "
            f"{st_t} ({st_age_min}min ago)\n"
            f"   Both signals aligned — execute now per the play.\n\n"
        )
    else:
        banner = (
            f"👁 WATCHING — wait for Structural Turn confirmation (90min window)\n"
            f"   Take if ST fires same direction; SKIP if ST never confirms.\n"
            f"   On TREND days (no LOD retest), ST may not fire — discretionary call.\n\n"
        )

    # Header
    header = (
        f"{banner}"
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

    # Management reminder — Apr 27 audit on small sample (n=5) suggested
    # buy-and-hold to time-stop bleeds (avg end-of-90min was -38% despite
    # avg MFE +90%). Treat the timing claim as anecdotal until larger
    # sample confirms. Behavioral nudge to scale > rule of law.
    manage = (
        "⚠ MANAGE: small sample suggests scaling at +50% beats "
        "hold-to-time-stop. Trail rest."
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
    alerting failures should never break the eval loop.

    Apr 29: hardened error logging after the SPX 14:58 alert went missing
    (DB had it, Telegram didn't). Now wraps format + send with try/except
    and logs alert_id so we can correlate which fires died in transit."""
    alert_id = getattr(alert, "alert_id", "?")
    ticker = getattr(alert, "ticker", "?")
    try:
        from .telegram import send
    except ImportError:
        print(f"[ZERO_DTE] {alert_id} ({ticker}) telegram module not available")
        return
    try:
        text = format_zero_dte_alert(alert)
    except Exception as e:
        print(f"[ZERO_DTE] {alert_id} ({ticker}) format failed: {e!r}")
        import traceback
        traceback.print_exc()
        return
    try:
        result = await send(text, ticker=alert.ticker, force=True)
        if not result:
            print(f"[ZERO_DTE] {alert_id} ({ticker}) send returned False "
                  f"(token/chat? rate limit?)")
    except Exception as e:
        print(f"[ZERO_DTE] {alert_id} ({ticker}) telegram send failed: {e!r}")
        import traceback
        traceback.print_exc()
