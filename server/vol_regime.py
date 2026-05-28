"""Intraday volatility regime classifier — time-of-day context for alerts.

Based on Massive Capital's intraday-vol research (rolling 30-min H/L range
on SPX futures since 2021):

  ⚡ 9:30-10:00 ET — OPENING PEAK (most volatile 30 min of the day)
  📊  8:30 ET     — ECON RELEASE spike (PCE/CPI/NFP drop)
  💤 12:20-12:50 ET — LULL (lowest vol of regular session)
  ⚡ 3:30-4:00 ET — CLOSING PEAK (2nd most volatile)
  😴  4:00-5:00 ET — futures session reset (lowest of 24h)

Cross-referenced against our own 5/28 data: 44% of INFORMED FLOW peaks
landed in 2:00-3:00 PM ET (RECOVERY_LATE), confirming the post-lull
afternoon recovery wave is where option prices actually peak.

Usage:
  from server.vol_regime import current_regime
  label, desc = current_regime()
  # ("OPENING_PEAK", "🔥 9:30-10:00 — opening volatility peak")

Wire into format_soe_signal / format_flow_alert to show time-of-day
context on every alert. Wire into scorecard to break down WR by regime.

Machine clock assumed ET (matches existing market_calendar pattern).
"""
from __future__ import annotations

import datetime as _dt


# (start_minute, end_minute, label, emoji, description)
# Minutes counted from midnight ET (0 = 12:00 AM, 570 = 9:30 AM, etc.)
_REGIMES: list[tuple[int, int, str, str, str]] = [
    (0, 510, "OVERNIGHT", "🌙", "overnight session (futures only)"),
    (510, 525, "ECON_RELEASE", "📊", "8:30 ET econ data release (PCE/CPI/NFP)"),
    (525, 570, "PRE_OPEN", "·", "pre-market drift"),
    (570, 600, "OPENING_PEAK", "🔥", "9:30-10:00 — opening vol peak (most volatile 30m)"),
    (600, 690, "MORNING_DIR", "📈", "10:00-11:30 — directional follow-through"),
    (690, 740, "MIDDAY", "·", "11:30-12:20 — vol decaying"),
    (740, 770, "LULL", "💤", "12:20-12:50 — lowest vol of RTH"),
    (770, 840, "RECOVERY_EARLY", "📈", "12:50-2:00 — post-lull recovery (Mir TP window)"),
    (840, 930, "RECOVERY_LATE", "📈", "2:00-3:30 — afternoon peak drift"),
    (930, 960, "CLOSING_PEAK", "🔥", "3:30-4:00 — closing vol peak (reversal risk)"),
    (960, 1020, "POST_CLOSE", "😴", "4:00-5:00 — futures rest"),
    (1020, 1440, "AFTER_HOURS", "·", "after-hours session"),
]


def _minute_of_day(ts: float | int | None = None) -> int:
    """Minute of ET day (0-1439). ts is unix epoch; None = now."""
    if ts is None:
        now = _dt.datetime.now()
    else:
        now = _dt.datetime.fromtimestamp(ts)
    return now.hour * 60 + now.minute


def current_regime(ts: float | int | None = None) -> tuple[str, str, str]:
    """Return (label, emoji, description) for the time-of-day vol regime.

    Examples:
      ("LULL", "💤", "12:20-12:50 — lowest vol of RTH")
      ("OPENING_PEAK", "🔥", "9:30-10:00 — opening vol peak (most volatile 30m)")
    """
    m = _minute_of_day(ts)
    for start, end, label, emoji, desc in _REGIMES:
        if start <= m < end:
            return label, emoji, desc
    # Fallback (shouldn't happen)
    return "UNKNOWN", "·", "unknown vol regime"


def is_high_vol(ts: float | int | None = None) -> bool:
    """True during the two daily peak windows (open + close).
    Use to widen stop distances, reduce position size, or filter setups."""
    label, _, _ = current_regime(ts)
    return label in ("OPENING_PEAK", "CLOSING_PEAK", "ECON_RELEASE")


def is_low_vol(ts: float | int | None = None) -> bool:
    """True during the midday lull. Use to filter false-signal noise."""
    label, _, _ = current_regime(ts)
    return label == "LULL"


def is_recovery_window(ts: float | int | None = None) -> bool:
    """True during the post-lull recovery wave (Mir's TP window).
    Use to trigger profit-take suggestions on open winners."""
    label, _, _ = current_regime(ts)
    return label in ("RECOVERY_EARLY", "RECOVERY_LATE")


def format_for_telegram(ts: float | int | None = None) -> str:
    """Compact one-line tag for Telegram appending.

    Example: "💤 LULL — lowest vol of RTH"
    """
    label, emoji, desc = current_regime(ts)
    return f"{emoji} <i>{label}</i> — <i>{desc.split('—', 1)[-1].strip() if '—' in desc else desc}</i>"
