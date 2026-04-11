"""Tradier API adapter.

Docs: https://documentation.tradier.com/brokerage-api/markets/get-quotes
Only the endpoints we need:
  - /markets/quotes          (batch quotes, used for spot + stream polling)
  - /markets/options/expirations
  - /markets/options/chains  (with greeks=true for gamma/vanna)

The adapter returns plain dicts; higher layers convert to our internal schema.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import get_settings


class TradierClient:
    def __init__(self, token: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.token = token or s.tradier_token
        self.base_url = (base_url or s.tradier_base_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- Public endpoints ---

    async def quotes(self, symbols: list[str]) -> dict[str, float]:
        """Return a dict of ticker -> last price."""
        if not symbols:
            return {}
        client = await self._get_client()
        out: dict[str, float] = {}
        # Tradier caps symbol list size; chunk to be safe
        for i in range(0, len(symbols), 50):
            batch = symbols[i : i + 50]
            r = await client.get(
                "/markets/quotes",
                params={"symbols": ",".join(batch), "greeks": "false"},
            )
            if r.status_code != 200:
                continue
            data = r.json().get("quotes") or {}
            quotes = data.get("quote") or []
            if isinstance(quotes, dict):
                quotes = [quotes]
            for q in quotes:
                sym = q.get("symbol")
                last = q.get("last") or q.get("close") or q.get("prevclose")
                if sym and last is not None:
                    try:
                        out[sym] = float(last)
                    except (TypeError, ValueError):
                        pass
        return out

    async def expirations(self, symbol: str) -> list[str]:
        client = await self._get_client()
        r = await client.get(
            "/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
        )
        if r.status_code != 200:
            return []
        data = r.json().get("expirations") or {}
        dates = data.get("date") or []
        if isinstance(dates, str):
            dates = [dates]
        return list(dates)

    async def chain(self, symbol: str, expiration: str) -> list[dict[str, Any]]:
        """Return the raw options chain for a given expiration with greeks."""
        client = await self._get_client()
        r = await client.get(
            "/markets/options/chains",
            params={"symbol": symbol, "expiration": expiration, "greeks": "true"},
        )
        if r.status_code != 200:
            return []
        data = r.json().get("options") or {}
        opts = data.get("option") or []
        if isinstance(opts, dict):
            opts = [opts]
        return opts

    async def history(
        self, symbol: str, interval: str = "daily", start: str = "", end: str = ""
    ) -> list[dict[str, Any]]:
        """Fetch price history. interval = 'daily' | '5min' | '15min' | '1min'.
        For intraday, uses /markets/timesales. For daily, /markets/history."""
        client = await self._get_client()
        if interval == "daily":
            params: dict[str, str] = {"symbol": symbol, "interval": "daily"}
            if start:
                params["start"] = start
            if end:
                params["end"] = end
            r = await client.get("/markets/history", params=params)
            if r.status_code != 200:
                return []
            data = r.json().get("history") or {}
            bars = data.get("day") or []
            if isinstance(bars, dict):
                bars = [bars]
            return [
                {
                    "time": b["date"],
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b.get("volume", 0),
                }
                for b in bars
            ]
        else:
            # Intraday via timesales
            params = {"symbol": symbol, "interval": interval}
            if start:
                params["start"] = start
            if end:
                params["end"] = end
            r = await client.get("/markets/timesales", params=params)
            if r.status_code != 200:
                return []
            data = r.json().get("series") or {}
            bars = data.get("data") or []
            if isinstance(bars, dict):
                bars = [bars]
            return [
                {
                    "time": b.get("timestamp", 0),
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b.get("volume", 0),
                }
                for b in bars
            ]

    async def full_chain(
        self, symbol: str, max_expirations: int = 17
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Fetch the first N expirations merged into one flat chain list."""
        exps = await self.expirations(symbol)
        if not exps:
            return [], []
        exps = exps[:max_expirations]
        results = await asyncio.gather(
            *(self.chain(symbol, e) for e in exps), return_exceptions=True
        )
        flat: list[dict[str, Any]] = []
        for batch in results:
            if isinstance(batch, Exception):
                continue
            flat.extend(batch)
        return flat, exps
