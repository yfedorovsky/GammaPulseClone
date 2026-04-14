"""Real-time unusual flow alert system — ZERO additional API calls.

Piggybacks on the GEX worker's chain cache to scan ALL cached tickers
(300+ across mega/large/mid cap) for unusual options volume every 30 seconds.

Coverage:
  - Tier 1: mega caps (SPY, QQQ, AAPL, NVDA, TSLA, etc.)
  - Tier 2: large caps (META, CRM, SHOP, UBER, etc.)
  - Tier 3: mid caps (DOCN, SOFI, RIVN, MARA, etc.)
  All tickers in the scanner universe are covered for flow alerts.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

import httpx

from .cache import cache
from .config import get_settings


ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,
  option_type TEXT NOT NULL,
  volume INTEGER,
  oi INTEGER,
  vol_oi REAL,
  last_price REAL,
  bid REAL,
  ask REAL,
  side TEXT,
  sentiment TEXT,
  iv REAL,
  delta REAL,
  notional REAL,
  spot REAL,
  conviction TEXT DEFAULT 'LOW',
  status TEXT DEFAULT 'OPEN',
  king REAL,
  floor_level REAL,
  ceiling_level REAL,
  signal TEXT,
  regime TEXT
);
CREATE INDEX IF NOT EXISTS idx_flow_ts ON flow_alerts(ts);
CREATE INDEX IF NOT EXISTS idx_flow_ticker ON flow_alerts(ticker, ts);
"""

_seen: set[str] = set()


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_alert_db() -> None:
    with _conn() as c:
        c.executescript(ALERT_SCHEMA)


def _compute_conviction(alert: dict[str, Any], gex_info: dict[str, Any] | None = None) -> str:
    """Score conviction: HIGH / MEDIUM / LOW based on volume, notional, and GEX alignment."""
    score = 0
    vol = alert.get("volume", 0)
    notional = alert.get("notional", 0)
    vol_oi = alert.get("vol_oi", 0)

    # Volume tier
    if vol >= 5000: score += 2
    elif vol >= 2000: score += 1

    # Notional tier
    if notional >= 5_000_000: score += 2
    elif notional >= 1_000_000: score += 1

    # V/OI ratio
    if vol_oi >= 10: score += 1

    # GEX alignment: does the flow direction match the GEX signal?
    if gex_info:
        signal = gex_info.get("signal", "")
        sentiment = alert.get("sentiment", "")
        otype = alert.get("option_type", "")
        # Bullish call flow in MAGNET UP / SUPPORT = aligned
        if sentiment == "BULLISH" and otype == "call" and signal in ("MAGNET UP", "SUPPORT"):
            score += 2
        # Bearish put flow in AIR POCKET / RESISTANCE = aligned
        elif sentiment == "BEARISH" and otype == "put" and signal in ("AIR POCKET", "RESISTANCE"):
            score += 2
        # Neutral pinning flow
        elif signal == "PINNING":
            score += 1

    if score >= 5: return "HIGH"
    if score >= 3: return "MEDIUM"
    return "LOW"


def insert_alert(alert: dict[str, Any], gex_info: dict[str, Any] | None = None) -> None:
    conviction = _compute_conviction(alert, gex_info)
    alert["conviction"] = conviction
    with _conn() as c:
        c.execute(
            """INSERT INTO flow_alerts
            (ts, ticker, strike, expiration, option_type, volume, oi, vol_oi,
             last_price, bid, ask, side, sentiment, iv, delta, notional, spot,
             conviction, status, king, floor_level, ceiling_level, signal, regime)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()),
                alert["ticker"],
                alert["strike"],
                alert["expiration"],
                alert["option_type"],
                alert.get("volume"),
                alert.get("oi"),
                alert.get("vol_oi"),
                alert.get("last"),
                alert.get("bid"),
                alert.get("ask"),
                alert.get("side"),
                alert.get("sentiment"),
                alert.get("iv"),
                alert.get("delta"),
                alert.get("notional"),
                alert.get("spot"),
                conviction,
                "OPEN",
                gex_info.get("king") if gex_info else None,
                gex_info.get("floor") if gex_info else None,
                gex_info.get("ceiling") if gex_info else None,
                gex_info.get("signal") if gex_info else None,
                gex_info.get("regime") if gex_info else None,
            ),
        )


def get_alerts(
    since_ts: int = 0, limit: int = 100, ticker: str | None = None
) -> list[dict[str, Any]]:
    with _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE ts > ? AND ticker = ? ORDER BY ts DESC LIMIT ?",
                (since_ts, ticker.upper(), limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                (since_ts, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get_recent_flow(ticker: str, minutes: int = 30) -> dict[str, Any] | None:
    """Get most recent HIGH-conviction flow alert for a ticker within N minutes."""
    cutoff = int(time.time()) - minutes * 60
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM flow_alerts WHERE ticker = ? AND ts > ? AND conviction = 'HIGH' ORDER BY ts DESC LIMIT 1",
            (ticker.upper(), cutoff),
        ).fetchone()
    return dict(row) if row else None


def _detect_side(bid: float, ask: float, last: float) -> str:
    if bid <= 0 and ask <= 0:
        return "MID"
    mid = (bid + ask) / 2
    spread = ask - bid if ask > bid else 0.01
    dist = abs(last - mid) / spread
    if dist < 0.2:
        return "MID"
    return "ASK" if last >= mid else "BID"


def _detect_sentiment(option_type: str, side: str) -> str:
    if side == "MID":
        return "NEUTRAL"
    if option_type == "call":
        return "BULLISH" if side == "ASK" else "BEARISH"
    return "BEARISH" if side == "ASK" else "BULLISH"


async def _send_telegram(alert: dict[str, Any]) -> None:
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return
    emoji = (
        "🟢" if alert["sentiment"] == "BULLISH"
        else "🔴" if alert["sentiment"] == "BEARISH"
        else "🟡"
    )
    otype = alert["option_type"].upper()
    text = (
        f"{emoji} FLOW ALERT: {alert['ticker']}\n"
        f"${alert['strike']} {otype} {alert['expiration']}\n"
        f"Vol: {alert['volume']:,} | OI: {alert['oi']:,} | {alert['vol_oi']}x\n"
        f"Side: {alert['side']} | {alert['sentiment']}\n"
        f"Last: ${alert['last']:.2f} | Notional: ${alert['notional']:,.0f}\n"
        f"IV: {alert['iv']}% | Delta: {alert['delta']} | Spot: ${alert['spot']:.2f}"
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": text},
                timeout=10,
            )
    except Exception as e:
        print(f"[TELEGRAM] send failed: {e}")


async def _scan_flow_from_cache(vol_oi_threshold: float = 3.0) -> list[dict[str, Any]]:
    """Scan ALL cached tickers for unusual flow using data the GEX worker
    already fetched. ZERO additional API calls.

    Covers 300+ tickers across mega/large/mid cap — including names like
    DOCN, SOFI, RIVN, MARA that wouldn't be caught by a tier-1-only scan.
    """
    import datetime

    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return []
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return []

    today_str = now.strftime("%Y-%m-%d")

    # Read the worker's chain cache — this has raw per-option data
    from .worker import _chain_cache

    snapshot = await cache.snapshot()
    new_alerts: list[dict[str, Any]] = []

    for cache_key, (ts, contracts) in list(_chain_cache.items()):
        ticker = cache_key.split(":")[0]
        exp_date = cache_key.split(":", 1)[1] if ":" in cache_key else ""

        # 0DTE alerts stay ON all day — tradeable until market close on most brokers

        spot = 0
        state = snapshot.get(ticker)
        if state:
            spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot:
            continue

        for opt in contracts:
            vol = int(opt.get("volume") or 0)
            oi = int(opt.get("open_interest") or 0)
            if vol < 500 or oi < 1:
                continue
            vol_oi = round(vol / oi, 1)
            # Two paths to qualify:
            # 1. High V/OI ratio (unusual relative to open interest)
            # 2. Massive notional (>$5M) regardless of V/OI — catches big block trades
            est_notional = vol * (float(opt.get("last") or 0)) * 100
            if vol_oi < vol_oi_threshold and est_notional < 5_000_000:
                continue

            strike = opt.get("strike", 0)
            otype = (opt.get("option_type") or "").lower()
            opt_exp = opt.get("expiration_date") or exp_date

            # Dedup
            key = f"{ticker}:{strike}:{opt_exp}:{otype}"
            if key in _seen:
                continue
            _seen.add(key)

            bid = float(opt.get("bid") or 0)
            ask = float(opt.get("ask") or 0)
            last = float(opt.get("last") or 0)
            greeks = opt.get("greeks") or {}
            iv = float(greeks.get("mid_iv") or greeks.get("smv_vol") or 0)
            delta = float(greeks.get("delta") or 0)

            side = _detect_side(bid, ask, last)
            sentiment = _detect_sentiment(otype, side)
            notional = vol * last * 100

            # Noise filters
            if notional < 250_000:
                continue
            if abs(delta) > 0.95:
                continue
            if iv > 2.0:
                continue

            alert = {
                "ticker": ticker,
                "strike": strike,
                "expiration": opt_exp,
                "option_type": otype,
                "volume": vol,
                "oi": oi,
                "vol_oi": round(vol_oi, 1),
                "last": last,
                "bid": bid,
                "ask": ask,
                "side": side,
                "sentiment": sentiment,
                "iv": round(iv * 100, 1),
                "delta": round(delta, 3),
                "notional": round(notional),
                "spot": spot,
            }
            gex_info = {
                "king": state.get("king") if state else None,
                "floor": state.get("floor") if state else None,
                "ceiling": state.get("ceiling") if state else None,
                "regime": state.get("regime") if state else None,
                "signal": state.get("signal") if state else None,
            }
            insert_alert(alert, gex_info)
            new_alerts.append(alert)

            # Auto-track for exit signals
            try:
                from .trade_tracker import create_trade
                create_trade(alert, gex_info)
            except Exception:
                pass

    return new_alerts


async def run_flow_scanner(stop_event: asyncio.Event) -> None:
    """Background loop scanning cached data every 30 seconds.
    Zero API calls — uses the GEX worker's chain cache."""
    # Wait a bit for the first GEX cycle to populate the cache
    await asyncio.sleep(30)
    while not stop_event.is_set():
        try:
            alerts = await _scan_flow_from_cache()
            if alerts:
                tickers_hit = list(set(a["ticker"] for a in alerts))
                print(
                    f"[FLOW] {len(alerts)} new alerts: "
                    f"{', '.join(tickers_hit[:10])}"
                )
                import datetime
                today_str = datetime.date.today().isoformat()
                from .telegram import send, format_flow_alert
                for a in alerts[:2]:  # Max 2 per cycle
                    if a.get("conviction") != "HIGH":  # HIGH only
                        continue
                    # Must be a clear directional signal (not MID/NEUTRAL)
                    if a.get("side") == "MID":
                        continue
                    # Minimum $5M notional for all flow alerts
                    if (a.get("notional", 0) or 0) < 5_000_000:
                        continue
                    # Strike must be OTM by at least 1% — skip already-ITM chases
                    strike = a.get("strike", 0) or 0
                    spot = a.get("spot", 0) or 0
                    if strike and spot:
                        is_call = (a.get("option_type") or "").lower() == "call"
                        otm_pct = ((strike - spot) / spot * 100) if is_call else ((spot - strike) / spot * 100)
                        if otm_pct < 1.0:
                            continue  # ITM or barely OTM — premium already jacked
                    await send(
                        format_flow_alert(a),
                        ticker=a.get("ticker", ""),
                    )
        except Exception as e:
            print(f"[FLOW] scan error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
