"""Backtest #2: EMA8/EMA20 cross on SPY 5-min as a parallel 0DTE alert source.

For each historical day with NBBO option data:
  1. Pull SPY 1-min bars, resample to 5-min
  2. Compute EMA8, EMA20 on 5-min closes
  3. Detect crosses:
     - Bull cross: EMA8 was <= EMA20 prev bar, now > EMA20
     - Bear cross: EMA8 was >= EMA20 prev bar, now < EMA20
  4. For each cross, simulate:
     - Bull → buy SPY 0DTE ATM CALL (round to nearest $1) at NEXT 5-min bar's open
     - Bear → buy SPY 0DTE ATM PUT
     - Use real NBBO mid as entry; track MFE/EOD via NBBO
  5. Apply TP+50/Stop-30 exit; report performance vs our existing GEX alerts

Compares EMA-cross-only system vs GEX-alert-only system vs union.
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

ALERT_DB = "zero_dte_alerts.db"
THETA = "http://127.0.0.1:25503"


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
    df["ts"] = (df["t"].astype("int64") // 10**9).astype(int)
    df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
    if df.empty:
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df[["ts", "hhmm", "bid", "ask", "mid"]].reset_index(drop=True)


def detect_crosses(date: str) -> list[dict]:
    """Return list of {ts, hhmm, type, spy_close, ema8, ema20} crosses on 5-min."""
    bars = get_minute_bars("SPY", date)
    if bars.empty:
        return []
    bars = bars.copy().reset_index(drop=True)
    for c in ("close", "high", "low", "volume"):
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    # Resample to 5-min using the minute timestamp
    bars["minute_dt"] = bars["minute"]
    bars = bars.set_index("minute_dt")
    bars5 = bars.resample("5min", closed="right", label="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum",
    }).dropna()
    bars5 = bars5.reset_index()
    # Restrict to RTH: 09:30 - 15:55 ET
    bars5["hhmm"] = bars5["minute_dt"].dt.strftime("%H:%M")
    bars5 = bars5[(bars5["hhmm"] >= "09:30") & (bars5["hhmm"] <= "16:00")]
    if bars5.empty:
        return []
    bars5 = bars5.reset_index(drop=True)

    bars5["ema8"] = bars5["close"].ewm(span=8, adjust=False).mean()
    bars5["ema20"] = bars5["close"].ewm(span=20, adjust=False).mean()
    # Need >= 20 bars before we trust EMA20 (warmup)
    bars5["e8_above"] = bars5["ema8"] > bars5["ema20"]
    bars5["prev_above"] = bars5["e8_above"].shift(1)
    crosses = []
    for i, r in bars5.iterrows():
        if i < 4:  # warmup
            continue
        if pd.isna(r["prev_above"]):
            continue
        if r["e8_above"] and not r["prev_above"]:
            ctype = "BULL"
        elif not r["e8_above"] and r["prev_above"]:
            ctype = "BEAR"
        else:
            continue
        # Skip last 2 bars (no time to trade)
        if r["hhmm"] >= "15:30":
            continue
        crosses.append({
            "ts": int(r["minute_dt"].timestamp()),
            "hhmm": r["hhmm"],
            "type": ctype,
            "spy_close": float(r["close"]),
            "ema8": float(r["ema8"]),
            "ema20": float(r["ema20"]),
        })
    return crosses


def simulate_cross_trade(date: str, cross: dict) -> dict:
    """Buy ATM SPY 0DTE call/put at NEXT 5-min bar's open. Track MFE via NBBO."""
    spy = cross["spy_close"]
    strike = float(round(spy))  # ATM $1 grid
    right = "C" if cross["type"] == "BULL" else "P"
    nbbo = fetch_quote_bars("SPY", date, strike, right, date)
    if nbbo.empty:
        return {"status": "NO_NBBO", "mfe_pct": None}
    # Entry at first NBBO bar at-or-after cross hhmm + 5 min
    # (next bar after the cross signal completes)
    entry_hhmm = cross["hhmm"]  # close of bar that confirmed cross; trade
                                # would be placed in the next minute or two
    # But realistic: enter at hhmm + 1 minute (one min after cross close)
    h, m = entry_hhmm.split(":")
    next_min = (int(h) * 60 + int(m) + 1)
    entry_str = f"{next_min // 60:02d}:{next_min % 60:02d}"
    entry_rows = nbbo[nbbo["hhmm"] >= entry_str]
    if entry_rows.empty:
        return {"status": "NO_ENTRY", "mfe_pct": None}
    entry_row = entry_rows.iloc[0]
    cost = float(entry_row["mid"])
    # Window from entry to EOD
    sub = nbbo[nbbo["hhmm"] >= entry_row["hhmm"]].reset_index(drop=True)
    peak_idx = sub["mid"].idxmax()
    peak_mid = float(sub.iloc[peak_idx]["mid"])
    peak_hhmm = sub.iloc[peak_idx]["hhmm"]
    eod_mid = float(sub.iloc[-1]["mid"])
    if cost <= 0:
        return {"status": "ZERO_COST", "mfe_pct": None}
    mfe_pct = (peak_mid - cost) / cost * 100
    eod_pct = (eod_mid - cost) / cost * 100
    # MFE-by-minute-N for time-stop classifier
    def mfe_at(n):
        early = sub[sub.index <= n]
        if early.empty:
            return None
        return (early["mid"].max() - cost) / cost * 100
    return {
        "status": "OK",
        "strike": strike, "right": right,
        "entry_hhmm": entry_row["hhmm"], "entry_mid": cost,
        "peak_hhmm": peak_hhmm, "peak_mid": peak_mid,
        "mfe_pct": round(mfe_pct, 2), "eod_pct": round(eod_pct, 2),
        "mfe_min1": mfe_at(0), "mfe_min3": mfe_at(2),
        "mfe_min5": mfe_at(4), "mfe_min10": mfe_at(9),
    }


def main() -> int:
    # Days with NBBO option data (we know paired_trades.db has Apr 14-May 4)
    # Use the days where we have alerts as the universe.
    conn = sqlite3.connect(ALERT_DB)
    days = pd.read_sql("""
        SELECT DISTINCT date(fired_at,'unixepoch','-4 hours') as day
        FROM zero_dte_alerts
        ORDER BY day
    """, conn)["day"].tolist()
    conn.close()
    print(f"[ema-cross] backtesting on {len(days)} days: {days}")

    all_trades = []
    for day in days:
        crosses = detect_crosses(day)
        print(f"\n[{day}] {len(crosses)} crosses")
        for c in crosses:
            r = simulate_cross_trade(day, c)
            if r["status"] != "OK":
                print(f"  {c['hhmm']} {c['type']:<4} → {r['status']}")
                continue
            r["day"] = day
            r["cross_hhmm"] = c["hhmm"]
            r["cross_type"] = c["type"]
            all_trades.append(r)
            print(f"  {c['hhmm']} {c['type']:<4} → K={r['strike']:.0f}{r['right']} "
                  f"entry@{r['entry_hhmm']} ${r['entry_mid']:.2f}  "
                  f"MFE={r['mfe_pct']:+.0f}% (peak@{r['peak_hhmm']})  "
                  f"EOD={r['eod_pct']:+.0f}%")

    if not all_trades:
        print("No trades generated."); return 0
    df = pd.DataFrame(all_trades)
    print()
    print("=" * 90)
    print(f"BACKTEST #2: EMA8/EMA20 5-min cross signals (n={len(df)} trades, "
          f"{df['day'].nunique()} days)")
    print("=" * 90)

    def sim(r):
        if r["mfe_pct"] >= 50:
            return 50.0
        if r["eod_pct"] <= -30:
            return -30.0
        return float(r["eod_pct"])
    df["policy"] = df.apply(sim, axis=1)
    df["win50"] = (df["mfe_pct"] >= 50).astype(int)
    df["win25"] = (df["mfe_pct"] >= 25).astype(int)

    print(f"\nMFE distribution:")
    print(f"  mean: {df['mfe_pct'].mean():+.0f}%, median: {df['mfe_pct'].median():+.0f}%")
    print(f"  win50: {df['win50'].sum()}/{len(df)} ({df['win50'].mean()*100:.0f}%)")
    print(f"  win25: {df['win25'].sum()}/{len(df)} ({df['win25'].mean()*100:.0f}%)")
    print(f"\nTP+50/Stop-30 P&L:")
    print(f"  mean: {df['policy'].mean():+.0f}%/trade")
    print(f"  median: {df['policy'].median():+.0f}%/trade")
    print(f"  total: {df['policy'].sum():+.0f}%")
    print()
    print("By cross type:")
    for ct in ("BULL", "BEAR"):
        sub = df[df["cross_type"] == ct]
        if sub.empty: continue
        print(f"  {ct}: n={len(sub)}, mean MFE={sub['mfe_pct'].mean():+.0f}%, "
              f"win50={sub['win50'].sum()}/{len(sub)}, "
              f"policy={sub['policy'].mean():+.0f}%/trade")

    print()
    print("Per-day:")
    for day, sub in df.groupby("day"):
        print(f"  {day}: n={len(sub)}, mean MFE={sub['mfe_pct'].mean():+.0f}%, "
              f"win50={sub['win50'].sum()}/{len(sub)}, "
              f"policy={sub['policy'].mean():+.0f}%")

    print()
    # Compare: GEX system on same days
    conn = sqlite3.connect(ALERT_DB)
    gex_df = pd.read_sql("""
        SELECT a.alert_id, date(a.fired_at,'unixepoch','-4 hours') as day,
               n.peak_pnl_pct as mfe, n.eod_pnl_pct as eod
        FROM zero_dte_alerts a
        JOIN zero_dte_alerts_nbbo_outcomes n ON n.alert_id = a.alert_id
        WHERE n.source = 'NBBO'
    """, conn)
    conn.close()
    gex_df["policy"] = gex_df.apply(sim, axis=1) if "mfe_pct" in gex_df.columns else 0
    # Map mfe_pct → mfe column
    gex_df["mfe_pct"] = gex_df["mfe"]
    gex_df["eod_pct"] = gex_df["eod"]
    gex_df["policy"] = gex_df.apply(sim, axis=1)
    gex_df["win50"] = (gex_df["mfe"] >= 50).astype(int)

    print("=" * 90)
    print("COMPARISON: GEX alert system vs EMA-cross system on same day universe")
    print("=" * 90)
    print(f"{'system':<25} {'n':<5} {'days':<6} {'mean MFE':<11} {'win50':<10} "
          f"{'policy mean':<13} {'total':<8}")
    print("-" * 90)
    for name, dfx in [("GEX alerts", gex_df), ("EMA crosses", df)]:
        n = len(dfx)
        d = dfx["day"].nunique()
        mfe = dfx["mfe_pct"].mean()
        w50 = f"{dfx['win50'].sum()}/{n}"
        pol = dfx["policy"].mean()
        total = dfx["policy"].sum()
        print(f"{name:<25} {n:<5} {d:<6} {mfe:>+5.0f}%      {w50:<10} "
              f"{pol:>+5.0f}%        {total:>+5.0f}%")

    print("\nDays where BOTH systems fired:")
    common_days = set(df["day"]) & set(gex_df["day"])
    print(f"  {len(common_days)} common days")
    for day in sorted(common_days):
        gex_n = (gex_df["day"] == day).sum()
        ema_n = (df["day"] == day).sum()
        gex_pol = gex_df[gex_df["day"] == day]["policy"].mean()
        ema_pol = df[df["day"] == day]["policy"].mean()
        print(f"    {day}: GEX n={gex_n} pol={gex_pol:+.0f}%  |  "
              f"EMA n={ema_n} pol={ema_pol:+.0f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
