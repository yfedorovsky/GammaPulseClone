"""6-month extended EMA cross backtest.

Uses 127 days of Databento SPY MBP-1 (Oct 30 2025 - May 1 2026) +
ThetaData OPRA NBBO for option exits.

For each day:
  1. Aggregate Databento trades to 1-min OHLC
  2. Resample to 5-min, compute EMA8/EMA20
  3. Detect crosses (warmup ≥4 bars, no fires after 15:30)
  4. Simulate ATM SPY 0DTE trade entry on next 5-min bar's open
  5. Pull NBBO bars for that contract, compute MFE/EOD
  6. Apply TP+50/Stop-30 exit policy

Reports:
  - Per-trade summary across full sample
  - Per-month aggregation
  - Bull cross vs bear cross split
  - Bootstrap CI on per-trade P&L
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

from server.alert_annotations import get_minute_bars  # noqa: E402
from scripts.databento_loader import cache_status  # noqa: E402

THETA = "http://127.0.0.1:25503"
OUT_DB = "ema_cross_backtest_6mo.db"


def fetch_quote_bars(symbol: str, expiration: str, strike: float, right: str,
                    date: str) -> pd.DataFrame:
    params = {"symbol": symbol, "expiration": expiration,
              "strike": f"{strike:.3f}", "right": right,
              "start_date": date, "end_date": date, "interval": "1m"}
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote", params=params,
                         timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
    if df.empty:
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df[["hhmm", "bid", "ask", "mid"]].reset_index(drop=True)


def detect_crosses_5min(date: str) -> list[dict]:
    bars = get_minute_bars("SPY", date)
    if bars.empty:
        return []
    bars = bars.copy().reset_index(drop=True)
    for c in ("close", "high", "low", "volume"):
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    bars["minute_dt"] = bars["minute"]
    b5 = bars.set_index("minute_dt").resample("5min", closed="right",
                                              label="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum"}).dropna().reset_index()
    b5["hhmm"] = b5["minute_dt"].dt.strftime("%H:%M")
    b5 = b5[(b5["hhmm"] >= "09:30") & (b5["hhmm"] <= "16:00")].reset_index(drop=True)
    if b5.empty:
        return []
    b5["ema8"] = b5["close"].ewm(span=8, adjust=False).mean()
    b5["ema20"] = b5["close"].ewm(span=20, adjust=False).mean()
    b5["e8_above"] = b5["ema8"] > b5["ema20"]
    b5["prev_above"] = b5["e8_above"].shift(1)
    crosses = []
    for i, r in b5.iterrows():
        if i < 4: continue
        if pd.isna(r["prev_above"]): continue
        if r["e8_above"] and not r["prev_above"]:
            ctype = "BULL"
        elif not r["e8_above"] and r["prev_above"]:
            ctype = "BEAR"
        else: continue
        if r["hhmm"] >= "15:30": continue
        crosses.append({
            "hhmm": r["hhmm"], "type": ctype,
            "spy_close": float(r["close"]),
        })
    return crosses


def simulate_trade(date: str, cross: dict) -> dict:
    spy = cross["spy_close"]
    strike = float(round(spy))
    right = "C" if cross["type"] == "BULL" else "P"
    nbbo = fetch_quote_bars("SPY", date, strike, right, date)
    if nbbo.empty:
        return {"status": "NO_NBBO"}
    h, m = cross["hhmm"].split(":")
    next_min = int(h) * 60 + int(m) + 1
    entry_str = f"{next_min // 60:02d}:{next_min % 60:02d}"
    entry_rows = nbbo[nbbo["hhmm"] >= entry_str]
    if entry_rows.empty:
        return {"status": "NO_ENTRY"}
    e = entry_rows.iloc[0]
    cost = float(e["mid"])
    if cost <= 0:
        return {"status": "ZERO_COST"}
    sub = nbbo[nbbo["hhmm"] >= e["hhmm"]].reset_index(drop=True)
    peak_idx = sub["mid"].idxmax()
    peak = sub.iloc[peak_idx]
    eod = sub.iloc[-1]
    return {
        "status": "OK",
        "strike": strike, "right": right,
        "entry_hhmm": e["hhmm"], "entry_mid": cost,
        "peak_hhmm": peak["hhmm"], "peak_mid": float(peak["mid"]),
        "eod_mid": float(eod["mid"]),
        "mfe_pct": (float(peak["mid"]) - cost) / cost * 100,
        "eod_pct": (float(eod["mid"]) - cost) / cost * 100,
    }


def main() -> int:
    status = cache_status()
    spy_days = sorted(status[status["ticker"] == "SPY"]["date"].unique())
    print(f"[ema-6mo] {len(spy_days)} SPY days available "
          f"({spy_days[0]} to {spy_days[-1]})")

    conn = sqlite3.connect(OUT_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ema_cross_trades (
          day TEXT, cross_hhmm TEXT, cross_type TEXT,
          spy_close REAL, strike REAL, right TEXT,
          entry_hhmm TEXT, entry_mid REAL,
          peak_hhmm TEXT, peak_mid REAL, eod_mid REAL,
          mfe_pct REAL, eod_pct REAL, status TEXT,
          PRIMARY KEY (day, cross_hhmm)
        );
    """)

    all_trades = []
    for i, day in enumerate(spy_days):
        crosses = detect_crosses_5min(day)
        if not crosses:
            print(f"  [{i+1}/{len(spy_days)}] {day}: no crosses")
            continue
        day_trades = []
        for c in crosses:
            r = simulate_trade(day, c)
            r["day"] = day
            r["cross_hhmm"] = c["hhmm"]
            r["cross_type"] = c["type"]
            r["spy_close"] = c["spy_close"]
            day_trades.append(r)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO ema_cross_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["day"], r["cross_hhmm"], r["cross_type"],
                     r["spy_close"], r.get("strike"), r.get("right"),
                     r.get("entry_hhmm"), r.get("entry_mid"),
                     r.get("peak_hhmm"), r.get("peak_mid"), r.get("eod_mid"),
                     r.get("mfe_pct"), r.get("eod_pct"), r["status"]))
                conn.commit()
            except Exception as e:
                print(f"    db save fail: {e}")
        ok_n = sum(1 for r in day_trades if r["status"] == "OK")
        if ok_n:
            mean_mfe = np.mean([r["mfe_pct"] for r in day_trades
                                if r["status"] == "OK"])
            print(f"  [{i+1}/{len(spy_days)}] {day}: {len(crosses)} crosses, "
                  f"{ok_n} ok, mean MFE {mean_mfe:+.0f}%")
        else:
            print(f"  [{i+1}/{len(spy_days)}] {day}: {len(crosses)} crosses, "
                  f"all NBBO failed")
        all_trades.extend(day_trades)

    conn.close()

    df = pd.DataFrame([t for t in all_trades if t["status"] == "OK"])
    if df.empty:
        print("No usable trades."); return 0

    print()
    print("=" * 90)
    print(f"6-MONTH EMA CROSS BACKTEST: n={len(df)} trades, "
          f"{df['day'].nunique()} days")
    print("=" * 90)

    def sim_policy(r):
        if r["mfe_pct"] >= 50:
            return 50.0
        if r["eod_pct"] <= -30:
            return -30.0
        return float(r["eod_pct"])
    df["policy"] = df.apply(sim_policy, axis=1)
    df["win50"] = (df["mfe_pct"] >= 50).astype(int)
    df["win25"] = (df["mfe_pct"] >= 25).astype(int)
    df["wipeout"] = (df["mfe_pct"] <= -50).astype(int)

    def summary(tag, sub):
        if sub.empty:
            print(f"{tag:<30} n=0"); return
        n = len(sub)
        d = sub["day"].nunique()
        print(f"{tag:<30} n={n:<4} days={d:<3}  "
              f"mean MFE={sub['mfe_pct'].mean():>+5.0f}%  "
              f"win50={sub['win50'].sum()}/{n} ({sub['win50'].mean()*100:.0f}%)  "
              f"policy mean={sub['policy'].mean():>+5.0f}%  "
              f"median={sub['policy'].median():>+5.0f}%  "
              f"total={sub['policy'].sum():>+5.0f}%")

    summary("ALL", df)
    summary("BULL crosses", df[df["cross_type"] == "BULL"])
    summary("BEAR crosses", df[df["cross_type"] == "BEAR"])

    # Per month
    df["month"] = df["day"].str[:7]
    print("\nPer month:")
    for month, sub in df.groupby("month"):
        summary(f"  {month}", sub)

    # Bootstrap CI on policy mean
    print("\nBootstrap (2000 resamples) on per-trade policy P&L:")
    np.random.seed(42)
    means = []
    for _ in range(2000):
        s = df.sample(len(df), replace=True)
        means.append(s["policy"].mean())
    means = np.array(means)
    print(f"  Mean: {means.mean():+.1f}%  90% CI: "
          f"[{np.percentile(means,5):+.1f}, {np.percentile(means,95):+.1f}]")
    print(f"  P(mean > 0): {(means > 0).mean()*100:.0f}%")
    print(f"  P(mean > +5%): {(means > 5).mean()*100:.0f}%")
    print(f"  P(mean > +10%): {(means > 10).mean()*100:.0f}%")

    # Cluster bootstrap by day (more honest CI)
    print("\nCluster bootstrap by day (2000 resamples):")
    days_arr = df["day"].unique()
    means_cb = []
    for _ in range(2000):
        sample_days = np.random.choice(days_arr, size=len(days_arr), replace=True)
        sample_df = pd.concat([df[df["day"] == d] for d in sample_days])
        means_cb.append(sample_df["policy"].mean())
    means_cb = np.array(means_cb)
    print(f"  Mean: {means_cb.mean():+.1f}%  90% CI: "
          f"[{np.percentile(means_cb,5):+.1f}, {np.percentile(means_cb,95):+.1f}]")
    print(f"  P(mean > 0): {(means_cb > 0).mean()*100:.0f}%")

    print(f"\n[ema-6mo] saved to {OUT_DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
