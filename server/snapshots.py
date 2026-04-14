"""SQLite snapshot store for the HISTORY tab.

Schema:
  snapshots(id, ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
            pos_gex, neg_gex, net_delta, net_vanna, iv)

We keep ~5-minute resolution snapshots per ticker and trim old rows on insert.
"""
from __future__ import annotations

import sqlite3
import time
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
  iv REAL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_ts ON snapshots(ticker, ts);
"""


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
    await db.write(
        """INSERT INTO snapshots
        (ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
         pos_gex, neg_gex, net_delta, net_vanna, iv)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            int(time.time()),
            state.get("actual_spot") or state.get("_spot"),
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
        ),
    )


def insert(ticker: str, state: dict[str, Any]) -> None:
    """Synchronous fallback for non-async callers (e.g., init, tests)."""
    with _conn() as c:
        c.execute(
            """INSERT INTO snapshots
            (ticker, ts, spot, king, floor, ceiling, zgl, signal, regime,
             pos_gex, neg_gex, net_delta, net_vanna, iv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                int(time.time()),
                state.get("actual_spot") or state.get("_spot"),
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
