"""SQLite snapshot store for the HISTORY tab.

Schema:
  snapshots(id, ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
            pos_gex, neg_gex, net_delta, net_vanna, iv, is_stale)

We keep ~5-minute resolution snapshots per ticker and trim old rows on insert.

2026-05-21 PM addition: staleness detection. 5/21 audit revealed DIA spot
stuck at $500.66 for 6 hours of RTH while real DIA moved $499 -> $503. The
detector tracks per-ticker recent spot writes; if the last N writes are all
identical AND span > 2 min during RTH, is_stale=1 is set and the write is
logged once per (ticker, day). Pure instrumentation — write still happens,
detectors can later choose to filter on is_stale=0.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import time
from collections import deque
from contextlib import contextmanager
from typing import Any

from .config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  ts INTEGER NOT NULL,
  spot REAL,
  king REAL,
  floor REAL,
  ceiling REAL,
  zgl REAL,
  signal TEXT,
  regime TEXT,
  pos_gex REAL,
  neg_gex REAL,
  net_delta REAL,
  net_vanna REAL,
  iv REAL,
  is_stale INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_ts ON snapshots(ticker, ts);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Staleness detection (2026-05-21 PM)
# ─────────────────────────────────────────────────────────────────────────────

# Track last N (spot, ts) pairs per ticker. Deque grows up to MAX, then rotates.
_recent_spots: dict[str, deque[tuple[float, int]]] = {}
_RECENT_MAX = 5

# Dedup: log a stale-detection event at most once per (ticker, day).
_stale_logged_today: set[tuple[str, str]] = set()

# Thresholds: stale = last N identical spots AND span > THRESHOLD_S
_STALE_MIN_DUPLICATES = 4   # 4 identical writes in a row
_STALE_MIN_SPAN_S = 120     # those writes must span > 2 min (so we're not
                            # just catching back-to-back-millisecond writes)


def _is_rth() -> bool:
    """RTH = weekday, 9:30-16:00 ET."""
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    if hm < (9, 30):
        return False
    if now.hour >= 16:
        return False
    return True


def _check_stale(ticker: str, spot: float | None, ts: int) -> int:
    """Return 1 if the new (spot, ts) write looks stale, else 0.

    Stale = the last _STALE_MIN_DUPLICATES writes all have the same spot AND
    the oldest of those writes was more than _STALE_MIN_SPAN_S seconds ago.

    Only flags during RTH — pre/post market deduplicates are normal because
    quote feeds are slow when the market is closed.
    """
    if spot is None or spot <= 0:
        return 0

    dq = _recent_spots.setdefault(ticker, deque(maxlen=_RECENT_MAX))
    # Push the new write before evaluating so future calls see this row.
    dq.append((float(spot), int(ts)))

    if not _is_rth():
        return 0
    if len(dq) < _STALE_MIN_DUPLICATES:
        return 0

    # Look at the last N writes including the one we just added.
    last_n = list(dq)[-_STALE_MIN_DUPLICATES:]
    spots = [s for s, _t in last_n]
    if len(set(spots)) > 1:
        return 0  # at least one different value -> not stale
    span = last_n[-1][1] - last_n[0][1]
    if span < _STALE_MIN_SPAN_S:
        return 0  # writes happened too close together to count as stale

    # Stale. Log once per (ticker, day).
    day = _dt.date.today().isoformat()
    key = (ticker, day)
    if key not in _stale_logged_today:
        _stale_logged_today.add(key)
        print(
            f"[SNAP-STALE] ticker={ticker} spot={spot} "
            f"duplicates={_STALE_MIN_DUPLICATES}+ span={span}s "
            f"(detector worker is writing the same spot repeatedly during RTH — "
            f"upstream Theta/Tradier feed likely frozen)",
            flush=True,
        )
    return 1


def is_latest_stale(ticker: str) -> int:
    """Return is_stale value (0 or 1) of the most recent snapshot for ticker.

    Used by alert_outcomes.log_alert to tag entry_was_stale. Returns 0 on any
    error / missing data (the safer default — don't flag unless we're sure)."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT is_stale FROM snapshots WHERE ticker = ? "
                "ORDER BY ts DESC LIMIT 1",
                (ticker,),
            ).fetchone()
        if not row:
            return 0
        return int(row["is_stale"] or 0)
    except Exception:
        return 0


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


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


async def insert_async(ticker: str, state: dict[str, Any]) -> None:
    """Queue a snapshot write through the single-writer (preferred for async callers)."""
    from .db import db
    ts_now = int(time.time())
    spot = state.get("actual_spot") or state.get("_spot")
    is_stale = _check_stale(ticker, spot, ts_now)
    await db.write(
        """INSERT INTO snapshots
        (ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
         pos_gex, neg_gex, net_delta, net_vanna, iv, is_stale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            ts_now,
            spot,
            state.get("king"),
            state.get("floor"),
            state.get("ceiling"),
            state.get("zgl") or (state.get("exp_data", {}).get("MACRO (ALL 200D)") or {}).get("zgl"),
            state.get("signal"),
            state.get("regime"),
            state.get("pos_gex"),
            state.get("neg_gex"),
            state.get("net_delta"),
            state.get("net_vanna"),
            state.get("iv"),
            is_stale,
        ),
    )


def insert(ticker: str, state: dict[str, Any]) -> None:
    """Synchronous fallback for non-async callers (e.g., init, tests)."""
    ts_now = int(time.time())
    spot = state.get("actual_spot") or state.get("_spot")
    is_stale = _check_stale(ticker, spot, ts_now)
    with _conn() as c:
        c.execute(
            """INSERT INTO snapshots
            (ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
             pos_gex, neg_gex, net_delta, net_vanna, iv, is_stale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                ts_now,
                spot,
                state.get("king"),
                state.get("floor"),
                state.get("ceiling"),
                state.get("zgl") or (state.get("exp_data", {}).get("MACRO (ALL 200D)") or {}).get("zgl"),
                state.get("signal"),
                state.get("regime"),
                state.get("pos_gex"),
                state.get("neg_gex"),
                state.get("net_delta"),
                state.get("net_vanna"),
                state.get("iv"),
                is_stale,
            ),
        )


def series(ticker: str, limit: int = 500) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM snapshots WHERE ticker = ? ORDER BY ts DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def prune(keep_days: int = 14) -> None:
    cutoff = int(time.time()) - keep_days * 86400
    with _conn() as c:
        c.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))


def get_iv_history(ticker: str, days: int = 365) -> list[float]:
    """Return list of historical IV values for a ticker over the past N days.

    Used for per-ticker IV Percentile (IVP) calculation.
    Returns one IV value per snapshot (5-min resolution), deduplicated to
    daily close values by taking the last snapshot of each day.
    """
    cutoff = int(time.time()) - days * 86400
    with _conn() as c:
        # Get daily max-timestamp IV values to avoid intraday noise
        rows = c.execute(
            """SELECT iv FROM snapshots
               WHERE ticker = ? AND ts > ? AND iv > 0 AND iv IS NOT NULL
               GROUP BY date(ts, 'unixepoch')
               HAVING ts = MAX(ts)
               ORDER BY ts""",
            (ticker, cutoff),
        ).fetchall()
    return [r["iv"] for r in rows if r["iv"]]


def get_daily_closes(ticker: str, days: int = 30) -> list[float]:
    """Return daily close (last snapshot of each day) for realized vol calculation."""
    cutoff = int(time.time()) - days * 86400
    with _conn() as c:
        rows = c.execute(
            """SELECT spot FROM snapshots
               WHERE ticker = ? AND ts > ? AND spot > 0 AND spot IS NOT NULL
               GROUP BY date(ts, 'unixepoch')
               HAVING ts = MAX(ts)
               ORDER BY ts""",
            (ticker, cutoff),
        ).fetchall()
    return [r["spot"] for r in rows if r["spot"]]


def compute_realized_vol(daily_closes: list[float], window: int = 20) -> float | None:
    """Compute annualized realized volatility from daily close prices.

    Uses the standard log-return method with a 20-day lookback.
    Returns annualized vol as a decimal (e.g., 0.25 = 25%).
    Returns None if insufficient data.
    """
    if len(daily_closes) < window + 1:
        return None
    import math
    # Use the most recent `window` days
    closes = daily_closes[-(window + 1):]
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(log_returns) < window:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)
    annualized = daily_vol * math.sqrt(252)
    return round(annualized, 4)


def compute_ivp(ticker: str, current_iv: float, days: int = 365) -> float | None:
    """Compute IV Percentile: % of past observations where IV was lower.

    Returns 0-100 scale, or None if insufficient history (<20 data points).
    Industry standard: Tastytrade, Schwab, Menthor Q all use this.
    """
    history = get_iv_history(ticker, days)
    if len(history) < 20:
        return None
    lower = sum(1 for h in history if h < current_iv)
    return round(lower / len(history) * 100, 1)
