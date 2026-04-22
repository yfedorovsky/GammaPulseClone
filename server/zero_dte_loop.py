"""0DTE alert loop — runs evaluate() every N seconds across SPY/SPX/QQQ/IWM,
builds trade tickets on qualifying grades, fires Telegram + stores history.

## Loop cadence

Every EVAL_INTERVAL_S seconds (default 10s):
  1. Pull current GEX state from cache for each tracked ticker
  2. Pull fast-flow snapshot from FastTickNetFlowAggregator
  3. Pull regime from NetFlowAggregator + regime_summary
  4. Pull recent sweeps from flow_alerts DB (last 2 min)
  5. Pull recent Goldens from live_flow_aggregator telemetry
  6. Call evaluate() → ConfluenceEval
  7. If grade ≥ MIN_TELEGRAM_GRADE and cooldown elapsed:
       - Pick strike via zero_dte_strikes.pick_zero_dte_strike
       - Plan exit via plan_exit_levels
       - Format Telegram message + send
       - Store alert record for /api/zero-dte/alerts endpoint
  8. Store evaluation in history ring-buffer regardless (for UI display)

## Cooldown logic

Per (ticker, direction, grade_tier): grade-tier dedupe means a B+ fire
doesn't block a subsequent A or A+ fire. That's intentional — if a setup
strengthens, we want to re-alert with the upgrade.

Tiers: {'A+': 3, 'A': 2, 'B+': 1, 'B': 0, 'C': -1}
Cooldown applies if: tier ≤ last_fired_tier AND age < COOLDOWN_S
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# ── Configuration ─────────────────────────────────────────────────

EVAL_INTERVAL_S = 10
COOLDOWN_S = 600  # 10 minutes

# Tiers used for cooldown-override logic
TIER_RANK = {"A+": 3, "A": 2, "B+": 1, "B": 0, "C": -1}
MIN_TELEGRAM_TIER = 1   # B+ or better triggers Telegram

# How many past evals to keep in memory for the UI endpoint
HISTORY_SIZE = 200


# ── Data structures ───────────────────────────────────────────────


@dataclass
class ZeroDTEAlert:
    """A fired 0DTE alert with full trade ticket."""
    alert_id: str             # epoch_ms + ticker + dir (for dedup in UI)
    ticker: str
    direction: str            # 'bullish' | 'bearish'
    grade: str
    total_points: int
    max_points: int
    fired_at: float           # epoch seconds

    # Evaluation snapshot
    factors: list[dict[str, Any]] = field(default_factory=list)
    spot: float | None = None
    king_pos: float | None = None
    king_neg: float | None = None
    target_level: float | None = None
    gex_signal: str | None = None
    flow_regime: str | None = None

    # Trade ticket
    strike: float | None = None
    right: str | None = None
    expiration: str | None = None
    est_delta: float | None = None
    est_entry_price: float | None = None   # mid quote at fire time
    est_bid: float | None = None
    est_ask: float | None = None
    target_mid: float | None = None
    stop_mid: float | None = None
    target_r: float | None = None
    time_stop_minutes: int = 90
    strike_quality: str = "unknown"
    ticket_reasoning: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "ticker": self.ticker,
            "direction": self.direction,
            "grade": self.grade,
            "total_points": self.total_points,
            "max_points": self.max_points,
            "fired_at": self.fired_at,
            "fired_at_iso": (
                dt.datetime.utcfromtimestamp(self.fired_at).isoformat() + "Z"
                if self.fired_at else None
            ),
            "factors": self.factors,
            "spot": self.spot,
            "king_pos": self.king_pos,
            "king_neg": self.king_neg,
            "target_level": self.target_level,
            "gex_signal": self.gex_signal,
            "flow_regime": self.flow_regime,
            "strike": self.strike,
            "right": self.right,
            "expiration": self.expiration,
            "est_delta": self.est_delta,
            "est_entry_price": self.est_entry_price,
            "est_bid": self.est_bid,
            "est_ask": self.est_ask,
            "target_mid": self.target_mid,
            "stop_mid": self.stop_mid,
            "target_r": self.target_r,
            "time_stop_minutes": self.time_stop_minutes,
            "strike_quality": self.strike_quality,
            "ticket_reasoning": self.ticket_reasoning,
        }


# ── Cooldown state ────────────────────────────────────────────────


class CooldownState:
    """Per-(ticker, direction) last-fired tracking for grade-tier cooldown."""

    def __init__(self):
        # (ticker, direction) → (last_tier, last_fired_epoch)
        self._last: dict[tuple[str, str], tuple[int, float]] = {}
        self.fires = 0
        self.suppressed = 0
        self.suppressed_low_grade = 0

    def should_fire(self, ticker: str, direction: str, grade: str) -> bool:
        tier = TIER_RANK.get(grade, -1)
        if tier < MIN_TELEGRAM_TIER:
            self.suppressed_low_grade += 1
            return False
        now = time.time()
        key = (ticker, direction)
        last = self._last.get(key)
        if last is None:
            return True
        last_tier, last_ts = last
        age = now - last_ts
        if age > COOLDOWN_S:
            return True
        # Within cooldown — only fire if grade upgraded
        if tier > last_tier:
            return True
        self.suppressed += 1
        return False

    def mark(self, ticker: str, direction: str, grade: str) -> None:
        tier = TIER_RANK.get(grade, -1)
        self._last[(ticker, direction)] = (tier, time.time())
        self.fires += 1

    def stats(self) -> dict[str, Any]:
        return {
            "fires": self.fires,
            "suppressed": self.suppressed,
            "suppressed_low_grade": self.suppressed_low_grade,
            "active_keys": len(self._last),
            "last_by_key": {
                f"{k[0]}:{k[1]}": {"tier": v[0], "age_s": round(time.time() - v[1], 1)}
                for k, v in self._last.items()
            },
        }


_cooldown_state: CooldownState | None = None
_alert_history: deque[ZeroDTEAlert] | None = None


def get_cooldown_state() -> CooldownState:
    global _cooldown_state
    if _cooldown_state is None:
        _cooldown_state = CooldownState()
    return _cooldown_state


def get_alert_history() -> deque[ZeroDTEAlert]:
    global _alert_history
    if _alert_history is None:
        _alert_history = deque(maxlen=HISTORY_SIZE)
    return _alert_history


# ── Sweep / Golden context pulls ──────────────────────────────────


def _recent_sweeps_for_ticker(ticker: str, seconds: int = 120) -> list[dict[str, Any]]:
    """Query flow_alerts DB for recent sweeps on a ticker. Returns list of
    dicts with at minimum ts, option_type, sweep_notional."""
    from .config import get_settings
    settings = get_settings()
    try:
        db_path = getattr(settings, "flow_alerts_db", None) or getattr(settings, "alert_db_path", None)
        if not db_path:
            # Fallback to known path
            db_path = "./flow_alerts.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        since_iso = (dt.datetime.utcnow() - dt.timedelta(seconds=seconds)).isoformat()
        cur.execute(
            "SELECT * FROM flow_alerts WHERE ticker=? AND time > ? ORDER BY time DESC LIMIT 50",
            (ticker.upper(), since_iso),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        # Normalize ts key
        for r in rows:
            r["ts"] = r.get("time") or r.get("fired_at") or r.get("ts")
        return rows
    except Exception:
        return []


def _recent_goldens_for_ticker(ticker: str, seconds: int = 300) -> list[dict[str, Any]]:
    """Query flow_daily for recent GOLDEN-classified flows on a ticker."""
    try:
        from .option_flow_daily import get_golden_flow
        today = dt.date.today().isoformat()
        goldens = get_golden_flow(since_date=today, ticker=ticker.upper(), limit=50)
        # Attach ts field for freshness check — use 'date' + 'hour' approximation
        # (we don't have exact fire-time per-row in flow_daily, so use "now" as
        # freshness sentinel meaning "if classifier currently returns as golden,
        # it's fresh enough"). Not ideal — refine later with explicit timestamps.
        for g in goldens:
            g["ts"] = time.time()
        return goldens
    except Exception:
        return []


# ── Main eval + fire ──────────────────────────────────────────────


async def _eval_and_maybe_fire(
    ticker: str,
) -> ZeroDTEAlert | None:
    """One full eval pass for one ticker. Returns ZeroDTEAlert if fired."""
    from .cache import cache
    from .net_flow_fast import get_fast_net_flow_aggregator, snapshot_fast_flow
    from .net_flow import get_net_flow_aggregator
    from .net_flow_signals import regime_summary
    from .zero_dte_engine import evaluate
    from .zero_dte_strikes import pick_zero_dte_strike, plan_exit_levels

    # 1. GEX state
    try:
        snap = await cache.snapshot()
    except Exception:
        snap = {}
    gex_state = snap.get(ticker) or snap.get("SPX" if ticker == "SPX" else ticker) or {}

    # SPX special-case: in some setups the aggregated state lives under 'SPX'
    # while trades come through SPXW subscriptions. Fall back to the fast
    # aggregator's price if needed.
    if not gex_state and ticker == "SPX":
        gex_state = snap.get("SPXW") or {}

    # 2. Fast-flow snapshot
    fast_agg = get_fast_net_flow_aggregator()
    fast_snap = snapshot_fast_flow(fast_agg, ticker)

    # 3. Regime (from main net-flow aggregator)
    main_agg = get_net_flow_aggregator()
    regime_bars = main_agg.series(ticker, minutes=240)
    reg = regime_summary(regime_bars) if regime_bars else {}

    # 4. Recent sweeps + goldens
    sweeps = _recent_sweeps_for_ticker(ticker)
    goldens = _recent_goldens_for_ticker(ticker)

    # 5. Evaluate
    ev = evaluate(
        ticker=ticker,
        gex_state=gex_state,
        fast_flow_snap=fast_snap,
        regime=reg.get("regime"),
        regime_confidence=reg.get("confidence"),
        recent_sweeps=sweeps,
        recent_goldens=goldens,
    )

    if ev.direction is None:
        return None

    # 6. Cooldown / grade gate
    cd = get_cooldown_state()
    if not cd.should_fire(ev.ticker, ev.direction, ev.grade):
        return None

    # 7. Pick strike
    raw_chain: list[dict[str, Any]] = []
    try:
        # Flatten all expirations' raw contracts for the picker's quote map
        raw_by_exp = gex_state.get("_raw_contracts") or {}
        for exp, contracts in raw_by_exp.items():
            for c in contracts:
                c2 = dict(c)
                c2["expiration_date"] = exp
                raw_chain.append(c2)
    except Exception:
        pass

    exps = gex_state.get("exps") or []

    strike_choice = pick_zero_dte_strike(
        ticker=ticker,
        direction=ev.direction,
        spot=ev.spot or 0,
        available_exps=exps,
        raw_chain=raw_chain,
        target_price=ev.target_level,
    )
    if strike_choice is None:
        return None

    # 8. Plan exit
    entry_price = strike_choice.mid_price or strike_choice.ask or 1.0
    exit_plan = plan_exit_levels(
        entry_price=entry_price,
        direction=ev.direction,
        spot=ev.spot or 0,
        target_price=ev.target_level,
        est_delta=strike_choice.est_delta,
    )

    # 9. Build alert record
    alert_id = f"{int(ev.eval_ts * 1000)}_{ticker}_{ev.direction[:3]}"
    alert = ZeroDTEAlert(
        alert_id=alert_id,
        ticker=ticker,
        direction=ev.direction,
        grade=ev.grade,
        total_points=ev.total_points,
        max_points=ev.max_points,
        fired_at=ev.eval_ts,
        factors=[{"name": f.name, "points": f.points, "reasoning": f.reasoning} for f in ev.factors],
        spot=ev.spot,
        king_pos=ev.king_pos,
        king_neg=ev.king_neg,
        target_level=ev.target_level,
        gex_signal=ev.gex_signal,
        flow_regime=ev.flow_regime,
        strike=strike_choice.strike,
        right=strike_choice.right,
        expiration=strike_choice.expiration,
        est_delta=strike_choice.est_delta,
        est_entry_price=entry_price,
        est_bid=strike_choice.bid,
        est_ask=strike_choice.ask,
        target_mid=exit_plan["target_mid"],
        stop_mid=exit_plan["stop_mid"],
        target_r=exit_plan["target_r"],
        time_stop_minutes=exit_plan["time_stop_minutes"],
        strike_quality=strike_choice.quality,
        ticket_reasoning=strike_choice.reasoning,
    )

    # 10. Telegram (see zero_dte_telegram.py)
    try:
        from .zero_dte_telegram import send_zero_dte_alert
        asyncio.create_task(send_zero_dte_alert(alert))
    except Exception as e:
        print(f"[ZERO_DTE] telegram send failed: {e}")

    # 11. Record
    cd.mark(ev.ticker, ev.direction, ev.grade)
    get_alert_history().append(alert)
    print(
        f"[ZERO_DTE] {alert.grade} {alert.direction.upper()} {ticker} "
        f"{strike_choice.strike}{strike_choice.right[0].upper()} "
        f"exp={strike_choice.expiration} "
        f"entry=${entry_price:.2f} target=${exit_plan['target_mid']:.2f} "
        f"stop=${exit_plan['stop_mid']:.2f} ({ev.total_points}/20)"
    )
    return alert


# ── Main loop ─────────────────────────────────────────────────────


async def run_zero_dte_loop(stop_event: asyncio.Event) -> None:
    """Periodic evaluator for all TRACKED_TICKERS."""
    from .zero_dte_engine import TRACKED_TICKERS

    print(
        f"[zero_dte] loop starting — interval={EVAL_INTERVAL_S}s "
        f"tickers={TRACKED_TICKERS} cooldown={COOLDOWN_S}s"
    )
    cycles = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=EVAL_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

        try:
            for ticker in TRACKED_TICKERS:
                try:
                    await _eval_and_maybe_fire(ticker)
                except Exception as e:
                    print(f"[zero_dte] {ticker} eval error: {e}")
            cycles += 1
            if cycles % 30 == 0:  # heartbeat every 5 min
                cd = get_cooldown_state()
                print(f"[zero_dte] heartbeat — {cd.stats()}")
        except Exception as e:
            print(f"[zero_dte] loop error: {e}")

    print(f"[zero_dte] loop stopped — cooldown state: {get_cooldown_state().stats()}")
