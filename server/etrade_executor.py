"""E-Trade auto-execution daemon.

Background process that:
  1. Polls structural_turns.db (qualified ST fires) and zero_dte_alerts.db
     (0DTE engine alerts) every POLL_INTERVAL_SEC
  2. For each new alert, places a paper LIMIT order via E-Trade
  3. Tracks the entry through fill, then sets TP/Stop sub-orders
  4. Time-stops at 30min from entry; EOD-closes at 15:55 ET
  5. Logs everything to paper_executions.db (separate from main forward
     window paired_trades.db — see ETRADE_PAPER_EXECUTION_SPEC.md)

State machine for each paper_executions row:

  PENDING                       (entry order placed)
    │
    ├── timeout > ENTRY_TIMEOUT_SEC → CANCELLED (NO_FILL)
    │
    └── E-Trade reports filled → FILLED
                                  │
                                  └── place TP + Stop sub-orders → POSITION_OPEN
                                                                    │
                                                                    ├── TP filled → CLOSED (TP)
                                                                    ├── Stop filled → CLOSED (STOP)
                                                                    ├── time_stop reached → close MKT → CLOSED (TIME_STOP)
                                                                    └── EOD reached → close MKT → CLOSED (EOD)

Per the production freeze on `main`: this daemon lives only on
`feature/etrade-paper-execution` branch. Never modifies any
forward-window logic.

Run:
  python -m server.etrade_executor                     # default sandbox
  python -m server.etrade_executor --account-id KEY    # specify which paper acct
  python -m server.etrade_executor --no-execute        # dry-run: log intents, don't place orders
  python -m server.etrade_executor --catchup           # process unprocessed historical alerts on startup
  python -m server.etrade_executor --reconcile-only    # reconcile and exit
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.etrade import ETradeClient, get_cached_token, _is_sandbox, _base_url  # noqa: E402
from server import paper_executions as pe  # noqa: E402


# Polling cadence — alerts are rare (≤ ~20/day) so 15s is plenty
POLL_INTERVAL_SEC = 15

# Token renewal cadence — every 90 min keeps idle tokens warm
TOKEN_RENEWAL_INTERVAL_SEC = 90 * 60

# Entry order timing
ENTRY_LIMIT_BUFFER = 0.02   # +$0.02 over expected ask to ensure fill
ENTRY_TIMEOUT_SEC = 60      # cancel limit if not filled in 60s

# Exit policy (per docs/research/ETRADE_PAPER_EXECUTION_SPEC.md)
TP_PCT = 0.50               # +50% profit target
STOP_PCT = -0.30            # -30% stop
TIME_STOP_MIN = 30          # close at 30 min after entry
EOD_CLOSE_HHMM = "15:55"    # final EOD safety close

# Paths
ALERT_DB = "zero_dte_alerts.db"
ST_DB = "structural_turns.db"


# ── Strike-grid helper for ST auto-execution ────────────────────


# SPY / QQQ / IWM use $1 strikes; SPX uses $5
STRIKE_GRID = {
    "SPY": 1.0, "QQQ": 1.0, "IWM": 1.0,
    "SPX": 5.0, "SPXW": 5.0,
}


def round_to_strike(ticker: str, spot: float) -> float:
    step = STRIKE_GRID.get(ticker.upper(), 1.0)
    return round(spot / step) * step


def st_today_expiration() -> str:
    """ST fires on a 0DTE thesis: expiration = today (US ET)."""
    return datetime.now().strftime("%Y-%m-%d")


# ── Alert discovery ──────────────────────────────────────────────


def fetch_new_zero_dte_alerts(since_ts: int) -> list[dict[str, Any]]:
    """Pull 0DTE alerts fired after `since_ts` that haven't been
    intent-recorded in paper_executions yet."""
    if not os.path.exists(ALERT_DB):
        return []
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT alert_id, ticker, fired_at, direction, strike, right,
                      expiration, est_entry_price, est_bid, est_ask
               FROM zero_dte_alerts
               WHERE fired_at > ?
               ORDER BY fired_at""",
            (since_ts,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    out = []
    for r in rows:
        existing = pe.get_by_alert("0dte", r["alert_id"])
        if existing is None:
            out.append(r)
    return out


def fetch_new_st_qualified(since_ts: int) -> list[dict[str, Any]]:
    """Pull ST qualified fires after `since_ts` that haven't been
    intent-recorded yet."""
    if not os.path.exists(ST_DB):
        return []
    conn = sqlite3.connect(ST_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT id, ts, ticker, direction, spot, king, floor, tier
               FROM structural_turns
               WHERE qualified = 1 AND ts > ?
               ORDER BY ts""",
            (since_ts,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    out = []
    for r in rows:
        # Synthesize alert_id from row identity
        alert_id = f"st_{r['id']}_{r['ticker']}_{r['ts']}"
        existing = pe.get_by_alert("st", alert_id)
        if existing is None:
            out.append({**r, "synthetic_alert_id": alert_id})
    return out


# ── Helpers for option mid-price quote (for ST limit pricing) ───


async def get_option_ask(
    client: ETradeClient,
    ticker: str, expiration: str, strike: float, call_or_put: str,
) -> float | None:
    """Fetch current ask price for an option contract.

    E-Trade option symbols use OCC format. We construct it inline.
    """
    # OCC symbol format: TICKER + YYMMDD + C/P + strike*1000 (8 digits)
    exp_compact = expiration.replace("-", "")[2:]  # YYMMDD
    cp = "C" if call_or_put.upper() in ("C", "CALL") else "P"
    strike_int = int(round(strike * 1000))
    occ = f"{ticker.upper()}{exp_compact}{cp}{strike_int:08d}"
    try:
        quotes = await client.quote([occ])
        if not quotes:
            return None
        q = quotes[0]
        # Quote shape varies; try multiple paths
        ask = (
            (q.get("Option") or {}).get("ask")
            or (q.get("All") or {}).get("ask")
            or q.get("ask")
        )
        return float(ask) if ask is not None else None
    except Exception:
        return None


# ── Order placement primitives ──────────────────────────────────


async def place_entry_order(
    client: ETradeClient, account_id_key: str,
    ticker: str, direction: str,
    expiration: str, strike: float, right: str,
    limit_price: float, quantity: int = 1,
    execute: bool = True,
) -> dict[str, Any]:
    """Place a LIMIT BUY order to open a position."""
    direction = direction.lower()
    call_or_put = right.upper()
    if call_or_put in ("C", "CALL"):
        call_or_put = "CALL"
    else:
        call_or_put = "PUT"
    underlying = "SPX" if ticker == "SPXW" else ticker
    return await client.place_option_order(
        account_id_key=account_id_key,
        symbol=underlying,
        expiration_date=expiration,
        strike=strike,
        call_or_put=call_or_put,
        action="BUY_OPEN",
        quantity=quantity,
        order_type="LIMIT",
        limit_price=round(limit_price + ENTRY_LIMIT_BUFFER, 2),
        time_in_force="DAY",
        preview_only=not execute,
    )


def _norm_call_or_put(right: str) -> str:
    return "CALL" if right.upper() in ("C", "CALL") else "PUT"


async def place_tp_and_stop(
    client: ETradeClient, account_id_key: str, row: dict[str, Any],
    fill_price: float,
) -> tuple[str | None, str | None]:
    """Place the TP LIMIT + Stop STOP orders for an open position.
    Returns (tp_order_id, stop_order_id). Either may be None on failure."""
    ticker = "SPX" if row["ticker"] in ("SPXW", "SPX") else row["ticker"]
    expiration = row["intent_expiration"]
    strike = float(row["intent_strike"])
    right = _norm_call_or_put(row["intent_right"] or "C")
    quantity = int(row["intent_quantity"] or 1)

    tp_price = round(fill_price * (1 + TP_PCT), 2)
    stop_price = round(fill_price * (1 + STOP_PCT), 2)

    tp_id: str | None = None
    stop_id: str | None = None

    # Place TP (LIMIT SELL_CLOSE)
    try:
        tp_resp = await client.place_close_limit(
            account_id_key=account_id_key,
            symbol=ticker, expiration_date=expiration, strike=strike,
            call_or_put=right, quantity=quantity, limit_price=tp_price,
        )
        tp_id = _extract_order_id(tp_resp.get("place_response"))
    except Exception as e:
        print(f"  [exec] TP placement failed: {e}", flush=True)

    # Place Stop (STOP SELL_CLOSE)
    try:
        stop_resp = await client.place_close_stop(
            account_id_key=account_id_key,
            symbol=ticker, expiration_date=expiration, strike=strike,
            call_or_put=right, quantity=quantity, stop_price=stop_price,
        )
        stop_id = _extract_order_id(stop_resp.get("place_response"))
    except Exception as e:
        print(f"  [exec] Stop placement failed: {e}", flush=True)

    return tp_id, stop_id


def _extract_order_id(place_response: dict | None) -> str | None:
    """Pull orderId out of a place_response payload (E-Trade nests it)."""
    if not place_response:
        return None
    try:
        order_ids = (place_response.get("PlaceOrderResponse", {})
                     .get("OrderIds") or [])
        if order_ids:
            return str(order_ids[0].get("orderId"))
    except Exception:
        pass
    return None


async def close_position_market(
    client: ETradeClient, account_id_key: str, row: dict[str, Any],
) -> str | None:
    """Place a MARKET SELL_CLOSE for time-stop / EOD safety."""
    ticker = "SPX" if row["ticker"] in ("SPXW", "SPX") else row["ticker"]
    try:
        resp = await client.place_close_market(
            account_id_key=account_id_key,
            symbol=ticker,
            expiration_date=row["intent_expiration"],
            strike=float(row["intent_strike"]),
            call_or_put=_norm_call_or_put(row["intent_right"] or "C"),
            quantity=int(row["intent_quantity"] or 1),
        )
        return _extract_order_id(resp.get("place_response"))
    except Exception as e:
        print(f"  [exec] market close FAILED: {e}", flush=True)
        return None


async def safe_cancel(
    client: ETradeClient, account_id_key: str, order_id: str | None,
) -> None:
    if not order_id:
        return
    try:
        await client.cancel_order(account_id_key, int(order_id))
    except Exception as e:
        print(f"  [exec] cancel order {order_id} failed (may already be filled/cancelled): {e}",
              flush=True)


# ── Per-alert orchestration ─────────────────────────────────────


async def process_zero_dte_alert(
    client: ETradeClient, account_id_key: str,
    alert: dict[str, Any], execute: bool,
) -> None:
    """Submit entry intent for one 0DTE alert, log to paper_executions."""
    print(f"[exec] 0DTE {alert['alert_id']} {alert['ticker']} {alert['direction']} "
          f"{alert['strike']:.0f}{alert['right']} @ ${alert['est_entry_price']}",
          flush=True)

    row_id = pe.insert_intent(
        alert_source="0dte",
        alert_id=alert["alert_id"],
        fired_at=int(alert["fired_at"]),
        ticker=alert["ticker"],
        direction=alert["direction"],
        intent_strike=float(alert["strike"]),
        intent_right=alert["right"].upper(),
        intent_expiration=alert["expiration"],
        intent_limit_price=float(alert["est_entry_price"]),
        intent_quantity=1,
        is_sandbox=_is_sandbox(),
        account_id_key=account_id_key,
    )

    if not execute:
        print(f"  [exec] DRY-RUN — intent logged (row_id={row_id}), no order placed",
              flush=True)
        pe.update(row_id, {"entry_fill_status": "NO_FILL",
                           "notes": "dry-run, not submitted"})
        return

    try:
        result = await place_entry_order(
            client, account_id_key,
            ticker=alert["ticker"],
            direction=alert["direction"],
            expiration=alert["expiration"],
            strike=float(alert["strike"]),
            right=alert["right"],
            limit_price=float(alert["est_entry_price"]),
            quantity=1, execute=True,
        )
        order_id = _extract_order_id(result.get("place_response"))
        pe.update(row_id, {
            "entry_order_id": str(order_id) if order_id else None,
            "entry_placed_at": int(time.time()),
            "entry_fill_status": "PENDING",
        })
        print(f"  [exec] order placed, order_id={order_id}", flush=True)
    except Exception as e:
        print(f"  [exec] order placement FAILED: {e}", flush=True)
        pe.update(row_id, {
            "entry_fill_status": "REJECTED",
            "notes": f"placement error: {type(e).__name__}: {e}",
        })


async def process_st_alert(
    client: ETradeClient, account_id_key: str,
    st_event: dict[str, Any], execute: bool,
) -> None:
    """Auto-execute ST qualified fires.

    ST events don't carry strike/expiration directly. We pick:
      - expiration = today (0DTE thesis)
      - strike = ATM rounded to ticker grid
      - right = call for BULLISH, put for BEARISH
      - limit_price = current ask (queried from E-Trade) + buffer
    """
    alert_id = st_event["synthetic_alert_id"]
    ticker = st_event["ticker"]
    direction = st_event["direction"].lower()
    spot = float(st_event["spot"])

    if spot <= 0:
        print(f"[exec] ST {alert_id}: invalid spot={spot}, skipping",
              flush=True)
        return

    expiration = st_today_expiration()
    strike = round_to_strike(ticker, spot)
    right = "CALL" if direction == "bullish" else "PUT"

    print(f"[exec] ST qualified {alert_id} {ticker} {direction} → "
          f"{strike:.0f}{right[0]} {expiration}", flush=True)

    # Insert intent first so we have a row even if quote lookup fails
    row_id = pe.insert_intent(
        alert_source="st",
        alert_id=alert_id,
        fired_at=int(st_event["ts"]),
        ticker=ticker,
        direction=direction,
        intent_strike=strike,
        intent_right=right,
        intent_expiration=expiration,
        intent_limit_price=None,   # filled below if quote available
        intent_quantity=1,
        is_sandbox=_is_sandbox(),
        account_id_key=account_id_key,
        notes=f"ST tier={st_event.get('tier')} spot=${spot:.2f}",
    )

    if not execute:
        pe.update(row_id, {"entry_fill_status": "NO_FILL",
                           "notes": "dry-run, ST not submitted"})
        return

    # Get current option ask for limit pricing
    ask = await get_option_ask(client, ticker, expiration, strike, right)
    if ask is None or ask <= 0:
        print(f"  [exec] ST: no ask quote for {strike:.0f}{right[0]} — using $0.50 fallback",
              flush=True)
        limit_price = 0.50
    else:
        limit_price = ask
    pe.update(row_id, {"intent_limit_price": limit_price})

    try:
        result = await place_entry_order(
            client, account_id_key,
            ticker=ticker, direction=direction,
            expiration=expiration, strike=strike, right=right,
            limit_price=limit_price, quantity=1, execute=True,
        )
        order_id = _extract_order_id(result.get("place_response"))
        pe.update(row_id, {
            "entry_order_id": str(order_id) if order_id else None,
            "entry_placed_at": int(time.time()),
            "entry_fill_status": "PENDING",
        })
        print(f"  [exec] ST order placed, id={order_id} @ ${limit_price + ENTRY_LIMIT_BUFFER:.2f}",
              flush=True)
    except Exception as e:
        print(f"  [exec] ST order placement FAILED: {e}", flush=True)
        pe.update(row_id, {
            "entry_fill_status": "REJECTED",
            "notes": (pe.get_by_alert("st", alert_id) or {}).get("notes", "") +
                     f" | placement error: {type(e).__name__}: {e}",
        })


# ── Position management state machine ───────────────────────────


def _today_eod_ts() -> int:
    """Today's 15:55 ET as UNIX seconds (rough — uses local tz)."""
    now = datetime.now()
    h, m = map(int, EOD_CLOSE_HHMM.split(":"))
    eod = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if eod < now:
        eod = eod + timedelta(days=1)
    return int(eod.timestamp())


def _extract_fill_price(order: dict[str, Any]) -> float | None:
    """Pull fill price out of an E-Trade order detail."""
    detail = order.get("OrderDetail")
    if isinstance(detail, list):
        detail = detail[0] if detail else {}
    elif detail is None:
        detail = {}
    instrument = detail.get("Instrument", [{}])
    if isinstance(instrument, list):
        instrument = instrument[0] if instrument else {}
    candidates = [
        detail.get("netPrice"),
        detail.get("filledPrice"),
        detail.get("limitPrice"),
        instrument.get("filledPrice"),
        instrument.get("averageExecutionPrice"),
    ]
    for c in candidates:
        if c is not None:
            try:
                return float(c)
            except (TypeError, ValueError):
                continue
    return None


async def manage_open_positions(
    client: ETradeClient, account_id_key: str,
) -> None:
    """Drive each open paper_executions row through its state machine."""
    # Fetch executed + open orders ONCE per cycle
    try:
        executed = await client.list_orders(account_id_key, status="EXECUTED")
        executed_by_id = {
            str((o.get("orderId") or o.get("OrderId"))): o for o in executed
        }
    except Exception as e:
        print(f"  [exec] failed to list executed orders: {e}", flush=True)
        executed_by_id = {}

    now = int(time.time())

    # ── State 1: PENDING entries — check fills + timeout ─────────
    pending = pe.get_pending_orders()
    for row in pending:
        oid = row.get("entry_order_id")
        if not oid:
            continue
        order = executed_by_id.get(str(oid))
        if order is None:
            # Still pending → check timeout
            placed_at = row.get("entry_placed_at") or 0
            if now - placed_at > ENTRY_TIMEOUT_SEC:
                print(f"  [exec] cancelling stale entry order {oid} (timeout)",
                      flush=True)
                await safe_cancel(client, account_id_key, str(oid))
                pe.update(row["id"], {
                    "entry_fill_status": "CANCELLED",
                    "exit_reason": "NO_FILL",
                    "exit_at": now,
                    "notes": (row.get("notes") or "") +
                             f" cancelled after {ENTRY_TIMEOUT_SEC}s timeout",
                })
            continue

        # Order filled → record fill, transition to FILLED
        fill_price = _extract_fill_price(order)
        if fill_price is None:
            continue
        pe.update(row["id"], {
            "entry_filled_at": now,
            "entry_fill_price": float(fill_price),
            "entry_fill_status": "FILLED",
            "time_stop_at": now + TIME_STOP_MIN * 60,
            "eod_close_at": _today_eod_ts(),
        })
        print(f"  [exec] entry filled: order={oid} fill=${fill_price}",
              flush=True)

    # ── State 2: FILLED with no exit orders yet — place TP + Stop ─
    open_positions = pe.get_open_positions()
    for row in open_positions:
        if row.get("tp_order_id") or row.get("stop_order_id"):
            continue   # exit orders already placed
        fill_price = row.get("entry_fill_price")
        if not fill_price:
            continue
        print(f"  [exec] placing TP/Stop for row {row['id']} "
              f"(fill=${fill_price})", flush=True)
        tp_id, stop_id = await place_tp_and_stop(
            client, account_id_key, row, float(fill_price),
        )
        update = {}
        if tp_id:
            update["tp_order_id"] = tp_id
        if stop_id:
            update["stop_order_id"] = stop_id
        if update:
            pe.update(row["id"], update)

    # ── State 3: open positions with TP/Stop placed — check exits ─
    for row in pe.get_open_positions():
        if not (row.get("tp_order_id") or row.get("stop_order_id")):
            continue   # no exit orders placed yet (shouldn't reach here)

        tp_id = row.get("tp_order_id")
        stop_id = row.get("stop_order_id")
        fill_price = float(row.get("entry_fill_price") or 0)
        time_stop_at = int(row.get("time_stop_at") or 0)
        eod_at = int(row.get("eod_close_at") or 0)

        # Did either exit order fill?
        tp_filled = executed_by_id.get(str(tp_id)) if tp_id else None
        stop_filled = executed_by_id.get(str(stop_id)) if stop_id else None

        if tp_filled:
            exit_price = _extract_fill_price(tp_filled) or 0
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "tp_filled_at": now, "tp_fill_price": exit_price,
                "exit_reason": "TP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
            })
            await safe_cancel(client, account_id_key, stop_id)
            print(f"  [exec] TP filled row {row['id']} pnl={pnl:+.0f}%",
                  flush=True)
            continue

        if stop_filled:
            exit_price = _extract_fill_price(stop_filled) or 0
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "stop_filled_at": now, "stop_fill_price": exit_price,
                "exit_reason": "STOP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
            })
            await safe_cancel(client, account_id_key, tp_id)
            print(f"  [exec] Stop filled row {row['id']} pnl={pnl:+.0f}%",
                  flush=True)
            continue

        # Time-stop or EOD close?
        if time_stop_at and now >= time_stop_at:
            print(f"  [exec] time-stop hit for row {row['id']} — closing market",
                  flush=True)
            await safe_cancel(client, account_id_key, tp_id)
            await safe_cancel(client, account_id_key, stop_id)
            close_id = await close_position_market(client, account_id_key, row)
            pe.update(row["id"], {
                "exit_reason": "TIME_STOP",
                "notes": (row.get("notes") or "") +
                         f" | time-stop close order_id={close_id}",
            })
            continue

        if eod_at and now >= eod_at:
            print(f"  [exec] EOD safety close for row {row['id']}",
                  flush=True)
            await safe_cancel(client, account_id_key, tp_id)
            await safe_cancel(client, account_id_key, stop_id)
            close_id = await close_position_market(client, account_id_key, row)
            pe.update(row["id"], {
                "exit_reason": "EOD",
                "notes": (row.get("notes") or "") +
                         f" | EOD close order_id={close_id}",
            })


# ── Reconciliation on startup ───────────────────────────────────


async def reconcile_on_startup(
    client: ETradeClient, account_id_key: str,
) -> dict[str, int]:
    """Sync E-Trade actual state with our local paper_executions DB.

    Steps:
      1. Pull all OPEN orders + EXECUTED orders + current positions
         from E-Trade
      2. For each PENDING row in our DB: cross-reference order_id with
         E-Trade. If OPEN → keep PENDING. If EXECUTED → mark FILLED
         and trigger TP/Stop placement on next loop. If not found →
         mark CANCELLED (likely lost during downtime).
      3. For each FILLED row in our DB without exit_reason:
         - Check if TP/Stop orders are still OPEN (preserve them)
         - Check if exit order filled while we were down (mark CLOSED)
         - If position no longer in E-Trade portfolio but we think it's
           open, mark as ERROR (orphaned)
      4. Detect orphaned E-Trade positions/orders not in our DB:
         log a warning (manual cleanup needed; we don't auto-cancel
         them since they may belong to other strategies)

    Returns counts: {pending_advanced, fills_recorded, orphaned}.
    """
    counts = {"pending_advanced": 0, "fills_recorded": 0,
              "orphaned_etrade_orders": 0, "orphaned_local_rows": 0}

    try:
        open_orders = await client.list_orders(account_id_key, status="OPEN")
        executed_orders = await client.list_orders(account_id_key, status="EXECUTED")
        cancelled_orders = await client.list_orders(account_id_key, status="CANCELLED")
    except Exception as e:
        print(f"[reconcile] failed to query E-Trade: {e}", flush=True)
        return counts

    open_by_id = {str((o.get("orderId") or o.get("OrderId"))): o
                  for o in open_orders}
    exec_by_id = {str((o.get("orderId") or o.get("OrderId"))): o
                  for o in executed_orders}
    cancelled_by_id = {str((o.get("orderId") or o.get("OrderId"))): o
                       for o in cancelled_orders}

    print(f"[reconcile] E-Trade state: {len(open_orders)} open, "
          f"{len(executed_orders)} executed, "
          f"{len(cancelled_orders)} cancelled", flush=True)

    now = int(time.time())

    # Step 2: PENDING rows
    for row in pe.get_pending_orders():
        oid = row.get("entry_order_id")
        if not oid:
            continue
        if str(oid) in open_by_id:
            continue   # still pending, OK
        if str(oid) in exec_by_id:
            fill = _extract_fill_price(exec_by_id[str(oid)])
            if fill:
                pe.update(row["id"], {
                    "entry_filled_at": now,
                    "entry_fill_price": float(fill),
                    "entry_fill_status": "FILLED",
                    "time_stop_at": now + TIME_STOP_MIN * 60,
                    "eod_close_at": _today_eod_ts(),
                    "notes": (row.get("notes") or "") +
                             " | reconciled FILLED on startup",
                })
                counts["pending_advanced"] += 1
                counts["fills_recorded"] += 1
                print(f"  [reconcile] row {row['id']}: PENDING → FILLED "
                      f"(fill=${fill})", flush=True)
        elif str(oid) in cancelled_by_id:
            pe.update(row["id"], {
                "entry_fill_status": "CANCELLED",
                "exit_reason": "NO_FILL", "exit_at": now,
                "notes": (row.get("notes") or "") +
                         " | reconciled CANCELLED on startup",
            })
            counts["pending_advanced"] += 1
            print(f"  [reconcile] row {row['id']}: PENDING → CANCELLED",
                  flush=True)
        else:
            # Order not found in any status — assume cancelled by E-Trade
            pe.update(row["id"], {
                "entry_fill_status": "CANCELLED",
                "exit_reason": "NO_FILL", "exit_at": now,
                "notes": (row.get("notes") or "") +
                         " | reconciled MISSING on startup (assumed cancelled)",
            })
            counts["pending_advanced"] += 1
            print(f"  [reconcile] row {row['id']}: PENDING → MISSING (assumed cancelled)",
                  flush=True)

    # Step 3: FILLED rows without exit_reason — check exit-order status
    for row in pe.get_open_positions():
        tp_id = row.get("tp_order_id")
        stop_id = row.get("stop_order_id")

        # Did TP/Stop fill while we were down?
        if tp_id and str(tp_id) in exec_by_id:
            exit_price = _extract_fill_price(exec_by_id[str(tp_id)]) or 0
            fill_price = float(row.get("entry_fill_price") or 0)
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "tp_filled_at": now, "tp_fill_price": exit_price,
                "exit_reason": "TP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
                "notes": (row.get("notes") or "") +
                         " | reconciled TP-filled during downtime",
            })
            await safe_cancel(client, account_id_key, stop_id)
            counts["fills_recorded"] += 1
            continue

        if stop_id and str(stop_id) in exec_by_id:
            exit_price = _extract_fill_price(exec_by_id[str(stop_id)]) or 0
            fill_price = float(row.get("entry_fill_price") or 0)
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "stop_filled_at": now, "stop_fill_price": exit_price,
                "exit_reason": "STOP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
                "notes": (row.get("notes") or "") +
                         " | reconciled Stop-filled during downtime",
            })
            await safe_cancel(client, account_id_key, tp_id)
            counts["fills_recorded"] += 1
            continue

    # Step 4: orphaned E-Trade orders we don't track
    tracked_order_ids: set[str] = set()
    for r in pe.get_recent(200):
        for col in ("entry_order_id", "tp_order_id", "stop_order_id"):
            v = r.get(col)
            if v:
                tracked_order_ids.add(str(v))

    for oid, o in open_by_id.items():
        if oid not in tracked_order_ids:
            counts["orphaned_etrade_orders"] += 1
            print(f"  [reconcile] WARNING: orphaned E-Trade order {oid} "
                  f"not in our DB — manual review needed", flush=True)

    print(f"[reconcile] done: {counts}", flush=True)
    return counts


# ── Main loop ───────────────────────────────────────────────────


def _startup_safety_banner(account_id_key: str, execute: bool) -> None:
    """Loud, unmissable banner at daemon startup. If we're about to
    place orders in PRODUCTION (real money), require interactive
    confirmation before continuing — this is the foot-gun guard."""
    is_sandbox = _is_sandbox()
    base_url = _base_url()

    print("=" * 70, flush=True)
    if is_sandbox:
        print("  E-TRADE EXECUTOR — SANDBOX MODE (simulated paper trades)",
              flush=True)
    else:
        print("  ! ! ! E-TRADE EXECUTOR — PRODUCTION MODE — REAL MONEY ! ! !",
              flush=True)
    print("=" * 70, flush=True)
    print(f"  base URL:    {base_url}", flush=True)
    print(f"  account:     {account_id_key}", flush=True)
    print(f"  execute:     {execute}  ({'orders WILL be placed' if execute else 'DRY RUN'})",
          flush=True)
    print(f"  TP:          +{int(TP_PCT*100)}%", flush=True)
    print(f"  Stop:        {int(STOP_PCT*100)}%", flush=True)
    print(f"  Time-stop:   {TIME_STOP_MIN} min from entry", flush=True)
    print(f"  EOD close:   {EOD_CLOSE_HHMM} ET", flush=True)
    print("=" * 70, flush=True)

    # Production guard: require typed confirmation
    if not is_sandbox and execute:
        print(flush=True)
        print("  *** PRODUCTION + EXECUTE = REAL ORDERS WITH REAL MONEY ***",
              flush=True)
        print("  *** Type 'YES TRADE LIVE' to proceed, anything else aborts. ***",
              flush=True)
        try:
            confirm = input("  Confirmation: ").strip()
        except EOFError:
            confirm = ""
        if confirm != "YES TRADE LIVE":
            print("  Aborted by safety guard. Set ETRADE_USE_SANDBOX=1 to use paper account.",
                  file=sys.stderr)
            sys.exit(1)
        print("  Confirmed. Starting in 5 seconds (Ctrl+C to abort)...", flush=True)
        import time as _t
        _t.sleep(5)


async def run_loop(
    account_id_key: str, execute: bool = True, catchup: bool = False,
    skip_reconcile: bool = False,
) -> None:
    """Main daemon loop."""
    token = get_cached_token()
    if token is None:
        print("[exec] no cached E-Trade token. Run scripts/etrade_oauth_setup.py first.",
              file=sys.stderr)
        sys.exit(1)

    # Loud safety banner + production confirmation gate
    _startup_safety_banner(account_id_key, execute)

    pe.init_db()
    client = ETradeClient(token=token)
    print(f"[exec] starting loop — env={'sandbox' if _is_sandbox() else 'PROD'} "
          f"account={account_id_key} execute={execute}", flush=True)

    # Reconcile on startup (catches state changes during downtime)
    if not skip_reconcile and execute:
        try:
            await reconcile_on_startup(client, account_id_key)
        except Exception as e:
            print(f"[exec] reconcile failed: {e} (continuing anyway)",
                  flush=True)

    if catchup:
        last_seen_ts = 0
    else:
        last_seen_ts = int(time.time())

    last_renewal = time.time()

    try:
        while True:
            try:
                if time.time() - last_renewal > TOKEN_RENEWAL_INTERVAL_SEC:
                    if await client.renew_access_token():
                        last_renewal = time.time()
                        print(f"[exec] token renewed", flush=True)

                new_zd = fetch_new_zero_dte_alerts(last_seen_ts)
                new_st = fetch_new_st_qualified(last_seen_ts)

                for a in new_zd:
                    await process_zero_dte_alert(client, account_id_key, a, execute)
                    last_seen_ts = max(last_seen_ts, int(a["fired_at"]))
                for s in new_st:
                    await process_st_alert(client, account_id_key, s, execute)
                    last_seen_ts = max(last_seen_ts, int(s["ts"]))

                if execute:
                    await manage_open_positions(client, account_id_key)

                await asyncio.sleep(POLL_INTERVAL_SEC)

            except asyncio.CancelledError:
                print("[exec] shutdown signal received", flush=True)
                break
            except Exception as e:
                print(f"[exec] loop error: {type(e).__name__}: {e}",
                      flush=True)
                import traceback
                traceback.print_exc()
                await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        await client.close()
        print("[exec] stopped", flush=True)


async def list_accounts_cli() -> int:
    token = get_cached_token()
    if token is None:
        print("No cached token. Run scripts/etrade_oauth_setup.py first.",
              file=sys.stderr)
        return 1
    client = ETradeClient(token=token)
    try:
        accts = await client.list_accounts()
        for a in accts:
            print(f"  account: id={a.get('accountId')} "
                  f"id_key={a.get('accountIdKey')} "
                  f"type={a.get('accountType')} status={a.get('accountStatus')} "
                  f"description={a.get('accountDesc') or a.get('institutionType')}")
    finally:
        await client.close()
    return 0


async def reconcile_only_cli(account_id_key: str) -> int:
    token = get_cached_token()
    if token is None:
        print("No cached token. Run scripts/etrade_oauth_setup.py first.",
              file=sys.stderr)
        return 1
    pe.init_db()
    client = ETradeClient(token=token)
    try:
        counts = await reconcile_on_startup(client, account_id_key)
        print(f"\nReconcile result: {counts}")
    finally:
        await client.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account-id", default=None,
                   help="E-Trade account_id_key (run --list-accounts to find)")
    p.add_argument("--list-accounts", action="store_true",
                   help="List your accounts and exit")
    p.add_argument("--no-execute", action="store_true",
                   help="Dry-run: log intents but don't place actual orders")
    p.add_argument("--catchup", action="store_true",
                   help="Process historical alerts on startup")
    p.add_argument("--reconcile-only", action="store_true",
                   help="Reconcile DB with E-Trade state and exit")
    p.add_argument("--skip-reconcile", action="store_true",
                   help="Skip startup reconciliation")
    args = p.parse_args()

    if args.list_accounts:
        return asyncio.run(list_accounts_cli())

    if not args.account_id:
        print("--account-id required (use --list-accounts to find yours)",
              file=sys.stderr)
        return 1

    if args.reconcile_only:
        return asyncio.run(reconcile_only_cli(args.account_id))

    return asyncio.run(run_loop(
        args.account_id, execute=not args.no_execute, catchup=args.catchup,
        skip_reconcile=args.skip_reconcile,
    ))


if __name__ == "__main__":
    sys.exit(main())
