"""SPX STARS-ALIGN scanner — anticipatory, defined-risk, shadow-first.

The selectivity + pre-positioning layer on top of the live SPX context (GEX map +
flow). Designed AGAINST this project's own evidence, not the hope:
  - GEX levels are coin-flip BOUNDARIES (BOUNDARY_BEHAVIOR_AUDIT_SPX_RESULTS.md,
    FAIL) → the level is a defined-risk LIMIT LOCATION, never a bounce prediction.
  - Flow on index 0DTE is EXHAUST, not lead (INFORMED_CLUSTER_MARKOUT_VERDICT) →
    flow is a VETO here, never a trigger.
  - The edge, if any, is brutal SELECTIVITY (the spread-regime gate — the one PASS)
    + the forced-exit policy (scale at the magnet, never hold to close).

So this never CHASES: it pre-positions a resting BUY-LIMIT on a 1-5 DTE WEEKLY call
at a positive-gamma support, filled only if price comes to it (latency-immune), with
a forced scale at the magnet and a defined-risk stop. It fires SELDOM by design
(MAX_FIRES_PER_DAY) so the critical=True send lane stays spam-safe.

SHADOW-FIRST: STARS_ALIGN_ACTIVE=0 (default) → evaluate + log a PAPER ticket to
alert_outcomes (alert_type='SPX_STARS') for the 30-day markout shadow test; NO
Telegram. Flip to 1 ONLY after the shadow test beats the CLUSTER_INDEX baseline +
random-level + opposite-direction controls (see the design synthesis).

Gates wired now: spread-regime veto (GATE 0), positive-gamma/PINNED regime,
signal-not-DANGER, structure-not-risk-off veto, price-pulled-into-support. Soft
gates (opening-drive aligned, directional-prior tilt, explicit flow-not-fighting
veto) are marked TODO and add only selectivity — they never loosen the gate.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .market_calendar import is_market_holiday
from .spread_regime_gate import check_spread_regime

TRACKED = "SPX"
EVAL_INTERVAL_S = 30
RTH_ONLY = True
MAX_FIRES_PER_DAY = 2          # self-throttle — keeps critical=True spam-safe
SUPPORT_BAND_PCT = 0.004       # spot must be within 0.4% of a positive-gamma support
STOP_BUFFER_PCT = 0.003        # hard stop = support × (1 − 0.3%) close-through
TICKET_DTE_MIN, TICKET_DTE_MAX = 1, 5   # WEEKLY, never 0DTE (theta incineration)
SPX_STRIKE_STEP = 5.0


def _active() -> bool:
    return os.getenv("STARS_ALIGN_ACTIVE", "0").strip().lower() in ("1", "true", "yes", "on")


def _et_now() -> _dt.datetime:
    return _dt.datetime.now()


def _et_day(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).date().isoformat()


def _is_rth() -> bool:
    now = _et_now()
    if now.weekday() >= 5 or is_market_holiday(now.date()):
        return False
    hm = (now.hour, now.minute)
    return (9, 30) <= hm and now.hour < 16


# per-ET-day fire counter (self-throttle)
_fires_today: dict[str, int] = {}


@dataclass
class StarsAlignSignal:
    ticker: str
    fired_at: float
    spot: float
    support_name: str
    support_level: float       # the LIMIT location (defined-risk, NOT a bounce call)
    target: float              # magnet / ceiling — forced scale-out zone
    stop: float                # hard close-through stop
    sugg_strike: float
    sugg_exp: str
    sugg_dte: int
    regime: str
    spread_pct: float | None
    gates: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "spot", "support_name", "support_level", "target", "stop",
            "sugg_strike", "sugg_exp", "sugg_dte", "regime", "spread_pct", "gates")}


def _nearest_support(spot: float, king_pos, floor, zgl) -> tuple[str | None, float | None]:
    """Nearest positive-gamma support at/just below spot — where a long limit rests."""
    cands = [(n, float(v)) for n, v in
             (("king_pos", king_pos), ("floor", floor), ("zgl", zgl))
             if v and float(v) > 0 and float(v) <= spot * 1.001]
    if not cands:
        return None, None
    name, lvl = min(cands, key=lambda x: abs(spot - x[1]))
    return name, lvl


def _pick_weekly(state: dict[str, Any], now: float) -> tuple[str | None, int]:
    """Nearest real available expiration with DTE in [MIN,MAX] (weekly, not 0DTE)."""
    today = _dt.datetime.fromtimestamp(now).date()
    best, best_dte = None, 999
    for e in (state.get("exps") or []):
        try:
            d = _dt.date.fromisoformat(str(e))
        except ValueError:
            continue  # MACRO key etc.
        dte = (d - today).days
        if TICKET_DTE_MIN <= dte <= TICKET_DTE_MAX and dte < best_dte:
            best, best_dte = str(e), dte
    return best, (best_dte if best else 0)


def _macro(state: dict[str, Any]) -> dict[str, Any]:
    ed = state.get("exp_data") or {}
    for k in ("MACRO", "macro", "ALL"):
        if k in ed:
            return ed[k] or {}
    return {}


# ── Soft gates (selectivity-only; FAIL-OPEN — a missing data source must never
#    cause a fire, only relax a veto. Each returns (ok, reason); ok=False vetoes) ──

def _opening_drive_ok(now: float, db_path: str = "./snapshots.db") -> tuple[bool, str]:
    """After ~10:00 ET, require the day's opening drive (9:30→10:00 SPX) to be UP
    (we take longs). The one VALIDATED context prior (close-on-drive-side 67-71%).
    Before 10:00 or on no data → pass."""
    try:
        ndt = _dt.datetime.fromtimestamp(now)
        if (ndt.hour, ndt.minute) < (10, 0):
            return True, "drive_pending"
        import sqlite3
        open_ts = ndt.replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
        drive_ts = ndt.replace(hour=10, minute=0, second=0, microsecond=0).timestamp()
        conn = sqlite3.connect(db_path)
        o = conn.execute("SELECT spot FROM snapshots WHERE ticker='SPX' AND ts>=? ORDER BY ts LIMIT 1", (open_ts,)).fetchone()
        d = conn.execute("SELECT spot FROM snapshots WHERE ticker='SPX' AND ts>=? ORDER BY ts LIMIT 1", (drive_ts,)).fetchone()
        conn.close()
        if not o or not d or not o[0] or not d[0]:
            return True, "drive_nodata"
        return (d[0] >= o[0]), ("drive_up" if d[0] >= o[0] else "opening_drive_down")
    except Exception:
        return True, "drive_err"


def _directional_ok() -> tuple[bool, str]:
    """Walk-forward P(up) prior tilt-up. prob_up < 50 → veto. Fail-open."""
    try:
        from .directional_prior import get_directional
        pu = (get_directional("SPX") or {}).get("prob_up")
        if pu is not None and pu < 50:
            return False, f"prior_down({pu:.0f})"
        return True, "prior_ok"
    except Exception:
        return True, "prior_err"


def _flow_not_fighting() -> tuple[bool, str]:
    """Bearish flow (BEARISH_DIVERGENCE / DOUBLE_STALL) → veto. Flow is VETO-only,
    never a trigger (the CLUSTER_INDEX EXHAUST lesson). Fail-open."""
    try:
        from .net_flow import get_net_flow_aggregator
        from .net_flow_signals import detect_signals
        hits = detect_signals(get_net_flow_aggregator().series("SPX"))
        bad = next((h for h in hits if getattr(h, "signal", "") in
                    ("BEARISH_DIVERGENCE", "DOUBLE_STALL")), None)
        if bad:
            return False, f"flow_{bad.signal}"
        return True, "flow_ok"
    except Exception:
        return True, "flow_err"


def evaluate(state: dict[str, Any], now: float | None = None) -> tuple[StarsAlignSignal | None, str]:
    """Run the gate stack in order. Returns (signal | None, block_reason).
    block_reason is logged so a non-fire is never silent (shadow diagnostics)."""
    now = now if now is not None else time.time()
    if RTH_ONLY and not _is_rth():
        return None, "not_rth"
    if _fires_today.get(_et_day(now), 0) >= MAX_FIRES_PER_DAY:
        return None, "daily_throttle"

    spot = state.get("actual_spot") or state.get("_spot") or state.get("spot")
    if not spot or spot <= 0:
        return None, "no_spot"
    spot = float(spot)

    # GATE 0 — spread/vol regime (the one PASS). HIGH spread = toxic tape = veto.
    sr = check_spread_regime(state, now=now)
    if sr.get("is_high") is True:
        return None, f"spread_high({sr.get('basis')})"

    # GATE 1 — positive-gamma regime (mean-revert-to-magnet only valid in +gamma)
    regime = (state.get("regime") or "").upper()
    if regime != "POS":
        return None, f"regime_{regime or 'unknown'}"

    # GATE 2 — signal not in a risk-off/amplifying config
    signal = (state.get("signal") or "").upper()
    if signal in ("DANGER", "MAGNET FADE"):
        return None, f"signal_{signal}"

    # GATE 3 — structure not RISK_OFF (short-gamma bear-day veto). Read from the
    # macro if present; absent → don't block (SPX structure cache lands next).
    macro = _macro(state)
    if macro.get("structure_risk_off") is True:
        return None, "structure_risk_off"

    # GATE 4 — price PULLED INTO a positive-gamma support (the limit location).
    king_pos = state.get("king_pos") or state.get("king")
    sname, slvl = _nearest_support(spot, king_pos, state.get("floor"), state.get("zgl"))
    if slvl is None or abs(spot - slvl) / spot > SUPPORT_BAND_PCT:
        return None, "not_at_support"

    # SOFT GATES (selectivity-only, fail-open — they only TIGHTEN). Each is a veto.
    od_ok, od_r = _opening_drive_ok(now)
    if not od_ok:
        return None, od_r
    dp_ok, dp_r = _directional_ok()
    if not dp_ok:
        return None, dp_r
    fl_ok, fl_r = _flow_not_fighting()
    if not fl_ok:
        return None, fl_r

    # All gates pass → build the resting-limit ticket on a WEEKLY call.
    target = state.get("ceiling") or king_pos
    if not target or float(target) <= spot:
        return None, "no_target_above"
    exp, dte = _pick_weekly(state, now)
    if not exp:
        return None, "no_weekly_expiry"
    sig = StarsAlignSignal(
        ticker="SPX", fired_at=now, spot=spot,
        support_name=sname or "?", support_level=float(slvl),
        target=float(target), stop=round(float(slvl) * (1 - STOP_BUFFER_PCT), 2),
        sugg_strike=round(spot / SPX_STRIKE_STEP) * SPX_STRIKE_STEP,
        sugg_exp=exp, sugg_dte=dte, regime=regime,
        spread_pct=sr.get("current_spread_pct"),
        gates=["spread_ok", "pos_gamma", f"signal_{signal or 'na'}",
               "not_risk_off", f"at_{sname}", od_r, dp_r, fl_r],
    )
    _fires_today[_et_day(now)] = _fires_today.get(_et_day(now), 0) + 1
    return sig, "FIRE"


def format_telegram(s: StarsAlignSignal) -> str:
    up = (s.target - s.spot) / s.spot * 100
    spread_str = f" · spread {s.spread_pct*100:.1f}%" if s.spread_pct is not None else ""
    return (
        f"⭐ <b>SPX STARS-ALIGN</b> (anticipatory limit)\n\n"
        f"Spot ${s.spot:,.2f} · regime {s.regime}{spread_str}\n"
        f"<b>Rest a BUY-LIMIT at {s.support_name} ${s.support_level:,.0f}</b>\n"
        f"Contract: ~${s.sugg_strike:,.0f}C {s.sugg_exp} ({s.sugg_dte}DTE weekly)\n"
        f"Target (scale ⅓): ${s.target:,.0f} (+{up:.2f}%) · Stop: ${s.stop:,.0f}\n"
        f"<i>Limit only — move comes to you. Scale at the magnet, don't hold to close.</i>"
    )


def _log_paper(sig: StarsAlignSignal) -> None:
    try:
        from .alert_outcomes import log_alert
        log_alert(
            alert_type="SPX_STARS", ticker="SPX", fired_at=sig.fired_at,
            direction="BULL", strike=sig.sugg_strike, expiration=sig.sugg_exp,
            option_type="call", dte=sig.sugg_dte, spot_at_alert=sig.spot,
            entry_price=None, target_spot=sig.target, stop_spot=sig.stop,
            king=sig.support_level, raw_alert=sig.to_row(),
        )
    except Exception as e:
        print(f"[spx_stars] log_alert failed: {e}", flush=True)


async def run_spx_stars_loop(stop_event: asyncio.Event) -> None:
    """Background loop. Evaluates SPX every EVAL_INTERVAL_S. Shadow by default:
    logs a paper ticket on every fire; Telegram (critical=True) only when
    STARS_ALIGN_ACTIVE=1."""
    from .cache import cache
    print(f"[spx_stars] loop starting — interval={EVAL_INTERVAL_S}s "
          f"active={_active()} max/day={MAX_FIRES_PER_DAY} (SHADOW unless active)", flush=True)
    cycles = fires = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=EVAL_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass
        try:
            snap = await cache.snapshot()
            state = snap.get(TRACKED) or {}
            sig, reason = evaluate(state)
            if sig:
                fires += 1
                print(f"[spx_stars] FIRE spot=${sig.spot:,.2f} {sig.support_name} "
                      f"${sig.support_level:,.0f} -> ${sig.target:,.0f} "
                      f"{sig.sugg_exp}({sig.sugg_dte}DTE)  active={_active()}", flush=True)
                _log_paper(sig)
                if _active():
                    try:
                        from .telegram import send
                        await send(format_telegram(sig), ticker="SPX", critical=True)
                    except Exception as e:
                        print(f"[spx_stars] telegram failed: {e}", flush=True)
            cycles += 1
            if cycles % 120 == 0:  # ~1h heartbeat
                print(f"[spx_stars] heartbeat cycles={cycles} fires={fires} last_block={reason}", flush=True)
        except Exception as e:
            print(f"[spx_stars] loop error: {e}", flush=True)
    print(f"[spx_stars] loop stopped — fires={fires}", flush=True)
