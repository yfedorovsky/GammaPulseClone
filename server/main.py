"""FastAPI app exposing the same routes the live GammaPulse frontend calls.

Run:
  uvicorn server.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any

import json

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .cache import cache
from .config import get_settings
from .flow_alerts import init_alert_db, get_alerts as get_flow_alerts, run_flow_scanner
from .trade_tracker import init_tracker_db, get_all_trades, run_position_monitor
from .gex import compute_exp_data, build_signal
from .snapshots import init_db, series as snapshot_series
from .stream import streamer
from .tickers import all_tickers
from .tradier import TradierClient
from .worker import run_worker

MACRO_KEY = "MACRO (ALL 200D)"

_stop = asyncio.Event()
_worker_task: asyncio.Task | None = None


_flow_task: asyncio.Task | None = None
_monitor_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_alert_db()
    init_tracker_db()
    await streamer.ensure_running()
    global _worker_task, _flow_task, _monitor_task
    _worker_task = asyncio.create_task(run_worker(_stop))
    _flow_task = asyncio.create_task(run_flow_scanner(_stop))
    _monitor_task = asyncio.create_task(run_position_monitor(_stop))
    try:
        yield
    finally:
        _stop.set()
        await streamer.stop()
        for task in (_worker_task, _flow_task, _monitor_task):
            if task:
                try:
                    await asyncio.wait_for(task, timeout=5)
                except asyncio.TimeoutError:
                    task.cancel()


app = FastAPI(title="GammaPulse Clone", version="1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---

class ChainsReq(BaseModel):
    tickers: list[str]
    strikes: int | None = 60


class QuotesReq(BaseModel):
    tickers: list[str]


class SubscribeReq(BaseModel):
    tickers: list[str]


class SignalLogReq(BaseModel):
    ticker: str
    signal: str
    regime: str
    spot: float
    king: float
    floor: float | None = None
    ceiling: float | None = None
    king_pos: bool | None = None


# --- Helpers ---

def _trim_to_window(exp_data: dict[str, Any], window: int) -> dict[str, Any]:
    """Limit strikes to the nearest `window` around the first strike with king."""
    if not window or window <= 0:
        return exp_data
    out = {}
    for exp, ed in exp_data.items():
        strikes = ed.get("strikes") or []
        if len(strikes) <= window:
            out[exp] = ed
            continue
        king = ed.get("king") or 0
        # Find index of king and take ±window/2 around it
        idx = 0
        for i, s in enumerate(strikes):
            if s["strike"] == king:
                idx = i
                break
        half = window // 2
        lo = max(0, idx - half)
        hi = min(len(strikes), lo + window)
        lo = max(0, hi - window)
        trimmed = dict(ed)
        trimmed["strikes"] = strikes[lo:hi]
        out[exp] = trimmed
    return out


def _ticker_public(state: dict[str, Any], strikes_window: int | None = 60) -> dict[str, Any]:
    exps = state.get("exps") or []
    exp_data = state.get("exp_data") or {}
    if strikes_window:
        exp_data = _trim_to_window(exp_data, strikes_window)
    return {
        "exp_data": exp_data,
        "exps": exps,
        "spot": state.get("actual_spot") or state.get("_spot"),
        "timestamp": state.get("timestamp"),
        "_cached": True,
        # scanner-style flat fields (useful for clients that want them)
        "king": state.get("king"),
        "floor": state.get("floor"),
        "ceiling": state.get("ceiling"),
        "pos_gex": state.get("pos_gex"),
        "neg_gex": state.get("neg_gex"),
        "net_delta": state.get("net_delta"),
        "net_vanna": state.get("net_vanna"),
        "signal": state.get("signal"),
        "regime": state.get("regime"),
        "iv": state.get("iv"),
    }


async def _get_or_compute(ticker: str) -> dict[str, Any] | None:
    state = await cache.get(ticker)
    if state is not None:
        return state
    # Not in cache (e.g. custom ticker) - compute on demand
    tradier = TradierClient()
    try:
        q = await tradier.quotes([ticker])
        spot = q.get(ticker)
        if not spot:
            return None
        from .worker import _compute_one  # local to avoid cycle
        state = await _compute_one(tradier, ticker, spot)
        if state:
            await cache.put(ticker, state)
        return state
    finally:
        await tradier.close()


# --- Routes ---

@app.get("/api/health")
async def health():
    tradier_token_set = bool(get_settings().tradier_token)
    ws = cache.worker_status()
    # Basic US market-hours guess (9:30-16:00 ET). Real app would use an exchange calendar.
    now = time.localtime()
    weekday = now.tm_wday < 5
    minute_of_day = now.tm_hour * 60 + now.tm_min
    market_open = weekday and 9 * 60 + 30 <= minute_of_day < 16 * 60
    return {
        "status": "ok",
        "version": "1.0",
        "token_expired": not tradier_token_set,
        "worker": ws,
        "market": {
            "open": market_open,
            "status": "LIVE" if market_open else "CLOSED",
            "color": "#10dc9a" if market_open else "#ff6b6b",
        },
        "ai_enabled": False,
        "chain_provider": "tradier",
        "polygon_configured": False,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


@app.post("/api/chains")
async def chains(req: ChainsReq):
    out: dict[str, Any] = {}
    tasks = [_get_or_compute(t.upper()) for t in req.tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for t, state in zip((s.upper() for s in req.tickers), results):
        if isinstance(state, Exception) or state is None:
            out[t] = {
                "exp_data": {},
                "exps": [],
                "spot": None,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "_cached": False,
            }
            continue
        # Also subscribe so the price stream picks it up
        await streamer.subscribe([t])
        out[t] = _ticker_public(state, strikes_window=req.strikes or 60)
    return out


@app.get("/api/confluence")
async def confluence():
    """Hard-pinned to SPY/QQQ/IWM regardless of client state."""
    pins = ["SPY", "QQQ", "IWM"]
    tasks = [_get_or_compute(t) for t in pins]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, Any] = {}
    for t, state in zip(pins, results):
        if isinstance(state, Exception) or state is None:
            out[t] = {"exp_data": {}, "exps": [], "spot": None, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
            continue
        out[t] = _ticker_public(state, strikes_window=None)
    return out


@app.post("/api/quotes")
async def quotes_route(req: QuotesReq):
    # Pull from stream cache first; fall back to live Tradier for anything missing
    syms = [t.upper() for t in req.tickers]
    last = streamer.last_prices()
    out: dict[str, float | None] = {t: last.get(t) for t in syms}
    missing = [t for t, v in out.items() if v is None]
    if missing:
        tradier = TradierClient()
        try:
            fresh = await tradier.quotes(missing)
        finally:
            await tradier.close()
        out.update(fresh)
    # Also make sure future SSE ticks include these
    await streamer.subscribe(syms)
    return {k: v for k, v in out.items() if v is not None}


@app.get("/api/scanner")
async def scanner():
    snap = await cache.snapshot()
    tickers_out: list[dict[str, Any]] = []
    for ticker, state in sorted(snap.items()):
        entry = {
            "_ticker": ticker,
            "_spot": state.get("_spot"),
            "_updated": state.get("_updated"),
            "_tier": state.get("_tier"),
            "actual_spot": state.get("actual_spot"),
            "king": state.get("king"),
            "floor": state.get("floor"),
            "ceiling": state.get("ceiling"),
            "pos_gex": state.get("pos_gex"),
            "neg_gex": state.get("neg_gex"),
            "net_delta": state.get("net_delta"),
            "net_vanna": state.get("net_vanna"),
            "signal": state.get("signal"),
            "regime": state.get("regime"),
            "iv": state.get("iv"),
            "exps": state.get("exps"),
            "exp_data": state.get("exp_data"),
        }
        tickers_out.append(entry)
    return {
        "tickers": tickers_out,
        "worker_status": cache.worker_status(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


@app.post("/api/stream/subscribe")
async def stream_subscribe(req: SubscribeReq):
    subs = await streamer.subscribe(req.tickers)
    return {"subscribed": subs, "pending": []}


@app.get("/api/stream/prices")
async def stream_prices(request: Request):
    """SSE fallback for spot price streaming."""
    await streamer.ensure_running()

    async def gen():
        async for ev in streamer.sse_iter():
            if await request.is_disconnected():
                break
            yield ev

    return EventSourceResponse(gen())


@app.websocket("/ws/prices")
async def ws_prices(websocket: WebSocket):
    """Primary spot-price channel: tick-by-tick WebSocket.

    Protocol:
      client → { "subscribe": ["SPY","QQQ"] }   (optional; may be sent repeatedly)
      server → { "SPY": 679.25, "QQQ": 609.38 }  every ~STREAM_POLL_SECONDS
    """
    import asyncio

    await websocket.accept()
    await streamer.ensure_running()
    settings_local = get_settings()

    async def reader():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    payload = json.loads(msg)
                except Exception:
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("subscribe"), list):
                    await streamer.subscribe([str(t).upper() for t in payload["subscribe"]])
                elif isinstance(payload, dict) and isinstance(payload.get("unsubscribe"), list):
                    await streamer.unsubscribe([str(t).upper() for t in payload["unsubscribe"]])
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    reader_task = asyncio.create_task(reader())
    last_tick = -1
    try:
        while True:
            tick = streamer._tick  # type: ignore[attr-defined]
            prices = streamer.last_prices()
            if tick != last_tick and prices:
                last_tick = tick
                await websocket.send_text(json.dumps(prices))
            await asyncio.sleep(settings_local.stream_poll_seconds)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        reader_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/alerts")
async def alerts(since: int = 0, limit: int = 100, ticker: str = ""):
    """Get timestamped flow alerts. Use ?since=<epoch> for polling."""
    rows = get_flow_alerts(since_ts=since, limit=limit, ticker=ticker or None)
    return {"alerts": rows, "count": len(rows)}


@app.get("/api/trades")
async def trades(limit: int = 50):
    """Get tracked trades with their exit signals."""
    return {"trades": get_all_trades(limit)}


@app.post("/api/signals/log")
async def signals_log(req: SignalLogReq):
    # Could be persisted for signal accuracy tracking; for now ack.
    return {"ok": True, "ticker": req.ticker, "ts": time.time()}


# --- Clone-only conveniences ---

@app.get("/api/history")
async def history(ticker: str, limit: int = 500):
    if not ticker:
        raise HTTPException(400, "ticker required")
    return {"ticker": ticker.upper(), "series": snapshot_series(ticker.upper(), limit)}


@app.get("/api/mtf")
async def mtf(ticker: str):
    t = ticker.upper()
    state = await _get_or_compute(t)
    if state is None:
        raise HTTPException(404, f"no data for {t}")
    table: list[dict[str, Any]] = []
    for exp in state.get("exps") or []:
        ed = (state.get("exp_data") or {}).get(exp) or {}
        table.append(
            {
                "expiration": exp,
                "king": ed.get("king"),
                "floor": ed.get("floor"),
                "ceiling": ed.get("ceiling"),
                "zgl": ed.get("zgl"),
                "pos_gex": ed.get("pos_gex"),
                "neg_gex": ed.get("neg_gex"),
                "iv": ed.get("iv"),
            }
        )
    return {"ticker": t, "spot": state.get("actual_spot"), "table": table}


@app.get("/api/flow/{ticker}")
async def flow_detail(ticker: str):
    """Enhanced flow detail: scans first N expirations for unusual volume,
    returns per-option rows with expiration, type, side, sentiment, volume,
    OI, V/OI, last, notional, IV, delta — matching the original's layout."""
    t = ticker.upper()
    tradier = TradierClient()
    try:
        exps = await tradier.expirations(t)
        if not exps:
            raise HTTPException(404, f"no expirations for {t}")
        # Scan up to 12 near-term expirations for broader volume coverage
        import asyncio
        chains = await asyncio.gather(
            *(tradier.chain(t, e) for e in exps[:12]),
            return_exceptions=True,
        )
        spot_q = await tradier.quotes([t])
        spot = spot_q.get(t, 0)
    finally:
        await tradier.close()

    rows: list[dict[str, Any]] = []
    call_vol = 0.0
    put_vol = 0.0
    for exp_chain in chains:
        if isinstance(exp_chain, Exception):
            continue
        for o in exp_chain:
            otype = (o.get("option_type") or "").lower()
            vol = float(o.get("volume") or 0)
            oi = float(o.get("open_interest") or 0)
            last_price = float(o.get("last") or 0)
            bid = float(o.get("bid") or 0)
            ask = float(o.get("ask") or 0)
            greeks = o.get("greeks") or {}
            iv = float(greeks.get("mid_iv") or greeks.get("smv_vol") or 0)
            delta = float(greeks.get("delta") or 0)
            exp_date = o.get("expiration_date") or ""

            if otype == "call":
                call_vol += vol
            else:
                put_vol += vol

            if vol > 0 and oi > 0 and vol >= 2 * oi:
                mid = (bid + ask) / 2 if bid and ask else last_price
                spread = ask - bid if ask > bid else 0.01
                dist_to_mid = abs(last_price - mid) / spread if spread > 0 else 0
                # Side: ASK if near ask, BID if near bid, MID if within 20% of midpoint
                if dist_to_mid < 0.2:
                    side = "MID"
                elif last_price >= mid:
                    side = "ASK"
                else:
                    side = "BID"
                # Sentiment: ASK calls / BID puts = bullish; BID calls / ASK puts = bearish; MID = neutral
                if side == "MID":
                    sentiment = "NEUTRAL"
                elif otype == "call":
                    sentiment = "BULLISH" if side == "ASK" else "BEARISH"
                else:
                    sentiment = "BEARISH" if side == "ASK" else "BULLISH"
                notional = vol * last_price * 100  # volume × price × 100 shares
                rows.append(
                    {
                        "exp": exp_date,
                        "strike": o.get("strike"),
                        "type": otype,
                        "side": side,
                        "sentiment": sentiment,
                        "volume": vol,
                        "oi": oi,
                        "vol_oi": round(vol / oi, 1) if oi else 0,
                        "last": last_price,
                        "notional": notional,
                        "iv": round(iv * 100, 1) if iv else 0,
                        "delta": round(delta, 3),
                    }
                )
    # Sort by volume descending and cap at top 50 to match original density
    rows.sort(key=lambda r: r["volume"], reverse=True)
    rows = rows[:50]
    pc_ratio = round(put_vol / call_vol, 2) if call_vol else 0
    return {
        "ticker": t,
        "spot": spot,
        "rows": rows,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "pc_ratio": pc_ratio,
    }


@app.get("/api/earnings")
async def earnings_calendar():
    """Weekly earnings calendar filtered to our ticker universe.

    Uses Tradier's calendar or a static approach. Since Tradier doesn't have
    a dedicated earnings endpoint, we'll provide a placeholder that can be
    replaced with a Nasdaq/Yahoo scraper later.
    """
    import datetime

    today = datetime.date.today()
    # Find Monday of this week
    monday = today - datetime.timedelta(days=today.weekday())
    days = []
    for i in range(5):
        day = monday + datetime.timedelta(days=i)
        days.append({
            "date": day.isoformat(),
            "weekday": ["MON", "TUE", "WED", "THU", "FRI"][i],
            "is_today": day == today,
            "tickers": [],  # populated by earnings data source
        })
    return {
        "week_start": monday.isoformat(),
        "week_end": (monday + datetime.timedelta(days=4)).isoformat(),
        "days": days,
        "source": "Placeholder — connect a Nasdaq or Yahoo earnings feed for real data",
    }


@app.get("/api/flow/scan")
async def flow_scan_all():
    snap = await cache.snapshot()
    hot: list[dict[str, Any]] = []
    for ticker, state in snap.items():
        ed = (state.get("exp_data") or {}).get(MACRO_KEY) or {}
        strikes = ed.get("strikes") or []
        top = sorted(strikes, key=lambda s: abs(s.get("net_gex") or 0), reverse=True)[:3]
        hot.append(
            {
                "ticker": ticker,
                "spot": state.get("actual_spot"),
                "signal": state.get("signal"),
                "regime": state.get("regime"),
                "top": top,
            }
        )
    hot.sort(key=lambda r: abs((r["top"][0] or {}).get("net_gex") or 0) if r["top"] else 0, reverse=True)
    return {"results": hot[:50]}


@app.get("/api/bars/{ticker}")
async def bars(ticker: str, interval: str = "5min", days: int = 5):
    """Fetch OHLCV bars for the overlay chart.
    interval: 'daily' | '5min' | '15min' | '1min'
    days: how many calendar days back to fetch.
    """
    import datetime

    t = ticker.upper()
    tradier = TradierClient()
    try:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        if interval == "daily":
            start = end - datetime.timedelta(days=max(days, 30))
        result = await tradier.history(
            t,
            interval=interval,
            start=start.isoformat(),
            end=end.isoformat(),
        )
    finally:
        await tradier.close()
    return {"ticker": t, "interval": interval, "bars": result}


@app.get("/api/tickers")
async def tickers_list():
    return {"tickers": all_tickers()}


class TickerModReq(BaseModel):
    tickers: list[str]


@app.post("/api/tickers/add")
async def tickers_add(req: TickerModReq):
    """Add custom tickers to the scanner universe at runtime."""
    from .tickers import TIER_1
    added = []
    for t in req.tickers:
        sym = t.upper().strip()
        if sym and sym not in all_tickers():
            TIER_1.append(sym)
            added.append(sym)
    return {"added": added, "total": len(all_tickers())}


@app.post("/api/tickers/remove")
async def tickers_remove(req: TickerModReq):
    """Remove tickers from the scanner universe."""
    from .tickers import TIER_1, TIER_2, TIER_3
    removed = []
    for t in req.tickers:
        sym = t.upper().strip()
        for bucket in (TIER_1, TIER_2, TIER_3):
            if sym in bucket:
                bucket.remove(sym)
                removed.append(sym)
                break
    return {"removed": removed, "total": len(all_tickers())}


# Root for convenience
@app.get("/")
async def root():
    return JSONResponse({"app": "GammaPulse Clone", "docs": "/docs"})
