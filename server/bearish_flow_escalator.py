"""Aggregate bearish-flow escalator (#122-C, 2026-06-27 semis post-mortem).

The MU reversal on 2026-06-25 was *in our own tape and correctly tagged* and we
still missed it: at 09:40 ET (spot ~1240, AT the 1250 high) the raw ASK prints
went net-bearish for one window — put-ASK $45.5M (9 prints) > call-ASK $27.0M
(8 prints), driven by a fresh front-week ATM put ladder. But:

  * the strike-CLUSTER detector (informed_cluster.py) only fires when EACH leg
    is `is_insider` — only some MU put legs were insider-tagged, so it never
    reached the 3-strike threshold; and
  * every directional engine is long-biased, so nothing read "net-bearish ASK
    minute at a euphoric extreme" as a turn.

This escalator fixes that with NO dependency on per-leg insider/whale tags: it
keeps a rolling per-ticker window of ASK-side option notional and fires a BEAR
escalation when aggressive put-buying out-totals aggressive call-buying by a
meaningful margin above a dollar floor. It is the aggregate the system was
missing — the data was already there, there was just no reader.

Shadow by default. Env BEAR_ESCALATOR_ACTIVE=1 to dispatch.
"""
from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Any

WINDOW_SEC = 10 * 60          # rolling aggregation window
PUT_ASK_FLOOR = 15_000_000.0  # min ASK-side put $ in window (MU 09:40 was $45.5M)
RATIO = 1.0                   # put-ASK must exceed call-ASK by this factor
MIN_PUT_PRINTS = 3           # at least N distinct ASK put prints (not one block)
DEDUP_SEC = 30 * 60          # one escalation per ticker per 30 min


def _active() -> bool:
    return os.environ.get("BEAR_ESCALATOR_ACTIVE", "").lower() in ("1", "true", "yes")


class _ActiveProxy:
    def __bool__(self) -> bool:
        return _active()


ESCALATOR_ACTIVE = _ActiveProxy()

# ticker -> deque[(ts, option_type, side, notional)]
_events: dict[str, deque] = defaultdict(deque)
# ticker -> last escalation ts
_last_fire: dict[str, float] = {}
# escalations awaiting async Telegram dispatch (drained by the flow loop)
_pending: deque = deque()


def enqueue(esc: dict[str, Any]) -> None:
    """Queue an escalation for the async dispatch loop to send (ACTIVE mode)."""
    _pending.append(esc)


def drain_pending() -> list[dict[str, Any]]:
    """Return and clear all queued escalations (called from the async loop)."""
    out = list(_pending)
    _pending.clear()
    return out


def _norm(s: str | None) -> str:
    return (s or "").upper()


def record_and_check(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Record one flow alert; return a BEAR escalation payload or None.

    Required alert fields: ticker, ts (epoch s), option_type ('put'/'call'),
    side ('ASK'/'BID'/'MID'), notional ($). spot optional (for the payload).
    """
    ticker = alert.get("ticker")
    ts = alert.get("ts")
    notional = alert.get("notional") or 0.0
    if not ticker or ts is None or notional <= 0:
        return None

    ot = _norm(alert.get("option_type"))
    side = _norm(alert.get("side"))
    dq = _events[ticker]
    dq.append((ts, ot, side, float(notional)))

    # evict outside the window
    cutoff = ts - WINDOW_SEC
    while dq and dq[0][0] < cutoff:
        dq.popleft()

    # only ASK-side aggression counts
    put_ask = sum(n for (_t, o, s, n) in dq if o == "PUT" and s == "ASK")
    call_ask = sum(n for (_t, o, s, n) in dq if o == "CALL" and s == "ASK")
    put_prints = sum(1 for (_t, o, s, _n) in dq if o == "PUT" and s == "ASK")

    if put_ask < PUT_ASK_FLOOR or put_prints < MIN_PUT_PRINTS:
        return None
    if put_ask <= call_ask * RATIO:
        return None

    # dedup
    last = _last_fire.get(ticker)
    if last is not None and ts - last < DEDUP_SEC:
        return None
    _last_fire[ticker] = ts

    return {
        "kind": "BEAR_FLOW_ESCALATION",
        "ticker": ticker,
        "ts": ts,
        "direction": "BEAR",
        "put_ask_m": round(put_ask / 1e6, 2),
        "call_ask_m": round(call_ask / 1e6, 2),
        "put_prints": put_prints,
        "ratio": round(put_ask / call_ask, 2) if call_ask else None,
        "spot": alert.get("spot"),
        "window_sec": WINDOW_SEC,
    }


def format_telegram(esc: dict[str, Any]) -> str:
    r = f"{esc['ratio']:.1f}x" if esc.get("ratio") else "∞"
    spot = f" @ {esc['spot']:.2f}" if esc.get("spot") else ""
    return (
        f"🔴🔴 <b>BEAR FLOW ESCALATION</b> — {esc['ticker']}{spot}\n"
        f"Aggressive PUT-buying out-totals call-buying {r} in {esc['window_sec']//60}min: "
        f"${esc['put_ask_m']}M put-ASK vs ${esc['call_ask_m']}M call-ASK "
        f"({esc['put_prints']} put prints).\n"
        f"<i>Net-bearish ASK aggregation — possible distribution / turn.</i>"
    )


def reset() -> None:
    _events.clear()
    _last_fire.clear()
    _pending.clear()
