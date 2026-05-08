"""Backtest #1: EMA-direction alignment as a 0DTE filter.

For each historical alert with NBBO outcome, compute SPY's EMA8/EMA20 (1-min)
at fire time, then split outcomes by:
  - bullish alert + EMA8>EMA20 (aligned) vs EMA8<EMA20 (counter)
  - bearish alert + EMA8<EMA20 (aligned) vs EMA8>EMA20 (counter)

Uses minute bars from server.alert_annotations.get_minute_bars (yfinance/databento).
NBBO outcomes from zero_dte_alerts_nbbo_outcomes.

Reports: hit rate, mean MFE, TP+50/Stop-30 mean P&L per slice + bootstrap CI.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_annotations import get_minute_bars  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"


def compute_spy_features_at(date: str, fire_ts: int) -> dict:
    """Return SPY EMA8, EMA20, slope, VWAP at fire_ts."""
    bars = get_minute_bars("SPY", date)
    if bars.empty:
        return {}
    bars = bars.copy().reset_index(drop=True)
    for c in ("close", "high", "low", "volume"):
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    bars["ema8"] = bars["close"].ewm(span=8, adjust=False).mean()
    bars["ema20"] = bars["close"].ewm(span=20, adjust=False).mean()
    bars["typ"] = (bars["high"] + bars["low"] + bars["close"]) / 3
    bars["vp"] = bars["typ"] * bars["volume"]
    bars["vwap"] = bars["vp"].cumsum() / bars["volume"].cumsum()
    minute_ts = bars["minute"].apply(lambda t: int(t.timestamp())).astype("int64")
    sub = bars[minute_ts <= fire_ts]
    if sub.empty:
        return {}
    last = sub.iloc[-1]
    last5 = sub.tail(5)
    e8_slope = ((last5.iloc[-1]["ema8"] - last5.iloc[0]["ema8"]) /
                last5.iloc[0]["ema8"] * 1000) if len(last5) >= 2 else 0
    return {
        "spy_close": float(last["close"]),
        "ema8": float(last["ema8"]),
        "ema20": float(last["ema20"]),
        "vwap": float(last["vwap"]),
        "ema8_slope_pml": float(e8_slope),
    }


def main() -> int:
    conn = sqlite3.connect(ALERT_DB)
    df = pd.read_sql("""
        SELECT a.alert_id, a.ticker, a.fired_at, a.direction,
               n.peak_pnl_pct as mfe, n.eod_pnl_pct as eod
        FROM zero_dte_alerts a
        JOIN zero_dte_alerts_nbbo_outcomes n ON n.alert_id = a.alert_id
        WHERE n.source = 'NBBO'
        ORDER BY a.fired_at
    """, conn)
    conn.close()

    print(f"[ema-align] computing SPY features for {len(df)} alerts...")
    features = []
    for _, a in df.iterrows():
        d = datetime.fromtimestamp(a["fired_at"]).strftime("%Y-%m-%d")
        f = compute_spy_features_at(d, int(a["fired_at"]))
        features.append(f)
    feat_df = pd.DataFrame(features)
    df = pd.concat([df.reset_index(drop=True), feat_df.reset_index(drop=True)],
                   axis=1)

    df = df[df["ema8"].notna()].copy()
    print(f"[ema-align] usable: {len(df)} alerts (lost {len(features)-len(df)} to missing data)")

    df["ema_bull"] = df["ema8"] > df["ema20"]
    df["above_vwap"] = df["spy_close"] > df["vwap"]

    def aligned(r):
        if r["direction"] == "bullish":
            return r["ema_bull"]
        return not r["ema_bull"]
    df["ema_aligned"] = df.apply(aligned, axis=1)

    def vwap_aligned(r):
        if r["direction"] == "bullish":
            return r["above_vwap"]
        return not r["above_vwap"]
    df["vwap_aligned"] = df.apply(vwap_aligned, axis=1)

    # Combined alignment
    df["dual_aligned"] = df["ema_aligned"] & df["vwap_aligned"]

    # TP+50/Stop-30 simulated P&L
    def sim(r):
        if r["mfe"] >= 50:
            return 50.0
        if r["eod"] <= -30:
            return -30.0
        return float(r["eod"])
    df["policy"] = df.apply(sim, axis=1)
    df["win50"] = (df["mfe"] >= 50).astype(int)
    df["win25"] = (df["mfe"] >= 25).astype(int)

    print()
    print("=" * 90)
    print(f"BACKTEST #1: EMA-direction alignment (n={len(df)})")
    print("=" * 90)

    def report(name, sub):
        if sub.empty:
            print(f"{name:<40} n=0")
            return
        n = len(sub)
        print(f"{name:<40} n={n:<3}  mean MFE={sub['mfe'].mean():>+5.0f}%  "
              f"win50={sub['win50'].sum()}/{n} ({sub['win50'].mean()*100:.0f}%)  "
              f"TP50/S30 mean={sub['policy'].mean():>+5.0f}%  "
              f"median={sub['policy'].median():>+5.0f}%")

    print("\n--- BY EMA ALIGNMENT ---")
    report("ALL alerts", df)
    report("EMA-aligned (matches direction)", df[df["ema_aligned"]])
    report("EMA counter-trend", df[~df["ema_aligned"]])

    print("\n--- BY VWAP POSITION ALIGNMENT ---")
    report("VWAP-aligned (above for bull, below bear)", df[df["vwap_aligned"]])
    report("VWAP counter", df[~df["vwap_aligned"]])

    print("\n--- COMBINED EMA+VWAP ---")
    report("DUAL aligned (EMA + VWAP)", df[df["dual_aligned"]])
    report("EITHER misaligned", df[~df["dual_aligned"]])

    print("\n--- BULLISH alerts only ---")
    bull = df[df["direction"] == "bullish"]
    report("Bull + EMA8>EMA20 (aligned)", bull[bull["ema_aligned"]])
    report("Bull + EMA8<EMA20 (counter)", bull[~bull["ema_aligned"]])
    report("Bull + above VWAP", bull[bull["above_vwap"]])
    report("Bull + below VWAP", bull[~bull["above_vwap"]])

    print("\n--- BEARISH alerts only ---")
    bear = df[df["direction"] == "bearish"]
    report("Bear + EMA8<EMA20 (aligned)", bear[bear["ema_aligned"] == False])
    report("Bear + EMA8>EMA20 (counter)", bear[bear["ema_aligned"] == True])

    # Bootstrap CI on aligned − counter difference (TP50/S30 means)
    print("\n--- BOOTSTRAP (2000 resamples) ---")
    np.random.seed(42)
    diffs_ema = []
    diffs_vwap = []
    diffs_dual = []
    for _ in range(2000):
        s = df.sample(len(df), replace=True)
        a = s[s["ema_aligned"]]["policy"]
        b = s[~s["ema_aligned"]]["policy"]
        if len(a) > 0 and len(b) > 0:
            diffs_ema.append(a.mean() - b.mean())
        a = s[s["vwap_aligned"]]["policy"]
        b = s[~s["vwap_aligned"]]["policy"]
        if len(a) > 0 and len(b) > 0:
            diffs_vwap.append(a.mean() - b.mean())
        a = s[s["dual_aligned"]]["policy"]
        b = s[~s["dual_aligned"]]["policy"]
        if len(a) > 0 and len(b) > 0:
            diffs_dual.append(a.mean() - b.mean())

    def bs_print(name, diffs):
        d = np.array(diffs)
        print(f"{name:<35} mean diff={d.mean():>+5.1f}pp  "
              f"90% CI=[{np.percentile(d,5):>+5.1f}, {np.percentile(d,95):>+5.1f}]  "
              f"P(diff>0)={(d>0).mean()*100:.0f}%")
    bs_print("EMA-aligned − counter", diffs_ema)
    bs_print("VWAP-aligned − counter", diffs_vwap)
    bs_print("Dual-aligned − any-misaligned", diffs_dual)

    # Per-alert table
    print()
    print("=" * 110)
    print("PER-ALERT DETAIL (sorted by date)")
    print("=" * 110)
    df["fire_dt"] = df["fired_at"].apply(
        lambda t: datetime.fromtimestamp(t).strftime("%m-%d %H:%M"))
    cols_show = ["fire_dt", "ticker", "direction", "spy_close", "ema8", "ema20",
                 "ema_aligned", "vwap_aligned", "mfe", "policy", "win50"]
    print(df[cols_show].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
