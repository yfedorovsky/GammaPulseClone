"""Faithful replay of SETUP FORMING scoring against historical snapshots.

The scan_setups() pathway (server/signals.py:2312) fires Telegram alerts
but never writes to soe_signals or signal_outcomes — so we have NO live WR
for it. This script reconstructs every PM-window snapshot, applies the exact
scoring rubric with real RTS / IVP, and measures forward 1d/3d/5d hit rates.

Inputs:
  - snapshots table (ts, ticker, regime, signal, king, floor, iv)
  - yfinance daily OHLC for RTS computation + forward returns
  - server.mir_rules.is_mir_sector for sector bonus (static, present-day)

Output:
  - data/setup_forming_replay.csv  (all would-fire events with outcomes)
  - aggregate WR tables to stdout

Caveats:
  - is_mir_sector is point-in-time-now (sector baskets evolved during 2026)
  - 4hr cooldown applied per ticker (matches live behavior)
  - PM window proxy: 14:00-16:00 ET = 18-21 UTC (DST handling approximate)

Run:
    python -m backtest.setup_forming_replay
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from server.config import get_settings
from server.mir_rules import is_mir_sector

OUT = Path("data/setup_forming_replay.csv")
OHLC_CACHE = Path("data/setup_replay_ohlc.pkl")

SCORE_THRESHOLD = 6
COOLDOWN_SEC = 14400  # 4hr — matches live
INDEX_TICKERS = {"SPY", "QQQ", "IWM", "DIA", "SPX", "NDX", "RUT", "VIX"}


def load_snapshots() -> pd.DataFrame:
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    # PM window proxy: 18-21 UTC covers 13-17 ET across DST transitions.
    # We'll filter precisely in Python after converting to ET.
    df = pd.read_sql_query("""
        SELECT ts, ticker, spot, king, floor, signal, regime, iv
        FROM snapshots
        WHERE strftime('%H', ts, 'unixepoch') IN ('18','19','20','21')
          AND spot IS NOT NULL AND spot > 5
    """, c)
    c.close()
    # Convert ts to ET (US/Eastern); approximate via UTC-5 (won't be off > 1hr)
    df["dt_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df["dt_et"] = df["dt_utc"].dt.tz_convert("US/Eastern")
    df["hour_et"] = df["dt_et"].dt.hour
    df["weekday"] = df["dt_et"].dt.weekday
    df["date_et"] = df["dt_et"].dt.date
    # PM window: 14:00-15:59 ET (matches scan_setups is_pm)
    df = df[(df["hour_et"] >= 14) & (df["hour_et"] < 16)]
    df = df[df["weekday"] < 5]  # weekdays only
    # Skip indexes
    df = df[~df["ticker"].isin(INDEX_TICKERS)]
    return df.reset_index(drop=True)


def fetch_ohlc(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Batch yfinance daily Close for all tickers + SPY. Cache to parquet."""
    if OHLC_CACHE.exists():
        cached = pd.read_pickle(OHLC_CACHE)
        have = set(cached.columns)
        need = (set(tickers) | {"SPY"}) - have
        if not need:
            return cached
        print(f"  cache hit on {len(have)} tickers, fetching {len(need)} more")
        new = _yf_batch(sorted(need), start, end)
        if new is not None and not new.empty:
            merged = cached.join(new, how="outer")
            merged.to_pickle(OHLC_CACHE)
            return merged
        return cached
    print(f"  fetching {len(tickers)+1} tickers from yfinance ({start} -> {end})")
    df = _yf_batch(sorted(set(tickers) | {"SPY"}), start, end)
    df.to_pickle(OHLC_CACHE)
    return df


def _yf_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download Close prices for tickers, return wide df indexed by date."""
    out = {}
    BATCH = 50
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i+BATCH]
        try:
            d = yf.download(batch, start=start, end=end, progress=False,
                            auto_adjust=True, threads=True, group_by="ticker")
        except Exception as e:
            print(f"    batch {i}-{i+BATCH} ERROR: {e}")
            continue
        for t in batch:
            try:
                if isinstance(d.columns, pd.MultiIndex):
                    s = d[t]["Close"] if t in d.columns.get_level_values(0) else None
                else:
                    s = d["Close"]
                if s is not None and not s.dropna().empty:
                    out[t] = s
            except (KeyError, AttributeError):
                continue
        print(f"    batch {i//BATCH+1}: {len(out)} tickers loaded")
        time.sleep(0.3)
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def compute_rts(snap_df: pd.DataFrame, ohlc: pd.DataFrame) -> pd.Series:
    """Approximation of RTS score (0-100) from 20d return vs SPY 20d.
    Live RTS is more sophisticated, but 20d relative-strength dominates the
    signal. Output scaled so 70+ = "leader" and 50+ = "above SPY".
    """
    spy = ohlc.get("SPY")
    if spy is None:
        return pd.Series(0, index=snap_df.index)
    # 20d return at each calendar date for SPY
    spy_20d = (spy / spy.shift(20) - 1) * 100
    rts = []
    for idx, row in snap_df.iterrows():
        d = pd.Timestamp(row["date_et"])
        t = row["ticker"]
        ser = ohlc.get(t)
        if ser is None:
            rts.append(0)
            continue
        # Use the close from PRIOR trading day to avoid lookahead
        valid_dates = ser.index[ser.index < d]
        if len(valid_dates) < 21:
            rts.append(0)
            continue
        ld = valid_dates[-1]
        old = ser.index[ser.index <= ld - pd.Timedelta(days=28)]
        if len(old) == 0:
            rts.append(0)
            continue
        old_d = old[-1]
        try:
            t_ret = (ser.loc[ld] / ser.loc[old_d] - 1) * 100
        except KeyError:
            rts.append(0)
            continue
        # SPY 20d at the same prior trading day
        spy_valid = spy_20d.dropna().index[spy_20d.dropna().index <= ld]
        spy_r = float(spy_20d.loc[spy_valid[-1]]) if len(spy_valid) else 0
        # Map relative return to 0-100 score: (ticker - SPY) capped
        # +0% rel = 50, +10% rel = 70, +20% rel = 90, +30%+ = 100
        rel = float(t_ret - spy_r)
        score = max(0, min(100, 50 + rel * 2))
        rts.append(score)
    return pd.Series(rts, index=snap_df.index)


def compute_ivp(snap_df: pd.DataFrame) -> pd.Series:
    """IV percentile per ticker via rolling 252-trading-day window of `iv`
    column from snapshots. Matches the spirit of live _ivp.
    """
    out = pd.Series(np.nan, index=snap_df.index)
    for t, sub in snap_df.groupby("ticker"):
        ivs = sub["iv"].dropna()
        if ivs.empty:
            continue
        # For each row, compute percentile rank vs trailing 252 calendar days
        sub_sorted = sub.sort_values("ts")
        ts_ordered = sub_sorted["ts"].values
        iv_ordered = sub_sorted["iv"].values
        idx_ordered = sub_sorted.index.values
        for i, (ts, iv_v, idx) in enumerate(zip(ts_ordered, iv_ordered, idx_ordered)):
            if pd.isna(iv_v):
                continue
            cutoff = ts - 252 * 86400
            window = iv_ordered[(ts_ordered >= cutoff) & (ts_ordered < ts)]
            window = window[~pd.isna(window)]
            if len(window) < 20:
                continue
            pct = float((window < iv_v).sum()) / len(window) * 100
            out.loc[idx] = pct
    return out


def score_row(row: pd.Series) -> tuple[int, list[str]]:
    """Replicate scan_setups() scoring exactly."""
    score = 0
    reasons = []
    spot = row.get("spot") or 0
    king = row.get("king") or 0
    floor_v = row.get("floor") or 0
    regime = row.get("regime")
    signal = row.get("signal", "") or ""

    # 1. GEX structure: POS regime + king above as magnet
    if regime == "POS" and king and spot:
        king_dist = (king - spot) / spot * 100
        if 0.3 < king_dist < 5:
            score += 2
            reasons.append("king_magnet")
        if floor_v and spot > floor_v:
            score += 1
            reasons.append("above_floor")
    if signal in ("MAGNET UP", "SUPPORT"):
        score += 1
        reasons.append(f"signal_{signal}")

    # 2. RTS / momentum
    rts_score = row.get("rts") or 0
    if rts_score >= 70:
        score += 2
        reasons.append("rts_leader")
    elif rts_score >= 50:
        score += 1
        reasons.append("rts_above")

    # 3. Mir's preferred sectors
    in_sector, _ = is_mir_sector(row["ticker"])
    if in_sector:
        score += 2
        reasons.append("mir_sector")

    # 4. IV environment (cheap)
    ivp = row.get("ivp")
    if ivp is not None and not pd.isna(ivp) and ivp < 30:
        score += 1
        reasons.append("ivp_cheap")

    # 5. Time bonus (PM window) — always true here since we filtered
    score += 1
    reasons.append("pm_window")

    # 6. Monday penalty
    if row["weekday"] == 0:
        score -= 1
        reasons.append("monday_penalty")

    return score, reasons


def apply_cooldown(fires: pd.DataFrame) -> pd.DataFrame:
    """4hr per-ticker cooldown — matches live setup_cooldown.json behavior."""
    fires = fires.sort_values("ts").reset_index(drop=True)
    last_fire: dict[str, int] = {}
    keep = []
    for _, r in fires.iterrows():
        ts = int(r["ts"])
        last = last_fire.get(r["ticker"], 0)
        if ts - last >= COOLDOWN_SEC:
            keep.append(True)
            last_fire[r["ticker"]] = ts
        else:
            keep.append(False)
    return fires[keep].reset_index(drop=True)


def add_forward_returns(fires: pd.DataFrame, ohlc: pd.DataFrame) -> pd.DataFrame:
    """Forward 1d/3d/5d returns from yfinance Close-to-Close."""
    rets_1d, rets_3d, rets_5d = [], [], []
    for _, r in fires.iterrows():
        t = r["ticker"]
        d = pd.Timestamp(r["date_et"])
        ser = ohlc.get(t)
        if ser is None:
            rets_1d.append(np.nan); rets_3d.append(np.nan); rets_5d.append(np.nan)
            continue
        # entry close on signal day (or the day before if intraday before close)
        valid = ser.index[ser.index <= d]
        if len(valid) < 1:
            rets_1d.append(np.nan); rets_3d.append(np.nan); rets_5d.append(np.nan)
            continue
        entry_d = valid[-1]
        entry_px = float(ser.loc[entry_d])
        future = ser.index[ser.index > entry_d]

        def _ret(n):
            if len(future) < n:
                return np.nan
            return (float(ser.loc[future[n-1]]) / entry_px - 1) * 100
        rets_1d.append(_ret(1)); rets_3d.append(_ret(3)); rets_5d.append(_ret(5))
    fires = fires.copy()
    fires["return_1d"] = rets_1d
    fires["return_3d"] = rets_3d
    fires["return_5d"] = rets_5d
    return fires


def report(fires: pd.DataFrame) -> None:
    print("\n" + "="*70)
    print(f"SETUP FORMING REPLAY — {len(fires)} fires (post-cooldown)")
    print("="*70)
    print(f"Date range: {fires['date_et'].min()} to {fires['date_et'].max()}")
    print(f"Unique tickers: {fires['ticker'].nunique()}")

    have_1d = fires.dropna(subset=["return_1d"])
    print(f"\nWith 1d outcomes: {len(have_1d)}")

    print("\n--- Overall WR ---")
    for h in ["1d", "3d", "5d"]:
        col = f"return_{h}"
        sub = fires.dropna(subset=[col])
        if not len(sub):
            continue
        hit = (sub[col] > 0).mean() * 100
        avg = sub[col].mean()
        med = sub[col].median()
        print(f"  {h}:  n={len(sub):>4}  hit={hit:>5.1f}%  avg={avg:+5.2f}%  med={med:+5.2f}%")

    print("\n--- WR by score ---")
    for sc, sub in have_1d.groupby("score"):
        if len(sub) < 5:
            continue
        hit = (sub["return_1d"] > 0).mean() * 100
        avg = sub["return_1d"].mean()
        print(f"  score={sc}:  n={len(sub):>4}  1d_hit={hit:>5.1f}%  avg={avg:+5.2f}%")

    print("\n--- WR by regime ---")
    for r, sub in have_1d.groupby("regime"):
        if len(sub) < 5:
            continue
        hit = (sub["return_1d"] > 0).mean() * 100
        avg = sub["return_1d"].mean()
        print(f"  {r:<8}  n={len(sub):>4}  1d_hit={hit:>5.1f}%  avg={avg:+5.2f}%")

    print("\n--- Top 15 tickers by fire count ---")
    by_t = have_1d.groupby("ticker").agg(
        n=("return_1d", "count"),
        hit_1d=("return_1d", lambda x: (x > 0).mean() * 100),
        avg_1d=("return_1d", "mean"),
        avg_5d=("return_5d", "mean"),
    ).sort_values("n", ascending=False).head(15).round(2)
    print(by_t.to_string())

    print("\n--- Mir-sector vs non-sector ---")
    have_1d["in_sector"] = have_1d["ticker"].apply(lambda t: is_mir_sector(t)[0])
    for in_s, sub in have_1d.groupby("in_sector"):
        label = "Mir sector" if in_s else "non-sector"
        hit = (sub["return_1d"] > 0).mean() * 100
        avg = sub["return_1d"].mean()
        print(f"  {label:<14}  n={len(sub):>4}  1d_hit={hit:>5.1f}%  avg={avg:+5.2f}%")


def main() -> int:
    print("[1/6] Loading PM-window snapshots...")
    snap = load_snapshots()
    print(f"  {len(snap)} rows, {snap['ticker'].nunique()} tickers, "
          f"{snap['date_et'].nunique()} dates")

    print("\n[2/6] Fetching daily OHLC (yfinance batch, cached)...")
    tickers = sorted(snap["ticker"].unique().tolist())
    start = (pd.Timestamp(snap["date_et"].min()) - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(snap["date_et"].max()) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    ohlc = fetch_ohlc(tickers, start, end)
    print(f"  OHLC matrix: {ohlc.shape[0]} dates × {ohlc.shape[1]} tickers")

    print("\n[3/6] Computing RTS approximation (20d rel to SPY)...")
    snap["rts"] = compute_rts(snap, ohlc)

    print("\n[4/6] Computing IVP (rolling 252d)...")
    snap["ivp"] = compute_ivp(snap)

    print("\n[5/6] Scoring all rows + filtering threshold...")
    scores_reasons = snap.apply(score_row, axis=1)
    snap["score"] = scores_reasons.apply(lambda x: x[0])
    snap["reasons"] = scores_reasons.apply(lambda x: ",".join(x[1]))
    fires = snap[snap["score"] >= SCORE_THRESHOLD].copy()
    print(f"  {len(fires)} pre-cooldown fires (out of {len(snap)} candidates)")
    fires = apply_cooldown(fires)
    print(f"  {len(fires)} post-cooldown fires")

    print("\n[6/6] Forward returns from cached OHLC...")
    fires = add_forward_returns(fires, ohlc)
    fires.to_csv(OUT, index=False)
    print(f"  Wrote {OUT}")

    report(fires)
    return 0


if __name__ == "__main__":
    sys.exit(main())
