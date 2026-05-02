"""E-Trade async REST client with OAuth 1.0a authentication.

Used by:
  - server/etrade_executor.py (auto-execution daemon for paper trades)
  - mcp_servers/etrade_paper/server.py (Claude MCP tool wrapper)
  - scripts/etrade_oauth_setup.py (one-time interactive token grant)

## OAuth 1.0a flow (E-Trade specific)

1. POST oauth/request_token with consumer_key/secret signed → request_token
2. User visits https://us.etrade.com/e/t/etws/authorize?key=...&token=... in
   browser, authorizes, copies verification code shown on the page
3. POST oauth/access_token with verification code → access_token + token_secret
4. Subsequent API calls signed with access_token

Tokens expire daily at midnight US ET. To avoid daily browser dance during
market hours, E-Trade provides /oauth/renew_access_token which extends an
idle token's lifetime within the same trading day. We use renewal aggressively.

## Sandbox vs production

Set ETRADE_USE_SANDBOX=1 in .env (default) to use apisb.etrade.com — the
paper trading environment with simulated fills. Only switch to production
(ETRADE_USE_SANDBOX=0) when you EXPLICITLY want real-money execution.
This module reads the env var on every request to make accidental
production calls harder.

## Per the production freeze (FALSIFICATION_PROTOCOL.md)

This client is part of the `feature/etrade-paper-execution` branch only.
It does NOT exist on main. Forward window verdict on main proceeds via
intrinsic-only simulation in paired_trades.py. The E-Trade paper account
is a SECONDARY validation layer that captures real fill timing/slippage
once we're confident the OAuth pipeline works.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


SANDBOX_BASE = "https://apisb.etrade.com"
PROD_BASE = "https://api.etrade.com"

# Persisted token cache (so a daily auth doesn't require restarting daemons)
TOKEN_CACHE_PATH = ROOT / ".etrade_tokens.json"


# ── Config + token persistence ─────────────────────────────────────


def _is_sandbox() -> bool:
    """Default to sandbox unless explicitly set to 0."""
    return os.getenv("ETRADE_USE_SANDBOX", "1") != "0"


def _base_url() -> str:
    return SANDBOX_BASE if _is_sandbox() else PROD_BASE


def _consumer_credentials() -> tuple[str, str]:
    """Read consumer key + secret from env. Sandbox and prod use DIFFERENT
    credentials — set ETRADE_SANDBOX_KEY/SECRET vs ETRADE_KEY/SECRET."""
    if _is_sandbox():
        key = os.getenv("ETRADE_SANDBOX_KEY")
        secret = os.getenv("ETRADE_SANDBOX_SECRET")
    else:
        key = os.getenv("ETRADE_KEY")
        secret = os.getenv("ETRADE_SECRET")
    if not key or not secret:
        raise RuntimeError(
            f"E-Trade {'sandbox' if _is_sandbox() else 'prod'} credentials "
            f"not set in .env. See scripts/etrade_oauth_setup.py for the "
            f"one-time setup."
        )
    return key, secret


@dataclass
class Token:
    """OAuth token pair (oauth_token + oauth_token_secret).

    For request tokens (step 1) and access tokens (step 3+).
    Persisted to .etrade_tokens.json keyed by environment.
    """
    oauth_token: str
    oauth_token_secret: str
    granted_at: float = field(default_factory=time.time)


def _load_cached_tokens() -> dict[str, Token]:
    """Returns dict keyed by 'sandbox' or 'prod' → Token."""
    if not TOKEN_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        return {
            env: Token(**t) for env, t in raw.items()
            if isinstance(t, dict) and "oauth_token" in t
        }
    except Exception:
        return {}


def _save_cached_tokens(tokens: dict[str, Token]) -> None:
    payload = {env: vars(t) for env, t in tokens.items()}
    TOKEN_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_cached_token() -> Token | None:
    """Return the most recently saved access token for the current env."""
    env = "sandbox" if _is_sandbox() else "prod"
    return _load_cached_tokens().get(env)


def save_token(token: Token) -> None:
    env = "sandbox" if _is_sandbox() else "prod"
    cache = _load_cached_tokens()
    cache[env] = token
    _save_cached_tokens(cache)


# ── OAuth 1.0a signature helpers ───────────────────────────────────


def _percent_encode(s: str) -> str:
    """RFC 5849 §3.6 percent-encoding (more aggressive than urlencode)."""
    return urllib.parse.quote(str(s), safe="-._~")


def _build_signature_base(method: str, url: str, params: dict[str, str]) -> str:
    """OAuth 1.0a signature base string per RFC 5849 §3.4.1."""
    encoded_params = sorted(
        (_percent_encode(k), _percent_encode(v)) for k, v in params.items()
    )
    param_str = "&".join(f"{k}={v}" for k, v in encoded_params)
    return "&".join([
        method.upper(),
        _percent_encode(url),
        _percent_encode(param_str),
    ])


def _sign_hmac_sha1(base_str: str, consumer_secret: str,
                    token_secret: str = "") -> str:
    """HMAC-SHA1 signing per RFC 5849 §3.4.2."""
    key = f"{_percent_encode(consumer_secret)}&{_percent_encode(token_secret)}"
    digest = hmac.new(key.encode("utf-8"), base_str.encode("utf-8"),
                      hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_oauth_header(
    method: str, url: str, consumer_key: str, consumer_secret: str,
    token: Token | None = None,
    extra_oauth: dict[str, str] | None = None,
    body_params: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct OAuth Authorization header for one request.

    body_params: any application/x-www-form-urlencoded body fields
                 (must be included in signature base string).
    extra_oauth: extra oauth_* fields like oauth_callback or oauth_verifier.
    """
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    if token is not None:
        oauth_params["oauth_token"] = token.oauth_token
    if extra_oauth:
        oauth_params.update(extra_oauth)

    # Signature base includes oauth_* + body params (NOT the signature itself)
    sig_params = dict(oauth_params)
    if body_params:
        sig_params.update(body_params)
    base_str = _build_signature_base(method, url, sig_params)
    token_secret = token.oauth_token_secret if token is not None else ""
    oauth_params["oauth_signature"] = _sign_hmac_sha1(
        base_str, consumer_secret, token_secret,
    )

    # Build header value: OAuth realm="", oauth_consumer_key="...", ...
    header_value = "OAuth " + ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return {"Authorization": header_value}


# ── Client ────────────────────────────────────────────────────────


class ETradeClient:
    """Async E-Trade REST client.

    Auth: pass `token` explicitly OR rely on the cached token via
    get_cached_token() (loaded automatically). Use scripts/etrade_oauth_setup.py
    to perform the initial OAuth dance and populate the cache.
    """

    def __init__(self, token: Token | None = None,
                 base_url: str | None = None) -> None:
        self._token = token or get_cached_token()
        self._base = base_url or _base_url()
        self._client: httpx.AsyncClient | None = None
        self._consumer_key, self._consumer_secret = _consumer_credentials()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, base_url=self._base)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Internal request helper ────────────────────────────────────

    async def _request(
        self, method: str, path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | str | None = None,
        accept: str = "application/json",
        content_type: str | None = None,
    ) -> Any:
        if self._token is None:
            raise RuntimeError(
                "No E-Trade access token. Run scripts/etrade_oauth_setup.py "
                "first to grant access."
            )
        url = f"{self._base}{path}"

        # Query params (signed in signature base)
        qparams: dict[str, str] = {k: str(v) for k, v in (params or {}).items()}

        # Body — for x-www-form-urlencoded bodies, fields are signed too.
        # For JSON bodies (our orders), body is NOT signed (per OAuth spec
        # — only form-encoded body fields are part of the signature base).
        body_for_sig: dict[str, str] | None = None
        request_body: Any = None
        if body is not None:
            if content_type == "application/x-www-form-urlencoded" or \
               (isinstance(body, dict) and content_type is None and
                method.upper() == "POST" and not path.endswith("/orders")):
                body_for_sig = {k: str(v) for k, v in body.items()}
                request_body = urllib.parse.urlencode(body_for_sig)
                content_type = "application/x-www-form-urlencoded"
            else:
                # JSON body
                request_body = json.dumps(body) if isinstance(body, dict) else body
                if content_type is None:
                    content_type = "application/json"

        # Combine query params for signature
        all_sig_params = dict(qparams)
        if body_for_sig:
            all_sig_params.update(body_for_sig)

        oauth_header = _build_oauth_header(
            method, url, self._consumer_key, self._consumer_secret,
            self._token, body_params=all_sig_params,
        )
        headers = dict(oauth_header)
        headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type

        client = await self._get_client()
        resp = await client.request(
            method, url, params=qparams, content=request_body, headers=headers,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                f"E-Trade 401 Unauthorized — token may be expired or "
                f"invalid. Re-run scripts/etrade_oauth_setup.py. "
                f"(URL: {url})"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"E-Trade {resp.status_code} on {method} {path}: "
                f"{resp.text[:500]}"
            )
        if accept == "application/json":
            try:
                return resp.json()
            except Exception:
                return resp.text
        return resp.text

    # ── OAuth endpoints (used by setup script) ─────────────────────

    @staticmethod
    async def get_request_token(consumer_key: str, consumer_secret: str,
                                base_url: str | None = None) -> Token:
        """Step 1 of OAuth: request a temporary request token."""
        base = base_url or _base_url()
        url = f"{base}/oauth/request_token"
        oauth_header = _build_oauth_header(
            "GET", url, consumer_key, consumer_secret,
            extra_oauth={"oauth_callback": "oob"},
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=oauth_header)
        if resp.status_code != 200:
            raise RuntimeError(f"request_token failed: {resp.status_code} {resp.text}")
        parsed = urllib.parse.parse_qs(resp.text)
        return Token(
            oauth_token=parsed["oauth_token"][0],
            oauth_token_secret=parsed["oauth_token_secret"][0],
        )

    @staticmethod
    def authorize_url(consumer_key: str, request_token: Token) -> str:
        """Step 2: URL the user must visit in their browser to authorize."""
        return (
            f"https://us.etrade.com/e/t/etws/authorize"
            f"?key={consumer_key}&token={request_token.oauth_token}"
        )

    @staticmethod
    async def exchange_for_access_token(
        consumer_key: str, consumer_secret: str,
        request_token: Token, verifier: str,
        base_url: str | None = None,
    ) -> Token:
        """Step 3: exchange verifier code for the long-lived access token."""
        base = base_url or _base_url()
        url = f"{base}/oauth/access_token"
        oauth_header = _build_oauth_header(
            "GET", url, consumer_key, consumer_secret, request_token,
            extra_oauth={"oauth_verifier": verifier},
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=oauth_header)
        if resp.status_code != 200:
            raise RuntimeError(
                f"access_token failed: {resp.status_code} {resp.text}"
            )
        parsed = urllib.parse.parse_qs(resp.text)
        return Token(
            oauth_token=parsed["oauth_token"][0],
            oauth_token_secret=parsed["oauth_token_secret"][0],
        )

    async def renew_access_token(self) -> bool:
        """Refresh an idle access token to extend its life within the same
        trading day. Returns True on success."""
        try:
            await self._request("GET", "/oauth/renew_access_token")
            if self._token is not None:
                self._token.granted_at = time.time()
                save_token(self._token)
            return True
        except Exception as e:
            print(f"[etrade] renew failed: {e}")
            return False

    # ── Account endpoints ──────────────────────────────────────────

    async def list_accounts(self) -> list[dict[str, Any]]:
        """Returns list of accounts owned by this user."""
        data = await self._request("GET", "/v1/accounts/list")
        accts = (data or {}).get("AccountListResponse", {}).get("Accounts", {})
        out = accts.get("Account") or []
        if isinstance(out, dict):
            out = [out]
        return out

    async def account_balance(self, account_id_key: str) -> dict[str, Any]:
        """Returns balance + buying power for a paper account."""
        data = await self._request(
            "GET", f"/v1/accounts/{account_id_key}/balance",
            params={"instType": "BROKERAGE", "realTimeNAV": "true"},
        )
        return (data or {}).get("BalanceResponse", {})

    async def account_positions(self, account_id_key: str) -> list[dict[str, Any]]:
        """Returns current positions in a paper account."""
        data = await self._request(
            "GET", f"/v1/accounts/{account_id_key}/portfolio",
        )
        resp = (data or {}).get("PortfolioResponse", {}).get(
            "AccountPortfolio", {}
        )
        if isinstance(resp, list):
            resp = resp[0] if resp else {}
        positions = resp.get("Position") or []
        if isinstance(positions, dict):
            positions = [positions]
        return positions

    # ── Quote endpoints ────────────────────────────────────────────

    async def quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Get real-time quote for one or more symbols (equity or option).

        For options, symbol format is the OCC symbol or E-Trade's compound
        format. For equities, use the ticker.
        """
        sym_str = ",".join(symbols)
        data = await self._request(
            "GET", f"/v1/market/quote/{sym_str}",
            params={"detailFlag": "ALL"},
        )
        quotes = (data or {}).get("QuoteResponse", {}).get("QuoteData") or []
        if isinstance(quotes, dict):
            quotes = [quotes]
        return quotes

    # ── Order endpoints ────────────────────────────────────────────

    async def place_option_order(
        self, account_id_key: str,
        symbol: str, expiration_date: str, strike: float, call_or_put: str,
        action: str,    # 'BUY_OPEN' / 'SELL_CLOSE' / 'SELL_OPEN' / 'BUY_CLOSE'
        quantity: int,
        order_type: str = "LIMIT",   # MARKET / LIMIT / STOP / STOP_LIMIT
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "DAY",  # DAY / GTC / IMMEDIATE / FILL_OR_KILL
        preview_only: bool = True,
    ) -> dict[str, Any]:
        """Place an option order. Default is preview_only=True for safety —
        returns the preview without executing. Set preview_only=False to
        actually place the order.

        E-Trade two-step order pattern:
          1. POST /orders/preview → returns previewId
          2. POST /orders/place → executes the previewed order

        For simulation we usually want full preview→place flow so fill
        prices match what the preview said.

        expiration_date: 'YYYY-MM-DD'
        call_or_put: 'CALL' or 'PUT'
        symbol: underlying ticker (e.g. 'SPY', 'QQQ') — NOT the OCC option symbol
        """
        action = action.upper()
        order_type = order_type.upper()
        call_or_put = call_or_put.upper()
        time_in_force = time_in_force.upper()

        # E-Trade preview/place orders use XML-or-JSON. JSON is supported.
        # Schema: PreviewOrderRequest with Order array containing Instrument array
        exp_dt = expiration_date  # YYYY-MM-DD
        exp_year, exp_month, exp_day = exp_dt.split("-")

        instrument = {
            "Product": {
                "symbol": symbol.upper(),
                "securityType": "OPTN",
                "callPut": call_or_put,
                "expiryYear": int(exp_year),
                "expiryMonth": int(exp_month),
                "expiryDay": int(exp_day),
                "strikePrice": float(strike),
            },
            "orderAction": action,
            "quantityType": "QUANTITY",
            "quantity": int(quantity),
        }

        order_obj: dict[str, Any] = {
            "allOrNone": "false",
            "priceType": order_type,
            "orderTerm": "GOOD_FOR_DAY" if time_in_force == "DAY" else time_in_force,
            "marketSession": "REGULAR",
            "Instrument": [instrument],
        }
        if order_type in ("LIMIT", "STOP_LIMIT"):
            if limit_price is None:
                raise ValueError("limit_price required for LIMIT/STOP_LIMIT")
            order_obj["limitPrice"] = float(limit_price)
        if order_type in ("STOP", "STOP_LIMIT"):
            if stop_price is None:
                raise ValueError("stop_price required for STOP/STOP_LIMIT")
            order_obj["stopPrice"] = float(stop_price)

        preview_payload = {
            "PreviewOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": secrets.token_hex(8),
                "Order": [order_obj],
            }
        }

        # Step 1: preview
        preview_resp = await self._request(
            "POST", f"/v1/accounts/{account_id_key}/orders/preview",
            body=preview_payload, content_type="application/json",
        )
        if preview_only:
            return {"preview_only": True, "preview_response": preview_resp}

        # Step 2: place
        preview_id = (
            preview_resp.get("PreviewOrderResponse", {})
                        .get("PreviewIds", [{}])[0].get("previewId")
        )
        if preview_id is None:
            raise RuntimeError(f"preview did not return previewId: {preview_resp}")

        place_payload = {
            "PlaceOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": preview_payload["PreviewOrderRequest"][
                    "clientOrderId"
                ],
                "PreviewIds": [{"previewId": preview_id}],
                "Order": [order_obj],
            }
        }
        place_resp = await self._request(
            "POST", f"/v1/accounts/{account_id_key}/orders/place",
            body=place_payload, content_type="application/json",
        )
        return {
            "preview_only": False,
            "preview_response": preview_resp,
            "place_response": place_resp,
        }

    async def list_orders(self, account_id_key: str,
                          status: str = "OPEN") -> list[dict[str, Any]]:
        """List orders by status (OPEN / EXECUTED / CANCELLED / etc)."""
        data = await self._request(
            "GET", f"/v1/accounts/{account_id_key}/orders",
            params={"status": status},
        )
        orders_resp = (data or {}).get("OrdersResponse", {})
        orders = orders_resp.get("Order") or []
        if isinstance(orders, dict):
            orders = [orders]
        return orders

    async def cancel_order(self, account_id_key: str, order_id: int) -> dict[str, Any]:
        """Cancel an open order."""
        payload = {
            "CancelOrderRequest": {"orderId": int(order_id)},
        }
        return await self._request(
            "PUT", f"/v1/accounts/{account_id_key}/orders/cancel",
            body=payload, content_type="application/json",
        )
