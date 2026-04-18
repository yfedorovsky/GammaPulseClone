"""Per-contract daily option flow aggregation — broader than ISO sweeps.

The SWEEPS tab (server/sweep_detector.py) captures only OPRA-tagged ISO
prints (condition 95/126/128) — the narrowest, highest-signal subset.
This module captures ALL aggressive flow per contract per day, matching
the view that UW and similar tools show:

  NVDA $200C 04-20 (3d)  vol=84,694  notional=$22.2M  Bought  sweep%=7%

Differences vs sweep_detector:
  - Aggregation grain: one row per (date, ticker, strike, exp, type)
    (vs sweep's 30s time-bucket rollups)
  - Filter: includes BOTH sweep (cond 95/126/128) AND non-ISO aggressive
    prints (any trade with price >= ask or price <= bid)
  - Output: total daily flow with buy/sell/neutral splits + sweep share

Architecture:
  - Backfill: scripts/backfill_option_flow.py pulls trade_quote history
    per contract, aggregates into this table
  - Live: not implemented in this first version — data is populated
    daily via backfill. Live streaming is a follow-up (needs broader
    WebSocket subscription than the narrow sweep ATM watchlist).
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings


# ── Schema ─────────────────────────────────────────────────────────

FLOW_DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_flow_daily (
  date TEXT NOT NULL,                      -- YYYY-MM-DD (trade date)
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,                -- YYYY-MM-DD
  option_type TEXT NOT NULL,               -- 'call' | 'put'

  -- Totals (includes ALL non-cancelled prints)
  total_volume INTEGER DEFAULT 0,
  total_notional REAL DEFAULT 0,
  trade_count INTEGER DEFAULT 0,

  -- Side split (strict NBBO classification: price >= ask = BUY, price <= bid = SELL)
  buy_volume INTEGER DEFAULT 0,
  buy_notional REAL DEFAULT 0,
  sell_volume INTEGER DEFAULT 0,
  sell_notional REAL DEFAULT 0,
  neutral_volume INTEGER DEFAULT 0,
  neutral_notional REAL DEFAULT 0,

  -- Sweep share (subset of the above; ISO condition 95/126/128)
  sweep_volume INTEGER DEFAULT 0,
  sweep_notional REAL DEFAULT 0,
  sweep_prints INTEGER DEFAULT 0,

  -- Block trade share (condition 75; off-exchange institutional blocks)
  block_volume INTEGER DEFAULT 0,
  block_notional REAL DEFAULT 0,

  -- Biggest single print of the day (for UW-style "detail" field)
  largest_print_size INTEGER DEFAULT 0,
  largest_print_price REAL DEFAULT 0,
  largest_print_time TEXT,                 -- ISO timestamp
  largest_print_venue INTEGER,
  largest_print_side TEXT,
  largest_print_is_sweep INTEGER DEFAULT 0,

  -- Static context (latest snapshot values; approximate for historical dates)
  oi INTEGER,
  iv REAL,
  delta REAL,
  spot REAL,

  -- When this row was written/refreshed
  updated_ts INTEGER DEFAULT 0,

  PRIMARY KEY (date, ticker, strike, expiration, option_type)
);
CREATE INDEX IF NOT EXISTS idx_flow_daily_date ON option_flow_daily(date);
CREATE INDEX IF NOT EXISTS idx_flow_daily_ticker ON option_flow_daily(ticker, date);
CREATE INDEX IF NOT EXISTS idx_flow_daily_notional ON option_flow_daily(total_notional DESC);
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


# ── GOLDEN FLOW classifier ─────────────────────────────────────────
#
# Pattern targeted: the SPY 647P 03/24/2026 trade that hit 15 min before
# market-moving headlines — $1.49M premium, 76% bought at ask, V/OI ~10x,
# 1% OTM, 1DTE. All the classic insider-flow fingerprints.
#
# Rules (all must match):
#   1. Notional        >= $500K          (material size)
#   2. Bought%         >= 70%            (aggressive at-ask, not mid)
#   3. Volume / OI     >= 3.0            (opening position, not closing)
#   4. |strike-spot|/spot <= 2.5%        (just OTM / near-ATM)
#   5. DTE             <= 2              (short-dated = high leverage)

GOLDEN_FLOW_RULES = {
    "min_notional": 500_000,
    "min_bought_pct": 0.70,
    "min_vol_oi_ratio": 3.0,
    "max_otm_pct": 0.025,
    "max_dte": 2,
}


def is_golden_flow(row: dict) -> tuple[bool, list[str]]:
    """Return (is_golden, list_of_failed_rules).

    Row is a dict matching option_flow_daily columns (or close). Missing
    fields fail their rule. Enables "show me what's ALMOST golden" UI later.
    """
    failed: list[str] = []

    notional = row.get("total_notional") or 0
    if notional < GOLDEN_FLOW_RULES["min_notional"]:
        failed.append(f"notional(${notional/1000:.0f}K<${GOLDEN_FLOW_RULES['min_notional']/1000:.0f}K)")

    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    neutral = row.get("neutral_notional") or 0
    total = buy + sell + neutral
    bought_pct = (buy / total) if total > 0 else 0
    if bought_pct < GOLDEN_FLOW_RULES["min_bought_pct"]:
        failed.append(f"bought_pct({bought_pct*100:.0f}%<{GOLDEN_FLOW_RULES['min_bought_pct']*100:.0f}%)")

    vol = row.get("total_volume") or 0
    oi = row.get("oi") or 0
    vol_oi = (vol / oi) if oi > 0 else float("inf")  # no OI = definitely new
    if oi > 0 and vol_oi < GOLDEN_FLOW_RULES["min_vol_oi_ratio"]:
        failed.append(f"vol/oi({vol_oi:.1f}x<{GOLDEN_FLOW_RULES['min_vol_oi_ratio']}x)")

    strike = row.get("strike") or 0
    spot = row.get("spot") or 0
    otm_pct = abs(strike - spot) / spot if (strike > 0 and spot > 0) else 1.0
    if otm_pct > GOLDEN_FLOW_RULES["max_otm_pct"]:
        failed.append(f"OTM({otm_pct*100:.1f}%>{GOLDEN_FLOW_RULES['max_otm_pct']*100:.1f}%)")

    # DTE = days between expiration and trade date
    from datetime import date as _date
    trade_date = row.get("date") or ""
    exp = row.get("expiration") or ""
    try:
        td = _date.fromisoformat(trade_date)
        ed = _date.fromisoformat(exp)
        dte = (ed - td).days
    except (ValueError, TypeError):
        dte = 999
    if dte > GOLDEN_FLOW_RULES["max_dte"]:
        failed.append(f"dte({dte}>{GOLDEN_FLOW_RULES['max_dte']})")

    return (len(failed) == 0), failed


def get_golden_flow(
    since_date: str | None = None, ticker: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query flow_daily + apply Golden Flow classifier. Returns only matches."""
    from .option_flow_daily import get_flow_daily  # self-ref for import clarity
    rows = get_flow_daily(
        since_date=since_date, ticker=ticker,
        min_notional=GOLDEN_FLOW_RULES["min_notional"],
        limit=limit * 5,  # fetch more, filter down
    )
    golden: list[dict] = []
    for r in rows:
        is_gold, _failed = is_golden_flow(r)
        if is_gold:
            r["_golden"] = True
            golden.append(r)
    return golden[:limit]


def init_flow_daily_db() -> None:
    with _conn() as c:
        c.executescript(FLOW_DAILY_SCHEMA)


# ── Aggregator ─────────────────────────────────────────────────────

# Block trade condition
COND_BLOCK_TRADE = 75


class DailyFlowAggregate:
    """Per-contract daily accumulator.

    Consume each trade print via `add()`. When all trades for a contract-day
    have been consumed, call `.to_row()` to get the dict for DB upsert.
    """

    def __init__(self, date: str, ticker: str, strike: float, expiration: str, option_type: str):
        self.date = date
        self.ticker = ticker
        self.strike = strike
        self.expiration = expiration
        self.option_type = option_type

        self.total_volume = 0
        self.total_notional = 0.0
        self.trade_count = 0

        self.buy_volume = 0
        self.buy_notional = 0.0
        self.sell_volume = 0
        self.sell_notional = 0.0
        self.neutral_volume = 0
        self.neutral_notional = 0.0

        self.sweep_volume = 0
        self.sweep_notional = 0.0
        self.sweep_prints = 0

        self.block_volume = 0
        self.block_notional = 0.0

        self.largest_print_size = 0
        self.largest_print_price = 0.0
        self.largest_print_time = ""
        self.largest_print_venue = 0
        self.largest_print_side = "NEUTRAL"
        self.largest_print_is_sweep = False

    def add(
        self, *, size: int, price: float, exchange: int, condition: int,
        side: str, is_sweep: bool, timestamp: str,
    ) -> None:
        notional = size * price * 100.0

        self.total_volume += size
        self.total_notional += notional
        self.trade_count += 1

        if side == "BUY":
            self.buy_volume += size
            self.buy_notional += notional
        elif side == "SELL":
            self.sell_volume += size
            self.sell_notional += notional
        else:
            self.neutral_volume += size
            self.neutral_notional += notional

        if is_sweep:
            self.sweep_volume += size
            self.sweep_notional += notional
            self.sweep_prints += 1

        if condition == COND_BLOCK_TRADE:
            self.block_volume += size
            self.block_notional += notional

        # Track biggest single print by size (could also be by notional — size
        # is simpler and matches UW's "N blocks" semantic)
        if size > self.largest_print_size:
            self.largest_print_size = size
            self.largest_print_price = price
            self.largest_print_time = timestamp
            self.largest_print_venue = exchange
            self.largest_print_side = side
            self.largest_print_is_sweep = is_sweep

    @property
    def dominant_side(self) -> str:
        """Aggregate side determined by notional majority (>55% threshold)."""
        total = self.buy_notional + self.sell_notional + self.neutral_notional
        if total <= 0:
            return "NEUTRAL"
        if self.buy_notional / total >= 0.55:
            return "BUY"
        if self.sell_notional / total >= 0.55:
            return "SELL"
        return "NEUTRAL"

    @property
    def bought_pct(self) -> float:
        """Fraction of notional at/above ask."""
        total = self.buy_notional + self.sell_notional + self.neutral_notional
        return self.buy_notional / total if total > 0 else 0.0

    @property
    def sweep_share(self) -> float:
        """Fraction of notional that was ISO sweep."""
        return self.sweep_notional / self.total_notional if self.total_notional > 0 else 0.0

    def to_db_tuple(self, oi: int | None, iv: float | None, delta: float | None, spot: float | None) -> tuple:
        """Build the tuple for INSERT OR REPLACE INTO option_flow_daily."""
        return (
            self.date, self.ticker, self.strike, self.expiration, self.option_type,
            self.total_volume, round(self.total_notional, 2), self.trade_count,
            self.buy_volume, round(self.buy_notional, 2),
            self.sell_volume, round(self.sell_notional, 2),
            self.neutral_volume, round(self.neutral_notional, 2),
            self.sweep_volume, round(self.sweep_notional, 2), self.sweep_prints,
            self.block_volume, round(self.block_notional, 2),
            self.largest_print_size, self.largest_print_price,
            self.largest_print_time, self.largest_print_venue,
            self.largest_print_side, 1 if self.largest_print_is_sweep else 0,
            oi, iv, delta, spot,
            int(time.time()),
        )


# ── Batch insert ───────────────────────────────────────────────────


UPSERT_SQL = """
INSERT OR REPLACE INTO option_flow_daily (
  date, ticker, strike, expiration, option_type,
  total_volume, total_notional, trade_count,
  buy_volume, buy_notional, sell_volume, sell_notional,
  neutral_volume, neutral_notional,
  sweep_volume, sweep_notional, sweep_prints,
  block_volume, block_notional,
  largest_print_size, largest_print_price, largest_print_time,
  largest_print_venue, largest_print_side, largest_print_is_sweep,
  oi, iv, delta, spot, updated_ts
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def upsert_flow_daily_batch(rows: list[tuple]) -> int:
    """Upsert a list of flow-daily tuples in a single transaction."""
    if not rows:
        return 0
    with _conn() as c:
        c.executemany(UPSERT_SQL, rows)
    return len(rows)


def clean_flow_daily_range(dates: list[str], tickers: list[str]) -> int:
    """Delete rows for date range × ticker list (for idempotent re-backfill)."""
    if not dates or not tickers:
        return 0
    ticker_filter = ",".join(f"'{t.upper()}'" for t in tickers)
    date_filter = ",".join(f"'{d}'" for d in dates)
    with _conn() as c:
        cur = c.execute(
            f"DELETE FROM option_flow_daily "
            f"WHERE date IN ({date_filter}) AND ticker IN ({ticker_filter})"
        )
        return cur.rowcount


def get_flow_daily(
    since_date: str | None = None, ticker: str | None = None,
    min_notional: float = 0, min_oi: int = 0, side: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Query per-contract daily flow, sorted by total_notional desc."""
    clauses = ["1=1"]
    args: list[Any] = []
    if since_date:
        clauses.append("date >= ?")
        args.append(since_date)
    if ticker:
        clauses.append("ticker = ?")
        args.append(ticker.upper())
    if min_notional > 0:
        clauses.append("total_notional >= ?")
        args.append(min_notional)
    if min_oi > 0:
        clauses.append("COALESCE(oi, 0) >= ?")
        args.append(min_oi)
    if side and side != "ALL":
        # Dominant side computed client-side from buy/sell/neutral notional
        # but we can pre-filter with heuristic: majority side > 55%
        if side == "BUY":
            clauses.append("buy_notional > sell_notional AND buy_notional > neutral_notional")
        elif side == "SELL":
            clauses.append("sell_notional > buy_notional AND sell_notional > neutral_notional")
        elif side == "NEUTRAL":
            clauses.append("neutral_notional >= buy_notional AND neutral_notional >= sell_notional")

    sql = (
        f"SELECT * FROM option_flow_daily WHERE {' AND '.join(clauses)} "
        f"ORDER BY total_notional DESC LIMIT ?"
    )
    args.append(limit)

    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]
