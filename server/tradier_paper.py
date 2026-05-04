"""Tradier Paper Account async client.

Replaces server/etrade.py for paper-trade execution. Tradier paper
sandbox is significantly better than E-Trade's developer sandbox:

  - Bearer token auth (no OAuth dance, no daily expiry)
  - Real-market quotes (not mocked canned responses)
  - Realistic simulated fills tied to actual bid/ask
  - Real position tracking visible in brokerage.tradier.com UI
  - Same JSON API shape as Tradier production

Used by:
  - server/tradier_executor.py (auto-execution daemon)
  - mcp_servers/tradier_paper/server.py (Claude MCP)
  - scripts/tradier_paper_setup.py (one-time validation)

## Auth

Set in .env:
  TRADIER_PAPER_TOKEN=<sandbox_bearer_token>
  TRADIER_PAPER_ACCOUNT_ID=<your_sandbox_account_id>

Generate at https://developer.tradier.com — Sandbox API → Access Token.

## Sandbox vs production

This module is HARDCODED to sandbox. There is no env toggle. To trade
real money you'd need a separate module — that's deliberate friction
to avoid accidental production execution.

Sandbox base URL: https://sandbox.tradier.com
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


SANDBOX_BASE = "https://sandbox.tradier.com"


def _read_token() -> str:
    token = os.getenv("TRADIER_PAPER_TOKEN")
    if not token:
        raise RuntimeError(
            "TRADIER_PAPER_TOKEN not set in .env. Generate one at "
            "https://developer.tradier.com (Sandbox API)."
        )
    return token


def _read_account_id() -> str:
    aid = os.getenv("TRADIER_PAPER_ACCOUNT_ID")
    if not aid:
        raise RuntimeError(
            "TRADIER_PAPER_ACCOUNT_ID not set in .env. Run "
            "scripts/tradier_paper_setup.py to find your account_id."
        )
    return aid


# ── Client ────────────────────────────────────────────────────────


class TradierPaperClient:
    """Async REST client for Tradier paper sandbox.

    Auth: Bearer token (TRADIER_PAPER_TOKEN env var). No OAuth, no
    refresh — tokens don't expire.
    """

    def __init__(self, token: str | None = None,
                 account_id: str | None = None) -> None:
        self._token = token or _read_token()
        self._account_id = account_id or _read_account_id()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                base_url=SANDBOX_BASE,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE

    # ── Internal request helper ────────────────────────────────────

    async def _request(
        self, method: str, path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._get_client()
        # Tradier expects form-encoded bodies for orders
        if body is not None and method in ("POST", "PUT"):
            data = body
            content_type = "application/x-www-form-urlencoded"
            resp = await client.request(
                method, path, params=params, data=data,
                headers={"Content-Type": content_type},
            )
        else:
            resp = await client.request(method, path, params=params)

        if resp.status_code == 401:
            raise RuntimeError(
                f"Tradier 401 Unauthorized — check TRADIER_PAPER_TOKEN "
                f"in .env. (URL: {path})"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Tradier {resp.status_code} on {method} {path}: "
                f"{resp.text[:500]}"
            )
        try:
            return resp.json()
        except Exception:
            return resp.text

    # ── User / accounts ────────────────────────────────────────────

    async def user_profile(self) -> dict[str, Any]:
        """Returns user profile + linked accounts (paper + live if any)."""
        data = await self._request("GET", "/v1/user/profile")
        return data.get("profile", {})

    async def account_balance(
        self, account_id: str | None = None,
    ) -> dict[str, Any]:
        """Cash + equity + buying power for an account."""
        aid = account_id or self._account_id
        data = await self._request("GET", f"/v1/accounts/{aid}/balances")
        return data.get("balances", {})

    async def account_positions(
        self, account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Current open positions."""
        aid = account_id or self._account_id
        data = await self._request("GET", f"/v1/accounts/{aid}/positions")
        positions = (data or {}).get("positions") or {}
        if positions == "null" or positions is None:
            return []
        if isinstance(positions, str):
            return []
        # Tradier returns either {"positions": "null"} (no positions),
        # {"positions": {"position": {...}}} (single), or
        # {"positions": {"position": [{...}, {...}]}} (multiple)
        out = positions.get("position") if isinstance(positions, dict) else None
        if out is None:
            return []
        if isinstance(out, dict):
            return [out]
        return out

    # ── Quotes ─────────────────────────────────────────────────────

    async def quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Get quotes for one or more symbols. For options, use the
        OCC symbol format (e.g. 'SPY260504C00720000')."""
        sym_str = ",".join(symbols)
        data = await self._request(
            "GET", "/v1/markets/quotes", params={"symbols": sym_str},
        )
        quotes = (data or {}).get("quotes", {}).get("quote") or []
        if isinstance(quotes, dict):
            quotes = [quotes]
        return quotes

    # ── Order endpoints ────────────────────────────────────────────

    async def place_option_order(
        self, account_id_key: str | None,
        symbol: str, expiration_date: str, strike: float, call_or_put: str,
        action: str,    # 'buy_to_open' / 'sell_to_close' / 'sell_to_open' / 'buy_to_close'
        quantity: int,
        order_type: str = "limit",   # market / limit / stop / stop_limit
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "day",
        preview_only: bool = True,
    ) -> dict[str, Any]:
        """Place an option order via Tradier paper API.

        Tradier uses a single POST that accepts a 'preview' field — when
        true, returns the would-be order details without placing.

        OCC option symbol is constructed inline.

        Tradier action vocabulary (lowercase):
          buy_to_open / sell_to_close / sell_to_open / buy_to_close
        """
        aid = account_id_key or self._account_id

        # OCC option symbol: TICKER + YYMMDD + C/P + strike*1000 (8 digits)
        exp_compact = expiration_date.replace("-", "")[2:]   # YYMMDD
        cp_letter = "C" if call_or_put.upper() in ("C", "CALL") else "P"
        strike_int = int(round(float(strike) * 1000))
        occ = f"{symbol.upper()}{exp_compact}{cp_letter}{strike_int:08d}"

        # Tradier expects form-encoded params (NOT JSON)
        body: dict[str, str] = {
            "class": "option",
            "symbol": symbol.upper(),       # underlying
            "option_symbol": occ,
            "side": action.lower(),
            "quantity": str(quantity),
            "type": order_type.lower(),
            "duration": time_in_force.lower(),
        }
        if order_type.lower() in ("limit", "stop_limit"):
            if limit_price is None:
                raise ValueError("limit_price required for limit/stop_limit")
            body["price"] = f"{float(limit_price):.2f}"
        if order_type.lower() in ("stop", "stop_limit"):
            if stop_price is None:
                raise ValueError("stop_price required for stop/stop_limit")
            body["stop"] = f"{float(stop_price):.2f}"
        if preview_only:
            body["preview"] = "true"

        data = await self._request(
            "POST", f"/v1/accounts/{aid}/orders", body=body,
        )
        return data

    async def list_orders(
        self, account_id: str | None = None,
        include_tags: bool = True,
    ) -> list[dict[str, Any]]:
        """List ALL orders for the account (Tradier doesn't filter by
        status server-side — caller filters)."""
        aid = account_id or self._account_id
        params = {"includeTags": "true" if include_tags else "false"}
        data = await self._request(
            "GET", f"/v1/accounts/{aid}/orders", params=params,
        )
        orders = (data or {}).get("orders") or {}
        if orders == "null" or orders is None or isinstance(orders, str):
            return []
        out = orders.get("order") if isinstance(orders, dict) else None
        if out is None:
            return []
        if isinstance(out, dict):
            return [out]
        return out

    async def get_order(
        self, order_id: int, account_id: str | None = None,
    ) -> dict[str, Any]:
        """Get a single order by ID."""
        aid = account_id or self._account_id
        data = await self._request(
            "GET", f"/v1/accounts/{aid}/orders/{order_id}",
        )
        return (data or {}).get("order", {})

    async def cancel_order(
        self, order_id: int, account_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel an open order."""
        aid = account_id or self._account_id
        data = await self._request(
            "DELETE", f"/v1/accounts/{aid}/orders/{order_id}",
        )
        return (data or {}).get("order", {})

    # ── Convenience: filter orders by status client-side ──────────

    async def list_orders_by_status(
        self, statuses: tuple[str, ...] = ("open", "pending"),
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        all_orders = await self.list_orders(account_id=account_id)
        statuses_lower = tuple(s.lower() for s in statuses)
        return [o for o in all_orders
                if (o.get("status") or "").lower() in statuses_lower]

    # ── Exit-order convenience wrappers (mirror E-Trade module) ───

    async def place_close_limit(
        self, account_id_key: str | None,
        symbol: str, expiration_date: str, strike: float, call_or_put: str,
        quantity: int, limit_price: float,
        execute: bool = True,
    ) -> dict[str, Any]:
        return await self.place_option_order(
            account_id_key=account_id_key,
            symbol=symbol, expiration_date=expiration_date,
            strike=strike, call_or_put=call_or_put,
            action="sell_to_close",
            quantity=quantity,
            order_type="limit",
            limit_price=limit_price,
            time_in_force="day",
            preview_only=not execute,
        )

    async def place_close_stop(
        self, account_id_key: str | None,
        symbol: str, expiration_date: str, strike: float, call_or_put: str,
        quantity: int, stop_price: float,
        execute: bool = True,
    ) -> dict[str, Any]:
        return await self.place_option_order(
            account_id_key=account_id_key,
            symbol=symbol, expiration_date=expiration_date,
            strike=strike, call_or_put=call_or_put,
            action="sell_to_close",
            quantity=quantity,
            order_type="stop",
            stop_price=stop_price,
            time_in_force="day",
            preview_only=not execute,
        )

    async def place_close_market(
        self, account_id_key: str | None,
        symbol: str, expiration_date: str, strike: float, call_or_put: str,
        quantity: int,
        execute: bool = True,
    ) -> dict[str, Any]:
        return await self.place_option_order(
            account_id_key=account_id_key,
            symbol=symbol, expiration_date=expiration_date,
            strike=strike, call_or_put=call_or_put,
            action="sell_to_close",
            quantity=quantity,
            order_type="market",
            time_in_force="day",
            preview_only=not execute,
        )
