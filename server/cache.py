"""In-memory ticker cache. Keyed by ticker, holds the fully computed
`ticker_state` that matches the `/api/scanner` entry and `/api/chains` value.

Thread-safe via asyncio.Lock since the worker and HTTP handlers both read/write.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any


class TickerCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._last_cycle_end: float = 0.0
        self._worker_status: str = "Idle"

    async def put(self, ticker: str, state: dict[str, Any]) -> None:
        async with self._lock:
            state["_ticker"] = ticker
            state["_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._data[ticker] = state

    async def get(self, ticker: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._data.get(ticker)

    async def get_many(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {t: self._data[t] for t in tickers if t in self._data}

    async def snapshot(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return dict(self._data)

    async def set_status(self, status: str) -> None:
        async with self._lock:
            self._worker_status = status

    async def mark_cycle_end(self) -> None:
        async with self._lock:
            self._last_cycle_end = time.time()

    def worker_status(self) -> dict[str, str]:
        ts = (
            time.strftime("%I:%M:%S %p", time.localtime(self._last_cycle_end))
            if self._last_cycle_end
            else "--:--:-- --"
        )
        return {"last_cycle_end": ts, "status": self._worker_status}


cache = TickerCache()
