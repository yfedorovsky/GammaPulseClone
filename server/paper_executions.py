"""SQLite storage for paper-account execution tracking.

Both the auto-executor (`server/etrade_executor.py`) and the MCP server
(`mcp_servers/etrade_paper/server.py`) read/write this DB.

Schema mirrors the spec in `docs/research/ETRADE_PAPER_EXECUTION_SPEC.md`.
Per the production freeze, this DB is on `feature/etrade-paper-execution`
branch only and gitignored.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
PAPER_EXECUTIONS_DB = str(ROOT / "paper_executions.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  -- Source alert reference
  alert_source TEXT NOT NULL CHECK (alert_source IN ('0dte', 'st')),
  alert_id TEXT NOT NULL,
  fired_at INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,
  -- Order intent (what we WANTED to do)
  intent_strike REAL,
  intent_right TEXT,            -- 'CALL' or 'PUT'
  intent_expiration TEXT,       -- YYYY-MM-DD
  intent_limit_price REAL,
  intent_quantity INTEGER,
  -- Order placement (entry)
  entry_order_id TEXT,
  entry_placed_at INTEGER,
  entry_filled_at INTEGER,
  entry_fill_price REAL,
  entry_fill_status TEXT,       -- 'FILLED' / 'NO_FILL' / 'PARTIAL' / 'REJECTED' / 'PENDING' / 'CANCELLED'
  entry_preview_id TEXT,        -- E-Trade two-step preview→place id
  -- TP / Stop / Time-stop sub-orders
  tp_order_id TEXT,
  tp_filled_at INTEGER,
  tp_fill_price REAL,
  stop_order_id TEXT,
  stop_filled_at INTEGER,
  stop_fill_price REAL,
  time_stop_at INTEGER,         -- target timestamp (entry_filled_at + 30min)
  eod_close_at INTEGER,         -- target timestamp (15:55 ET on alert day)
  -- Final outcome
  exit_reason TEXT,             -- 'TP' / 'STOP' / 'TIME_STOP' / 'EOD' / 'NO_FILL' / 'ERROR'
  exit_price REAL,
  exit_at INTEGER,
  pnl_pct REAL,
  -- E-Trade context
  account_id_key TEXT,
  is_sandbox INTEGER NOT NULL,
  -- Audit
  notes TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(alert_source, alert_id)
);
CREATE INDEX IF NOT EXISTS idx_pe_fired_at ON paper_executions(fired_at);
CREATE INDEX IF NOT EXISTS idx_pe_ticker ON paper_executions(ticker, fired_at);
CREATE INDEX IF NOT EXISTS idx_pe_entry_status ON paper_executions(entry_fill_status);
CREATE INDEX IF NOT EXISTS idx_pe_exit_reason ON paper_executions(exit_reason);
"""


@contextmanager
def _conn(db_path: str = PAPER_EXECUTIONS_DB) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db(db_path: str = PAPER_EXECUTIONS_DB) -> None:
    with _conn(db_path) as c:
        c.executescript(SCHEMA)


# ── Insert / update operations ─────────────────────────────────────


def insert_intent(
    *, alert_source: str, alert_id: str, fired_at: int,
    ticker: str, direction: str,
    intent_strike: float | None, intent_right: str | None,
    intent_expiration: str | None,
    intent_limit_price: float | None, intent_quantity: int,
    is_sandbox: bool, account_id_key: str | None = None,
    notes: str | None = None,
    db_path: str = PAPER_EXECUTIONS_DB,
) -> int:
    """Insert a new execution-intent row. Returns the row id.

    Idempotent on (alert_source, alert_id) — if the row already exists,
    returns its existing id without modification."""
    init_db(db_path)
    now = int(time.time())
    with _conn(db_path) as c:
        cur = c.execute(
            "SELECT id FROM paper_executions WHERE alert_source = ? AND alert_id = ?",
            (alert_source, alert_id),
        )
        existing = cur.fetchone()
        if existing:
            return int(existing["id"])
        cur = c.execute(
            """INSERT INTO paper_executions (
                 alert_source, alert_id, fired_at, ticker, direction,
                 intent_strike, intent_right, intent_expiration,
                 intent_limit_price, intent_quantity,
                 entry_fill_status,
                 account_id_key, is_sandbox, notes, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)""",
            (alert_source, alert_id, fired_at, ticker, direction,
             intent_strike, intent_right, intent_expiration,
             intent_limit_price, intent_quantity,
             account_id_key, int(is_sandbox), notes, now, now),
        )
        return int(cur.lastrowid)


def update(
    row_id: int, fields: dict[str, Any],
    db_path: str = PAPER_EXECUTIONS_DB,
) -> None:
    """Update arbitrary fields on a row. Always bumps updated_at."""
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = int(time.time())
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values()) + [row_id]
    with _conn(db_path) as c:
        c.execute(f"UPDATE paper_executions SET {cols} WHERE id = ?", vals)


# ── Query operations (used by MCP + daily reports) ─────────────────


def get_by_alert(
    alert_source: str, alert_id: str,
    db_path: str = PAPER_EXECUTIONS_DB,
) -> dict[str, Any] | None:
    init_db(db_path)
    with _conn(db_path) as c:
        cur = c.execute(
            "SELECT * FROM paper_executions WHERE alert_source = ? AND alert_id = ?",
            (alert_source, alert_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_open_positions(db_path: str = PAPER_EXECUTIONS_DB) -> list[dict[str, Any]]:
    """Rows where entry filled but exit hasn't happened yet."""
    init_db(db_path)
    with _conn(db_path) as c:
        cur = c.execute(
            """SELECT * FROM paper_executions
               WHERE entry_fill_status = 'FILLED'
                 AND exit_reason IS NULL
               ORDER BY entry_filled_at"""
        )
        return [dict(r) for r in cur.fetchall()]


def get_pending_orders(db_path: str = PAPER_EXECUTIONS_DB) -> list[dict[str, Any]]:
    """Rows where entry order was placed but hasn't filled yet."""
    init_db(db_path)
    with _conn(db_path) as c:
        cur = c.execute(
            """SELECT * FROM paper_executions
               WHERE entry_fill_status IN ('PENDING', 'PARTIAL')
                 AND entry_order_id IS NOT NULL
               ORDER BY entry_placed_at"""
        )
        return [dict(r) for r in cur.fetchall()]


def get_today(db_path: str = PAPER_EXECUTIONS_DB) -> list[dict[str, Any]]:
    """Rows from today (UTC midnight to next midnight)."""
    init_db(db_path)
    from datetime import datetime
    now = datetime.now()
    t0 = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    t1 = t0 + 86400
    with _conn(db_path) as c:
        cur = c.execute(
            """SELECT * FROM paper_executions
               WHERE fired_at BETWEEN ? AND ?
               ORDER BY fired_at""",
            (t0, t1),
        )
        return [dict(r) for r in cur.fetchall()]


def get_recent(n: int = 50, db_path: str = PAPER_EXECUTIONS_DB) -> list[dict[str, Any]]:
    """Most recent N rows."""
    init_db(db_path)
    with _conn(db_path) as c:
        cur = c.execute(
            "SELECT * FROM paper_executions ORDER BY fired_at DESC LIMIT ?",
            (n,),
        )
        return [dict(r) for r in cur.fetchall()]


def summary_today(db_path: str = PAPER_EXECUTIONS_DB) -> dict[str, Any]:
    """Aggregate stats for today's executions."""
    init_db(db_path)
    rows = get_today(db_path)
    n_total = len(rows)
    n_filled = sum(1 for r in rows if r["entry_fill_status"] == "FILLED")
    n_open = sum(1 for r in rows if r["entry_fill_status"] == "FILLED"
                 and r["exit_reason"] is None)
    n_closed = sum(1 for r in rows if r["exit_reason"] is not None)
    closed_pnls = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
    return {
        "n_alerts": n_total,
        "n_filled": n_filled,
        "n_open_positions": n_open,
        "n_closed": n_closed,
        "mean_pnl_pct": (sum(closed_pnls) / len(closed_pnls)
                         if closed_pnls else None),
        "winners": sum(1 for p in closed_pnls if p > 0),
        "losers": sum(1 for p in closed_pnls if p <= 0),
    }
