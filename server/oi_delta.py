"""Daily OI snapshot + delta tracking for flow-direction inference.

Purpose (Priority 3 from Skylit synthesis): Tradier's OI is stale EOD
settlement. We have no way to know *direction* of today's flow without
OPRA tick classification. But we CAN observe OI changes between
consecutive days — a free proxy:

  - Rising OI + large volume → net new positions opened
  - Falling OI + large volume → net closing
  - Combined with intraday price action: can infer likely dealer side

## Schema

    CREATE TABLE daily_oi_snapshot (
        date        TEXT NOT NULL,        -- OCC settlement date (yesterday's close)
        ticker      TEXT NOT NULL,
        exp         TEXT NOT NULL,
        strike      REAL NOT NULL,
        option_type TEXT NOT NULL,        -- 'call' | 'put'
        oi          INTEGER NOT NULL,     -- settlement OI as of `date`
        volume      INTEGER,              -- volume that day (optional)
        captured_ts INTEGER NOT NULL,     -- when we recorded it
        PRIMARY KEY (date, ticker, exp, strike, option_type)
    );

## Workflow

1. Once per day at end-of-session (4:15 PM ET), snapshot current OI
   for every ticker in the universe. Store with yesterday's date (the
   settlement date this OI represents).
2. Next day during the session, look up yesterday's OI and compare to
   current Tradier OI to compute ΔOI:
      delta = today_OI - yesterday_OI
3. Use delta as a flow-direction hint:
      delta > 0 and today_volume high → net opening → big new exposure
      delta < 0 and today_volume high → net closing → exposure unwinding

## Retention

Keep 30 days rolling. Prune older rows on each daily snapshot run.

## When this pays off

After 1 burn-in day (tomorrow's EOD snapshot will be used by
Monday's scan). Before that, no delta available — degrade
gracefully to activity-weighted heuristic.

NOTE: This is Priority 3 of Option A (retail-honest improvements).
Priority 2 (absolute-magnitude King) is already shipped. Priority 4
(Vanna/Charm composite) and Priority 5 (Model A + Model B UI) are
pinned for future sessions.
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings


# ── Schema ────────────────────────────────────────────────────────────

OI_DELTA_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_oi_snapshot (
    date        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    exp         TEXT NOT NULL,
    strike      REAL NOT NULL,
    option_type TEXT NOT NULL,
    oi          INTEGER NOT NULL,
    volume      INTEGER DEFAULT 0,
    captured_ts INTEGER NOT NULL,
    PRIMARY KEY (date, ticker, exp, strike, option_type)
);
CREATE INDEX IF NOT EXISTS idx_dois_ticker_date ON daily_oi_snapshot(ticker, date);
CREATE INDEX IF NOT EXISTS idx_dois_date ON daily_oi_snapshot(date);
"""

RETENTION_DAYS = 30


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


def init_oi_delta_db() -> None:
    with _conn() as c:
        c.executescript(OI_DELTA_SCHEMA)


# ── Snapshot (called once per day at EOD) ────────────────────────────

def snapshot_ticker_oi(ticker: str, raw_contracts: dict[str, list[dict[str, Any]]]) -> int:
    """Persist per-contract OI for a single ticker. raw_contracts is a dict
    keyed by expiration string → list of Tradier option dicts.

    Returns the number of rows inserted/updated.
    """
    today = datetime.date.today().isoformat()
    ts = int(time.time())
    rows = []
    for exp, contracts in raw_contracts.items():
        for c in contracts:
            oi = c.get("open_interest")
            if not oi or oi <= 0:
                continue
            strike = c.get("strike")
            if not strike or strike <= 0:
                continue
            otype = (c.get("option_type") or "").lower()
            if otype not in ("call", "put"):
                continue
            vol = c.get("volume") or 0
            rows.append((today, ticker, exp, strike, otype, int(oi), int(vol), ts))

    if not rows:
        return 0

    try:
        with _conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO daily_oi_snapshot
                   (date, ticker, exp, strike, option_type, oi, volume, captured_ts)
                   VALUES (?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)
    except Exception as e:
        print(f"[oi_delta] snapshot_ticker_oi({ticker}) failed: {e}")
        return 0


def prune_old_snapshots() -> int:
    """Delete rows older than RETENTION_DAYS. Called daily after snapshot."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    try:
        with _conn() as c:
            cur = c.execute("DELETE FROM daily_oi_snapshot WHERE date < ?", (cutoff,))
            return cur.rowcount
    except Exception as e:
        print(f"[oi_delta] prune failed: {e}")
        return 0


# ── Lookup (called during intraday GEX compute) ──────────────────────

def get_prior_oi(
    ticker: str, exp: str, strike: float, option_type: str,
    lookback_days: int = 1,
) -> int | None:
    """Return the most recent stored OI for (ticker, exp, strike, type)
    from at least lookback_days ago. Used to compute ΔOI vs current.

    Returns None if no snapshot exists.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=lookback_days)).isoformat()
    try:
        with _conn() as c:
            row = c.execute(
                """SELECT oi FROM daily_oi_snapshot
                   WHERE ticker = ? AND exp = ? AND strike = ?
                     AND option_type = ? AND date <= ?
                   ORDER BY date DESC LIMIT 1""",
                (ticker, exp, strike, option_type.lower(), cutoff),
            ).fetchone()
            return int(row["oi"]) if row else None
    except Exception:
        return None


def get_oi_asof(
    ticker: str, exp: str, strike: float, option_type: str,
    asof_date: str, mode: str = "before",
) -> tuple[int | None, str | None]:
    """OI snapshot nearest `asof_date` (ISO) for one contract.
    mode='before' → most recent snapshot with date <= asof_date;
    mode='after'  → earliest snapshot with date >= asof_date.
    Returns (oi, snapshot_date) or (None, None). Used to compute the OI change
    ACROSS a flow event (post - pre) = did the flow OPEN (accumulation) or CLOSE (exit)."""
    op, order = ("<=", "DESC") if mode == "before" else (">=", "ASC")
    try:
        with _conn() as c:
            row = c.execute(
                f"""SELECT oi, date FROM daily_oi_snapshot
                    WHERE ticker=? AND exp=? AND strike=? AND option_type=? AND date {op} ?
                    ORDER BY date {order} LIMIT 1""",
                (ticker, exp, float(strike), option_type.lower(), asof_date),
            ).fetchone()
            return (int(row["oi"]), row["date"]) if row else (None, None)
    except Exception:
        return (None, None)


def get_ticker_deltas(
    ticker: str, lookback_days: int = 1,
) -> dict[tuple[str, float, str], dict[str, Any]]:
    """Return {(exp, strike, option_type) → {prior_oi, prior_date}} for every
    contract we have a snapshot for in the lookback window.

    Worker can join this dict against live Tradier OI to compute deltas in a
    single batch.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=lookback_days)).isoformat()
    try:
        with _conn() as c:
            rows = c.execute(
                """SELECT exp, strike, option_type, oi, date FROM daily_oi_snapshot
                   WHERE ticker = ? AND date <= ?
                   GROUP BY exp, strike, option_type
                   HAVING date = MAX(date)""",
                (ticker, cutoff),
            ).fetchall()
        return {
            (r["exp"], r["strike"], r["option_type"]): {
                "prior_oi": r["oi"],
                "prior_date": r["date"],
            }
            for r in rows
        }
    except Exception as e:
        print(f"[oi_delta] get_ticker_deltas({ticker}) failed: {e}")
        return {}


def stats() -> dict[str, Any]:
    """Quick diagnostic for API/debug."""
    try:
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) as n FROM daily_oi_snapshot").fetchone()["n"]
            days = c.execute(
                "SELECT COUNT(DISTINCT date) as n FROM daily_oi_snapshot"
            ).fetchone()["n"]
            tickers = c.execute(
                "SELECT COUNT(DISTINCT ticker) as n FROM daily_oi_snapshot"
            ).fetchone()["n"]
            latest = c.execute(
                "SELECT MAX(date) as d FROM daily_oi_snapshot"
            ).fetchone()["d"]
        return {
            "total_rows": total,
            "distinct_days": days,
            "distinct_tickers": tickers,
            "latest_date": latest,
        }
    except Exception as e:
        return {"error": str(e)}
