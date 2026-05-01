"""Paired-trade tracker for the structural-turn falsification experiment.

For each qualified fire from structural_turns.db, compute two paper trades
on the same day:

  1. GATED trade — enter at the fire-time NBBO ask; exit at -30% stop or
     end-of-session (15:59 ET) bid. Same option contract the alert specified
     (ticker, strike, right, expiration).

  2. NAIVE_OPEN_ATM trade — enter at 09:30 ET on the same day; same direction
     (call/put); ATM strike at 09:30 spot rounded per ticker convention
     (SPX/SPXW = $5, others = $1); same expiration (0DTE = same day);
     exit at -30% stop or end-of-session bid.

Both run through the same entry-pays-ask / exit-hits-bid mechanic and the
same -30% / EOD exit rule.

This is the falsification experiment from Perplexity's Q11 protocol
(Apr 30 2026): the gated entry's only privileged input is the gate's
timing (entry time + strike pick). If gate-fire-timing carries genuine
alpha over a fixed-time entry on the same day, gated will systematically
beat naive_open_atm. If it doesn't, the gates are noise.

Stored in a SEPARATE database (`paired_trades.db`) so the falsification
state is auditable and isolated from production tables.

Schema:
  paired_trades(
    id, fire_id, source ('gated' or 'naive_open_atm'),
    ticker, day, direction,
    entry_hhmm, entry_strike, entry_right, entry_expiration,
    entry_ask, entry_bid,
    exit_hhmm, exit_reason, exit_bid, pnl_pct,
    regime_at_fire, vix1d_prior_close, vix9d_prior_close,
    computed_at
  )

Run as an EOD job:
  python -m server.paired_trades --date 2026-04-30
"""
from __future__ import annotations

import argparse
import io
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

THETA = "http://127.0.0.1:25503"
STRUCTURAL_TURN_DB = str(ROOT / "structural_turns.db")
SNAPSHOTS_DB = str(ROOT / "snapshots.db")
PAIRED_DB = str(ROOT / "paired_trades.db")

# Exit rule (frozen for the experiment per Apr 30 protocol)
STOP_PCT = -30.0
SESSION_END_HHMM = "15:59"
SESSION_OPEN_HHMM = "09:30"

# Random-minute-ATM control (Perplexity Apr 30 follow-up #2):
# For each gated fire, also simulate K random-minute same-direction
# ATM-at-that-minute entries on the same day. Mean P&L is the primary
# control because it isolates timing alpha (holds direction + strike-rule
# + exit constant; varies entry minute only).
RANDOM_MINUTE_K = 5                  # samples per fire
RANDOM_MINUTE_RANGE_HHMM = ("09:30", "15:30")  # never sample past 15:30


def _hhmm_to_min(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _min_to_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _sample_non_fire_minutes(
    day: str, exclude_hhmm: set[str], k: int, seed: int,
) -> list[str]:
    """Sample k minutes uniformly from RANDOM_MINUTE_RANGE_HHMM excluding
    any minute in `exclude_hhmm`. Deterministic via fire-derived seed.
    """
    import random
    rng = random.Random(seed)
    lo = _hhmm_to_min(RANDOM_MINUTE_RANGE_HHMM[0])
    hi = _hhmm_to_min(RANDOM_MINUTE_RANGE_HHMM[1])
    universe = [m for m in range(lo, hi)
                if _min_to_hhmm(m) not in exclude_hhmm]
    if len(universe) < k:
        return [_min_to_hhmm(m) for m in universe]
    return [_min_to_hhmm(m) for m in rng.sample(universe, k)]


PAIRED_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS paired_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fire_id TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('gated', 'random_minute_atm', 'naive_open_atm')),
  ticker TEXT NOT NULL,
  day TEXT NOT NULL,
  direction TEXT NOT NULL,
  entry_ts INTEGER,
  entry_hhmm TEXT,
  entry_spot REAL,
  entry_strike REAL,
  entry_right TEXT,
  entry_expiration TEXT,
  entry_ask REAL,
  entry_bid REAL,
  exit_ts INTEGER,
  exit_hhmm TEXT,
  exit_reason TEXT,
  exit_bid REAL,
  pnl_pct REAL,
  regime_at_fire TEXT,
  vix1d_prior_close REAL,
  vix9d_prior_close REAL,
  computed_at INTEGER NOT NULL,
  UNIQUE(fire_id, source)
);
CREATE INDEX IF NOT EXISTS idx_paired_day ON paired_trades(day);
CREATE INDEX IF NOT EXISTS idx_paired_fire ON paired_trades(fire_id);
CREATE INDEX IF NOT EXISTS idx_paired_source ON paired_trades(source);
"""


# ── Option contract helpers ──────────────────────────────────────


def _option_root(ticker: str) -> str:
    return "SPXW" if ticker == "SPX" else ticker


def _strike_round(ticker: str, spot: float) -> float:
    """SPX/SPXW use $5 strikes, others use $1."""
    if ticker == "SPX":
        return float(round(spot / 5) * 5)
    return float(round(spot))


def _right_for_direction(direction: str) -> str:
    return "C" if direction.upper() == "BULLISH" else "P"


# ── ThetaData NBBO bar pull ──────────────────────────────────────


def _fetch_quote_bars(
    symbol: str, expiration: str, strike: float, right: str, date: str,
) -> pd.DataFrame:
    """Pull 1-min NBBO bars for one contract for one day."""
    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": f"{strike:.3f}", "right": right,
        "start_date": date, "end_date": date, "interval": "1m",
    }
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote",
                         params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"  [paired] quote pull failed: {e}", flush=True)
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df["ts"] = (df["t"].astype("int64") // 10**9).astype(int)
    df = df[(df["bid"] > 0) | (df["ask"] > 0)].copy()
    return df[["ts", "hhmm", "bid", "ask"]]


# ── Spot-at-time lookup (snapshots fallback to ThetaData index) ──


def _get_spot_at(ticker: str, date_str: str, hhmm: str) -> float | None:
    """Pull underlying spot at given time-of-day from snapshots.db.

    Looks for a snapshot in the next 10 minutes after target. If absent,
    returns None — caller should skip.
    """
    h, m = map(int, hhmm.split(":"))
    target = datetime.fromisoformat(date_str).replace(hour=h, minute=m)
    ts = int(target.timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB)
    try:
        cur = conn.execute(
            "SELECT spot FROM snapshots WHERE ticker=? AND ts BETWEEN ? AND ? "
            "ORDER BY ts LIMIT 1",
            (ticker, ts, ts + 600),
        )
        row = cur.fetchone()
        return float(row[0]) if row and row[0] else None
    finally:
        conn.close()


# ── VIX context (ex-ante regime features) ───────────────────────


def _vix_prior_close(date_str: str) -> tuple[float | None, float | None]:
    """Return (VIX1D, VIX9D) close from the most recent prior trading day.

    Best-effort — any failure returns (None, None) and the trade still
    persists with NULLs in the VIX columns.
    """
    def _fetch(symbol: str) -> float | None:
        try:
            r = requests.get(
                f"{THETA}/v3/index/history/eod",
                params={"symbol": symbol,
                        "start_date": date_str.replace("-", "")[:8],
                        "end_date": date_str},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            df = pd.read_csv(io.StringIO(r.text))
            if df.empty:
                return None
            df["d"] = pd.to_datetime(df["last_trade"]).dt.strftime("%Y-%m-%d")
            prior = df[df["d"] < date_str].sort_values("d")
            if prior.empty:
                return None
            return float(prior.iloc[-1]["close"])
        except Exception:
            return None
    # Pull a wide window so prior-day exists
    from datetime import timedelta
    start = (datetime.fromisoformat(date_str)
             - timedelta(days=10)).strftime("%Y-%m-%d")
    def _fetch_window(symbol: str) -> float | None:
        try:
            r = requests.get(
                f"{THETA}/v3/index/history/eod",
                params={"symbol": symbol,
                        "start_date": start, "end_date": date_str},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            df = pd.read_csv(io.StringIO(r.text))
            if df.empty:
                return None
            df["d"] = pd.to_datetime(df["last_trade"]).dt.strftime("%Y-%m-%d")
            prior = df[df["d"] < date_str].sort_values("d")
            if prior.empty:
                return None
            return float(prior.iloc[-1]["close"])
        except Exception:
            return None
    return _fetch_window("VIX1D"), _fetch_window("VIX9D")


# ── Trade simulation (entry + walk + exit) ──────────────────────


@dataclass
class TradeResult:
    entry_ts: int | None
    entry_hhmm: str | None
    entry_ask: float | None
    entry_bid: float | None
    exit_ts: int | None
    exit_hhmm: str | None
    exit_bid: float | None
    exit_reason: str | None
    pnl_pct: float | None


def _simulate_trade(
    bars: pd.DataFrame, entry_hhmm: str,
    stop_pct: float = STOP_PCT,
    session_end_hhmm: str = SESSION_END_HHMM,
) -> TradeResult:
    """Walk bars from entry forward, applying -stop_pct or EOD exit.

    Entry: first bar at or after entry_hhmm (pay ask).
    Each later bar: compute mid_pct vs entry_ask. If mid_pct <= stop_pct,
    exit at that bar's bid.
    Otherwise at the last bar with hhmm <= session_end_hhmm: exit at bid.
    """
    if bars.empty:
        return TradeResult(*([None] * 9))
    entry_sub = bars[bars["hhmm"] >= entry_hhmm]
    if entry_sub.empty:
        return TradeResult(*([None] * 9))
    entry_row = entry_sub.iloc[0]
    entry_ask = float(entry_row["ask"])
    entry_bid = float(entry_row["bid"])
    entry_ts = int(entry_row["ts"])
    entry_t = entry_row["hhmm"]
    if entry_ask <= 0:
        return TradeResult(entry_ts, entry_t, entry_ask, entry_bid,
                           None, None, None, "no_entry_ask", None)

    last_bar = None
    for _, b in entry_sub.iterrows():
        if b["hhmm"] > session_end_hhmm:
            break
        last_bar = b
        mid = (float(b["bid"]) + float(b["ask"])) / 2
        mid_pct = (mid - entry_ask) / entry_ask * 100
        if mid_pct <= stop_pct:
            bid = float(b["bid"])
            exit_pnl = (bid - entry_ask) / entry_ask * 100
            return TradeResult(
                entry_ts, entry_t, entry_ask, entry_bid,
                int(b["ts"]), b["hhmm"], bid, "stop", exit_pnl,
            )

    if last_bar is None:
        return TradeResult(entry_ts, entry_t, entry_ask, entry_bid,
                           None, None, None, "no_session_bars", None)
    bid = float(last_bar["bid"])
    exit_pnl = (bid - entry_ask) / entry_ask * 100
    return TradeResult(
        entry_ts, entry_t, entry_ask, entry_bid,
        int(last_bar["ts"]), last_bar["hhmm"], bid, "eod", exit_pnl,
    )


# ── Per-fire orchestration ──────────────────────────────────────


def _compute_random_minute_atm_baseline(
    ticker: str, day: str, direction: str, expiration: str,
    fire_id: str, exclude_hhmm: set[str],
) -> dict:
    """For one gated fire, sample K random non-fire minutes, simulate each
    as a same-direction ATM-at-that-minute entry with -30%/EOD exit, and
    return ONE row holding the mean P&L of the K samples.

    Per-sample audit info captured in `entry_hhmm` as a comma-joined list
    of minutes; per-sample P&Ls aren't persisted individually (the paired
    bootstrap pairs by fire_id and the mean is the relevant statistic).
    """
    sym = _option_root(ticker)
    right = _right_for_direction(direction)
    seed = abs(hash(fire_id)) & 0xFFFFFFFF
    sampled = _sample_non_fire_minutes(
        day, exclude_hhmm, RANDOM_MINUTE_K, seed,
    )
    pnls: list[float] = []
    sampled_used: list[str] = []
    for hhmm in sampled:
        spot = _get_spot_at(ticker, day, hhmm)
        if spot is None:
            continue
        strike = _strike_round(ticker, spot)
        bars = _fetch_quote_bars(sym, expiration, strike, right, day)
        if bars.empty:
            continue
        result = _simulate_trade(bars, hhmm)
        if result.pnl_pct is None:
            continue
        pnls.append(result.pnl_pct)
        sampled_used.append(hhmm)

    if not pnls:
        return {
            "fire_id": fire_id, "source": "random_minute_atm",
            "ticker": ticker, "day": day, "direction": direction,
            "entry_ts": None, "entry_hhmm": "",
            "entry_spot": None, "entry_strike": None,
            "entry_right": right, "entry_expiration": expiration,
            "entry_ask": None, "entry_bid": None,
            "exit_ts": None, "exit_hhmm": None,
            "exit_reason": "no_samples", "exit_bid": None, "pnl_pct": None,
        }

    mean_pnl = sum(pnls) / len(pnls)
    return {
        "fire_id": fire_id, "source": "random_minute_atm",
        "ticker": ticker, "day": day, "direction": direction,
        "entry_ts": None,
        "entry_hhmm": ",".join(sampled_used),  # audit: which minutes used
        "entry_spot": None, "entry_strike": None,  # multiple strikes — N/A
        "entry_right": right, "entry_expiration": expiration,
        "entry_ask": None, "entry_bid": None,
        "exit_ts": None, "exit_hhmm": None,
        "exit_reason": f"mean_of_{len(pnls)}_samples",
        "exit_bid": None, "pnl_pct": mean_pnl,
    }


def compute_paired_trades_for_fire(
    fire: dict, all_fire_minutes_today: set[str] | None = None,
) -> list[dict]:
    """Given one qualified fire row, compute and return three rows: gated,
    random_minute_atm (primary control), naive_open_atm (secondary control).

    `all_fire_minutes_today` is the set of HH:MM strings for every fire
    that occurred on this day across all tickers; used to exclude those
    minutes from the random-minute baseline sampling. If None, only the
    current fire's minute is excluded.

    Any row may be None-result (insufficient data); we still persist with
    NULLs so the experiment has a complete audit trail.
    """
    ticker = fire["ticker"]
    day = fire["day"]            # YYYY-MM-DD
    direction = fire["direction"]
    fire_hhmm = fire["fire_hhmm"]
    fire_ts = int(fire["ts"])
    regime = fire.get("regime")
    spot_at_fire = float(fire.get("spot") or 0)

    sym = _option_root(ticker)
    right = _right_for_direction(direction)

    # Gated entry uses the spot/strike already chosen by the live worker.
    # We re-derive from spot to avoid the script needing a separate join
    # to opt_strike (which is alert-side, not detector-side).
    gated_strike = _strike_round(ticker, spot_at_fire)

    # Naive entry: 09:30 ATM on same day, same direction. Strike from
    # 09:30 spot, not from fire-time spot.
    open_spot = _get_spot_at(ticker, day, SESSION_OPEN_HHMM)
    naive_strike = _strike_round(ticker, open_spot) if open_spot else None

    # 0DTE = expiration is the same day
    expiration = day

    # Pull bars for both contracts (cache via the same call signature)
    gated_bars = _fetch_quote_bars(sym, expiration, gated_strike, right, day)
    naive_bars = (_fetch_quote_bars(sym, expiration, naive_strike, right, day)
                  if naive_strike else pd.DataFrame())

    gated = _simulate_trade(gated_bars, fire_hhmm)
    naive = _simulate_trade(naive_bars, SESSION_OPEN_HHMM) if naive_strike else None

    v1, v9 = _vix_prior_close(day)
    fire_id = f"{day}_{ticker}_{fire_hhmm}_{direction}"
    now = int(time.time())

    # Random-minute-ATM baseline (PRIMARY control per Perplexity Apr 30 #2):
    # exclude all fire minutes for the day so we don't accidentally sample
    # one as a "non-fire" minute.
    exclude = set(all_fire_minutes_today) if all_fire_minutes_today else {fire_hhmm}
    exclude.add(fire_hhmm)
    rmin_row = _compute_random_minute_atm_baseline(
        ticker, day, direction, expiration, fire_id, exclude,
    )

    rows = []

    rows.append({
        "fire_id": fire_id, "source": "gated",
        "ticker": ticker, "day": day, "direction": direction,
        "entry_ts": gated.entry_ts, "entry_hhmm": gated.entry_hhmm,
        "entry_spot": spot_at_fire,
        "entry_strike": gated_strike, "entry_right": right,
        "entry_expiration": expiration,
        "entry_ask": gated.entry_ask, "entry_bid": gated.entry_bid,
        "exit_ts": gated.exit_ts, "exit_hhmm": gated.exit_hhmm,
        "exit_reason": gated.exit_reason, "exit_bid": gated.exit_bid,
        "pnl_pct": gated.pnl_pct,
        "regime_at_fire": regime,
        "vix1d_prior_close": v1, "vix9d_prior_close": v9,
        "computed_at": now,
    })

    # Append random_minute_atm row with the common context fields filled in
    rmin_row["regime_at_fire"] = regime
    rmin_row["vix1d_prior_close"] = v1
    rmin_row["vix9d_prior_close"] = v9
    rmin_row["computed_at"] = now
    rows.append(rmin_row)

    if naive is not None:
        rows.append({
            "fire_id": fire_id, "source": "naive_open_atm",
            "ticker": ticker, "day": day, "direction": direction,
            "entry_ts": naive.entry_ts, "entry_hhmm": naive.entry_hhmm,
            "entry_spot": open_spot,
            "entry_strike": naive_strike, "entry_right": right,
            "entry_expiration": expiration,
            "entry_ask": naive.entry_ask, "entry_bid": naive.entry_bid,
            "exit_ts": naive.exit_ts, "exit_hhmm": naive.exit_hhmm,
            "exit_reason": naive.exit_reason, "exit_bid": naive.exit_bid,
            "pnl_pct": naive.pnl_pct,
            "regime_at_fire": regime,
            "vix1d_prior_close": v1, "vix9d_prior_close": v9,
            "computed_at": now,
        })
    else:
        # Persist a stub so the audit trail is complete
        rows.append({
            "fire_id": fire_id, "source": "naive_open_atm",
            "ticker": ticker, "day": day, "direction": direction,
            "entry_ts": None, "entry_hhmm": SESSION_OPEN_HHMM,
            "entry_spot": None,
            "entry_strike": None, "entry_right": right,
            "entry_expiration": expiration,
            "entry_ask": None, "entry_bid": None,
            "exit_ts": None, "exit_hhmm": None,
            "exit_reason": "no_open_spot", "exit_bid": None,
            "pnl_pct": None,
            "regime_at_fire": regime,
            "vix1d_prior_close": v1, "vix9d_prior_close": v9,
            "computed_at": now,
        })
    return rows


# ── DB ops ──────────────────────────────────────────────────────


def _ensure_db(path: str = PAIRED_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(PAIRED_TRADES_SCHEMA)
    return conn


def persist_paired_rows(rows: list[dict], path: str = PAIRED_DB) -> int:
    if not rows:
        return 0
    conn = _ensure_db(path)
    try:
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO paired_trades
                     (fire_id, source, ticker, day, direction,
                      entry_ts, entry_hhmm, entry_spot,
                      entry_strike, entry_right, entry_expiration,
                      entry_ask, entry_bid,
                      exit_ts, exit_hhmm, exit_reason, exit_bid, pnl_pct,
                      regime_at_fire, vix1d_prior_close, vix9d_prior_close,
                      computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?)""",
                (r["fire_id"], r["source"], r["ticker"], r["day"], r["direction"],
                 r["entry_ts"], r["entry_hhmm"], r["entry_spot"],
                 r["entry_strike"], r["entry_right"], r["entry_expiration"],
                 r["entry_ask"], r["entry_bid"],
                 r["exit_ts"], r["exit_hhmm"], r["exit_reason"], r["exit_bid"],
                 r["pnl_pct"], r["regime_at_fire"],
                 r["vix1d_prior_close"], r["vix9d_prior_close"],
                 r["computed_at"]),
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def fetch_qualified_fires_for_day(day: str) -> list[dict]:
    """Pull qualified fires from structural_turns.db for a given day."""
    conn = sqlite3.connect(STRUCTURAL_TURN_DB)
    conn.row_factory = sqlite3.Row
    try:
        d = datetime.fromisoformat(day)
        t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
        t1 = int(d.replace(hour=23, minute=59, second=59).timestamp())
        cur = conn.execute(
            """SELECT ts, ticker, direction, spot, regime, tier
               FROM structural_turns
               WHERE qualified = 1 AND ts BETWEEN ? AND ?
               ORDER BY ts""",
            (t0, t1),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "ts": r["ts"], "ticker": r["ticker"],
            "direction": r["direction"], "spot": r["spot"],
            "regime": r["regime"], "tier": r["tier"],
            "day": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d"),
            "fire_hhmm": datetime.fromtimestamp(r["ts"]).strftime("%H:%M"),
        }
        for r in rows
    ]


def fetch_qualified_fires_from_csv(
    csv_path: str, day: str | None = None,
) -> list[dict]:
    """Backtest path: read fires from the structural_turn_30d_fires.csv that
    the backtest harness writes (docs/research/structural_turn_30d_fires.csv).
    Used to bootstrap paired_trades.db from the existing 27-fire sample for
    smoke-testing this module before the live worker repopulates the DB.
    """
    df = pd.read_csv(csv_path)
    if day is not None:
        df = df[df["day"] == day]
    out = []
    for _, r in df.iterrows():
        out.append({
            "ts": int(r["ts"]),
            "ticker": r["ticker"],
            "direction": r["direction"],
            "spot": float(r["spot"]),
            "regime": r.get("regime"),
            "tier": r.get("tier"),
            "day": r["day"],
            "fire_hhmm": r["time"],
        })
    return out


def run_eod(date_str: str, csv_path: str | None = None) -> int:
    if csv_path:
        fires = fetch_qualified_fires_from_csv(csv_path, day=date_str)
        source_label = f"CSV {csv_path}"
    else:
        fires = fetch_qualified_fires_for_day(date_str)
        source_label = "structural_turns.db"
    print(f"[paired] {date_str} ({source_label}): {len(fires)} qualified fires",
          flush=True)
    if not fires:
        return 0
    # Pre-compute the set of all fire HH:MM on this day so the random-minute
    # baseline can exclude them.
    all_fire_minutes = {f["fire_hhmm"] for f in fires}
    total = 0
    for f in fires:
        try:
            rows = compute_paired_trades_for_fire(
                f, all_fire_minutes_today=all_fire_minutes,
            )
            n = persist_paired_rows(rows)
            total += n
            gated = next((r for r in rows if r["source"] == "gated"), None)
            rmin = next((r for r in rows if r["source"] == "random_minute_atm"), None)
            naive = next((r for r in rows if r["source"] == "naive_open_atm"), None)
            g_pnl = (gated or {}).get("pnl_pct")
            r_pnl = (rmin or {}).get("pnl_pct")
            n_pnl = (naive or {}).get("pnl_pct")
            print(f"  {f['fire_hhmm']} {f['ticker']} {f['direction']} "
                  f"tier={f['tier']}  gated={g_pnl}  rmin={r_pnl}  naive={n_pnl}",
                  flush=True)
        except Exception as e:
            print(f"  ! fire {f['ticker']}@{f['fire_hhmm']}: {type(e).__name__}: {e}",
                  flush=True)
    print(f"[paired] {date_str}: persisted {total} rows", flush=True)
    return total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--csv", default=None,
                   help="Optional: read fires from CSV instead of "
                   "structural_turns.db (e.g., the backtest output at "
                   "docs/research/structural_turn_30d_fires.csv)")
    args = p.parse_args()
    return 0 if run_eod(args.date, csv_path=args.csv) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
