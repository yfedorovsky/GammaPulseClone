"""Multi-strike basket detector — catches OTM-ladder accumulation patterns.

Bug #6 (2026-05-12). The 5/12 MU 5/15 alert blast caught us flat-footed:
between 3:11 and 3:59 PM ET, an institutional buyer accumulated ASK-side
across 12+ strikes from $800C all the way to $1000C — but most individual
strikes were under the per-strike alert thresholds (vol < 200, notional
< $100K each). FL0WG0D's tweet read the BASKET. Our scanner only saw
the few biggest strikes (800/850/900) and even then misclassified side.

The fix: a separate detector that walks the chain cache and identifies
strike LADDERS — same ticker + expiration + option_type with 5+ strikes
showing ASK-side aggression within a single chain snapshot.

This catches:
  - "Buy every OTM call up the curve" institutional positioning ahead of
    a catalyst (MU 5/15 today)
  - Coordinated multi-strike sweeps that are too small per-strike for the
    flow_alerts gate but obviously orchestrated in aggregate
  - Pre-earnings call-laddering on names with binary upside

Per-strike criteria for inclusion in basket:
  - vol >= 100 contracts
  - ask_vol / total_vol >= 0.55 (call basket) OR bid_vol / total_vol
    >= 0.55 (put basket); inverted for puts where BID = bullish
  - notional >= $25,000

Basket-level fire criteria:
  - >= 5 qualifying strikes in the same (ticker, expiration, option_type)
    AND aggregate notional >= $500,000
  - dedup: 1 fire per (ticker, expiration, option_type) per 60 min unless
    basket grows by >= 50% in strike count or notional
"""
from __future__ import annotations

import time
from typing import Any

from .cache import cache


# ── Tuning ────────────────────────────────────────────────────────────
# Calibration revision 2026-05-13: first live run on a gap-up day showed
# basket alerts dominating Telegram (17 candidates in 15 min, mostly
# index products with 20+ strikes naturally hitting). Tightened to make
# basket alerts mean "institutional concentration", not "active 0DTE day".
MIN_STRIKES = 7             # was 5 — 7+ strikes filters routine index noise
MIN_VOL_PER_STRIKE = 100    # under this, the strike doesn't count
MIN_NOTIONAL_PER_STRIKE = 25_000
ASK_BIAS_THRESHOLD = 0.55   # >= 55% of side reads "ASK" -> qualifying
BASKET_MIN_NOTIONAL = 2_000_000  # was 500K — institutional-only floor

# Index products generate basket noise by design — they have dozens of
# liquid strikes per expiration and market-makers fill across the curve.
# Skip them entirely; their institutional positioning surfaces through
# the GEX wall + flow_alerts paths instead.
TICKER_BLOCKLIST = {"SPX", "SPXW", "NDX", "RUT", "VIX", "SPY", "QQQ", "IWM", "DIA"}

# Dedup state: (ticker, exp, otype, sentiment) -> (last_ts, last_count, last_notional)
_basket_dedup: dict[tuple[str, str, str, str], tuple[float, int, float]] = {}
DEDUP_WINDOW_SECONDS = 7200      # was 3600 — 2-hour window per (ticker, exp, type)
GROWTH_REFIRE_THRESHOLD = 1.0    # was 0.5 — require basket to DOUBLE before re-firing


def _strike_is_qualifying(
    opt: dict[str, Any],
    side: str,
    otype: str,
) -> bool:
    """A single strike counts toward a basket if it shows directional bias.

    For CALLS: ASK-side = bullish accumulation (buy calls).
    For PUTS:  ASK-side = bearish accumulation (buy puts) OR BID-side =
               bullish (sell puts, premium-collect). We treat the BID-side
               put basket as bullish because that's the structural signal
               that mirrors the 5/12 MU 1/15/27 $1000P whale write.

    Either way, the basket detector groups by direction so both patterns
    fire as separate baskets when they exist.
    """
    vol = int(opt.get("volume") or 0)
    last = float(opt.get("last") or 0)
    if vol < MIN_VOL_PER_STRIKE:
        return False
    if vol * last * 100 < MIN_NOTIONAL_PER_STRIKE:
        return False
    return side in ("ASK", "BID")


def _basket_sentiment(otype: str, side: str) -> str:
    """Same logic as flow_alerts._detect_sentiment but isolated for clarity."""
    if otype == "call":
        return "BULLISH" if side == "ASK" else "BEARISH"
    # puts
    return "BEARISH" if side == "ASK" else "BULLISH"


def _should_fire(
    key: tuple[str, str, str, str],
    strike_count: int,
    aggregate_notional: float,
) -> bool:
    """Dedup gate. Fires on first detection, re-fires on 50%+ growth."""
    now = time.time()
    last = _basket_dedup.get(key)
    if last is None:
        return True
    last_ts, last_count, last_notional = last
    # Same window, growth check
    if now - last_ts < DEDUP_WINDOW_SECONDS:
        count_growth = (strike_count - last_count) / max(last_count, 1)
        notional_growth = (
            (aggregate_notional - last_notional) / max(last_notional, 1.0)
        )
        if count_growth < GROWTH_REFIRE_THRESHOLD and notional_growth < GROWTH_REFIRE_THRESHOLD:
            return False
    # Out of window, or growth threshold met
    return True


def _record_fired(
    key: tuple[str, str, str, str],
    strike_count: int,
    aggregate_notional: float,
) -> None:
    _basket_dedup[key] = (time.time(), strike_count, aggregate_notional)


async def detect_baskets() -> list[dict[str, Any]]:
    """Scan the chain cache for multi-strike basket accumulation patterns.

    Returns a list of basket-alert dicts. The worker cycle is expected to
    iterate the returned list and fire Telegram + persist to DB as needed.

    Walks the worker's _chain_cache directly (avoiding a second Tradier
    fetch) and groups by (ticker, expiration, option_type), then applies
    the per-strike + aggregate gates.
    """
    # Lazy import to avoid circular dep with worker
    from .worker import _chain_cache
    from .flow_alerts import _detect_side
    from .tick_side_tracker import get_tracker as _get_tracker

    # Group cache: key = (ticker, expiration) -> list of (opt, side, otype)
    groups: dict[tuple[str, str], list[tuple[dict, str, str]]] = {}

    snapshot = await cache.snapshot()

    for cache_key, (ts, contracts) in list(_chain_cache.items()):
        # cache_key format: "TICKER:YYYY-MM-DD"
        if ":" not in cache_key:
            continue
        ticker, exp_date = cache_key.split(":", 1)
        # Skip index products — too noisy for the basket-as-conviction
        # signal (dozens of liquid strikes per expiration by design).
        if ticker in TICKER_BLOCKLIST:
            continue
        for opt in contracts:
            otype = (opt.get("option_type") or "").lower()
            if otype not in ("call", "put"):
                continue
            strike = float(opt.get("strike", 0))
            bid = float(opt.get("bid") or 0)
            ask = float(opt.get("ask") or 0)
            last = float(opt.get("last") or 0)
            greeks = opt.get("greeks") or {}
            delta = float(greeks.get("delta") or 0)

            # Prefer tick tracker (real OPRA-grade side); fall back to
            # the improved snapshot detector with delta/V-O-I bias.
            tracker_side = _get_tracker().latest_side(
                ticker, strike, exp_date, otype,
            )
            vol = int(opt.get("volume") or 0)
            oi = int(opt.get("open_interest") or 0)
            if tracker_side is None:
                est_notional = vol * last * 100 if last > 0 else 0
                side = _detect_side(
                    bid, ask, last,
                    delta=delta, vol=vol, oi=oi, notional=est_notional,
                )
            else:
                side = tracker_side
            groups.setdefault((ticker, exp_date), []).append((opt, side, otype))

    alerts: list[dict[str, Any]] = []

    for (ticker, exp_date), opts in groups.items():
        # Get spot for context
        spot = 0.0
        st = snapshot.get(ticker)
        if st:
            spot = st.get("actual_spot") or st.get("_spot") or 0.0

        # Sub-bucket by (option_type, sentiment) — call+ASK is bullish basket,
        # put+BID is bullish basket, call+BID is bearish basket, put+ASK is
        # bearish basket. Each fires as its own pattern.
        sub: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for opt, side, otype in opts:
            if not _strike_is_qualifying(opt, side, otype):
                continue
            sentiment = _basket_sentiment(otype, side)
            sub.setdefault((otype, sentiment), []).append(opt)

        for (otype, sentiment), basket_opts in sub.items():
            if len(basket_opts) < MIN_STRIKES:
                continue
            aggregate_vol = sum(int(o.get("volume") or 0) for o in basket_opts)
            aggregate_notional = sum(
                int(o.get("volume") or 0) * float(o.get("last") or 0) * 100
                for o in basket_opts
            )
            if aggregate_notional < BASKET_MIN_NOTIONAL:
                continue

            key = (ticker, exp_date, otype, sentiment)
            if not _should_fire(key, len(basket_opts), aggregate_notional):
                continue
            _record_fired(key, len(basket_opts), aggregate_notional)

            strike_summary = sorted(
                [
                    {
                        "strike": float(o.get("strike", 0)),
                        "vol": int(o.get("volume") or 0),
                        "last": float(o.get("last") or 0),
                        "notional": int(o.get("volume") or 0)
                        * float(o.get("last") or 0) * 100,
                    }
                    for o in basket_opts
                ],
                key=lambda x: x["strike"],
            )
            alerts.append({
                "ticker": ticker,
                "expiration": exp_date,
                "option_type": otype,
                "sentiment": sentiment,
                "strike_count": len(basket_opts),
                "aggregate_vol": aggregate_vol,
                "aggregate_notional": round(aggregate_notional),
                "strike_low": strike_summary[0]["strike"],
                "strike_high": strike_summary[-1]["strike"],
                "spot": spot,
                "strikes": strike_summary,
                "ts": time.time(),
            })

    return alerts


def reset_dedup_state() -> None:
    """Clear dedup state — only used in tests."""
    _basket_dedup.clear()
