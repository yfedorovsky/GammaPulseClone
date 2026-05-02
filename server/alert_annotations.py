"""Alert annotation features — May 2 2026 Tier-2 ship.

Annotation-only metrics that get computed at alert fire time (or
backfilled retroactively) for diagnostic / future-classifier purposes.
Per cross-LLM round 5 consensus (Gemini + OpenAI deep research),
these features address the "feasibility layer" gap in the current
stack — measuring whether a strike can plausibly get paid before
theta/spread kill it, and characterizing day-state context.

CRITICAL: these features are LOGGING ONLY. They MUST NOT be used
to filter, gate, or modify alert dispatch behavior during the forward
window. Per FALSIFICATION_PROTOCOL.md, production logic is frozen
until Stage 3 stopping. Future analyses will validate which features
have predictive power once we have ≥50 forward alerts × ≥20 day
clusters.

## Feature catalog

**Strike feasibility group**:
- `realized_vol_20d_pct`: trailing-20-day realized vol from minute
  bars (Databento for SPY/QQQ, yfinance for IWM/SPX). Annualized.
- `expected_move_pct_to_eod`: σ × √(time_remaining / 365)
- `strike_distance_pct`: |strike − spot| / spot
- `strike_reachability_ratio`: expected_move_pct / strike_distance_pct.
  >1.0 = strike inside 1σ expected move. <1.0 = beyond.
- `minutes_to_expiry`: minutes from fire-time to 16:00 ET

**Day-state group** (the OpenAI causal-features set):
- `open_to_spot_pct`: net move from session open at fire time
- `path_efficiency`: |close - open| / sum(|bar_returns|) — separates
  trend (high) from chop (low)
- `open_cross_count`: number of times price crossed opening price
  by fire time (rotational sessions cross multiple times; trend
  sessions never cross)
- `directional_change_count`: count of alternating moves above a
  vol-scaled threshold (event-based regime summary)
- `jump_share`: max(realized_var − bipower_var, 0) / realized_var.
  Separates jump/event days from smooth continuous trend/rotation.

**Episode tagging** (the OpenAI methodological repair):
- `episode_id`: same ticker + same direction + no >45min gap = 1
  episode. Prevents pseudo-replication when a single regime produces
  multiple alerts.

## What we explicitly are NOT computing (yet)

Per OpenAI's data-quality argument: vanna/charm/dealer-positioning
proxies require fragile estimates from sparse data. Not adding them
to avoid false precision. Future work after Stage 3 with cleaner
chain greeks may add them.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Feature thresholds (pre-committed) ──────────────────────────────

# Annualization basis for vol calcs (252 trading days * 6.5 hours)
TRADING_DAYS_PER_YEAR = 252

# Window for realized vol estimation
REALIZED_VOL_WINDOW_DAYS = 20

# Episode definition: same ticker + direction + no gap > this = same episode
EPISODE_GAP_MAX_MIN = 45

# For directional-change counter: vol-scaled threshold
DIRECTIONAL_CHANGE_SIGMA = 0.5  # 0.5 sigma move triggers a "change"

# Default fallback vols when we can't compute realized (per ticker)
DEFAULT_VOL = {
    "SPY": 0.18, "QQQ": 0.22, "IWM": 0.24, "SPX": 0.18,
}


# ── Database schema migration ──────────────────────────────────────

ALERT_ANNOTATION_MIGRATIONS = [
    # Strike feasibility
    "ALTER TABLE zero_dte_alerts ADD COLUMN realized_vol_20d_pct REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN expected_move_pct_to_eod REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN strike_distance_pct REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN strike_reachability_ratio REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN minutes_to_expiry INTEGER",
    # Day-state
    "ALTER TABLE zero_dte_alerts ADD COLUMN open_to_spot_pct REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN path_efficiency REAL",
    "ALTER TABLE zero_dte_alerts ADD COLUMN open_cross_count INTEGER",
    "ALTER TABLE zero_dte_alerts ADD COLUMN directional_change_count INTEGER",
    "ALTER TABLE zero_dte_alerts ADD COLUMN jump_share REAL",
    # Episode tagging
    "ALTER TABLE zero_dte_alerts ADD COLUMN episode_id TEXT",
    # Tape regime tag at fire time (already classified elsewhere; persist here)
    "ALTER TABLE zero_dte_alerts ADD COLUMN tape_regime_at_fire TEXT",
    # Cross-ticker alignment (May 2 evening — OpenAI recommendation)
    "ALTER TABLE zero_dte_alerts ADD COLUMN cross_ticker_aligned INTEGER",
    "ALTER TABLE zero_dte_alerts ADD COLUMN cross_ticker_corr_30m REAL",
    # Macro event window (hardcoded FOMC/CPI/NFP calendar)
    "ALTER TABLE zero_dte_alerts ADD COLUMN in_macro_window INTEGER",
    "ALTER TABLE zero_dte_alerts ADD COLUMN macro_event_label TEXT",
]


def apply_migrations(db_path: str = "zero_dte_alerts.db") -> int:
    """Apply ADD COLUMN migrations idempotently."""
    conn = sqlite3.connect(db_path)
    n = 0
    for stmt in ALERT_ANNOTATION_MIGRATIONS:
        try:
            conn.execute(stmt)
            n += 1
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()
    return n


# ── Minute-bar loaders (Databento + yfinance) ──────────────────────

_BARS_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


# ── Macro-event calendar (hardcoded — replace with API later) ──────

# 2026 macro events (conservative — only well-known ones, avoid false
# positives that contaminate the analysis). Dates are ET.
# Format: "YYYY-MM-DD HH:MM" → label
MACRO_EVENTS: dict[str, str] = {
    # FOMC announcements (typically 14:00 ET)
    "2026-01-28 14:00": "FOMC",
    "2026-03-18 14:00": "FOMC",
    "2026-04-29 14:00": "FOMC",
    "2026-06-17 14:00": "FOMC",
    "2026-07-29 14:00": "FOMC",
    "2026-09-16 14:00": "FOMC",
    "2026-11-04 14:00": "FOMC",
    "2026-12-09 14:00": "FOMC",
    # CPI releases (typically 08:30 ET — pre-market but affects open)
    "2026-01-13 08:30": "CPI",
    "2026-02-11 08:30": "CPI",
    "2026-03-12 08:30": "CPI",
    "2026-04-10 08:30": "CPI",
    "2026-05-13 08:30": "CPI",
    "2026-06-10 08:30": "CPI",
    "2026-07-15 08:30": "CPI",
    "2026-08-12 08:30": "CPI",
    "2026-09-10 08:30": "CPI",
    "2026-10-15 08:30": "CPI",
    "2026-11-12 08:30": "CPI",
    "2026-12-10 08:30": "CPI",
    # NFP releases (typically first Friday at 08:30 ET)
    "2026-01-09 08:30": "NFP",
    "2026-02-06 08:30": "NFP",
    "2026-03-06 08:30": "NFP",
    "2026-04-03 08:30": "NFP",
    "2026-05-01 08:30": "NFP",  # ← May 1 NFP! that explains the chase
    "2026-06-05 08:30": "NFP",
    "2026-07-02 08:30": "NFP",  # July 4th week shifts
    "2026-08-07 08:30": "NFP",
    "2026-09-04 08:30": "NFP",
    "2026-10-02 08:30": "NFP",
    "2026-11-06 08:30": "NFP",
    "2026-12-04 08:30": "NFP",
}

# Window around a macro event during which an alert is "in the macro
# window". Pre-event = 30 min before (positioning); post-event = 90 min
# after (volatility absorption).
MACRO_PRE_EVENT_MIN = 30
MACRO_POST_EVENT_MIN = 90


def macro_event_at(fire_ts: int) -> tuple[bool, str | None]:
    """Returns (in_window, event_label_or_None) for a given fire timestamp."""
    fire_dt = datetime.fromtimestamp(fire_ts)
    fire_iso = fire_dt.strftime("%Y-%m-%d %H:%M")
    fire_day = fire_dt.strftime("%Y-%m-%d")
    for event_iso, label in MACRO_EVENTS.items():
        # Same-day events only (skip cross-day comparisons)
        if not event_iso.startswith(fire_day):
            continue
        try:
            event_dt = datetime.strptime(event_iso, "%Y-%m-%d %H:%M")
            delta_min = (fire_dt - event_dt).total_seconds() / 60
            if -MACRO_PRE_EVENT_MIN <= delta_min <= MACRO_POST_EVENT_MIN:
                return True, label
        except ValueError:
            continue
    return False, None


def cross_ticker_alignment(
    primary_ticker: str, day: str, fire_ts: int,
    primary_open_to_spot_pct: float | None,
) -> tuple[int | None, float | None]:
    """For SPY/QQQ alerts, check if the OTHER index is moving in the
    same direction by similar magnitude. Returns:
      (aligned_int, correlation_30m) where aligned_int is 1/0/None.

    Aligned = both on same side of open AND magnitudes within 0.4pp
    of each other AND 30-min log-return correlation > 0.5.

    NOTE: `primary_open_to_spot_pct` is a percentage value (e.g. 0.19
    for +0.19% from open), matching the storage convention in
    `compute_day_state_features`.
    """
    if primary_ticker not in ("SPY", "QQQ") or primary_open_to_spot_pct is None:
        return None, None
    other = "QQQ" if primary_ticker == "SPY" else "SPY"
    other_bars = get_minute_bars(other, day)
    if other_bars.empty:
        return None, None

    other_sub = other_bars[other_bars["minute"].astype("int64") // 10**9 <= fire_ts].copy()
    if other_sub.empty or len(other_sub) < 10:
        return None, None

    other_open = float(other_sub.iloc[0]["open"])
    other_spot = float(other_sub.iloc[-1]["close"])
    # other_otp computed as percentage (matching the primary's units)
    other_otp_pct = ((other_spot - other_open) / other_open * 100
                     if other_open > 0 else 0)
    primary_otp_pct = primary_open_to_spot_pct  # already in %

    # 30-min trailing correlation
    prim_bars = get_minute_bars(primary_ticker, day)
    prim_sub = prim_bars[prim_bars["minute"].astype("int64") // 10**9 <= fire_ts].copy()
    fast_cutoff = fire_ts - 30 * 60
    other_30m = other_sub[other_sub["minute"].astype("int64") // 10**9 >= fast_cutoff]
    prim_30m = prim_sub[prim_sub["minute"].astype("int64") // 10**9 >= fast_cutoff]
    corr = None
    if len(other_30m) >= 5 and len(prim_30m) >= 5:
        # Align on minute and compute log-return correlation
        other_30m = other_30m.set_index("minute")["close"]
        prim_30m = prim_30m.set_index("minute")["close"]
        merged = pd.concat({"prim": prim_30m, "other": other_30m},
                           axis=1).dropna()
        if len(merged) >= 5:
            prim_ret = merged["prim"].pct_change().dropna()
            other_ret = merged["other"].pct_change().dropna()
            if len(prim_ret) >= 4 and prim_ret.std() > 0 and other_ret.std() > 0:
                corr = float(prim_ret.corr(other_ret))

    # Aligned if same side of open AND |magnitudes| within 0.4pp of each
    # other (rough proxy for "no major divergence"). All in percent.
    same_side = (primary_otp_pct > 0) == (other_otp_pct > 0)
    mag_close = abs(abs(primary_otp_pct) - abs(other_otp_pct)) < 0.4  # 0.4pp
    high_corr = corr is not None and corr > 0.5
    aligned = 1 if (same_side and mag_close and high_corr) else 0

    return aligned, round(corr, 3) if corr is not None else None


def get_minute_bars(ticker: str, day: str) -> pd.DataFrame:
    """Per-minute OHLC bars for (ticker, day). Databento for SPY/QQQ;
    yfinance fallback for others. Cached. Empty DF if no data.

    For SPX (no intraday source available), use SPY as proxy — they
    move in near-lockstep at ~10:1 ratio, and the tape-regime features
    we derive are direction/path-shape-based rather than absolute-price-
    based, so SPY's tape character is a faithful proxy for SPX's."""
    key = (ticker, day)
    if key in _BARS_CACHE:
        return _BARS_CACHE[key]
    bars = pd.DataFrame()

    # SPX → use SPY data as proxy (they move 10:1 in lockstep)
    if ticker in ("SPX", "SPXW"):
        bars = get_minute_bars("SPY", day)
        _BARS_CACHE[key] = bars
        return bars

    # Databento path (SPY/QQQ)
    if ticker in ("SPY", "QQQ"):
        try:
            from scripts.databento_loader import load_window
            df = load_window(ticker, day, start_hhmm="09:30",
                             end_hhmm="16:00", actions=["T"])
            if not df.empty:
                df["t"] = pd.to_datetime(df["ts_event"], utc=True) \
                    .dt.tz_convert("America/New_York")
                df["minute"] = df["t"].dt.floor("min")
                g = df.groupby("minute").agg(
                    open=("price", "first"), high=("price", "max"),
                    low=("price", "min"), close=("price", "last"),
                    volume=("size", "sum"),
                ).reset_index()
                g["hhmm"] = g["minute"].dt.strftime("%H:%M")
                bars = g
        except Exception:
            pass

    # yfinance fallback (only works for ~30 most recent days for 1m)
    if bars.empty:
        try:
            import yfinance as yf
            d = datetime.fromisoformat(day)
            start = d.strftime("%Y-%m-%d")
            end = (d + timedelta(days=2)).strftime("%Y-%m-%d")
            df = yf.download(ticker, start=start, end=end, interval="1m",
                             progress=False, prepost=False, auto_adjust=False,
                             threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty:
                df = df.reset_index()
                ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
                df["t"] = pd.to_datetime(df[ts_col], utc=True) \
                    .dt.tz_convert("America/New_York")
                df = df[df["t"].dt.strftime("%Y-%m-%d") == day].copy()
                df["minute"] = df["t"]
                bars = df.rename(columns={
                    "Open": "open", "High": "high", "Low": "low",
                    "Close": "close", "Volume": "volume",
                })[["minute", "open", "high", "low", "close", "volume"]]
                bars["hhmm"] = bars["minute"].dt.strftime("%H:%M")
                bars = bars[(bars["hhmm"] >= "09:30") &
                            (bars["hhmm"] < "16:00")].copy()
        except Exception:
            pass

    _BARS_CACHE[key] = bars
    return bars


def get_realized_vol_20d(ticker: str, end_day: str) -> float | None:
    """Compute trailing 20-day realized vol from daily close-to-close
    log returns. Annualized. Returns None on insufficient data."""
    try:
        import yfinance as yf
        end_d = datetime.fromisoformat(end_day)
        start_d = end_d - timedelta(days=45)
        df = yf.download(ticker, start=start_d.strftime("%Y-%m-%d"),
                         end=end_d.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or len(df) < 5:
            return None
        closes = df["Close"].astype(float)
        logret = (closes / closes.shift(1)).apply(lambda x: math.log(x) if x > 0 else 0)
        sigma_daily = logret.tail(REALIZED_VOL_WINDOW_DAYS).std()
        if sigma_daily is None or pd.isna(sigma_daily):
            return None
        return float(sigma_daily * math.sqrt(TRADING_DAYS_PER_YEAR))
    except Exception:
        return None


# ── Day-state feature computation ──────────────────────────────────


def compute_day_state_features(bars: pd.DataFrame, fire_ts: int) -> dict:
    """Compute path-efficiency, open-cross count, directional changes,
    jump share from minute bars up to fire time."""
    if bars.empty:
        return {
            "open_to_spot_pct": None, "path_efficiency": None,
            "open_cross_count": None, "directional_change_count": None,
            "jump_share": None,
        }
    sub = bars[bars["minute"].astype("int64") // 10**9 <= fire_ts].copy()
    if sub.empty or len(sub) < 2:
        return {
            "open_to_spot_pct": None, "path_efficiency": None,
            "open_cross_count": None, "directional_change_count": None,
            "jump_share": None,
        }

    open_price = float(sub.iloc[0]["open"])
    spot = float(sub.iloc[-1]["close"])
    open_to_spot = (spot - open_price) / open_price if open_price > 0 else 0

    # Path efficiency: net distance / sum of bar returns
    bar_returns = sub["close"].diff().abs().dropna()
    total_path = float(bar_returns.sum())
    net_distance = abs(spot - open_price)
    path_eff = net_distance / total_path if total_path > 0 else 0

    # Open-cross count: number of bars where close transitions across open
    above_open = (sub["close"] > open_price).astype(int)
    crosses = (above_open.diff().abs() > 0).sum()
    open_cross_count = int(crosses)

    # Directional change count: alternating moves > sigma threshold
    log_returns = (sub["close"] / sub["close"].shift(1)).apply(
        lambda x: math.log(x) if x > 0 else 0
    ).dropna()
    if len(log_returns) > 5:
        sigma = log_returns.std()
        threshold = DIRECTIONAL_CHANGE_SIGMA * sigma
        signs = log_returns.apply(
            lambda x: 1 if x > threshold else (-1 if x < -threshold else 0)
        )
        nonzero_signs = signs[signs != 0]
        if len(nonzero_signs) > 1:
            dir_changes = int((nonzero_signs.diff().abs() > 0).sum())
        else:
            dir_changes = 0
    else:
        dir_changes = 0

    # Jump share: realized variance vs bipower variation
    # RV = sum(r²); BV = (π/2) × sum(|r_t| × |r_{t-1}|)
    if len(log_returns) > 10:
        rv = float((log_returns ** 2).sum())
        abs_returns = log_returns.abs()
        bv_terms = abs_returns.iloc[1:].values * abs_returns.iloc[:-1].values
        bv = float((math.pi / 2) * bv_terms.sum())
        jump_share = max(rv - bv, 0) / rv if rv > 0 else 0
    else:
        jump_share = None

    return {
        "open_to_spot_pct": round(open_to_spot * 100, 4),
        "path_efficiency": round(path_eff, 4) if path_eff else None,
        "open_cross_count": open_cross_count,
        "directional_change_count": dir_changes,
        "jump_share": round(jump_share, 4) if jump_share is not None else None,
    }


# ── Strike feasibility ────────────────────────────────────────────


def compute_feasibility(
    ticker: str, day: str, fire_ts: int,
    spot: float, strike: float, direction: str,
) -> dict:
    """Reachability metric: ratio of expected EOD move to strike distance."""
    fire_dt = datetime.fromtimestamp(fire_ts)
    eod_dt = fire_dt.replace(hour=16, minute=0, second=0, microsecond=0)
    minutes_to_expiry = max(int((eod_dt - fire_dt).total_seconds() / 60), 1)

    # Realized vol (annualized) — fall back to default if unavailable
    rv_20d = get_realized_vol_20d(ticker, day)
    if rv_20d is None or rv_20d <= 0:
        rv_20d = DEFAULT_VOL.get(ticker, 0.20)

    # Expected move from now to EOD (in % terms)
    # σ × √(time_remaining / 365 trading-day-equivalents)
    # minutes_to_expiry / (252 × 6.5 × 60) gives fraction of trading year
    time_frac_year = minutes_to_expiry / (TRADING_DAYS_PER_YEAR * 6.5 * 60)
    expected_move_pct = rv_20d * math.sqrt(time_frac_year)

    # Strike distance %
    strike_dist_pct = abs(strike - spot) / spot if spot > 0 else None
    if strike_dist_pct is None or strike_dist_pct <= 0:
        reachability = None
    else:
        reachability = expected_move_pct / strike_dist_pct

    return {
        "realized_vol_20d_pct": round(rv_20d * 100, 2),
        "expected_move_pct_to_eod": round(expected_move_pct * 100, 4),
        "strike_distance_pct": round(strike_dist_pct * 100, 4)
            if strike_dist_pct else None,
        "strike_reachability_ratio": round(reachability, 3)
            if reachability is not None else None,
        "minutes_to_expiry": minutes_to_expiry,
    }


# ── Episode tagging ───────────────────────────────────────────────


def assign_episode_ids(alerts: list[dict]) -> list[str]:
    """Group alerts into episodes: same (ticker, direction) with no gap
    >EPISODE_GAP_MAX_MIN minutes = same episode_id.

    Returns list of episode_id strings parallel to alerts list.
    """
    by_key: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for i, a in enumerate(alerts):
        key = (a["ticker"], a["direction"])
        by_key.setdefault(key, []).append((a["fired_at"], i))

    episode_ids = [""] * len(alerts)
    for (ticker, direction), entries in by_key.items():
        entries.sort()
        ep_num = 0
        prev_ts = None
        for ts, idx in entries:
            if prev_ts is None or (ts - prev_ts) > EPISODE_GAP_MAX_MIN * 60:
                ep_num += 1
                # Episode ID format: {ticker}_{direction}_{day}_{ep_num}
                day_str = datetime.fromtimestamp(ts).strftime("%Y%m%d")
                ep_id = f"{ticker}_{direction[:4]}_{day_str}_ep{ep_num}"
            episode_ids[idx] = ep_id
            prev_ts = ts
    return episode_ids


# ── Top-level: annotate one alert ─────────────────────────────────


def annotate_alert(alert: dict) -> dict:
    """Compute all annotation features for one alert. Returns a dict
    suitable for UPDATE'ing the alert row."""
    ticker = alert["ticker"]
    fire_ts = int(alert["fired_at"])
    day = datetime.fromtimestamp(fire_ts).strftime("%Y-%m-%d")
    spot = float(alert.get("spot") or 0)
    strike = float(alert.get("strike") or 0)
    direction = alert.get("direction", "bullish")

    out: dict[str, Any] = {}

    # Strike feasibility
    if spot > 0 and strike > 0:
        out.update(compute_feasibility(ticker, day, fire_ts, spot, strike, direction))
    else:
        out.update({
            "realized_vol_20d_pct": None, "expected_move_pct_to_eod": None,
            "strike_distance_pct": None, "strike_reachability_ratio": None,
            "minutes_to_expiry": None,
        })

    # Day-state features (only for SPY/QQQ where we have Databento)
    bars = get_minute_bars(ticker, day)
    out.update(compute_day_state_features(bars, fire_ts))

    # Tape regime tag at fire time
    try:
        from server.tape_regime import classify_tape_regime
        if not bars.empty:
            bars_for_regime = [
                {"ts": int(r["minute"].timestamp()),
                 "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])}
                for _, r in bars.iterrows()
            ]
            result = classify_tape_regime(bars_for_regime, fire_ts)
            out["tape_regime_at_fire"] = result.regime
        else:
            out["tape_regime_at_fire"] = None
    except Exception:
        out["tape_regime_at_fire"] = None

    # Cross-ticker SPY/QQQ alignment (May 2 evening — OpenAI rec)
    try:
        aligned, corr = cross_ticker_alignment(
            ticker, day, fire_ts, out.get("open_to_spot_pct"),
        )
        out["cross_ticker_aligned"] = aligned
        out["cross_ticker_corr_30m"] = corr
    except Exception:
        out["cross_ticker_aligned"] = None
        out["cross_ticker_corr_30m"] = None

    # Macro-event window flag (May 2 evening)
    try:
        in_window, label = macro_event_at(fire_ts)
        out["in_macro_window"] = int(in_window)
        out["macro_event_label"] = label
    except Exception:
        out["in_macro_window"] = None
        out["macro_event_label"] = None

    return out
