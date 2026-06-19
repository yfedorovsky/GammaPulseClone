"""Detector A — OPEX-day fresh-spot 1-minute velocity break.

The MRVL 6/18 OPEX pin-break post-mortem (`session-jun18-findings`) established
that structure DETECTS but does not PREDICT a pin break: net_GEX is a FALSE
all-clear that PEAKS right before the cascade, and every structural signal stamps
at the break minute (15:50) with zero lead. The one thing that failed us live was
LATENCY — our spot froze for ~10-12 minutes (stale worker cache), so we were
blind to a −3.4%/min cascade as it happened.

This detector does NOT forecast. It removes the blindness: on an OPEX day, using
the 5s FRESH spot (stream.fresh_spot, the #51 fix — NOT the stale worker cache),
fire once when price drops >= VELOCITY_THRESHOLD_PCT within a ~1-minute rolling
window. Validated on MRVL 6/18: exactly 1 fire (the 15:50 −3.41% candle), 0 false
positives (next-worst 1-min drop all day was −1.17%). ~17 sigma vs the pinned
regime's ~0.2% per-minute stdev.

Why a velocity break and NOT raw close < floor: floor hugs spot on a pinned day,
so close<floor whipsaws ~19x/day. A 1-minute velocity threshold fires only on a
genuine dealer-unwind cascade.

OPEX-day gate is HOLIDAY-SHIFT aware: monthly OPEX is the 3rd Friday, but when
that Friday is a market holiday OPEX rolls back to the prior trading day. 6/18 was
OPEX precisely because 6/19 is Juneteenth — the detector must arm on that shift.

Detector B (the OPEX-pin ARMING context gate: floor-compression + OI king/wall,
NOT charm) is intended to wrap this; A is the latency-killer, B is the context.
"""
from __future__ import annotations

import datetime
from collections import deque
from typing import Any

VELOCITY_THRESHOLD_PCT = 1.5      # 1-min drop magnitude that fires
WINDOW_SECONDS = 70               # rolling window; compare to price ~1 min ago
WINDOW_MIN_SECONDS = 50           # reference sample must be at least this old
COOLDOWN_SECONDS = 120            # one fire per ticker per cascade


# ── OPEX-day gate (holiday-shift aware) ──────────────────────────────

def _third_friday(year: int, month: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    first_fri = first + datetime.timedelta(days=(4 - first.weekday()) % 7)
    return first_fri + datetime.timedelta(weeks=2)


def opex_date(year: int, month: int) -> datetime.date:
    """Monthly OPEX date: 3rd Friday, rolled back to the prior trading day when
    that Friday is a market holiday (e.g. Jun 2026 -> 6/18 because 6/19 is
    Juneteenth)."""
    d = _third_friday(year, month)
    try:
        from .market_calendar import is_market_holiday
        while d.weekday() >= 5 or is_market_holiday(d):
            d -= datetime.timedelta(days=1)
    except Exception:
        pass
    return d


def is_opex_day(d: datetime.date | None = None) -> bool:
    d = d or datetime.date.today()
    return d == opex_date(d.year, d.month)


def is_quad_witch_day(d: datetime.date | None = None) -> bool:
    d = d or datetime.date.today()
    return d.month in (3, 6, 9, 12) and is_opex_day(d)


# ── Pure detector (backtest / validation) ────────────────────────────

def detect_velocity_breaks(
    closes: list[tuple[Any, float]],
    threshold_pct: float = VELOCITY_THRESHOLD_PCT,
    direction: str = "down",
) -> list[dict[str, Any]]:
    """Scan an aligned 1-minute close series for velocity breaks. `closes` is a
    list of (label, price). Returns one fire dict per qualifying close-to-close
    move. direction: 'down' (cascade, default) | 'up' | 'both'."""
    fires: list[dict[str, Any]] = []
    prev_label = prev = None
    for label, price in closes:
        if prev and prev > 0 and price:
            ret = (price / prev - 1) * 100
            hit = (
                (direction == "down" and ret <= -threshold_pct)
                or (direction == "up" and ret >= threshold_pct)
                or (direction == "both" and abs(ret) >= threshold_pct)
            )
            if hit:
                fires.append({
                    "label": label, "ret_pct": round(ret, 3),
                    "from": prev, "to": price,
                    "dir": "down" if ret < 0 else "up",
                })
        prev_label, prev = label, price
    return fires


# ── Live monitor (rolling fresh-spot window) ─────────────────────────

class OpexVelocityMonitor:
    """Stateful per-ticker monitor. Feed it fresh-spot samples; it fires once per
    cascade when price moves >= threshold within a ~1-minute rolling window, only
    on OPEX days. Bar-alignment-free — works at whatever cadence update() is
    called, using the oldest sample inside the [MIN, WINDOW] age band as the
    ~1-min-ago reference."""

    def __init__(self, threshold_pct: float = VELOCITY_THRESHOLD_PCT,
                 direction: str = "down"):
        self.threshold_pct = threshold_pct
        self.direction = direction
        self._samples: dict[str, deque] = {}
        self._last_fire_ts: dict[str, float] = {}

    def update(self, ticker: str, spot: float, ts: float,
               force_opex: bool | None = None) -> dict[str, Any] | None:
        """Push a (ts, spot) sample and return a fire dict or None. `force_opex`
        overrides the calendar gate (testing / replay of a known OPEX day)."""
        if not spot or spot <= 0:
            return None
        is_opex = force_opex if force_opex is not None else is_opex_day(
            datetime.date.fromtimestamp(ts))
        if not is_opex:
            return None

        tk = (ticker or "").upper()
        dq = self._samples.setdefault(tk, deque())
        dq.append((ts, spot))
        # evict samples older than the window
        while dq and ts - dq[0][0] > WINDOW_SECONDS:
            dq.popleft()

        # reference = oldest sample at least WINDOW_MIN_SECONDS old (~1 min ago)
        ref = None
        for s_ts, s_spot in dq:
            if ts - s_ts >= WINDOW_MIN_SECONDS:
                ref = (s_ts, s_spot)
                break
        if ref is None or not ref[1]:
            return None

        ret = (spot / ref[1] - 1) * 100
        hit = (
            (self.direction == "down" and ret <= -self.threshold_pct)
            or (self.direction == "up" and ret >= self.threshold_pct)
            or (self.direction == "both" and abs(ret) >= self.threshold_pct)
        )
        if not hit:
            return None
        # cooldown
        last = self._last_fire_ts.get(tk, 0.0)
        if ts - last < COOLDOWN_SECONDS:
            return None
        self._last_fire_ts[tk] = ts
        elapsed = ts - ref[0]
        return {
            "ticker": tk,
            "ret_pct": round(ret, 3),
            "from": round(ref[1], 4),
            "to": round(spot, 4),
            "window_s": round(elapsed, 1),
            "dir": "down" if ret < 0 else "up",
            "ts": ts,
            "kind": "OPEX_VELOCITY_BREAK",
        }


_MONITOR: OpexVelocityMonitor | None = None


def get_monitor() -> OpexVelocityMonitor:
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = OpexVelocityMonitor()
    return _MONITOR


# ── Live feed surface ────────────────────────────────────────────────
#
# Live SCOPE is indices only, deliberately. A −1.5%/min move is genuinely rare
# and unambiguous on an index (near-zero false positives — it IS a cascade), but
# common on single names as ordinary volatility. Single-name pin-breaks (the MRVL
# 6/18 case) need Detector B's arming context (floor-compression + OI wall) to
# separate a real break from noise; until B ships, standalone A on single names
# would be a noise faucet. The monitor/pure detector stay general so B + the
# backtests use them on any ticker.
VELOCITY_LIVE_TICKERS = {"SPY", "QQQ", "IWM", "DIA", "SPX", "NDX", "RUT"}


def maybe_fire(prices: dict[str, float], ts: float) -> list[dict[str, Any]]:
    """Feed the singleton monitor with the in-scope index prices and return any
    velocity-break fires. Cheap no-op off-OPEX. Never raises."""
    try:
        if not is_opex_day(datetime.date.fromtimestamp(ts)):
            return []
    except Exception:
        return []
    mon = get_monitor()
    # Detector B (opex_pin_detector) qualifies single names: an index is always
    # in scope (a −1.5%/min move there is unambiguous), but a single name fires
    # only when it is pin-ARMED (sandwiched in a tight long-gamma OPEX pin). Lazy
    # import avoids the A<->B cycle.
    try:
        from .opex_pin_detector import armed_details
    except Exception:
        armed_details = lambda _t, now=None: None  # noqa: E731
    fires: list[dict[str, Any]] = []
    for sym, px in (prices or {}).items():
        tk = (sym or "").upper()
        is_index = tk in VELOCITY_LIVE_TICKERS
        arm = None if is_index else armed_details(tk, ts)
        if not is_index and arm is None:
            continue
        try:
            f = mon.update(sym, float(px), ts, force_opex=True)
            if f:
                if arm:
                    f["pin_armed"] = True
                    f["call_wall"] = arm.get("call_wall")
                    f["floor"] = arm.get("floor")
                fires.append(f)
        except Exception:
            pass
    return fires


def format_fire(f: dict[str, Any]) -> str:
    """Telegram text for a velocity-break fire. Honest framing: this is a
    latency-killer (fires ON the move), not a forecast."""
    arrow = "🔻" if f.get("dir") == "down" else "🔺"
    head = "OPEX PIN-BREAK" if f.get("pin_armed") else "OPEX VELOCITY BREAK"
    lines = [
        f"{arrow} {head} — {f['ticker']}",
        f"{f['ret_pct']:+.2f}% in {f.get('window_s', 60):.0f}s "
        f"({f['from']:g} → {f['to']:g}), fresh spot",
    ]
    if f.get("pin_armed"):
        lines.append(
            f"Was pin-armed: floor {f.get('floor'):g} / call wall {f.get('call_wall'):g} "
            f"(long-gamma OPEX sandwich → cascade).")
    lines.append("Context, not a forecast — fires ON the move.")
    return "\n".join(lines)
