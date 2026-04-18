"""Forward-return outcome tracking for every alert/signal GammaPulse generates.

Purpose: answer "the last N times this kind of setup fired, what happened next?"
Borrowed from the systematic-timing tool pattern (user's friend's Saturday-morning
screenshot) — `Day 50 · 28 prior SELLs · 1mo 46% · 3mo 77% · 6mo 92%`.

For every flow alert / sweep / SOE signal, we compute the forward price action
on the UNDERLYING (not the option — option P&L has too many confounds) at
1d / 3d / 1w / 2w / 1mo horizons. Binary "hit" flags respect direction:
  - BUY/BULLISH setup → hit = 1 if underlying closed higher
  - SELL/BEARISH setup → hit = 1 if underlying closed lower
  - NEUTRAL setup → hit = 0 (neutral signals don't predict direction)

The API exposes cohort-filtered aggregates for the UI hit-rate strip:
  "last 47 NVDA BUY sweeps ≥$500K → 1d 58% · 1w 72% · 1mo 64%"

Implementation notes
--------------------
- Outcomes are computed lazily via scripts/backfill_outcomes.py + an API refresh
  endpoint. No live tracking overhead on the signal-generation path.
- Daily closes come from snapshots.py (already backfilled 1yr for 187 tickers).
- When the forward date hasn't arrived yet, the corresponding column stays NULL
  and a later run fills it in (idempotent — INSERT OR REPLACE by (source, id)).
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings


# ── Schema ─────────────────────────────────────────────────────────

OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
  -- Source identification
  source_type TEXT NOT NULL,        -- 'sweep' | 'flow_alert' | 'soe_signal' | 'mir_signal' | 'flow_daily'
  source_id TEXT NOT NULL,          -- row id in originating table (int or composite)
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,          -- 'BUY' | 'SELL' | 'BULLISH' | 'BEARISH' | 'NEUTRAL'

  -- Trigger context
  trigger_ts INTEGER NOT NULL,      -- epoch seconds when the alert/signal fired
  trigger_date TEXT NOT NULL,       -- YYYY-MM-DD derived from trigger_ts
  trigger_price REAL,               -- underlying spot at trigger time
  notional REAL,                    -- for cohort filtering (sweeps/flow)
  grade TEXT,                       -- for SOE signals (A/A+/B+/etc.)
  is_sweep INTEGER DEFAULT 0,       -- for flow_alerts: 1 if ISO sweep
  sweep_venues INTEGER,             -- multi-venue attribution

  -- Forward prices (underlying close on T+N trading days, NULL if not yet available)
  price_1d REAL,
  price_3d REAL,
  price_1w REAL,
  price_2w REAL,
  price_1mo REAL,

  -- Forward returns (pct, same NULL semantics as prices)
  return_1d REAL,
  return_3d REAL,
  return_1w REAL,
  return_2w REAL,
  return_1mo REAL,

  -- Hit flags (NULL until forward price is known; 1/0 once computed)
  -- Hit = 1 if return respected the direction (BUY+up, SELL+down).
  -- For NEUTRAL direction, hit = NULL (unmeaningful).
  hit_1d INTEGER,
  hit_3d INTEGER,
  hit_1w INTEGER,
  hit_2w INTEGER,
  hit_1mo INTEGER,

  computed_ts INTEGER,

  PRIMARY KEY (source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_ticker ON signal_outcomes(ticker, trigger_ts);
CREATE INDEX IF NOT EXISTS idx_outcomes_source ON signal_outcomes(source_type, trigger_ts);
CREATE INDEX IF NOT EXISTS idx_outcomes_direction ON signal_outcomes(direction, trigger_ts);
"""


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db, timeout=30.0)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_outcomes_db() -> None:
    with _conn() as c:
        c.executescript(OUTCOMES_SCHEMA)


# ── Direction helpers ──────────────────────────────────────────────


BULLISH_DIRECTIONS = frozenset({"BUY", "BULLISH", "LONG", "CALL"})
BEARISH_DIRECTIONS = frozenset({"SELL", "BEARISH", "SHORT", "PUT"})


def hit_from_return(direction: str, ret: float | None) -> int | None:
    """Binary hit flag: 1 if return respected direction, 0 if not, NULL if either missing."""
    if ret is None:
        return None
    d = (direction or "").upper()
    if d in BULLISH_DIRECTIONS:
        return 1 if ret > 0 else 0
    if d in BEARISH_DIRECTIONS:
        return 1 if ret < 0 else 0
    return None  # NEUTRAL or unknown


# ── Insert / upsert ────────────────────────────────────────────────


UPSERT_SQL = """
INSERT OR REPLACE INTO signal_outcomes (
  source_type, source_id, ticker, direction,
  trigger_ts, trigger_date, trigger_price,
  notional, grade, is_sweep, sweep_venues,
  price_1d, price_3d, price_1w, price_2w, price_1mo,
  return_1d, return_3d, return_1w, return_2w, return_1mo,
  hit_1d, hit_3d, hit_1w, hit_2w, hit_1mo,
  computed_ts
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def upsert_outcomes_batch(rows: list[tuple]) -> int:
    if not rows:
        return 0
    with _conn() as c:
        c.executemany(UPSERT_SQL, rows)
    return len(rows)


# ── Aggregate query: hit-rate per cohort ───────────────────────────


def get_hit_rate(
    source_type: str | None = None,
    ticker: str | None = None,
    direction: str | None = None,
    min_notional: float = 0,
    grade: str | None = None,
    is_sweep: int | None = None,
    min_sweep_venues: int = 0,
    lookback_days: int = 90,
    limit: int = 1000,
) -> dict[str, Any]:
    """Return cohort-level hit-rate summary.

    Returns:
      {
        'cohort_size': 47,
        'lookback_days': 90,
        'filters': {...echoed args...},
        'horizons': {
          '1d':  {'n': 47, 'hits': 27, 'rate': 0.574, 'avg_return': 0.012},
          '3d':  {...},
          '1w':  {...},
          '2w':  {...},
          '1mo': {...},
        },
      }

    NULL-safe: a horizon's n = count where return is not null (i.e., the forward
    date has actually arrived). Hit rate is over that subset.
    """
    clauses = ["1=1"]
    args: list[Any] = []
    if source_type:
        clauses.append("source_type = ?")
        args.append(source_type)
    if ticker:
        clauses.append("ticker = ?")
        args.append(ticker.upper())
    if direction:
        clauses.append("direction = ?")
        args.append(direction.upper())
    if min_notional > 0:
        clauses.append("COALESCE(notional, 0) >= ?")
        args.append(min_notional)
    if grade:
        clauses.append("grade = ?")
        args.append(grade)
    if is_sweep is not None:
        clauses.append("is_sweep = ?")
        args.append(is_sweep)
    if min_sweep_venues > 0:
        clauses.append("COALESCE(sweep_venues, 0) >= ?")
        args.append(min_sweep_venues)
    if lookback_days > 0:
        cutoff = int(time.time()) - lookback_days * 86400
        clauses.append("trigger_ts >= ?")
        args.append(cutoff)

    where_sql = " AND ".join(clauses)

    horizons = {}
    with _conn() as c:
        cohort_size = c.execute(
            f"SELECT COUNT(*) FROM signal_outcomes WHERE {where_sql}", args
        ).fetchone()[0]

        for horizon in ("1d", "3d", "1w", "2w", "1mo"):
            ret_col = f"return_{horizon}"
            hit_col = f"hit_{horizon}"
            row = c.execute(
                f"""SELECT
                      COUNT(CASE WHEN {hit_col} IS NOT NULL THEN 1 END) AS n,
                      SUM(CASE WHEN {hit_col} = 1 THEN 1 ELSE 0 END) AS hits,
                      AVG({ret_col}) AS avg_ret
                    FROM signal_outcomes WHERE {where_sql}""",
                args,
            ).fetchone()
            n = row[0] or 0
            hits = row[1] or 0
            avg_ret = row[2] or 0.0
            horizons[horizon] = {
                "n": n,
                "hits": hits,
                "rate": (hits / n) if n > 0 else None,
                "avg_return": round(avg_ret, 4) if avg_ret else None,
            }

    return {
        "cohort_size": cohort_size,
        "lookback_days": lookback_days,
        "filters": {
            "source_type": source_type,
            "ticker": ticker,
            "direction": direction,
            "min_notional": min_notional,
            "grade": grade,
            "is_sweep": is_sweep,
            "min_sweep_venues": min_sweep_venues,
        },
        "horizons": horizons,
    }
