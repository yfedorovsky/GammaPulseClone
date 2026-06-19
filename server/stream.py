"""SSE streaming and price subscription.

We maintain a set of subscribed tickers. Every STREAM_POLL_SECONDS we call
Tradier /markets/quotes for the whole set and push a single JSON blob to all
connected SSE clients.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from .config import get_settings
from .tradier import TradierClient


class PriceStreamer:
    def __init__(self) -> None:
        self.subs: set[str] = set()
        self._lock = asyncio.Lock()
        self._tradier: TradierClient | None = None
        self._task: asyncio.Task | None = None
        self._last: dict[str, float] = {}
        self._tick = 0

    async def subscribe(self, tickers: list[str]) -> list[str]:
        async with self._lock:
            for t in tickers:
                self.subs.add(t.upper())
            return sorted(self.subs)

    async def unsubscribe(self, tickers: list[str]) -> list[str]:
        async with self._lock:
            for t in tickers:
                self.subs.discard(t.upper())
            return sorted(self.subs)

    async def ensure_running(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._tradier:
            await self._tradier.close()

    async def _loop(self) -> None:
        settings = get_settings()
        self._tradier = TradierClient()
        while True:
            try:
                async with self._lock:
                    syms = sorted(self.subs)
                if syms:
                    prices = await self._tradier.quotes(syms)
                    if prices:
                        self._last = prices
                        self._tick += 1
                        _check_velocity_break(prices)
                await asyncio.sleep(settings.stream_poll_seconds)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(2.0)

    def last_prices(self) -> dict[str, float]:
        return dict(self._last)

    async def sse_iter(self) -> AsyncIterator[str]:
        settings = get_settings()
        last_tick = -1
        while True:
            if self._tick != last_tick and self._last:
                last_tick = self._tick
                yield f"data: {json.dumps(self._last)}\n\n"
            else:
                # Heartbeat / keepalive
                yield ": keepalive\n\n"
            await asyncio.sleep(settings.stream_poll_seconds)


streamer = PriceStreamer()


def _check_velocity_break(prices: dict) -> None:
    """Feed the 5s fresh-spot poll into Detector A (OPEX-day velocity break) and
    dispatch any fires. Fail-open: must never disrupt the price-poll cadence.
    Cheap no-op off-OPEX (returns before touching the monitor)."""
    try:
        import time as _t
        from .opex_velocity_detector import maybe_fire, format_fire
        fires = maybe_fire(prices, _t.time())
        for f in fires:
            print(f"[VELOCITY-BREAK] {f['ticker']} {f['ret_pct']:+.2f}% "
                  f"{f['from']:g}->{f['to']:g} in {f.get('window_s', 60):.0f}s",
                  flush=True)
            asyncio.create_task(_dispatch_velocity_break(f, format_fire(f)))
    except Exception:
        pass


async def _dispatch_velocity_break(fire: dict, text: str) -> None:
    try:
        from . import telegram
        await telegram.send(text, ticker=fire.get("ticker", ""), priority=True)
    except Exception:
        pass


def fresh_spot(ticker: str, state: dict | None = None) -> float:
    """Freshest available spot for flow-alert / side-detection use.

    #51 fix (2026-06-18): flow detectors read state['actual_spot']/['_spot'],
    which only refreshes on the worker's per-ticker GEX cadence (~270s+, tier-
    dependent). During a fast move — the MRVL 6/18 15:50 OPEX-into-Juneteenth
    drop — that spot froze ~$17 stale for 10 minutes, mispricing every alert and
    corrupting bid/ask/mid side classification. The price stream polls Tradier
    every stream_poll_seconds (5s); prefer it. Fall back to the cached state spot
    only when the stream lacks the symbol (not yet subscribed)."""
    p = streamer.last_prices().get((ticker or "").upper())
    if p and p > 0:
        return float(p)
    if state:
        return state.get("actual_spot") or state.get("_spot") or 0
    return 0
