"""Intraday RS-DECOUPLE detector — a name pulling away from its SECTOR in real
time (the GLW 6/18 case: +6.9% while its Photonics/Fiber peers were −4 to −12%).

WHY THIS EXISTS (the signal-to-noise win): GLW's monster run was buried under ~53
flow alerts on it alone (and ~658/day universe-wide), so a genuine catalyst-driven
leader went unnoticed. This detector is the opposite of the flow firehose — on
6/18 it fired on exactly 2 of 467 names (GLW, KLAC), both real leaders. ~0.4% of
the universe. Rare by construction = prominent by construction.

WHAT IT IS vs the EOD rs_acceleration: rs_acceleration.py snapshots the RTS
composite once at 16:00-16:30 ET and measures a multi-DAY rate-of-change — useful
swing context, but ZERO same-day lead (it computes after the close). THIS detector
runs INTRADAY: each name's open->now return vs its industry-group's mean return.
On 6/18 it would have fired GLW at ~12:00 (GLW +1.9% vs sector −2.3%, spread
+4.2%) with +3.6% of underlying move — and most of the option upside — still ahead,
and the spread widened monotonically after (a real decouple, not a head-fake).

DISCIPLINE: this is a CONTEXT / attention flag, NOT a buy signal. We have one
clean day (n=1); the logic is sound and structurally distinct from flow (it reads
relative leadership, not "someone bought calls"), but it is not a proven edge.
Frame the alert as "look here," never "buy this."
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from .config import get_settings

# Thresholds validated on the 6/18 universe scan (2/467 fired: GLW, KLAC).
NAME_MIN_PCT = 2.0       # the name must be up at least this much intraday (green)
SPREAD_MIN_PCT = 3.0     # name_ret - sector_ret must exceed this
SECTOR_MAX_PCT = 1.5     # the sector itself must be flat/down (not a sector-wide rip)
MIN_PEERS = 3            # need a real sector to decouple FROM
REFIRE_DELTA_PCT = 3.0   # re-fire same name only if spread grows this much more
SCAN_MIN_ET_HOUR = 10    # don't scan before ~10:15 ET (let moves develop)
SCAN_MIN_ET_MINUTE = 15
SCAN_INTERVAL_S = 300    # at most once per 5 min


# ── Pure cores (no DB / no clock — unit-testable) ────────────────────

def sector_returns(ret_by_ticker: dict[str, float],
                   groups: dict[str, list[str]]) -> dict[str, float]:
    """Mean intraday return per sector, over members present in ret_by_ticker."""
    out: dict[str, float] = {}
    for sector, members in groups.items():
        rs = [ret_by_ticker[m] for m in members if m in ret_by_ticker]
        if len(rs) >= 1:
            out[sector] = sum(rs) / len(rs)
    return out


def find_decouples(
    ret_by_ticker: dict[str, float], groups: dict[str, list[str]],
    name_min: float = NAME_MIN_PCT, spread_min: float = SPREAD_MIN_PCT,
    sector_max: float = SECTOR_MAX_PCT, min_peers: int = MIN_PEERS,
) -> list[dict[str, Any]]:
    """Names decoupling UP from their sector. Returns events sorted by spread desc.

    A fire requires: name green (>= name_min), sector flat/down (<= sector_max),
    spread (name - sector) >= spread_min, and a real sector (>= min_peers with
    data). The name is EXCLUDED from its own sector mean so a single monster can't
    drag the baseline up and mask its own decouple."""
    tk2sec: dict[str, str] = {m: s for s, ms in groups.items() for m in ms}
    events = []
    for t, rt in ret_by_ticker.items():
        sec = tk2sec.get(t)
        if not sec:
            continue
        peers = [ret_by_ticker[m] for m in groups[sec]
                 if m != t and m in ret_by_ticker]
        if len(peers) < min_peers:
            continue
        sec_ret = sum(peers) / len(peers)   # ex-self sector mean
        spread = rt - sec_ret
        if rt >= name_min and sec_ret <= sector_max and spread >= spread_min:
            events.append({
                "ticker": t, "name_ret": round(rt, 2), "sector": sec,
                "sector_ret": round(sec_ret, 2), "spread": round(spread, 2),
                "n_peers": len(peers),
            })
    events.sort(key=lambda e: -e["spread"])
    return events


# ── Live glue ────────────────────────────────────────────────────────

def intraday_returns_from_db(date: str | None = None) -> dict[str, float]:
    """Open->latest intraday pct return per ticker from today's snapshots
    (open = first snapshot at/after 09:30 ET local). Read-only, fail-open {}."""
    s = get_settings()
    try:
        con = sqlite3.connect(f"file:{s.snapshot_db}?mode=ro", uri=True)
    except Exception:
        return {}
    try:
        d = date or time.strftime("%Y-%m-%d")
        rows = con.execute(
            "SELECT ticker, ts, spot FROM snapshots "
            "WHERE date(ts,'unixepoch','localtime')=? ORDER BY ticker, ts", (d,)
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    for t, ts, spot in rows:
        if not spot or spot <= 0:
            continue
        if time.strftime("%H:%M", time.localtime(ts)) < "09:30":
            continue
        if t not in first:
            first[t] = spot
        last[t] = spot
    return {t: (last[t] / first[t] - 1) * 100
            for t in first if first[t] and t in last}


_fired: dict[str, tuple[str, float]] = {}   # ticker -> (date, last_fired_spread)
_last_scan_ts: float = 0.0


def _new_fires(events: list[dict], date: str) -> list[dict]:
    """Filter to genuinely new fires (per-day throttle + re-fire only on a
    materially wider spread)."""
    out = []
    for e in events:
        t = e["ticker"]
        prev = _fired.get(t)
        if prev and prev[0] == date and e["spread"] < prev[1] + REFIRE_DELTA_PCT:
            continue
        _fired[t] = (date, e["spread"])
        out.append(e)
    return out


def scan_decouples(ret_by_ticker: dict[str, float] | None = None,
                   date: str | None = None) -> list[dict]:
    """Compute decouples from intraday returns and return only NEW fires."""
    from .industry import INDUSTRY_GROUPS
    d = date or time.strftime("%Y-%m-%d")
    rets = ret_by_ticker if ret_by_ticker is not None else intraday_returns_from_db(d)
    if not rets:
        return []
    events = find_decouples(rets, INDUSTRY_GROUPS)
    return _new_fires(events, d)


def confirming_flow(ticker: str, date: str | None = None) -> dict[str, Any]:
    """Cross-reference our OWN flow: is smart money already accumulating calls on
    the decoupling name, and WHICH strikes? Makes the alert actionable without us
    'recommending' — we report what's being bought. Fail-open {}.

    Returns {n_high_conv, top_strikes} where top_strikes is a compact string like
    '200C 7/17, 175C 6/26' (the most-accumulated bullish-ASK call strikes today)."""
    s = get_settings()
    d = date or time.strftime("%Y-%m-%d")
    try:
        con = sqlite3.connect(f"file:{s.snapshot_db}?mode=ro", uri=True)
    except Exception:
        return {}
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM flow_alerts WHERE ticker=? "
            "AND date(ts,'unixepoch','localtime')=? AND side='ASK' "
            "AND sentiment LIKE 'BULL%' AND conviction='HIGH'", (ticker, d)
        ).fetchone()[0]
        # vol_oi >= 1 excludes deep-ITM stock-replacement / synthetic-long lines
        # (v/oi≈0, delta~1 — e.g. GLW's $20M 140C 9/18) which are NOT directional
        # call accumulation. Keeps the near-money/OTM lottery+conviction strikes.
        rows = con.execute(
            "SELECT strike, expiration, COUNT(*) c, SUM(notional) n FROM flow_alerts "
            "WHERE ticker=? AND date(ts,'unixepoch','localtime')=? AND side='ASK' "
            "AND sentiment LIKE 'BULL%' AND option_type='call' AND vol_oi >= 1 "
            "GROUP BY strike, expiration ORDER BY n DESC LIMIT 3", (ticker, d)
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()

    def _strike(k):
        return f"{k:g}C"

    def _exp(e):
        try:
            return f"{int(e[5:7])}/{int(e[8:10])}"
        except Exception:
            return str(e)
    top = ", ".join(f"{_strike(k)} {_exp(e)}" for k, e, c, no in rows if k)
    return {"n_high_conv": int(n), "top_strikes": top}


def format_decouple(e: dict) -> str:
    """Prominent Telegram banner. CONTEXT framing — attention flag, not a buy."""
    lines = [
        f"🚀 RS DECOUPLE — {e['ticker']}",
        f"+{e['name_ret']:.1f}% while {e['sector']} sector {e['sector_ret']:+.1f}% "
        f"(leading peers by +{e['spread']:.1f}%)",
        "Name accelerating away from its group on a catalyst.",
    ]
    flow = e.get("flow") or {}
    if flow.get("top_strikes"):
        lines.append(
            f"▸ Confirming flow: {flow.get('n_high_conv', 0)} bull-ASK HIGH-conv today; "
            f"whales accumulating {flow['top_strikes']}")
    elif flow.get("n_high_conv"):
        lines.append(f"▸ Confirming flow: {flow['n_high_conv']} bull-ASK HIGH-conv alerts today")
    lines.append("CONTEXT — high-conviction attention flag, not a buy signal.")
    return "\n".join(lines)


async def maybe_scan_rs_decouples() -> int:
    """RTH-gated, ~5-min-throttled intraday decouple scan. Dispatches a prominent
    Telegram per new fire. Returns # dispatched. Self-gates; cheap no-op outside
    the window. Never raises into the scan loop."""
    global _last_scan_ts
    try:
        from .market_calendar import is_rth_or_extended
        if not is_rth_or_extended():
            return 0
    except Exception:
        pass
    now = time.time()
    if now - _last_scan_ts < SCAN_INTERVAL_S:
        return 0
    lt = time.localtime(now)
    if (lt.tm_hour, lt.tm_min) < (SCAN_MIN_ET_HOUR, SCAN_MIN_ET_MINUTE):
        return 0
    _last_scan_ts = now
    try:
        fires = scan_decouples()
    except Exception as e:
        print(f"[RS-DECOUPLE] scan failed: {e!r}", flush=True)
        return 0
    sent = 0
    for e in fires:
        try:
            e["flow"] = confirming_flow(e["ticker"])
        except Exception:
            pass
        print(f"[RS-DECOUPLE] {e['ticker']} +{e['name_ret']}% vs {e['sector']} "
              f"{e['sector_ret']}% spread +{e['spread']}%", flush=True)
        try:
            from . import telegram
            # critical=True: NEVER-MUTE. Self-throttled to 1/name/day, so it
            # bypasses the per-ticker cooldown/daily-cap that would otherwise let
            # a hot name's whale-flow starve this (the GLW 6/18 / MRVL-$50M risk).
            ok = await telegram.send(format_decouple(e), ticker=e["ticker"], critical=True)
            sent += 1 if ok else 0
        except Exception:
            pass
    return sent
