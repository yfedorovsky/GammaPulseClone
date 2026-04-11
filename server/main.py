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
async def earnings_calendar(week_offset: int = 0):
    """Weekly calendar: earnings from Finnhub + hardcoded economic events."""
    import datetime

    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    friday = monday + datetime.timedelta(days=4)

    days = []
    for i in range(5):
        day = monday + datetime.timedelta(days=i)
        days.append({
            "date": day.isoformat(),
            "weekday": ["MON", "TUE", "WED", "THU", "FRI"][i],
            "is_today": day == today,
            "tickers": [],
        })

    # Fetch earnings from Finnhub if API key is set
    s = get_settings()
    our_tickers = set(t.upper() for t in all_tickers())

    if s.finnhub_api_key:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={
                        "from": monday.isoformat(),
                        "to": friday.isoformat(),
                        "token": s.finnhub_api_key,
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for ec in data.get("earningsCalendar", []):
                        sym = ec.get("symbol", "").upper()
                        if sym not in our_tickers:
                            continue
                        edate = ec.get("date", "")
                        for d in days:
                            if d["date"] == edate:
                                timing = "bmo" if ec.get("hour") == "bmo" else "amc" if ec.get("hour") == "amc" else ec.get("hour", "")
                                result = None
                                if ec.get("epsActual") is not None and ec.get("epsEstimate") is not None:
                                    result = "beat" if ec["epsActual"] > ec["epsEstimate"] else "miss"
                                d["tickers"].append({
                                    "ticker": sym,
                                    "timing": timing,
                                    "result": result,
                                    "eps_actual": ec.get("epsActual"),
                                    "eps_estimate": ec.get("epsEstimate"),
                                })
                                break
        except Exception as e:
            print(f"[EARNINGS] Finnhub fetch failed: {e}")

    # Economic events (hardcoded major events)
    economic_events = _get_economic_events(monday, friday)

    return {
        "week_start": monday.isoformat(),
        "week_end": friday.isoformat(),
        "days": days,
        "economic_events": economic_events,
        "source": "Finnhub" if s.finnhub_api_key else "No API key — add FINNHUB_API_KEY to .env",
    }


def _get_economic_events(monday, friday):
    """Return major economic events that fall within the given week."""
    import datetime

    # Known recurring economic event dates for 2026
    # OPEX = 3rd Friday of each month
    events = []
    year = monday.year

    # FOMC meeting dates (approximate — 8 meetings per year)
    fomc_dates = [
        (1, 28), (3, 18), (5, 6), (6, 17), (7, 29), (9, 16), (11, 4), (12, 16),
    ]
    for m, d in fomc_dates:
        try:
            dt = datetime.date(year, m, d)
            if monday <= dt <= friday:
                events.append({"name": "FOMC Decision", "date": dt.isoformat(), "time": "2:00 PM ET", "icon": "🏛", "impact": "high"})
        except ValueError:
            pass

    # CPI: usually 2nd week of month
    for m in range(1, 13):
        try:
            dt = datetime.date(year, m, 12)
            if monday <= dt <= friday:
                events.append({"name": "CPI Report", "date": dt.isoformat(), "time": "8:30 AM ET", "icon": "📊", "impact": "high"})
        except ValueError:
            pass

    # PPI: usually day after CPI
    for m in range(1, 13):
        try:
            dt = datetime.date(year, m, 13)
            if monday <= dt <= friday:
                events.append({"name": "PPI Report", "date": dt.isoformat(), "time": "8:30 AM ET", "icon": "📊", "impact": "high"})
        except ValueError:
            pass

    # Jobs Report: 1st Friday of month
    for m in range(1, 13):
        first = datetime.date(year, m, 1)
        first_friday = first + datetime.timedelta(days=(4 - first.weekday()) % 7)
        if monday <= first_friday <= friday:
            events.append({"name": "Jobs Report / NFP", "date": first_friday.isoformat(), "time": "8:30 AM ET", "icon": "👷", "impact": "high"})

    # OPEX: 3rd Friday of month
    for m in range(1, 13):
        first = datetime.date(year, m, 1)
        first_friday = first + datetime.timedelta(days=(4 - first.weekday()) % 7)
        third_friday = first_friday + datetime.timedelta(weeks=2)
        if monday <= third_friday <= friday:
            # Quad witching in March, June, Sept, Dec
            label = "Quad Witching OPEX" if m in (3, 6, 9, 12) else "Monthly OPEX"
            events.append({"name": label, "date": third_friday.isoformat(), "time": "Market Close", "icon": "📅", "impact": "medium"})

    return events


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


# --- News ---

_BULLISH_KW = {
    "beat", "surge", "upgrade", "approval", "record", "raises", "bullish",
    "growth", "outperform", "buy", "strong", "soar", "rally", "jumps", "breakout",
}
_BEARISH_KW = {
    "miss", "plunge", "downgrade", "lawsuit", "recall", "cuts", "bearish",
    "decline", "underperform", "sell", "weak", "crash", "drops", "warning", "layoff",
}


def _tag_sentiment(headline: str) -> str:
    words = set(headline.lower().split())
    if words & _BULLISH_KW:
        return "BULLISH"
    if words & _BEARISH_KW:
        return "BEARISH"
    return "NEUTRAL"


@app.get("/api/news/{ticker}")
async def news(ticker: str):
    import datetime
    import httpx

    api_key = get_settings().finnhub_api_key
    if not api_key:
        return JSONResponse(
            {"error": "FINNHUB_API_KEY not configured", "articles": []},
            status_code=200,
        )

    sym = ticker.upper()
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    url = (
        f"https://finnhub.io/api/v1/company-news"
        f"?symbol={sym}&from={week_ago.isoformat()}&to={today.isoformat()}&token={api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw: list[dict] = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Finnhub error: {exc}") from exc

    articles = []
    for item in raw[:50]:  # cap at 50
        articles.append(
            {
                "id": item.get("id"),
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "image": item.get("image", ""),
                "category": item.get("category", ""),
                "datetime": item.get("datetime"),
                "sentiment": _tag_sentiment(item.get("headline", "")),
            }
        )

    return {"ticker": sym, "articles": articles}


# --- Sectors ---

SECTORS: dict[str, dict] = {
    "XLK":  {"name": "Technology",    "weight": 31.0, "holdings": ["AAPL","MSFT","NVDA","AVGO","CRM","ADBE","AMD","ORCL","CSCO","INTC"]},
    "XLF":  {"name": "Financials",    "weight": 13.0, "holdings": ["BRK.B","JPM","V","MA","BAC","WFC","GS","MS","AXP","SCHW"]},
    "XLV":  {"name": "Health Care",   "weight": 12.0, "holdings": ["UNH","JNJ","LLY","ABBV","MRK","PFE","TMO","ABT","AMGN","DHR"]},
    "XLE":  {"name": "Energy",        "weight":  3.5, "holdings": ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","OXY","WMB"]},
    "XLI":  {"name": "Industrials",   "weight":  8.5, "holdings": ["GE","CAT","UNP","HON","RTX","BA","DE","LMT","UPS","ADP"]},
    "XLY":  {"name": "Cons. Disc.",   "weight": 10.0, "holdings": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG"]},
    "XLC":  {"name": "Comm. Svc.",    "weight":  9.0, "holdings": ["META","GOOGL","GOOG","NFLX","DIS","CMCSA","T","VZ","TMUS","EA"]},
    "XLP":  {"name": "Cons. Staples", "weight":  6.0, "holdings": ["PG","KO","PEP","COST","WMT","PM","MO","CL","MDLZ","GIS"]},
    "XLRE": {"name": "Real Estate",   "weight":  2.5, "holdings": ["PLD","AMT","CCI","EQIX","PSA","SPG","O","WELL","DLR","AVB"]},
    "XLU":  {"name": "Utilities",     "weight":  2.5, "holdings": ["NEE","SO","DUK","CEG","SRE","AEP","D","EXC","XEL","WEC"]},
    "XLB":  {"name": "Materials",     "weight":  2.0, "holdings": ["LIN","APD","SHW","FCX","ECL","NEM","NUE","VMC","MLM","DOW"]},
}

# In-memory caches for sector data
_sector_price_cache: dict[str, Any] = {}
_sector_holdings_cache: dict[str, Any] = {}


async def _fetch_daily_history(tradier: TradierClient, symbol: str, days: int = 35) -> list[float]:
    """Return list of daily close prices (most recent last)."""
    import datetime
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days + 15)
    try:
        bars = await tradier.history(symbol, interval="daily", start=start.isoformat(), end=end.isoformat())
        return [b["close"] for b in bars if b.get("close") is not None]
    except Exception:
        return []


def _rs_ratio_momentum(sector_closes: list[float], spy_closes: list[float]) -> tuple[float, float]:
    """Compute RS-Ratio and RS-Momentum centred at 100."""
    def _ret(closes: list[float], n: int) -> float | None:
        if len(closes) < n + 1:
            return None
        old = closes[-(n + 1)]
        new_val = closes[-1]
        if old == 0:
            return None
        return (new_val - old) / old

    ret20_sec = _ret(sector_closes, 20)
    ret20_spy = _ret(spy_closes, 20)
    if ret20_sec is None or ret20_spy is None or ret20_spy == 0:
        rs_ratio = 100.0
    else:
        rs_ratio = round((ret20_sec / ret20_spy) * 100, 2)

    if len(sector_closes) >= 26 and len(spy_closes) >= 26:
        sec_5ago = sector_closes[:-5] if len(sector_closes) > 5 else sector_closes
        spy_5ago = spy_closes[:-5] if len(spy_closes) > 5 else spy_closes
        ret20_sec_5ago = _ret(sec_5ago, 20)
        ret20_spy_5ago = _ret(spy_5ago, 20)
        if ret20_sec_5ago is not None and ret20_spy_5ago is not None and ret20_spy_5ago != 0:
            rs_ratio_5ago = (ret20_sec_5ago / ret20_spy_5ago) * 100
        else:
            rs_ratio_5ago = 100.0
        rs_momentum = round(rs_ratio - rs_ratio_5ago + 100, 2)
    else:
        rs_momentum = 100.0

    return rs_ratio, rs_momentum


@app.get("/api/sectors")
async def sectors_list():
    """Return sector data: weight, price change, RS-ratio, RS-momentum. Cached 5 min."""
    now = time.time()
    cached = _sector_price_cache.get("data")
    if cached and now - _sector_price_cache.get("ts", 0) < 300:
        return {"sectors": cached, "cached": True}

    tradier = TradierClient()
    try:
        all_syms = list(SECTORS.keys()) + ["SPY"]
        history_tasks = [_fetch_daily_history(tradier, sym) for sym in all_syms]
        histories = await asyncio.gather(*history_tasks, return_exceptions=True)
        quotes = await tradier.quotes(all_syms)
    finally:
        await tradier.close()

    spy_idx = all_syms.index("SPY")
    spy_closes = histories[spy_idx] if not isinstance(histories[spy_idx], Exception) else []

    result = []
    for sym in list(SECTORS.keys()):
        meta = SECTORS[sym]
        idx = all_syms.index(sym)
        closes = histories[idx] if not isinstance(histories[idx], Exception) else []

        spot = quotes.get(sym)
        if closes and len(closes) >= 2:
            prev = closes[-2]
            curr = spot if spot else closes[-1]
            pct_change = round((curr - prev) / prev * 100, 2) if prev else 0.0
        elif spot and closes:
            prev = closes[-1]
            pct_change = round((spot - prev) / prev * 100, 2) if prev else 0.0
        else:
            pct_change = 0.0

        rs_ratio, rs_momentum = _rs_ratio_momentum(closes, spy_closes)

        result.append({
            "ticker": sym,
            "name": meta["name"],
            "weight": meta["weight"],
            "pct_change": pct_change,
            "spot": spot,
            "rs_ratio": rs_ratio,
            "rs_momentum": rs_momentum,
        })

    _sector_price_cache["data"] = result
    _sector_price_cache["ts"] = now
    return {"sectors": result, "cached": False}


@app.get("/api/sectors/{sector}")
async def sector_detail(sector: str):
    """Return top 10 holdings of a sector with GEX data from cache. Cached 5 min."""
    sym = sector.upper()
    if sym not in SECTORS:
        raise HTTPException(404, f"Unknown sector {sym}")

    now = time.time()
    cached_entry = _sector_holdings_cache.get(sym)
    if cached_entry and now - cached_entry.get("ts", 0) < 300:
        return {**cached_entry["data"], "cached": True}

    meta = SECTORS[sym]
    holdings = meta["holdings"]

    tasks = [cache.get(h) for h in holdings]
    states = await asyncio.gather(*tasks, return_exceptions=True)

    tradier = TradierClient()
    try:
        spot_map = await tradier.quotes(holdings)
    finally:
        await tradier.close()

    holding_rows: list[dict[str, Any]] = []
    total_weight = 0.0
    weighted_king_dist_num = 0.0
    regime_votes: dict[str, float] = {}
    n = len(holdings)

    for i, h in enumerate(holdings):
        state = states[i]
        if isinstance(state, Exception):
            state = None
        spot = spot_map.get(h) or (state.get("actual_spot") or state.get("_spot") if state else None)
        king = state.get("king") if state else None
        signal = state.get("signal", "–") if state else "–"
        regime = state.get("regime", "–") if state else "–"
        floor_val = state.get("floor") if state else None
        ceiling_val = state.get("ceiling") if state else None

        king_dist = None
        if spot and king and spot > 0:
            king_dist = round((king - spot) / spot * 100, 2)

        w = 1.0 / n
        total_weight += w
        if king_dist is not None:
            weighted_king_dist_num += king_dist * w
        if regime and regime != "–":
            regime_votes[regime] = regime_votes.get(regime, 0) + w

        holding_rows.append({
            "ticker": h,
            "spot": round(spot, 2) if spot else None,
            "king": king,
            "signal": signal,
            "regime": regime,
            "floor": floor_val,
            "ceiling": ceiling_val,
            "king_dist": king_dist,
        })

    agg_king_dist = round(weighted_king_dist_num / total_weight, 2) if total_weight > 0 else None
    agg_regime = max(regime_votes, key=lambda k: regime_votes[k]) if regime_votes else "–"

    data: dict[str, Any] = {
        "sector": sym,
        "name": meta["name"],
        "holdings": holding_rows,
        "aggregate": {
            "regime": agg_regime,
            "king_dist": agg_king_dist,
        },
    }
    _sector_holdings_cache[sym] = {"data": data, "ts": now}
    return {**data, "cached": False}


# Root for convenience
@app.get("/")
async def root():
    return JSONResponse({"app": "GammaPulse Clone", "docs": "/docs"})
