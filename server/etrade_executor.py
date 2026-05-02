"""E-Trade auto-execution daemon.

Background process that:
  1. Polls structural_turns.db (qualified ST fires) and zero_dte_alerts.db
     (0DTE engine alerts) every POLL_INTERVAL_SEC
  2. For each new alert, places a paper LIMIT order via E-Trade
  3. Tracks the entry through fill, then sets TP/Stop sub-orders
  4. Time-stops at 30min from entry; EOD-closes at 15:55 ET
  5. Logs everything to paper_executions.db (separate from main forward
     window paired_trades.db — see ETRADE_PAPER_EXECUTION_SPEC.md)

Per the production freeze on `main`: this daemon lives only on
`feature/etrade-paper-execution` branch. Never modifies any
forward-window logic.

Run:
  python -m server.etrade_executor                     # default sandbox
  python -m server.etrade_executor --account-id KEY    # specify which paper acct
  python -m server.etrade_executor --no-execute        # dry-run: log intents, don't place orders
  python -m server.etrade_executor --catchup           # process unprocessed historical alerts on startup

Operational pre-requisites:
  1. Run scripts/etrade_oauth_setup.py first to grant tokens
  2. Set ETRADE_USE_SANDBOX=1 in .env (default)
  3. Identify your paper account_id_key (run --list-accounts)
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

from server.etrade import ETradeClient, get_cached_token, _is_sandbox  # noqa: E402
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


# ── Order placement ─────────────────────────────────────────────


async def place_entry_order(
    client: ETradeClient, account_id_key: str,
    ticker: str, direction: str,
    expiration: str, strike: float, right: str,
    limit_price: float, quantity: int = 1,
    execute: bool = True,
) -> dict[str, Any]:
    """Place a LIMIT BUY order to open a position.

    direction: 'bullish' → call BUY_OPEN, 'bearish' → put BUY_OPEN
    Returns dict with preview + place response.
    """
    direction = direction.lower()
    call_or_put = right.upper()
    if call_or_put in ("C", "CALL"):
        call_or_put = "CALL"
    else:
        call_or_put = "PUT"

    # Strike-picker uses tickers; E-Trade expects underlying ticker
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
        place_resp = result.get("place_response", {})
        place_obj = (place_resp.get("PlaceOrderResponse", {})
                     .get("OrderIds", [{}])[0])
        order_id = place_obj.get("orderId")
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
    """ST fires don't carry strike info directly — pick ATM same-day expiration.
    For now, log the intent without auto-placing (would need strike picker
    integration). MVP: log only, MCP can manually fire if desired.
    """
    alert_id = st_event["synthetic_alert_id"]
    print(f"[exec] ST qualified {alert_id} {st_event['ticker']} "
          f"{st_event['direction']} (LOG ONLY for MVP)", flush=True)

    pe.insert_intent(
        alert_source="st",
        alert_id=alert_id,
        fired_at=int(st_event["ts"]),
        ticker=st_event["ticker"],
        direction=st_event["direction"].lower(),
        intent_strike=None,        # MVP: don't auto-pick strike for ST
        intent_right=None,
        intent_expiration=None,
        intent_limit_price=None,
        intent_quantity=1,
        is_sandbox=_is_sandbox(),
        account_id_key=account_id_key,
        notes="ST fire logged but not auto-executed (MVP). "
              "Use MCP to manually place the position.",
    )


# ── Position management (open positions exit logic) ─────────────


async def manage_open_positions(client: ETradeClient, account_id_key: str) -> None:
    """For each open position in paper_executions, check whether TP/Stop/
    Time-stop/EOD has triggered. Place exit orders as needed.

    MVP scope: log decisions only; full TP/Stop sub-order placement is
    a follow-on. The current implementation:
      - Detects pending entries that have filled (queries E-Trade orders)
      - Records fill price + status
      - Detects time-stop conditions and logs
      - Does NOT yet place the closing orders (that's Phase 2.5)
    """
    open_pending = pe.get_pending_orders()
    if not open_pending:
        return

    # Pull current order status from E-Trade
    try:
        executed = await client.list_orders(account_id_key, status="EXECUTED")
        executed_by_id = {
            str((o.get("orderId") or o.get("OrderId"))): o for o in executed
        }
    except Exception as e:
        print(f"  [exec] failed to list executed orders: {e}", flush=True)
        return

    now = int(time.time())
    for row in open_pending:
        oid = row.get("entry_order_id")
        if not oid:
            continue
        order = executed_by_id.get(str(oid))
        if order is None:
            # Still pending — check timeout
            placed_at = row.get("entry_placed_at") or 0
            if now - placed_at > ENTRY_TIMEOUT_SEC:
                print(f"  [exec] cancelling stale entry order {oid} (timeout)",
                      flush=True)
                try:
                    await client.cancel_order(account_id_key, int(oid))
                    pe.update(row["id"], {
                        "entry_fill_status": "CANCELLED",
                        "exit_reason": "NO_FILL",
                        "notes": (row.get("notes") or "") +
                                 f" cancelled after {ENTRY_TIMEOUT_SEC}s timeout",
                    })
                except Exception as e:
                    print(f"  [exec] cancel failed: {e}", flush=True)
            continue

        # Order filled — record fill price
        # E-Trade response shapes vary; try common paths
        order_detail = order.get("OrderDetail", [{}])[0] if isinstance(
            order.get("OrderDetail"), list,
        ) else order.get("OrderDetail", {})
        instrument = order_detail.get("Instrument", [{}])
        if isinstance(instrument, list):
            instrument = instrument[0] if instrument else {}
        fill_price = (
            order_detail.get("filledPrice")
            or order_detail.get("limitPrice")
            or instrument.get("filledPrice")
        )
        if fill_price is None:
            continue
        pe.update(row["id"], {
            "entry_filled_at": now,
            "entry_fill_price": float(fill_price),
            "entry_fill_status": "FILLED",
            "time_stop_at": now + TIME_STOP_MIN * 60,
            # EOD = 15:55 ET on same day as fire (rough)
            "eod_close_at": int(_today_eod_ts()),
        })
        print(f"  [exec] entry filled: order={oid} fill=${fill_price}",
              flush=True)


def _today_eod_ts() -> int:
    """Today's 15:55 ET as UNIX seconds (rough — uses local tz)."""
    now = datetime.now()
    eod = now.replace(hour=15, minute=55, second=0, microsecond=0)
    if eod < now:
        eod = eod + timedelta(days=1)
    return int(eod.timestamp())


# ── Main loop ───────────────────────────────────────────────────


async def run_loop(
    account_id_key: str, execute: bool = True, catchup: bool = False,
) -> None:
    """Main daemon loop."""
    token = get_cached_token()
    if token is None:
        print("[exec] no cached E-Trade token. Run scripts/etrade_oauth_setup.py first.",
              file=sys.stderr)
        sys.exit(1)

    pe.init_db()
    client = ETradeClient(token=token)
    print(f"[exec] starting — env={'sandbox' if _is_sandbox() else 'PROD'} "
          f"account={account_id_key} execute={execute}", flush=True)

    # Pick starting timestamp — if catchup, process all historical;
    # else only new alerts from now.
    if catchup:
        last_seen_ts = 0
    else:
        last_seen_ts = int(time.time())

    last_renewal = time.time()

    try:
        while True:
            try:
                # 1. Renew token periodically
                if time.time() - last_renewal > TOKEN_RENEWAL_INTERVAL_SEC:
                    if await client.renew_access_token():
                        last_renewal = time.time()
                        print(f"[exec] token renewed", flush=True)

                # 2. Discover new alerts
                new_zd = fetch_new_zero_dte_alerts(last_seen_ts)
                new_st = fetch_new_st_qualified(last_seen_ts)

                # 3. Process each
                for a in new_zd:
                    await process_zero_dte_alert(client, account_id_key, a, execute)
                    last_seen_ts = max(last_seen_ts, int(a["fired_at"]))
                for s in new_st:
                    await process_st_alert(client, account_id_key, s, execute)
                    last_seen_ts = max(last_seen_ts, int(s["ts"]))

                # 4. Manage open positions (fill detection, time/EOD stops)
                if execute:
                    await manage_open_positions(client, account_id_key)

                # 5. Sleep
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
    args = p.parse_args()

    if args.list_accounts:
        return asyncio.run(list_accounts_cli())

    if not args.account_id:
        print("--account-id required (use --list-accounts to find yours)",
              file=sys.stderr)
        return 1

    return asyncio.run(run_loop(
        args.account_id, execute=not args.no_execute, catchup=args.catchup,
    ))


if __name__ == "__main__":
    sys.exit(main())
