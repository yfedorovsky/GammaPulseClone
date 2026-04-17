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
import time
from collections import defaultdict
from typing import Any

from .cache import cache
from .config import get_settings
from .gex import build_signal, compute_exp_data
from .massive import MassiveClient, enrich_contracts_with_massive
from .rts import compute_rts
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

# Aggressive caches to minimize API calls
_exp_cache: dict[str, tuple[float, list[str]]] = {}  # ticker → (ts, [exps])
_chain_cache: dict[str, tuple[float, list[dict]]] = {}  # "ticker:exp" → (ts, [contracts])

EXP_TTL = 3600  # 1 hour — expirations rarely change
CHAIN_TTL = 120  # 2 minutes — matches the scan cycle


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
        if time.time() - ts < CHAIN_TTL:
            return contracts
    return None


async def _fetch_chain_cached(
    tradier: TradierClient, ticker: str, max_exp: int = 12
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch chain with aggressive caching. Only hits API for stale data."""
    # Expirations: cached for 1 hour
    exps = _exp_fresh(ticker)
    if exps is None:
        exps = await tradier.expirations(ticker)
        _exp_cache[ticker] = (time.time(), exps)

    if not exps:
        return [], []
    exps = exps[:max_exp]

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

import datetime as _dt

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
    massive: MassiveClient | None = None,
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

    # Enrich with Massive real-time Greeks (if available)
    greeks_source = "tradier"
    greeks_ts = time.time()
    if massive:
        try:
            # Compute expiration range from the contracts we have
            all_exps = sorted(set(c.get("expiration_date", "") for c in contracts if c.get("expiration_date")))
            exp_gte = all_exps[0] if all_exps else ""
            exp_lte = all_exps[-1] if all_exps else ""

            massive_greeks, m_ts = await massive.snapshot_greeks(
                ticker, expiration_gte=exp_gte, expiration_lte=exp_lte
            )
            if massive_greeks:
                contracts = enrich_contracts_with_massive(contracts, massive_greeks, m_ts)
                greeks_source = "massive"
                greeks_ts = m_ts

                # Spot-consistency check: compare Massive's underlying vs Tradier spot
                from .massive import get_massive_spot
                m_spot = get_massive_spot(ticker)
                if m_spot and spot and abs(m_spot - spot) / spot > 0.003:
                    pct_diff = abs(m_spot - spot) / spot * 100
                    print(f"[GEX_STALE_SPOT] {ticker}: Tradier=${spot:.2f} Massive=${m_spot:.2f} ({pct_diff:.1f}% divergence)")
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
    }

    # Compute Mir momentum signal for approved sector tickers
    mir_signal = _compute_mir_signal(ticker, spot, state.get("_rts"))
    if mir_signal:
        state["_mir_signal"] = mir_signal

    return state


async def _scan_cycle(
    tradier: TradierClient, cycle_num: int, massive: MassiveClient | None = None
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

    source_label = "tradier+massive" if massive else "tradier"
    await cache.set_status(f"Running Cycle... [{source_label}] 0/{len(targets)}")

    # Batch spot quotes with volume data (1 API call per 50 tickers — very cheap)
    quotes_full = await tradier.quotes_full(targets)
    quotes = {sym: q["last"] for sym, q in quotes_full.items() if q.get("last")}

    # Process with concurrency control. Thanks to the chain cache, repeat
    # cycles only fetch chains that expired from cache (2min TTL). First
    # cycle is the most expensive; subsequent cycles are mostly cache hits.
    sem = asyncio.Semaphore(4)
    processed = 0

    # Massive Greeks: first cycle = all, then Tier 1 every cycle, Tier 2+3 every other
    def _use_massive(t: str) -> MassiveClient | None:
        if not massive:
            return None
        if is_first_cycle:
            return massive  # First cycle: Massive for everything
        tier = tier_of(t)
        if tier == 1:
            return massive  # Always use Massive for majors
        if cycle_num % 2 == 0:
            return massive  # Even cycles: Massive for all
        return None  # Odd cycles: Tradier-only for Tier 2+3

    async def process(t: str) -> None:
        nonlocal processed
        spot = quotes.get(t)
        if not spot:
            return
        async with sem:
            try:
                state = await _compute_one(
                    tradier, t, spot,
                        max_exp=12 if tier_of(t) <= 2 else 6,
                        massive=_use_massive(t)
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


async def run_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    tradier = TradierClient()

    # Initialize Massive client for real-time Greeks (if configured)
    massive: MassiveClient | None = None
    if settings.use_massive_greeks and settings.massive_api_key:
        massive = MassiveClient()
        print("[worker] Massive Greeks enabled — real-time delta/gamma/vega/IV")
    else:
        print("[worker] Massive not configured — using Tradier Greeks (hourly)")

    try:
        cycle = 0
        while not stop_event.is_set():
            cycle += 1
            try:
                await _scan_cycle(tradier, cycle, massive)
            except Exception as e:  # noqa: BLE001
                await cache.set_status(f"Cycle error: {e!r}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.scan_interval_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await tradier.close()
        if massive:
            await massive.close()
