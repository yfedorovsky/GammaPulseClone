"""Mir TP Window — daily Telegram alert at 1:00 PM ET.

TraderMir 5/28 PM observation: "if you take profits regardless of target
in the window from 10am to 10:45 pacific time you will likely sell the
high for the day of your options contracts."

Validated against today's 396 INFORMED FLOW fires:
  - 9.8% peaked exactly in Mir's 1:00-1:45 PM ET window
  - 24% peaked between 13:00-14:00
  - 58% peaked in the 13:45-15:00 PM window
  - Only 9% peaked in power hour (15:00-16:00)
  - 0% peaked at/after close

The rule is directionally right: take profits in early afternoon,
not at close. Specific 1:00 PM trigger captures micro-caps (DPRO,
ONDS, SOXX peaked at 13:00 today); large-caps run an hour later.

This module fires a daily Telegram ping at 13:00 ET listing every
INFORMED FLOW + SOE A/A+ alert from today that's still tradeable
(neither TP'd nor stopped) with current P/L vs entry.

Dedup: fires once per calendar day (ET). Resets at midnight.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any


# Once-per-day dedup state (in-memory; resets on restart)
_last_fired_date: date | None = None


def _today_et() -> date:
    """ET calendar day (server clock assumed ET)."""
    return datetime.now().date()


def _is_mir_window_now() -> bool:
    """True between 13:00 and 13:30 ET (gives 30-min firing window).

    Mir's window is 13:00-13:45, but we want to fire EARLY in the
    window (13:00-13:15 ideally) so the user has time to actually
    place orders before the peak rolls past.
    """
    now = datetime.now()
    if now.weekday() >= 5:  # weekend
        return False
    minute_of_day = now.hour * 60 + now.minute
    # 13:00 = 780, 13:30 = 810
    return 780 <= minute_of_day <= 810


def _spot_at(conn, ticker: str, target_ts: int, window: int = 900) -> float | None:
    """Closest snapshot to target_ts within ±window seconds."""
    r = conn.execute(
        """SELECT spot FROM snapshots
           WHERE ticker = ? AND ABS(ts - ?) <= ?
           ORDER BY ABS(ts - ?) LIMIT 1""",
        (ticker, target_ts, window, target_ts),
    ).fetchone()
    return float(r[0]) if r and r[0] else None


def _direction(opt_type: str | None, sentiment: str | None) -> str:
    """Map (option_type, sentiment) -> BULL/BEAR."""
    ot = (opt_type or "").lower()
    sent = (sentiment or "").upper()
    if ot == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if ot == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "BULL"


def _compute_pl_pct(entry: float, current: float, direction: str) -> float:
    if entry <= 0:
        return 0.0
    sign = 1 if direction == "BULL" else -1
    return (current - entry) / entry * 100 * sign


def _collect_open_alerts() -> dict[str, list[dict[str, Any]]]:
    """Gather today's INFORMED FLOW + SOE A/A+ alerts that are still tradeable
    (neither TP'd nor stopped). Returns dict with 'flow' and 'soe' lists."""
    today_start = int(datetime.combine(_today_et(), datetime.min.time()).timestamp())
    now_ts = int(time.time())

    conn = sqlite3.connect("snapshots.db")
    conn.row_factory = sqlite3.Row

    # INFORMED FLOW — per-contract dedup, only one per contract per day
    flow_rows = conn.execute(
        """SELECT MIN(ts) AS fire_ts, ticker, strike, option_type, expiration,
                  sentiment, MIN(spot) AS entry_spot, MAX(notional) AS notional,
                  MAX(vol_oi) AS vol_oi, MAX(insider_score) AS score
           FROM flow_alerts
           WHERE is_insider = 1 AND ts >= ?
           GROUP BY ticker, strike, expiration, option_type, sentiment
           ORDER BY fire_ts""",
        (today_start,),
    ).fetchall()

    flow_open: list[dict] = []
    for r in flow_rows:
        if not r["entry_spot"]:
            continue
        ticker = r["ticker"]
        direction = _direction(r["option_type"], r["sentiment"])
        entry = float(r["entry_spot"])
        cur = _spot_at(conn, ticker, now_ts) or entry
        pl_pct = _compute_pl_pct(entry, cur, direction)

        # Only ping on meaningful winners — Mir's rule is about CAPTURING
        # peak P/L, not nudging on every open position. Skip trades that
        # haven't moved at least +3% spot in our direction yet.
        if pl_pct < 3.0:
            continue

        flow_open.append({
            "ticker": ticker,
            "strike": r["strike"],
            "option_type": (r["option_type"] or "").upper(),
            "expiration": r["expiration"],
            "direction": direction,
            "entry": entry,
            "current": cur,
            "pl_pct": pl_pct,
            "vol_oi": r["vol_oi"],
            "notional": r["notional"] or 0,
        })

    # SOE A/A+ — open if neither target nor stop hit yet
    soe_rows = conn.execute(
        """SELECT ts, ticker, signal_type, grade, spot, target, stop, direction
           FROM soe_signals
           WHERE ts >= ? AND grade IN ('A', 'A+') AND status = 'PENDING'
           ORDER BY ts""",
        (today_start,),
    ).fetchall()

    soe_open: list[dict] = []
    for r in soe_rows:
        ticker = r["ticker"]
        entry = float(r["spot"] or 0)
        if entry <= 0:
            continue
        target = float(r["target"] or 0)
        stop = float(r["stop"] or 0)
        cur = _spot_at(conn, ticker, now_ts) or entry

        # Direction inference
        direction = "BULL"
        if "▼" in (r["direction"] or "") or "BEAR" in (r["direction"] or "").upper():
            direction = "BEAR"

        # Has it hit target or stop already? skip if yes
        if direction == "BULL":
            if target > 0 and cur >= target:
                continue
            if stop > 0 and cur <= stop:
                continue
        else:
            if target > 0 and cur <= target:
                continue
            if stop > 0 and cur >= stop:
                continue

        pl_pct = _compute_pl_pct(entry, cur, direction)
        # Same +3% winner threshold as flow path
        if pl_pct < 3.0:
            continue

        soe_open.append({
            "ticker": ticker,
            "signal": r["signal_type"],
            "grade": r["grade"],
            "direction": direction,
            "entry": entry,
            "current": cur,
            "target": target,
            "stop": stop,
            "pl_pct": pl_pct,
        })

    # SOE dedup by ticker — keep best P/L per ticker (avoids QCOM ×4)
    soe_by_ticker: dict[str, dict] = {}
    for s in soe_open:
        existing = soe_by_ticker.get(s["ticker"])
        if not existing or s["pl_pct"] > existing["pl_pct"]:
            soe_by_ticker[s["ticker"]] = s
    soe_open = list(soe_by_ticker.values())

    # FLOW dedup by (ticker, direction) — keep best P/L
    # (User generally rolls multiple strike alerts on same ticker into one
    # net thesis trade.)
    flow_by_key: dict[tuple, dict] = {}
    for f in flow_open:
        key = (f["ticker"], f["direction"])
        existing = flow_by_key.get(key)
        if not existing or f["pl_pct"] > existing["pl_pct"]:
            flow_by_key[key] = f
    flow_open = list(flow_by_key.values())

    conn.close()
    return {"flow": flow_open, "soe": soe_open}


def _format_telegram(open_alerts: dict[str, list[dict]]) -> str:
    """Build the Telegram message body."""
    flow = open_alerts["flow"]
    soe = open_alerts["soe"]
    lines: list[str] = []

    lines.append("⏰ <b>MIR TP WINDOW</b> (1:00–1:45 PM ET)")
    lines.append("<i>Take partial profits on open winners — peak window today</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    if not flow and not soe:
        lines.append("No open INFORMED FLOW or SOE A/A+ alerts to ping.")
        lines.append("")
        lines.append(
            "<i>Reminder: this window historically captures the day's peak. "
            "If you have broker positions open, consider taking partial profits.</i>"
        )
        return "\n".join(lines)

    # INFORMED FLOW winners sorted by P/L descending
    if flow:
        lines.append(f"<b>INFORMED FLOW</b> ({len(flow)} open)")
        # Sort: winners first, biggest gains on top
        flow.sort(key=lambda x: -x["pl_pct"])
        for f in flow[:10]:  # top 10 to keep msg short
            emoji = "🟢" if f["direction"] == "BULL" else "🔴"
            pl_str = (
                f"+{f['pl_pct']:.2f}%" if f["pl_pct"] >= 0
                else f"{f['pl_pct']:.2f}%"
            )
            lines.append(
                f"{emoji} <b>{f['ticker']}</b> ${f['strike']:g}{f['option_type'][0]}"
                f" {f['expiration']}  "
                f"<i>{pl_str}</i>"
            )
            lines.append(
                f"   entry ${f['entry']:.2f} → ${f['current']:.2f}"
            )
        if len(flow) > 10:
            lines.append(f"   <i>+ {len(flow) - 10} more</i>")
        lines.append("")

    # SOE A/A+ winners
    if soe:
        lines.append(f"<b>SOE A/A+</b> ({len(soe)} open)")
        soe.sort(key=lambda x: -x["pl_pct"])
        for s in soe[:8]:
            emoji = "🟢" if s["direction"] == "BULL" else "🔴"
            pl_str = (
                f"+{s['pl_pct']:.2f}%" if s["pl_pct"] >= 0
                else f"{s['pl_pct']:.2f}%"
            )
            lines.append(
                f"{emoji} <b>{s['ticker']}</b> {s['grade']} {s['signal']}  "
                f"<i>{pl_str}</i>"
            )
            lines.append(
                f"   entry ${s['entry']:.2f} → ${s['current']:.2f}  "
                f"target ${s['target']:.2f}"
            )
        if len(soe) > 8:
            lines.append(f"   <i>+ {len(soe) - 8} more</i>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "<i>Mir's rule: take partial profits regardless of target. "
        "Re-enter at power hour (3-4 PM ET) or tomorrow morning if setup intact.</i>"
    )

    return "\n".join(lines)


async def maybe_fire_mir_tp_alert() -> bool:
    """Check if it's time to fire the Mir TP window alert. Returns True if fired.

    Idempotent: only fires once per ET calendar day. Call from worker loop
    every cycle — cheap no-op when not in window or already fired today.
    """
    global _last_fired_date

    today = _today_et()
    if _last_fired_date == today:
        return False  # already fired today

    if not _is_mir_window_now():
        return False

    # Collect data
    try:
        open_alerts = _collect_open_alerts()
        msg = _format_telegram(open_alerts)
    except Exception as e:
        print(f"[MIR_TP] collect failed: {e!r}", flush=True)
        return False

    # Send via Telegram (force=True so it bypasses rate limits)
    try:
        from .telegram import send
        ok = await send(msg, priority=True, force=True)
        if ok:
            _last_fired_date = today
            n_total = len(open_alerts["flow"]) + len(open_alerts["soe"])
            print(
                f"[MIR_TP] fired Mir TP window alert: "
                f"{n_total} open positions tagged",
                flush=True,
            )
        return ok
    except Exception as e:
        print(f"[MIR_TP] send failed: {e!r}", flush=True)
        return False
