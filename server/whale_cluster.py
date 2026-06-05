"""WHALE CLUSTER detector — N+ whale-tagged strikes same direction.

Built 2026-06-04 PM (overnight Phase 3). Today's NVDA accumulation was
the canonical example:
  09:33  NVDA 230C 8/21  $4.42M ASK
  10:04  NVDA 160C 8/21  $3.53M ASK (deep ITM stock-replacement)
  12:32  NVDA 215C 7/2   $3.73M ASK
  09:43  NVDA 200C 1/15/27 $1.69M ASK (LEAP)
  09:47  NVDA 230C 1/15/27 $987K ASK (LEAP)
  ... and ~7 more whale-tagged BULL prints across 4+ expirations

11 individual WHALE Telegrams = noise. ONE summary alert
("NVDA — 11 whale prints across 4 expirations, $30M+ total ASK, BULL
ladder pattern, smart money loading multi-tenor") = signal.

Difference from server/informed_cluster.py:
  - informed_cluster groups by (ticker, EXPIRATION, direction) — single
    expiration only. Catches the Panuwat 3-strike-same-week insider
    pattern (META 615C/617.5C/620C all 0DTE).
  - whale_cluster groups by (ticker, direction) — CROSS-expiration. The
    canonical whale pattern is multi-tenor (weeklies + monthlies + LEAPs
    simultaneously), so collapsing across expirations is the point.

Telegram threshold = 2 strikes (lower than INFORMED CLUSTER's 3) because
each individual whale already cleared a higher bar ($1M+ ASK, vol>=500,
V/OI>=30%). Two of those on the same ticker+direction in a 30-min window
is already a strong ladder signal.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


# Rolling window: how far back we look for sibling whale fires
WHALE_CLUSTER_WINDOW_SEC = 30 * 60  # 30 minutes

# Minimum distinct strikes to RECORD a cluster (for audit/UI surface)
MIN_WHALE_CLUSTER_STRIKES = 2

# Minimum distinct strikes to FIRE Telegram alert.
# 2 is enough because every whale already cleared the $1M ASK + vol>=500
# + V/OI>=30% gates. Two whale-tagged strikes on the same ticker+direction
# inside 30 min is the textbook ladder accumulation pattern.
MIN_WHALE_CLUSTER_TELEGRAM_STRIKES = 2

# Per-cluster dedup TTL — same cluster can't re-fire even as more strikes
# accumulate. The cluster GROWS within the window but Telegram pings once.
WHALE_CLUSTER_DEDUP_TTL_SEC = 30 * 60


# In-memory roster of recent whale-tagged fires keyed by (ticker, direction).
# Value is list of {strike, expiration, ts, notional, vol, oi, option_type}.
_recent_whale_fires: dict[tuple[str, str], list[dict]] = defaultdict(list)

# Cluster dedup: last fire timestamp per (ticker, direction)
_whale_cluster_dedup: dict[tuple[str, str], float] = {}


def _direction_of(alert: dict[str, Any]) -> str:
    """Map sentiment to BULL/BEAR direction.

    The sentiment column in flow_alerts is computed by _detect_sentiment
    in flow_alerts.py, which already encodes the directional view on
    the underlying (NOT on the option position):

        call + ASK → BULLISH  (buying calls = bullish on underlying)
        call + BID → BEARISH  (selling calls = bearish)
        put  + ASK → BEARISH  (buying puts = bearish on underlying)
        put  + BID → BULLISH  (selling puts = bullish)

    So the direction is simply: BULLISH→BULL, BEARISH→BEAR. No need to
    re-derive from option_type. (Note: server/informed_cluster.py has an
    inverted mapping for puts; preserving the docstring divergence here
    so future code-readers don't conclude this is the same bug.)
    """
    sent = (alert.get("sentiment") or "").upper()
    if sent == "BULLISH":
        return "BULL"
    if sent == "BEARISH":
        return "BEAR"
    return "NEUTRAL"


def record_and_check(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Record a whale-tagged fire. Return a cluster-fire dict if this fire
    completes (or extends) a cluster of N+ DISTINCT strikes; else None.

    Caller should pass only is_whale=1 alerts — this module doesn't
    re-verify the whale gate (that's the job of _classify_whale_signature).

    Cluster-fire dict format:
      {
        "ticker": str,
        "direction": "BULL" | "BEAR",
        "strikes": [{strike, exp, ts, notional, vol, oi, option_type}, ...],
        "n_strikes": int,
        "n_expirations": int,
        "first_ts": int,
        "last_ts": int,
        "total_notional": float,
        "avg_notional": float,
        "duration_min": float,
        "expirations": list[str],
      }
    """
    ticker = (alert.get("ticker") or "").upper()
    direction = _direction_of(alert)
    if not ticker or direction == "NEUTRAL":
        return None
    if not alert.get("is_whale"):
        # Defense in depth: skip alerts that didn't pass the whale gate.
        # Caller is responsible but we don't want to silently form clusters
        # on non-whale data.
        return None

    key = (ticker, direction)
    now = time.time()
    strike = alert.get("strike", 0)
    exp = alert.get("expiration", "")

    # GC: drop expired siblings from the roster (outside window)
    cutoff = now - WHALE_CLUSTER_WINDOW_SEC
    roster = [f for f in _recent_whale_fires[key] if f["ts"] >= cutoff]

    # Same (strike, expiration) re-firing — keep the latest, don't double-count.
    # We dedup by (strike, exp) because a whale could plausibly add to the
    # same strike at multiple expirations (a true ladder); those count as
    # distinct slots for the cluster.
    existing = next(
        (f for f in roster if f["strike"] == strike and f["expiration"] == exp),
        None,
    )
    fire_record = {
        "strike": strike,
        "expiration": exp,
        "ts": now,
        "notional": alert.get("notional", 0) or 0,
        "vol": alert.get("volume", 0) or 0,
        "oi": alert.get("oi", 0) or 0,
        "option_type": alert.get("option_type", ""),
    }
    if existing:
        roster.remove(existing)
    roster.append(fire_record)
    _recent_whale_fires[key] = roster

    # Distinct (strike, expiration) pairs in window
    distinct_legs = {(f["strike"], f["expiration"]) for f in roster}
    if len(distinct_legs) < MIN_WHALE_CLUSTER_STRIKES:
        return None

    # Cluster dedup
    last_cluster_fire = _whale_cluster_dedup.get(key, 0.0)
    if now - last_cluster_fire < WHALE_CLUSTER_DEDUP_TTL_SEC:
        return None
    _whale_cluster_dedup[key] = now

    first_ts = min(f["ts"] for f in roster)
    last_ts = max(f["ts"] for f in roster)
    expirations = sorted({f["expiration"] for f in roster})
    total_notional = sum(f["notional"] for f in roster)

    return {
        "ticker": ticker,
        "direction": direction,
        "strikes": sorted(
            roster,
            key=lambda f: (f["expiration"], f["strike"]),
        ),
        "n_strikes": len(distinct_legs),
        "n_expirations": len(expirations),
        "first_ts": int(first_ts),
        "last_ts": int(last_ts),
        "total_notional": total_notional,
        "avg_notional": total_notional / max(len(roster), 1),
        "duration_min": (last_ts - first_ts) / 60.0,
        "expirations": expirations,
    }


def gc_old_entries() -> int:
    """Drop entries older than 2× window. Returns count removed."""
    cutoff = time.time() - 2 * WHALE_CLUSTER_WINDOW_SEC
    removed = 0
    for key in list(_recent_whale_fires.keys()):
        before = len(_recent_whale_fires[key])
        _recent_whale_fires[key] = [
            f for f in _recent_whale_fires[key] if f["ts"] >= cutoff
        ]
        removed += before - len(_recent_whale_fires[key])
        if not _recent_whale_fires[key]:
            del _recent_whale_fires[key]
    cutoff2 = time.time() - 2 * WHALE_CLUSTER_DEDUP_TTL_SEC
    for key in list(_whale_cluster_dedup.keys()):
        if _whale_cluster_dedup[key] < cutoff2:
            del _whale_cluster_dedup[key]
    return removed


def format_cluster_telegram(cluster: dict[str, Any]) -> str:
    """Format a whale-cluster fire dict as a Telegram-ready string."""
    import datetime as _dt
    ticker = cluster["ticker"]
    direction = cluster["direction"]
    n_strikes = cluster["n_strikes"]
    n_exps = cluster["n_expirations"]
    notional = cluster["total_notional"]
    avg = cluster["avg_notional"]
    dur = cluster["duration_min"]
    strikes = cluster["strikes"]
    expirations = cluster["expirations"]

    dir_emoji = "🟢" if direction == "BULL" else "🔴"
    dir_label = "BULLISH" if direction == "BULL" else "BEARISH"

    # Format strike rows grouped by expiration
    by_exp: dict[str, list[dict]] = defaultdict(list)
    for f in strikes:
        by_exp[f["expiration"]].append(f)
    rows = []
    for exp in expirations:
        legs = sorted(by_exp[exp], key=lambda f: f["strike"])
        strike_str = " / ".join(
            f"${f['strike']:g}{f['option_type'][0].upper()}"
            for f in legs
        )
        exp_notional = sum(f["notional"] for f in legs)
        rows.append(f"  {exp}  {strike_str}  (${exp_notional/1e6:.1f}M)")
    rows_str = "\n".join(rows[:10])  # cap at 10 expiration rows
    if len(rows) > 10:
        rows_str += f"\n  (+{len(rows)-10} more expirations)"

    first_t = _dt.datetime.fromtimestamp(cluster["first_ts"]).strftime("%H:%M")
    last_t = _dt.datetime.fromtimestamp(cluster["last_ts"]).strftime("%H:%M")

    # Tenor span flag — multi-tenor ladders are the textbook whale pattern
    tenor_flag = ""
    if n_exps >= 3:
        tenor_flag = (
            f"\n<b>📐 MULTI-TENOR LADDER</b> "
            f"({n_exps} expirations) — institutional accumulation across the curve"
        )

    return (
        f"🐋🐋🐋 <b>WHALE CLUSTER</b> ({n_strikes} strikes, {dir_label}) 🐋🐋🐋\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{dir_emoji} <b>{ticker}</b>\n"
        f"<b>Total notional: ${notional:,.0f}</b>  (avg ${avg/1e6:.2f}M/leg)\n"
        f"Window: {first_t}-{last_t} ET ({dur:.0f} min){tenor_flag}\n"
        f"\n"
        f"<b>Legs:</b>\n"
        f"{rows_str}\n"
        f"\n"
        f"<i>Pattern: 2+ whale-tagged ASK prints on same ticker+direction\n"
        f"within 30 min. Today's canonical example: NVDA 6/4 — 11 whale\n"
        f"prints across 4 expirations (weeklies, monthlies, LEAPs) = $30M+\n"
        f"ASK = multi-tenor institutional accumulation.</i>"
    )
