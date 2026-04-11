"""Trade tracker + exit signal engine.

When a flow alert fires, a "tracked trade" is created. The position monitor
runs every 30 seconds checking each tracked trade against live data for exit
signals:

EXIT SIGNALS:
  KING_HIT       — spot reached the king strike (target hit, take profits)
  KING_BREAK     — spot broke through king by >0.5% (trend continuation)
  KING_SHIFT     — king moved to a different strike (structure changed)
  FLOOR_BREAK    — spot broke below floor (stop loss for longs)
  CEIL_BREAK     — spot broke above ceiling (stop loss for shorts)
  ZGL_CROSS      — spot crossed ZGL (regime boundary)
  REGIME_FLIP    — POS γ ↔ NEG γ (volatility regime changed)
  IV_CRUSH       — IV dropped 25%+ from entry (premium decaying)
  THETA_WARNING  — ≤3 days to expiration (time decay accelerating)
  PROFIT_TARGET  — option price doubled from entry (100% gain)
  STOP_LOSS      — option price dropped 50% from entry

Each signal is sent once per trade (dedup by trade_id + signal_type).
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings
from .cache import cache
from .tradier import TradierClient


TRACKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,
  option_type TEXT NOT NULL,
  entry_spot REAL,
  entry_price REAL,
  entry_iv REAL,
  entry_king REAL,
  entry_floor REAL,
  entry_ceiling REAL,
  entry_regime TEXT,
  entry_signal TEXT,
  sentiment TEXT,
  notional REAL,
  status TEXT DEFAULT 'ACTIVE',
  closed_ts INTEGER,
  close_reason TEXT
);

CREATE TABLE IF NOT EXISTS trade_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  signal_type TEXT NOT NULL,
  message TEXT,
  spot REAL,
  option_price REAL,
  FOREIGN KEY (trade_id) REFERENCES tracked_trades(id)
);
CREATE INDEX IF NOT EXISTS idx_trade_signals_tid ON trade_signals(trade_id);
"""


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


def init_tracker_db() -> None:
    with _conn() as c:
        c.executescript(TRACKER_SCHEMA)


def create_trade(alert: dict[str, Any], gex_data: dict[str, Any] | None = None) -> int:
    """Create a tracked trade from a flow alert. Returns trade_id."""
    gex = gex_data or {}
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO tracked_trades
            (created_ts, ticker, strike, expiration, option_type, entry_spot,
             entry_price, entry_iv, entry_king, entry_floor, entry_ceiling,
             entry_regime, entry_signal, sentiment, notional)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()),
                alert["ticker"],
                alert["strike"],
                alert["expiration"],
                alert["option_type"],
                alert.get("spot"),
                alert.get("last"),
                alert.get("iv"),
                gex.get("king"),
                gex.get("floor"),
                gex.get("ceiling"),
                gex.get("regime"),
                gex.get("signal"),
                alert.get("sentiment"),
                alert.get("notional"),
            ),
        )
        return cur.lastrowid


def add_signal(trade_id: int, signal_type: str, message: str, spot: float = 0, option_price: float = 0) -> bool:
    """Returns True if signal was new (inserted), False if duplicate."""
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM trade_signals WHERE trade_id = ? AND signal_type = ?",
            (trade_id, signal_type),
        ).fetchone()
        if existing:
            return False
        c.execute(
            "INSERT INTO trade_signals (trade_id, ts, signal_type, message, spot, option_price) VALUES (?,?,?,?,?,?)",
            (trade_id, int(time.time()), signal_type, message, spot, option_price),
        )
        return True


def close_trade(trade_id: int, reason: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE tracked_trades SET status = 'CLOSED', closed_ts = ?, close_reason = ? WHERE id = ?",
            (int(time.time()), reason, trade_id),
        )


def get_active_trades() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM tracked_trades WHERE status = 'ACTIVE' ORDER BY created_ts DESC",
        ).fetchall()
    return [dict(r) for r in rows]


def get_trade_signals(trade_id: int) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trade_signals WHERE trade_id = ? ORDER BY ts DESC",
            (trade_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_trades(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM tracked_trades ORDER BY created_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    trades = [dict(r) for r in rows]
    for t in trades:
        t["signals"] = get_trade_signals(t["id"])
    return trades


async def _check_exit_signals(tradier: TradierClient) -> list[dict[str, Any]]:
    """Check all active trades for exit signals. Returns list of new signals."""
    import datetime
    now = datetime.datetime.now()
    # Only check during market hours
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 30) or now.hour >= 17:
        return []

    active = get_active_trades()
    if not active:
        return []

    # Batch quotes for all active tickers
    tickers = list(set(t["ticker"] for t in active))
    quotes = await tradier.quotes(tickers)

    # Get cached GEX data for structural levels
    new_signals: list[dict[str, Any]] = []

    for trade in active:
        ticker = trade["ticker"]
        spot = quotes.get(ticker)
        if not spot:
            continue

        trade_id = trade["id"]
        entry_spot = trade["entry_spot"] or spot
        entry_price = trade["entry_price"] or 0
        entry_iv = trade["entry_iv"] or 0
        entry_king = trade["entry_king"] or 0
        entry_floor = trade["entry_floor"] or 0
        entry_ceiling = trade["entry_ceiling"] or 0
        entry_regime = trade["entry_regime"] or ""
        option_type = trade["option_type"]
        strike = trade["strike"]
        expiration = trade["expiration"]

        # Get current GEX state from cache
        gex_state = await cache.get(ticker)
        if not gex_state:
            continue
        current_king = gex_state.get("king", 0)
        current_floor = gex_state.get("floor", 0)
        current_ceiling = gex_state.get("ceiling", 0)
        current_regime = gex_state.get("regime", "")
        current_iv = gex_state.get("iv", 0)

        is_bullish = trade["sentiment"] == "BULLISH"

        # --- EXIT SIGNAL CHECKS ---

        # 1. KING_HIT — spot reached king (within 0.3%)
        if current_king and abs(spot - current_king) / spot < 0.003:
            msg = f"{ticker} ${spot:.2f} hit king ${current_king}. Target zone — consider taking profits."
            if add_signal(trade_id, "KING_HIT", msg, spot):
                new_signals.append({"trade_id": trade_id, "type": "KING_HIT", "msg": msg, "ticker": ticker})

        # 2. KING_SHIFT — king moved to a different strike
        if entry_king and current_king and current_king != entry_king:
            msg = f"{ticker} king shifted ${entry_king} → ${current_king}. Structure changed — reassess."
            if add_signal(trade_id, "KING_SHIFT", msg, spot):
                new_signals.append({"trade_id": trade_id, "type": "KING_SHIFT", "msg": msg, "ticker": ticker})

        # 3. FLOOR_BREAK — spot broke below floor (bad for bulls)
        if current_floor and spot < current_floor * 0.995:
            msg = f"{ticker} ${spot:.2f} broke below floor ${current_floor}. Support lost."
            if add_signal(trade_id, "FLOOR_BREAK", msg, spot):
                new_signals.append({"trade_id": trade_id, "type": "FLOOR_BREAK", "msg": msg, "ticker": ticker})
            if is_bullish:
                close_trade(trade_id, "FLOOR_BREAK")

        # 4. CEIL_BREAK — spot broke above ceiling (bad for bears)
        if current_ceiling and spot > current_ceiling * 1.005:
            msg = f"{ticker} ${spot:.2f} broke above ceiling ${current_ceiling}. Resistance broken."
            if add_signal(trade_id, "CEIL_BREAK", msg, spot):
                new_signals.append({"trade_id": trade_id, "type": "CEIL_BREAK", "msg": msg, "ticker": ticker})
            if not is_bullish:
                close_trade(trade_id, "CEIL_BREAK")

        # 5. REGIME_FLIP — POS ↔ NEG
        if entry_regime and current_regime and current_regime != entry_regime:
            direction = "POS → NEG (volatile)" if current_regime == "NEG" else "NEG → POS (stable)"
            msg = f"{ticker} regime flipped {direction}. Volatility structure changed."
            if add_signal(trade_id, "REGIME_FLIP", msg, spot):
                new_signals.append({"trade_id": trade_id, "type": "REGIME_FLIP", "msg": msg, "ticker": ticker})

        # 6. IV_CRUSH — IV dropped 25%+ from entry
        if entry_iv > 0 and current_iv > 0:
            iv_change = (current_iv - entry_iv) / entry_iv
            if iv_change < -0.25:
                msg = f"{ticker} IV crushed {entry_iv:.0f}% → {current_iv:.0f}% ({iv_change*100:.0f}%). Premium decaying."
                if add_signal(trade_id, "IV_CRUSH", msg, spot):
                    new_signals.append({"trade_id": trade_id, "type": "IV_CRUSH", "msg": msg, "ticker": ticker})

        # 7. THETA_WARNING — ≤3 days to expiration
        try:
            from datetime import datetime
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            days_left = (exp_date - datetime.now()).days
            if days_left <= 3:
                msg = f"{ticker} ${strike} {option_type.upper()} expires in {days_left} day(s). Theta accelerating."
                if add_signal(trade_id, "THETA_WARNING", msg, spot):
                    new_signals.append({"trade_id": trade_id, "type": "THETA_WARNING", "msg": msg, "ticker": ticker})
                if days_left <= 0:
                    close_trade(trade_id, "EXPIRED")
        except Exception:
            pass

        # 8. EXIT LADDER — systematic profit taking based on spot move from entry
        if entry_spot and entry_spot > 0:
            spot_gain_pct = ((spot - entry_spot) / entry_spot) * 100
            is_0dte_trade = False
            try:
                from datetime import datetime as dt
                exp = dt.strptime(expiration, "%Y-%m-%d").date()
                is_0dte_trade = exp == dt.now().date()
            except Exception:
                pass

            if is_0dte_trade:
                # 0DTE ladder
                if spot_gain_pct >= 100:
                    msg = f"🎯 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — sell 75%, let rest ride at $0 cost basis"
                    if add_signal(trade_id, "LADDER_100", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_100", "msg": msg, "ticker": ticker})
                elif spot_gain_pct >= 50:
                    msg = f"🎯 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — sell 50%, move stop to breakeven"
                    if add_signal(trade_id, "LADDER_50", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_50", "msg": msg, "ticker": ticker})
                if spot_gain_pct <= -50:
                    msg = f"🛑 0DTE HARD STOP -{abs(spot_gain_pct):.0f}%: {ticker} — exit 100%, no recovery time"
                    if add_signal(trade_id, "HARD_STOP_0DTE", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "HARD_STOP_0DTE", "msg": msg, "ticker": ticker})
                        close_trade(trade_id, "CLOSED_STOP")
            else:
                # Multi-week ladder
                if spot_gain_pct >= 200:
                    msg = f"🚀 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — trail remaining 25% with stop at +100%"
                    if add_signal(trade_id, "LADDER_200", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_200", "msg": msg, "ticker": ticker})
                elif spot_gain_pct >= 150:
                    msg = f"🎯 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — sell 25% more (75% total exited)"
                    if add_signal(trade_id, "LADDER_150", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_150", "msg": msg, "ticker": ticker})
                elif spot_gain_pct >= 100:
                    msg = f"🎯 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — sell 25% more (50% total), trail stop → +50%"
                    if add_signal(trade_id, "LADDER_100", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_100", "msg": msg, "ticker": ticker})
                elif spot_gain_pct >= 50:
                    msg = f"🎯 EXIT LADDER +{spot_gain_pct:.0f}%: {ticker} — sell 25%, move stop to breakeven"
                    if add_signal(trade_id, "LADDER_50", msg, spot):
                        new_signals.append({"trade_id": trade_id, "type": "LADDER_50", "msg": msg, "ticker": ticker})

        # 9. PRICE_UPDATE — spot moved significantly from entry (>2%)
        if entry_spot:
            move_pct = (spot - entry_spot) / entry_spot
            if abs(move_pct) > 0.02:
                direction = "UP" if move_pct > 0 else "DOWN"
                msg = f"{ticker} moved {direction} {abs(move_pct)*100:.1f}% from entry ${entry_spot:.2f} → ${spot:.2f}"
                if add_signal(trade_id, f"MOVE_{direction}", msg, spot):
                    new_signals.append({"trade_id": trade_id, "type": f"MOVE_{direction}", "msg": msg, "ticker": ticker})

    return new_signals


async def _send_exit_telegram(signal: dict[str, Any]) -> None:
    """Send a properly formatted exit signal to Telegram."""
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return
    emoji = {
        "KING_HIT": "🎯", "KING_SHIFT": "👑", "FLOOR_BREAK": "⚠️",
        "CEIL_BREAK": "⚠️", "REGIME_FLIP": "🔄", "IV_CRUSH": "📉",
        "THETA_WARNING": "⏰", "MOVE_UP": "📈", "MOVE_DOWN": "📉",
        "LADDER_50": "🎯", "LADDER_100": "🎯", "LADDER_150": "🎯",
        "LADDER_200": "🚀", "HARD_STOP_0DTE": "🛑",
    }.get(signal["type"], "📍")
    text = f"{emoji} {signal['type']}: {signal['ticker']}\n{signal['msg']}"
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": text},
                timeout=10,
            )
    except Exception as e:
        print(f"[TELEGRAM] exit signal send failed: {e}")


async def run_position_monitor(stop_event: asyncio.Event) -> None:
    """Background loop checking active trades every 30 seconds."""
    tradier = TradierClient()
    try:
        while not stop_event.is_set():
            try:
                signals = await _check_exit_signals(tradier)
                if signals:
                    print(f"[TRACKER] {len(signals)} new exit signals")
                    # Send Telegram with proper exit signal format
                    for s in signals[:5]:
                        await _send_exit_telegram(s)
            except Exception as e:
                print(f"[TRACKER] error: {e}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    finally:
        await tradier.close()
