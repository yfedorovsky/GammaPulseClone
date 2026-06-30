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

import os
import time
from collections import defaultdict
from typing import Any

# Rolling window: how far back we look for sibling fires
CLUSTER_WINDOW_SEC = 30 * 60  # 30 minutes

# Minimum strikes to RECORD a cluster (persist for audit/UI display)
MIN_CLUSTER_STRIKES = 2

# Minimum strikes to FIRE Telegram alert (production threshold).
# 2026-05-27 PM backtest finding: 2-strike clusters have ~49.5% hit rate
# (coin flip), while 4-strike are 88.9% and 5-strike are 80%. Telegram
# fires at 3+ to suppress the low-conviction tier. The 2-strike clusters
# still surface in the UI strip (audit visibility) but don't ping phone.
MIN_CLUSTER_TELEGRAM_STRIKES = 3

# Per-cluster dedup TTL (prevents the same (ticker, exp, direction)
# cluster from re-firing as new strikes accumulate within the window)
CLUSTER_DEDUP_TTL_SEC = 30 * 60

# Broad-market index / ETF roots whose 0DTE "clusters" are the NOISE FLOOR, not
# informed single-name ladders. 2026-06-29 reconstruction (5/27-6/29, n=24,709
# reconstructed cluster legs): these were ~half of all fires, with the worst
# realized option P&L of any segment — short-horizon markout EXHAUST and a median
# option-MAE of -80% (vs -32% for single-names). They get their own
# alert_type='CLUSTER_INDEX' bucket so the universe-wide CLUSTER tier stays clean.
INDEX_ETF_ROOTS: frozenset[str] = frozenset({
    "SPY", "SPX", "SPXW", "QQQ", "QQQM", "IWM", "NDX", "DIA", "RUT", "XSP",
    "VIX", "VIXW", "XND",
})


def _is_index_etf(ticker: str) -> bool:
    return (ticker or "").upper() in INDEX_ETF_ROOTS


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


def record_and_check(alert: dict[str, Any],
                     db_path: str | None = None,
                     now: float | None = None) -> dict[str, Any] | None:
    """Record an INFORMED FLOW fire. Returns a cluster-fire dict if this
    fire completes (or grows) a cluster of N+ strikes; else None.

    `now` is injectable (defaults to wall-clock) so the historical
    reconstruction (scripts/reconstruct_clusters.py) can replay past insider
    fires chronologically through this EXACT logic — guaranteeing reconstructed
    clusters match what the live detector produces, no reimplementation drift.

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
    now = now if now is not None else time.time()
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

    # Cluster fire payload — built for every 2+ -strike state. The caller decides
    # what to do by n_strikes (Telegram fires only at >= MIN_CLUSTER_TELEGRAM_STRIKES).
    first_ts = min(f["ts"] for f in roster)
    last_ts = max(f["ts"] for f in roster)
    cluster = {
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

    # Telegram / outcome-log tier. THE DEDUP IS STAMPED HERE — at the first time the
    # cluster reaches the 3-strike conviction tier — NOT at the 2-strike record floor.
    # BUG FIXED 2026-06-29 (4-LLM-audit root-cause): the dedup used to be stamped at
    # the 2-strike floor, so the 3rd/4th strike returned None before n_strikes could
    # reach 3 → the >=3 log/Telegram tier never executed → 0 alert_type='CLUSTER' rows
    # in alert_outcomes for 60 days (the crown-jewel detector had NO live outcome
    # telemetry). Logging it once here (idempotent) backfills realized option P&L +
    # short-horizon markout (#92) so the "INFORMED CLUSTER 89% WR" claim can be tested.
    if len(distinct_strikes) >= MIN_CLUSTER_TELEGRAM_STRIKES:
        last_cluster_fire = _cluster_dedup.get(key, 0.0)
        if now - last_cluster_fire < CLUSTER_DEDUP_TTL_SEC:
            return None  # already fired the 3+ tier this window — don't spam/double-log
        _cluster_dedup[key] = now
        log_cluster_outcomes(cluster, db_path=db_path)

    return cluster


def log_cluster_outcomes(cluster: dict[str, Any], db_path: str | None = None,
                         alert_type: str = "CLUSTER") -> int:
    """Log each distinct leg of a fired cluster to alert_outcomes (grade='{n}strike'
    so the validation harness can segment 3- vs 4-strike — the C10 question), so its
    realized option P&L + short-horizon markout can be backfilled (#92). Best-effort,
    never raises; env CLUSTER_OUTCOME_LOG=0 disables (tests). Returns rows logged.

    `alert_type` segments the source: 'CLUSTER' = the universe-wide INFORMED CLUSTER
    detector (record_and_check); 'CLUSTER_SEMIS' = the curated 🔬 SEMIS tier
    (semis_signals) — the actually-traded tier — kept in its own bucket so the two
    populations don't double-count in the markout report.

    Tolerates BOTH leg shapes: record_and_check emits tuples (strike, ts, ...);
    semis_signals emits a bare list of float strikes."""
    if os.getenv("CLUSTER_OUTCOME_LOG", "1").strip().lower() not in ("1", "true", "yes", "on"):
        return 0
    try:
        from .alert_outcomes import log_alert
    except Exception:
        return 0
    ticker = cluster.get("ticker", "")
    # Keep the universe-wide CLUSTER bucket single-name-clean: route broad-market
    # index/ETF 0DTE (the noise floor) to CLUSTER_INDEX. An explicit non-default
    # alert_type (e.g. CLUSTER_SEMIS, already scoped to non-index names) is
    # respected as-is.
    if alert_type == "CLUSTER" and _is_index_etf(ticker):
        alert_type = "CLUSTER_INDEX"
    n = cluster.get("n_strikes", 0)
    otype = (cluster.get("option_type") or "").lower() or None
    fired = float(cluster.get("last_ts") or time.time())
    notional = cluster.get("total_notional", cluster.get("notional"))
    logged, seen = 0, set()
    for leg in cluster.get("strikes", []):
        strike = leg[0] if isinstance(leg, (list, tuple)) else leg
        if strike in seen:
            continue
        seen.add(strike)
        kw: dict[str, Any] = dict(
            alert_type=alert_type, ticker=ticker,
            direction=cluster.get("direction"), grade=f"{n}strike",
            score=cluster.get("max_score"), strike=float(strike),
            expiration=cluster.get("expiration"), option_type=otype, fired_at=fired,
            raw_alert={"n_strikes": n, "total_notional": notional,
                       "avg_vol_oi": cluster.get("avg_vol_oi")},
        )
        if db_path:
            kw["db_path"] = db_path
        try:
            if log_alert(**kw):
                logged += 1
        except Exception:
            pass
    return logged


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
