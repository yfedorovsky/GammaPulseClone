"""Tradier paper auto-execution daemon.

Mirrors server/etrade_executor.py architecture but adapted for Tradier
API. Differences from E-Trade:
  - No OAuth dance (Bearer token, no daily expiry, no token renewal)
  - Tradier uses lowercase action verbs: buy_to_open, sell_to_close, etc.
  - Order list is unfiltered server-side; we filter by status client-side
  - Orders carry status fields: 'pending', 'open', 'partially_filled',
    'filled', 'expired', 'canceled', 'rejected', 'error'
  - Real-market quotes (no canned mocks like E-Trade sandbox)

State machine (same as E-Trade):

  PENDING (entry order placed)
    ├── 60s timeout → CANCELLED (NO_FILL)
    └── filled → FILLED
                   ├── place TP (limit @ +50%)
                   └── place Stop (stop @ -30%)
                        ├── TP filled → CLOSED (TP), cancel Stop
                        ├── Stop filled → CLOSED (STOP), cancel TP
                        ├── time_stop hit (30min) → market close
                        └── EOD hit (15:55 ET) → market close

Run:
  python -m server.tradier_executor                  # uses TRADIER_PAPER_ACCOUNT_ID from .env
  python -m server.tradier_executor --no-execute     # dry-run
  python -m server.tradier_executor --catchup        # process historical
  python -m server.tradier_executor --reconcile-only # reconcile + exit
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

from server.tradier_paper import TradierPaperClient, SANDBOX_BASE  # noqa: E402
from server import paper_executions as pe  # noqa: E402


POLL_INTERVAL_SEC = 15
ENTRY_LIMIT_BUFFER = 0.02
ENTRY_TIMEOUT_SEC = 60

TP_PCT = 0.50
STOP_PCT = -0.30
TIME_STOP_MIN = 30
EOD_CLOSE_HHMM = "15:55"

ALERT_DB = "zero_dte_alerts.db"
ST_DB = "structural_turns.db"


# Strike grid + ST helpers (copy from etrade_executor) ────────────


STRIKE_GRID = {"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0, "SPX": 5.0, "SPXW": 5.0}


def round_to_strike(ticker: str, spot: float) -> float:
    step = STRIKE_GRID.get(ticker.upper(), 1.0)
    return round(spot / step) * step


def st_today_expiration() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── Alert discovery ──────────────────────────────────────────────


def fetch_new_zero_dte_alerts(since_ts: int) -> list[dict[str, Any]]:
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
    return [r for r in rows if pe.get_by_alert("0dte", r["alert_id"]) is None]


def fetch_new_st_qualified(since_ts: int) -> list[dict[str, Any]]:
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
        alert_id = f"st_{r['id']}_{r['ticker']}_{r['ts']}"
        if pe.get_by_alert("st", alert_id) is None:
            out.append({**r, "synthetic_alert_id": alert_id})
    return out


# ── Quote helper for ST limit pricing ───────────────────────────


async def get_option_ask_via_tradier(
    client: TradierPaperClient, ticker: str, expiration: str,
    strike: float, call_or_put: str,
) -> float | None:
    """Fetch current option ask via Tradier markets/quotes (real prices)."""
    exp_compact = expiration.replace("-", "")[2:]
    cp = "C" if call_or_put.upper() in ("C", "CALL") else "P"
    strike_int = int(round(strike * 1000))
    occ = f"{ticker.upper()}{exp_compact}{cp}{strike_int:08d}"
    try:
        quotes = await client.quote([occ])
        if not quotes:
            return None
        q = quotes[0]
        ask = q.get("ask")
        # Sanity check: option ask should never exceed underlying spot.
        # Tradier sometimes returns 0 or stale data — reject obvious garbage.
        if ask is None:
            return None
        ask_f = float(ask)
        if ask_f <= 0:
            return None
        if ask_f > 100 and ticker.upper() in ("SPY", "QQQ", "IWM"):
            # SPY/QQQ/IWM 0DTE option asks shouldn't exceed $100 — likely
            # got an underlying-equity quote by mistake
            return None
        return ask_f
    except Exception as e:
        print(f"  [exec] quote lookup failed for {occ}: {e}", flush=True)
        return None


# ── Order placement primitives ──────────────────────────────────


async def place_entry_order(
    client: TradierPaperClient,
    ticker: str, direction: str,
    expiration: str, strike: float, right: str,
    limit_price: float, quantity: int = 1,
    execute: bool = True,
) -> dict[str, Any]:
    """Place a limit BUY order to open a position."""
    direction = direction.lower()
    cp = "CALL" if right.upper() in ("C", "CALL") else "PUT"
    underlying = "SPX" if ticker == "SPXW" else ticker
    return await client.place_option_order(
        account_id_key=None,    # uses default
        symbol=underlying, expiration_date=expiration,
        strike=strike, call_or_put=cp,
        action="buy_to_open", quantity=quantity,
        order_type="limit",
        limit_price=round(limit_price + ENTRY_LIMIT_BUFFER, 2),
        time_in_force="day",
        preview_only=not execute,
    )


def _norm_call_or_put(right: str) -> str:
    return "CALL" if right.upper() in ("C", "CALL") else "PUT"


def _extract_order_id(response: dict | None) -> str | None:
    """Pull order_id from Tradier response.

    Successful order POST returns: {"order": {"id": 123, "status": "ok", ...}}
    Preview returns:                {"order": {"status": "ok", ...}} (no id)
    """
    if not response:
        return None
    order = response.get("order")
    if isinstance(order, dict):
        oid = order.get("id")
        if oid is not None:
            return str(oid)
    return None


def _extract_fill_price(order: dict[str, Any]) -> float | None:
    """Pull fill price from Tradier order detail.
    Tradier fields: avg_fill_price, exec_quantity, last_fill_price.
    """
    for field in ("avg_fill_price", "last_fill_price", "price"):
        v = order.get(field)
        if v is not None:
            try:
                f = float(v)
                if f > 0:
                    return f
            except (TypeError, ValueError):
                pass
    return None


async def place_tp_and_stop(
    client: TradierPaperClient, row: dict[str, Any],
    fill_price: float,
) -> tuple[str | None, str | None]:
    """Place TP limit + Stop stop_market sub-orders. Returns (tp_id, stop_id)."""
    ticker = "SPX" if row["ticker"] in ("SPXW", "SPX") else row["ticker"]
    expiration = row["intent_expiration"]
    strike = float(row["intent_strike"])
    right = _norm_call_or_put(row["intent_right"] or "C")
    quantity = int(row["intent_quantity"] or 1)

    tp_price = round(fill_price * (1 + TP_PCT), 2)
    stop_price = round(fill_price * (1 + STOP_PCT), 2)

    tp_id = stop_id = None
    try:
        tp_resp = await client.place_close_limit(
            account_id_key=None, symbol=ticker, expiration_date=expiration,
            strike=strike, call_or_put=right, quantity=quantity,
            limit_price=tp_price,
        )
        tp_id = _extract_order_id(tp_resp)
    except Exception as e:
        print(f"  [exec] TP placement failed: {e}", flush=True)

    try:
        stop_resp = await client.place_close_stop(
            account_id_key=None, symbol=ticker, expiration_date=expiration,
            strike=strike, call_or_put=right, quantity=quantity,
            stop_price=stop_price,
        )
        stop_id = _extract_order_id(stop_resp)
    except Exception as e:
        print(f"  [exec] Stop placement failed: {e}", flush=True)

    return tp_id, stop_id


async def close_position_market(
    client: TradierPaperClient, row: dict[str, Any],
) -> str | None:
    ticker = "SPX" if row["ticker"] in ("SPXW", "SPX") else row["ticker"]
    try:
        resp = await client.place_close_market(
            account_id_key=None, symbol=ticker,
            expiration_date=row["intent_expiration"],
            strike=float(row["intent_strike"]),
            call_or_put=_norm_call_or_put(row["intent_right"] or "C"),
            quantity=int(row["intent_quantity"] or 1),
        )
        return _extract_order_id(resp)
    except Exception as e:
        print(f"  [exec] market close FAILED: {e}", flush=True)
        return None


async def safe_cancel(
    client: TradierPaperClient, order_id: str | None,
) -> None:
    if not order_id:
        return
    try:
        await client.cancel_order(int(order_id))
    except Exception as e:
        print(f"  [exec] cancel order {order_id} failed (may already be filled/cancelled): {e}",
              flush=True)


# ── Per-alert orchestration ─────────────────────────────────────


async def process_zero_dte_alert(
    client: TradierPaperClient, alert: dict[str, Any], execute: bool,
) -> None:
    print(f"[exec] 0DTE {alert['alert_id']} {alert['ticker']} {alert['direction']} "
          f"{alert['strike']:.0f}{alert['right']} @ ${alert['est_entry_price']}",
          flush=True)

    row_id = pe.insert_intent(
        alert_source="0dte", alert_id=alert["alert_id"],
        fired_at=int(alert["fired_at"]),
        ticker=alert["ticker"], direction=alert["direction"],
        intent_strike=float(alert["strike"]), intent_right=alert["right"].upper(),
        intent_expiration=alert["expiration"],
        intent_limit_price=float(alert["est_entry_price"]),
        intent_quantity=1, is_sandbox=True,
        account_id_key=client.account_id,
    )

    if not execute:
        pe.update(row_id, {"entry_fill_status": "NO_FILL",
                           "notes": "dry-run, not submitted"})
        return

    try:
        result = await place_entry_order(
            client, ticker=alert["ticker"],
            direction=alert["direction"],
            expiration=alert["expiration"],
            strike=float(alert["strike"]),
            right=alert["right"],
            limit_price=float(alert["est_entry_price"]),
            quantity=1, execute=True,
        )
        order_id = _extract_order_id(result)
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
    client: TradierPaperClient, st_event: dict[str, Any], execute: bool,
) -> None:
    """Auto-execute ST qualified fires."""
    alert_id = st_event["synthetic_alert_id"]
    ticker = st_event["ticker"]
    direction = st_event["direction"].lower()
    spot = float(st_event["spot"])

    if spot <= 0:
        return

    expiration = st_today_expiration()
    strike = round_to_strike(ticker, spot)
    right = "CALL" if direction == "bullish" else "PUT"

    print(f"[exec] ST qualified {alert_id} {ticker} {direction} → "
          f"{strike:.0f}{right[0]} {expiration}", flush=True)

    row_id = pe.insert_intent(
        alert_source="st", alert_id=alert_id,
        fired_at=int(st_event["ts"]),
        ticker=ticker, direction=direction,
        intent_strike=strike, intent_right=right,
        intent_expiration=expiration, intent_limit_price=None,
        intent_quantity=1, is_sandbox=True,
        account_id_key=client.account_id,
        notes=f"ST tier={st_event.get('tier')} spot=${spot:.2f}",
    )

    if not execute:
        pe.update(row_id, {"entry_fill_status": "NO_FILL",
                           "notes": "dry-run, ST not submitted"})
        return

    ask = await get_option_ask_via_tradier(client, ticker, expiration,
                                           strike, right)
    if ask is None or ask <= 0:
        print(f"  [exec] ST: no clean ask — skipping (no fallback price)",
              flush=True)
        pe.update(row_id, {
            "entry_fill_status": "NO_FILL",
            "notes": "no valid quote — Tradier returned no/garbage ask",
        })
        return

    pe.update(row_id, {"intent_limit_price": ask})

    try:
        result = await place_entry_order(
            client, ticker=ticker, direction=direction,
            expiration=expiration, strike=strike, right=right,
            limit_price=ask, quantity=1, execute=True,
        )
        order_id = _extract_order_id(result)
        pe.update(row_id, {
            "entry_order_id": str(order_id) if order_id else None,
            "entry_placed_at": int(time.time()),
            "entry_fill_status": "PENDING",
        })
        print(f"  [exec] ST order placed, id={order_id} @ ${ask + ENTRY_LIMIT_BUFFER:.2f}",
              flush=True)
    except Exception as e:
        print(f"  [exec] ST order placement FAILED: {e}", flush=True)
        pe.update(row_id, {
            "entry_fill_status": "REJECTED",
            "notes": f"placement error: {type(e).__name__}: {e}",
        })


# ── Position management state machine ───────────────────────────


_LAST_ORDER_ERR_TS = 0
_ORDER_ERR_LOG_INTERVAL_SEC = 15 * 60


def _today_eod_ts() -> int:
    now = datetime.now()
    h, m = map(int, EOD_CLOSE_HHMM.split(":"))
    eod = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if eod < now:
        eod = eod + timedelta(days=1)
    return int(eod.timestamp())


async def manage_open_positions(client: TradierPaperClient) -> None:
    """State machine driver: PENDING → FILLED → POSITION_OPEN → CLOSED."""
    global _LAST_ORDER_ERR_TS

    try:
        all_orders = await client.list_orders()
        orders_by_id = {
            str(o.get("id")): o for o in all_orders if o.get("id") is not None
        }
    except Exception as e:
        now_ts = int(time.time())
        if now_ts - _LAST_ORDER_ERR_TS > _ORDER_ERR_LOG_INTERVAL_SEC:
            print(f"  [exec] failed to list orders: {e} "
                  f"(suppressing repeats for 15min)", flush=True)
            _LAST_ORDER_ERR_TS = now_ts
        return

    now = int(time.time())

    # ── State 1: PENDING entries ─────────────────────────────────
    for row in pe.get_pending_orders():
        oid = row.get("entry_order_id")
        if not oid:
            continue
        order = orders_by_id.get(str(oid))
        if order is None:
            placed_at = row.get("entry_placed_at") or 0
            if now - placed_at > ENTRY_TIMEOUT_SEC:
                print(f"  [exec] cancelling stale entry {oid} (timeout)",
                      flush=True)
                await safe_cancel(client, str(oid))
                pe.update(row["id"], {
                    "entry_fill_status": "CANCELLED",
                    "exit_reason": "NO_FILL",
                    "exit_at": now,
                })
            continue

        status = (order.get("status") or "").lower()
        if status == "filled":
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
        elif status in ("canceled", "rejected", "expired", "error"):
            pe.update(row["id"], {
                "entry_fill_status": "CANCELLED",
                "exit_reason": "NO_FILL", "exit_at": now,
                "notes": (row.get("notes") or "") +
                         f" | tradier marked {status}",
            })

    # ── State 2: FILLED with no exit orders → place TP + Stop ────
    for row in pe.get_open_positions():
        if row.get("tp_order_id") or row.get("stop_order_id"):
            continue
        fill_price = row.get("entry_fill_price")
        if not fill_price:
            continue
        print(f"  [exec] placing TP/Stop for row {row['id']} "
              f"(fill=${fill_price})", flush=True)
        tp_id, stop_id = await place_tp_and_stop(client, row, float(fill_price))
        update = {}
        if tp_id:
            update["tp_order_id"] = tp_id
        if stop_id:
            update["stop_order_id"] = stop_id
        if update:
            pe.update(row["id"], update)

    # ── State 3: open positions with TP/Stop → check exits ───────
    for row in pe.get_open_positions():
        if not (row.get("tp_order_id") or row.get("stop_order_id")):
            continue

        tp_id = row.get("tp_order_id")
        stop_id = row.get("stop_order_id")
        fill_price = float(row.get("entry_fill_price") or 0)
        time_stop_at = int(row.get("time_stop_at") or 0)
        eod_at = int(row.get("eod_close_at") or 0)

        tp_order = orders_by_id.get(str(tp_id)) if tp_id else None
        stop_order = orders_by_id.get(str(stop_id)) if stop_id else None

        tp_filled = (tp_order and (tp_order.get("status") or "").lower() == "filled")
        stop_filled = (stop_order and (stop_order.get("status") or "").lower() == "filled")

        if tp_filled:
            exit_price = _extract_fill_price(tp_order) or 0
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "tp_filled_at": now, "tp_fill_price": exit_price,
                "exit_reason": "TP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
            })
            await safe_cancel(client, stop_id)
            print(f"  [exec] TP filled row {row['id']} pnl={pnl:+.0f}%",
                  flush=True)
            continue

        if stop_filled:
            exit_price = _extract_fill_price(stop_order) or 0
            pnl = (exit_price - fill_price) / fill_price * 100 if fill_price > 0 else None
            pe.update(row["id"], {
                "stop_filled_at": now, "stop_fill_price": exit_price,
                "exit_reason": "STOP", "exit_price": exit_price,
                "exit_at": now, "pnl_pct": pnl,
            })
            await safe_cancel(client, tp_id)
            print(f"  [exec] Stop filled row {row['id']} pnl={pnl:+.0f}%",
                  flush=True)
            continue

        if time_stop_at and now >= time_stop_at:
            print(f"  [exec] time-stop hit row {row['id']} → market close",
                  flush=True)
            await safe_cancel(client, tp_id)
            await safe_cancel(client, stop_id)
            close_id = await close_position_market(client, row)
            pe.update(row["id"], {
                "exit_reason": "TIME_STOP",
                "notes": (row.get("notes") or "") +
                         f" | time-stop close order_id={close_id}",
            })
            continue

        if eod_at and now >= eod_at:
            print(f"  [exec] EOD safety close row {row['id']}", flush=True)
            await safe_cancel(client, tp_id)
            await safe_cancel(client, stop_id)
            close_id = await close_position_market(client, row)
            pe.update(row["id"], {
                "exit_reason": "EOD",
                "notes": (row.get("notes") or "") +
                         f" | EOD close order_id={close_id}",
            })


# ── Reconciliation on startup ───────────────────────────────────


async def reconcile_on_startup(client: TradierPaperClient) -> dict[str, int]:
    """Sync Tradier actual state with our local DB."""
    counts = {"pending_advanced": 0, "fills_recorded": 0,
              "orphaned_tradier_orders": 0}

    try:
        all_orders = await client.list_orders()
    except Exception as e:
        print(f"[reconcile] failed to query Tradier: {e}", flush=True)
        return counts

    orders_by_id = {str(o.get("id")): o for o in all_orders if o.get("id")}
    print(f"[reconcile] Tradier state: {len(all_orders)} total orders", flush=True)

    now = int(time.time())

    for row in pe.get_pending_orders():
        oid = row.get("entry_order_id")
        if not oid:
            continue
        order = orders_by_id.get(str(oid))
        if order is None:
            pe.update(row["id"], {
                "entry_fill_status": "CANCELLED",
                "exit_reason": "NO_FILL", "exit_at": now,
                "notes": (row.get("notes") or "") +
                         " | reconciled MISSING (assumed cancelled)",
            })
            counts["pending_advanced"] += 1
            continue
        status = (order.get("status") or "").lower()
        if status == "filled":
            fill = _extract_fill_price(order)
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
        elif status in ("canceled", "rejected", "expired", "error"):
            pe.update(row["id"], {
                "entry_fill_status": "CANCELLED",
                "exit_reason": "NO_FILL", "exit_at": now,
            })
            counts["pending_advanced"] += 1

    # Detect orphaned Tradier orders not in our DB
    tracked_order_ids = set()
    for r in pe.get_recent(200):
        for col in ("entry_order_id", "tp_order_id", "stop_order_id"):
            if r.get(col):
                tracked_order_ids.add(str(r[col]))
    for oid, o in orders_by_id.items():
        status = (o.get("status") or "").lower()
        if status in ("open", "pending") and oid not in tracked_order_ids:
            counts["orphaned_tradier_orders"] += 1
            print(f"  [reconcile] WARNING: orphaned Tradier order {oid} "
                  f"({o.get('side')} {o.get('symbol')}) not in our DB",
                  flush=True)

    print(f"[reconcile] done: {counts}", flush=True)
    return counts


# ── Safety banner ───────────────────────────────────────────────


def _startup_safety_banner(execute: bool, account_id: str) -> None:
    print("=" * 70, flush=True)
    print("  TRADIER PAPER EXECUTOR — sandbox (paper-money simulation)",
          flush=True)
    print("=" * 70, flush=True)
    print(f"  base URL:    {SANDBOX_BASE}", flush=True)
    print(f"  account:     {account_id}", flush=True)
    print(f"  execute:     {execute}  ({'orders WILL be placed' if execute else 'DRY RUN'})",
          flush=True)
    print(f"  TP:          +{int(TP_PCT*100)}%", flush=True)
    print(f"  Stop:        {int(STOP_PCT*100)}%", flush=True)
    print(f"  Time-stop:   {TIME_STOP_MIN} min from entry", flush=True)
    print(f"  EOD close:   {EOD_CLOSE_HHMM} ET", flush=True)
    print(f"  UI:          https://brokerage.tradier.com (sandbox view)",
          flush=True)
    print("=" * 70, flush=True)


# ── Main loop ───────────────────────────────────────────────────


async def run_loop(execute: bool = True, catchup: bool = False,
                   skip_reconcile: bool = False) -> None:
    pe.init_db()
    client = TradierPaperClient()
    _startup_safety_banner(execute, client.account_id)

    if not skip_reconcile and execute:
        try:
            await reconcile_on_startup(client)
        except Exception as e:
            print(f"[exec] reconcile failed: {e} (continuing anyway)",
                  flush=True)

    last_seen_ts = 0 if catchup else int(time.time())
    print(f"[exec] starting loop (since_ts={last_seen_ts})", flush=True)

    try:
        while True:
            try:
                new_zd = fetch_new_zero_dte_alerts(last_seen_ts)
                new_st = fetch_new_st_qualified(last_seen_ts)

                for a in new_zd:
                    await process_zero_dte_alert(client, a, execute)
                    last_seen_ts = max(last_seen_ts, int(a["fired_at"]))
                for s in new_st:
                    await process_st_alert(client, s, execute)
                    last_seen_ts = max(last_seen_ts, int(s["ts"]))

                if execute:
                    await manage_open_positions(client)

                await asyncio.sleep(POLL_INTERVAL_SEC)
            except asyncio.CancelledError:
                print("[exec] shutdown signal received", flush=True)
                break
            except Exception as e:
                print(f"[exec] loop error: {type(e).__name__}: {e}", flush=True)
                import traceback
                traceback.print_exc()
                await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        await client.close()
        print("[exec] stopped", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-execute", action="store_true",
                   help="Dry run: log intents but don't place orders")
    p.add_argument("--catchup", action="store_true",
                   help="Process historical alerts on startup")
    p.add_argument("--reconcile-only", action="store_true",
                   help="Reconcile DB with Tradier state and exit")
    p.add_argument("--skip-reconcile", action="store_true",
                   help="Skip startup reconciliation")
    args = p.parse_args()

    if args.reconcile_only:
        async def _r():
            client = TradierPaperClient()
            try:
                counts = await reconcile_on_startup(client)
                print(f"\nReconcile result: {counts}")
            finally:
                await client.close()
        return asyncio.run(_r())

    return asyncio.run(run_loop(
        execute=not args.no_execute, catchup=args.catchup,
        skip_reconcile=args.skip_reconcile,
    ))


if __name__ == "__main__":
    sys.exit(main())
