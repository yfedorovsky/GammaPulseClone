"""Massive (formerly Polygon.io) API adapter for real-time Greeks & IV.

Tradier provides Greeks from ORATS that update hourly.  Massive's Starter
plan ($29/mo) advertises "Real-time Greeks and IV," making it the primary
Greeks source for GammaPulse while Tradier remains the source for quotes,
streaming, candles, OI, volume, and bid/ask.

Usage pattern:
  1. Fetch Tradier chain (structural data)
  2. Fetch Massive snapshot (fresh Greeks)
  3. Merge Massive Greeks into Tradier contracts
  4. Pass enriched contracts to compute_exp_data()
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import get_settings

# In-memory Greeks cache: ticker -> (timestamp, greeks_dict)
_greeks_cache: dict[str, tuple[float, dict[tuple[float, str, str], dict[str, float]]]] = {}
GREEKS_CACHE_TTL = 30  # seconds — fresh enough for intraday, avoids API hammering

# Spot price embedded in Massive's snapshot (for consistency check vs Tradier)
_massive_spot_cache: dict[str, float] = {}


def get_massive_spot(ticker: str) -> float | None:
    """Return the underlying spot price from the last Massive snapshot for this ticker."""
    return _massive_spot_cache.get(ticker.upper())


class MassiveClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.massive_api_key
        self.base_url = (base_url or s.massive_base_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def snapshot_greeks(
        self,
        ticker: str,
        expiration_gte: str = "",
        expiration_lte: str = "",
        limit: int = 250,
        max_pages: int = 10,
    ) -> tuple[dict[tuple[float, str, str], dict[str, float]], float]:
        """Fetch option chain snapshot with Greeks from Massive.

        Returns (greeks_lookup, timestamp).

        greeks_lookup is keyed by (strike, expiration_date, option_type) for
        O(1) merge with Tradier contracts:
          {
            (580.0, "2026-04-18", "call"): {
                "delta": 0.55, "gamma": 0.012,
                "theta": -0.08, "vega": 0.15, "iv": 0.25
            },
            ...
          }
        """
        # Check cache first
        cache_key = f"{ticker}:{expiration_gte}:{expiration_lte}"
        cached = _greeks_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < GREEKS_CACHE_TTL:
            return cached[1], cached[0]

        client = await self._get_client()
        greeks_lookup: dict[tuple[float, str, str], dict[str, float]] = {}
        ts = time.time()

        # Paginate through results (capped at max_pages to avoid slow SPY-like chains)
        next_url: str | None = None
        first_call = True
        page = 0

        while (first_call or next_url) and page < max_pages:
            first_call = False
            page += 1

            if next_url:
                # Pagination: next_url is a full URL from Massive
                # Append apiKey since it's not included in next_url
                sep = "&" if "?" in next_url else "?"
                full_url = f"{next_url}{sep}apiKey={self.api_key}"
                r = await httpx.AsyncClient(timeout=httpx.Timeout(15.0)).get(full_url)
            else:
                params: dict[str, str] = {
                    "apiKey": self.api_key,
                    "limit": str(limit),
                }
                if expiration_gte:
                    params["expiration_date.gte"] = expiration_gte
                if expiration_lte:
                    params["expiration_date.lte"] = expiration_lte

                r = await client.get(
                    f"/v3/snapshot/options/{ticker}",
                    params=params,
                )

            if r.status_code != 200:
                break

            data = r.json()
            results = data.get("results") or []

            # Extract Massive's underlying spot from first result (for consistency check)
            if results:
                ua = results[0].get("underlying_asset") or {}
                if ua.get("price"):
                    _massive_spot_cache[ticker.upper()] = ua["price"]

            for opt in results:
                details = opt.get("details") or {}
                greeks = opt.get("greeks") or {}

                strike = details.get("strike_price")
                exp_date = details.get("expiration_date", "")
                contract_type = details.get("contract_type", "").lower()

                if strike is None or not exp_date or not contract_type:
                    continue

                # Only include if we have actual Greeks
                delta = greeks.get("delta")
                gamma = greeks.get("gamma")
                if delta is None and gamma is None:
                    continue

                key = (float(strike), exp_date, contract_type)
                greeks_lookup[key] = {
                    "delta": delta or 0.0,
                    "gamma": gamma or 0.0,
                    "theta": greeks.get("theta") or 0.0,
                    "vega": greeks.get("vega") or 0.0,
                    "iv": opt.get("implied_volatility") or 0.0,
                }

            # Check for next page
            next_url = data.get("next_url")
            if not next_url:
                break

        # Cache the result
        _greeks_cache[cache_key] = (ts, greeks_lookup)
        return greeks_lookup, ts


def enrich_contracts_with_massive(
    contracts: list[dict[str, Any]],
    massive_greeks: dict[tuple[float, str, str], dict[str, float]],
    massive_ts: float,
) -> list[dict[str, Any]]:
    """Merge Massive real-time Greeks into Tradier contract dicts.

    For each contract, if Massive has Greeks for that (strike, exp, type),
    overwrite the Tradier greeks sub-dict.  Tag each contract with
    _greeks_source and _greeks_ts for freshness tracking.
    """
    for c in contracts:
        strike = c.get("strike")
        exp = c.get("expiration_date", "")
        otype = (c.get("option_type") or "").lower()

        if strike is None or not exp or not otype:
            c["_greeks_source"] = "tradier"
            c["_greeks_ts"] = time.time()
            continue

        key = (float(strike), exp, otype)
        mg = massive_greeks.get(key)

        if mg:
            # Preserve Tradier Greeks for auditability before overwriting
            c["_greeks_tradier"] = dict(c.get("greeks") or {})
            # Overwrite active Greeks with fresh Massive data
            c["greeks"] = {
                "delta": mg["delta"],
                "gamma": mg["gamma"],
                "theta": mg["theta"],
                "vega": mg["vega"],
                "mid_iv": mg["iv"],
            }
            c["_greeks_massive"] = dict(c["greeks"])
            c["_greeks_source"] = "massive"
            c["_greeks_ts"] = massive_ts
        else:
            # Keep Tradier Greeks as active + store copy
            c["_greeks_tradier"] = dict(c.get("greeks") or {})
            c["_greeks_source"] = "tradier"
            c["_greeks_ts"] = time.time()

    return contracts
