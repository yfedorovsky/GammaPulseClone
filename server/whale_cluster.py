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


# ─── Two-tier cluster windows (Option A, task #48) ───────────────────
#
# FAST tier — intra-day burst (the META 0DTE 3-strike Panuwat pattern).
# Catches multi-strike accumulation within a 30-min window where the
# strikes need NOT be on different expirations.
#
# SLOW tier — cross-day-long multi-tenor ladder (today's NBIS case).
# Catches institutional ladders that build SLOWLY across hours:
#   10:14  NBIS 250C 6/18    $X.XM (first whale)
#   13:51  NBIS 210C 1/15/27 $22.7M (second whale, 217 min later)
# A 30-min window misses this because the 10:14 record gets pruned
# before 13:51 arrives. The slow tier extends the window to 4 hours
# AND requires DIFFERENT expirations (the cross-tenor signature) so
# it doesn't double-fire on patterns the fast tier already catches.
#
# Tier dispatch rule:
#   1. Check fast first (30-min window, 2+ distinct strikes)
#   2. If no fast cluster, check slow (4-hour window, 2+ distinct expirations)
#   3. At most ONE cluster fires per record_and_check call
# This avoids double-firing on multi-strike-multi-tenor patterns.

# FAST window — intra-day burst
WHALE_CLUSTER_WINDOW_SEC = 30 * 60   # 30 minutes
# SLOW window — multi-tenor ladder
WHALE_CLUSTER_SLOW_WINDOW_SEC = 4 * 60 * 60  # 4 hours

# Minimum distinct strikes to RECORD a fast cluster (for audit/UI surface)
MIN_WHALE_CLUSTER_STRIKES = 2

# Minimum distinct strikes to FIRE fast (INTRADAY) Telegram alert.
# 2 is enough because every whale already cleared the $1M ASK + vol>=500
# + V/OI>=30% gates. Two whale-tagged strikes on the same ticker+direction
# inside 30 min is the textbook ladder accumulation pattern.
MIN_WHALE_CLUSTER_TELEGRAM_STRIKES = 2

# Minimum distinct EXPIRATIONS to FIRE slow (MULTI-TENOR) Telegram alert.
# 2 distinct expirations = cross-tenor signature that the fast tier won't
# catch (because fast doesn't require cross-tenor). Higher floor for slow
# than fast because the 4-hour window will see more incidental hits.
MIN_WHALE_SLOW_CLUSTER_EXPIRATIONS = 2

# Per-cluster dedup TTL — same cluster can't re-fire even as more strikes
# accumulate. The cluster GROWS within the window but Telegram pings once.
# Slow dedup is longer (4 hours) so a multi-tenor ladder doesn't keep
# re-firing throughout the afternoon as new legs land.
WHALE_CLUSTER_DEDUP_TTL_SEC = 30 * 60
WHALE_CLUSTER_SLOW_DEDUP_TTL_SEC = 4 * 60 * 60


# In-memory roster of recent whale-tagged fires keyed by (ticker, direction).
# Value is list of {strike, expiration, ts, notional, vol, oi, option_type}.
# Sized for the SLOW window (4hr) since fast queries are just a filter.
_recent_whale_fires: dict[tuple[str, str], list[dict]] = defaultdict(list)

# Fast cluster dedup: last fire timestamp per (ticker, direction)
_whale_cluster_dedup: dict[tuple[str, str], float] = {}
# Slow cluster dedup: last fire timestamp per (ticker, direction)
_whale_slow_cluster_dedup: dict[tuple[str, str], float] = {}


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


def _build_cluster_dict(
    ticker: str,
    direction: str,
    roster: list[dict],
    tier: str,
) -> dict[str, Any]:
    """Assemble a cluster payload dict from a roster. `tier` is 'fast' or 'slow'."""
    distinct_legs = {(f["strike"], f["expiration"]) for f in roster}
    expirations = sorted({f["expiration"] for f in roster})
    total_notional = sum(f["notional"] for f in roster)
    first_ts = min(f["ts"] for f in roster)
    last_ts = max(f["ts"] for f in roster)
    return {
        "ticker": ticker,
        "direction": direction,
        "tier": tier,                   # "fast" | "slow"
        "strikes": sorted(roster, key=lambda f: (f["expiration"], f["strike"])),
        "n_strikes": len(distinct_legs),
        "n_expirations": len(expirations),
        "first_ts": int(first_ts),
        "last_ts": int(last_ts),
        "total_notional": total_notional,
        "avg_notional": total_notional / max(len(roster), 1),
        "duration_min": (last_ts - first_ts) / 60.0,
        "expirations": expirations,
    }


def record_and_check(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Record a whale-tagged fire. Return a cluster-fire dict if this fire
    completes or extends either tier of cluster; else None.

    Caller should pass only is_whale=1 alerts.

    Two-tier dispatch (Option A, task #48):
      FAST tier (30-min window): intra-day burst, same or different expirations.
        - 2+ distinct (strike, exp) legs within 30 min.
        - Catches META 0DTE 3-strike Panuwat-class patterns.
      SLOW tier (4-hour window): cross-day multi-tenor ladder.
        - 2+ DISTINCT EXPIRATIONS within 4 hours.
        - Catches NBIS-class patterns where legs build over hours.
        - Only fires if fast didn't fire (prevents double-fire).

    Returned dict includes tier='fast' or tier='slow' so callers can
    choose which Telegram format to use.
    """
    ticker = (alert.get("ticker") or "").upper()
    direction = _direction_of(alert)
    if not ticker or direction == "NEUTRAL":
        return None
    if not alert.get("is_whale"):
        return None

    key = (ticker, direction)
    now = time.time()
    strike = alert.get("strike", 0)
    exp = alert.get("expiration", "")

    # Maintain the roster at SLOW window size (4 hr) — the fast tier is a
    # filtered view of the same roster so we only need one data structure.
    slow_cutoff = now - WHALE_CLUSTER_SLOW_WINDOW_SEC
    roster = [f for f in _recent_whale_fires[key] if f["ts"] >= slow_cutoff]

    # Upsert this fire into the roster.
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

    # ── FAST TIER: 30-min window, 2+ distinct legs ────────────────────
    fast_cutoff = now - WHALE_CLUSTER_WINDOW_SEC
    fast_roster = [f for f in roster if f["ts"] >= fast_cutoff]
    fast_legs = {(f["strike"], f["expiration"]) for f in fast_roster}

    if len(fast_legs) >= MIN_WHALE_CLUSTER_TELEGRAM_STRIKES:
        last_fast = _whale_cluster_dedup.get(key, 0.0)
        if now - last_fast >= WHALE_CLUSTER_DEDUP_TTL_SEC:
            _whale_cluster_dedup[key] = now
            return _build_cluster_dict(ticker, direction, fast_roster, "fast")

    # ── SLOW TIER: 4-hour window, 2+ distinct EXPIRATIONS, span > 30 min ──
    # Two guards keep this mutually exclusive with the fast tier:
    #   1. We only reach here if fast did NOT fire THIS call (early return
    #      above). Note this is per-call, not "fast never fired" — after a
    #      fast cooldown a later call can fall through to slow.
    #   2. SPAN GUARD: the roster must span MORE than the fast window. A
    #      multi-expiration burst that lands entirely within 30 min is the
    #      fast tier's domain (and already carries a "📐 + MULTI-TENOR"
    #      badge in the fast banner when 3+ expirations). The slow tier is
    #      ONLY for ladders that genuinely build over hours — the NBIS 6/4
    #      case (10:14 → 13:51 = 217 min). Without this guard, backtest on
    #      2026-06-04 fired 18 redundant slow banners on sub-30-min bursts
    #      that fast already covered (71 slow → 53 genuine cross-window).
    slow_expirations = {f["expiration"] for f in roster}
    roster_span = max(f["ts"] for f in roster) - min(f["ts"] for f in roster)
    if (len(slow_expirations) >= MIN_WHALE_SLOW_CLUSTER_EXPIRATIONS
            and roster_span > WHALE_CLUSTER_WINDOW_SEC):
        last_slow = _whale_slow_cluster_dedup.get(key, 0.0)
        if now - last_slow >= WHALE_CLUSTER_SLOW_DEDUP_TTL_SEC:
            _whale_slow_cluster_dedup[key] = now
            return _build_cluster_dict(ticker, direction, roster, "slow")

    return None


def gc_old_entries() -> int:
    """Drop entries older than 2× slow window. Returns count removed."""
    now = time.time()
    # Roster GC — keep anything in the slow window
    cutoff = now - 2 * WHALE_CLUSTER_SLOW_WINDOW_SEC
    removed = 0
    for key in list(_recent_whale_fires.keys()):
        before = len(_recent_whale_fires[key])
        _recent_whale_fires[key] = [
            f for f in _recent_whale_fires[key] if f["ts"] >= cutoff
        ]
        removed += before - len(_recent_whale_fires[key])
        if not _recent_whale_fires[key]:
            del _recent_whale_fires[key]
    # Fast dedup GC
    cutoff_fast = now - 2 * WHALE_CLUSTER_DEDUP_TTL_SEC
    for key in list(_whale_cluster_dedup.keys()):
        if _whale_cluster_dedup[key] < cutoff_fast:
            del _whale_cluster_dedup[key]
    # Slow dedup GC
    cutoff_slow = now - 2 * WHALE_CLUSTER_SLOW_DEDUP_TTL_SEC
    for key in list(_whale_slow_cluster_dedup.keys()):
        if _whale_slow_cluster_dedup[key] < cutoff_slow:
            del _whale_slow_cluster_dedup[key]
    return removed


def format_cluster_telegram(cluster: dict[str, Any]) -> str:
    """Format a whale-cluster fire dict as a Telegram-ready string.

    Two tiers produce distinct headers and context lines:
      FAST  → ⚡ INTRADAY CLUSTER (30-min burst, e.g. META 0DTE 3-strike)
      SLOW  → 🐋 MULTI-TENOR LADDER (4-hr cross-exp, e.g. NBIS today)
    """
    import datetime as _dt
    ticker = cluster["ticker"]
    direction = cluster["direction"]
    tier = cluster.get("tier", "fast")
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
    rows_str = "\n".join(rows[:10])
    if len(rows) > 10:
        rows_str += f"\n  (+{len(rows)-10} more expirations)"

    first_t = _dt.datetime.fromtimestamp(cluster["first_ts"]).strftime("%H:%M")
    last_t = _dt.datetime.fromtimestamp(cluster["last_ts"]).strftime("%H:%M")

    if tier == "slow":
        # SLOW tier: multi-tenor ladder — fired hours after the first whale
        # The actionable callout is the cross-curve conviction, not urgency
        header = (
            f"🐋 <b>MULTI-TENOR LADDER</b> ({n_exps} expirations, {dir_label}) 🐋\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        context = (
            f"<i>Institutional ladder building across the curve for {dur:.0f} min.\n"
            f"Canonical case: NBIS 6/4 — 250C 6/18 at 10:14 → 210C 1/15/27\n"
            f"at 13:51 = 217-min gap, $90M+ total ASK across 6 expirations.\n"
            f"Signal: not a one-day bet — strategic multi-tenor positioning.</i>"
        )
    else:
        # FAST tier: intra-day burst — urgency is the point
        header = (
            f"⚡ <b>INTRADAY CLUSTER</b> ({n_strikes} strikes, {dir_label}) ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        # Multi-tenor badge even within fast tier if 3+ expirations
        multi_tenor = ""
        if n_exps >= 3:
            multi_tenor = (
                f"\n<b>📐 + MULTI-TENOR</b> ({n_exps} expirations)"
            )
        context = (
            f"<i>2+ whale-tagged ASK strikes within 30 min on same direction.{multi_tenor}\n"
            f"Canonical case: META 5/27 615C/617.5C/620C 0DTE pre-paid-subs\n"
            f"news. Intraday accumulation = catalyst soon.</i>"
        )

    return (
        f"{header}"
        f"{dir_emoji} <b>{ticker}</b>\n"
        f"<b>Total notional: ${notional:,.0f}</b>  (avg ${avg/1e6:.2f}M/leg)\n"
        f"Window: {first_t}-{last_t} ET ({dur:.0f} min)\n"
        f"\n"
        f"<b>Legs:</b>\n"
        f"{rows_str}\n"
        f"\n"
        f"{context}"
    )
