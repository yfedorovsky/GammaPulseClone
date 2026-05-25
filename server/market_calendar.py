"""US equity market open/close calendar.

Centralized helper so every RTH-gated loop checks the same source of truth
for weekends + US stock market holidays.

Holiday data is hardcoded for 2026 (and a few years either side) because
that's all we need until Tradier's /markets/calendar can be wired in. The
list covers FULL-CLOSE days only — half-days (early close 1:00 PM) like
the day after Thanksgiving and Christmas Eve still count as "market open"
because the scanner's existing 16:00 cutoff handles the close naturally.

Bug history: 2026-05-25 (Memorial Day) — backend was left running over
the weekend, scanners had no holiday awareness, fired 93,000+ alerts on
stale Friday-close data before this module was shipped.
"""
from __future__ import annotations

import datetime as _dt


# US equity market full-close holidays. Hardcoded through 2027 so the
# scanner survives the next 18 months without touching this file. Update
# when 2028 calendar publishes.
US_MARKET_HOLIDAYS: set[_dt.date] = {
    # 2025 (in case backfill loops process old data)
    _dt.date(2025, 1, 1),    # New Year's Day
    _dt.date(2025, 1, 20),   # MLK Day
    _dt.date(2025, 2, 17),   # Presidents Day
    _dt.date(2025, 4, 18),   # Good Friday
    _dt.date(2025, 5, 26),   # Memorial Day
    _dt.date(2025, 6, 19),   # Juneteenth
    _dt.date(2025, 7, 4),    # Independence Day
    _dt.date(2025, 9, 1),    # Labor Day
    _dt.date(2025, 11, 27),  # Thanksgiving
    _dt.date(2025, 12, 25),  # Christmas
    # 2026
    _dt.date(2026, 1, 1),    # New Year's Day
    _dt.date(2026, 1, 19),   # MLK Day
    _dt.date(2026, 2, 16),   # Presidents Day
    _dt.date(2026, 4, 3),    # Good Friday
    _dt.date(2026, 5, 25),   # Memorial Day  ← TODAY
    _dt.date(2026, 6, 19),   # Juneteenth
    _dt.date(2026, 7, 3),    # Independence Day (July 4 falls Saturday → observed Friday)
    _dt.date(2026, 9, 7),    # Labor Day
    _dt.date(2026, 11, 26),  # Thanksgiving
    _dt.date(2026, 12, 25),  # Christmas
    # 2027
    _dt.date(2027, 1, 1),    # New Year's Day
    _dt.date(2027, 1, 18),   # MLK Day
    _dt.date(2027, 2, 15),   # Presidents Day
    _dt.date(2027, 3, 26),   # Good Friday
    _dt.date(2027, 5, 31),   # Memorial Day
    _dt.date(2027, 6, 18),   # Juneteenth (observed; falls Saturday → Friday)
    _dt.date(2027, 7, 5),    # Independence Day (observed; July 4 Sunday → Monday)
    _dt.date(2027, 9, 6),    # Labor Day
    _dt.date(2027, 11, 25),  # Thanksgiving
    _dt.date(2027, 12, 24),  # Christmas observed (Dec 25 Saturday)
}


def is_market_holiday(d: _dt.date | None = None) -> bool:
    """Return True if `d` (default: today) is a US equity full-close holiday."""
    if d is None:
        d = _dt.date.today()
    return d in US_MARKET_HOLIDAYS


def is_market_open() -> bool:
    """Return True if RIGHT NOW is a US equity RTH session moment.

    Combines: not weekend AND not full-close holiday AND time in 9:30-16:00 ET.

    Note: assumes server clock is in ET. Production GammaPulse runs in
    ET — if that ever changes, swap _dt.datetime.now() for a zoneinfo
    America/New_York-aware call.
    """
    now = _dt.datetime.now()
    if now.weekday() >= 5:        # Saturday/Sunday
        return False
    if is_market_holiday(now.date()):
        return False
    hm = (now.hour, now.minute)
    if hm < (9, 30):
        return False
    if now.hour >= 16:
        return False
    return True


def is_rth_or_extended() -> bool:
    """Like is_market_open() but allows the 16:00-16:15 wind-down window
    used by some loops (basket detector, etc.)."""
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    hm = (now.hour, now.minute)
    if hm < (9, 30):
        return False
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return False
    return True
