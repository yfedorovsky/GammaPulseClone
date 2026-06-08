"""Noise filter for flow_alerts inserts.

Shipped 2026-06-02 PM after audit: 327,024 alerts in one day from 7,143
unique contracts (46x repeat-fire/contract). 66.5% LOW conviction, 49.2%
side=MID (P0 side-detection bug residue). Filters reduce stored noise
by ~95% while preserving every meaningful state change.

Five fixes here, in order of impact:

(1) Contract-snapshot dedup
    Only insert if (a) new contract today, (b) V/OI crossed a meaningful
    band (10x, 25x, 50x, 100x), or (c) 30+ min since last fire on the
    same contract. Repeat fires of the same vol_oi level are dropped.

(2) Drop LOW conviction at insert
    LOW alerts never trigger tracker creation, INFORMED FLOW, or
    Telegram. Logging them just inflates the table and adds CPU to the
    conviction booster.

(3) Drop side=MID under $1M notional
    49.2% MID rate is the P0 side-detection bug. Big-dollar MIDs are
    real institutional crosses worth keeping. Small MIDs are pure noise.

(4) Chop detection per ticker
    When today's BULLISH/BEARISH ASK notional balance is within ±10% on
    the dominant expiration, tag the ticker as CHOP. INFORMED FLOW
    dispatch is suppressed until balance breaks. TSLA today: $9.2B bull
    vs $9.2B bear on the 6/5 weekly = 0.1% bias = textbook chop.

(5) Cross-expiration directional bias (separate query helper)
    See compute_directional_bias_by_expiration() for tickers with
    multi-expiration flow that can surface "weekly chop but monthly bull"
    as an actionable signal.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, datetime
from typing import Any

# Test hook: point the cross-expiration bias query at a temp DB. None → prod
# "snapshots.db". (Same pattern as rs_acceleration._DB_PATH_OVERRIDE.)
_DB_PATH_OVERRIDE: str | None = None


def _bias_db_path() -> str:
    return _DB_PATH_OVERRIDE or "snapshots.db"


# === Contract-snapshot dedup state ===
# Keyed by (ticker, strike, exp, option_type). Value = dict with
# {last_ts, last_voi_band, fire_count_today}
_contract_state: dict[tuple, dict[str, Any]] = {}

# V/OI bands — alert ONLY when crossing into a new band (or back below).
# Captures meaningful escalation; suppresses re-fires of same band level.
_VOI_BANDS = (10, 25, 50, 100, 250)

# Time-based re-fire window. Even at same band, allow re-fire after this.
_REFIRE_WINDOW_SEC = 30 * 60  # 30 min

# Side=MID notional floor. Below this, drop. Above this, keep (institutional
# cross with deliberate MID print — worth preserving).
_MID_NOTIONAL_FLOOR = 1_000_000  # $1M


def _voi_band(vol_oi: float) -> int:
    """Return the highest band V/OI clears. 0 if below 10x."""
    band = 0
    for b in _VOI_BANDS:
        if vol_oi >= b:
            band = b
    return band


def _contract_key(alert: dict[str, Any]) -> tuple:
    return (
        alert.get("ticker", "").upper(),
        alert.get("strike"),
        alert.get("expiration"),
        (alert.get("option_type") or "").lower(),
    )


def _reset_state_if_new_day() -> None:
    """Clear in-memory state at midnight ET. Called inside should_insert."""
    global _contract_state, _last_state_date
    today = date.today()
    if _last_state_date != today:
        _contract_state = {}
        _last_state_date = today


_last_state_date: date | None = None


# === Chop detector state ===
# Keyed by (ticker, date_iso). Value = dict with bull_buy / bear_buy
# accumulating notional. Recomputed on each insert that survives other
# gates. CHOP threshold checked against this state.
_ticker_bias_state: dict[tuple[str, str], dict[str, float]] = {}

# Chop threshold: when bull-buy and bear-buy on the dominant expiration
# are within this fraction of each other, ticker is in CHOP mode.
CHOP_BALANCE_PCT = 0.10  # ±10%

# Minimum dollar volume before chop logic kicks in (don't tag low-volume
# names as CHOP from noise; they're already filtered upstream).
CHOP_MIN_NOTIONAL = 5_000_000  # $5M each side


def is_ticker_in_chop(ticker: str) -> bool:
    """Return True if ticker is currently flagged CHOP for today."""
    key = (ticker.upper(), date.today().isoformat())
    state = _ticker_bias_state.get(key)
    if not state:
        return False
    bull = state.get("bull_buy", 0.0)
    bear = state.get("bear_buy", 0.0)
    if min(bull, bear) < CHOP_MIN_NOTIONAL:
        return False
    total = bull + bear
    if total == 0:
        return False
    bias_pct = abs(bull - bear) / total
    return bias_pct < CHOP_BALANCE_PCT


def _accumulate_bias(alert: dict[str, Any]) -> None:
    """Add this alert's notional to today's bull/bear bias for the ticker."""
    ticker = alert.get("ticker", "").upper()
    if not ticker:
        return
    sentiment = (alert.get("sentiment") or "").upper()
    side = (alert.get("side") or "").upper()
    otype = (alert.get("option_type") or "").lower()
    ntl = float(alert.get("notional") or 0)
    if ntl <= 0:
        return
    # Only count buyer-initiated directional plays
    is_bull_buy = sentiment == "BULLISH" and side == "ASK" and otype == "call"
    is_bear_buy = sentiment == "BEARISH" and side == "ASK" and otype == "put"
    if not (is_bull_buy or is_bear_buy):
        return
    key = (ticker, date.today().isoformat())
    state = _ticker_bias_state.setdefault(key, {"bull_buy": 0.0, "bear_buy": 0.0})
    if is_bull_buy:
        state["bull_buy"] += ntl
    else:
        state["bear_buy"] += ntl


def should_insert(alert: dict[str, Any]) -> tuple[bool, str | None]:
    """Decide whether to persist this flow_alerts row.

    Returns (should_insert, drop_reason). drop_reason is None when keeping.

    Filters applied in cost-cheapest order:
      1. LOW conviction → drop
      2. Small-dollar MID side → drop
      3. Contract-snapshot dedup → drop unless new band or stale
    """
    _reset_state_if_new_day()

    # Fix #2: Drop LOW conviction at insert.
    # NOTE: conviction may not be set yet on the alert if filter is called
    # BEFORE _compute_conviction in insert_alert. We accept both pre- and
    # post-conviction calls — the caller in insert_alert sets conviction
    # first, then calls us, so we read the freshly-computed value.
    conviction = (alert.get("conviction") or "").upper()
    if conviction == "LOW":
        return False, "LOW conviction"

    # Fix #3: Drop side=MID under $1M notional.
    side = (alert.get("side") or "").upper()
    notional = float(alert.get("notional") or 0)
    if side == "MID" and notional < _MID_NOTIONAL_FLOOR:
        return False, f"MID side <${_MID_NOTIONAL_FLOOR/1e6:.0f}M"

    # Fix #1: Contract-snapshot dedup.
    key = _contract_key(alert)
    if None in key or key[0] == "":
        return True, None  # Malformed — let SQL deal with it
    vol_oi = float(alert.get("vol_oi") or 0)
    band = _voi_band(vol_oi)
    now = time.time()
    state = _contract_state.get(key)
    if state is None:
        # First fire of this contract today — keep
        _contract_state[key] = {
            "last_ts": now,
            "last_voi_band": band,
            "fire_count_today": 1,
        }
        _accumulate_bias(alert)
        return True, None
    # Subsequent fires — check escalation or staleness
    elapsed = now - state["last_ts"]
    if band > state["last_voi_band"]:
        # Crossed into a new (higher) V/OI band — meaningful escalation
        state["last_ts"] = now
        state["last_voi_band"] = band
        state["fire_count_today"] += 1
        _accumulate_bias(alert)
        return True, None
    if elapsed >= _REFIRE_WINDOW_SEC:
        # 30+ min since last fire — refresh even at same band
        state["last_ts"] = now
        state["fire_count_today"] += 1
        _accumulate_bias(alert)
        return True, None
    # Same band, recent fire — drop as repeat noise
    return False, f"dup band={band} {elapsed:.0f}s ago"


# === Cross-expiration directional summary (Fix #5; delta-weighted in #59) ===
#
# #59 (4-LLM synthesis 6/8): the headline directional bias is now
# DELTA-WEIGHTED buy-to-open flow, not raw $ notional. All 4 LLMs converged
# (Pan-Poteshman, Ge-Lin-Pearson): the predictive object is signed,
# buyer-initiated, OPENING, *delta-weighted* demand — Σ(V·Δ·100·P_open).
# Notional over-weights deep-ITM premium (Δ≈1 mechanical/stock-substitute) and
# the cheap-OTM lottery flood (each Δ≈0.05) inflates raw counts; delta-weighting
# collapses both, which is the direct fix for the 7,898-vs-6,514 long-bias on a
# crash day. Notional fields are retained as *_notional for reference.
#
# P_open = calibrated probability the trade opens new OI. Alerts already pass a
# vol≥2·oi unusual-flow gate, so opening likelihood is ~1 here; left as a flat
# constant + calibration hook (calibrate vs next-day settled OI à la #60).
BIAS_POPEN: float = 1.0
# Fallback |delta| when a row is missing greeks (~0.3% of ASK-opening rows).
_BIAS_DELTA_FALLBACK: float = 0.5


def _bias_verdict(bias_pct: float) -> str:
    if abs(bias_pct) < 10:
        return "CHOP"
    if bias_pct >= 40:
        return "STRONG_BULL"
    if bias_pct >= 20:
        return "BULL"
    if bias_pct <= -40:
        return "STRONG_BEAR"
    if bias_pct <= -20:
        return "BEAR"
    return "MILD"


def compute_directional_bias_by_expiration(
    ticker: str, lookback_hours: int = 6
) -> list[dict[str, Any]]:
    """Return per-expiration delta-weighted bull/bear bias for a ticker.

    Useful for surfacing patterns like TSLA today: weekly chop but next
    week bullish + monthly bearish. The same data structure is what
    the daily digest will render.

    Headline `bias_pct`/`verdict` are DELTA-WEIGHTED (signed buy-to-open delta
    demand). Notional equivalents are kept as `bias_pct_notional` etc.

    Returns list of dicts sorted by total delta demand descending:
      [{expiration, bull_buy, bear_buy, net,            # notional ($)
        bull_delta, bear_delta, net_delta,              # delta-weighted (Δ·shares)
        bias_pct, verdict,                              # headline = delta-weighted
        bias_pct_notional, verdict_notional}]           # reference = notional
    """
    cutoff = int(time.time()) - lookback_hours * 3600
    # vol × |delta| × 100, NULL/0 delta → fallback; whole thing × P_open.
    dexpr = (
        f"volume * COALESCE(NULLIF(ABS(delta), 0), {_BIAS_DELTA_FALLBACK}) "
        f"* 100 * {BIAS_POPEN}"
    )
    try:
        conn = sqlite3.connect(_bias_db_path(), timeout=5)
        rows = conn.execute(
            f"""SELECT expiration,
               SUM(CASE WHEN sentiment='BULLISH' AND side='ASK' AND option_type='call'
                        THEN notional ELSE 0 END) as bull_buy,
               SUM(CASE WHEN sentiment='BEARISH' AND side='ASK' AND option_type='put'
                        THEN notional ELSE 0 END) as bear_buy,
               SUM(CASE WHEN sentiment='BULLISH' AND side='ASK' AND option_type='call'
                        THEN {dexpr} ELSE 0 END) as bull_delta,
               SUM(CASE WHEN sentiment='BEARISH' AND side='ASK' AND option_type='put'
                        THEN {dexpr} ELSE 0 END) as bear_delta
               FROM flow_alerts WHERE ticker = ? AND ts >= ?
               GROUP BY expiration
               HAVING bull_buy + bear_buy > 500000
               ORDER BY bull_delta + bear_delta DESC""",
            (ticker.upper(), cutoff),
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[NOISE_FILTER] bias query failed {ticker}: {e!r}", flush=True)
        return []

    results = []
    for r in rows:
        bull = r[1] or 0
        bear = r[2] or 0
        bull_d = r[3] or 0
        bear_d = r[4] or 0
        total_d = bull_d + bear_d
        if total_d == 0:
            continue
        net_d = bull_d - bear_d
        bias_pct = (net_d / total_d) * 100  # DELTA-weighted headline

        total_n = bull + bear
        net_n = bull - bear
        bias_pct_n = (net_n / total_n) * 100 if total_n else 0.0

        results.append({
            "expiration": r[0],
            # notional ($) — reference
            "bull_buy": bull,
            "bear_buy": bear,
            "net": net_n,
            "bias_pct_notional": bias_pct_n,
            "verdict_notional": _bias_verdict(bias_pct_n),
            # delta-weighted — headline
            "bull_delta": bull_d,
            "bear_delta": bear_d,
            "net_delta": net_d,
            "bias_pct": bias_pct,
            "verdict": _bias_verdict(bias_pct),
        })
    return results


# === Per-underlying flow z-score normalization (task #61, 4-LLM synthesis) ===
#
# #61 (4-LLM synthesis 6/8): options sweep flow is mechanically call-heavy, so
# absolute directional flow always reads bullish. Sophisticated desks normalize
# each name against its OWN rolling base rate (z-score / percentile) and only
# treat flow as a standout when it deviates ≥2σ — this washes out the constant
# institutional call-overwrite hum (Grok/ChatGPT/Gemini converged on this).
#
# SHADOW by default (per the no-arch-change-until-validated discipline rule):
# we compute + surface the z-score but DO NOT hard-gate dispatch. Flip
# FLOW_ZSCORE_GATE_ACTIVE=1 only after live validation to actually escalate on
# |z|≥threshold. The z is delta-weighted (reuses the #59 buy-to-open construct).
FLOW_ZSCORE_GATE_ACTIVE: bool = os.getenv("FLOW_ZSCORE_GATE_ACTIVE", "0") in ("1", "true", "True")
FLOW_ZSCORE_BASELINE_DAYS: int = 20      # trailing window for the per-name baseline
FLOW_ZSCORE_MIN_DAYS: int = 5            # need this many prior days or z is untrusted
FLOW_ZSCORE_STANDOUT: float = 2.0        # |z| ≥ this = standout / escalation-eligible


def _daily_net_delta_series(ticker: str, days: int) -> list[tuple[str, float]]:
    """Per-trading-day signed buy-to-open delta flow for a ticker, most recent
    `days` days. Returns [(YYYY-MM-DD, net_delta)] oldest→newest. Day buckets use
    localtime (consistent with the rest of flow_noise_filter)."""
    cutoff = int(time.time()) - days * 86400
    dexpr = (
        f"volume * COALESCE(NULLIF(ABS(delta), 0), {_BIAS_DELTA_FALLBACK}) "
        f"* 100 * {BIAS_POPEN}"
    )
    try:
        conn = sqlite3.connect(_bias_db_path(), timeout=5)
        rows = conn.execute(
            f"""SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') as d,
                   SUM(CASE
                       WHEN sentiment='BULLISH' AND side='ASK' AND option_type='call' THEN {dexpr}
                       WHEN sentiment='BEARISH' AND side='ASK' AND option_type='put'  THEN -({dexpr})
                       ELSE 0 END) as net_delta
                FROM flow_alerts WHERE ticker = ? AND ts >= ?
                GROUP BY d ORDER BY d ASC""",
            (ticker.upper(), cutoff),
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[NOISE_FILTER] zscore query failed {ticker}: {e!r}", flush=True)
        return []
    return [(r[0], float(r[1] or 0.0)) for r in rows]


def compute_flow_zscore(ticker: str) -> dict[str, Any]:
    """How unusual is today's signed buy-to-open delta flow vs this name's own
    trailing baseline? Returns a shadow-mode read the bias endpoint surfaces:

      z          : float | None — (today − mean_prior) / std_prior; None if untrusted
      today_net  : float        — today's signed delta flow (Δ·shares; + bull / − bear)
      mean, std  : float        — trailing baseline (prior days only, today excluded)
      n_days     : int          — prior days available for the baseline
      standout   : bool         — |z| ≥ FLOW_ZSCORE_STANDOUT
      direction  : str          — BULL / BEAR / FLAT (sign of today_net)
      trusted    : bool         — n_days ≥ FLOW_ZSCORE_MIN_DAYS and std > 0
      gate_active: bool
    """
    out: dict[str, Any] = {
        "z": None, "today_net": 0.0, "mean": 0.0, "std": 0.0, "n_days": 0,
        "standout": False, "direction": "FLAT", "trusted": False,
        "gate_active": FLOW_ZSCORE_GATE_ACTIVE,
    }
    series = _daily_net_delta_series(ticker, FLOW_ZSCORE_BASELINE_DAYS + 1)
    if not series:
        return out
    today_key = date.today().isoformat()
    today_net = next((v for d, v in series if d == today_key), 0.0)
    prior = [v for d, v in series if d != today_key]
    out["today_net"] = today_net
    out["direction"] = "BULL" if today_net > 0 else ("BEAR" if today_net < 0 else "FLAT")
    out["n_days"] = len(prior)
    if len(prior) < FLOW_ZSCORE_MIN_DAYS:
        return out
    mean = sum(prior) / len(prior)
    var = sum((v - mean) ** 2 for v in prior) / len(prior)
    std = var ** 0.5
    out["mean"] = mean
    out["std"] = std
    if std <= 0:
        return out
    z = (today_net - mean) / std
    out["z"] = z
    out["trusted"] = True
    out["standout"] = abs(z) >= FLOW_ZSCORE_STANDOUT
    return out
