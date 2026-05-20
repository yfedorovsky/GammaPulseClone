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
import json
import os
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

# In-memory deque size — used for fire-time operations (cooldown context,
# Telegram format). API reads from sqlite (see ZERO_DTE_DB_PATH) so alerts
# survive server restarts. Was losing every alert on deploy before Apr 22.
HISTORY_SIZE = 200

# Dedicated sqlite file for 0DTE alert history (schema + path below).
ZERO_DTE_DB_PATH = os.environ.get("ZERO_DTE_DB_PATH", "./zero_dte_alerts.db")

ZERO_DTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS zero_dte_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id TEXT UNIQUE NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,
  grade TEXT NOT NULL,
  total_points REAL,
  max_points REAL,
  fired_at REAL NOT NULL,
  factors_json TEXT,
  spot REAL,
  king_pos REAL,
  king_neg REAL,
  target_level REAL,
  gex_signal TEXT,
  flow_regime TEXT,
  strike REAL,
  right TEXT,
  expiration TEXT,
  est_delta REAL,
  est_entry_price REAL,
  est_bid REAL,
  est_ask REAL,
  target_mid REAL,
  stop_mid REAL,
  target_r REAL,
  time_stop_minutes INTEGER,
  strike_quality TEXT,
  ticket_reasoning TEXT
);
CREATE INDEX IF NOT EXISTS idx_zero_dte_fired_at ON zero_dte_alerts(fired_at);
CREATE INDEX IF NOT EXISTS idx_zero_dte_ticker ON zero_dte_alerts(ticker, fired_at);
"""


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
_db_schema_ready = False


def get_cooldown_state() -> CooldownState:
    global _cooldown_state
    if _cooldown_state is None:
        _cooldown_state = CooldownState()
    return _cooldown_state


def _ensure_db_schema() -> None:
    """Idempotent — creates the zero_dte_alerts table if missing."""
    global _db_schema_ready
    if _db_schema_ready:
        return
    conn = sqlite3.connect(ZERO_DTE_DB_PATH)
    try:
        conn.executescript(ZERO_DTE_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _db_schema_ready = True


def _persist_alert(alert: "ZeroDTEAlert") -> None:
    """Write an alert to the persistent store. Best-effort — DB failures
    log a warning but never interrupt the fire path (Telegram already sent).

    May 2 2026: also writes annotation features (strike reachability,
    day-state, episode_id, tape_regime_at_fire) per cross-LLM round 5
    Tier-2 ship. Annotation compute is wrapped in try/except so any
    failure there doesn't block the core alert insert."""
    try:
        _ensure_db_schema()
        # Apply annotation-column migrations idempotently
        try:
            from .alert_annotations import apply_migrations as _apply_ann_mig
            _apply_ann_mig(ZERO_DTE_DB_PATH)
        except Exception:
            pass

        conn = sqlite3.connect(ZERO_DTE_DB_PATH)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO zero_dte_alerts (
                  alert_id, ticker, direction, grade, total_points, max_points,
                  fired_at, factors_json, spot, king_pos, king_neg, target_level,
                  gex_signal, flow_regime, strike, right, expiration, est_delta,
                  est_entry_price, est_bid, est_ask, target_mid, stop_mid,
                  target_r, time_stop_minutes, strike_quality, ticket_reasoning
                ) VALUES (
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?,
                  ?, ?, ?, ?
                )
                """,
                (
                    alert.alert_id, alert.ticker, alert.direction, alert.grade,
                    alert.total_points, alert.max_points,
                    alert.fired_at, json.dumps(alert.factors),
                    alert.spot, alert.king_pos, alert.king_neg, alert.target_level,
                    alert.gex_signal, alert.flow_regime,
                    alert.strike, alert.right, alert.expiration, alert.est_delta,
                    alert.est_entry_price, alert.est_bid, alert.est_ask,
                    alert.target_mid, alert.stop_mid,
                    alert.target_r, alert.time_stop_minutes,
                    alert.strike_quality, alert.ticket_reasoning,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Annotation features (May 2 2026 Tier-2 ship). Annotation only —
        # never affects fire decision. Wrap in try so failures don't
        # corrupt the alert pipeline.
        try:
            from .alert_annotations import annotate_alert
            ann = annotate_alert({
                "alert_id": alert.alert_id, "ticker": alert.ticker,
                "fired_at": alert.fired_at, "direction": alert.direction,
                "spot": alert.spot, "strike": alert.strike,
            })
            # Episode_id is computed across all alerts on the same day,
            # so we compute it as: ticker_dir_YYYYMMDD_episode (where
            # episode is the running count of distinct same-direction
            # episodes today). Best-effort; full re-compute via backfill
            # script periodically.
            ep_id = _compute_episode_id_for_alert(alert)
            ann["episode_id"] = ep_id

            conn = sqlite3.connect(ZERO_DTE_DB_PATH)
            try:
                cols = ", ".join(f"{k} = ?" for k in ann.keys())
                vals = list(ann.values()) + [alert.alert_id]
                conn.execute(
                    f"UPDATE zero_dte_alerts SET {cols} WHERE alert_id = ?",
                    vals,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[ZERO_DTE] annotation failed for {alert.alert_id}: {e}")
    except Exception as e:
        print(f"[ZERO_DTE] persist failed for {alert.alert_id}: {e}")


def _compute_episode_id_for_alert(alert: "ZeroDTEAlert") -> str:
    """Episode ID for a NEW alert: look at most recent same-(ticker,
    direction) alert today, see if it's within EPISODE_GAP_MAX_MIN
    (45min). If yes → reuse its episode_id; if no → new episode.

    Falls back to ep1 if anything goes wrong."""
    try:
        from .alert_annotations import EPISODE_GAP_MAX_MIN
        from datetime import datetime as _dt
        d = _dt.fromtimestamp(alert.fired_at)
        day_str = d.strftime("%Y%m%d")
        cutoff = alert.fired_at - EPISODE_GAP_MAX_MIN * 60
        conn = sqlite3.connect(ZERO_DTE_DB_PATH)
        try:
            cur = conn.execute(
                "SELECT episode_id FROM zero_dte_alerts WHERE ticker = ? "
                "AND direction = ? AND fired_at >= ? AND fired_at < ? "
                "AND alert_id != ? "
                "ORDER BY fired_at DESC LIMIT 1",
                (alert.ticker, alert.direction, cutoff,
                 alert.fired_at, alert.alert_id),
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
            # Otherwise count today's existing episodes for this (ticker, direction)
            cur = conn.execute(
                "SELECT COUNT(DISTINCT episode_id) FROM zero_dte_alerts "
                "WHERE ticker = ? AND direction = ? AND episode_id LIKE ? "
                "AND alert_id != ?",
                (alert.ticker, alert.direction,
                 f"{alert.ticker}_{alert.direction[:4]}_{day_str}_%",
                 alert.alert_id),
            )
            n_existing = cur.fetchone()[0] or 0
            ep_num = n_existing + 1
            return f"{alert.ticker}_{alert.direction[:4]}_{day_str}_ep{ep_num}"
        finally:
            conn.close()
    except Exception:
        return f"{alert.ticker}_{alert.direction[:4]}_unknown_ep1"


def load_alerts_from_db(limit: int = 50, ticker: str | None = None) -> list[dict[str, Any]]:
    """Return recent alerts from sqlite, newest first. Used by the
    /api/zero-dte/alerts handler so history survives server restarts."""
    try:
        _ensure_db_schema()
        conn = sqlite3.connect(ZERO_DTE_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if ticker:
                cur = conn.execute(
                    "SELECT * FROM zero_dte_alerts WHERE ticker=? "
                    "ORDER BY fired_at DESC LIMIT ?",
                    (ticker.upper(), limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM zero_dte_alerts "
                    "ORDER BY fired_at DESC LIMIT ?",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"[ZERO_DTE] load failed: {e}")
        return []

    # Normalize to the same shape as ZeroDTEAlert.to_row() so the UI can
    # consume either source interchangeably.
    out: list[dict[str, Any]] = []
    for r in rows:
        factors: list[dict[str, Any]] = []
        fj = r.get("factors_json")
        if fj:
            try:
                factors = json.loads(fj)
            except Exception:
                factors = []
        fired_at = r.get("fired_at") or 0
        out.append({
            "alert_id": r.get("alert_id"),
            "ticker": r.get("ticker"),
            "direction": r.get("direction"),
            "grade": r.get("grade"),
            "total_points": r.get("total_points"),
            "max_points": r.get("max_points"),
            "fired_at": fired_at,
            "fired_at_iso": (
                dt.datetime.utcfromtimestamp(fired_at).isoformat() + "Z"
                if fired_at else None
            ),
            "factors": factors,
            "spot": r.get("spot"),
            "king_pos": r.get("king_pos"),
            "king_neg": r.get("king_neg"),
            "target_level": r.get("target_level"),
            "gex_signal": r.get("gex_signal"),
            "flow_regime": r.get("flow_regime"),
            "strike": r.get("strike"),
            "right": r.get("right"),
            "expiration": r.get("expiration"),
            "est_delta": r.get("est_delta"),
            "est_entry_price": r.get("est_entry_price"),
            "est_bid": r.get("est_bid"),
            "est_ask": r.get("est_ask"),
            "target_mid": r.get("target_mid"),
            "stop_mid": r.get("stop_mid"),
            "target_r": r.get("target_r"),
            "time_stop_minutes": r.get("time_stop_minutes"),
            "strike_quality": r.get("strike_quality"),
            "ticket_reasoning": r.get("ticket_reasoning"),
        })
    return out


def get_alert_history() -> deque[ZeroDTEAlert]:
    """Return the in-memory deque. Used at fire time only — API reads
    from sqlite via load_alerts_from_db() so it survives restarts."""
    global _alert_history
    if _alert_history is None:
        _alert_history = deque(maxlen=HISTORY_SIZE)
    return _alert_history


# ── Sweep / Golden context pulls ──────────────────────────────────


def _recent_sweeps_for_ticker(ticker: str, seconds: int = 120) -> list[dict[str, Any]]:
    """Query flow_alerts table in snapshots.db for recent flows on a ticker.

    Bug fix 2026-05-20: previously pointed at `./flow_alerts.db` (which is
    empty — flow_alerts data lives in snapshots.db) AND used column 'time'
    which doesn't exist (real column is 'ts' epoch float). Both bugs caused
    sweep score = 0 for every ticker, every cycle, since the loop launched.
    """
    from .config import get_settings
    settings = get_settings()
    db_path = getattr(settings, "snapshot_db", None) or "./snapshots.db"
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        since_epoch = time.time() - seconds
        cur.execute(
            "SELECT * FROM flow_alerts WHERE ticker=? AND ts > ? "
            "ORDER BY ts DESC LIMIT 50",
            (ticker.upper(), since_epoch),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        # Once-per-loop log so the next bug doesn't disappear silently
        print(f"[ZERO_DTE] sweep query failed for {ticker}: {e}")
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

    # 11. Record — in-memory deque for fire-time ops, sqlite for durability
    cd.mark(ev.ticker, ev.direction, ev.grade)
    get_alert_history().append(alert)
    _persist_alert(alert)

    # Performance database (2026-05-20)
    try:
        from .alert_outcomes import log_alert
        log_alert(
            alert_type=f"ZERO_DTE_{alert.grade.replace('+','P')}",
            ticker=alert.ticker,
            fired_at=alert.fired_at,
            direction="BULL" if alert.direction == "bullish" else "BEAR",
            grade=alert.grade,
            score=alert.total_points,
            strike=alert.strike,
            expiration=alert.expiration,
            option_type=(alert.right or "").lower(),
            dte=0,
            spot_at_alert=alert.spot,
            entry_price=alert.est_entry_price,
            target_premium=alert.target_mid,
            stop_premium=alert.stop_mid,
            gex_signal=alert.gex_signal,
            king=alert.king_pos,
            floor=alert.king_neg,
            raw_alert=alert.to_row(),
        )
    except Exception as e:
        print(f"[alert_outcomes] zero_dte log failed: {e}")
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
            # Snapshot of what each ticker scored this cycle — used by
            # the silence-detector heartbeat below. Lets us SEE that
            # evaluation is happening even when nothing crosses B+.
            cycle_scores: dict[str, dict[str, Any]] = {}
            for ticker in TRACKED_TICKERS:
                try:
                    alert = await _eval_and_maybe_fire(ticker)
                    if alert:
                        cycle_scores[ticker] = {
                            "fired": True, "grade": alert.grade,
                            "direction": alert.direction,
                        }
                except Exception as e:
                    print(f"[zero_dte] {ticker} eval error: {e}")
            cycles += 1
            # Heartbeat every 5 min: report stats + RTH activity. If we go
            # 30 min with zero fires AND scores stayed sub-B+, that's a
            # signal something is structurally suppressed (the original
            # 6-day silence was missed because there were no diagnostics).
            if cycles % 30 == 0:
                cd = get_cooldown_state()
                last_hour_fires = cd.fires  # approx; lifetime counter
                _hb = (
                    f"[zero_dte] heartbeat — cycle={cycles} {cd.stats()}"
                )
                print(_hb)
        except Exception as e:
            print(f"[zero_dte] loop error: {e}")

    print(f"[zero_dte] loop stopped — cooldown state: {get_cooldown_state().stats()}")
