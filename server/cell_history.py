"""Per-cell GEX intraday change tracking (Skylit heatseeker-style).

Purpose: decorate each strike in `exp_data.strikes` with `open_change_pct`
so the heatmap can show "+11%" / "-3%" badges indicating how dealers have
moved GEX at that specific strike since market open. Lets you spot real-time
positioning shifts that aren't visible in the static snapshot.

Architecture:
  - In-memory dict keyed by (ticker, exp) → {strike: open_net_gex}
  - SQLite persistence via `cell_gex_open` table so we survive restarts
  - Snapshot fires once per (ticker, exp) per trading day, on the first
    cycle that runs after 9:30 AM ET (market open)
  - Decoration is O(n_strikes) per cycle — negligible overhead

Denominator threshold: we only compute change% when the open value was at
least $50K in absolute magnitude. Below that, division amplifies noise into
huge spurious %s (e.g. a $500 → $5K move is +900% but structurally meaningless).
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

try:
    import pytz  # type: ignore
    _ET = pytz.timezone("America/New_York")
except ImportError:
    _ET = None

from .config import get_settings
from .market_calendar import is_market_holiday


# ── Schema ────────────────────────────────────────────────────────────

CELL_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS cell_gex_open (
    ticker      TEXT NOT NULL,
    exp         TEXT NOT NULL,
    strike      REAL NOT NULL,
    open_net_gex REAL,
    open_ts     INTEGER NOT NULL,
    date        TEXT NOT NULL,
    UNIQUE(ticker, exp, strike, date)
);
CREATE INDEX IF NOT EXISTS idx_cgo_tikexp ON cell_gex_open(ticker, exp, date);
CREATE INDEX IF NOT EXISTS idx_cgo_date ON cell_gex_open(date);
"""

# Threshold — only compute % change when open value was meaningful.
# $50K is our "noise floor" — below this, % changes are not informative.
MIN_DENOMINATOR_ABS = 50_000

# Minimum |change%| to surface in API output / render a badge. Avoids UI
# clutter from 1% wiggles. Skylit appears to threshold around 3-5%.
MIN_CHANGE_PCT_TO_REPORT = 3.0


# ── In-memory state ────────────────────────────────────────────────────

# (ticker, exp) -> {strike: open_net_gex}
_open_cells: dict[tuple[str, str], dict[float, float]] = {}
# The date all _open_cells were captured under. Resets the dict on date roll.
_open_date: str = ""


# ── DB helpers ────────────────────────────────────────────────────────

@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_cell_history_db() -> None:
    """Create table + reload today's open snapshots into memory on startup."""
    with _conn() as c:
        c.executescript(CELL_HISTORY_SCHEMA)
    _load_today_from_db()


def _load_today_from_db() -> None:
    """Restore today's open snapshots into _open_cells so a restart during
    the trading day doesn't treat 2 PM as 'open'."""
    global _open_date
    today = _today_iso()
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT ticker, exp, strike, open_net_gex FROM cell_gex_open WHERE date = ?",
                (today,),
            ).fetchall()
        if rows:
            loaded = 0
            for r in rows:
                key = (r["ticker"], r["exp"])
                if key not in _open_cells:
                    _open_cells[key] = {}
                _open_cells[key][r["strike"]] = r["open_net_gex"]
                loaded += 1
            _open_date = today
            print(f"[cell_history] Restored {loaded} open snapshots across {len(_open_cells)} (ticker,exp) keys for {today}")
        else:
            _open_date = today
    except Exception as e:
        print(f"[cell_history] Error loading today's snapshots: {e}")


# ── Time helpers ──────────────────────────────────────────────────────

def _now_et() -> datetime.datetime:
    """Current time in US/Eastern. Falls back to naive local if pytz absent."""
    if _ET is not None:
        return datetime.datetime.now(_ET)
    return datetime.datetime.now()


def _today_iso() -> str:
    return _now_et().date().isoformat()


def _is_after_open() -> bool:
    """True once the ET clock is past 9:30 AM on a weekday."""
    now = _now_et()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    # 9:30 AM ET — snapshot window starts here
    return now.hour > 9 or (now.hour == 9 and now.minute >= 30)


def _is_capture_window() -> bool:
    """True only during the first 30 min of regular hours (9:30-10:00 ET).

    Capture window is narrow to prevent a mid-day server start from snapshotting
    stale 2pm values as "open". If no snapshot exists past 10:00 AM, we skip
    decoration for the rest of today — no badges rather than wrong badges.
    """
    now = _now_et()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    if now.hour == 9 and now.minute >= 30:
        return True
    # 10:00 AM ET exactly — still in window for the cycle that runs at 10:00
    if now.hour == 10 and now.minute == 0:
        return True
    return False


def _reset_if_date_rolled() -> None:
    """Clear in-memory cache at the start of a new trading day."""
    global _open_cells, _open_date
    today = _today_iso()
    if _open_date and _open_date != today:
        print(f"[cell_history] Date rolled {_open_date} -> {today}, clearing {len(_open_cells)} open snapshots")
        _open_cells = {}
        _open_date = today


# ── Main API ──────────────────────────────────────────────────────────

def snapshot_and_decorate(ticker: str, exp: str, strikes: list[dict[str, Any]]) -> None:
    """Two jobs in one call (so we only iterate strikes once):

      1. If this (ticker, exp) doesn't have an open snapshot for today
         AND we're past 9:30 AM ET, capture one now.
      2. Decorate each strike dict with `open_change_pct` if we can compute it.

    Mutates `strikes` in place. Safe to call pre-open (does nothing).
    """
    _reset_if_date_rolled()

    if not _is_after_open():
        return  # before market open, nothing to do

    key = (ticker, exp)
    open_map = _open_cells.get(key)

    # Capture only during the first 30 min of regular hours. If the server
    # boots mid-session with no prior snapshot, don't capture — degrade
    # gracefully to "no badges today" rather than fake an "open" from
    # mid-afternoon values.
    if open_map is None:
        if not _is_capture_window():
            return  # no snapshot today, no decoration
        open_map = {s["strike"]: (s.get("net_gex") or 0.0) for s in strikes}
        _open_cells[key] = open_map
        _persist_open_snapshot(ticker, exp, open_map)

    # Decorate
    for s in strikes:
        current = s.get("net_gex") or 0.0
        open_val = open_map.get(s["strike"])
        if open_val is None:
            # Strike wasn't present at open — new OI appeared intraday
            s["open_change_pct"] = None
            continue
        denom = abs(open_val)
        if denom < MIN_DENOMINATOR_ABS:
            # Open value too small — % change would be noise
            s["open_change_pct"] = None
            continue
        change_pct = (current - open_val) / denom * 100
        if abs(change_pct) < MIN_CHANGE_PCT_TO_REPORT:
            s["open_change_pct"] = None  # below UI threshold
        else:
            s["open_change_pct"] = round(change_pct, 1)


def _persist_open_snapshot(ticker: str, exp: str, open_map: dict[float, float]) -> None:
    """Write to SQLite so a restart during the day doesn't re-capture 'open'
    as the restart-moment value."""
    if not open_map:
        return
    ts = int(time.time())
    date = _today_iso()
    try:
        with _conn() as c:
            c.executemany(
                "INSERT OR IGNORE INTO cell_gex_open "
                "(ticker, exp, strike, open_net_gex, open_ts, date) VALUES (?,?,?,?,?,?)",
                [(ticker, exp, strike, gex, ts, date) for strike, gex in open_map.items()],
            )
    except Exception as e:
        print(f"[cell_history] persist error for {ticker}/{exp}: {e}")


def prune_old_snapshots(keep_days: int = 7) -> int:
    """Remove cell_gex_open rows older than `keep_days`. Called daily."""
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    try:
        with _conn() as c:
            cur = c.execute("DELETE FROM cell_gex_open WHERE date < ?", (cutoff_date,))
            return cur.rowcount
    except Exception as e:
        print(f"[cell_history] prune error: {e}")
        return 0


def stats() -> dict[str, Any]:
    """Debug snapshot of current state."""
    total_cells = sum(len(m) for m in _open_cells.values())
    return {
        "date": _open_date,
        "keys_tracked": len(_open_cells),
        "total_cells": total_cells,
        "is_after_open": _is_after_open(),
    }
