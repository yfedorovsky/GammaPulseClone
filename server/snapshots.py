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


def insert(ticker: str, state: dict[str, Any]) -> None:
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
