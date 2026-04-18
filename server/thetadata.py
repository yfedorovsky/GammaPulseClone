"""ThetaData adapter — replaces server/massive.py and unlocks OPRA-level flow.

Subscription: ThetaData Options Standard ($80/mo, subbed Apr 17, 2026)

What this module provides:
  1. Bulk chain snapshots with first-order Greeks + NBBO (one REST call per ticker)
  2. Bulk open-interest snapshots
  3. Historical trade queries (for sweep backfill / backtesting)
  4. Per-contract WebSocket streaming with reconnect + subscription manager
  5. Gamma synthesis via BSM (Theta Standard doesn't provide gamma;
     second-order Greeks are Pro-only — trivial to compute from IV)
  6. `enrich_contracts_with_thetadata()` — drop-in replacement for the
     corresponding Massive function in worker.py

Architecture:
  REST port 25503 (v3)   — chain snapshots, history
  WebSocket port 25520   — per-contract Trade/Quote stream (Standard-tier)

Tier notes:
  - Standard $80: first-order Greeks only (delta, theta, vega, rho, IV).
    We synthesize gamma via BSM using the IV returned from Theta.
  - Standard $80: per-contract WebSocket STREAM mode, 15K contract budget.
    Full STREAM_BULK is Pro-only ($160) — we don't need it.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .config import get_settings

# ── Constants ──────────────────────────────────────────────────────────

REST_BASE = "http://127.0.0.1:25503"
WS_URL = "ws://127.0.0.1:25520/v1/events"

# OPRA sale condition codes (verified via docs + live smoke test Apr 17)
# Full enum: docs/thetadata-options-api-docs.md Trade-Conditions section
COND_INTERMARKET_SWEEP = 95            # THE sweep flag
COND_SINGLE_LEG_AUCTION_ISO = 126      # ISO via auction mechanism
COND_SINGLE_LEG_CROSS_ISO = 128        # ISO via cross mechanism
COND_BID_AGGRESSOR = 145               # seller aggressively hitting bid
COND_ASK_AGGRESSOR = 146               # buyer aggressively lifting ask

ISO_SWEEP_CONDITIONS = frozenset({
    COND_INTERMARKET_SWEEP,
    COND_SINGLE_LEG_AUCTION_ISO,
    COND_SINGLE_LEG_CROSS_ISO,
})
AGGRESSOR_CONDITIONS = frozenset({COND_BID_AGGRESSOR, COND_ASK_AGGRESSOR})

# Conditions to exclude from any flow/sweep analysis (canceled/corrected prints)
EXCLUDE_CONDITIONS = frozenset({40, 41, 42, 43, 44})  # CANC* variants

# Non-ISO auction prints — real trades but NOT sweeps; keep them out of sweep detector
NON_ISO_AUCTION_CONDITIONS = frozenset({125, 127})


# ── Trade side classification (BUY/SELL/NEUTRAL from price vs NBBO) ────

def classify_side(price: float, bid: float, ask: float) -> str:
    """Classify a trade print as BUY / SELL / NEUTRAL from price vs NBBO.

    UW-style strict logic:
      - price >= ask → BUY  (aggressive buyer lifted the ask)
      - price <= bid → SELL (aggressive seller hit the bid)
      - strictly inside spread → NEUTRAL (mid-cross, paired, auction)

    Strict comparison is correct because Theta returns the NBBO AT trade
    time — no loose tolerance needed. Ambiguous mid-spread prints are
    legitimately neutral.

    Returns 'NEUTRAL' if bid/ask are missing, zero, or crossed.
    """
    if bid <= 0 or ask <= 0 or ask <= bid:
        return "NEUTRAL"
    if price >= ask:
        return "BUY"
    if price <= bid:
        return "SELL"
    return "NEUTRAL"

# ── Caches ─────────────────────────────────────────────────────────────

# Greeks cache: ticker -> (timestamp, {(strike, exp_date, type): greeks_dict})
_greeks_cache: dict[str, tuple[float, dict[tuple[float, str, str], dict[str, float]]]] = {}
GREEKS_CACHE_TTL = 30  # matches existing Massive cache — fresh enough for intraday

# Underlying spot cache (Theta returns it inline with every Greeks row)
_theta_spot_cache: dict[str, float] = {}


def get_theta_spot(ticker: str) -> float | None:
    """Return the underlying spot from the last Theta snapshot (for consistency checks)."""
    return _theta_spot_cache.get(ticker.upper())


# ── Data classes ───────────────────────────────────────────────────────


@dataclass
class ThetaTrade:
    """A single option trade print from the WebSocket stream."""
    ticker: str           # underlying root (e.g. "SPY")
    expiration: str       # "YYYY-MM-DD"
    strike: float         # dollars (not 10ths-of-a-cent)
    right: str            # "call" or "put"
    timestamp_ms: int     # ms since market open ET
    sequence: int
    size: int
    price: float
    exchange: int
    condition: int
    ext_conditions: tuple[int, int, int, int] = (255, 255, 255, 255)

    @property
    def is_sweep(self) -> bool:
        return self.condition in ISO_SWEEP_CONDITIONS

    @property
    def is_aggressor(self) -> bool:
        return self.condition in AGGRESSOR_CONDITIONS

    @property
    def is_excluded(self) -> bool:
        return self.condition in EXCLUDE_CONDITIONS

    @property
    def notional(self) -> float:
        return self.size * self.price * 100.0


@dataclass
class SubscribeSpec:
    """A contract subscription request for the WebSocket stream."""
    root: str
    expiration: int       # YYYYMMDD int (Theta wire format)
    strike_1000ths: int   # strike in 10ths of a cent (e.g. $700 = 700000)
    right: str            # "C" or "P"

    @property
    def key(self) -> str:
        return f"{self.root}:{self.expiration}:{self.strike_1000ths}:{self.right}"


# ── BSM gamma synthesis (Pro tier gated — we compute ourselves) ────────


def synth_gamma(
    spot: float, strike: float, iv: float, days_to_exp: float,
    r: float = 0.045, q: float = 0.013,
) -> float:
    """Compute BSM gamma from spot/strike/IV/T.

    Mirrors server.gex._bsm_gamma signature but takes days instead of years
    (more natural for upstream callers who have expiration dates).
    Returns 0 for invalid inputs (follows gex.py convention — caller filters).
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or days_to_exp <= 0:
        return 0.0
    T = max(days_to_exp, 1.0) / 365.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return pdf * math.exp(-q * T) / (spot * iv * sqrt_T)


def _days_to_exp(exp_date_str: str) -> float:
    """Parse 'YYYY-MM-DD' and return days until expiration (>= 0)."""
    try:
        exp = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return max(0.0, (exp - today).days)
    except (ValueError, TypeError):
        return 0.0


# ── REST client ────────────────────────────────────────────────────────


class ThetaDataClient:
    """Async REST client for the local Theta Terminal.

    Handles the endpoints that matter for GammaPulse:
      - snapshot/greeks/first_order — bulk chain Greeks + NBBO + underlying
      - snapshot/open_interest      — bulk OI refresh
      - history/trade               — historical trade stream (sweep backfill)
      - list/expirations            — chain metadata

    Terminal caps concurrent requests (4 on Standard tier). We don't exceed
    it — worker.py already batches via asyncio.gather with tier rotation.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or REST_BASE).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(4)  # respect Terminal concurrent-request cap

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(20.0, connect=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get_csv(self, path: str, params: dict[str, str]) -> list[dict[str, str]]:
        """GET a CSV endpoint and return list-of-dicts keyed by header row.

        Returns [] on error (including subscription-tier errors — caller
        should not fail loud for a single ticker). All Theta v3 endpoints
        we use return CSV by default.
        """
        async with self._sem:
            client = await self._get_client()
            try:
                r = await client.get(path, params=params)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RequestError) as e:
                print(f"[THETA] {path} request error: {e}")
                return []

        if r.status_code != 200:
            return []
        text = r.text.strip()
        if not text:
            return []
        # Theta returns either CSV or an error message — detect by looking
        # for the expected header prefix.
        if not text.startswith(("symbol", "timestamp")):
            # e.g. "Requesting an option endpoint requiring a professional..."
            print(f"[THETA] {path} non-CSV response: {text[:120]}")
            return []

        lines = text.split("\n")
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].split(",")]
        out: list[dict[str, str]] = []
        for ln in lines[1:]:
            if not ln.strip():
                continue
            vals = ln.split(",")
            if len(vals) != len(headers):
                continue
            out.append({h: v.strip().strip('"') for h, v in zip(headers, vals)})
        return out

    async def snapshot_chain_greeks(
        self, ticker: str, expiration: str = "*",
    ) -> tuple[list[dict[str, Any]], float | None]:
        """Fetch chain with first-order Greeks + NBBO + underlying price.

        expiration: "YYYY-MM-DD" for one expiration, "*" for all.
        Returns (contracts, underlying_price). Contracts is raw dicts.

        On Standard tier, this endpoint returns delta/theta/vega/rho/IV.
        Gamma is synthesized via BSM in enrich_contracts_with_thetadata.
        """
        rows = await self._get_csv(
            "/v3/option/snapshot/greeks/first_order",
            {"symbol": ticker.upper(), "expiration": expiration},
        )
        underlying = None
        if rows:
            try:
                underlying = float(rows[0].get("underlying_price") or 0) or None
                if underlying:
                    _theta_spot_cache[ticker.upper()] = underlying
            except (ValueError, TypeError):
                pass
        return rows, underlying

    async def snapshot_chain_oi(
        self, ticker: str, expiration: str = "*",
    ) -> list[dict[str, Any]]:
        """Fetch chain-wide open interest snapshot (for GEX & flow filtering)."""
        return await self._get_csv(
            "/v3/option/snapshot/open_interest",
            {"symbol": ticker.upper(), "expiration": expiration},
        )

    async def snapshot_chain_quote(
        self, ticker: str, expiration: str = "*",
    ) -> list[dict[str, Any]]:
        """Fetch chain NBBO quotes (when Greeks not needed, lighter payload)."""
        return await self._get_csv(
            "/v3/option/snapshot/quote",
            {"symbol": ticker.upper(), "expiration": expiration},
        )

    async def history_trades(
        self, ticker: str, expiration: str, strike: float, right: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """Historical trade prints for sweep backfill / testing.

        date, expiration: "YYYY-MM-DD"
        right: "call" or "put"

        NOTE: prefer history_trade_quote() for backfill — same cost, richer
        response (includes NBBO at trade time for side classification).
        """
        return await self._get_csv(
            "/v3/option/history/trade",
            {
                "symbol": ticker.upper(),
                "expiration": expiration,
                "strike": f"{strike:g}",
                "right": right,
                "date": date,
            },
        )

    async def history_trade_quote(
        self, ticker: str, expiration: str, strike: float, right: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """Historical trade prints PAIRED with the NBBO at trade time.

        Response columns: trade_timestamp, quote_timestamp, sequence,
        ext_condition1-4, condition, size, exchange, price,
        bid_size, bid_exchange, bid, bid_condition,
        ask_size, ask_exchange, ask, ask_condition

        Enables Bought/Sold classification:
          price >= ask → BUY  (aggressive buyer lifting the ask)
          price <= bid → SELL (aggressive seller hitting the bid)
          else         → NEUTRAL (mid-market, likely rollup or crossing)
        """
        return await self._get_csv(
            "/v3/option/history/trade_quote",
            {
                "symbol": ticker.upper(),
                "expiration": expiration,
                "strike": f"{strike:g}",
                "right": right,
                "date": date,
            },
        )

    async def list_expirations(self, ticker: str) -> list[str]:
        """All available expirations for a symbol (YYYY-MM-DD strings)."""
        rows = await self._get_csv(
            "/v3/option/list/expirations",
            {"symbol": ticker.upper()},
        )
        return [r.get("expiration", "") for r in rows if r.get("expiration")]


# ── Massive drop-in replacement ────────────────────────────────────────


async def snapshot_greeks(
    client: ThetaDataClient,
    ticker: str,
    expiration_gte: str = "",
    expiration_lte: str = "",
) -> tuple[dict[tuple[float, str, str], dict[str, float]], float]:
    """Massive-compatible signature. Used by worker.py for chain enrichment.

    Returns (greeks_lookup, timestamp).
    greeks_lookup keyed by (strike, expiration_date, option_type) with:
      {"delta", "gamma", "theta", "vega", "iv"}

    Gamma is synthesized via BSM from IV (Standard tier doesn't provide it).
    expiration_gte/lte are honored by filtering the wildcard response.
    """
    cache_key = f"{ticker}:{expiration_gte}:{expiration_lte}"
    cached = _greeks_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < GREEKS_CACHE_TTL:
        return cached[1], cached[0]

    ts = time.time()
    rows, underlying = await client.snapshot_chain_greeks(ticker, expiration="*")

    out: dict[tuple[float, str, str], dict[str, float]] = {}
    for r in rows:
        try:
            strike = float(r.get("strike") or 0)
            exp_date = r.get("expiration") or ""
            right_raw = (r.get("right") or "").upper()
            if not strike or not exp_date or right_raw not in ("CALL", "PUT"):
                continue
            otype = "call" if right_raw == "CALL" else "put"

            # Range filter (mirrors Massive's gte/lte behavior)
            if expiration_gte and exp_date < expiration_gte:
                continue
            if expiration_lte and exp_date > expiration_lte:
                continue

            delta = float(r.get("delta") or 0)
            theta = float(r.get("theta") or 0)
            vega = float(r.get("vega") or 0)
            iv = float(r.get("implied_vol") or 0)

            # Skip rows with missing primary Greeks (Theta returns 0 for stale/bad)
            if delta == 0 and iv == 0:
                continue

            # Synthesize gamma via BSM (Standard tier doesn't provide it)
            gamma = synth_gamma(
                spot=underlying or 0,
                strike=strike,
                iv=iv,
                days_to_exp=_days_to_exp(exp_date),
            ) if underlying else 0.0

            out[(strike, exp_date, otype)] = {
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "iv": iv,
            }
        except (ValueError, TypeError):
            continue

    _greeks_cache[cache_key] = (ts, out)
    return out, ts


def enrich_contracts_with_thetadata(
    contracts: list[dict[str, Any]],
    theta_greeks: dict[tuple[float, str, str], dict[str, float]],
    theta_ts: float,
) -> list[dict[str, Any]]:
    """Drop-in replacement for enrich_contracts_with_massive.

    Merges Theta Greeks into Tradier contract dicts. Same audit-trail
    convention (_greeks_tradier preserved, _greeks_source tagged).
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
        tg = theta_greeks.get(key)

        if tg:
            c["_greeks_tradier"] = dict(c.get("greeks") or {})
            c["greeks"] = {
                "delta": tg["delta"],
                "gamma": tg["gamma"],
                "theta": tg["theta"],
                "vega": tg["vega"],
                "mid_iv": tg["iv"],
            }
            c["_greeks_theta"] = dict(c["greeks"])
            c["_greeks_source"] = "thetadata"
            c["_greeks_ts"] = theta_ts
        else:
            c["_greeks_tradier"] = dict(c.get("greeks") or {})
            c["_greeks_source"] = "tradier"
            c["_greeks_ts"] = time.time()

    return contracts


# ── WebSocket streaming ────────────────────────────────────────────────


class ThetaStream:
    """Persistent WebSocket connection with reconnect + subscription state.

    Behavior:
      - Single long-lived connection to ws://127.0.0.1:25520/v1/events
      - Tracks which contracts are currently subscribed
      - On disconnect, auto-reconnects + re-subscribes all prior contracts
      - STATUS heartbeats monitored; if silent > 10s, treat as dead
      - Exposes async iterator of ThetaTrade events (sweep detector consumes)

    Budget: 15K contract subscriptions on Standard tier. SubscriptionManager
    (separate class) decides which contracts to subscribe to; this class
    just executes + tracks.
    """

    def __init__(self, ws_url: str = WS_URL):
        self.ws_url = ws_url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscriptions: dict[str, SubscribeSpec] = {}
        self._next_req_id = 0
        self._last_heartbeat = 0.0
        self._out_queue: asyncio.Queue[ThetaTrade] = asyncio.Queue(maxsize=10_000)
        self._stop = asyncio.Event()
        self._connected = asyncio.Event()
        self._reconnect_delay = 1.0  # exponential backoff starts here
        self.on_trade: Callable[[ThetaTrade], None] | None = None

    # ── Public API ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the connection loop (call from FastAPI lifespan task)."""
        asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    def is_healthy(self) -> bool:
        """True if connected and heartbeats are recent."""
        if not self._connected.is_set():
            return False
        return (time.time() - self._last_heartbeat) < 10.0

    async def subscribe(self, spec: SubscribeSpec) -> bool:
        """Subscribe to a contract. Idempotent. Returns True if subscribe sent."""
        if spec.key in self._subscriptions:
            return False
        if len(self._subscriptions) >= 14_500:  # stay under 15K hard cap
            print(f"[THETA_STREAM] subscription budget hit, cannot add {spec.key}")
            return False
        self._subscriptions[spec.key] = spec
        if self._ws and self._connected.is_set():
            await self._send_subscribe(spec)
        return True

    async def unsubscribe(self, spec: SubscribeSpec) -> bool:
        if spec.key not in self._subscriptions:
            return False
        self._subscriptions.pop(spec.key)
        if self._ws and self._connected.is_set():
            await self._send_unsubscribe(spec)
        return True

    async def trades(self) -> AsyncIterator[ThetaTrade]:
        """Async iterator of trade events. Consumer-side API."""
        while not self._stop.is_set():
            try:
                evt = await asyncio.wait_for(self._out_queue.get(), timeout=1.0)
                yield evt
            except asyncio.TimeoutError:
                continue

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    # ── Internal ───────────────────────────────────────────────────

    async def _connection_loop(self) -> None:
        """Connect + stay connected. Reconnects with exponential backoff."""
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.ws_url, ping_interval=20, close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    self._last_heartbeat = time.time()
                    self._reconnect_delay = 1.0  # reset on successful connect
                    print(f"[THETA_STREAM] connected, resubscribing {len(self._subscriptions)} contracts")

                    # Resubscribe everything we had before the drop
                    for spec in list(self._subscriptions.values()):
                        await self._send_subscribe(spec)

                    await self._read_loop(ws)

            except (ConnectionClosed, WebSocketException, OSError) as e:
                print(f"[THETA_STREAM] connection lost: {e}")
            except Exception as e:
                print(f"[THETA_STREAM] unexpected error: {e}")
            finally:
                self._ws = None
                self._connected.clear()

            if self._stop.is_set():
                return

            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    async def _read_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
            except asyncio.TimeoutError:
                # No message in 15s — heartbeat should arrive every 1s
                print("[THETA_STREAM] no heartbeat for 15s, forcing reconnect")
                await ws.close()
                return

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            header = msg.get("header") or {}
            mtype = header.get("type", "")

            if mtype == "STATUS":
                self._last_heartbeat = time.time()
            elif mtype == "TRADE":
                evt = self._parse_trade(msg)
                if evt:
                    # Invoke direct callback (for sync-ish consumers like logging)
                    if self.on_trade:
                        try:
                            self.on_trade(evt)
                        except Exception as e:
                            print(f"[THETA_STREAM] on_trade callback error: {e}")
                    # Queue for async iterator consumers (sweep detector)
                    try:
                        self._out_queue.put_nowait(evt)
                    except asyncio.QueueFull:
                        # Queue is backed up — drop oldest to keep newest flowing
                        try:
                            self._out_queue.get_nowait()
                            self._out_queue.put_nowait(evt)
                        except Exception:
                            pass
            elif mtype == "REQ_RESPONSE":
                resp = header.get("response")
                if resp and resp != "SUBSCRIBED":
                    print(f"[THETA_STREAM] req response: {resp} id={header.get('req_id')}")

    def _parse_trade(self, msg: dict) -> ThetaTrade | None:
        """Convert raw Theta TRADE message to ThetaTrade dataclass.

        Raw schema (verified via smoke test Apr 17):
          header:   {status, type: "TRADE"}
          contract: {security_type, root, expiration (int YYYYMMDD),
                     strike (int 10ths-of-a-cent), right ("C"|"P")}
          trade:    {ms_of_day, sequence, size, condition, price, exchange, date}
        """
        try:
            c = msg.get("contract") or {}
            t = msg.get("trade") or {}
            if not c or not t:
                return None
            root = c.get("root", "")
            exp_int = int(c.get("expiration") or 0)
            strike_1000ths = int(c.get("strike") or 0)
            right_char = (c.get("right") or "").upper()
            if not root or not exp_int or right_char not in ("C", "P"):
                return None

            # Convert wire formats to human-friendly
            exp_str = f"{exp_int // 10000:04d}-{(exp_int // 100) % 100:02d}-{exp_int % 100:02d}"
            strike_dollars = strike_1000ths / 1000.0
            right_long = "call" if right_char == "C" else "put"

            return ThetaTrade(
                ticker=root,
                expiration=exp_str,
                strike=strike_dollars,
                right=right_long,
                timestamp_ms=int(t.get("ms_of_day") or 0),
                sequence=int(t.get("sequence") or 0),
                size=int(t.get("size") or 0),
                price=float(t.get("price") or 0),
                exchange=int(t.get("exchange") or 0),
                condition=int(t.get("condition") or 0),
                ext_conditions=(
                    int(t.get("ext_condition1") or 255),
                    int(t.get("ext_condition2") or 255),
                    int(t.get("ext_condition3") or 255),
                    int(t.get("ext_condition4") or 255),
                ),
            )
        except (ValueError, TypeError, KeyError) as e:
            print(f"[THETA_STREAM] parse error: {e}")
            return None

    async def _send_subscribe(self, spec: SubscribeSpec) -> None:
        req = {
            "msg_type": "STREAM",
            "sec_type": "OPTION",
            "req_type": "TRADE",
            "add": True,
            "id": self._next_req_id,
            "contract": {
                "root": spec.root,
                "expiration": spec.expiration,
                "strike": spec.strike_1000ths,
                "right": spec.right,
            },
        }
        self._next_req_id += 1
        try:
            await self._ws.send(json.dumps(req))
        except Exception as e:
            print(f"[THETA_STREAM] subscribe send failed: {e}")

    async def _send_unsubscribe(self, spec: SubscribeSpec) -> None:
        req = {
            "msg_type": "STREAM",
            "sec_type": "OPTION",
            "req_type": "TRADE",
            "add": False,
            "id": self._next_req_id,
            "contract": {
                "root": spec.root,
                "expiration": spec.expiration,
                "strike": spec.strike_1000ths,
                "right": spec.right,
            },
        }
        self._next_req_id += 1
        try:
            await self._ws.send(json.dumps(req))
        except Exception as e:
            print(f"[THETA_STREAM] unsubscribe send failed: {e}")


# ── Module-level singletons (following the server/massive.py pattern) ──

_client_singleton: ThetaDataClient | None = None
_stream_singleton: ThetaStream | None = None


def get_client() -> ThetaDataClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = ThetaDataClient()
    return _client_singleton


def get_stream() -> ThetaStream:
    global _stream_singleton
    if _stream_singleton is None:
        _stream_singleton = ThetaStream()
    return _stream_singleton
