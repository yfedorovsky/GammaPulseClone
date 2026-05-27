"""INFORMED FLOW cluster detector — N+ strikes in same expiration.

Built 2026-05-27 PM per cross-LLM validation unanimous (4/4) finding: the
single highest-value missing signal is multi-strike clustering. The META
5/27 catch shows the pattern clearly: 615C / 617.5C / 620C all 0DTE, all
5-6/6 INFORMED FLOW, all firing within 40 min. The Panuwat SEC complaint
(Lit. Rel. 25170) notes his 3 strikes represented 70-84% of total daily
volume — quantitative threshold worth modeling.

Different from `basket_detector.py`:
  - basket_detector: requires MIN_STRIKES=10, MIN_VOL=150/strike, $5M agg
    notional. Catches whale-tier OTM-ladder accumulation (MU 5/15).
  - informed_cluster: requires only 2+ strikes that ALREADY passed the
    INFORMED FLOW 5/6 gate. Catches the Panuwat-class 3-strike insider
    ladder where each strike is meaningful on its own but the cluster
    is the smoking gun.

This module is INFORMED FLOW v2 Batch 2.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

# Rolling window: how far back we look for sibling fires
CLUSTER_WINDOW_SEC = 30 * 60  # 30 minutes

# Minimum strikes to form a cluster
MIN_CLUSTER_STRIKES = 2

# Per-cluster dedup TTL (prevents the same (ticker, exp, direction)
# cluster from re-firing as new strikes accumulate within the window)
CLUSTER_DEDUP_TTL_SEC = 30 * 60


# In-memory roster of recent INFORMED FLOW fires keyed by
# (ticker, expiration, direction) where direction is "BULL" or "BEAR"
# based on (option_type, sentiment). Value is list of dicts with
# {strike, ts, score, notional, vol_oi}.
_recent_fires: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

# Cluster dedup: last fire timestamp per (ticker, exp, direction)
_cluster_dedup: dict[tuple[str, str, str], float] = {}


def _direction_of(alert: dict[str, Any]) -> str:
    """Map (option_type, sentiment) to BULL/BEAR direction.

    BULL: call + BULLISH (long call) OR put + BEARISH (sold puts = bullish)
    BEAR: call + BEARISH (sold calls = bearish) OR put + BULLISH (long put)
    """
    otype = (alert.get("option_type") or "").lower()
    sent = (alert.get("sentiment") or "").upper()
    if otype == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if otype == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "NEUTRAL"


def record_and_check(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Record an INFORMED FLOW fire. Returns a cluster-fire dict if this
    fire completes (or grows) a cluster of N+ strikes; else None.

    Cluster-fire dict format:
      {
        "ticker": str,
        "expiration": str,
        "direction": "BULL" | "BEAR",
        "option_type": str,
        "strikes": [(strike, ts, score, notional, vol_oi), ...],
        "first_ts": int,
        "last_ts": int,
        "total_notional": float,
        "max_score": int,
        "avg_vol_oi": float,
        "duration_min": float,
      }
    """
    ticker = alert.get("ticker", "")
    exp = alert.get("expiration", "")
    direction = _direction_of(alert)
    if not ticker or not exp or direction == "NEUTRAL":
        return None

    key = (ticker, exp, direction)
    now = time.time()
    strike = alert.get("strike", 0)

    # GC: drop expired siblings from the roster (outside window)
    cutoff = now - CLUSTER_WINDOW_SEC
    roster = [f for f in _recent_fires[key] if f["ts"] >= cutoff]

    # Record this fire (or update the existing strike entry if any)
    existing = next((f for f in roster if f["strike"] == strike), None)
    fire_record = {
        "strike": strike,
        "ts": now,
        "score": alert.get("insider_score", 0),
        "notional": alert.get("notional", 0) or 0,
        "vol_oi": alert.get("vol_oi", 0) or 0,
    }
    if existing:
        # Same strike re-firing — keep the latest, don't double-count
        roster.remove(existing)
    roster.append(fire_record)
    _recent_fires[key] = roster

    # Distinct strikes in window
    distinct_strikes = sorted({f["strike"] for f in roster})

    if len(distinct_strikes) < MIN_CLUSTER_STRIKES:
        return None

    # Cluster dedup — only fire CLUSTER once per (ticker, exp, direction)
    # per 30 min. The cluster GROWS within that window but we don't spam
    # one alert per added strike.
    last_cluster_fire = _cluster_dedup.get(key, 0.0)
    if now - last_cluster_fire < CLUSTER_DEDUP_TTL_SEC:
        return None

    _cluster_dedup[key] = now

    # Cluster fire payload
    first_ts = min(f["ts"] for f in roster)
    last_ts = max(f["ts"] for f in roster)
    return {
        "ticker": ticker,
        "expiration": exp,
        "direction": direction,
        "option_type": alert.get("option_type", ""),
        "strikes": sorted(
            [(f["strike"], f["ts"], f["score"], f["notional"], f["vol_oi"]) for f in roster],
            key=lambda x: x[0],
        ),
        "n_strikes": len(distinct_strikes),
        "first_ts": int(first_ts),
        "last_ts": int(last_ts),
        "total_notional": sum(f["notional"] for f in roster),
        "max_score": max(f["score"] for f in roster),
        "avg_vol_oi": sum(f["vol_oi"] for f in roster) / max(len(roster), 1),
        "duration_min": (last_ts - first_ts) / 60.0,
    }


def gc_old_entries() -> int:
    """Drop entries older than 2× window. Returns count removed."""
    cutoff = time.time() - 2 * CLUSTER_WINDOW_SEC
    removed = 0
    for key in list(_recent_fires.keys()):
        before = len(_recent_fires[key])
        _recent_fires[key] = [f for f in _recent_fires[key] if f["ts"] >= cutoff]
        removed += before - len(_recent_fires[key])
        if not _recent_fires[key]:
            del _recent_fires[key]
    # GC dedup map
    cutoff2 = time.time() - 2 * CLUSTER_DEDUP_TTL_SEC
    for key in list(_cluster_dedup.keys()):
        if _cluster_dedup[key] < cutoff2:
            del _cluster_dedup[key]
    return removed


def format_cluster_telegram(cluster: dict[str, Any]) -> str:
    """Format a cluster-fire dict as a Telegram-ready string."""
    import datetime as _dt
    ticker = cluster["ticker"]
    exp = cluster["expiration"]
    direction = cluster["direction"]
    otype = (cluster.get("option_type") or "").upper()
    n = cluster["n_strikes"]
    notional = cluster["total_notional"]
    max_score = cluster["max_score"]
    avg_voi = cluster["avg_vol_oi"]
    dur = cluster["duration_min"]
    strikes = cluster["strikes"]

    dir_emoji = "🟢" if direction == "BULL" else "🔴"
    strikes_str = " / ".join(f"${s:g}" for s, _t, _sc, _n, _v in strikes[:8])
    if len(strikes) > 8:
        strikes_str += f" (+{len(strikes)-8} more)"

    first_t = _dt.datetime.fromtimestamp(cluster["first_ts"]).strftime("%H:%M")
    last_t = _dt.datetime.fromtimestamp(cluster["last_ts"]).strftime("%H:%M")

    return (
        f"⚡⚡⚡ <b>INFORMED CLUSTER</b> ({n} strikes, {direction}) ⚡⚡⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{dir_emoji} <b>{ticker}</b> {otype} {exp}\n"
        f"Strikes: {strikes_str}\n"
        f"Window: {first_t}-{last_t} ET ({dur:.0f} min)\n"
        f"Total notional: ${notional:,.0f}\n"
        f"Max score: {max_score}/6 | Avg V/OI: {avg_voi:.1f}x\n"
        f"<i>Pattern matches Panuwat (3 strikes, 70-84% daily volume) +\n"
        f"META 5/27 ladder (615C/617.5C/620C 0DTE pre-paid-subs news)</i>"
    )
