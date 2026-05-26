"""Alert-send gates — prevent after-hours Telegram noise.

Created 2026-04-23 after midnight runner-tracker and GOLDEN alerts started
spamming the user during overnight/weekend. Both bugs same class: alert
loops don't check whether sending right now is useful to the trader.

Two gates exported:

  is_rth_or_close_window() — True during 9:30 AM - 4:15 PM ET weekdays.
    15-min post-close buffer catches late-arriving closing prints that
    were still generated intraday. Alerts outside this window are either
    delayed OPRA reconciliations (flow alerts) or spurious day-rollover
    triggers (runner tracker) — neither actionable.

  contract_still_tradeable(expiration_str) — True if a dated option
    contract hasn't yet expired. Blocks GOLDEN/UPSIDE_BET alerts from
    firing on 0DTE contracts after the 4 PM expiration.

Philosophy: log to console so the event is not lost; just skip the
Telegram hop. Traders can inspect the log in the morning.
"""
from __future__ import annotations

import datetime as dt

from .market_calendar import is_market_holiday
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def is_rth_or_close_window() -> bool:
    """True during RTH plus a 15-min post-close buffer.

    Weekends return False. Pre-market (before 9:30 AM ET) returns False —
    pre-market alerts are fine in concept but our current loops emit
    stale state-rollover transitions at midnight, so keeping gate simple
    until that's refactored.
    """
    now = dt.datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if is_market_holiday(now.date()):
        return False
    minute_of_day = now.hour * 60 + now.minute
    # 9:30 AM (570 min) through 4:15 PM (975 min)
    return 570 <= minute_of_day < 975


def contract_still_tradeable(expiration: str | None) -> bool:
    """Return True if an option contract has time left to trade.

    Accepts expiration as YYYY-MM-DD or YYYYMMDD. Returns True on parse
    failure (fail-open) so alerts with malformed dates still fire rather
    than silently swallowing.
    """
    if not expiration:
        return True
    try:
        # Normalize: strip dashes, parse as YYYYMMDD
        s = str(expiration).replace("-", "")
        exp_date = dt.datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, TypeError):
        return True  # fail-open on parse error

    now = dt.datetime.now(ET)
    today = now.date()
    if exp_date < today:
        return False
    if exp_date == today:
        # 0DTE — tradeable only during RTH (strict: no post-close alerts)
        minute_of_day = now.hour * 60 + now.minute
        return 570 <= minute_of_day < 960  # 4:00 PM cutoff, no buffer
    return True


def should_send_alert(
    *,
    expiration: str | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """One-call gate. Returns (should_send, reason_if_blocked).

    Pass expiration for option alerts; omit for generic alerts that only
    need the market-hours check. Pass force=True to bypass gates (used
    sparingly — e.g., system startup/shutdown notifications).
    """
    if force:
        return True, ""
    if not is_rth_or_close_window():
        return False, "outside market hours"
    if expiration is not None and not contract_still_tradeable(expiration):
        return False, f"contract {expiration} already expired"
    return True, ""
