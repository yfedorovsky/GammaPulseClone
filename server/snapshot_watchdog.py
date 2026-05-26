"""Snapshot persist watchdog.

Background loop that detects when the `snapshots` table goes >N minutes
without a write during RTH. Alarms via Telegram once per silent-event,
auto-rearms when writes resume.

Motivated by 2026-05-14 → 2026-05-19 bug: the snapshots table silently
stopped accepting writes for 4 days (5 days including weekend) while
flow_alerts/soe_signals continued. Every detector that reads snapshot
state was poisoned with stale data. NEVER AGAIN.

Cost: one SELECT COUNT(*) every CHECK_INTERVAL_S seconds. Negligible.

Shipped 2026-05-20.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import sqlite3
import time

from .market_calendar import is_market_holiday
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CHECK_INTERVAL_S = 120              # check every 2 minutes
SILENCE_THRESHOLD_S = 600           # 10 min of silence during RTH = alarm
REARM_AFTER_ROWS = 50               # rearm alarm once we see 50 fresh rows
ALARM_COOLDOWN_S = 1800             # don't re-alarm within 30 min of last alarm


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

_last_alarm_ts: float = 0
_alarm_armed: bool = True


def _is_rth() -> bool:
    """RTH = weekday, 9:30-16:00 ET, excluding US equity holidays."""
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    hm = (now.hour, now.minute)
    if hm < (9, 30):
        return False
    if now.hour >= 16:
        return False
    return True


def count_recent_snapshots(db_path: str, seconds: int) -> int:
    """Return number of snapshot rows written in the last N seconds."""
    try:
        conn = sqlite3.connect(db_path)
        cutoff = time.time() - seconds
        n = conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE ts > ?", (cutoff,)
        ).fetchone()[0]
        conn.close()
        return int(n or 0)
    except Exception as e:
        print(f"[snap_watchdog] db read error: {e}")
        return -1


def get_last_snapshot_age_seconds(db_path: str) -> float | None:
    """Return seconds since the most recent snapshot row, or None on error."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT MAX(ts) FROM snapshots").fetchone()
        conn.close()
        if not row or row[0] is None:
            return None
        return time.time() - float(row[0])
    except Exception as e:
        print(f"[snap_watchdog] db read error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────


async def run_snapshot_watchdog(stop_event: asyncio.Event) -> None:
    """Periodic check that snapshot writes are flowing during RTH."""
    from .config import get_settings

    global _last_alarm_ts, _alarm_armed

    settings = get_settings()
    db_path = getattr(settings, "snapshot_db", None) or "./snapshots.db"

    print(
        f"[snap_watchdog] loop starting — check_interval={CHECK_INTERVAL_S}s "
        f"silence_threshold={SILENCE_THRESHOLD_S}s db={db_path}"
    )

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

        try:
            if not _is_rth():
                continue  # only watch during RTH

            age_s = get_last_snapshot_age_seconds(db_path)
            recent_n = count_recent_snapshots(db_path, SILENCE_THRESHOLD_S)

            now = time.time()
            silence_exceeded = (
                age_s is not None and age_s > SILENCE_THRESHOLD_S
            ) or recent_n == 0

            if silence_exceeded and _alarm_armed:
                # Cooldown check
                if now - _last_alarm_ts < ALARM_COOLDOWN_S:
                    continue
                # ALARM
                age_min = (age_s or 0) / 60
                msg = (
                    f"🚨 <b>SNAPSHOT PERSIST WATCHDOG</b>\n"
                    f"\n"
                    f"Snapshots table has not written for "
                    f"<b>{age_min:.0f} min</b> during RTH.\n"
                    f"\n"
                    f"Last row: {age_min:.1f} min ago\n"
                    f"Rows in last {SILENCE_THRESHOLD_S//60} min: {recent_n}\n"
                    f"\n"
                    f"Detectors reading from snapshots will use STALE data. "
                    f"Restart the backend ASAP to restore the persist path."
                )
                try:
                    from .telegram import send
                    await send(msg, ticker="WATCHDOG", force=True)
                    print(f"[snap_watchdog] ALARM fired — age={age_min:.1f}min recent={recent_n}")
                except Exception as e:
                    print(f"[snap_watchdog] alarm send failed: {e}")
                _last_alarm_ts = now
                _alarm_armed = False  # don't re-fire until rearmed

            elif not silence_exceeded and not _alarm_armed:
                # Writes resumed — rearm if enough fresh rows
                if recent_n >= REARM_AFTER_ROWS:
                    _alarm_armed = True
                    print(f"[snap_watchdog] rearmed — {recent_n} fresh snapshots")
                    try:
                        from .telegram import send
                        await send(
                            f"✅ <b>Snapshot persist restored</b>\n"
                            f"{recent_n} rows written in last "
                            f"{SILENCE_THRESHOLD_S//60} min.",
                            ticker="WATCHDOG", force=True,
                        )
                    except Exception:
                        pass

        except Exception as e:
            print(f"[snap_watchdog] loop error: {e}")

    print("[snap_watchdog] loop stopped")
