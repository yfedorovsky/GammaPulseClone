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
from .snapshots import insert as snapshot_insert
from .tickers import all_tickers, tier_of
from .tradier import TradierClient


MACRO_KEY = "MACRO (ALL 200D)"

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
    tradier: TradierClient, ticker: str, max_exp: int = 6
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


async def _compute_one(
    tradier: TradierClient, ticker: str, spot: float, max_exp: int = 6
) -> dict[str, Any] | None:
    contracts, exps = await _fetch_chain_cached(tradier, ticker, max_exp)
    if not contracts:
        return None

    # Group by expiration
    by_exp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in contracts:
        exp = c.get("expiration_date") or ""
        if exp:
            by_exp[exp].append(c)

    exp_data: dict[str, dict[str, Any]] = {}
    for exp, batch in by_exp.items():
        exp_data[exp] = compute_exp_data(batch, spot)

    # MACRO = all merged
    exp_data[MACRO_KEY] = compute_exp_data(contracts, spot)

    macro = exp_data[MACRO_KEY]
    signal, regime, king_pos = build_signal(macro, spot)

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
        "exps": [MACRO_KEY] + sorted(by_exp.keys()),
        "spot": spot,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_tier": tier_of(ticker),
    }
    return state


async def _scan_cycle(tradier: TradierClient, cycle_num: int) -> None:
    settings = get_settings()

    # Tiered scanning: Tier 1 every cycle, Tier 2+3 alternate → full coverage in 2 cycles.
    targets: list[str] = []
    for t in all_tickers():
        tier = tier_of(t)
        if tier == 1:
            targets.append(t)
        elif tier == 2 and cycle_num % 2 == 0:
            targets.append(t)
        elif tier == 3 and cycle_num % 2 == 1:
            targets.append(t)

    await cache.set_status(f"Running Cycle... [tradier] 0/{len(targets)}")

    # Batch spot quotes (1 API call per 50 tickers — very cheap)
    quotes = await tradier.quotes(targets)

    # Process with concurrency control. Thanks to the chain cache, repeat
    # cycles only fetch chains that expired from cache (2min TTL). First
    # cycle is the most expensive; subsequent cycles are mostly cache hits.
    sem = asyncio.Semaphore(4)
    processed = 0

    async def process(t: str) -> None:
        nonlocal processed
        spot = quotes.get(t)
        if not spot:
            return
        async with sem:
            try:
                state = await _compute_one(tradier, t, spot, max_exp=6)
                if state is None:
                    return
                await cache.put(t, state)
                snapshot_insert(t, state)
                processed += 1
                if processed % 10 == 0:
                    await cache.set_status(
                        f"Running Cycle... [tradier] {processed}/{len(targets)}"
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
    await cache.set_status("Idle (waiting for next cycle)")


async def run_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    tradier = TradierClient()
    try:
        cycle = 0
        while not stop_event.is_set():
            cycle += 1
            try:
                await _scan_cycle(tradier, cycle)
            except Exception as e:  # noqa: BLE001
                await cache.set_status(f"Cycle error: {e!r}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.scan_interval_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await tradier.close()
