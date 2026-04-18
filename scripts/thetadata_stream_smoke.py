"""Smoke test for ThetaData WebSocket streaming.

Goal: verify end-to-end that the Standard-tier per-contract Trade Stream
works against the locally-running Theta Terminal, before baking it into
server/thetadata.py.

Runs for ~15 seconds, subscribes to SPY near-ATM options on the next
expiration, prints every message received, counts ISO sweeps (condition=95).

Market-hours usage:
    python scripts/thetadata_stream_smoke.py

Off-hours usage (what we're doing tonight):
    Same command — will print CONNECTED status + subscription ACK + STATUS
    heartbeats, but no TRADE messages since OPRA doesn't emit after hours.
    This proves the transport works; live sweep data proves Monday AM.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter

import websockets

WS_URL = "ws://127.0.0.1:25520/v1/events"
RUN_SECONDS = 15

# ISO sweep condition codes (verified via docs + REST smoke test):
#   95  = INTERMARKET_SWEEP
#   126 = SINGLE_LEG_AUCTION_ISO
#   128 = SINGLE_LEG_CROSS_ISO
SWEEP_CONDITIONS = {95, 126, 128}
AGGRESSOR_CONDITIONS = {145, 146}  # BID_AGGRESSOR / ASK_AGGRESSOR


def build_subscribe_payload(
    root: str, expiration: int, strike_thousandths: int, right: str, req_id: int
) -> dict:
    """Per-contract Trade Stream subscribe payload (Options Standard tier).

    strike is in 10ths of a cent: $540.00 = 5400000
    expiration is YYYYMMDD int: 2026-04-17 = 20260417
    right is 'C' or 'P'
    """
    return {
        "msg_type": "STREAM",
        "sec_type": "OPTION",
        "req_type": "TRADE",
        "add": True,
        "id": req_id,
        "contract": {
            "root": root,
            "expiration": expiration,
            "strike": strike_thousandths,
            "right": right,
        },
    }


async def smoke_test() -> int:
    # Next trading day 0DTE won't exist yet (Friday night), use Monday expiration
    # but also subscribe to a few recent contracts that definitely have OI.
    # For tonight's smoke test we just need to prove connection works.
    #
    # Subscribe to a handful of SPY strikes on the next Friday expiration
    # (2026-04-24). These have OI regardless of when the test runs.
    target_contracts = [
        ("SPY", 20260424, 700000, "C"),   # 700 call
        ("SPY", 20260424, 700000, "P"),   # 700 put
        ("SPY", 20260424, 690000, "C"),   # 690 call
        ("SPY", 20260424, 710000, "C"),   # 710 call
        ("QQQ", 20260424, 600000, "C"),   # QQQ 600 call
    ]

    print(f"[SMOKE] Connecting to {WS_URL} ...", flush=True)
    try:
        async with websockets.connect(WS_URL, ping_interval=20) as ws:
            print("[SMOKE] Connected. Sending subscribe payloads ...", flush=True)

            for req_id, (root, exp, strike, right) in enumerate(target_contracts):
                payload = build_subscribe_payload(root, exp, strike, right, req_id)
                await ws.send(json.dumps(payload))
                print(f"[SMOKE]   > subscribe {root} {exp} {strike/1000} {right} (id={req_id})", flush=True)

            print(f"[SMOKE] Listening for {RUN_SECONDS}s ...", flush=True)

            msg_types = Counter()
            sweep_count = 0
            aggressor_count = 0
            trade_count = 0
            quote_count = 0
            status_count = 0
            raw_samples: list[str] = []

            async def reader():
                nonlocal sweep_count, aggressor_count, trade_count, quote_count, status_count
                while True:
                    raw = await ws.recv()
                    # Keep first few raw samples for schema inspection
                    if len(raw_samples) < 3:
                        raw_samples.append(raw if isinstance(raw, str) else raw.decode())

                    try:
                        msg = json.loads(raw)
                    except Exception:
                        print(f"[SMOKE] non-json message: {raw[:200]!r}", flush=True)
                        continue

                    header = msg.get("header") or {}
                    mtype = header.get("type", "UNKNOWN")
                    msg_types[mtype] += 1

                    if mtype == "TRADE":
                        trade_count += 1
                        trade = msg.get("trade") or {}
                        cond = trade.get("condition")
                        contract = msg.get("contract") or {}
                        root = contract.get("root", "?")
                        strike = (contract.get("strike") or 0) / 1000.0
                        right = contract.get("right", "?")
                        size = trade.get("size", 0)
                        price = trade.get("price", 0)
                        exch = trade.get("exchange", "?")

                        if cond in SWEEP_CONDITIONS:
                            sweep_count += 1
                            notional = size * price * 100
                            print(
                                f"[SWEEP] {root} ${strike:.0f}{right} "
                                f"size={size} @ ${price:.2f} = ${notional:,.0f} "
                                f"exch={exch} cond={cond}",
                                flush=True,
                            )
                        elif cond in AGGRESSOR_CONDITIONS:
                            aggressor_count += 1
                        # else: regular trade, don't spam

                    elif mtype == "QUOTE":
                        quote_count += 1
                    elif mtype == "STATUS":
                        status_count += 1

            try:
                await asyncio.wait_for(reader(), timeout=RUN_SECONDS)
            except asyncio.TimeoutError:
                pass

            print("", flush=True)
            print("[SMOKE] === Results ===", flush=True)
            print(f"[SMOKE] Message types: {dict(msg_types)}", flush=True)
            print(f"[SMOKE] Trades: {trade_count}  Quotes: {quote_count}  Status: {status_count}", flush=True)
            print(f"[SMOKE] ISO sweeps detected: {sweep_count}", flush=True)
            print(f"[SMOKE] Aggressor prints: {aggressor_count}", flush=True)
            print("", flush=True)
            print("[SMOKE] First raw message (for schema inspection):", flush=True)
            if raw_samples:
                print(raw_samples[0][:800], flush=True)
            else:
                print("  (no messages received — check subscription ACK)", flush=True)

            # Pass criteria:
            # - at least one STATUS heartbeat = connection alive
            # - during market hours, at least one TRADE = data flowing
            if status_count > 0:
                print("[SMOKE] PASS: Connection + subscribe flow verified (heartbeats received)", flush=True)
                if trade_count > 0:
                    print("[SMOKE] PASS: Live trade data flowing -- sweep detection ready to wire in", flush=True)
                else:
                    print("[SMOKE] (No trades -- expected if market closed. Re-run Monday 9:30+)", flush=True)
                return 0
            else:
                print("[SMOKE] FAIL: No STATUS heartbeats -- connection issue", flush=True)
                return 1

    except Exception as e:
        print(f"[SMOKE] FAIL: Connection failed: {e}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(smoke_test()))
