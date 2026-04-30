"""30-day backtest of the Structural Turn detector.

Runs evaluate_turn() at every minute of every trading day in the last 30
days for a watchlist of tickers. Records every 5/5 qualified fire, then
measures actual outcomes:
  - Spot move T+15min, T+30min, T+60min, T+EOD
  - 0DTE ATM call P&L T+30min, T+60min, T+EOD
  - Hit rate, average return, Sharpe-ish metric

Output:
  docs/research/structural_turn_30d_backtest.md
  docs/research/structural_turn_30d_fires.csv

Usage:
  python scripts/structural_turn_backtest_30d.py [--tickers SPY,QQQ,IWM] [--days 30]
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

import httpx
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")
from server.floor_migration import run_backfill as floor_backfill
from server.structural_turn import evaluate_turn

SNAPSHOTS_DB = "./snapshots.db"
FLOOR_DB = "./floor_migrations.db"
OUT_REPORT = Path("docs/research/structural_turn_30d_backtest.md")
OUT_CSV = Path("docs/research/structural_turn_30d_fires.csv")

THETA = "http://127.0.0.1:25503"
TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN", "")
TRADIER_BASE = os.environ.get("TRADIER_BASE_URL", "https://api.tradier.com/v1").rstrip("/")


def trading_days(end_date: datetime, days_back: int) -> list[datetime]:
    """Return list of weekdays in [end - days_back, end]."""
    out = []
    d = end_date - timedelta(days=days_back)
    while d <= end_date:
        if d.weekday() < 5:
            out.append(d.replace(hour=0, minute=0, second=0, microsecond=0))
        d += timedelta(days=1)
    return out


def load_snapshots_for_day(ticker: str, day: datetime) -> list[dict]:
    start = int(day.replace(hour=4).timestamp())
    end = int(day.replace(hour=20).timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT ts, spot, king, floor, ceiling, regime, signal,
                      pos_gex, neg_gex, net_delta, zgl
               FROM snapshots
               WHERE ticker = ? AND ts BETWEEN ? AND ?
               ORDER BY ts""",
            (ticker, start, end),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def load_minute_bars_yf(ticker: str, day: datetime,
                         interval: str = "1m") -> list[dict]:
    """Pull bars for one day at given interval.

    yfinance interval coverage:
      1m  → last 30 days
      2m  → last 60 days
      5m  → last 60 days
    """
    start = day.strftime("%Y-%m-%d")
    end = (day + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        df = yf.Ticker(ticker).history(
            start=start, end=end, interval=interval, prepost=False,
        )
    except Exception:
        return []
    if df.empty:
        return []
    df.index = df.index.tz_convert("America/New_York")
    return [
        {
            "ts": int(t.timestamp()),
            "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "volume": int(r["Volume"]),
        }
        for t, r in df.iterrows()
    ]


def load_minute_bars_yf_with_fallback(ticker: str, day: datetime) -> list[dict]:
    """Try 1m → 2m → 5m intervals. 1m covers 30d, 2m/5m cover 60d."""
    for iv in ("1m", "2m", "5m"):
        bars = load_minute_bars_yf(ticker, day, interval=iv)
        if bars:
            return bars
    return []


def load_minute_bars_tradier(ticker: str, day: datetime) -> list[dict]:
    """Pull 1-min bars from Tradier timesales. ~20 days of intraday history."""
    if not TRADIER_TOKEN:
        return []
    start = day.strftime("%Y-%m-%d 09:30")
    end = day.strftime("%Y-%m-%d 16:00")
    try:
        r = requests.get(
            f"{TRADIER_BASE}/markets/timesales",
            params={"symbol": ticker, "interval": "1min",
                    "start": start, "end": end, "session_filter": "open"},
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}",
                     "Accept": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"  tradier {ticker} {day:%Y-%m-%d}: HTTP {r.status_code}")
            return []
        data = r.json().get("series") or {}
        bars_raw = data.get("data") or []
        if isinstance(bars_raw, dict):
            bars_raw = [bars_raw]
    except Exception as e:
        print(f"  tradier error {ticker} {day:%Y-%m-%d}: {e}")
        return []
    out = []
    for b in bars_raw:
        ts_str = b.get("time", "")
        try:
            t = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        out.append({
            "ts": int(t.timestamp()),
            "open": float(b.get("open", 0)),
            "high": float(b.get("high", 0)),
            "low": float(b.get("low", 0)),
            "close": float(b.get("close", 0)),
            "volume": int(b.get("volume", 0)),
        })
    return out


def load_minute_bars_spx(day: datetime) -> list[dict]:
    """SPX is an index — Tradier returns OHLC but volume=0. Merge SPY's
    volume so the absorption gate has a real volume signal. SPY is the
    standard ETF proxy for SPX flow, so SPY's volume = institutional
    SPX-complex activity.

    Fallback for older days (>28d): use SPY × 10 synthetic SPX from
    yfinance (correlation 0.99+; volume column = SPY's actual volume)."""
    spx_bars = load_minute_bars_tradier("SPX", day)
    if not spx_bars:
        # Fallback: synthesize SPX from SPY × 10 using yfinance
        spy_bars = load_minute_bars_yf_with_fallback("SPY", day)
        if not spy_bars:
            return []
        synth = []
        for b in spy_bars:
            synth.append({
                "ts": b["ts"],
                "open": b["open"] * 10,
                "high": b["high"] * 10,
                "low": b["low"] * 10,
                "close": b["close"] * 10,
                "volume": b["volume"],  # SPY volume as proxy
            })
        return synth
    spy_bars = load_minute_bars_tradier("SPY", day)
    if not spy_bars:
        return spx_bars
    spy_vol_by_ts = {b["ts"]: b["volume"] for b in spy_bars}
    for b in spx_bars:
        b["volume"] = spy_vol_by_ts.get(b["ts"], 0)
    return spx_bars


def load_minute_bars(ticker: str, day: datetime, source: str = "tradier") -> list[dict]:
    """Dispatch chain: Tradier (28d) → yfinance 1m (30d) → 2m (60d) → 5m (60d).
    SPX has special handling. Returned bars may be coarser than 1-min for older
    days; the detector treats them as a list of OHLCV dicts regardless."""
    if ticker == "SPX":
        return load_minute_bars_spx(day)
    if source == "tradier":
        bars = load_minute_bars_tradier(ticker, day)
        if bars:
            return bars
        return load_minute_bars_yf_with_fallback(ticker, day)
    return load_minute_bars_yf_with_fallback(ticker, day)


# ── ThetaData option-quote pull ────────────────────────────────────


# Cache IVs per (ticker, ts, strikes-tuple, side) — minute bars repeat
_iv_cache: dict[tuple, list[float | None]] = {}


def fetch_iv_at(ticker: str, ts: int, strikes: list[int], right: str,
                expiry: str | None = None) -> list[float | None]:
    """For each strike, pull the implied vol at the given timestamp from
    ThetaData option_history_greeks_implied_volatility endpoint.

    Uses 0DTE expiry (same date as ts) by default — that's the relevant
    expiry for our 0DTE strategy.

    Coarse but accurate: pull bar at the minute matching ts.
    """
    if not strikes:
        return []
    sym = "SPXW" if ticker == "SPX" else ticker
    day_dt = datetime.fromtimestamp(ts).date()
    day_str = day_dt.strftime("%Y-%m-%d")
    exp = expiry or day_str
    target_hhmm = datetime.fromtimestamp(ts).strftime("%H:%M")
    cache_key = (sym, exp, tuple(strikes), right, target_hhmm)
    if cache_key in _iv_cache:
        return _iv_cache[cache_key]
    out: list[float | None] = []
    for k in strikes:
        params = {
            "symbol": sym, "expiration": exp, "strike": f"{float(k):.3f}",
            "right": right.upper(), "start_date": day_str, "end_date": day_str,
            "interval": "1m",
        }
        try:
            r = requests.get(
                f"{THETA}/v3/option/history/greeks/implied_volatility",
                params=params, timeout=10,
            )
            if r.status_code != 200:
                out.append(None)
                continue
            df_iv = pd.read_csv(io.StringIO(r.text))
            if df_iv.empty:
                out.append(None)
                continue
            df_iv["t"] = pd.to_datetime(df_iv["timestamp"])
            df_iv["hhmm"] = df_iv["t"].dt.strftime("%H:%M")
            row = df_iv[df_iv["hhmm"] >= target_hhmm].head(1)
            if row.empty:
                out.append(None)
                continue
            iv_val = row.iloc[0].get("implied_vol")
            out.append(float(iv_val) if iv_val and iv_val > 0 else None)
        except Exception:
            out.append(None)
    _iv_cache[cache_key] = out
    return out


def fetch_option_quotes(symbol: str, expiration: str, strike: float,
                        right: str, date: str) -> pd.DataFrame:
    """Pull 1-min option bid/ask for one contract on one day."""
    params = {
        "symbol": symbol,
        "expiration": expiration,
        "strike": f"{strike:.3f}",
        "right": right,
        "start_date": date,
        "end_date": date,
        "interval": "1m",
    }
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote",
                         params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)]
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df


def measure_option_pnl(
    ticker: str, day: datetime, fire_ts: int, spot_at_fire: float,
    direction: str = "BULLISH",
) -> dict:
    """For a fire, pick ATM 0DTE call (BULLISH) or put (BEARISH) and
    compute realistic P&L paying ask, hitting bid, at +30m, +60m, EOD."""
    # SPX strikes are $5 wide; SPY/QQQ/IWM are $1
    if ticker == "SPX":
        strike = round(spot_at_fire / 5) * 5
        sym = "SPXW"
    else:
        strike = round(spot_at_fire)
        sym = ticker
    expiry = day.strftime("%Y-%m-%d")
    right = "C" if direction == "BULLISH" else "P"

    df = fetch_option_quotes(sym, expiry, float(strike), right,
                              day.strftime("%Y-%m-%d"))
    out = {"opt_strike": strike, "opt_right": right, "opt_entry": None,
           "opt_entry_t": None,
           "opt_30m_bid": None, "opt_60m_bid": None, "opt_eod_bid": None,
           "opt_30m_pnl": None, "opt_60m_pnl": None, "opt_eod_pnl": None,
           "opt_mfe": None}
    if df.empty:
        return out

    fire_dt = datetime.fromtimestamp(fire_ts)
    fire_hhmm = fire_dt.strftime("%H:%M")
    entry_sub = df[df["hhmm"] >= fire_hhmm]
    if entry_sub.empty:
        return out
    entry = entry_sub.iloc[0]
    entry_ask = float(entry["ask"])
    entry_mid = float(entry["mid"])
    if entry_ask <= 0:
        return out
    out["opt_entry"] = entry_ask
    out["opt_entry_t"] = entry["hhmm"]

    def quote_at_offset(off_sec: int):
        target_dt = fire_dt + timedelta(seconds=off_sec)
        target_hhmm = target_dt.strftime("%H:%M")
        sub = df[df["hhmm"] >= target_hhmm]
        if sub.empty:
            return None
        return float(sub.iloc[0]["bid"])

    b30 = quote_at_offset(30 * 60)
    b60 = quote_at_offset(60 * 60)
    eod_sub = df[df["hhmm"] <= "15:55"]
    beod = float(eod_sub.iloc[-1]["bid"]) if not eod_sub.empty else None

    out["opt_30m_bid"] = b30
    out["opt_60m_bid"] = b60
    out["opt_eod_bid"] = beod
    out["opt_30m_pnl"] = (b30 / entry_ask - 1) * 100 if b30 else None
    out["opt_60m_pnl"] = (b60 / entry_ask - 1) * 100 if b60 else None
    out["opt_eod_pnl"] = (beod / entry_ask - 1) * 100 if beod else None

    # MFE on mid between entry and EOD
    held = df[(df["hhmm"] >= fire_hhmm) & (df["hhmm"] <= "15:55")]
    if not held.empty and entry_mid > 0:
        out["opt_mfe"] = (held["mid"].max() / entry_mid - 1) * 100

    return out


def measure_outcome(
    bars: list[dict], fire_ts: int,
) -> dict:
    """For a fire at fire_ts, compute spot at +15/+30/+60min and EOD."""
    fire_bar = next((b for b in bars if b["ts"] >= fire_ts), None)
    if fire_bar is None:
        return {}
    entry_close = fire_bar["close"]

    def find_at_offset(off_sec: int) -> float | None:
        target = fire_ts + off_sec
        b = next((b for b in bars if b["ts"] >= target), None)
        return b["close"] if b else None

    p15 = find_at_offset(15 * 60)
    p30 = find_at_offset(30 * 60)
    p60 = find_at_offset(60 * 60)
    eod = bars[-1]["close"] if bars else None

    def pct(p: float | None) -> float | None:
        return (p / entry_close - 1) * 100 if p is not None else None

    return {
        "entry": entry_close,
        "p15": p15, "p30": p30, "p60": p60, "eod": eod,
        "ret_15m": pct(p15), "ret_30m": pct(p30),
        "ret_60m": pct(p60), "ret_eod": pct(eod),
    }


def find_qualified_fires_for_day(
    ticker: str, day: datetime, snaps: list[dict], bars: list[dict],
    pull_options: bool = True,
) -> list[dict]:
    """Walk every minute; scan BOTH BULLISH and BEARISH; record qualified 5/5 fires.
    Cooldown is per-direction (30 min) — bullish + bearish can both fire same day."""
    fires = []
    start = int(day.replace(hour=9, minute=30).timestamp())
    end = int(day.replace(hour=16, minute=0).timestamp())
    last_fire_by_dir: dict[str, int] = {"BULLISH": 0, "BEARISH": 0}
    cooldown = 30 * 60
    for ts in range(start, end + 1, 60):
        for direction in ("BULLISH", "BEARISH"):
            if ts - last_fire_by_dir[direction] < cooldown:
                continue
            ev = evaluate_turn(
                ticker, ts, direction=direction,
                snapshots_in_window=snaps, minute_bars=bars,
                snapshots_db=SNAPSHOTS_DB, floor_migrations_db=FLOOR_DB,
            )
            if not ev.qualified:
                continue
            outcome = measure_outcome(bars, ts)
            # For BEARISH, invert the spot-return interpretation: a bearish fire
            # that goes DOWN in spot is a winner. We negate the returns so the
            # downstream "positive = winner" logic works uniformly.
            if direction == "BEARISH":
                for k in ("ret_15m", "ret_30m", "ret_60m", "ret_eod"):
                    if outcome.get(k) is not None:
                        outcome[k] = -outcome[k]
            # Post-qualification: compute IV ratio (only for qualified fires
            # to avoid 50x backtest slowdown on per-minute IV pulls)
            try:
                from server.structural_turn import _compute_pc_iv_ratio
                pc_ratio, pc_z = _compute_pc_iv_ratio(
                    ticker, ts, ev.spot, fetch_iv_at,
                )
            except Exception:
                pc_ratio, pc_z = None, None

            row = {
                "ticker": ticker,
                "day": day.strftime("%Y-%m-%d"),
                "ts": ts,
                "time": datetime.fromtimestamp(ts).strftime("%H:%M"),
                "direction": direction,
                "tier": ev.tier,
                "spot": ev.spot,
                "floor": ev.floor,
                "king": ev.king,
                "regime": ev.regime,
                "ratio": ev.ratio,
                "zgl": ev.zgl,
                "spot_minus_zgl": ev.spot_minus_zgl,
                "avwap_prior_low": ev.avwap_prior_low,
                "spot_minus_avwap": ev.spot_minus_avwap,
                "pc_iv_ratio": pc_ratio,
                "pc_iv_ratio_z": pc_z,
                **outcome,
            }
            if pull_options:
                opt = measure_option_pnl(ticker, day, ts, ev.spot, direction=direction)
                row.update(opt)
                pnl_str = f"opt_eod={opt['opt_eod_pnl']:+.0f}%" if opt["opt_eod_pnl"] is not None else "opt=N/A"
                arrow = "🟢" if direction == "BULLISH" else "🔴"
                print(f"    [{ev.tier}] fire {arrow} {direction} @ {row['time']} spot=${ev.spot:.2f}  {pnl_str}")
            fires.append(row)
            last_fire_by_dir[direction] = ts
    return fires


def render_report(fires: pd.DataFrame, days_scanned: int, tickers: list[str]) -> str:
    L: list[str] = []
    L.append("# Structural Turn — 30-day Backtest (BULLISH + BEARISH)")
    L.append("")
    L.append(f"- Scan window: last **{days_scanned} trading days**")
    L.append(f"- Tickers: {', '.join(tickers)}")
    if "direction" in fires.columns:
        bull = (fires["direction"] == "BULLISH").sum()
        bear = (fires["direction"] == "BEARISH").sum()
        L.append(f"- Total qualified 5/5 fires: **{len(fires)}** "
                 f"(bullish {bull}, bearish {bear})")
    else:
        L.append(f"- Total qualified 5/5 fires: **{len(fires)}**")
    L.append("")
    L.append("**Note**: BEARISH fire returns are negated so positive = winner across both directions. "
             "BULLISH option P&L = ATM 0DTE call. BEARISH option P&L = ATM 0DTE put.")
    L.append("")
    if fires.empty:
        L.append("**No qualified fires found.** Either the gates are too strict, "
                 "the snapshot data doesn't extend back far enough, or yfinance "
                 "intraday bars only cover ~7-8 days (typical limit).")
        return "\n".join(L)

    # Hit rates at each horizon — SPOT
    L.append("## Hit rates — SPOT (% with positive return)")
    L.append("")
    L.append("| Horizon | n | Hit% | Avg | Median | P25 | P75 | Min | Max |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for col, label in [("ret_15m", "+15min"), ("ret_30m", "+30min"),
                       ("ret_60m", "+60min"), ("ret_eod", "EOD")]:
        sub = fires[col].dropna()
        if sub.empty:
            L.append(f"| {label} | 0 | — | — | — | — | — | — | — |")
            continue
        hit = (sub > 0).mean() * 100
        L.append(f"| {label} | {len(sub)} | {hit:.1f}% | {sub.mean():+.2f}% | "
                 f"{sub.median():+.2f}% | {sub.quantile(0.25):+.2f}% | "
                 f"{sub.quantile(0.75):+.2f}% | {sub.min():+.2f}% | {sub.max():+.2f}% |")
    L.append("")

    # Hit rates at each horizon — OPTION P&L (the trade)
    if "opt_eod_pnl" in fires.columns:
        L.append("## Hit rates — OPTION P&L (0DTE ATM call, ask→bid)")
        L.append("")
        L.append("| Horizon | n | Hit% | Avg | Median | P25 | P75 | Min | Max |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for col, label in [("opt_30m_pnl", "+30min"), ("opt_60m_pnl", "+60min"),
                           ("opt_eod_pnl", "EOD")]:
            sub = fires[col].dropna()
            if sub.empty:
                L.append(f"| {label} | 0 | — | — | — | — | — | — | — |")
                continue
            hit = (sub > 0).mean() * 100
            L.append(f"| {label} | {len(sub)} | {hit:.1f}% | {sub.mean():+.0f}% | "
                     f"{sub.median():+.0f}% | {sub.quantile(0.25):+.0f}% | "
                     f"{sub.quantile(0.75):+.0f}% | {sub.min():+.0f}% | {sub.max():+.0f}% |")
        # Add MFE row
        mfe_sub = fires["opt_mfe"].dropna() if "opt_mfe" in fires.columns else pd.Series(dtype=float)
        if not mfe_sub.empty:
            L.append(f"| MFE (mid) | {len(mfe_sub)} | — | {mfe_sub.mean():+.0f}% | "
                     f"{mfe_sub.median():+.0f}% | — | — | {mfe_sub.min():+.0f}% | "
                     f"{mfe_sub.max():+.0f}% |")
        L.append("")
        L.append("**Reading the option P&L**: positive numbers = trade made money. "
                 "Compare avg-EOD to MFE-mean — if MFE is >> avg-EOD, exit discipline is "
                 "leaving money on the table (the trade existed but you didn't hold).")
        L.append("")

    # By tier (the key new dimension)
    if "tier" in fires.columns:
        L.append("## By tier")
        L.append("")
        L.append("| Tier | Fires | Avg Opt EOD | Hit% Opt EOD | Avg MFE |")
        L.append("|---|---|---|---|---|")
        for t, sub in fires.groupby("tier"):
            avg_eod = sub["opt_eod_pnl"].dropna().mean() if "opt_eod_pnl" in sub else float("nan")
            hit_eod = (sub["opt_eod_pnl"].dropna() > 0).mean() * 100 if sub["opt_eod_pnl"].notna().any() else 0
            mfe = sub["opt_mfe"].dropna().mean() if "opt_mfe" in sub else float("nan")
            L.append(f"| {t} | {len(sub)} | {avg_eod:+.0f}% | {hit_eod:.0f}% | {mfe:+.0f}% |")
        L.append("")

    # By direction
    if "direction" in fires.columns:
        L.append("## By direction")
        L.append("")
        L.append("| Direction | Fires | Avg Opt EOD | Hit% Opt EOD | Avg MFE |")
        L.append("|---|---|---|---|---|")
        for d, sub in fires.groupby("direction"):
            avg_eod = sub["opt_eod_pnl"].dropna().mean() if "opt_eod_pnl" in sub else float("nan")
            hit_eod = (sub["opt_eod_pnl"].dropna() > 0).mean() * 100 if sub["opt_eod_pnl"].notna().any() else 0
            mfe = sub["opt_mfe"].dropna().mean() if "opt_mfe" in sub else float("nan")
            L.append(f"| {d} | {len(sub)} | {avg_eod:+.0f}% | {hit_eod:.0f}% | {mfe:+.0f}% |")
        L.append("")

    # By ticker
    L.append("## By ticker")
    L.append("")
    L.append("| Ticker | Fires | Avg +30m | Avg +60m | Avg EOD | Hit% +30m | Hit% EOD |")
    L.append("|---|---|---|---|---|---|---|")
    for t, sub in fires.groupby("ticker"):
        avg30 = sub["ret_30m"].dropna().mean()
        avg60 = sub["ret_60m"].dropna().mean()
        avgeod = sub["ret_eod"].dropna().mean()
        hit30 = (sub["ret_30m"].dropna() > 0).mean() * 100 if sub["ret_30m"].notna().any() else 0
        hiteod = (sub["ret_eod"].dropna() > 0).mean() * 100 if sub["ret_eod"].notna().any() else 0
        L.append(f"| {t} | {len(sub)} | {avg30:+.2f}% | {avg60:+.2f}% | "
                 f"{avgeod:+.2f}% | {hit30:.0f}% | {hiteod:.0f}% |")
    L.append("")

    # Time-of-day analysis
    L.append("## Time of day")
    L.append("")
    L.append("| Hour ET | Fires | Avg +30m | Hit% +30m |")
    L.append("|---|---|---|---|")
    fires["hour"] = pd.to_numeric(fires["time"].str[:2], errors="coerce")
    for h, sub in fires.groupby("hour"):
        if pd.isna(h):
            continue
        avg = sub["ret_30m"].dropna().mean()
        hit = (sub["ret_30m"].dropna() > 0).mean() * 100 if sub["ret_30m"].notna().any() else 0
        L.append(f"| {int(h):02d}:00 | {len(sub)} | {avg:+.2f}% | {hit:.0f}% |")
    L.append("")

    # Distribution of returns
    big_winners = fires[fires["ret_60m"] > 0.5]
    big_losers = fires[fires["ret_60m"] < -0.5]
    L.append(f"### Tail behavior (T+60min)")
    L.append(f"- Big winners (>+0.5% spot): **{len(big_winners)}**")
    L.append(f"- Big losers (<-0.5% spot): **{len(big_losers)}**")
    L.append(f"- Asymmetry ratio: **{len(big_winners) / max(len(big_losers), 1):.2f}**")
    L.append("")

    # Sample fires — with option P&L
    L.append("## All fires (chronological, with option P&L)")
    L.append("")
    L.append("| Day | Time | Tkr | Dir | Tier | Spot | Strike | Entry$ | "
             "Opt+30m | Opt+60m | **Opt EOD** | MFE |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in fires.sort_values(["day", "ts"]).iterrows():
        def fmt_pct(x):
            return f"{x:+.0f}%" if pd.notna(x) else "—"
        right = r.get("opt_right") or ("C" if r.get("direction", "BULLISH") == "BULLISH" else "P")
        strike = f"{int(r['opt_strike'])}{right}" if pd.notna(r.get('opt_strike')) else "—"
        entry = f"${r['opt_entry']:.2f}" if pd.notna(r.get('opt_entry')) else "—"
        d = r.get("direction", "BULLISH")
        d_emoji = "🟢" if d == "BULLISH" else "🔴"
        tier = r.get("tier", "—")
        tier_emoji = "⚡" if tier == "A" else ("👁" if tier == "B" else "—")
        L.append(f"| {r['day']} | {r['time']} | {r['ticker']} | {d_emoji} | "
                 f"{tier_emoji} {tier} | ${r['spot']:.2f} | {strike} | {entry} | "
                 f"{fmt_pct(r.get('opt_30m_pnl'))} | "
                 f"{fmt_pct(r.get('opt_60m_pnl'))} | "
                 f"**{fmt_pct(r.get('opt_eod_pnl'))}** | "
                 f"{fmt_pct(r.get('opt_mfe'))} |")
    L.append("")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--bars-source", default="tradier",
                    choices=["tradier", "yfinance"])
    ap.add_argument("--skip-floor-backfill", action="store_true",
                    help="Skip [1/3] floor_migrations backfill — useful when "
                    "it was already populated in a prior run.")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    print(f"Tickers: {tickers}")
    print(f"Backtest window: last {args.days} days")

    # Step 1: ensure floor_migrations is current
    if args.skip_floor_backfill:
        print("\n[1/3] Skipping floor_migrations backfill (--skip-floor-backfill)")
    else:
        print("\n[1/3] Backfilling floor_migrations...", flush=True)
        summary = floor_backfill(snapshot_db_path=SNAPSHOTS_DB, since_days=args.days + 7)
        print(f"  {summary['events_total']} events ({summary['reclaims']} reclaims)")

    # Step 2: walk every trading day
    end_date = datetime(2026, 4, 28)  # use end of today (audit base)
    days = trading_days(end_date, args.days)
    print(f"\n[2/3] Scanning {len(days)} trading days...")

    all_fires = []
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_csv = OUT_CSV.parent / (OUT_CSV.stem + "_checkpoint.csv")
    for d in days:
        for t in tickers:
            try:
                snaps = load_snapshots_for_day(t, d)
                if not snaps:
                    continue
                bars = load_minute_bars(t, d, source=args.bars_source)
                if not bars:
                    continue
                fires = find_qualified_fires_for_day(t, d, snaps, bars)
                if fires:
                    print(f"  {d:%Y-%m-%d} {t}: {len(fires)} fires (bars={len(bars)})",
                          flush=True)
                all_fires.extend(fires)
            except Exception as e:
                print(f"  ! {d:%Y-%m-%d} {t}: SKIPPED — {type(e).__name__}: {e}",
                      flush=True)
                import traceback
                traceback.print_exc()
                continue
        # Per-day checkpoint so a later crash doesn't lose what we have.
        if all_fires:
            pd.DataFrame(all_fires).to_csv(checkpoint_csv, index=False)

    print(f"\n[3/3] Total fires: {len(all_fires)}")
    df = pd.DataFrame(all_fires)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"  CSV → {OUT_CSV}")

    md = render_report(df, len(days), tickers)
    OUT_REPORT.write_text(md, encoding="utf-8")
    print(f"  Report → {OUT_REPORT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
