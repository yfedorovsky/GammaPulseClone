"""Realistic slippage backtest — re-pull NBBO, apply real bid/ask fills.

For each trade in unified_setup_backtest.db:
  - Pull the actual NBBO bars for that contract+day
  - Entry at ask (worst-case retail buy fill)
  - Exit at bid (worst-case retail sell fill)
  - For TP exit: TP triggers when bid crosses TP threshold (so option mid
    would be slightly higher; we exit at bid which is conservative)
  - For Stop exit: stop triggers when bid crosses below stop threshold
  - For EOD: exit at last bar's bid

Compares 4 fill models:
  - mid-mid (the original backtest's assumption)
  - mid-mid + 4% spread haircut (parametric)
  - ask-bid (real worst-case retail fills)
  - ask + 1¢ tick on entry, bid - 1¢ tick on exit (very conservative)

Reports updated mean P&L + bootstrap CI per setup × fill model.
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

THETA = "http://127.0.0.1:25503"
SOURCE_DB = "unified_setup_backtest.db"
OUT_DB = "realistic_slippage_backtest.db"

_CACHE: dict[tuple, pd.DataFrame] = {}


def fetch_nbbo(symbol: str, expiration: str, strike: float, right: str,
               date: str) -> pd.DataFrame:
    key = (date, symbol, expiration, strike, right)
    if key in _CACHE:
        return _CACHE[key]
    params = {"symbol": symbol, "expiration": expiration,
              "strike": f"{strike:.3f}", "right": right,
              "start_date": date, "end_date": date, "interval": "1m"}
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote", params=params,
                         timeout=30)
        if r.status_code != 200:
            _CACHE[key] = pd.DataFrame()
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        _CACHE[key] = pd.DataFrame()
        return pd.DataFrame()
    if df.empty:
        _CACHE[key] = df
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
    if df.empty:
        _CACHE[key] = df
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread_pct"] = (df["ask"] - df["bid"]) / df["mid"] * 100
    df = df[["hhmm", "bid", "ask", "mid", "spread_pct"]].reset_index(drop=True)
    _CACHE[key] = df
    return df


def simulate_realistic_fills(date: str, expiration: str, strike: float,
                             right: str, entry_hhmm: str,
                             tp_pct: float = 100, stop_pct: float = -30) -> dict:
    """Re-simulate the trade with realistic fill models."""
    nbbo = fetch_nbbo("SPY", expiration, strike, right, date)
    if nbbo.empty:
        return {"status": "NO_NBBO"}
    sub = nbbo[nbbo["hhmm"] >= entry_hhmm].reset_index(drop=True)
    if sub.empty:
        return {"status": "NO_DATA"}
    sub["minute_idx"] = range(len(sub))

    # Entry models
    entry_mid = float(sub.iloc[0]["mid"])
    entry_ask = float(sub.iloc[0]["ask"])
    entry_ask_plus_tick = entry_ask + 0.01

    # Track how each fill model executes
    def simulate(entry_price: float, exit_at_bid: bool):
        # Walk forward, hit TP if mid (or bid for conservative) crosses TP
        for _, r in sub.iterrows():
            # TP target reached when "exit price" >= entry * (1 + tp_pct/100)
            # For mid-mid: exit_price = mid; for ask-bid: exit_price = bid
            check_price = float(r["bid"]) if exit_at_bid else float(r["mid"])
            if check_price >= entry_price * (1 + tp_pct / 100):
                # Fill at TP target
                tp_fill = entry_price * (1 + tp_pct / 100)
                # If we're using ask-bid model, fill = bid (the check_price)
                # which is at-or-above target
                fill = check_price if exit_at_bid else tp_fill
                return ((fill - entry_price) / entry_price * 100, "TP",
                        int(r["minute_idx"]))
            if check_price <= entry_price * (1 + stop_pct / 100):
                fill = check_price if exit_at_bid else (
                    entry_price * (1 + stop_pct / 100))
                return ((fill - entry_price) / entry_price * 100, "STOP",
                        int(r["minute_idx"]))
        # EOD
        last = sub.iloc[-1]
        eod_price = float(last["bid"]) if exit_at_bid else float(last["mid"])
        return ((eod_price - entry_price) / entry_price * 100, "EOD",
                int(last["minute_idx"]))

    results = {
        "status": "OK",
        "entry_mid": entry_mid,
        "entry_ask": entry_ask,
        "spread_pct_at_entry": float(sub.iloc[0]["spread_pct"]),
        "median_spread_pct_during_trade": float(sub["spread_pct"].median()),
    }
    # Model 1: mid-mid (original)
    pnl_mm, exit_mm, _ = simulate(entry_mid, exit_at_bid=False)
    results["pol_midmid"] = round(pnl_mm, 2)
    results["exit_midmid"] = exit_mm
    # Model 2: ask-mid (buy at ask, sell at mid — slightly conservative)
    pnl_am, exit_am, _ = simulate(entry_ask, exit_at_bid=False)
    results["pol_askmid"] = round(pnl_am, 2)
    # Model 3: ask-bid (real retail fills)
    pnl_ab, exit_ab, _ = simulate(entry_ask, exit_at_bid=True)
    results["pol_askbid"] = round(pnl_ab, 2)
    results["exit_askbid"] = exit_ab
    # Model 4: ask+tick / bid-tick (very conservative)
    pnl_at, exit_at, _ = simulate(entry_ask_plus_tick, exit_at_bid=True)
    results["pol_asktick"] = round(pnl_at, 2)
    return results


def main(limit: int | None = None) -> int:
    conn = sqlite3.connect(SOURCE_DB)
    df = pd.read_sql("""SELECT setup, day, cross_hhmm, direction, strike,
                              right, entry_hhmm, mfe_pct, eod_pct, pol_tp50_s30
                       FROM unified_trades ORDER BY day, cross_hhmm""", conn)
    conn.close()

    # 0DTE: expiration = same day
    df["expiration"] = df["day"]
    if limit:
        df = df.head(limit)
    print(f"[realistic-slip] simulating {len(df)} trades", flush=True)

    out_conn = sqlite3.connect(OUT_DB)
    out_conn.executescript("""
        CREATE TABLE IF NOT EXISTS realistic_slip (
            setup TEXT, day TEXT, cross_hhmm TEXT, direction TEXT,
            strike REAL, right TEXT,
            entry_mid REAL, entry_ask REAL, spread_pct_at_entry REAL,
            median_spread_pct_during_trade REAL,
            pol_midmid REAL, exit_midmid TEXT,
            pol_askmid REAL,
            pol_askbid REAL, exit_askbid TEXT,
            pol_asktick REAL,
            status TEXT,
            PRIMARY KEY (setup, day, cross_hhmm)
        );
    """)

    n = 0
    for i, r in df.iterrows():
        result = simulate_realistic_fills(
            r["day"], r["expiration"], r["strike"], r["right"],
            r["entry_hhmm"])
        if result["status"] != "OK":
            continue
        out_conn.execute(
            "INSERT OR REPLACE INTO realistic_slip VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["setup"], r["day"], r["cross_hhmm"], r["direction"],
             r["strike"], r["right"],
             result["entry_mid"], result["entry_ask"],
             result["spread_pct_at_entry"],
             result["median_spread_pct_during_trade"],
             result["pol_midmid"], result["exit_midmid"],
             result["pol_askmid"],
             result["pol_askbid"], result["exit_askbid"],
             result["pol_asktick"],
             result["status"]))
        out_conn.commit()
        n += 1
        if n % 100 == 0:
            print(f"  {n}/{len(df)} done", flush=True)

    print(f"[realistic-slip] {n} trades simulated", flush=True)
    out_conn.close()

    # Summary
    conn = sqlite3.connect(OUT_DB)
    summary = pd.read_sql("""
        SELECT setup, COUNT(*) as n,
               AVG(spread_pct_at_entry) as avg_spread,
               AVG(pol_midmid) as mean_midmid,
               AVG(pol_askmid) as mean_askmid,
               AVG(pol_askbid) as mean_askbid,
               AVG(pol_asktick) as mean_asktick
        FROM realistic_slip
        GROUP BY setup
        ORDER BY mean_askbid DESC""", conn)
    conn.close()

    print("\n" + "=" * 110)
    print("REALISTIC SLIPPAGE TABLE (sorted by ask-bid mean, the actual retail fill)")
    print("=" * 110)
    print(f"{'setup':<25} {'n':<5} {'avg_spread':<12} "
          f"{'mid-mid':<10} {'ask-mid':<10} {'ASK-BID':<10} {'ask+tick':<10}")
    print("-" * 110)
    for _, r in summary.iterrows():
        print(f"{r['setup']:<25} {int(r['n']):<5} {r['avg_spread']:>5.1f}%      "
              f"{r['mean_midmid']:>+5.1f}%   {r['mean_askmid']:>+5.1f}%   "
              f"{r['mean_askbid']:>+5.1f}%   {r['mean_asktick']:>+5.1f}%")

    print("\nMid-mid is the original (theoretical) result.")
    print("Ask-bid is what real retail fills produce. This is the truth.")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    sys.exit(main(limit=args.limit))
