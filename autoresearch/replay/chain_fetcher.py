"""Historical option-chain cache — THE durable, signal-agnostic dataset.

Fetches ThetaData v3 bulk EOD chains into a local SQLite store so that ANY
future algo can backtest off it with one command. The whale/informed replay is
just the first customer. Design notes (validated empirically 2026-06-09):

  - ``/v3/option/history/greeks/eod?symbol=X&expiration=E&start_date=..&end_date=..``
    (strike/right OMITTED = bulk, ALL contracts) returns OHLC + volume + closing
    bid/ask + delta + implied_vol + underlying_price per contract-day.
  - ``/v3/option/history/open_interest`` (same bulk form) returns OI with a
    ~06:30 ET timestamp — i.e. the row dated D is the MORNING-SETTLED value
    (end of D-1). That is exactly the denominator live V/OI uses, so day-D
    volume / day-D OI-row needs NO extra join.
  - Expirations must be REAL listed dates (``/v3/option/list/expirations``);
    holiday-shifted monthlies (e.g. 2026-06-18 for Juneteenth) are returned
    correctly by the list endpoint — never construct expirations by rule.

Store: ``autoresearch/_artifacts/hist_chains/chains.db`` (gitignored).
  option_eod   one row per (root, expiration, strike, right, date) with
               volume/close/bid/ask/delta/iv/spot/oi. Rows that never traded
               AND carry no OI are dropped (dead strikes; documented).
  fetch_log    idempotency ledger — a (root, exp, endpoint, range) fetched OK
               is never re-fetched; re-runs are instant off cache.

Survivorship-safe: expirations are enumerated from the full listed history
(expired/delisted contracts included — ThetaData retains them).

Throughput: flat sub but rate-limited; a polite throttle + the ledger makes
the YTD first run an overnight job and every later run free. Fetch failures
log + skip, never crash. Read-only against live systems; offline only.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Iterable, Optional

THETA_URL = "http://127.0.0.1:25503"
DEFAULT_DB = (Path(__file__).resolve().parent.parent / "_artifacts"
              / "hist_chains" / "chains.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_eod (
    date       TEXT NOT NULL,   -- YYYY-MM-DD trading day
    root       TEXT NOT NULL,
    expiration TEXT NOT NULL,   -- YYYY-MM-DD as listed
    strike     REAL NOT NULL,
    right      TEXT NOT NULL,   -- 'C' / 'P'
    volume     INTEGER,
    trade_count INTEGER,
    close      REAL,            -- last trade of the day (0 if never traded)
    bid        REAL,            -- closing NBBO
    ask        REAL,
    delta      REAL,
    iv         REAL,
    spot       REAL,            -- underlying price at the EOD greeks snapshot
    oi         INTEGER,         -- MORNING-settled OI (= end of prior day)
    PRIMARY KEY (root, expiration, strike, right, date)
);
CREATE INDEX IF NOT EXISTS idx_eod_root_date ON option_eod(root, date);
CREATE INDEX IF NOT EXISTS idx_eod_date ON option_eod(date);
CREATE TABLE IF NOT EXISTS fetch_log (
    root TEXT, expiration TEXT, endpoint TEXT,
    start_date TEXT, end_date TEXT,
    status TEXT, n_rows INTEGER, fetched_at REAL,
    PRIMARY KEY (root, expiration, endpoint, start_date, end_date)
);
"""


@dataclass
class FetchConfig:
    base_url: str = THETA_URL
    timeout: float = 180.0          # bulk ranges can be slow on big chains.
    throttle_s: float = 0.15        # polite gap between requests.
    # Expiration scope: near-dated covers everything ACTIVE in the window
    # (weeklies/dailies/monthlies); long-dated keeps only monthly-class
    # expirations (day-of-month 14..22 — third-Friday week, holiday-shifted
    # Thursdays included) out to the whale LEAP tenor.
    near_horizon_days: int = 60
    leap_horizon_days: int = 550
    monthly_dom_lo: int = 14
    monthly_dom_hi: int = 22


@dataclass
class FetchStats:
    n_requests: int = 0
    n_cached_skips: int = 0
    n_rows: int = 0
    n_failures: int = 0
    failures: list = field(default_factory=list)


def open_store(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(_SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def _http_csv(url: str, timeout: float) -> Optional[list[dict]]:
    """GET -> CSV rows as dicts; None on failure; [] on no-data."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    if text.startswith("No data"):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def list_expirations(root: str, cfg: FetchConfig) -> list[str]:
    """All LISTED expirations for a root (full history — survivorship-safe)."""
    url = (f"{cfg.base_url}/v3/option/list/expirations?"
           + urllib.parse.urlencode({"symbol": root}))
    rows = _http_csv(url, cfg.timeout)
    return [r["expiration"].strip('"') for r in rows or [] if r.get("expiration")]


def scope_expirations(expirations: Iterable[str], start: str, end: str,
                      cfg: FetchConfig) -> list[str]:
    """The tenors the signatures target, for a fetch window [start, end]:
    every expiration alive and near-dated during the window, plus
    monthly-class expirations out to LEAP tenor (whale territory)."""
    out = []
    d_start = _date.fromisoformat(start)
    d_end = _date.fromisoformat(end)
    for e in expirations:
        try:
            d = _date.fromisoformat(e)
        except ValueError:
            continue
        if d < d_start:           # expired before the window — no overlap.
            continue
        days_past_end = (d - d_end).days
        if days_past_end <= cfg.near_horizon_days:
            out.append(e)
        elif (days_past_end <= cfg.leap_horizon_days
              and cfg.monthly_dom_lo <= d.day <= cfg.monthly_dom_hi):
            out.append(e)
    return sorted(out)


def _f(row: dict, key: str) -> Optional[float]:
    try:
        v = row.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _fetch_one(con: sqlite3.Connection, root: str, exp: str, endpoint: str,
               start: str, end: str, cfg: FetchConfig,
               stats: FetchStats) -> None:
    """Fetch one (root, exp, endpoint, range) if not already in the ledger."""
    key = (root, exp, endpoint, start, end)
    done = con.execute(
        "SELECT status FROM fetch_log WHERE root=? AND expiration=? AND "
        "endpoint=? AND start_date=? AND end_date=?", key).fetchone()
    if done is not None and done["status"] == "OK":
        stats.n_cached_skips += 1
        return

    path = {"greeks": "/v3/option/history/greeks/eod",
            "oi": "/v3/option/history/open_interest"}[endpoint]
    url = (f"{cfg.base_url}{path}?" + urllib.parse.urlencode({
        "symbol": root, "expiration": exp,
        "start_date": start, "end_date": end}))
    time.sleep(cfg.throttle_s)
    rows = _http_csv(url, cfg.timeout)
    stats.n_requests += 1
    if rows is None:
        stats.n_failures += 1
        stats.failures.append(key)
        con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?,?,?)",
                    key + ("FAIL", 0, time.time()))
        con.commit()
        return

    n = 0
    if endpoint == "greeks":
        for r in rows:
            day = (r.get("timestamp") or "")[:10]
            strike, right = _f(r, "strike"), (r.get("right") or "")[:1].upper()
            if not day or strike is None or right not in ("C", "P"):
                continue
            vol = int(_f(r, "volume") or 0)
            # Dead strikes (never traded, and OI pass will skip oi=0) are
            # dropped at the OI step; here keep volume>0 OR quoted rows so the
            # cache stays lean but chain-structure queries still work.
            con.execute(
                "INSERT INTO option_eod (date, root, expiration, strike, right,"
                " volume, trade_count, close, bid, ask, delta, iv, spot)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(root, expiration, strike, right, date) DO UPDATE SET"
                " volume=excluded.volume, trade_count=excluded.trade_count,"
                " close=excluded.close, bid=excluded.bid, ask=excluded.ask,"
                " delta=excluded.delta, iv=excluded.iv, spot=excluded.spot",
                (day, root, exp, strike, right, vol, int(_f(r, "count") or 0),
                 _f(r, "close"), _f(r, "bid"), _f(r, "ask"), _f(r, "delta"),
                 _f(r, "implied_vol"), _f(r, "underlying_price")))
            n += 1
    else:  # oi
        for r in rows:
            day = (r.get("timestamp") or "")[:10]
            strike, right = _f(r, "strike"), (r.get("right") or "")[:1].upper()
            oi = int(_f(r, "open_interest") or 0)
            if not day or strike is None or right not in ("C", "P"):
                continue
            cur = con.execute(
                "UPDATE option_eod SET oi=? WHERE root=? AND expiration=? AND"
                " strike=? AND right=? AND date=?",
                (oi, root, exp, strike, right, day))
            if cur.rowcount == 0 and oi > 0:
                con.execute(
                    "INSERT OR IGNORE INTO option_eod (date, root, expiration,"
                    " strike, right, volume, oi) VALUES (?,?,?,?,?,0,?)",
                    (day, root, exp, strike, right, oi))
            n += 1
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?,?,?)",
                key + ("OK", n, time.time()))
    con.commit()
    stats.n_rows += n


def fetch_root(con: sqlite3.Connection, root: str, start: str, end: str,
               cfg: Optional[FetchConfig] = None,
               stats: Optional[FetchStats] = None,
               expirations: Optional[list[str]] = None) -> FetchStats:
    """Fetch one root's scoped chain history into the store (idempotent)."""
    cfg = cfg or FetchConfig()
    stats = stats if stats is not None else FetchStats()
    exps = expirations if expirations is not None else scope_expirations(
        list_expirations(root, cfg), start, end, cfg)
    for exp in exps:
        for endpoint in ("greeks", "oi"):
            _fetch_one(con, root, exp, endpoint, start, end, cfg, stats)
    return stats


def prune_dead_rows(con: sqlite3.Connection) -> int:
    """Drop rows with no volume AND no OI (dead strikes) — keeps the asset lean."""
    cur = con.execute(
        "DELETE FROM option_eod WHERE COALESCE(volume,0)=0 AND COALESCE(oi,0)=0")
    con.commit()
    return cur.rowcount


def trading_days(con: sqlite3.Connection, start: str, end: str) -> list[str]:
    """Trading days derivable from the cache itself (no calendar dependency)."""
    return [r["date"] for r in con.execute(
        "SELECT DISTINCT date FROM option_eod WHERE date >= ? AND date <= ? "
        "ORDER BY date", (start, end))]


__all__ = [
    "DEFAULT_DB", "FetchConfig", "FetchStats", "open_store", "fetch_root",
    "list_expirations", "scope_expirations", "prune_dead_rows", "trading_days",
]
