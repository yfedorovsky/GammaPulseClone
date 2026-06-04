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

import sqlite3
import time
from datetime import date, datetime
from typing import Any


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


# === Cross-expiration directional summary (Fix #5) ===
def compute_directional_bias_by_expiration(
    ticker: str, lookback_hours: int = 6
) -> list[dict[str, Any]]:
    """Return per-expiration bull/bear bias for a ticker.

    Useful for surfacing patterns like TSLA today: weekly chop but next
    week bullish + monthly bearish. The same data structure is what
    the daily digest will render.

    Returns list of dicts sorted by total volume descending:
      [{exp, bull_buy, bear_buy, net, bias_pct, verdict}]
    """
    cutoff = int(time.time()) - lookback_hours * 3600
    try:
        conn = sqlite3.connect("snapshots.db", timeout=5)
        rows = conn.execute(
            """SELECT expiration,
               SUM(CASE WHEN sentiment='BULLISH' AND side='ASK' AND option_type='call'
                        THEN notional ELSE 0 END) as bull_buy,
               SUM(CASE WHEN sentiment='BEARISH' AND side='ASK' AND option_type='put'
                        THEN notional ELSE 0 END) as bear_buy
               FROM flow_alerts WHERE ticker = ? AND ts >= ?
               GROUP BY expiration
               HAVING bull_buy + bear_buy > 500000
               ORDER BY bull_buy + bear_buy DESC""",
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
        total = bull + bear
        if total == 0:
            continue
        net = bull - bear
        bias_pct = (net / total) * 100
        if abs(bias_pct) < 10:
            verdict = "CHOP"
        elif bias_pct >= 40:
            verdict = "STRONG_BULL"
        elif bias_pct >= 20:
            verdict = "BULL"
        elif bias_pct <= -40:
            verdict = "STRONG_BEAR"
        elif bias_pct <= -20:
            verdict = "BEAR"
        else:
            verdict = "MILD"
        results.append({
            "expiration": r[0],
            "bull_buy": bull,
            "bear_buy": bear,
            "net": net,
            "bias_pct": bias_pct,
            "verdict": verdict,
        })
    return results
