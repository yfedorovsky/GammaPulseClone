"""FastAPI app exposing the same routes the live GammaPulse frontend calls.

Run:
  uvicorn server.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import json

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .cache import cache
from .config import get_settings
from .db import db
from .flow_alerts import init_alert_db, get_alerts as get_flow_alerts, run_flow_scanner, get_sweep_alerts
from .option_flow_daily import init_flow_daily_db, get_flow_daily, get_golden_flow, is_golden_flow, GOLDEN_FLOW_RULES, get_tail_flow, is_tail_flow, TAIL_FLOW_RULES
from .signal_outcomes import init_outcomes_db, get_hit_rate
from .discipline import init_discipline_db, get_ticker_stats, compute_kelly_size, get_circuit_breaker, log_trade
from .signals import init_signals_db, init_ab_db, init_setup_forming_db, get_signals, get_signal_stats, run_signal_engine
from .paper_trading import init_paper_db
from .scalp_alerts import run_scalp_scanner
from .trade_tracker import init_tracker_db, get_all_trades, run_position_monitor
from .breadth import get_breadth_context, get_nymo, get_namo, init_breadth_db
from .industry import compute_industry_scores, enrich_ticker_with_industry
from .rts import compute_rts_universe, rank_tickers
from .gex import compute_exp_data, build_signal
from .snapshots import init_db, series as snapshot_series
from .stream import streamer
from .tickers import all_tickers
from .tradier import TradierClient
from .worker import run_worker
from .market_calendar import is_market_holiday

MACRO_KEY = "MACRO (ALL 200D)"

_stop = asyncio.Event()
_worker_task: asyncio.Task | None = None


_flow_task: asyncio.Task | None = None
_monitor_task: asyncio.Task | None = None
_signal_task: asyncio.Task | None = None
_scalp_task: asyncio.Task | None = None
_discord_task: asyncio.Task | None = None
_sweep_task: asyncio.Task | None = None
_priority_task: asyncio.Task | None = None
_net_flow_task: asyncio.Task | None = None
_net_flow_alert_task: asyncio.Task | None = None
_net_flow_fast_task: asyncio.Task | None = None
_zero_dte_task: asyncio.Task | None = None
_king_mig_task: asyncio.Task | None = None
_king_brk_task: asyncio.Task | None = None
_floor_mig_task: asyncio.Task | None = None
_structural_turn_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_alert_db()
    init_flow_daily_db()
    init_outcomes_db()
    init_tracker_db()
    init_signals_db()
    init_ab_db()
    init_setup_forming_db()
    from .net_flow_signals import init_net_flow_alerts_db
    init_net_flow_alerts_db()
    init_paper_db()
    init_discipline_db()
    init_breadth_db()
    from .runner_tracker import init_runner_db
    init_runner_db()
    from .cell_history import init_cell_history_db
    init_cell_history_db()
    from .oi_delta import init_oi_delta_db
    init_oi_delta_db()
    await db.start()  # Single-writer queue for SQLite (prevents SQLITE_BUSY)
    await streamer.ensure_running()
    # Compute quarterly basket on startup (PIT sector selection)
    try:
        from .basket import get_active_basket
        basket = await get_active_basket()
        print(f"[STARTUP] Active basket: {basket.get('sectors')} ({len(basket.get('tickers', set()))} tickers)")
    except Exception as e:
        print(f"[STARTUP] Basket computation failed: {e} — using static fallback")
    # Warm up the heatmap cache for index tickers BEFORE accepting heavy
    # /api/chains requests. Without this, a cold-start HEATMAPS visit
    # blocked for 30-40s on SPX (±200 strike radius + ThetaData greeks).
    # Fires as a background task so server starts serving immediately;
    # completes in ~30s alongside the worker's first cycle.
    from .worker import warmup_indexes
    asyncio.create_task(warmup_indexes())
    global _worker_task, _flow_task, _monitor_task, _signal_task, _scalp_task, _discord_task, _sweep_task, _priority_task
    _worker_task = asyncio.create_task(run_worker(_stop))
    _flow_task = asyncio.create_task(run_flow_scanner(_stop))
    _monitor_task = asyncio.create_task(run_position_monitor(_stop))
    _signal_task = asyncio.create_task(run_signal_engine(_stop))
    _scalp_task = asyncio.create_task(run_scalp_scanner(_stop))
    # Priority refresh: SPX every 5s for intraday heatmap / KING tracking.
    # Feature-flagged inside priority_refresh.py (PRIORITY_REFRESH_ENABLED).
    # If the flag is False, the task returns immediately (no-op).
    from .priority_refresh import run_priority_refresh
    _priority_task = asyncio.create_task(run_priority_refresh(_stop))
    # Net-flow rotation loop: price-backfill + session-open reset for
    # the per-ticker NCP/NPP aggregator. Trades are folded in via
    # LiveFlowAggregator.add_trade (sync hot path); this loop handles
    # async housekeeping that can't run in the hot path.
    global _net_flow_task, _net_flow_alert_task
    from .net_flow import run_net_flow_rotation_loop, get_net_flow_aggregator
    _net_flow_task = asyncio.create_task(
        run_net_flow_rotation_loop(get_net_flow_aggregator(), _stop)
    )
    # Net-flow alert loop: periodically scans regime transitions across
    # all tracked tickers and fires Telegram alerts on qualifying
    # FLOW_LEADS_UP / FLOW_LEADS_DOWN / DOUBLE_STALL / DIVERGENCE events.
    # Dedupe + 15-min cooldown prevents spam during regime flicker.
    from .net_flow_signals import run_net_flow_alert_loop
    _net_flow_alert_task = asyncio.create_task(run_net_flow_alert_loop(_stop))
    # Fast-tick net-flow aggregator (10s bars for SPY/SPX/QQQ/IWM) —
    # powers the 0DTE confluence engine with sub-minute freshness.
    global _net_flow_fast_task, _zero_dte_task
    from .net_flow_fast import run_fast_net_flow_loop
    _net_flow_fast_task = asyncio.create_task(run_fast_net_flow_loop(_stop))
    # 0DTE confluence alert engine — combines GEX + NetFlow + Sweep +
    # Golden signals into A+/A/B+/B/C-graded trade tickets with strike
    # selection + exit planning + Telegram push.
    from .zero_dte_loop import run_zero_dte_loop
    _zero_dte_task = asyncio.create_task(run_zero_dte_loop(_stop))
    # King migration live detector — fires Telegram when +King jumps
    # (structural runner signal, added 2026-04-24 after missing Mir's
    # ARM 250C migration at 9:35 AM when detector was backfill-only).
    global _king_mig_task, _king_brk_task
    from .king_migration import run_king_migration_live_loop
    _king_mig_task = asyncio.create_task(run_king_migration_live_loop(_stop))
    # King breakout live detector — fires Telegram when spot crosses a
    # stable +King from below (the OTHER half of the runner trigger,
    # missed DELL 2026-05-06 9:40 ET cross of $220 because detector was
    # backfill-only).
    from .king_breakout import run_king_breakout_live_loop
    _king_brk_task = asyncio.create_task(run_king_breakout_live_loop(_stop))
    # Floor migration + Structural Turn detectors (Apr 28 — shadow mode).
    # Catches the QQQ 13:30 floor-reclaim pattern + 5-gate structural-turn
    # synthesis that today's audit identified as the trade of the day.
    global _floor_mig_task, _structural_turn_task
    from .floor_migration import run_floor_migration_live_loop
    _floor_mig_task = asyncio.create_task(run_floor_migration_live_loop(_stop))
    from .structural_turn import run_structural_turn_live_loop
    _structural_turn_task = asyncio.create_task(run_structural_turn_live_loop(_stop))
    # GLW earnings primer (Apr 27 - Apr 29 window). Hourly scan during
    # market hours of GLW/COHR/LITE/RMBS for SOE/NET FLOW/large flow_alerts.
    # Self-disables after Wed 4/29 close. No-op outside the active dates.
    global _glw_primer_task
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.glw_earnings_primer import run_glw_primer_loop
        _glw_primer_task = asyncio.create_task(run_glw_primer_loop(_stop))
    except Exception as e:
        _glw_primer_task = None
        print(f"[STARTUP] glw_primer task NOT started: {e}")
    # Discord listener: opt-in via DISCORD_ENABLED=true in .env.
    # Bug #10 fix (May 13 2026): the embedded task path silently degraded for
    # weeks (mir_signal_cache last write 2026-05-12 13:09 despite live Mir
    # posts). Canonical path is now a standalone process launched by
    # clean_restart.ps1: `python -m server.discord_listener`. Set
    # DISCORD_EMBEDDED=true to fall back to in-process mode for debugging.
    _discord_task = None
    s = get_settings()
    if s.discord_enabled and s.discord_token and getattr(s, "discord_embedded", False):
        from .discord_listener import run_discord_listener
        _discord_task = asyncio.create_task(run_discord_listener(_stop))
        print("[STARTUP] Discord listener running EMBEDDED (DISCORD_EMBEDDED=true)")
    elif s.discord_enabled and s.discord_token:
        print("[STARTUP] Discord listener skipped — run standalone via `python -m server.discord_listener`")
    # ThetaData ISO sweep detector (consumes OPRA condition=95 prints via WebSocket)
    _sweep_task = None
    if s.thetadata_sweep_enabled:
        from .sweep_detector import run_sweep_detector
        _sweep_task = asyncio.create_task(run_sweep_detector(_stop))
        print("[STARTUP] Theta sweep detector enabled")

    # GEX Magnet Entry — 3-condition convergence alert (shipped 5/20)
    # Synthesis layer for SPY/QQQ/IWM 0DTE setups: magnet within reach +
    # higher-low confirmed + institutional call cluster firing.
    _gex_magnet_task = None
    try:
        from .gex_magnet_entry import run_magnet_entry_loop
        _gex_magnet_task = asyncio.create_task(run_magnet_entry_loop(_stop))
        print("[STARTUP] GEX magnet entry loop enabled")
    except Exception as e:
        print(f"[STARTUP] GEX magnet entry loop NOT started: {e}")

    # Snapshot persist watchdog — alarms via Telegram if snapshots table
    # goes >10 min without a write during RTH (the 5/14-5/19 4-day silent
    # bug must never repeat undetected).
    _snap_watchdog_task = None
    try:
        from .snapshot_watchdog import run_snapshot_watchdog
        _snap_watchdog_task = asyncio.create_task(run_snapshot_watchdog(_stop))
        print("[STARTUP] Snapshot persist watchdog enabled")
    except Exception as e:
        print(f"[STARTUP] Snapshot watchdog NOT started: {e}")

    # Alert outcomes performance database backfill (5/20 night, Perplexity
    # recommendation #1). Every 30 min walks pending alerts and computes
    # 1h/EOD/next-day outcomes + spot MFE/MAE + target/stop hits. Without
    # this, every filter threshold is unfounded.
    _outcomes_task = None
    try:
        from .alert_outcomes import run_outcome_backfill_loop
        _outcomes_task = asyncio.create_task(run_outcome_backfill_loop(_stop))
        print("[STARTUP] Alert outcomes backfill loop enabled")
    except Exception as e:
        print(f"[STARTUP] Alert outcomes backfill NOT started: {e}")
    try:
        yield
    finally:
        _stop.set()
        await streamer.stop()
        await db.stop()  # Drain write queue before shutdown
        all_tasks = [_worker_task, _flow_task, _monitor_task, _signal_task, _scalp_task, _discord_task, _sweep_task, _priority_task, _net_flow_task, _net_flow_alert_task, _net_flow_fast_task, _zero_dte_task, _king_mig_task, _king_brk_task, _floor_mig_task, _structural_turn_task, _gex_magnet_task, _snap_watchdog_task, _outcomes_task]
        for task in all_tasks:
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
            "_greeks_source": state.get("_greeks_source"),
            "_ivp": state.get("_ivp"),
            "_ivhv_ratio": state.get("_ivhv_ratio"),
            "_rts": state.get("_rts"),
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
            # Mir momentum signal (computed in worker for approved sector tickers)
            "_mir_score": (state.get("_mir_signal") or {}).get("mir_score"),
            "_mir_conviction": (state.get("_mir_signal") or {}).get("conviction"),
            # Trend day detection (gap-and-go vs pullback mode)
            "_trend_mode": (state.get("_trend_day") or {}).get("trend_mode"),
            "_gap_pct": (state.get("_trend_day") or {}).get("gap_pct"),
            # IBD industry group rank (Apr 19 — rotation overlay)
            "_ibd_group_rank": (state.get("_ibd_group") or {}).get("rank"),
            "_ibd_group_name": (state.get("_ibd_group") or {}).get("name"),
            "_ibd_group_ytd": (state.get("_ibd_group") or {}).get("ytd_pct"),
            "_ibd_group_leader_rank": (state.get("_ibd_group") or {}).get("leader_rank_in_group"),
            # IBD Sector Leader flag (Apr 20 — O'Neil's top-16 curated)
            "_ibd_sector_leader": state.get("_ibd_sector_leader", False),
            # exp_data excluded from scanner list (too heavy for 300+ tickers)
            # Use /api/chains for full exp_data per ticker
            "exps": state.get("exps"),
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
    rows = await asyncio.to_thread(
        get_flow_alerts, since_ts=since, limit=limit, ticker=ticker or None,
    )
    return {"alerts": rows, "count": len(rows)}


@app.get("/api/sweeps")
async def sweeps(
    since: int = 0, limit: int = 100, ticker: str = "", min_notional: float = 0
):
    """ISO-tagged sweep alerts only (is_sweep=1 from ThetaData stream).

    Sweeps are OPRA condition code 95/126/128 — orders routed across multiple
    exchanges simultaneously, indicating urgency + conviction. Highest-hit-rate
    flow category per UW-style analysis.

    NOTE: get_sweep_alerts is a synchronous SQLite call. Running it inline in
    an async endpoint blocks the FastAPI event loop, which (under heavy write
    contention from the live worker writing flow_alerts) cascades into 30-60s
    response times and frontend "Loading..." deadlocks. Offload to a thread.
    """
    rows = await asyncio.to_thread(
        get_sweep_alerts,
        since_ts=since, limit=limit, ticker=ticker or None, min_notional=min_notional,
    )
    return {"sweeps": rows, "count": len(rows)}


@app.get("/api/stats/hit-rate")
async def stats_hit_rate(
    source_type: str = "",
    ticker: str = "",
    direction: str = "",
    min_notional: float = 0,
    grade: str = "",
    is_sweep: int = -1,
    min_sweep_venues: int = 0,
    lookback_days: int = 90,
):
    """Cohort-filtered forward-return hit rate for alerts/signals.

    Returns {'cohort_size', 'horizons': {'1d', '3d', '1w', '2w', '1mo'}}.
    Each horizon dict has {'n', 'hits', 'rate', 'avg_return'} — NULL-safe
    when the forward date hasn't arrived yet (rate=None, n=0).

    Example:
      /api/stats/hit-rate?source_type=sweep&direction=BUY&min_sweep_venues=3
        → "last 216 BUY sweeps with ≥3 venues: 1d 51% · 3d 95%"
    """
    return get_hit_rate(
        source_type=source_type or None,
        ticker=ticker or None,
        direction=direction or None,
        min_notional=min_notional,
        grade=grade or None,
        is_sweep=is_sweep if is_sweep in (0, 1) else None,
        min_sweep_venues=min_sweep_venues,
        lookback_days=lookback_days,
    )


@app.get("/api/flow/tail")
async def flow_tail(
    since_date: str = "", ticker: str = "", limit: int = 200,
):
    """TAIL FLOW alerts — cheap-far-OTM-longer-dated insider pattern.

    Complements GOLDEN (urgent ATM 1-2 DTE). TAIL catches lotto-style
    puts and calls 5-20% OTM, 3-45 trading days out, cheap premium
    (< $2 avg fill), with 65%+ directional conviction.

    Signature example (SPY 620P 5/8 — 21 DTE, 13% OTM, $0.43 avg,
    $838K notional, 82% bought): fund managers hedging a month out
    or insiders positioning for a ~monthly window event.

    Clusters of 2+ per ticker per day = strong signal.
    """
    rows = await asyncio.to_thread(
        get_tail_flow, since_date=since_date or None, ticker=ticker or None, limit=limit,
    )
    return {"tail": rows, "count": len(rows), "rules": TAIL_FLOW_RULES}


@app.get("/api/flow/golden")
async def flow_golden(
    since_date: str = "", ticker: str = "", limit: int = 200,
):
    """GOLDEN FLOW alerts — composite unusual-flow pattern matching the
    SPY 647P 03/24 insider-flow profile shown in the UW screenshot.

    5 rules (all must match):
      1. notional         >= $500K
      2. bought at ask    >= 70%
      3. volume / OI      >= 3x (opening position)
      4. |strike-spot|/spot <= 2.5% (near-ATM / just-OTM)
      5. DTE              <= 2 (short-dated = high leverage + urgency)

    The 3/23 example: $1.49M prem, 76% bought, V/OI 10.2x, 1% OTM, 1DTE.
    Fires 15 min before market-moving headlines.
    """
    rows = await asyncio.to_thread(
        get_golden_flow, since_date=since_date or None, ticker=ticker or None, limit=limit,
    )
    return {
        "golden": rows, "count": len(rows),
        "rules": GOLDEN_FLOW_RULES,
    }


@app.get("/api/flow/daily")
async def flow_daily(
    since_date: str = "", ticker: str = "",
    min_notional: float = 0, min_oi: int = 0,
    side: str = "ALL", limit: int = 500,
):
    """Per-contract DAILY option flow — UW-style aggregated view.

    Returns all aggressive flow (not just ISO sweeps) aggregated by
    (date, ticker, strike, expiration, option_type). Includes buy/sell
    split, sweep share, block share, and the biggest single print.

    Filters:
      since_date: 'YYYY-MM-DD' — return rows on or after this date
      ticker: exact ticker match
      min_notional: minimum total_notional in dollars
      min_oi: minimum open interest
      side: 'ALL' | 'BUY' | 'SELL' | 'NEUTRAL' (dominant-side filter)
    """
    # Sync SQLite call → offload to threadpool so it doesn't block the event
    # loop (same fix as /api/sweeps — under WAL write contention this can
    # take 30-60s otherwise, with cascading "stuck on Loading" frontend bug).
    rows = await asyncio.to_thread(
        get_flow_daily,
        since_date=since_date or None,
        ticker=ticker or None,
        min_notional=min_notional,
        min_oi=min_oi,
        side=side,
        limit=limit,
    )
    return {"flow": rows, "count": len(rows)}


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


@app.get("/api/breadth")
async def breadth_data():
    """NYMO/NAMO McClellan Oscillator breadth context."""
    return await get_breadth_context()


@app.get("/api/vix-regime")
async def vix_regime():
    """Today's VIX intraday regime classification.

    Backtest-validated:
      VIX_BULL_COMPRESS (VIX<20, -3%+ intraday) = 80% SPY WR
      VIX_ELEVATED_COMP (VIX 20-25, declining)   = 87% SPY WR
      VIX_LOW_RISING / VIX_SPIKE = avoid longs
    """
    from .breadth import get_vix_intraday_regime
    return await get_vix_intraday_regime()


@app.get("/api/oil-regime")
async def oil_regime():
    """Today's oil regime with SPY+XLE co-movement disambiguation.

    4-LLM consensus architecture (Apr 16 2026):
      OIL_SPIKE_RISKOFF (USO +4%+ AND SPY red AND XLE bid) = telegram alert
      OIL_UP_MILD (USO +2-4%) = soft caution, runner score -1
      OIL_CRASH_RELIEF (USO -4%+ AND SPY green) = deflationary tailwind, +1
      OIL_DEMAND_RELIEF (USO +4%+ AND SPY green AND XLE green) = Liberation Day
        pattern, no action (would be false-positive risk-off)
    """
    from .breadth import get_oil_intraday_regime
    return await get_oil_intraday_regime()


@app.get("/api/rts")
async def rts_rankings(direction: str = "BULL", limit: int = 50):
    """Relative Trend Strength rankings for vehicle selection."""
    from .tickers import all_tickers
    tradier = TradierClient()
    try:
        tickers = all_tickers()[:limit]
        results = await compute_rts_universe(tradier, tickers)
        ranked = rank_tickers(results, direction)
        return {"direction": direction, "count": len(ranked), "tickers": ranked}
    finally:
        await tradier.close()


@app.get("/api/industry")
async def industry_rankings():
    """Industry leadership scores with member rankings."""
    snapshot = await cache.snapshot()
    scores = compute_industry_scores(snapshot)
    # Sort by score descending
    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return {"count": len(ranked), "industries": ranked}


# ── Paper Trading Portfolio ──────────────────────────────────────────

@app.get("/api/portfolio")
async def portfolio():
    """Paper trading account summary + open positions."""
    from .paper_trading import get_account, get_positions
    return {
        "account": get_account(),
        "open": get_positions("OPEN"),
        "stats": None,  # computed separately
    }


@app.get("/api/portfolio/history")
async def portfolio_history():
    """Closed trades + equity curve + stats."""
    from .paper_trading import get_positions, get_equity_history, get_portfolio_stats
    return {
        "closed": get_positions("CLOSED", limit=200),
        "equity": get_equity_history(),
        "stats": get_portfolio_stats(),
    }


class PortfolioOpenReq(BaseModel):
    signal_id: int
    contracts: int | None = None


@app.post("/api/portfolio/open")
async def portfolio_open(req: PortfolioOpenReq):
    """Open a paper position from an SOE signal."""
    from .paper_trading import open_position
    return open_position(req.signal_id, req.contracts)


class PortfolioCloseReq(BaseModel):
    position_id: int
    reason: str = "MANUAL"


@app.post("/api/portfolio/close")
async def portfolio_close(req: PortfolioCloseReq):
    """Close a paper position."""
    from .paper_trading import close_position
    return close_position(req.position_id, reason=req.reason)


@app.post("/api/portfolio/reset")
async def portfolio_reset():
    """Reset paper account to starting balance."""
    from .paper_trading import reset_account
    return reset_account()


@app.get("/api/ab/results")
async def ab_results():
    """A/B test results: Mir-only (Book B) vs Mir+GEX (Book A) comparison."""
    import sqlite3
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row

    total = c.execute("SELECT COUNT(*) as n FROM ab_decisions").fetchone()["n"]
    if total == 0:
        c.close()
        return {"total": 0, "summary": {}, "gex_contribution": {}, "by_conviction": {}, "daily": []}

    def _book_stats(prefix):
        would = c.execute(f"SELECT COUNT(*) as n FROM ab_decisions WHERE {prefix}_would_trade = 1").fetchone()["n"]
        wins = c.execute(f"SELECT COUNT(*) as n FROM ab_decisions WHERE {prefix}_outcome = 'WIN'").fetchone()["n"]
        losses = c.execute(f"SELECT COUNT(*) as n FROM ab_decisions WHERE {prefix}_outcome = 'LOSS'").fetchone()["n"]
        pending = c.execute(f"SELECT COUNT(*) as n FROM ab_decisions WHERE {prefix}_outcome = 'PENDING' AND {prefix}_would_trade = 1").fetchone()["n"]
        resolved = wins + losses
        avg_pnl = c.execute(f"SELECT AVG({prefix}_pnl_pct) as v FROM ab_decisions WHERE {prefix}_pnl_pct IS NOT NULL").fetchone()["v"]
        return {
            "would_trade": would, "wins": wins, "losses": losses, "pending": pending,
            "win_rate": round(wins / resolved * 100, 1) if resolved else 0,
            "avg_pnl": round(avg_pnl or 0, 2),
            "resolved": resolved,
        }

    summary = {"book_a": _book_stats("a"), "book_b": _book_stats("b"), "total_decisions": total}

    # GEX contribution breakdown
    gex_blocked = c.execute("SELECT COUNT(*) as n FROM ab_decisions WHERE gex_entry_blocked = 1").fetchone()["n"]
    gex_blocked_wins = c.execute("SELECT COUNT(*) as n FROM ab_decisions WHERE gex_entry_blocked = 1 AND b_outcome = 'WIN'").fetchone()["n"]
    gex_blocked_losses = c.execute("SELECT COUNT(*) as n FROM ab_decisions WHERE gex_entry_blocked = 1 AND b_outcome = 'LOSS'").fetchone()["n"]

    avg_a_rr = c.execute("SELECT AVG(a_rr_ratio) as v FROM ab_decisions WHERE a_would_trade = 1 AND a_rr_ratio IS NOT NULL").fetchone()["v"]
    avg_b_rr = c.execute("SELECT AVG(b_rr_ratio) as v FROM ab_decisions WHERE b_would_trade = 1 AND b_rr_ratio IS NOT NULL").fetchone()["v"]

    gex_contribution = {
        "entry_filter": {
            "signals_blocked": gex_blocked,
            "would_have_won": gex_blocked_wins,
            "would_have_lost": gex_blocked_losses,
        },
        "targeting": {
            "avg_rr_with_gex": round(avg_a_rr or 0, 2),
            "avg_rr_without_gex": round(avg_b_rr or 0, 2),
        },
    }

    # By conviction
    by_conviction = {}
    for conv in ("HIGH", "MEDIUM", "LOW"):
        row = c.execute(
            """SELECT
                COUNT(*) as n,
                SUM(CASE WHEN a_outcome = 'WIN' THEN 1 ELSE 0 END) as a_wins,
                SUM(CASE WHEN a_outcome IN ('WIN','LOSS') THEN 1 ELSE 0 END) as a_resolved,
                SUM(CASE WHEN b_outcome = 'WIN' THEN 1 ELSE 0 END) as b_wins,
                SUM(CASE WHEN b_outcome IN ('WIN','LOSS') THEN 1 ELSE 0 END) as b_resolved
            FROM ab_decisions WHERE mir_conviction = ?""", (conv,)
        ).fetchone()
        by_conviction[conv] = {
            "count": row["n"],
            "a_wr": round(row["a_wins"] / row["a_resolved"] * 100, 1) if row["a_resolved"] else 0,
            "b_wr": round(row["b_wins"] / row["b_resolved"] * 100, 1) if row["b_resolved"] else 0,
        }
    # NONE (no Mir signal)
    row = c.execute(
        """SELECT COUNT(*) as n,
            SUM(CASE WHEN a_outcome = 'WIN' THEN 1 ELSE 0 END) as a_wins,
            SUM(CASE WHEN a_outcome IN ('WIN','LOSS') THEN 1 ELSE 0 END) as a_resolved
        FROM ab_decisions WHERE mir_conviction IS NULL"""
    ).fetchone()
    by_conviction["NONE"] = {
        "count": row["n"],
        "a_wr": round(row["a_wins"] / row["a_resolved"] * 100, 1) if row["a_resolved"] else 0,
        "b_wr": 0,
    }

    # Daily time series
    daily = []
    rows = c.execute(
        """SELECT date(ts, 'unixepoch') as dt,
            SUM(CASE WHEN a_outcome = 'WIN' THEN 1 ELSE 0 END) as a_wins,
            SUM(CASE WHEN a_outcome IN ('WIN','LOSS') THEN 1 ELSE 0 END) as a_resolved,
            SUM(CASE WHEN b_outcome = 'WIN' THEN 1 ELSE 0 END) as b_wins,
            SUM(CASE WHEN b_outcome IN ('WIN','LOSS') THEN 1 ELSE 0 END) as b_resolved,
            COUNT(*) as decisions
        FROM ab_decisions GROUP BY dt ORDER BY dt"""
    ).fetchall()
    for r in rows:
        daily.append({
            "date": r["dt"],
            "a_wr": round(r["a_wins"] / r["a_resolved"] * 100, 1) if r["a_resolved"] else 0,
            "b_wr": round(r["b_wins"] / r["b_resolved"] * 100, 1) if r["b_resolved"] else 0,
            "decisions": r["decisions"],
        })

    c.close()
    return {"total": total, "summary": summary, "gex_contribution": gex_contribution,
            "by_conviction": by_conviction, "daily": daily}


@app.get("/api/ibd-groups")
async def ibd_groups_info():
    """IBD industry group rotation layer — top groups + members + weekend date.
    Static table in server/ibd_groups.py; refreshed manually each weekend."""
    from .ibd_groups import summary
    return summary()


@app.get("/api/ibd-sector-leaders")
async def ibd_sector_leaders_info():
    """IBD Sector Leaders — O'Neil's curated ≤16 CAN-SLIM pass list.
    Also exposes list cardinality as market regime gauge
    (16=STRONG_BULL / <7=CORRECTION). Refreshed weekly from the paper."""
    from .ibd_sector_leaders import summary
    return summary()


@app.get("/api/basket")
async def basket_info():
    """Current quarterly basket — which sectors and tickers are active."""
    from .basket import get_basket_info
    info = get_basket_info()
    if not info:
        return {"status": "not_computed", "sectors": [], "tickers": []}
    return {
        "status": "active",
        "quarter": info.get("quarter"),
        "sectors": info.get("sectors", []),
        "tickers": sorted(info.get("tickers", set())),
        "scores": info.get("scores", []),
        "computed_at": info.get("computed_at"),
        "valid_until": info.get("valid_until"),
    }


@app.get("/api/ab/block-reasons")
async def ab_block_reasons():
    """Block reason distribution — why signals were missed/blocked."""
    import sqlite3
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row

    # Book A block reasons (Mir+GEX pathway)
    a_blocks = c.execute("""
        SELECT a_blocked_by as reason, COUNT(*) as count,
            SUM(CASE WHEN b_outcome = 'WIN' THEN 1 ELSE 0 END) as would_have_won,
            SUM(CASE WHEN b_outcome = 'LOSS' THEN 1 ELSE 0 END) as would_have_lost
        FROM ab_decisions
        WHERE a_blocked_by IS NOT NULL
        GROUP BY a_blocked_by ORDER BY count DESC
    """).fetchall()

    # Book B block reasons (Mir-only pathway)
    b_blocks = c.execute("""
        SELECT b_blocked_by as reason, COUNT(*) as count
        FROM ab_decisions
        WHERE b_blocked_by IS NOT NULL
        GROUP BY b_blocked_by ORDER BY count DESC
    """).fetchall()

    # Mir-originated vs standard pathway counts
    pathway = c.execute("""
        SELECT
            SUM(CASE WHEN mir_signal_type = 'MIR_MOMENTUM' THEN 1 ELSE 0 END) as mir_originated,
            SUM(CASE WHEN mir_signal_type IS NULL OR mir_signal_type != 'MIR_MOMENTUM' THEN 1 ELSE 0 END) as gex_originated,
            COUNT(*) as total
        FROM ab_decisions
    """).fetchone()

    # Recent blocks (last 50) for debugging
    recent = c.execute("""
        SELECT datetime(ts, 'unixepoch') as time, ticker, direction,
            a_blocked_by, b_blocked_by, mir_conviction, mir_signal_type,
            a_score, a_grade, spot
        FROM ab_decisions
        WHERE a_blocked_by IS NOT NULL
        ORDER BY ts DESC LIMIT 50
    """).fetchall()

    c.close()
    return {
        "book_a_blocks": [dict(r) for r in a_blocks],
        "book_b_blocks": [dict(r) for r in b_blocks],
        "pathway": dict(pathway) if pathway else {},
        "recent_blocks": [dict(r) for r in recent],
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


@app.get("/api/earnings/dates/{ticker}")
async def earnings_dates(ticker: str, days: int = 90):
    """Return earnings dates for a ticker over the past N days (from Finnhub)."""
    import datetime
    s = get_settings()
    if not s.finnhub_api_key:
        return {"dates": []}
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": start.isoformat(),
                    "to": today.isoformat(),
                    "symbol": ticker.upper(),
                    "token": s.finnhub_api_key,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                dates = [ec["date"] for ec in data.get("earningsCalendar", [])
                         if ec.get("symbol", "").upper() == ticker.upper()]
                return {"dates": sorted(set(dates))}
    except Exception as e:
        print(f"[EARNINGS] dates fetch failed for {ticker}: {e}")
    return {"dates": []}


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
            result = await tradier.history(t, interval=interval, start=start.isoformat(), end=end.isoformat())
        else:
            # Multi-day intraday: fetch each day separately
            # Tradier timesales needs full datetime format and only returns 1 day at a time
            import asyncio as aio
            all_bars = []
            for d in range(days, -1, -1):
                day = end - datetime.timedelta(days=d)
                if day.weekday() >= 5 or is_market_holiday(day):
                    continue
                start_dt = f"{day.isoformat()} 04:00"
                end_dt = f"{day.isoformat()} 20:00"
                day_bars = await tradier.history(t, interval=interval, start=start_dt, end=end_dt)
                all_bars.extend(day_bars)
            result = all_bars
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


@app.get("/api/swing-scanner")
async def swing_scanner_route(mode: str = "standard"):
    """Swing watchlist scanner — separate from GEX/SOE signals.

    Modes: 'standard' (7-14 DTE, 1-5 day holds) or 'wifey' (14-30 DTE, longer holds).
    """
    from .swing_scanner import compute_swing_watchlist
    from .runner_tracker import get_runner_for_ticker
    results, meta = await compute_swing_watchlist(mode=mode)
    # Annotate with runner tracker state
    for r in results:
        runner = get_runner_for_ticker(r["ticker"])
        if runner:
            r["runner_state"] = runner.get("state")
            r["runner_score"] = runner.get("runner_score")
            r["runner_day"] = runner.get("consecutive_2pct_days", 0)
            r["runner_total_gain"] = runner.get("total_gain_pct")
        else:
            r["runner_state"] = None
    return {
        "tickers": results,
        **meta,
    }


@app.get("/api/runners")
async def runners_route(status: str = "active"):
    """Runner tracker — multi-day explosive breakout tracking.

    status: 'active' (in-progress runners) or 'history' (completed).
    """
    from .runner_tracker import get_active_runners, get_recent_runners
    if status == "history":
        return {"runners": get_recent_runners(limit=50)}
    return {"runners": get_active_runners()}


@app.get("/api/swing-alerts/stats")
async def swing_alerts_stats_route():
    """Diagnostic for new-watchlist-entry alerts. Shows which tickers have
    fired today + market-hours gate status."""
    from .swing_alerts import stats
    return stats()


@app.post("/api/swing-alerts/reset")
async def swing_alerts_reset_route():
    """Clear today's fired tickers so alerts can re-trigger."""
    from .swing_alerts import reset_today
    count = reset_today()
    return {"ok": True, "cleared": count}


@app.get("/api/price-watch/stats")
async def price_watch_stats_route():
    """Active price watches for manual-trade Telegram alerts (e.g. Mir setups).

    Each watch monitors a specific contract's bid and fires tiered Telegram
    alerts when the bid crosses into buy thresholds. Lets you walk away from
    the screen without missing a Mir discipline-price entry.

    Edit server/price_watch.py:_WATCHES to add more watches.
    """
    from .price_watch import stats
    return stats()


@app.post("/api/price-watch/reset/{watch_id}")
async def price_watch_reset_route(watch_id: str):
    """Clear fired-tier state for a watch so alerts can re-trigger today.
    Use when you want to test or restart monitoring for a given watch.
    """
    from .price_watch import reset_watch
    ok = reset_watch(watch_id)
    return {"ok": ok, "watch_id": watch_id}


@app.post("/api/price-watch/reset-all")
async def price_watch_reset_all_route():
    """Clear fired-tier state for ALL watches today. Safer re-arm after
    false-alert storms (stale-cache fire on restart)."""
    from .price_watch import reset_all_watches_today
    n = reset_all_watches_today()
    return {"ok": True, "cleared": n}


@app.get("/api/oi-delta/stats")
async def oi_delta_stats_route():
    """Diagnostic: how many OI snapshots have accumulated?

    Priority 3 from Skylit synthesis — daily OI persistence for ΔOI
    flow-direction inference. Burn-in: 1 trading day before ΔOI is useful.
    """
    from .oi_delta import stats
    return stats()


@app.get("/api/proto-runners")
async def proto_runners_route(limit: int = 50):
    """PROTO_RUNNER observation log (v3 — AMD case study, Apr 16 2026).

    Stealth-grind pre-state detection: 2+ consecutive higher closes at top
    of range on below-average volume. Observation mode only — not wired to
    alerts, paper trades, or runner scoring. Purpose: collect forward-sample
    evidence before deciding whether to promote to a full runner state.

    Outcome values: PENDING | PROMOTED | FADED | EXPIRED
    """
    from .runner_tracker import get_proto_runners
    rows = get_proto_runners(limit=limit)
    # Summary stats
    pending = sum(1 for r in rows if r.get("outcome") == "PENDING")
    promoted = sum(1 for r in rows if r.get("outcome") == "PROMOTED")
    faded = sum(1 for r in rows if r.get("outcome") == "FADED")
    total_resolved = promoted + faded
    hit_rate = round(promoted / total_resolved * 100, 1) if total_resolved > 0 else None
    return {
        "rows": rows,
        "summary": {
            "total": len(rows),
            "pending": pending,
            "promoted": promoted,
            "faded": faded,
            "hit_rate_pct": hit_rate,
        },
    }


def _debug_atm_contracts(raw: dict, spot: float) -> dict:
    """Show ATM call+put for each expiration with quality gate results."""
    import datetime
    today = datetime.date.today()
    result = {}
    for exp, contracts in raw.items():
        dte = (datetime.date.fromisoformat(exp) - today).days
        calls = [c for c in contracts if (c.get("option_type") or "").lower() == "call" and c.get("strike", 0) >= spot]
        puts = [c for c in contracts if (c.get("option_type") or "").lower() == "put" and c.get("strike", 0) <= spot]
        atm_call = min(calls, key=lambda c: abs(c["strike"] - spot)) if calls else None
        atm_put = min(puts, key=lambda c: abs(c["strike"] - spot)) if puts else None
        for label, c in [("call", atm_call), ("put", atm_put)]:
            if c:
                g = c.get("greeks") or {}
                bid, ask = c.get("bid", 0) or 0, c.get("ask", 0) or 0
                mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
                spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999
                delta = abs(g.get("delta", 0) or 0)
                oi = c.get("open_interest", 0) or 0
                # Quality gate check
                gates = []
                if spread_pct > 10: gates.append(f"spread={spread_pct:.0f}%>10%")
                if oi < 500: gates.append(f"OI={oi}<500")
                if delta < 0.25 or delta > 0.60: gates.append(f"delta={delta:.2f}")
                result[f"{exp} DTE={dte} {label}"] = {
                    "strike": c["strike"], "bid": bid, "ask": ask, "OI": oi,
                    "delta": round(delta, 3), "spread_pct": round(spread_pct, 1),
                    "PASS": len(gates) == 0, "fails": gates or "ALL_PASS",
                }
    return result


@app.get("/api/debug/raw-contracts/{ticker}")
async def debug_raw_contracts(ticker: str):
    """DEBUG: Check if _raw_contracts is in cache for a ticker."""
    state = await cache.get(ticker.upper())
    if not state:
        return {"error": f"{ticker} not in cache"}
    raw = state.get("_raw_contracts", {})
    exps = state.get("exps", [])
    return {
        "ticker": ticker.upper(),
        "exps": exps,
        "raw_contracts_keys": list(raw.keys()),
        "raw_contracts_total": sum(len(v) for v in raw.values()),
        "sample_atm": _debug_atm_contracts(raw, state.get("actual_spot") or state.get("_spot") or 0),
    }


# ── Net Flow (NCP / NPP time series) ──────────────────────────────────
#
# Implements the "Price-to-Premium Gap Theory" data layer. See
# server/net_flow.py for the aggregator + sign convention. Data source is
# the same WebSocket trade stream that powers sweep_detector — no extra
# subscription required.

@app.get("/api/net-flow/{ticker}")
async def net_flow_series(ticker: str, minutes: int = 240):
    """Return the last N minutes of net-flow bars for a ticker.

    Response shape:
      {
        "ticker": "SPY",
        "minutes": 240,
        "bars": [ {t, t_iso, price, ncp, npp, signed_vol, ...}, ... ],
        "latest": { ...last bar... },
        "cum_ncp": session cumulative NCP,
        "cum_npp": session cumulative NPP,
        "cum_net": cum_ncp - cum_npp,
        "cum_since": ISO timestamp of last session-open reset,
        "tracked": whether this ticker is in TRACKED_TICKERS
      }

    Clamp: minutes ∈ [1, 1440]. Past 1440 we have no data (24h window).
    """
    from .net_flow import get_net_flow_aggregator, TRACKED_TICKERS
    from .net_flow_signals import regime_summary
    mins = max(1, min(int(minutes), 1440))
    agg = get_net_flow_aggregator()
    ticker_up = ticker.upper()
    bars = agg.series(ticker_up, minutes=mins)
    snap = agg.snapshot(ticker_up)
    # Compute divergence / stall regime over the returned bars.
    # Stateless — fresh every call, no persistence needed.
    regime = regime_summary(bars)
    return {
        "ticker": ticker_up,
        "minutes": mins,
        "bars": bars,
        "latest": snap["latest"],
        "cum_ncp": snap["cum_ncp"],
        "cum_npp": snap["cum_npp"],
        "cum_net": snap["cum_net"],
        "cum_since": snap["cum_since"],
        "tracked": ticker_up in TRACKED_TICKERS,
        "regime": regime.get("regime"),
        "regime_description": regime.get("description"),
        "regime_gap_direction": regime.get("gap_direction"),
        "regime_confidence": regime.get("confidence"),
        "signals": regime.get("signals", []),
    }


# ── 0DTE Confluence Alert Engine ─────────────────────────────────
#
# Live-graded 0DTE alert feed with full trade tickets. See
# server/zero_dte_loop.py and server/zero_dte_engine.py for details.

@app.get("/api/king-breakouts")
async def king_breakouts_api(
    limit: int = 100,
    ticker: str | None = None,
    qualified_only: bool = False,
):
    """Recent king-breakout events (newest first).

    Breakouts are when spot crosses +King from below with mature gamma
    structure — the gamma-squeeze trigger documented in
    server/king_breakout.py. Sibling to /api/king-migrations.
    """
    from .king_breakout import load_recent
    rows = load_recent(limit=limit, ticker=ticker, qualified_only=qualified_only)
    return {"events": rows, "count": len(rows)}


@app.get("/api/king-migrations")
async def king_migrations_api(
    limit: int = 100,
    ticker: str | None = None,
    qualified_only: bool = False,
):
    """Return recent king-migration events (newest first).

    Qualifying events are the 5-gate-pass signals documented in
    server/king_migration.py — these are the runner roll-up triggers
    identified in the 2026-04-22 ARM audit.
    """
    from .king_migration import load_recent
    rows = load_recent(limit=limit, ticker=ticker, qualified_only=qualified_only)
    return {"events": rows, "count": len(rows)}


@app.get("/api/zero-dte/alerts")
async def zero_dte_alerts(limit: int = 50, ticker: str | None = None):
    """Return the most recent 0DTE alerts (newest first). Reads from
    sqlite so history survives server restarts. ``limit`` caps the number
    of rows; ``ticker`` optionally filters (case-insensitive)."""
    from .zero_dte_loop import load_alerts_from_db, get_cooldown_state
    alerts = load_alerts_from_db(limit=limit, ticker=ticker)
    return {
        "alerts": alerts,
        "count": len(alerts),
        "cooldown": get_cooldown_state().stats(),
    }


@app.get("/api/zero-dte/evaluate/{ticker}")
async def zero_dte_evaluate(ticker: str):
    """On-demand evaluation of a single ticker — returns the CURRENT
    confluence snapshot without firing alerts. Useful for UI debug /
    testing new signals before they're tuned."""
    from .cache import cache
    from .net_flow_fast import get_fast_net_flow_aggregator, snapshot_fast_flow
    from .net_flow import get_net_flow_aggregator
    from .net_flow_signals import regime_summary
    from .zero_dte_engine import evaluate
    from .zero_dte_loop import _recent_sweeps_for_ticker, _recent_goldens_for_ticker

    ticker_up = ticker.upper()
    snap = await cache.snapshot()
    gex_state = snap.get(ticker_up) or {}
    fast_snap = snapshot_fast_flow(get_fast_net_flow_aggregator(), ticker_up)
    main_bars = get_net_flow_aggregator().series(ticker_up, minutes=240)
    reg = regime_summary(main_bars) if main_bars else {}
    sweeps = _recent_sweeps_for_ticker(ticker_up)
    goldens = _recent_goldens_for_ticker(ticker_up)

    ev = evaluate(
        ticker=ticker_up,
        gex_state=gex_state,
        fast_flow_snap=fast_snap,
        regime=reg.get("regime"),
        regime_confidence=reg.get("confidence"),
        recent_sweeps=sweeps,
        recent_goldens=goldens,
    )
    return {
        "evaluation": ev.to_row(),
        "fast_flow": fast_snap.to_row() if fast_snap else None,
        "sweeps_seen": len(sweeps),
        "goldens_seen": len(goldens),
        "regime": reg,
    }


@app.get("/api/net-flow-stats")
async def net_flow_stats():
    """Operational telemetry for the net-flow aggregator.

    Useful for debugging: shows trades seen/tracked/skipped, bars rotated,
    tickers with data, and the current TRACKED_TICKERS config. Also
    includes Telegram alert state (last regime per ticker, counts).
    """
    from .net_flow import get_net_flow_aggregator
    from .net_flow_signals import get_alert_state
    return {
        "aggregator": get_net_flow_aggregator().stats(),
        "alerts": get_alert_state().stats(),
    }


@app.get("/api/debug/cache-meta/{ticker}")
async def debug_cache_meta(ticker: str):
    """DEBUG: Expose internal/underscore-prefixed cache fields for a ticker.

    Used to verify priority_refresh loop activity, OI model version, KING
    model version, etc. — fields that the public /api/chains endpoint
    filters out for client-facing responses.
    """
    import time as _time
    state = await cache.get(ticker.upper())
    if not state:
        return {"error": f"{ticker} not in cache"}

    priority_ts = state.get("_priority_refresh_ts")
    now = _time.time()
    priority_age_seconds = (now - priority_ts) if priority_ts else None

    # Pick an expiration panel's meta markers (they're stored per-exp inside
    # exp_data, not at top level, because compute_exp_data sets them).
    # Look at MACRO as the canonical one; fall back to first available.
    ed = state.get("exp_data") or {}
    sample_exp_key = "MACRO (ALL 200D)" if "MACRO (ALL 200D)" in ed else (
        next(iter(ed)) if ed else None
    )
    sample_exp = ed.get(sample_exp_key, {}) if sample_exp_key else {}

    return {
        "ticker": ticker.upper(),
        "cache_timestamp": state.get("timestamp"),
        "spot": state.get("spot") or state.get("actual_spot"),
        # Priority refresh loop markers (set by priority_refresh.run_priority_refresh)
        "_priority_refresh": state.get("_priority_refresh"),
        "_priority_refresh_ts": priority_ts,
        "_priority_refresh_age_seconds": (
            round(priority_age_seconds, 1) if priority_age_seconds is not None else None
        ),
        "_priority_refresh_status": (
            "fresh" if priority_age_seconds is not None and priority_age_seconds < 30
            else "stale" if priority_age_seconds is not None
            else "never_written"
        ),
        # Methodology version markers (set by compute_exp_data)
        "exp_panel_sampled": sample_exp_key,
        "_oi_model": sample_exp.get("_oi_model"),
        "_king_model": sample_exp.get("_king_model"),
        "_sign_model": sample_exp.get("_sign_model"),
        "_zgl_method": sample_exp.get("_zgl_method"),
        "_greeks_source": sample_exp.get("_greeks_source"),
        "_greeks_age_seconds": sample_exp.get("_greeks_age_seconds"),
        # Bifurcated king fields (v4)
        "king_pos": sample_exp.get("king_pos"),
        "king_pos_gex": sample_exp.get("king_pos_gex"),
        "king_neg": sample_exp.get("king_neg"),
        "king_neg_gex": sample_exp.get("king_neg_gex"),
    }


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


@app.get("/api/signals")
async def signals_list(limit: int = 50, status: str = "", grade: str = ""):
    """Get SOE trade signals with optional filters."""
    return {"signals": get_signals(limit, status, grade)}


@app.get("/api/signals/stats")
async def signals_stats():
    """Get win rate stats by conviction grade."""
    return get_signal_stats()


@app.get("/api/discipline/tiers")
async def discipline_tiers():
    """Get base rate tiers for all tickers with trade history."""
    return {"tickers": get_ticker_stats()}


@app.get("/api/discipline/kelly/{ticker}")
async def discipline_kelly(ticker: str, is_0dte: bool = False, account_value: float = 10000):
    """Compute Quarter-Kelly position size for a ticker."""
    return compute_kelly_size(ticker.upper(), is_0dte, account_value)


@app.get("/api/discipline/circuit-breaker")
async def discipline_cb():
    """Get current circuit breaker state."""
    return get_circuit_breaker()


class TradeLogReq(BaseModel):
    ticker: str
    outcome: str  # WIN | LOSS
    pnl_pct: float
    option_type: str = ""
    strike: float = 0
    expiration: str = ""
    entry_price: float = 0
    exit_price: float = 0
    is_0dte: bool = False
    signal_id: int | None = None


def _build_strike_matrix(
    state: dict, spot: float, is_call: bool,
) -> list[dict] | None:
    """Build 3-tier strike matrix: Aggressive (2-3 DTE), Base (5-7 DTE), Sniper (9-14 DTE).

    Uses cached chain data from worker — zero API calls.
    """
    import datetime

    raw_contracts = state.get("_raw_contracts", {})
    if not raw_contracts:
        return None

    today = datetime.date.today()
    otype = "call" if is_call else "put"

    tiers = [
        {"label": "AGGRESSIVE", "dte_lo": 1, "dte_hi": 3, "delta_target": 0.50},
        {"label": "BASE", "dte_lo": 5, "dte_hi": 9, "delta_target": 0.40},
        {"label": "SNIPER", "dte_lo": 10, "dte_hi": 16, "delta_target": 0.30},
    ]

    results = []
    for tier in tiers:
        best = None
        best_dist = 999

        for exp_str, chain in raw_contracts.items():
            try:
                exp_date = datetime.date.fromisoformat(exp_str)
                dte = (exp_date - today).days
            except (ValueError, TypeError):
                continue

            if not (tier["dte_lo"] <= dte <= tier["dte_hi"]):
                continue

            for c in chain:
                if (c.get("option_type") or "").lower() != otype:
                    continue
                c_strike = c.get("strike", 0)
                if not c_strike:
                    continue
                # OTM filter
                if is_call and c_strike < spot:
                    continue
                if not is_call and c_strike > spot:
                    continue

                greeks = c.get("greeks") or {}
                delta = abs(greeks.get("delta", 0) or 0)
                bid = c.get("bid", 0) or 0
                ask = c.get("ask", 0) or 0
                mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
                oi = c.get("open_interest", 0) or 0

                # Skip illiquid
                if mid <= 0 or oi < 50:
                    continue

                dist = abs(delta - tier["delta_target"])
                if dist < best_dist:
                    best_dist = dist
                    best = {
                        "label": tier["label"],
                        "strike": c_strike,
                        "dte": dte,
                        "delta": delta,
                        "mid": mid,
                        "bid": bid,
                        "ask": ask,
                        "oi": oi,
                        "expiration": exp_str,
                    }

        if best:
            results.append(best)

    return results if results else None


def _build_mir_telegram(
    ticker: str, signal_type: str, option_type: str,
    strike: float | None, price: float | None, expiry: str | None,
    conviction: str, channel: str,
    state: dict | None, gex_context: dict,
) -> str:
    """Build a rich Telegram alert for a Mir signal using cached chain data."""
    spot = gex_context.get("spot") or (state.get("actual_spot") if state else 0) or 0
    king = gex_context.get("king", 0)
    floor_val = gex_context.get("floor", 0)
    regime = gex_context.get("regime", "?")
    gex_signal = gex_context.get("signal", "?")

    lines = [f"🎯 <b>MIR {conviction}: ${ticker}</b>"]
    lines.append(f"{signal_type} — {option_type} ${strike or '?'} {expiry or ''}")
    if price:
        lines.append(f"Mir price: ${price}")

    # ── Resolve contract from cached chains ──
    is_call = "CALL" in (option_type or "").upper() or option_type == "C"
    otype_label = "C" if is_call else "P"

    if state and strike and option_type:
        from .discord_listener import _resolve_contract_from_cache
        contract = _resolve_contract_from_cache(state, strike, option_type, expiry)
        if contract:
            bid = contract.get("bid", 0)
            ask = contract.get("ask", 0)
            mid = contract.get("mid", 0)
            delta = contract.get("delta")
            oi = contract.get("oi", 0)
            iv = contract.get("iv")
            vol = contract.get("volume", 0)

            lines.append("")
            lines.append(f"<b>Contract: ${strike}{otype_label} {contract.get('expiration', expiry or '')}</b>")
            lines.append(f"Bid ${bid:.2f} | Ask ${ask:.2f} | Mid ${mid:.2f}")
            if oi:
                lines.append(f"OI: {oi:,}  Vol: {vol:,}")
            if delta is not None:
                delta_str = f"Δ {delta:.2f}"
                if iv:
                    iv_pct = iv * 100 if iv < 5 else iv
                    delta_str += f"  IV {iv_pct:.0f}%"
                lines.append(delta_str)

            # R:R using Mir's rules: target +100% on premium, stop -50%
            if mid > 0:
                target_premium = mid * 2
                stop_premium = mid * 0.5
                lines.append(f"Target: ${target_premium:.2f} (+100%) | Stop: ${stop_premium:.2f} (-50%)")
                lines.append(f"R:R 2.0:1 (Mir standard)")
            if spot and king and king > spot:
                lines.append(f"GEX target: King ${king} (+${king - spot:.2f})")

    # ── Strike matrix (Aggressive / Base / Sniper) ──
    if state and spot:
        matrix = _build_strike_matrix(state, spot, is_call)
        if matrix:
            lines.append("")
            lines.append("<b>── Strike Matrix ──</b>")
            for entry in matrix:
                lines.append(
                    f"<b>{entry['label']}</b>: ${entry['strike']}{otype_label} "
                    f"· {entry['dte']}DTE · ${entry['mid']:.2f} · Δ{entry['delta']:.2f}"
                )

    # ── GEX structure context ──
    lines.append("")
    if spot:
        lines.append(f"Spot ${spot:.2f} | {gex_signal} | {regime} γ")
    if king:
        king_dist = ((king - spot) / spot * 100) if spot else 0
        lines.append(f"King ${king} ({king_dist:+.1f}%) | Floor ${floor_val or '?'}")

    # ── Mir 6-point scoring ──
    mir_score_shown = False
    if state:
        mir_native = state.get("_mir_signal")
        if mir_native and mir_native.get("mir_score"):
            ms = mir_native["mir_score"]
            reasons = mir_native.get("mir_reasons", [])
            lines.append("")
            lines.append(f"<b>Mir Score: {ms}/6</b>")
            for r in reasons:
                check = "✓" if any(w in r.lower() for w in ("pass", "top", "sweet", "aligned", "strong", "low vol", "approved", "above")) else "✗"
                lines.append(f"  {check} {r}")
            mir_score_shown = True

    if not mir_score_shown:
        # Compute on the fly — try snapshots first, then Tradier daily history
        try:
            from backtest.mir_scorer import score_mir_pattern
            from .snapshots import get_daily_closes
            closes = get_daily_closes(ticker, days=250)
            if len(closes) < 50:
                # Fallback: fetch from Tradier daily history
                import httpx
                s = get_settings()
                if s.tradier_token:
                    r = httpx.get(
                        f"{s.tradier_base_url}/markets/history",
                        params={"symbol": ticker, "interval": "daily"},
                        headers={"Authorization": f"Bearer {s.tradier_token}", "Accept": "application/json"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        bars = (r.json().get("history") or {}).get("day") or []
                        if isinstance(bars, dict):
                            bars = [bars]
                        closes = [b["close"] for b in bars if b.get("close")]
            if len(closes) >= 50:
                ms, reasons = score_mir_pattern(ticker, closes, dte=10, direction="BULL")
                lines.append("")
                lines.append(f"<b>Mir Score: {ms}/6</b>")
                for r in reasons:
                    check = "✓" if any(w in r.lower() for w in ("pass", "top", "sweet", "aligned", "strong", "low vol", "approved", "above")) else "✗"
                    lines.append(f"  {check} {r}")
        except Exception:
            pass

    # ── RTS / trend context ──
    if state:
        rts = state.get("_rts")
        if rts:
            rts_score = rts.get("score", 0)
            ext = rts.get("extension", "")
            lines.append(f"RS {rts_score}{' ⚠️EXT' if ext == 'EXTENDED' else ''}")

        trend = state.get("_trend_day") or {}
        if trend.get("trend_mode") != "NORMAL":
            lines.append(f"🔥 {trend['trend_mode']} ({trend.get('gap_pct', 0):+.1f}% gap)")

    # ── Flow confirmation ──
    try:
        from .flow_alerts import get_recent_flow
        flow = get_recent_flow(ticker, minutes=60)
        if flow:
            f_sent = flow.get("sentiment", "?")
            f_notional = flow.get("notional", 0)
            f_strike = flow.get("strike", 0)
            f_type = (flow.get("option_type") or "?").upper()
            f_side = flow.get("side", "?")
            f_vol = flow.get("volume", 0)
            emoji = "🟢" if f_sent == "BULLISH" else "🔴" if f_sent == "BEARISH" else "🟡"
            lines.append("")
            lines.append(f"{emoji} <b>FLOW CONFIRMS</b>: {f_sent}")
            lines.append(f"${f_strike} {f_type} | {f_vol:,} contracts | ${f_notional/1e6:.1f}M | {f_side} side")
    except Exception:
        pass

    lines.append(f"\n📡 {channel}")
    return "\n".join(lines)


class MirSignalReq(BaseModel):
    """Inbound Mir signal from Mac Mini discord listener webhook."""
    signal_type: str = ""  # ENTRY | WATCH | ADD | PARTIAL_EXIT | EXIT | STOP_LEVEL
    ticker: str = ""
    strike: float | None = None
    option_type: str = ""  # CALL | PUT
    expiry: str = ""
    entry_price: float | None = None
    price: float | None = None  # discord_listener uses "price" not "entry_price"
    stop_price: float | None = None
    conviction: str = "MEDIUM"  # HIGH | MEDIUM | LOW
    channel: str = ""  # general-alerts | challenge-account
    author: str = ""
    raw: str = ""
    raw_signal: str = ""  # legacy compat
    source: str = "discord"
    timestamp: str = ""


@app.post("/api/signals/mir")
async def ingest_mir_signal(req: MirSignalReq):
    """Webhook endpoint for Mac Mini discord listener.

    Receives parsed Mir signals, enriches with GEX context,
    stores in cache for Factor 1 conviction scoring, and
    optionally pushes to Telegram.
    """
    t = (req.ticker or "").upper()
    if not t:
        return {"ok": False, "error": "no ticker"}

    # Get GEX context for this ticker
    state = await cache.get(t)
    gex_context = {}
    if state:
        gex_context = {
            "king": state.get("king"),
            "floor": state.get("floor"),
            "ceiling": state.get("ceiling"),
            "regime": state.get("regime"),
            "signal": state.get("signal"),
            "iv": state.get("iv"),
            "spot": state.get("actual_spot"),
        }

    # Build the Mir signal record
    mir_entry = {
        "ticker": t,
        "signal_type": req.signal_type,
        "option_type": req.option_type,
        "strike": req.strike,
        "price": req.price or req.entry_price,
        "expiry": req.expiry,
        "conviction": req.conviction,
        "channel": req.channel,
        "author": req.author,
        "raw": req.raw or req.raw_signal,
        "timestamp": req.timestamp,
        "gex_context": gex_context,
        "ts": time.time(),
    }

    # Store in proper cache (1-hour TTL, used by discipline.py Factor 1)
    await cache.set_mir_signal(t, mir_entry)

    # Telegram alert with full enrichment
    if req.signal_type in ("ENTRY", "ADD") and req.conviction in ("HIGH", "MEDIUM"):
        try:
            from .telegram import send
            text = _build_mir_telegram(
                t, req.signal_type, req.option_type, req.strike,
                req.price or req.entry_price, req.expiry, req.conviction,
                req.channel, state, gex_context,
            )
            await send(text, ticker=t, force=True)
        except Exception as e:
            print(f"[MIR] Telegram error: {e}")

    print(f"[MIR] {req.conviction} {req.signal_type}: {t} ${req.strike or '?'} {req.option_type} (from {req.channel})")

    return {"ok": True, "ticker": t, "conviction": req.conviction, "gex_context": gex_context}


@app.get("/api/signals/mir/active")
async def active_mir_signals():
    """Return all active Mir signals (within TTL)."""
    signals = await cache.get_all_mir_signals()
    return {"count": len(signals), "signals": signals}


@app.get("/api/signals/confluence")
async def signal_confluence():
    """Detect when multiple signal sources converge on the same ticker.

    Returns tickers where 2+ of {SOE signal, flow alert, Mir signal} fired
    within the last 60 minutes. This is the highest-conviction event.
    """
    cutoff = int(time.time()) - 3600  # last 60 min

    # SOE signals
    soe_tickers: set[str] = set()
    try:
        from .signals import get_signals
        for s in get_signals(limit=50):
            if s.get("ts", 0) >= cutoff:
                soe_tickers.add(s["ticker"])
    except Exception:
        pass

    # Flow alerts
    flow_tickers: set[str] = set()
    for a in get_flow_alerts(since_ts=cutoff, limit=50):
        flow_tickers.add(a["ticker"])

    # Mir signals
    mir_tickers: set[str] = set()
    for m in getattr(app.state, "mir_signals", []):
        if m.get("ts", 0) >= cutoff and m.get("signal_type") in ("ENTRY", "ADD"):
            mir_tickers.add(m["ticker"])

    # Find convergence
    all_tickers = soe_tickers | flow_tickers | mir_tickers
    confluences = []
    for t in all_tickers:
        sources = []
        if t in soe_tickers:
            sources.append("SOE")
        if t in flow_tickers:
            sources.append("FLOW")
        if t in mir_tickers:
            sources.append("MIR")
        if len(sources) >= 2:
            confluences.append({
                "ticker": t,
                "sources": sources,
                "count": len(sources),
                "max_conviction": len(sources) == 3,
            })

    confluences.sort(key=lambda c: c["count"], reverse=True)
    return {"confluences": confluences, "cutoff_minutes": 60}


@app.post("/api/discipline/log-trade")
async def discipline_log(req: TradeLogReq):
    """Log a completed trade for base rate tracking + circuit breaker."""
    log_trade(
        ticker=req.ticker, outcome=req.outcome, pnl_pct=req.pnl_pct,
        option_type=req.option_type, strike=req.strike, expiration=req.expiration,
        entry_price=req.entry_price, exit_price=req.exit_price,
        is_0dte=req.is_0dte, signal_id=req.signal_id,
    )
    return {"ok": True, "ticker": req.ticker, "outcome": req.outcome}


# Root for convenience
@app.get("/")
async def root():
    return JSONResponse({"app": "GammaPulse Clone", "docs": "/docs"})
