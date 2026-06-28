"""Background scanner worker.

Optimization: cache expirations + chain data aggressively. Per your buddy's
advice — "the chain endpoint gives you everything in one shot, cache it
aggressively." Tradier requires per-expiration calls, but we cache the
expiration list (1h TTL) and chain data (2min TTL) so repeat cycles are
mostly cache hits.

Flow per cycle:
  1. Batch spot quotes (1 API call per 50 tickers)
  2. For each ticker, check if cached chain is fresh (< 2 min old)
  3. If stale: fetch expirations (cached 1h) + chains (N calls)
  4. Compute GEX, store in cache + snapshot
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import time
from collections import defaultdict
from typing import Any

from .cache import cache
from .config import get_settings
from .gex import build_signal, compute_exp_data
from .massive import MassiveClient, enrich_contracts_with_massive
from .thetadata import (
    ThetaDataClient,
    enrich_contracts_with_thetadata,
    get_theta_spot,
    snapshot_greeks as theta_snapshot_greeks,
)
from .rts import compute_rts
from .ibd_groups import get_ibd_group_info as _ibd_group_info
from .ibd_sector_leaders import is_sector_leader as _is_sector_leader
from .snapshots import (
    insert_async as snapshot_insert,
    compute_ivp,
    compute_realized_vol,
    get_daily_closes,
)
from .tickers import all_tickers, tier_of
from .tradier import TradierClient


MACRO_KEY = "MACRO (ALL 200D)"

# Spot divergence tracker: ticker -> pct divergence (Massive vs Tradier)
_spot_stale_flag: dict[str, float] = {}
# #69: throttle the [GEX_STALE_SPOT] log. A persistently-bad Theta reference
# spot (e.g. KLAC, or XLP $218-vs-$84) diverges EVERY cycle, which spammed
# ~39 lines/cycle. GEX itself uses the Tradier `spot`, never this Theta value,
# so divergence is cosmetic. We still set _spot_stale_flag every cycle (the API
# flag stays live-accurate); only the LOG line is rate-limited per ticker.
_spot_stale_log_ts: dict[str, float] = {}
_STALE_LOG_THROTTLE_S = 600  # at most one log per ticker per 10 min


def _should_log_stale_spot(ticker: str) -> bool:
    """True at most once per _STALE_LOG_THROTTLE_S per ticker (log de-spam)."""
    now = time.time()
    if now - _spot_stale_log_ts.get(ticker, 0.0) >= _STALE_LOG_THROTTLE_S:
        _spot_stale_log_ts[ticker] = now
        return True
    return False

# Aggressive caches to minimize API calls
_exp_cache: dict[str, tuple[float, list[str]]] = {}  # ticker → (ts, [exps])
_chain_cache: dict[str, tuple[float, list[dict]]] = {}  # "ticker:exp" → (ts, [contracts])

EXP_TTL = 3600  # 1 hour — expirations rarely change
CHAIN_TTL = 120  # 2 minutes — matches the scan cycle (default)

# Close-window boost (Bug #3 fix, 2026-05-12).
# Between 15:30 and 16:15 ET, drop CHAIN_TTL to 45s so the worker re-fetches
# chain data on every 60-second scan cycle. Captures late-day institutional
# prints (FL0WG0D's 3:45 PM MU/SLV/GLD alerts were 14-25 min late under the
# default 120s TTL — many cycles were cache-hits on stale data). The window
# is bounded to a 45-min span so total API budget impact is small.
CLOSE_WINDOW_CHAIN_TTL = 45  # seconds
CLOSE_WINDOW_START = (15, 30)  # 15:30 ET
CLOSE_WINDOW_END = (16, 15)    # 16:15 ET (matches alert RTH cutoff)


def _in_close_window(now: _dt.datetime | None = None) -> bool:
    """True if local time is in the 15:30-16:15 close-window boost band.

    Assumes server clock is in Eastern Time, which matches the rest of the
    codebase's RTH gating (see flow_alerts._is_rth_now). If you ever move
    the server to a different TZ, gate this with a TZ-aware datetime.
    """
    now = now or _dt.datetime.now()
    if now.weekday() >= 5:
        return False  # weekends never boost
    if is_market_holiday(now.date()):
        return False  # holidays never boost
    hm = (now.hour, now.minute)
    return CLOSE_WINDOW_START <= hm < CLOSE_WINDOW_END


def _effective_chain_ttl() -> int:
    """Pick the active chain TTL based on time of day."""
    return CLOSE_WINDOW_CHAIN_TTL if _in_close_window() else CHAIN_TTL

# Smart expiration selector tiers (Bug #1 fix, 2026-05-12).
# Triggered by MU 1/15/27 $1000P miss ($257M whale, fully outside chain due to
# `exps[:max_exp]` cap). Prior behavior dropped LEAPs silently for any ticker
# with more than `max_exp` listed expirations. New selector guarantees LEAP
# coverage by tier rather than by raw count.
NEAR_TERM_DAYS = 45     # always include all weeklies + near monthlies <= 45 DTE
MID_TERM_MONTHLIES = 6  # next 6 monthly expirations after near-term band
# LEAP threshold lowered 270 -> 200 days (2026-05-12). MU 2027-01-15 sits at
# 248 DTE on 5/12/26 — under the old 270 threshold it was a "mid-term
# monthly", and got bumped out of the bucket as the 7th monthly when the
# chain included a (rare) November monthly. 200 DTE captures any monthly
# in the 7-12 month band as a LEAP, guaranteeing inclusion.
LEAP_THRESHOLD_DAYS = 200


def _exp_fresh(ticker: str) -> list[str] | None:
    if ticker in _exp_cache:
        ts, exps = _exp_cache[ticker]
        if time.time() - ts < EXP_TTL:
            return exps
    return None


def _chain_fresh(ticker: str, exp: str) -> list[dict] | None:
    key = f"{ticker}:{exp}"
    if key in _chain_cache:
        ts, contracts = _chain_cache[key]
        # TTL adapts to close-window boost — see _effective_chain_ttl.
        if time.time() - ts < _effective_chain_ttl():
            return contracts
    return None


def _dte(exp: str, today: _dt.date | None = None) -> int:
    """Calendar days from today to exp ('YYYY-MM-DD'). Returns 99999 on parse fail."""
    try:
        d = _dt.date.fromisoformat(exp)
    except (ValueError, TypeError):
        return 99999
    base = today or _dt.date.today()
    return (d - base).days


def _is_third_friday(exp: str) -> bool:
    """True if exp is the 3rd Friday of its month (standard monthly OPEX)."""
    try:
        d = _dt.date.fromisoformat(exp)
    except (ValueError, TypeError):
        return False
    return d.weekday() == 4 and 15 <= d.day <= 21


def _select_expirations(exps: list[str], max_exp: int) -> list[str]:
    """Pick expirations to scan, guaranteeing LEAP coverage.

    Selection tiers (in order, deduped, capped at 2*max_exp for safety):
      1. All <= NEAR_TERM_DAYS DTE      (every weekly + near monthly)
      2. Next MID_TERM_MONTHLIES monthly OPEX expirations after near-term
      3. ALL >= LEAP_THRESHOLD_DAYS DTE (every LEAP)
      4. Fill remaining slots up to max_exp with whatever's left, in DTE order

    Returns expirations in chronological order. The 2*max_exp ceiling
    prevents pathological cases (e.g., a symbol with 20+ LEAP expirations)
    from blowing up the Tradier API budget. In practice, most equity LEAP
    chains list 4-6 expirations (Jan/Jun cycles for 1-2 years out), so the
    ceiling is rarely hit.
    """
    if not exps:
        return []

    near = [e for e in exps if _dte(e) <= NEAR_TERM_DAYS]
    mid = [
        e for e in exps
        if NEAR_TERM_DAYS < _dte(e) < LEAP_THRESHOLD_DAYS and _is_third_friday(e)
    ][:MID_TERM_MONTHLIES]
    leaps = [e for e in exps if _dte(e) >= LEAP_THRESHOLD_DAYS]

    # Dedup while preserving chronological order
    seen: set[str] = set()
    selected: list[str] = []
    for bucket in (near, mid, leaps):
        for e in bucket:
            if e not in seen:
                seen.add(e)
                selected.append(e)

    # If we still have budget, fill with whatever's left (e.g., extra non-OPEX
    # mid-term expirations for symbols with rich chains).
    if len(selected) < max_exp:
        for e in exps:
            if e not in seen and len(selected) < max_exp:
                seen.add(e)
                selected.append(e)

    # Safety ceiling: even if all three buckets are huge, cap at 2*max_exp.
    ceiling = max(max_exp, 2 * max_exp)
    selected = selected[:ceiling]
    selected.sort(key=_dte)
    return selected


async def _fetch_chain_cached(
    tradier: TradierClient, ticker: str, max_exp: int = 12
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch chain with aggressive caching. Only hits API for stale data."""
    # P2 (5/13): hot tickers (had a $1M+ alert in the last 30 min) get
    # +4 expirations of coverage so secondary/leg prints further out on
    # the curve don't slip through the default cap. The chain cache TTL
    # (120s normal / 45s close-window) is already aggressive enough that
    # we don't need to bust it — newly-listed strikes will appear within
    # one cycle of CBOE adding them.
    try:
        from .hot_chain import is_hot, HOT_CHAIN_MAX_EXP_BUMP
        if is_hot(ticker):
            max_exp = max_exp + HOT_CHAIN_MAX_EXP_BUMP
    except Exception:
        pass

    # Expirations: cached for 1 hour
    exps = _exp_fresh(ticker)
    if exps is None:
        exps = await tradier.expirations(ticker)
        _exp_cache[ticker] = (time.time(), exps)

    if not exps:
        return [], []
    # Smart selection: always include LEAPs (Bug #1 fix). Replaces the prior
    # `exps[:max_exp]` slice that silently dropped any LEAPs past position 12.
    exps = _select_expirations(exps, max_exp)

    # Chains: cached for 2 minutes per expiration
    all_contracts: list[dict[str, Any]] = []
    fetch_exps: list[str] = []
    for e in exps:
        cached = _chain_fresh(ticker, e)
        if cached is not None:
            all_contracts.extend(cached)
        else:
            fetch_exps.append(e)

    # Only fetch the stale expirations
    if fetch_exps:
        results = await asyncio.gather(
            *(tradier.chain(ticker, e) for e in fetch_exps),
            return_exceptions=True,
        )
        for e, batch in zip(fetch_exps, results):
            if isinstance(batch, Exception):
                continue
            _chain_cache[f"{ticker}:{e}"] = (time.time(), batch)
            all_contracts.extend(batch)

    return all_contracts, exps


def _compute_rts_from_snapshots(ticker: str, spot: float) -> dict | None:
    """Compute RTS score from snapshot daily closes. Lightweight — no API calls."""
    closes = get_daily_closes(ticker, days=100)
    if len(closes) < 20:
        return None
    # Get SPY benchmark
    spy_closes = get_daily_closes("SPY", days=100)
    spy_returns = None
    if len(spy_closes) >= 20:
        from .rts import _compute_returns
        spy_returns = _compute_returns(spy_closes)
    rts = compute_rts(closes, spy_returns=spy_returns)
    rts["ticker"] = ticker
    return rts


def _compute_rv(ticker: str) -> float | None:
    """Compute 20-day realized vol for a ticker from snapshot history."""
    closes = get_daily_closes(ticker, days=30)
    return compute_realized_vol(closes, window=20)


def _compute_ivhv(iv: float | None, ticker: str) -> float | None:
    """Compute IV/HV ratio (Volatility Risk Premium proxy).

    IV/HV < 1.0  = options cheaper than realized (edge for long premium)
    IV/HV 1.0-1.2 = fair
    IV/HV > 1.5  = options expensive (edge for short premium)
    """
    if not iv or iv <= 0:
        return None
    rv = _compute_rv(ticker)
    if not rv or rv <= 0:
        return None
    # iv from compute_exp_data is in percentage (0-100), rv is decimal (0-1)
    iv_decimal = iv / 100 if iv > 1 else iv
    return round(iv_decimal / rv, 2)


# ── Trend Day Detection ─────────────────────────────────────────────
# Detects gap-and-go days where waiting for a pullback = missed entry.
# Computed once per day per ticker (first worker cycle captures the open).
# (datetime is imported as _dt at module top — needed earlier by
# _select_expirations / _dte helpers for the LEAP coverage selector.)

_gap_cache: dict[str, tuple[str, dict[str, Any]]] = {}  # ticker -> (date_str, result)


def _detect_trend_day(ticker: str, spot: float) -> dict[str, Any]:
    """Compare today's live spot to yesterday's close to detect gap days.

    Returns {gap_pct, trend_mode, gap_direction, prev_close}.
    Cached per day — first call captures approximate open for gap calc.
    """
    today = _dt.date.today().isoformat()
    cached = _gap_cache.get(ticker)
    if cached and cached[0] == today:
        return cached[1]

    closes = get_daily_closes(ticker, days=5)
    if not closes:
        result: dict[str, Any] = {
            "gap_pct": 0.0, "trend_mode": "NORMAL",
            "gap_direction": "FLAT", "prev_close": 0,
        }
        _gap_cache[ticker] = (today, result)
        return result

    prev_close = closes[-1]
    if prev_close <= 0:
        result = {
            "gap_pct": 0.0, "trend_mode": "NORMAL",
            "gap_direction": "FLAT", "prev_close": prev_close,
        }
        _gap_cache[ticker] = (today, result)
        return result

    gap_pct = round((spot - prev_close) / prev_close * 100, 2)
    abs_gap = abs(gap_pct)

    if abs_gap > 4.0:
        mode = "EXTREME_TREND"
    elif abs_gap > 2.0:
        mode = "TREND_DAY"
    else:
        mode = "NORMAL"

    direction = "UP" if gap_pct > 0 else "DOWN" if gap_pct < 0 else "FLAT"

    result = {
        "gap_pct": gap_pct,
        "trend_mode": mode,
        "gap_direction": direction,
        "prev_close": prev_close,
    }
    _gap_cache[ticker] = (today, result)
    return result


# ── Mir Momentum Scoring ─────────────────────────────────────────────
# Computes Mir's bullish momentum rules natively from snapshot data.
# Uses backtest/mir_scorer.py (standalone, no server deps).

try:
    from backtest.mir_scorer import (
        score_mir_pattern,
        MIR_APPROVED_TICKERS as _STATIC_MIR_TICKERS,
        MIR_SECTORS,
    )
    _MIR_AVAILABLE = True
except ImportError:
    _MIR_AVAILABLE = False
    _STATIC_MIR_TICKERS = set()
    MIR_SECTORS = {}

from .basket import get_basket_tickers, STOCK_SECTORS
from .market_calendar import is_market_holiday, is_rth_or_extended

_mir_cache: dict[str, tuple[str, dict[str, Any] | None]] = {}  # ticker -> (date_str, result)


def _compute_mir_signal(
    ticker: str, spot: float, state_rts: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Compute Mir momentum score for approved sector tickers.

    Returns a Mir signal dict if score >= 4.0/6, else None.
    Cached per day (momentum alignment is a daily condition).
    """
    if not _MIR_AVAILABLE:
        return None

    # PIT quarterly basket: only trade tickers in the active basket
    # Falls back to static MIR_APPROVED_TICKERS if basket not yet computed
    basket_tickers = get_basket_tickers()
    approved = basket_tickers if basket_tickers else _STATIC_MIR_TICKERS
    if ticker not in approved:
        return None

    # Day filter: Mondays have 34% WR vs 46-51% other days
    now = _dt.datetime.now()
    if now.weekday() == 0:
        return None

    # Daily cache: momentum alignment doesn't change intraday
    today = _dt.date.today().isoformat()
    cached = _mir_cache.get(ticker)
    if cached and cached[0] == today:
        return cached[1]

    if spot < 5:
        _mir_cache[ticker] = (today, None)
        return None

    # Regime filter: skip when SPY 20-day return < 0
    spy_closes = get_daily_closes("SPY", days=25)
    if len(spy_closes) >= 20:
        spy_ret = (spy_closes[-1] - spy_closes[-20]) / spy_closes[-20]
        if spy_ret < 0:
            _mir_cache[ticker] = (today, None)
            return None

    # Get price history for SMA/EMA checks
    closes = get_daily_closes(ticker, days=250)
    if len(closes) < 50:
        _mir_cache[ticker] = (today, None)
        return None

    # Quick SMA/EMA pre-filter (avoid expensive sector peer lookups)
    sma_20 = sum(closes[-20:]) / 20
    sma_50 = sum(closes[-50:]) / 50
    if spot <= sma_20 or spot <= sma_50:
        _mir_cache[ticker] = (today, None)
        return None

    # EMA 21 > EMA 50 check
    def _ema(data: list[float], period: int) -> float:
        if len(data) < period:
            return sum(data) / len(data)
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for val in data[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    ema_21 = _ema(closes, 21)
    ema_50 = _ema(closes, 50)
    if ema_21 <= ema_50:
        _mir_cache[ticker] = (today, None)
        return None

    # RTS filter: top quartile (score >= 70)
    if state_rts and state_rts.get("score", 0) < 70:
        _mir_cache[ticker] = (today, None)
        return None

    # Build sector peer histories for RS comparison
    # Use STOCK_SECTORS (SPDR mapping) for PIT basket peers
    sector_histories: dict[str, list[float]] = {}
    my_sector = STOCK_SECTORS.get(ticker)
    if my_sector:
        for peer, peer_sector in STOCK_SECTORS.items():
            if peer_sector == my_sector and peer != ticker:
                peer_closes = get_daily_closes(peer, days=100)
                if len(peer_closes) >= 20:
                    sector_histories[peer] = peer_closes

    # Score against Mir's 6 rules
    mir_score, reasons = score_mir_pattern(
        ticker, closes, dte=10, direction="BULL",
        sector_histories=sector_histories,
    )

    if mir_score >= 4.0:
        result: dict[str, Any] = {
            "ticker": ticker,
            "signal_type": "MIR_MOMENTUM",
            "option_type": "CALL",
            "conviction": "HIGH" if mir_score >= 5 else "MEDIUM",
            "mir_score": round(mir_score, 1),
            "mir_reasons": reasons,
            "direction": "BULL",
            "_computed_ts": time.time(),
        }
        _mir_cache[ticker] = (today, result)
        return result

    _mir_cache[ticker] = (today, None)
    return None


async def _compute_one(
    tradier: TradierClient,
    ticker: str,
    spot: float,
    max_exp: int = 6,
    greeks_client: Any = None,  # ThetaDataClient | MassiveClient | None
) -> dict[str, Any] | None:
    # SPX/NDX/RUT auto-fallback: if index chain is empty, use ETF equivalent
    INDEX_FALLBACK = {"SPX": "SPY", "NDX": "QQQ", "RUT": "IWM"}

    contracts, exps = await _fetch_chain_cached(tradier, ticker, max_exp)
    if not contracts and ticker in INDEX_FALLBACK:
        fallback = INDEX_FALLBACK[ticker]
        contracts, exps = await _fetch_chain_cached(tradier, fallback, max_exp)
        if contracts:
            print(f"[worker] {ticker} → fallback to {fallback}")
    if not contracts:
        return None

    # Enrich with real-time Greeks (Theta preferred; Massive kept as fallback path)
    greeks_source = "tradier"
    greeks_ts = time.time()
    if greeks_client is not None:
        try:
            # Compute expiration range from the contracts we have
            all_exps = sorted(set(c.get("expiration_date", "") for c in contracts if c.get("expiration_date")))
            exp_gte = all_exps[0] if all_exps else ""
            exp_lte = all_exps[-1] if all_exps else ""

            if isinstance(greeks_client, ThetaDataClient):
                # Theta path (primary, Apr 17 2026+)
                t_greeks, t_ts = await theta_snapshot_greeks(
                    greeks_client, ticker, expiration_gte=exp_gte, expiration_lte=exp_lte
                )
                if t_greeks:
                    contracts = enrich_contracts_with_thetadata(contracts, t_greeks, t_ts)
                    greeks_source = "thetadata"
                    greeks_ts = t_ts

                    # Spot-consistency check: Theta's underlying vs Tradier spot.
                    # Threshold adapts to market hours:
                    #  - During RTH (9:30-16:00 ET): 0.3% — catches 0DTE staleness
                    #  - After hours / weekends: 10% — Theta's CTA/UTP feed is
                    #    15-min delayed for NYSE-listed names AND its reference
                    #    `underlying_price` field has been observed returning
                    #    wrong values for newly-tracked ETFs (e.g. XLP showed
                    #    $218 vs Tradier $84 on 2026-05-13 — clearly bogus, not
                    #    a feed-lag artifact). The old 2.0% AH threshold
                    #    spam-flagged the legit 4-6% leveraged-ETF AH lag.
                    #    10% is loose enough to silence that noise while still
                    #    catching outright wrongness (>10% divergence is never
                    #    feed-timing; it means Theta's reference data is bad).
                    t_spot = get_theta_spot(ticker)
                    if t_spot and spot:
                        import datetime as _dt
                        now = _dt.datetime.now()
                        # RTH = weekday & 9:30-16:00 ET (assumes server runs in ET)
                        in_rth = (
                            now.weekday() < 5
                            and (now.hour, now.minute) >= (9, 30)
                            and now.hour < 16
                        )
                        threshold = 0.003 if in_rth else 0.10
                        pct_diff = abs(t_spot - spot) / spot
                        if pct_diff > threshold:
                            if _should_log_stale_spot(ticker):
                                print(f"[GEX_STALE_SPOT] {ticker}: Tradier=${spot:.2f} Theta=${t_spot:.2f} ({pct_diff*100:.1f}% divergence; GEX uses Tradier — log throttled 10min)")
                            _spot_stale_flag[ticker] = round(pct_diff * 100, 2)
                        else:
                            _spot_stale_flag.pop(ticker, None)
                    else:
                        _spot_stale_flag.pop(ticker, None)

            elif isinstance(greeks_client, MassiveClient):
                # Massive path (retained as fallback for rollback through Apr 20)
                massive_greeks, m_ts = await greeks_client.snapshot_greeks(
                    ticker, expiration_gte=exp_gte, expiration_lte=exp_lte
                )
                if massive_greeks:
                    contracts = enrich_contracts_with_massive(contracts, massive_greeks, m_ts)
                    greeks_source = "massive"
                    greeks_ts = m_ts

                    from .massive import get_massive_spot
                    m_spot = get_massive_spot(ticker)
                    if m_spot and spot and abs(m_spot - spot) / spot > 0.003:
                        pct_diff = abs(m_spot - spot) / spot * 100
                        if _should_log_stale_spot(ticker):
                            print(f"[GEX_STALE_SPOT] {ticker}: Tradier=${spot:.2f} Massive=${m_spot:.2f} ({pct_diff:.1f}% divergence; log throttled 10min)")
                        _spot_stale_flag[ticker] = round(pct_diff, 2)
                    else:
                        _spot_stale_flag.pop(ticker, None)
        except Exception as e:
            # Silently fall back to Tradier Greeks
            pass

    # Group by expiration
    by_exp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in contracts:
        exp = c.get("expiration_date") or ""
        if exp:
            by_exp[exp].append(c)

    if not by_exp and contracts:
        print(f"[worker] WARNING: {ticker} has {len(contracts)} contracts but 0 grouped by exp — missing expiration_date field?")

    exp_data: dict[str, dict[str, Any]] = {}
    for exp, batch in by_exp.items():
        exp_data[exp] = compute_exp_data(batch, spot)

    # MACRO = all merged
    exp_data[MACRO_KEY] = compute_exp_data(contracts, spot)

    # Decorate per-cell strikes with intraday % change vs open. Skylit
    # heatseeker-style: shows "+11%" / "-3%" badges indicating which specific
    # strikes dealers are moving GEX into or out of during the session.
    # Safe to call before market open — it's a no-op.
    try:
        from .cell_history import snapshot_and_decorate
        for exp, ed in exp_data.items():
            if ed and ed.get("strikes"):
                snapshot_and_decorate(ticker, exp, ed["strikes"])
    except Exception as e:
        # Never let cell-history failures break a cycle — it's informational
        print(f"[worker] cell_history decorate failed for {ticker}: {e}")

    macro = exp_data[MACRO_KEY]
    signal, regime, king_pos = build_signal(macro, spot)

    # Push SPY/QQQ dealer-structure to the market-structure cache (task #54
    # Layer 3) so the flow-alert scorer can read the index short-gamma tape
    # synchronously (bear-day guardrail). update_index_structure() filters to
    # the index tickers internally, so this is a cheap no-op for everything
    # else. Never let it break a scan cycle.
    #
    # #62 (4-LLM synthesis 6/8): the STRUCTURAL regime read anchors on SETTLED
    # OI (oi_mode="raw"), not the volume-adjusted/effective OI used for the MACRO
    # above. All 4 LLMs converged: effective OI is for intraday/0DTE level
    # identification; settled OI is the cleaner base for the dealer-positioning
    # regime (it's about inventories/open positions, not same-day churn). We pay
    # the extra compute ONLY for the index tickers the cache retains.
    try:
        from .structure_regime import update_index_structure, STRUCTURE_INDEX_TICKERS
        if ticker.upper() in STRUCTURE_INDEX_TICKERS:
            macro_settled = compute_exp_data(contracts, spot, oi_mode="raw")
            update_index_structure(ticker, macro_settled, spot)
    except Exception as e:
        print(f"[worker] structure update failed for {ticker}: {e!r}", flush=True)

    # Compute Greeks freshness
    greeks_age = time.time() - greeks_ts

    state: dict[str, Any] = {
        "actual_spot": spot,
        "_spot": spot,
        "king": macro["king"],
        "floor": macro["floor"],
        "ceiling": macro["ceiling"],
        "pos_gex": macro["pos_gex"],
        "neg_gex": macro["neg_gex"],
        "net_delta": macro["net_delta"],
        "net_vanna": macro["net_vanna"],
        "iv": macro["iv"],
        "signal": signal,
        "regime": regime,
        "king_pos": king_pos,
        "zgl": macro["zgl"],
        "exp_data": exp_data,
        "_raw_contracts": dict(by_exp),  # Raw Tradier contracts by exp (for contract selection)
        "exps": [MACRO_KEY] + sorted(by_exp.keys()),
        "spot": spot,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_tier": tier_of(ticker),
        "_greeks_source": greeks_source,
        "_greeks_ts": greeks_ts,
        "_greeks_age_seconds": round(greeks_age, 1),
        "_quote_ts": time.time(),  # spot quote timestamp (Tradier streaming/polling)
        "_ticker": ticker,
        "_ivp": compute_ivp(ticker, macro["iv"]) if macro.get("iv") else None,
        "_realized_vol": _compute_rv(ticker),
        "_ivhv_ratio": _compute_ivhv(macro.get("iv"), ticker),
        "_rts": _compute_rts_from_snapshots(ticker, spot),
        "_trend_day": _detect_trend_day(ticker, spot),
        "_greeks_spot_stale": ticker in _spot_stale_flag,
        "_greeks_spot_divergence": _spot_stale_flag.get(ticker, 0),
        # IBD industry group rotation layer (Apr 19 addition)
        # Static table in server/ibd_groups.py; null when ticker not mapped.
        "_ibd_group": _ibd_group_info(ticker),
        # IBD Sector Leaders — O'Neil's ≤16 curated list (Apr 20 addition).
        # Binary: in or out. Membership = full CAN-SLIM pass.
        "_ibd_sector_leader": _is_sector_leader(ticker),
    }

    # Compute Mir momentum signal for approved sector tickers
    mir_signal = _compute_mir_signal(ticker, spot, state.get("_rts"))
    if mir_signal:
        state["_mir_signal"] = mir_signal

    # Detector B (opex_pin_detector): maintain the OPEX-pin armed registry at GEX
    # cadence so Detector A can qualify single-name velocity breaks. Cheap no-op
    # off-OPEX; never break a scan cycle.
    try:
        from .opex_pin_detector import arm_from_state
        arm_from_state(ticker, state)
    except Exception as e:
        print(f"[worker] pin-arm eval failed for {ticker}: {e!r}", flush=True)

    return state


async def _scan_cycle(
    tradier: TradierClient, cycle_num: int, greeks_client: Any = None
) -> None:
    settings = get_settings()

    # First cycle after restart: scan EVERYTHING (catch-up mode)
    # Subsequent cycles: Tier 1 every cycle, Tier 2+3 alternate
    is_first_cycle = cycle_num <= 1
    targets: list[str] = []
    for t in all_tickers():
        tier = tier_of(t)
        if is_first_cycle or tier == 1:
            targets.append(t)
        elif tier == 2 and cycle_num % 2 == 0:
            targets.append(t)
        elif tier == 3 and cycle_num % 2 == 1:
            targets.append(t)
    if is_first_cycle:
        print(f"[worker] FIRST CYCLE — scanning ALL {len(targets)} tickers (catch-up)")

    if greeks_client is None:
        source_label = "tradier"
    elif isinstance(greeks_client, ThetaDataClient):
        source_label = "tradier+thetadata"
    else:
        source_label = "tradier+massive"
    await cache.set_status(f"Running Cycle... [{source_label}] 0/{len(targets)}")

    # Batch spot quotes with volume data (1 API call per 50 tickers — very cheap)
    quotes_full = await tradier.quotes_full(targets)
    quotes = {sym: q["last"] for sym, q in quotes_full.items() if q.get("last")}

    # Process with concurrency control. Thanks to the chain cache, repeat
    # cycles only fetch chains that expired from cache (TTL adapts to time
    # of day — see _effective_chain_ttl). Bumped 4 -> 6 on 2026-05-12 so
    # the per-cycle wall time stays under the 60s scan_interval target.
    # First cycle is the most expensive; subsequent cycles are mostly cache
    # hits except during the close-window boost (15:30-16:15 ET).
    sem = asyncio.Semaphore(6)
    processed = 0

    # Greeks enrichment cadence: first cycle = all, then Tier 1 every cycle, Tier 2+3 alternate
    def _pick_greeks_client(t: str) -> Any:
        if not greeks_client:
            return None
        if is_first_cycle:
            return greeks_client  # First cycle: Greeks for everything
        tier = tier_of(t)
        if tier == 1:
            return greeks_client  # Always enrich Tier 1 majors
        if cycle_num % 2 == 0:
            return greeks_client  # Even cycles: all tiers
        return None  # Odd cycles: Tradier-only for Tier 2+3

    async def process(t: str) -> None:
        nonlocal processed
        spot = quotes.get(t)
        if not spot:
            return
        async with sem:
            try:
                # max_exp is now a soft target (the selector adds LEAPs on
                # top regardless). Tier-1/2: 14 mid-term slots; Tier-3: 8.
                # Effective expirations scanned ≈ near-term band + monthlies
                # + LEAPs, typically 12-22 per ticker.
                state = await _compute_one(
                    tradier, t, spot,
                        max_exp=14 if tier_of(t) <= 2 else 8,
                        greeks_client=_pick_greeks_client(t)
                )
                if state is None:
                    return
                # Inject OHLCV data from quotes_full (swing scanner + runner tracker)
                qf = quotes_full.get(t) or {}
                state["_today_volume"] = qf.get("volume", 0)
                state["_avg_volume"] = qf.get("average_volume", 0)
                state["_today_open"] = qf.get("open")
                state["_today_high"] = qf.get("high")
                state["_today_low"] = qf.get("low")
                state["_prevclose"] = qf.get("prevclose")
                await cache.put(t, state)
                # Store Mir signal in cache (used by signal engine)
                if state.get("_mir_signal"):
                    await cache.set_mir_signal(t, state["_mir_signal"])
                await snapshot_insert(t, state)
                processed += 1
                if processed % 10 == 0:
                    src = state.get("_greeks_source", "tradier")
                    await cache.set_status(
                        f"Running Cycle... [{source_label}] {processed}/{len(targets)}"
                    )
            except Exception as e:  # noqa: BLE001
                await cache.set_status(f"Error on {t}: {e!r}")
                await asyncio.sleep(1)

    # Process in chunks with brief pauses
    for i in range(0, len(targets), 15):
        batch = targets[i : i + 15]
        await asyncio.gather(*(process(t) for t in batch))
        if i + 15 < len(targets):
            await asyncio.sleep(3)

    await cache.mark_cycle_end()

    # Update runner tracker (multi-day breakout state machine)
    try:
        from .runner_tracker import update_runners
        await update_runners()
    except Exception as e:
        print(f"[runner_tracker] Error: {e!r}")

    await cache.set_status("Idle (waiting for next cycle)")


# Module-level: track last date we persisted EOD OI snapshot (run once/day)
_last_oi_snapshot_date: str = ""


async def _maybe_snapshot_eod_oi() -> None:
    """Once per day at ~4:15 PM ET, walk cache.snapshot() and persist each
    ticker's OI by strike/exp/option_type to daily_oi_snapshot table.

    Used tomorrow to compute ΔOI vs today's live Tradier OI — a free
    flow-direction proxy per Priority 3 of the Option A action plan.
    """
    global _last_oi_snapshot_date
    import datetime as _dt
    now = _dt.datetime.now()

    # Window: 4:15 PM through end of day — allow catch-up if we miss the
    # first minute. Only fires once per date thanks to _last_oi_snapshot_date.
    if not (now.hour == 16 and now.minute >= 15) and now.hour < 17:
        return
    if now.weekday() >= 5:
        return
    if is_market_holiday(now.date()):
        return

    today_iso = _dt.date.today().isoformat()
    if _last_oi_snapshot_date == today_iso:
        return  # already ran today

    try:
        from .oi_delta import snapshot_ticker_oi, prune_old_snapshots
        snapshot = await cache.snapshot()
        total_rows = 0
        tickers_done = 0
        for ticker, state in snapshot.items():
            raw_contracts = state.get("_raw_contracts") or {}
            if not raw_contracts:
                continue
            rows = snapshot_ticker_oi(ticker, raw_contracts)
            total_rows += rows
            if rows > 0:
                tickers_done += 1
        pruned = prune_old_snapshots()
        _last_oi_snapshot_date = today_iso
        print(
            f"[worker] EOD OI snapshot: {total_rows} rows across {tickers_done} tickers, "
            f"pruned {pruned} older rows (retention 30d)"
        )
    except Exception as e:
        print(f"[worker] EOD OI snapshot failed: {e}")


async def warmup_indexes() -> None:
    """Pre-populate the cache with high-priority tickers so HEATMAPS /
    SCANNER have instant-load data on first visit after a cold start.

    Runs once at startup as a background task in parallel with the worker's
    first cycle. Without this, /api/chains?SPX was a 30-40s cache miss on
    boot (SPX has ±200 strike radius + ThetaData greeks = expensive).

    Scope:
      1. Index tickers first (SPY/QQQ/IWM/SPX/NDX/RUT/DIA/VIX) — critical
         path for the default MULTI panel.
      2. All remaining TIER_1 tickers (AI silicon / breakout names /
         mega caps) — high scanner priority.

    Safety:
      - Same math as _compute_one in the worker, so no data skew.
      - Semaphore(4) caps concurrency to match worker pattern — avoids
        blasting Tradier/ThetaData with 60 parallel calls.
      - Skips tickers already in cache (worker may beat us to some). This
        makes warmup + worker's first cycle race-safe with no duplicate
        work.
    """
    settings = get_settings()

    indexes = ["SPY", "QQQ", "IWM", "SPX", "NDX", "RUT", "DIA", "VIX"]
    # Import here to avoid circular dependency at module load
    from .tickers import TIER_1
    # 2026-06-02 PM: also prime Tier2 thematic names (RKLB, COIN, MSTR,
    # CRDO, ALAB, etc.) so the sweep_detector subscription planner has
    # spot prices when it runs. Without this, Tier2/flow_top/flow_mid/
    # flow_tail all show 0 contracts in the first cycle because
    # _subscribe_root() returns 0 when snapshot.get(root) has no spot.
    # This bug was masked at the old ±10% radius but became visible after
    # the Pro-tier upgrade widened Tier2 to ±50%.
    tier2_warmup: list[str] = []
    try:
        from .sweep_detector import TIER2_THEMATIC_ROOTS
        tier2_warmup = list(TIER2_THEMATIC_ROOTS)
    except Exception:
        pass
    # Index tickers first, then TIER_1, then TIER2 thematic, dedup
    seen: set[str] = set()
    ordered: list[str] = []
    for t in indexes + list(TIER_1) + tier2_warmup:
        if t not in seen and t in set(all_tickers()):
            ordered.append(t)
            seen.add(t)
    if not ordered:
        return

    tradier = TradierClient()
    greeks_client: Any = None
    if settings.use_thetadata_greeks:
        greeks_client = ThetaDataClient()
    elif settings.use_massive_greeks and settings.massive_api_key:
        greeks_client = MassiveClient()

    try:
        quotes_full = await tradier.quotes_full(ordered)
        quotes = {s: q["last"] for s, q in quotes_full.items() if q.get("last")}
        if not quotes:
            print("[WARMUP] No quotes returned — skipping warmup")
            return

        sem = asyncio.Semaphore(4)
        completed = 0
        skipped = 0

        async def warm(t: str) -> None:
            nonlocal completed, skipped
            # Skip if worker's first cycle already populated this ticker
            if await cache.get(t) is not None:
                skipped += 1
                return
            spot = quotes.get(t)
            if not spot:
                return
            async with sem:
                # Re-check inside the semaphore (worker may have caught up
                # while we were queued)
                if await cache.get(t) is not None:
                    skipped += 1
                    return
                try:
                    state = await _compute_one(
                        tradier, t, spot,
                        max_exp=14,  # LEAP-aware selector adds LEAPs on top
                        greeks_client=greeks_client,
                    )
                    if state is None:
                        return
                    qf = quotes_full.get(t) or {}
                    state["_today_volume"] = qf.get("volume", 0)
                    state["_avg_volume"] = qf.get("average_volume", 0)
                    await cache.put(t, state)
                    completed += 1
                except Exception as e:
                    # !r shows exception type + message (e.g. "ConnectTimeout()")
                    # so we don't get blank-after-colon when exc has no .args.
                    # flush=True belt-and-suspenders vs stdout buffering bugs
                    # (PYTHONUNBUFFERED handles it env-side too, but this is
                    # defense for runs without that flag).
                    print(f"[WARMUP] {t} failed: {e!r}", flush=True)

        t0 = time.time()
        n_tier2 = len(tier2_warmup) if tier2_warmup else 0
        n_tier1 = len(ordered) - 8 - n_tier2
        print(f"[WARMUP] Priming cache for {len(ordered)} tickers "
              f"(8 indexes + {n_tier1} TIER_1 + {n_tier2} TIER_2); concurrency=4")
        await asyncio.gather(*(warm(t) for t in ordered), return_exceptions=True)
        print(f"[WARMUP] Done in {time.time() - t0:.1f}s — "
              f"warmed={completed}, skipped_already_cached={skipped}")
    finally:
        await tradier.close()
        if greeks_client is not None:
            try:
                await greeks_client.close()
            except Exception:
                pass


async def _run_basket_detector() -> None:
    """Run the multi-strike basket detector and route alerts to Telegram.

    Bug #6 (2026-05-12). Called once per worker cycle from run_worker.
    Detector itself is RTH-gated via the per-strike volume floor (no vol
    outside hours), so we don't need a separate clock check here, but we
    DO want to swallow any per-cycle exception so a basket detector bug
    can't kill the cycle.
    """
    # Belt-and-suspenders RTH gate. Uses centralized market calendar so
    # weekends + US equity holidays both block off-hours scans on stale
    # cache. 2026-05-25: shipped market_calendar after Memorial Day
    # produced 93K stale alerts (worker re-fired Friday-close V/OI flow
    # on closed-market data). Holiday-aware. Module-level import (line 360).
    if not is_rth_or_extended():
        return

    from .basket_detector import detect_baskets
    from .telegram import send as tg_send, format_basket_alert
    from .earnings_calendar import get_next_er

    alerts = await detect_baskets()
    if not alerts:
        return
    print(f"[BASKET] fired {len(alerts)} basket alert(s)")
    for a in alerts:
        # P0.7: hydrate earnings cache for this ticker before formatting
        try:
            await get_next_er(a.get("ticker", ""))
        except Exception:
            pass
        text = format_basket_alert(a)
        # priority=True so baskets bypass the global 3/10min rate limit
        # (they're rare-but-important by design). Per-ticker cooldown
        # still applies, plus the detector's own internal dedup.
        await tg_send(text, ticker=a.get("ticker", ""), priority=True)


async def _run_spike_detector() -> None:
    """Run the intraday spike detector and route alerts to Telegram.

    P0.6 (2026-05-12). Called once per worker cycle from run_worker.
    Detector itself is RTH-gated and self-dedups per 5-min bucket so a
    burst that lasts multiple buckets gets one alert per bucket (not
    one per cycle).
    """
    from .spike_detector import detect_spikes, format_spike_alert
    from .telegram import send as tg_send
    from .earnings_calendar import get_next_er, earnings_badge_sync

    spikes = detect_spikes()
    if not spikes:
        return
    print(f"[SPIKE] fired {len(spikes)} spike alert(s)")
    for s in spikes:
        # P0.7: hydrate earnings cache; append ER badge if within window.
        try:
            await get_next_er(s["ticker"])
        except Exception:
            pass
        text = format_spike_alert(s)
        try:
            er = earnings_badge_sync(s["ticker"])
            if er:
                text = f"{text}\n{er}"
        except Exception:
            pass
        # priority=True — spike alerts are time-sensitive (5-min bucket
        # closed = signal is fresh-but-cooling within minutes).
        await tg_send(text, ticker=s["ticker"], priority=True)


async def _run_lotto_detector() -> None:
    """Surface cheap-OTM short-dated ASK-dominant accumulation patterns
    that are accelerating across scan cycles. Fires once per (ticker,
    strike, exp) per 90min so the operator gets the freshest crystallized
    pattern, not repeated noise."""
    from .lotto_ladder_detector import detect_lotto_ladders, format_lotto_alert
    from .telegram import send as tg_send
    from .earnings_calendar import get_next_er, earnings_badge_sync

    alerts = detect_lotto_ladders()
    if not alerts:
        return
    print(f"[LOTTO] fired {len(alerts)} lotto-ladder alert(s)")
    for a in alerts:
        try:
            await get_next_er(a["ticker"])
        except Exception:
            pass
        text = format_lotto_alert(a)
        try:
            er = earnings_badge_sync(a["ticker"])
            if er:
                text = f"{text}\n{er}"
        except Exception:
            pass
        # priority=True — these are by design the highest-leverage signals
        # the scanner produces; bypass global rate limit.
        await tg_send(text, ticker=a["ticker"], priority=True)


async def run_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    tradier = TradierClient()

    # Greeks enrichment source selection.
    # Priority: ThetaData (Apr 17, 2026+) → Massive (legacy fallback) → Tradier only.
    # The use_thetadata_greeks flag lets us hot-rollback to Massive if Theta hiccups.
    greeks_client: Any = None
    if settings.use_thetadata_greeks:
        greeks_client = ThetaDataClient()
        print("[worker] Theta Greeks enabled — real-time delta/theta/vega/IV via OPRA, gamma synthesized via BSM")
    elif settings.use_massive_greeks and settings.massive_api_key:
        greeks_client = MassiveClient()
        print("[worker] Massive Greeks enabled (legacy fallback) — real-time delta/gamma/vega/IV")
    else:
        print("[worker] No live Greeks provider — using Tradier Greeks (hourly, stale)")

    try:
        cycle = 0
        while not stop_event.is_set():
            cycle += 1
            try:
                await _scan_cycle(tradier, cycle, greeks_client)
                # EOD snapshot hook — self-gates to once/day at 4:15 PM
                await _maybe_snapshot_eod_oi()
                # Price-watch alerts (Mir setups, etc.) — self-gates dedup
                try:
                    from .price_watch import check_watches
                    snap = await cache.snapshot()
                    await check_watches(snap)
                except Exception as pw_err:
                    print(f"[worker] price_watch check failed: {pw_err}")
                # Swing scanner — refresh every 2 cycles (~4 min) so new
                # watchlist entrants fire Telegram alerts even when frontend
                # isn't polling. Internal hook fires alerts during market
                # hours only. Isolated try/except so failures can't kill cycle.
                if cycle % 2 == 0:
                    try:
                        from .swing_scanner import compute_swing_watchlist
                        await compute_swing_watchlist(mode="standard")
                    except Exception as sa_err:
                        print(f"[worker] swing_scanner refresh failed: {sa_err}")
                # Multi-strike basket detector — Bug #6 fix (2026-05-12).
                # Catches OTM-ladder accumulation patterns (e.g., MU 5/15
                # call buying across 12 strikes 800-1000 that no single-
                # strike alert can see). Self-dedups per (ticker, exp,
                # type, sentiment) on a 60-min rolling window. RTH-gated
                # inside the detector itself.
                try:
                    await _run_basket_detector()
                except Exception as bd_err:
                    print(f"[worker] basket_detector failed: {bd_err}")
                # End-of-day bullish-flow leaderboard digest. Self-gates to
                # 16:00-16:15 ET and dedup'd via in-memory date stamp so it
                # only fires once per trading day. Equivalent to Cheddar's
                # daily Bullish Flow sidebar — top tickers by aggregate
                # bullish premium (call-buy + put-write).
                try:
                    from .bullish_flow_leaderboard import maybe_fire_eod_leaderboard
                    await maybe_fire_eod_leaderboard()
                except Exception as lb_err:
                    print(f"[worker] leaderboard failed: {lb_err}")
                # Daily EOD RTS snapshot (task #56) — persists per-ticker
                # composite scores so we can compute acceleration/deceleration
                # (rate-of-change of relative strength). Self-gates to
                # 16:00-16:30 ET, once per day. Burn-in: deltas meaningful from
                # the 2nd recorded session.
                try:
                    from .rs_acceleration import maybe_record_eod_rts
                    await maybe_record_eod_rts(tradier)
                except Exception as rts_err:
                    print(f"[worker] rts history record failed: {rts_err}")
                # Intraday RS-DECOUPLE scan — a name pulling away from its sector
                # in real time (GLW 6/18: +6.9% vs Photonics/Fiber −4..−12%). Rare
                # by construction (2-4 / 467 names/day), prominent on purpose: cuts
                # through the flow firehose. RTH-gated + 5-min throttled internally.
                # CONTEXT attention flag, not a buy signal.
                try:
                    from .rs_decouple_detector import maybe_scan_rs_decouples
                    await maybe_scan_rs_decouples()
                except Exception as dc_err:
                    print(f"[worker] rs decouple scan failed: {dc_err}")
                # Cross-sector ROTATION + leading-sector RS leaderboard (#123):
                # one industry group broadly red while another broadly green
                # (the 6/26 semis-dump / healthcare-bid case rs_decouple's
                # SECTOR_MAX gate structurally suppressed). Sends the full sector
                # RS ranking + standout leaders so the operator can pivot fast.
                # RTH-gated + 5-min throttled internally. Shadow by default
                # (env ROTATION_ALERT_ACTIVE=1 to dispatch). CONTEXT, not a buy.
                try:
                    from .sector_rotation_alert import maybe_scan_rotation
                    await maybe_scan_rotation()
                except Exception as rot_err:
                    print(f"[worker] sector rotation scan failed: {rot_err}")
                # EOD RS-acceleration digest (swing complement to the intraday
                # decouple) — once/day 16:10-16:45 ET, who's climbing/rolling off
                # the relative-strength leaderboard over days.
                try:
                    from .rs_acceleration import maybe_fire_eod_accel_digest
                    await maybe_fire_eod_accel_digest()
                except Exception as ad_err:
                    print(f"[worker] rs accel digest failed: {ad_err}")
                # Refresh the index base-rate (Analogues) bias cache so the flow
                # scorer can tag alerts with market-context confluence (task #55
                # follow-up). Internally throttled to 30 min + 1h scan cache, and
                # run in a thread so the network fetch never blocks the loop.
                try:
                    import asyncio as _aio
                    from .analogue_confluence import refresh_market_bias
                    await _aio.to_thread(refresh_market_bias)
                except Exception as ac_err:
                    print(f"[worker] analogue bias refresh failed: {ac_err}")
                # Mir TP Window alert — daily 1:00-1:30 PM ET ping listing
                # open INFORMED FLOW + SOE A/A+ positions. Self-dedups to
                # once per ET calendar day. Cheap no-op outside window or
                # after first fire. 2026-05-28.
                try:
                    from .mir_tp_window import maybe_fire_mir_tp_alert
                    await maybe_fire_mir_tp_alert()
                except Exception as mir_err:
                    print(f"[worker] mir_tp_window failed: {mir_err}")
                # Semis pre-open briefing (2026-06-22) — one 🔬 SEMIS map ~9:10 ET,
                # once per market day. Flag SEMIS_BRIEFING (default on).
                try:
                    from .semis_briefing import maybe_fire_semis_briefing
                    await maybe_fire_semis_briefing()
                except Exception as sb_err:
                    print(f"[worker] semis_briefing failed: {sb_err}")
                # Semis high-conviction live tier (2026-06-22) — proven composites only
                # (INFORMED CLUSTER 3+ / WHALE $3M+) scoped to the semis watch legs,
                # self-contained off flow_alerts. Flag SEMIS_SIGNALS (default on).
                try:
                    from .semis_signals import maybe_fire_semis_signals
                    await maybe_fire_semis_signals()
                except Exception as ss_err:
                    print(f"[worker] semis_signals failed: {ss_err}")
                # Triple Confluence alert (2026-06-02) — fires when
                # INFORMED FLOW + king migration + SOE A/A+ all converge
                # on a ticker in same direction within a 4-hour rolling
                # window. Motivated by MRVL 5/28 missed signal: 4× INFORMED
                # FLOW + 4× A/A+ SOE + king migration all bullish in same
                # afternoon, but each fired separately. Composite alert
                # surfaces the convergence loudly. Once-per-ticker-per-
                # direction-per-day dedup.
                try:
                    from .triple_confluence import maybe_fire_triple_confluence
                    await maybe_fire_triple_confluence()
                except Exception as tc_err:
                    print(f"[worker] triple_confluence failed: {tc_err}")
                # Intraday spike detector (P0.6, 2026-05-12). Fires when a
                # ticker's 5-min flow bucket >= 10x today's baseline and
                # >= $5M absolute. Catches Fidget-style "18x surge" alerts
                # without needing tick-level OPRA. Self-dedups per bucket.
                try:
                    await _run_spike_detector()
                except Exception as sd_err:
                    print(f"[worker] spike_detector failed: {sd_err}")
                # Lotto-ladder detector (2026-05-13). Surfaces cheap-OTM
                # short-dated ASK-dominant accumulation that's accelerating
                # across scan cycles — the NVDA 5/15 $220C / FCEL 19C
                # archetype that goes 5-25x on next-day catalyst. The
                # existing flow_alerts catches these contracts but buries
                # them in 5000+ alerts/hour; this detector elevates ONLY
                # the cheap-OTM-pre-rip signature.
                try:
                    await _run_lotto_detector()
                except Exception as ll_err:
                    print(f"[worker] lotto_detector failed: {ll_err}")
            except Exception as e:  # noqa: BLE001
                await cache.set_status(f"Cycle error: {e!r}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.scan_interval_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await tradier.close()
        if greeks_client:
            await greeks_client.close()
