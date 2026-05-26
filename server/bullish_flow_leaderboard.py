"""Bullish flow leaderboard — daily end-of-day digest.

Equivalent to CheddarFlow's "Bullish flow" sidebar (the panel that ranked
NVDA / CNC / SNDK / AMD / AAPL by aggregate premium at 11:39 AM on 5/12).
We compute the same ranking from flow_alerts and fire a single Telegram
digest at the 4:05 PM ET close so the operator gets a clean
"here's where institutional bullish premium concentrated today" message.

Rank order: aggregate premium (notional) on BULLISH alerts only —
  - CALL + ASK side (someone bought calls aggressively)
  - PUT  + BID side (someone sold puts aggressively / collected premium)

Tickers needing minimum activity to appear (so we don't surface noise):
  - >= 3 qualifying alerts in the session
  - >= $2M aggregate bullish premium

Output: top 10 tickers, ranked by premium, formatted for Telegram.

Scheduling: fires once per trading day from worker.py via the EOD hook
(_maybe_fire_eod_leaderboard), gated to 16:00-16:15 ET and dedup'd by
the date stamp in _last_fired_date.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from contextlib import contextmanager
from typing import Any

from .config import get_settings
from .market_calendar import is_market_holiday


MIN_ORDERS_PER_TICKER = 3
MIN_PREMIUM_PER_TICKER = 2_000_000   # $2M floor
TOP_N = 10

_last_fired_date: str | None = None  # 'YYYY-MM-DD' of last successful fire


@contextmanager
def _conn():
    db = get_settings().snapshot_db
    c = sqlite3.connect(db)
    try:
        yield c
    finally:
        c.close()


def compute_leaderboard(
    date_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Compute today's bullish flow leaderboard.

    Returns a list of dicts ordered by aggregate premium descending.
    `date_iso` defaults to today (ET-server-clock).
    """
    today = date_iso or _dt.date.today().isoformat()
    # ts >= start of today, ts < start of tomorrow (Unix epoch from sqlite
    # strftime). 'unixepoch' in sqlite is in seconds; we match the format
    # used everywhere else in flow_alerts.
    # flow_alerts stores ONE ROW PER SCAN CYCLE per contract, and the
    # `notional` column reflects the CUMULATIVE day-volume × price at that
    # snapshot. Naive SUM across all rows overcounts ~30x (one row every
    # ~5 min through the trading day). We dedupe by taking the MAX
    # notional per (ticker, strike, expiration, option_type, sentiment)
    # = the final intraday reading for that contract.
    #
    # Then SUM across contracts within each ticker. Each contract
    # contributes its peak premium once. orders = distinct contracts.
    sql = """
      WITH last_per_contract AS (
        SELECT ticker, strike, expiration, option_type, sentiment,
               MAX(notional) AS contract_premium
        FROM flow_alerts
        WHERE ts >= strftime('%s', ?)
          AND ts <  strftime('%s', ?, '+1 day')
          AND sentiment='BULLISH'
          AND conviction IN ('MEDIUM','HIGH','SWEEP')
        GROUP BY ticker, strike, expiration, option_type, sentiment
      )
      SELECT ticker,
             COUNT(*) AS orders,
             SUM(contract_premium) AS total_premium,
             SUM(CASE WHEN option_type='call' THEN contract_premium ELSE 0 END)
                 AS call_premium,
             SUM(CASE WHEN option_type='put'  THEN contract_premium ELSE 0 END)
                 AS put_premium
      FROM last_per_contract
      GROUP BY ticker
      HAVING orders >= ? AND total_premium >= ?
      ORDER BY total_premium DESC
      LIMIT ?
    """
    with _conn() as c:
        cur = c.execute(sql, (
            today, today,
            MIN_ORDERS_PER_TICKER,
            MIN_PREMIUM_PER_TICKER,
            TOP_N,
        ))
        rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "ticker": r[0],
            "orders": int(r[1] or 0),
            "premium": float(r[2] or 0.0),
            "call_premium": float(r[3] or 0.0),
            "put_premium": float(r[4] or 0.0),
        })
    return out


def format_leaderboard_telegram(rows: list[dict[str, Any]],
                                date_iso: str | None = None) -> str:
    today = date_iso or _dt.date.today().isoformat()
    if not rows:
        return (
            f"📊 <b>BULLISH FLOW — {today}</b>\n"
            f"<i>No qualifying tickers today (min {MIN_ORDERS_PER_TICKER} "
            f"orders, ${MIN_PREMIUM_PER_TICKER/1e6:.0f}M premium).</i>"
        )
    lines = [f"📊 <b>BULLISH FLOW — {today}</b>"]
    lines.append(f"<i>Top {len(rows)} by aggregate premium "
                 f"(call-buy + put-write, MEDIUM+ conviction)</i>\n")
    for i, r in enumerate(rows, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"  {i}."
        prem_mm = r["premium"] / 1_000_000
        call_mm = r["call_premium"] / 1_000_000
        put_mm = r["put_premium"] / 1_000_000
        # Show call/put split inline so operator sees the structural
        # composition (pure call-buy vs. pure put-write vs. mixed).
        split = []
        if call_mm > 0.1:
            split.append(f"C ${call_mm:.1f}M")
        if put_mm > 0.1:
            split.append(f"P ${put_mm:.1f}M")
        split_str = " · ".join(split) if split else ""
        lines.append(
            f"{emoji} <b>{r['ticker']}</b> — "
            f"${prem_mm:.1f}M  ({r['orders']} orders)"
            + (f"\n     <i>{split_str}</i>" if split_str else "")
        )
    return "\n".join(lines)


async def maybe_fire_eod_leaderboard() -> bool:
    """Fire the EOD leaderboard once per trading day at 16:00-16:15 ET.

    Returns True if a Telegram digest was sent on this call. Self-gates:
      - Weekday only
      - Hour 16:00-16:15 ET (matches alert RTH end-of-day band)
      - Dedup via in-memory _last_fired_date so worker cycles in the
        16:00-16:15 window only send once
    """
    global _last_fired_date
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    # Fire band: 16:00-16:15 ET (matches the RTH end-of-day band).
    if not (now.hour == 16 and now.minute <= 15):
        return False
    today = now.date().isoformat()
    if _last_fired_date == today:
        return False

    rows = compute_leaderboard(date_iso=today)
    if not rows:
        # Don't burn an alert on a silent day — still record so we don't retry.
        _last_fired_date = today
        return False

    # Lazy import to avoid circular dependency at module load
    from .telegram import send as tg_send
    text = format_leaderboard_telegram(rows, date_iso=today)
    # priority=True so the daily digest bypasses the global 3/10min rate
    # limit (it's a once-per-day fire by design; the per-ticker cooldown
    # doesn't apply because we pass ticker="").
    sent = await tg_send(text, ticker="", priority=True)
    if sent:
        _last_fired_date = today
        print(f"[LEADERBOARD] EOD digest fired: {len(rows)} tickers, "
              f"top={rows[0]['ticker']} ${rows[0]['premium']/1e6:.1f}M")
    return sent
