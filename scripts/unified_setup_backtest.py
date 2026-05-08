"""Unified 0DTE setup backtester.

Tests 21 setups (EMA cross, ORB, PMH/PML, VWAP, failed-breakouts, sweeps)
across 6 months of SPY MBP-1 data with ThetaData NBBO option exits.

Architecture:
  - Setup: name + signal_fn(bars_1m, bars_5m, day_ctx) → list[Entry]
  - Each Entry has: hhmm, direction, invalidation_level (for underlying stop)
  - For each Entry: pull NBBO for ATM SPY 0DTE option, compute MFE/EOD
  - Apply 6 exit policies per trade (TP+50/Stop-30, TP+100/Stop-30,
    TP+50+underlying invalidation, time-stop 5/10/30 min)
  - Save all results to SQLite for slicing

Caching: NBBO bars per (date, strike, right) cached in memory across setups
to minimize API calls when multiple setups pick the same strike.
"""
from __future__ import annotations

import io
import sqlite3
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_annotations import get_minute_bars  # noqa: E402
from scripts.databento_loader import cache_status, load_window  # noqa: E402

THETA = "http://127.0.0.1:25503"
OUT_DB = "unified_setup_backtest.db"

# In-process NBBO cache: (date, sym, expiration, strike, right) → DataFrame
_NBBO_CACHE: dict[tuple, pd.DataFrame] = {}
_NBBO_HITS = 0
_NBBO_MISSES = 0


# ── Data containers ──────────────────────────────────────────────


@dataclass
class Entry:
    hhmm: str
    direction: str          # 'BULL' or 'BEAR'
    invalidation_level: Optional[float] = None
    invalidation_type: Optional[str] = None  # e.g. 'LOSE_VWAP', 'BREAK_OR_HIGH'
    note: str = ""


@dataclass
class TradeResult:
    setup: str
    day: str
    cross_hhmm: str          # signal time
    direction: str
    strike: float
    right: str               # 'C' or 'P'
    entry_hhmm: str
    entry_mid: float
    peak_mid: float
    peak_hhmm: str
    eod_mid: float
    mins_to_peak: int
    mfe_pct: float
    eod_pct: float
    # Exit-policy outcomes
    pol_tp50_s30: float
    pol_tp100_s30: float
    pol_tp50_und_inv: float   # underlying invalidation stop
    pol_tp50_ts5: float
    pol_tp50_ts10: float
    pol_tp50_ts30: float
    # MFE-by-minute-N
    mfe_min1: float
    mfe_min3: float
    mfe_min5: float
    mfe_min10: float
    # Day-type tags
    daytype: str = ""        # 'GAP_UP', 'GAP_DOWN', 'FLAT', etc
    vwap_slope_at_entry: float = 0.0
    inside_pdr: int = 0
    invalidation_level: float = 0.0
    invalidation_type: str = ""
    status: str = "OK"


# ── ThetaData NBBO ────────────────────────────────────────────────


def fetch_nbbo(symbol: str, expiration: str, strike: float, right: str,
               date: str) -> pd.DataFrame:
    global _NBBO_HITS, _NBBO_MISSES
    key = (date, symbol, expiration, strike, right)
    if key in _NBBO_CACHE:
        _NBBO_HITS += 1
        return _NBBO_CACHE[key]
    _NBBO_MISSES += 1
    params = {"symbol": symbol, "expiration": expiration,
              "strike": f"{strike:.3f}", "right": right,
              "start_date": date, "end_date": date, "interval": "1m"}
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote", params=params,
                         timeout=30)
        if r.status_code != 200:
            _NBBO_CACHE[key] = pd.DataFrame()
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        _NBBO_CACHE[key] = pd.DataFrame()
        return pd.DataFrame()
    if df.empty:
        _NBBO_CACHE[key] = df
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
    if df.empty:
        _NBBO_CACHE[key] = df
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df = df[["hhmm", "bid", "ask", "mid"]].reset_index(drop=True)
    _NBBO_CACHE[key] = df
    return df


# ── Bar helpers ───────────────────────────────────────────────────


def bars_5min_with_indicators(date: str) -> pd.DataFrame:
    """SPY 5-min bars with EMA8, EMA20, EMA50, VWAP, VWAP slope (1-bar delta)."""
    bars = get_minute_bars("SPY", date)
    if bars.empty:
        return pd.DataFrame()
    bars = bars.copy().reset_index(drop=True)
    for c in ("close", "high", "low", "open", "volume"):
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    bars["minute_dt"] = bars["minute"]
    b5 = bars.set_index("minute_dt").resample("5min", closed="right",
                                              label="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum"}).dropna().reset_index()
    b5["hhmm"] = b5["minute_dt"].dt.strftime("%H:%M")
    b5 = b5[(b5["hhmm"] >= "09:30") & (b5["hhmm"] <= "16:00")].reset_index(drop=True)
    if b5.empty:
        return b5
    b5["ema8"] = b5["close"].ewm(span=8, adjust=False).mean()
    b5["ema20"] = b5["close"].ewm(span=20, adjust=False).mean()
    b5["ema50"] = b5["close"].ewm(span=50, adjust=False).mean()
    # VWAP from session start
    b5["typ"] = (b5["high"] + b5["low"] + b5["close"]) / 3
    b5["vp"] = b5["typ"] * b5["volume"]
    b5["cum_vp"] = b5["vp"].cumsum()
    b5["cum_v"] = b5["volume"].cumsum()
    b5["vwap"] = b5["cum_vp"] / b5["cum_v"]
    # VWAP standard deviation bands
    b5["sq_dev"] = (b5["typ"] - b5["vwap"]) ** 2 * b5["volume"]
    b5["cum_sq_dev"] = b5["sq_dev"].cumsum()
    b5["vwap_var"] = b5["cum_sq_dev"] / b5["cum_v"]
    b5["vwap_std"] = np.sqrt(b5["vwap_var"])
    b5["vwap_p2s"] = b5["vwap"] + 2 * b5["vwap_std"]
    b5["vwap_m2s"] = b5["vwap"] - 2 * b5["vwap_std"]
    b5["vwap_p3s"] = b5["vwap"] + 3 * b5["vwap_std"]
    b5["vwap_m3s"] = b5["vwap"] - 3 * b5["vwap_std"]
    # VWAP slope per-bar
    b5["vwap_slope"] = b5["vwap"].diff()
    return b5


def bars_1min(date: str) -> pd.DataFrame:
    """SPY 1-min bars 09:30-16:00."""
    bars = get_minute_bars("SPY", date)
    if bars.empty:
        return pd.DataFrame()
    return bars.copy().reset_index(drop=True)


def get_premarket_high_low(date: str) -> tuple[float, float]:
    """Pre-market high/low from Databento 04:00-09:29 ET."""
    try:
        df = load_window("SPY", date, start_hhmm="04:00",
                         end_hhmm="09:29", actions=["T"])
        if df.empty:
            return (float("nan"), float("nan"))
        return (float(df["price"].max()), float(df["price"].min()))
    except Exception:
        return (float("nan"), float("nan"))


def get_prior_day_high_low(date: str) -> tuple[float, float]:
    """Previous trading day's RTH high/low."""
    try:
        # Find previous SPY trading day with data
        prev_date_dt = datetime.strptime(date, "%Y-%m-%d")
        for offset in range(1, 8):
            pd_dt = prev_date_dt - pd.Timedelta(days=offset)
            pd_str = pd_dt.strftime("%Y-%m-%d")
            bars = get_minute_bars("SPY", pd_str)
            if not bars.empty:
                return (float(bars["high"].max()), float(bars["low"].min()))
        return (float("nan"), float("nan"))
    except Exception:
        return (float("nan"), float("nan"))


def get_orb(b5: pd.DataFrame, minutes: int) -> tuple[float, float]:
    """Opening range high/low from 09:30 to 09:30+minutes."""
    end_h = 9
    end_m = 30 + minutes
    if end_m >= 60:
        end_h += end_m // 60
        end_m = end_m % 60
    end_str = f"{end_h:02d}:{end_m:02d}"
    sub = b5[b5["hhmm"] < end_str]
    if sub.empty:
        return (float("nan"), float("nan"))
    return (float(sub["high"].max()), float(sub["low"].min()))


def classify_daytype(b5: pd.DataFrame, pdh: float, pdl: float) -> str:
    """Gap up/down/flat + inside-PDR or breakout."""
    if b5.empty:
        return "UNKNOWN"
    open_px = float(b5.iloc[0]["open"])
    if not pd.isna(pdh) and not pd.isna(pdl):
        if open_px > pdh:
            return "GAP_UP"
        if open_px < pdl:
            return "GAP_DOWN"
    return "FLAT_OPEN"


# ── Signal generators ────────────────────────────────────────────


def sig_ema_cross_immediate(b1, b5, ctx) -> list[Entry]:
    """9/21 EMA cross on 5-min, enter at next bar (we use 8/20 as proxy
    since that's closer to retail standard and we already validated it)."""
    out = []
    if len(b5) < 5:
        return out
    b5 = b5.copy()
    b5["e8_above"] = b5["ema8"] > b5["ema20"]
    b5["prev_above"] = b5["e8_above"].shift(1)
    for i, r in b5.iterrows():
        if i < 4:
            continue
        if pd.isna(r["prev_above"]) or r["hhmm"] >= "15:30":
            continue
        if r["e8_above"] and not r["prev_above"]:
            out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                             invalidation_level=r["ema20"],
                             invalidation_type="LOSE_EMA20",
                             note="ema_cross_imm"))
        elif (not r["e8_above"]) and r["prev_above"]:
            out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                             invalidation_level=r["ema20"],
                             invalidation_type="LOSE_EMA20",
                             note="ema_cross_imm"))
    return out


def sig_ema_cross_pullback(b1, b5, ctx) -> list[Entry]:
    """Cross + wait for pullback to 9 EMA before entering."""
    out = []
    if len(b5) < 8:
        return out
    b5 = b5.copy()
    b5["e8_above"] = b5["ema8"] > b5["ema20"]
    b5["prev_above"] = b5["e8_above"].shift(1)
    pending: Optional[tuple] = None  # (cross_idx, direction)
    for i, r in b5.iterrows():
        if i < 4 or r["hhmm"] >= "15:30":
            continue
        if pd.isna(r["prev_above"]):
            continue
        # Detect new cross
        if r["e8_above"] and not r["prev_above"]:
            pending = (i, "BULL")
            continue
        if not r["e8_above"] and r["prev_above"]:
            pending = (i, "BEAR")
            continue
        # If pending, wait for pullback
        if pending is None:
            continue
        idx, direction = pending
        # Pullback: price tags 9 EMA without losing 21 EMA
        if direction == "BULL":
            if r["low"] <= r["ema8"] and r["close"] > r["ema20"]:
                out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                                 invalidation_level=r["ema20"],
                                 invalidation_type="LOSE_EMA20",
                                 note="ema_pullback"))
                pending = None
            elif r["close"] < r["ema20"]:
                pending = None  # cross invalidated
        else:
            if r["high"] >= r["ema8"] and r["close"] < r["ema20"]:
                out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                                 invalidation_level=r["ema20"],
                                 invalidation_type="GAIN_EMA20",
                                 note="ema_pullback"))
                pending = None
            elif r["close"] > r["ema20"]:
                pending = None
        # Limit to first 3 bars after cross
        if pending and (i - idx) >= 6:
            pending = None
    return out


def _orb_signal(b5, ctx, minutes: int, with_vwap=False) -> list[Entry]:
    out = []
    or_high, or_low = get_orb(b5, minutes)
    if pd.isna(or_high):
        return out
    end_h = 9
    end_m = 30 + minutes
    if end_m >= 60:
        end_h += end_m // 60
        end_m = end_m % 60
    end_str = f"{end_h:02d}:{end_m:02d}"
    fired_long = False
    fired_short = False
    for i, r in b5.iterrows():
        if r["hhmm"] < end_str or r["hhmm"] >= "15:00":
            continue
        if not fired_long and r["close"] > or_high:
            if not with_vwap or r["close"] > r["vwap"]:
                out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                                 invalidation_level=or_high,
                                 invalidation_type="LOSE_OR_HIGH",
                                 note=f"orb{minutes}_break"))
                fired_long = True
        if not fired_short and r["close"] < or_low:
            if not with_vwap or r["close"] < r["vwap"]:
                out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                                 invalidation_level=or_low,
                                 invalidation_type="GAIN_OR_LOW",
                                 note=f"orb{minutes}_break"))
                fired_short = True
        if fired_long and fired_short:
            break
    return out


def sig_orb5(b1, b5, ctx): return _orb_signal(b5, ctx, 5)
def sig_orb15(b1, b5, ctx): return _orb_signal(b5, ctx, 15)
def sig_orb30(b1, b5, ctx): return _orb_signal(b5, ctx, 30)
def sig_orb15_vwap(b1, b5, ctx): return _orb_signal(b5, ctx, 15, True)
def sig_orb30_vwap(b1, b5, ctx): return _orb_signal(b5, ctx, 30, True)


def sig_pmh_break(b1, b5, ctx) -> list[Entry]:
    out = []
    pmh = ctx.get("pmh")
    if pmh is None or pd.isna(pmh):
        return out
    for i, r in b5.iterrows():
        if r["hhmm"] < "09:30" or r["hhmm"] >= "12:00":
            continue
        if r["close"] > pmh and (i == 0 or b5.iloc[i-1]["close"] <= pmh):
            out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                             invalidation_level=pmh,
                             invalidation_type="LOSE_PMH",
                             note="pmh_break"))
            break
    return out


def sig_pml_break(b1, b5, ctx) -> list[Entry]:
    out = []
    pml = ctx.get("pml")
    if pml is None or pd.isna(pml):
        return out
    for i, r in b5.iterrows():
        if r["hhmm"] < "09:30" or r["hhmm"] >= "12:00":
            continue
        if r["close"] < pml and (i == 0 or b5.iloc[i-1]["close"] >= pml):
            out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                             invalidation_level=pml,
                             invalidation_type="GAIN_PML",
                             note="pml_break"))
            break
    return out


def sig_vwap_reclaim(b1, b5, ctx) -> list[Entry]:
    """First close above VWAP after being below for at least 3 bars."""
    out = []
    if len(b5) < 5:
        return out
    below_count = 0
    fired = False
    for i, r in b5.iterrows():
        if r["hhmm"] >= "15:00":
            break
        if r["close"] < r["vwap"]:
            below_count += 1
        elif below_count >= 3 and r["close"] > r["vwap"] and not fired:
            out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                             invalidation_level=r["vwap"],
                             invalidation_type="LOSE_VWAP",
                             note="vwap_reclaim"))
            fired = True
            below_count = 0
        else:
            below_count = 0
    return out


def sig_vwap_lose(b1, b5, ctx) -> list[Entry]:
    """First close below VWAP after being above for at least 3 bars."""
    out = []
    if len(b5) < 5:
        return out
    above_count = 0
    fired = False
    for i, r in b5.iterrows():
        if r["hhmm"] >= "15:00":
            break
        if r["close"] > r["vwap"]:
            above_count += 1
        elif above_count >= 3 and r["close"] < r["vwap"] and not fired:
            out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                             invalidation_level=r["vwap"],
                             invalidation_type="GAIN_VWAP",
                             note="vwap_lose"))
            fired = True
            above_count = 0
        else:
            above_count = 0
    return out


def sig_vwap_2sd_fade(b1, b5, ctx) -> list[Entry]:
    """Fade VWAP +/- 2σ extensions back to VWAP. Limit 1 per side."""
    out = []
    fired_up = fired_dn = False
    for i, r in b5.iterrows():
        if r["hhmm"] < "10:00" or r["hhmm"] >= "15:00":
            continue
        if not fired_up and r["high"] >= r["vwap_p2s"] and r["close"] < r["vwap_p2s"]:
            out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                             invalidation_level=r["vwap_p3s"],
                             invalidation_type="GAIN_VWAP_P3S",
                             note="vwap_2sd_fade_up"))
            fired_up = True
        if not fired_dn and r["low"] <= r["vwap_m2s"] and r["close"] > r["vwap_m2s"]:
            out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                             invalidation_level=r["vwap_m3s"],
                             invalidation_type="LOSE_VWAP_M3S",
                             note="vwap_2sd_fade_dn"))
            fired_dn = True
    return out


def sig_failed_pmh_break(b1, b5, ctx) -> list[Entry]:
    """Price breaks PMH then closes back below within 6 bars."""
    out = []
    pmh = ctx.get("pmh")
    if pmh is None or pd.isna(pmh):
        return out
    broke_idx = None
    for i, r in b5.iterrows():
        if r["hhmm"] >= "12:00":
            break
        if broke_idx is None and r["close"] > pmh:
            broke_idx = i
            continue
        if broke_idx is not None:
            if r["close"] < pmh:
                out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                                 invalidation_level=pmh,
                                 invalidation_type="GAIN_PMH",
                                 note="failed_pmh"))
                break
            if i - broke_idx >= 6:
                broke_idx = None
    return out


def sig_failed_pml_break(b1, b5, ctx) -> list[Entry]:
    out = []
    pml = ctx.get("pml")
    if pml is None or pd.isna(pml):
        return out
    broke_idx = None
    for i, r in b5.iterrows():
        if r["hhmm"] >= "12:00":
            break
        if broke_idx is None and r["close"] < pml:
            broke_idx = i
            continue
        if broke_idx is not None:
            if r["close"] > pml:
                out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                                 invalidation_level=pml,
                                 invalidation_type="LOSE_PML",
                                 note="failed_pml"))
                break
            if i - broke_idx >= 6:
                broke_idx = None
    return out


def sig_failed_pdh_break(b1, b5, ctx) -> list[Entry]:
    out = []
    pdh = ctx.get("pdh")
    if pdh is None or pd.isna(pdh):
        return out
    broke_idx = None
    for i, r in b5.iterrows():
        if r["hhmm"] >= "14:00":
            break
        if broke_idx is None and r["close"] > pdh:
            broke_idx = i
            continue
        if broke_idx is not None:
            if r["close"] < pdh:
                out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                                 invalidation_level=pdh,
                                 invalidation_type="GAIN_PDH",
                                 note="failed_pdh"))
                break
            if i - broke_idx >= 6:
                broke_idx = None
    return out


def sig_failed_pdl_break(b1, b5, ctx) -> list[Entry]:
    out = []
    pdl = ctx.get("pdl")
    if pdl is None or pd.isna(pdl):
        return out
    broke_idx = None
    for i, r in b5.iterrows():
        if r["hhmm"] >= "14:00":
            break
        if broke_idx is None and r["close"] < pdl:
            broke_idx = i
            continue
        if broke_idx is not None:
            if r["close"] > pdl:
                out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                                 invalidation_level=pdl,
                                 invalidation_type="LOSE_PDL",
                                 note="failed_pdl"))
                break
            if i - broke_idx >= 6:
                broke_idx = None
    return out


def sig_sweep_pmh_reclaim(b1, b5, ctx) -> list[Entry]:
    """Gemini's specific: PMH/PML sweep + reclaim 9:30-10:30."""
    out = []
    pmh = ctx.get("pmh")
    if pmh is None or pd.isna(pmh):
        return out
    swept = False
    for i, r in b5.iterrows():
        if r["hhmm"] < "09:30" or r["hhmm"] > "10:30":
            continue
        if not swept and r["high"] > pmh and r["close"] < pmh:
            swept = True
            continue
        if swept and r["close"] < pmh:
            out.append(Entry(hhmm=r["hhmm"], direction="BEAR",
                             invalidation_level=pmh,
                             invalidation_type="GAIN_PMH",
                             note="sweep_pmh"))
            break
    return out


def sig_sweep_pml_reclaim(b1, b5, ctx) -> list[Entry]:
    out = []
    pml = ctx.get("pml")
    if pml is None or pd.isna(pml):
        return out
    swept = False
    for i, r in b5.iterrows():
        if r["hhmm"] < "09:30" or r["hhmm"] > "10:30":
            continue
        if not swept and r["low"] < pml and r["close"] > pml:
            swept = True
            continue
        if swept and r["close"] > pml:
            out.append(Entry(hhmm=r["hhmm"], direction="BULL",
                             invalidation_level=pml,
                             invalidation_type="LOSE_PML",
                             note="sweep_pml"))
            break
    return out


SETUPS: dict[str, Callable] = {
    "ema_cross_imm": sig_ema_cross_immediate,
    "ema_cross_pullback": sig_ema_cross_pullback,
    "orb5_break": sig_orb5,
    "orb15_break": sig_orb15,
    "orb30_break": sig_orb30,
    "orb15_break_vwap": sig_orb15_vwap,
    "orb30_break_vwap": sig_orb30_vwap,
    "pmh_break": sig_pmh_break,
    "pml_break": sig_pml_break,
    "vwap_reclaim": sig_vwap_reclaim,
    "vwap_lose": sig_vwap_lose,
    "vwap_2sd_fade": sig_vwap_2sd_fade,
    "failed_pmh_break": sig_failed_pmh_break,
    "failed_pml_break": sig_failed_pml_break,
    "failed_pdh_break": sig_failed_pdh_break,
    "failed_pdl_break": sig_failed_pdl_break,
    "sweep_pmh": sig_sweep_pmh_reclaim,
    "sweep_pml": sig_sweep_pml_reclaim,
}


# ── Trade simulation ─────────────────────────────────────────────


def simulate_trade(date: str, setup_name: str, entry: Entry,
                   b1: pd.DataFrame, b5: pd.DataFrame,
                   daytype: str, vwap_slope: float,
                   inside_pdr: int) -> Optional[TradeResult]:
    """Compute MFE/EOD via NBBO + apply 6 exit policies."""
    # Find SPY price at signal close to pick ATM strike
    spy_at_signal = b5[b5["hhmm"] == entry.hhmm]
    if spy_at_signal.empty:
        return None
    spy_close = float(spy_at_signal.iloc[0]["close"])
    strike = float(round(spy_close))
    right = "C" if entry.direction == "BULL" else "P"

    nbbo = fetch_nbbo("SPY", date, strike, right, date)
    if nbbo.empty:
        return None

    # Entry at first NBBO bar at signal hhmm + 1 min
    h, m = entry.hhmm.split(":")
    next_min = int(h) * 60 + int(m) + 1
    entry_str = f"{next_min // 60:02d}:{next_min % 60:02d}"
    entry_rows = nbbo[nbbo["hhmm"] >= entry_str]
    if entry_rows.empty:
        return None
    e_row = entry_rows.iloc[0]
    cost = float(e_row["mid"])
    if cost <= 0:
        return None
    sub = nbbo[nbbo["hhmm"] >= e_row["hhmm"]].reset_index(drop=True)
    if sub.empty:
        return None
    sub["minute_idx"] = range(len(sub))
    peak_idx = sub["mid"].idxmax()
    peak = sub.iloc[peak_idx]
    eod = sub.iloc[-1]
    mfe_pct = (float(peak["mid"]) - cost) / cost * 100
    eod_pct = (float(eod["mid"]) - cost) / cost * 100

    def mfe_at(n):
        early = sub[sub["minute_idx"] <= n]
        if early.empty:
            return None
        return (early["mid"].max() - cost) / cost * 100

    # Underlying invalidation timing
    inv_pnl = None
    if entry.invalidation_level is not None:
        # Find first 5-min bar after entry where invalidation triggers
        e_idx_b5 = b5[b5["hhmm"] >= entry.hhmm].index
        for j in e_idx_b5[1:]:  # skip entry bar
            r5 = b5.iloc[j]
            triggered = False
            if entry.direction == "BULL":
                if r5["close"] < entry.invalidation_level:
                    triggered = True
            else:
                if r5["close"] > entry.invalidation_level:
                    triggered = True
            if triggered:
                # Find NBBO mid at that 5-min bar's hhmm
                exit_rows = nbbo[nbbo["hhmm"] >= r5["hhmm"]]
                if not exit_rows.empty:
                    inv_exit_mid = float(exit_rows.iloc[0]["mid"])
                    inv_pnl = (inv_exit_mid - cost) / cost * 100
                break

    # Exit policies
    def policy_tp_stop(tp_pct, stop_pct):
        if mfe_pct >= tp_pct:
            return tp_pct
        if eod_pct <= stop_pct:
            return stop_pct
        return eod_pct

    def policy_tp_underlying(tp_pct):
        if mfe_pct >= tp_pct:
            return tp_pct
        if inv_pnl is not None:
            return inv_pnl
        return eod_pct

    def policy_tp_timestop(tp_pct, ts_min):
        if mfe_pct >= tp_pct:
            # Check if TP hit before time-stop
            mt = sub[sub["mid"] >= cost * (1 + tp_pct / 100)]
            if not mt.empty and int(mt.iloc[0]["minute_idx"]) <= ts_min:
                return tp_pct
        # Time-stop exit at minute ts_min
        ts_rows = sub[sub["minute_idx"] >= ts_min]
        if ts_rows.empty:
            return eod_pct
        ts_exit = float(ts_rows.iloc[0]["mid"])
        return (ts_exit - cost) / cost * 100

    return TradeResult(
        setup=setup_name, day=date, cross_hhmm=entry.hhmm,
        direction=entry.direction, strike=strike, right=right,
        entry_hhmm=str(e_row["hhmm"]), entry_mid=cost,
        peak_mid=float(peak["mid"]), peak_hhmm=str(peak["hhmm"]),
        eod_mid=float(eod["mid"]), mins_to_peak=int(peak["minute_idx"]),
        mfe_pct=round(mfe_pct, 2), eod_pct=round(eod_pct, 2),
        pol_tp50_s30=round(policy_tp_stop(50, -30), 2),
        pol_tp100_s30=round(policy_tp_stop(100, -30), 2),
        pol_tp50_und_inv=round(policy_tp_underlying(50), 2),
        pol_tp50_ts5=round(policy_tp_timestop(50, 5), 2),
        pol_tp50_ts10=round(policy_tp_timestop(50, 10), 2),
        pol_tp50_ts30=round(policy_tp_timestop(50, 30), 2),
        mfe_min1=round(mfe_at(1) or 0, 2),
        mfe_min3=round(mfe_at(3) or 0, 2),
        mfe_min5=round(mfe_at(5) or 0, 2),
        mfe_min10=round(mfe_at(10) or 0, 2),
        daytype=daytype, vwap_slope_at_entry=round(vwap_slope, 4),
        inside_pdr=inside_pdr,
        invalidation_level=entry.invalidation_level or 0.0,
        invalidation_type=entry.invalidation_type or "",
    )


# ── Schema + DB persistence ──────────────────────────────────────


SCHEMA = """
CREATE TABLE IF NOT EXISTS unified_trades (
  setup TEXT, day TEXT, cross_hhmm TEXT,
  direction TEXT, strike REAL, right TEXT,
  entry_hhmm TEXT, entry_mid REAL,
  peak_mid REAL, peak_hhmm TEXT, eod_mid REAL, mins_to_peak INTEGER,
  mfe_pct REAL, eod_pct REAL,
  pol_tp50_s30 REAL, pol_tp100_s30 REAL, pol_tp50_und_inv REAL,
  pol_tp50_ts5 REAL, pol_tp50_ts10 REAL, pol_tp50_ts30 REAL,
  mfe_min1 REAL, mfe_min3 REAL, mfe_min5 REAL, mfe_min10 REAL,
  daytype TEXT, vwap_slope_at_entry REAL, inside_pdr INTEGER,
  invalidation_level REAL, invalidation_type TEXT, status TEXT,
  PRIMARY KEY (setup, day, cross_hhmm)
);
CREATE INDEX IF NOT EXISTS idx_unified_setup ON unified_trades(setup);
CREATE INDEX IF NOT EXISTS idx_unified_day ON unified_trades(day);
"""


def save_trade(conn, t: TradeResult):
    conn.execute(
        """INSERT OR REPLACE INTO unified_trades VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )""",
        (t.setup, t.day, t.cross_hhmm, t.direction, t.strike, t.right,
         t.entry_hhmm, t.entry_mid, t.peak_mid, t.peak_hhmm, t.eod_mid,
         t.mins_to_peak, t.mfe_pct, t.eod_pct,
         t.pol_tp50_s30, t.pol_tp100_s30, t.pol_tp50_und_inv,
         t.pol_tp50_ts5, t.pol_tp50_ts10, t.pol_tp50_ts30,
         t.mfe_min1, t.mfe_min3, t.mfe_min5, t.mfe_min10,
         t.daytype, t.vwap_slope_at_entry, t.inside_pdr,
         t.invalidation_level, t.invalidation_type, t.status))
    conn.commit()


# ── Main runner ──────────────────────────────────────────────────


def main(setups_to_run: Optional[list[str]] = None,
         start_idx: int = 0, end_idx: int = 999) -> int:
    setups_to_run = setups_to_run or list(SETUPS.keys())
    print(f"[unified] running {len(setups_to_run)} setups: {setups_to_run}",
          flush=True)
    status = cache_status()
    spy_days = sorted(status[status["ticker"] == "SPY"]["date"].unique())
    spy_days = spy_days[start_idx:end_idx]
    print(f"[unified] {len(spy_days)} days to process "
          f"({spy_days[0]} to {spy_days[-1]})", flush=True)

    conn = sqlite3.connect(OUT_DB)
    conn.executescript(SCHEMA)

    n_trades = 0
    for di, day in enumerate(spy_days):
        b1 = bars_1min(day)
        b5 = bars_5min_with_indicators(day)
        if b5.empty:
            print(f"  [{di+1}/{len(spy_days)}] {day}: no bars", flush=True)
            continue
        pmh, pml = get_premarket_high_low(day)
        pdh, pdl = get_prior_day_high_low(day)
        ctx = {"pmh": pmh, "pml": pml, "pdh": pdh, "pdl": pdl}
        daytype = classify_daytype(b5, pdh, pdl)
        # VWAP slope at midday (12:00 ET) as proxy for trend strength
        midday = b5[b5["hhmm"] == "12:00"]
        slope = float(midday.iloc[0]["vwap_slope"]) if not midday.empty else 0.0
        # inside-PDR flag
        inside_pdr = 0
        if not pd.isna(pdh) and not pd.isna(pdl):
            day_high = b5["high"].max()
            day_low = b5["low"].min()
            if day_high <= pdh and day_low >= pdl:
                inside_pdr = 1

        day_n = 0
        for setup_name in setups_to_run:
            sig_fn = SETUPS[setup_name]
            try:
                entries = sig_fn(b1, b5, ctx)
            except Exception as e:
                print(f"  ! signal {setup_name} failed: {type(e).__name__}: {e}",
                      flush=True)
                continue
            for entry in entries:
                t = simulate_trade(day, setup_name, entry, b1, b5,
                                   daytype, slope, inside_pdr)
                if t is None:
                    continue
                save_trade(conn, t)
                day_n += 1
                n_trades += 1
        print(f"  [{di+1}/{len(spy_days)}] {day} type={daytype} "
              f"trades={day_n} (cum={n_trades}) NBBO_cache:"
              f"{_NBBO_HITS}h/{_NBBO_MISSES}m", flush=True)

    conn.close()
    print(f"[unified] done. {n_trades} trades total. "
          f"NBBO cache: {_NBBO_HITS} hits / {_NBBO_MISSES} misses", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
