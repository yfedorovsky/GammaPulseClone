"""Outcome backfill using REAL ThetaData NBBO for ALL tickers (not SPY*10 proxy).

Replaces scripts/backfill_alert_outcomes.py for analysis purposes.
Uses 1-min OPRA NBBO bars per contract via the ThetaData REST proxy at
http://127.0.0.1:25503 (same source as paired_trades.py).

For each alert computes outcomes from BID-ASK MID, not intrinsic-from-spot:
  - peak_pnl_pct, peak_hhmm, mins_to_peak (MFE on the real option price)
  - eod_pnl_pct (mid at last bar)
  - mins_above_entry, mins_2x_entry (durability)
  - mfe_min1, mfe_min3, mfe_min5, mfe_min10 (time-stop classifier inputs)
  - outcome_category (recomputed)

Writes to a NEW table `zero_dte_alerts_nbbo_outcomes` keyed on alert_id.
This way we don't trample the existing (contaminated) outcome columns —
analysts can join to compare.

Run:
  python scripts/backfill_alert_outcomes_nbbo.py
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALERT_DB = "zero_dte_alerts.db"
THETA = "http://127.0.0.1:25503"


SCHEMA = """
CREATE TABLE IF NOT EXISTS zero_dte_alerts_nbbo_outcomes (
  alert_id TEXT PRIMARY KEY,
  ticker TEXT, fired_at INTEGER, fire_hhmm TEXT,
  strike REAL, right TEXT, expiration TEXT,
  est_entry_price REAL,
  -- entry mid via NBBO (may differ from est_entry_price)
  nbbo_entry_mid REAL,
  nbbo_entry_bid REAL, nbbo_entry_ask REAL,
  -- outcomes from NBBO mid
  peak_mid REAL, peak_hhmm TEXT, mins_to_peak INTEGER,
  peak_pnl_pct REAL,
  eod_mid REAL, eod_pnl_pct REAL,
  mins_above_entry INTEGER, mins_2x_entry INTEGER,
  -- time-stop classifier inputs
  mfe_min1_pct REAL, mfe_min3_pct REAL, mfe_min5_pct REAL,
  mfe_min7_pct REAL, mfe_min10_pct REAL, mfe_min15_pct REAL,
  -- meta
  outcome_category TEXT,
  source TEXT,  -- 'NBBO' or 'NO_DATA'
  computed_at INTEGER
);
"""


def _option_root(ticker: str) -> str:
    return "SPXW" if ticker in ("SPX", "SPXW") else ticker


def _fetch_quote_bars(
    symbol: str, expiration: str, strike: float, right: str, date: str,
) -> pd.DataFrame:
    """Pull 1-min NBBO bars for one contract for one day. Returns ts, hhmm, bid, ask, mid."""
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
        print(f"  [nbbo] quote pull failed: {e}", flush=True)
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df["ts"] = (df["t"].astype("int64") // 10**9).astype(int)
    df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
    if df.empty:
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df[["ts", "hhmm", "bid", "ask", "mid"]].reset_index(drop=True)


def categorize_outcome(peak_pnl: float | None) -> str:
    if peak_pnl is None:
        return "NO_DATA"
    if peak_pnl >= 200:
        return "WIN_BIG"
    if peak_pnl >= 50:
        return "WIN"
    if peak_pnl >= 0:
        return "MARGINAL"
    if peak_pnl >= -50:
        return "LOSS_BOUNCED"
    return "WIPEOUT"


def compute_nbbo_outcome(alert: dict) -> dict:
    fire_ts = int(alert["fired_at"])
    fire_dt = datetime.fromtimestamp(fire_ts)
    fire_hhmm = fire_dt.strftime("%H:%M")
    day = fire_dt.strftime("%Y-%m-%d")
    ticker = alert["ticker"]
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"]) if alert.get("est_entry_price") else None
    right_raw = (alert.get("right") or "").upper()
    right = "C" if right_raw in ("C", "CALL") else "P"
    expiration = alert.get("expiration") or day  # 0DTE assumes same-day expiry

    sym = _option_root(ticker)
    bars = _fetch_quote_bars(sym, expiration, strike, right, day)
    base = {
        "alert_id": alert["alert_id"], "ticker": ticker, "fired_at": fire_ts,
        "fire_hhmm": fire_hhmm, "strike": strike, "right": right,
        "expiration": expiration, "est_entry_price": entry,
    }
    if bars.empty:
        base.update({"source": "NO_DATA", "outcome_category": "NO_DATA"})
        return base

    # Trade window: from fire minute to 16:00
    sub = bars[bars["hhmm"] >= fire_hhmm].reset_index(drop=True)
    if sub.empty:
        base.update({"source": "NO_DATA", "outcome_category": "NO_DATA"})
        return base
    sub["minute_idx"] = range(len(sub))

    # NBBO entry mid at the first bar at-or-after fire time
    entry_row = sub.iloc[0]
    nbbo_entry_mid = float(entry_row["mid"])
    nbbo_entry_bid = float(entry_row["bid"])
    nbbo_entry_ask = float(entry_row["ask"])

    # Use the actual recorded entry price as the cost basis (what we paid)
    # If absent or zero, fall back to NBBO entry mid
    cost = entry if (entry is not None and entry > 0) else nbbo_entry_mid

    # MFE = peak mid AFTER entry, vs cost basis
    peak_idx = sub["mid"].idxmax()
    peak_row = sub.loc[peak_idx]
    peak_mid = float(peak_row["mid"])
    peak_hhmm = peak_row["hhmm"]
    mins_to_peak = int(peak_row["minute_idx"])
    peak_pnl_pct = (peak_mid - cost) / cost * 100 if cost > 0 else None

    eod_row = sub.iloc[-1]
    eod_mid = float(eod_row["mid"])
    eod_pnl_pct = (eod_mid - cost) / cost * 100 if cost > 0 else None

    sub["above_entry"] = (sub["mid"] > cost).astype(int)
    sub["above_2x"] = (sub["mid"] >= cost * 2).astype(int)
    mins_above = int(sub["above_entry"].sum())
    mins_2x = int(sub["above_2x"].sum())

    # MFE-by-minute-N (time-stop classifier inputs)
    def mfe_at(n: int) -> float | None:
        early = sub[sub["minute_idx"] <= n]
        if early.empty:
            return None
        m = float(early["mid"].max())
        return (m - cost) / cost * 100 if cost > 0 else None

    base.update({
        "nbbo_entry_mid": round(nbbo_entry_mid, 3),
        "nbbo_entry_bid": round(nbbo_entry_bid, 3),
        "nbbo_entry_ask": round(nbbo_entry_ask, 3),
        "peak_mid": round(peak_mid, 3),
        "peak_hhmm": peak_hhmm,
        "mins_to_peak": mins_to_peak,
        "peak_pnl_pct": round(peak_pnl_pct, 2) if peak_pnl_pct is not None else None,
        "eod_mid": round(eod_mid, 3),
        "eod_pnl_pct": round(eod_pnl_pct, 2) if eod_pnl_pct is not None else None,
        "mins_above_entry": mins_above, "mins_2x_entry": mins_2x,
        "mfe_min1_pct": round(mfe_at(1), 2) if mfe_at(1) is not None else None,
        "mfe_min3_pct": round(mfe_at(3), 2) if mfe_at(3) is not None else None,
        "mfe_min5_pct": round(mfe_at(5), 2) if mfe_at(5) is not None else None,
        "mfe_min7_pct": round(mfe_at(7), 2) if mfe_at(7) is not None else None,
        "mfe_min10_pct": round(mfe_at(10), 2) if mfe_at(10) is not None else None,
        "mfe_min15_pct": round(mfe_at(15), 2) if mfe_at(15) is not None else None,
        "outcome_category": categorize_outcome(peak_pnl_pct),
        "source": "NBBO",
    })
    return base


def main() -> int:
    conn = sqlite3.connect(ALERT_DB)
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM zero_dte_alerts ORDER BY fired_at"
    ).fetchall()]
    print(f"[nbbo-backfill] processing {len(alerts)} alerts...", flush=True)
    n_done = 0
    n_nodata = 0
    for a in alerts:
        try:
            o = compute_nbbo_outcome(a)
            o["computed_at"] = int(datetime.now().timestamp())
            cols = list(o.keys())
            placeholders = ",".join("?" for _ in cols)
            colnames = ",".join(cols)
            conn.execute(
                f"INSERT OR REPLACE INTO zero_dte_alerts_nbbo_outcomes "
                f"({colnames}) VALUES ({placeholders})",
                [o[c] for c in cols],
            )
            conn.commit()
            n_done += 1
            if o.get("source") == "NO_DATA":
                n_nodata += 1
            fire_dt = datetime.fromtimestamp(a["fired_at"]).strftime("%m-%d %H:%M")
            peak = o.get("peak_pnl_pct")
            peak_str = f"{peak:+.0f}%" if peak is not None else "?"
            cat = o.get("outcome_category", "?")
            print(f"  {fire_dt} {a['ticker']:<5} K={a['strike']:.0f} {a['direction'][:4]:<4} "
                  f"peak={peak_str:<7} cat={cat:<13} src={o.get('source','?')}",
                  flush=True)
        except Exception as e:
            print(f"  ! {a['alert_id']}: {type(e).__name__}: {e}", flush=True)
    print(f"\n[nbbo-backfill] {n_done} processed, {n_nodata} NO_DATA",
          flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
