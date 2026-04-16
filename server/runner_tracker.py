"""Runner Tracker — multi-day explosive breakout state machine.

Overlays the swing scanner to detect and track 8-15%+ moves over 2-4 days.
States: DAY1_BREAKOUT -> DAY2_CONFIRM -> DAY3_EXPLOSION -> DONE

Pure consumer of swing scanner output + quotes_full OHLC data.
Does NOT modify swing scanner scoring, gates, or ranking.
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings
from .cache import cache
from .snapshots import get_daily_closes

# Reclaim universe: TIER_1 megacaps + hand-picked high-activity names that
# frequently stage V-bottom reclaim setups. Kept separate from tickers.TIER_1
# so changes here don't affect worker scan tiering or other systems.
# Add names here as the user identifies them (Mir basket favorites, etc.).
RECLAIM_EXTRA_TICKERS: set[str] = {
    # Semis / AI infrastructure (Mir basket)
    "MRVL",   # added 2026-04-16 after Apr 13-15 swing watchlist appearance
    "CRDO",   # AI infra / data center optics
    "COHR",   # photonics
    "AXTI",   # photonics / substrates
    # Space / National Security (Mir 2026 themes)
    "RKLB",   # Rocket Lab
    "ASTS",   # AST SpaceMobile
    # Nuclear / energy (Mir 2026 theme)
    "OKLO",   # small modular reactors
}

# ── Schema ────────────────────────────────────────────────────────────

RUNNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS runner_tracker (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'DAY1_BREAKOUT',
    entry_ts        INTEGER NOT NULL,
    entry_date      TEXT NOT NULL,
    entry_path      TEXT DEFAULT 'SWING',  -- SWING | RECLAIM
    swing_score     REAL,
    rts_score       REAL,
    ivp             REAL,
    dist_to_high    REAL,
    -- Day 1 OHLCV
    d1_date  TEXT, d1_open REAL, d1_high REAL, d1_low REAL, d1_close REAL,
    d1_volume INTEGER, d1_rvol REAL, d1_gain_pct REAL,
    -- Day 2 OHLCV
    d2_date  TEXT, d2_open REAL, d2_high REAL, d2_low REAL, d2_close REAL,
    d2_volume INTEGER, d2_rvol REAL, d2_gap_pct REAL,
    -- Day 3 OHLCV
    d3_date  TEXT, d3_open REAL, d3_high REAL, d3_low REAL, d3_close REAL,
    d3_volume INTEGER, d3_rvol REAL, d3_gap_pct REAL,
    -- Aggregates
    total_gain_pct       REAL DEFAULT 0,
    consecutive_2pct_days INTEGER DEFAULT 0,
    runner_score         REAL DEFAULT 0,
    -- Runner shape (classification at Day 1 entry; ChatGPT v2 feedback)
    runner_shape   TEXT,            -- MEASURED | SQUEEZE
    adr_at_entry   REAL,            -- snapshot of 14-day ADR% at entry; used for ADR-relative grace band
    -- Completion
    done_ts     INTEGER,
    done_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_rt_ticker_state ON runner_tracker(ticker, state);
CREATE INDEX IF NOT EXISTS idx_rt_state ON runner_tracker(state);
"""

# ── In-memory state ───────────────────────────────────────────────────

_runners: dict[str, dict[str, Any]] = {}  # ticker -> live runner state
_last_date: str = ""

# ── DB helpers (same pattern as paper_trading.py) ─────────────────────


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_runner_db() -> None:
    """Create table + reload active runners from prior session."""
    with _conn() as c:
        c.executescript(RUNNER_SCHEMA)
        # Migration: add entry_path for installs predating the reclaim feature.
        # Pattern from paper_trading.py — safe if column already exists.
        for col, ddl in [
            ("entry_path", "ALTER TABLE runner_tracker ADD COLUMN entry_path TEXT DEFAULT 'SWING'"),
            ("runner_shape", "ALTER TABLE runner_tracker ADD COLUMN runner_shape TEXT"),
            ("adr_at_entry", "ALTER TABLE runner_tracker ADD COLUMN adr_at_entry REAL"),
        ]:
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
    _load_active_runners()


def _load_active_runners() -> None:
    """Restore runners not yet DONE from SQLite into memory."""
    global _last_date
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runner_tracker WHERE state != 'DONE' ORDER BY entry_ts"
        ).fetchall()
    for r in rows:
        _runners[r["ticker"]] = dict(r)
    if rows:
        print(f"[runner_tracker] Restored {len(rows)} active runner(s)")
    _last_date = _today()


# ── Helpers ───────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.date.today().isoformat()


def _is_weekday() -> bool:
    return datetime.date.today().weekday() < 5


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    m = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * m + e * (1 - m)
    return e


def _adr_from_closes(closes: list[float]) -> float:
    """14-day close-to-close average daily range as percentage.
    Fallback 2.5% if insufficient data."""
    if len(closes) < 15:
        return 2.5
    abs_returns = [
        abs(closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(-14, 0) if closes[i - 1] > 0
    ]
    return sum(abs_returns) / len(abs_returns) if abs_returns else 2.5


def _classify_shape(d1_rvol: float, d1_high: float, d1_low: float, d1_close: float, adr_pct: float) -> str:
    """MEASURED vs SQUEEZE classifier (per ChatGPT v2 feedback).

    SQUEEZE if Day 1 RVOL > 1.5x AND Day 1 range > 1.5x ADR.
    Otherwise MEASURED.
    """
    if d1_close <= 0 or adr_pct <= 0:
        return "MEASURED"
    day_range_pct = (d1_high - d1_low) / d1_close * 100
    if d1_rvol > 1.5 and day_range_pct > 1.5 * adr_pct:
        return "SQUEEZE"
    return "MEASURED"


def _cooldown_days(done_reason: str) -> int:
    """Outcome-aware cooldown: completed runners can reset fast,
    failed ones need longer to avoid re-triggering the same chop pocket."""
    return 5 if done_reason == "COMPLETED" else 10


def _has_recent_done(ticker: str) -> bool:
    """Check cooldown window. Fetches most recent DONE record for ticker
    and applies outcome-aware cooldown length."""
    with _conn() as c:
        row = c.execute(
            "SELECT done_ts, done_reason FROM runner_tracker "
            "WHERE ticker = ? AND state = 'DONE' "
            "ORDER BY done_ts DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    if not row or not row["done_ts"]:
        return False
    days = _cooldown_days(row["done_reason"] or "")
    return row["done_ts"] > int(time.time()) - days * 86400


def _check_reclaim_entry(ticker: str, state: dict, today: str) -> dict | None:
    """Detect V-bottom reclaim: mega-cap / watchlist name closing above EMA21
    after being below it recently, on rising volume.

    Returns a pre-built runner dict if the ticker qualifies, else None.

    Gates (aligned with user's documented MSFT-style Day 1 entry):
      - Ticker in RECLAIM_UNIVERSE (TIER_1 + hand-picked extras)
      - Close > EMA21 today AND close <= EMA21 in any of last 3 sessions
      - Daily gain >= max(1.5%, 0.6 * ADR%)
      - RVOL >= 1.1x (matches user's X thread spec — MSFT Apr 13 was 1.13x)
      - Close quality: top 35% of day's range OR close > prior day close
        (this is the real chop filter — low-vol reclaims that fade into close
        will fail here; genuine breakouts closing near highs will pass)
      - No earnings blackout
      - Outcome-aware cooldown: 5d for COMPLETED, 10d for failed
    """
    try:
        from .tickers import TIER_1
    except ImportError:
        return None
    reclaim_universe = set(TIER_1) | RECLAIM_EXTRA_TICKERS
    if ticker not in reclaim_universe:
        return None

    spot = state.get("actual_spot") or state.get("_spot") or 0
    prevclose = state.get("_prevclose") or 0
    if not spot or not prevclose:
        return None

    pct_change = (spot - prevclose) / prevclose * 100
    avg_vol = max(state.get("_avg_volume") or 1, 1)
    today_vol = state.get("_today_volume") or 0
    rvol = today_vol / avg_vol

    if rvol < 1.1:
        return None

    closes = get_daily_closes(ticker, 30)
    if len(closes) < 22:
        return None

    ema21_today = _ema(closes, 21)
    if spot <= ema21_today:
        return None

    # Fresh reclaim: below EMA21 in any of last 3 sessions
    recent_3 = closes[-3:] if len(closes) >= 3 else closes
    ema_for_recent = [_ema(closes[: -i] if i else closes, 21) for i in (3, 2, 1)]
    below_recently = any(c <= e for c, e in zip(recent_3, ema_for_recent))
    if not below_recently:
        return None

    # ADR + gain gate (aligned with SWING path: 1.5% floor)
    adr_pct = _adr_from_closes(closes)
    min_gain_reclaim = max(1.5, 0.6 * adr_pct)
    if pct_change < min_gain_reclaim:
        return None

    # Close quality: top 35% of day's range.
    # This is the REAL chop filter. A genuine breakout on 1.1x volume still
    # closes strong (MSFT Apr 13 closed at 98.8% of range); a failed reclaim
    # in chop tags EMA21 mid-day and fades into close (close_pct < 0.65).
    #
    # Note: we previously OR'd in "close > prior day close" but that's
    # redundant — any gain passing the 1.5% gate is trivially above prior
    # close, making the OR leg always TRUE and the gate toothless.
    d1_high = state.get("_today_high") or spot
    d1_low = state.get("_today_low") or spot
    day_range = d1_high - d1_low
    close_pct = (spot - d1_low) / day_range if day_range > 0 else 1.0
    if close_pct < 0.65:
        return None

    # Earnings blackout
    try:
        from .signals import _earnings_blackout_cache
        _, bo_set = _earnings_blackout_cache
        if ticker in bo_set:
            return None
    except Exception:
        pass

    # Outcome-aware cooldown (5d completed, 10d failed)
    if _has_recent_done(ticker):
        return None

    shape = _classify_shape(rvol, d1_high, d1_low, spot, adr_pct)

    return {
        "ticker": ticker,
        "state": "DAY1_BREAKOUT",
        "entry_ts": int(time.time()),
        "entry_date": today,
        "entry_path": "RECLAIM",
        "runner_shape": shape,
        "adr_at_entry": round(adr_pct, 2),
        "swing_score": None,
        "rts_score": None,
        "ivp": state.get("_ivp"),
        "dist_to_high": None,
        "d1_date": today,
        "d1_open": state.get("_today_open") or prevclose,
        "d1_high": d1_high,
        "d1_low": d1_low,
        "d1_close": spot,
        "d1_volume": today_vol,
        "d1_rvol": round(rvol, 2),
        "d1_gain_pct": round(pct_change, 2),
        "total_gain_pct": round(pct_change, 2),
        "consecutive_2pct_days": 1,
    }


def _candle_body_ratio(open_: float, high: float, low: float, close: float) -> float:
    """Fraction of candle that is body (0-1). 1.0 = marubozu."""
    rng = high - low
    if rng <= 0:
        return 0.0
    return abs(close - open_) / rng


def _compute_runner_score(runner: dict) -> float:
    """10-factor score (0-20). Only factors with data are scored."""
    score = 0.0

    # 1. Pullback quality (dist_to_high_pct at entry)
    dth = runner.get("dist_to_high") or 99
    score += 2 if dth < 3 else (1 if dth < 8 else 0)

    # 2. Volume dry-up before breakout (approximated: d1 is breakout day,
    #    so if d1_rvol is high relative to recent, the "dry-up" happened before)
    #    We use avg_volume availability — if d1_rvol >= 1.5 it implies prior was quiet
    d1_rvol = runner.get("d1_rvol") or 0
    score += 2 if d1_rvol >= 1.5 else (1 if d1_rvol >= 1.1 else 0)

    # 3. Breakout volume (same metric, higher bar)
    score += 2 if d1_rvol >= 2.0 else (1 if d1_rvol >= 1.3 else 0)

    # 4. MA reclaim — swing scanner gate guarantees price > EMA21 > SMA50
    score += 2

    # 5. Gap-up Day 2
    d2_gap = runner.get("d2_gap_pct")
    if d2_gap is not None:
        score += 2 if d2_gap >= 1.5 else (1 if d2_gap >= 0 else 0)
    else:
        score += 1  # neutral if Day 2 hasn't happened

    # 6. Volume expansion Day 2+
    d1_vol = runner.get("d1_volume") or 0
    d2_vol = runner.get("d2_volume") or 0
    if d1_vol and d2_vol:
        ratio = d2_vol / d1_vol
        score += 2 if ratio >= 1.0 else (1 if ratio >= 0.8 else 0)
    else:
        score += 1

    # 7. Thematic catalyst — can't automate, default 1
    score += 1

    # 8. Candle body ratio (best available day)
    best_body = 0.0
    for prefix in ("d1", "d2", "d3"):
        o = runner.get(f"{prefix}_open")
        h = runner.get(f"{prefix}_high")
        lo = runner.get(f"{prefix}_low")
        cl = runner.get(f"{prefix}_close")
        if all(v is not None and v > 0 for v in (o, h, lo, cl)):
            best_body = max(best_body, _candle_body_ratio(o, h, lo, cl))
    score += 2 if best_body >= 0.7 else (1 if best_body >= 0.4 else 0)

    # 9. Consecutive 2%+ days
    consec = runner.get("consecutive_2pct_days") or 0
    score += 2 if consec >= 3 else (1 if consec >= 2 else 0)

    # 10. Options IV (low IVP = move not priced in)
    ivp = runner.get("ivp")
    if ivp is not None:
        score += 2 if ivp < 30 else (1 if ivp < 50 else 0)
    else:
        score += 1

    return round(score, 1)


# ── Telegram alerts ───────────────────────────────────────────────────


async def _alert_transition(ticker: str, new_state: str, runner: dict) -> None:
    """Send Telegram on state transitions. force=True (rare, high-value event)."""
    try:
        from .telegram import send
    except ImportError:
        return

    gain = runner.get("total_gain_pct") or runner.get("d1_gain_pct") or 0
    score = runner.get("runner_score") or 0
    rvol = runner.get("d1_rvol") or 0

    if new_state == "DAY1_BREAKOUT":
        path = runner.get("entry_path", "SWING")
        path_tag = "[V-RECLAIM]" if path == "RECLAIM" else "[SWING]"
        shape = runner.get("runner_shape", "MEASURED")
        swing_s = runner.get("swing_score")
        rts_s = runner.get("rts_score")
        meta_line = ""
        if swing_s is not None and rts_s is not None:
            meta_line = f"SwingScore: {swing_s:.0f} | RTS: {rts_s:.0f}\n"
        # Shape-specific guidance (per ChatGPT v2: SQUEEZE needs different monetization)
        if shape == "SQUEEZE":
            shape_line = (
                f"Shape: SQUEEZE (high-conviction detonation)\n"
                f"Mir rule: harvest 25-50% at close — Day 1 often IS the move.\n"
            )
        else:
            shape_line = f"Shape: MEASURED (multi-day stair-step)\n"
        text = (
            f"🏃 RUNNER DAY 1 {path_tag}: ${ticker}\n"
            f"Gain: +{gain:.1f}% | RVOL: {rvol:.1f}x\n"
            f"{meta_line}"
            f"{shape_line}"
            f"Runner Score: {score:.0f}/20"
        )
    elif new_state == "DAY2_CONFIRM":
        gap = runner.get("d2_gap_pct") or 0
        text = (
            f"🏃🏃 RUNNER DAY 2: ${ticker}\n"
            f"Total: +{gain:.1f}% | Gap: +{gap:.1f}%\n"
            f"Runner Score: {score:.0f}/20\n"
            f"Mir rule: take 1/3 profit at open, watch VWAP pullback for add"
        )
    elif new_state == "DAY3_EXPLOSION":
        text = (
            f"🏃🏃🏃 RUNNER DAY 3: ${ticker}\n"
            f"Total: +{gain:.1f}% | Score: {score:.0f}/20\n"
            f"Mir rule: harvest 50-75% into strength. Terminal velocity."
        )
    elif new_state == "DONE":
        reason = runner.get("done_reason", "COMPLETED")
        text = (
            f"🏁 RUNNER DONE: ${ticker} [{reason}]\n"
            f"Total: {'+' if gain >= 0 else ''}{gain:.1f}% | "
            f"Days: {runner.get('consecutive_2pct_days', 0)} | "
            f"Score: {score:.0f}/20"
        )
    else:
        return

    await send(text, ticker=ticker, force=True)


# ── State transitions ─────────────────────────────────────────────────


def _finalize_day(runner: dict, state: dict, day_prefix: str) -> None:
    """Copy running intraday OHLCV into the appropriate day slot."""
    runner[f"{day_prefix}_date"] = runner.get("_current_date") or _today()
    runner[f"{day_prefix}_open"] = state.get("_today_open") or runner.get(f"{day_prefix}_open")
    runner[f"{day_prefix}_high"] = state.get("_today_high") or runner.get(f"{day_prefix}_high")
    runner[f"{day_prefix}_low"] = state.get("_today_low") or runner.get(f"{day_prefix}_low")
    runner[f"{day_prefix}_close"] = state.get("actual_spot") or state.get("_spot") or runner.get(f"{day_prefix}_close")
    runner[f"{day_prefix}_volume"] = state.get("_today_volume") or runner.get(f"{day_prefix}_volume")
    avg = state.get("_avg_volume") or 1
    vol = runner.get(f"{day_prefix}_volume") or 0
    runner[f"{day_prefix}_rvol"] = round(vol / max(avg, 1), 2)


def _persist(runner: dict) -> None:
    """Write runner state to SQLite."""
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM runner_tracker WHERE ticker = ? AND state != 'DONE' LIMIT 1",
            (runner["ticker"],),
        ).fetchone()
        if row:
            c.execute("""UPDATE runner_tracker SET
                state=?, swing_score=?, rts_score=?, ivp=?, dist_to_high=?,
                runner_shape=?, adr_at_entry=?,
                d1_date=?, d1_open=?, d1_high=?, d1_low=?, d1_close=?,
                d1_volume=?, d1_rvol=?, d1_gain_pct=?,
                d2_date=?, d2_open=?, d2_high=?, d2_low=?, d2_close=?,
                d2_volume=?, d2_rvol=?, d2_gap_pct=?,
                d3_date=?, d3_open=?, d3_high=?, d3_low=?, d3_close=?,
                d3_volume=?, d3_rvol=?, d3_gap_pct=?,
                total_gain_pct=?, consecutive_2pct_days=?, runner_score=?,
                done_ts=?, done_reason=?
            WHERE id = ?""", (
                runner.get("state"), runner.get("swing_score"), runner.get("rts_score"),
                runner.get("ivp"), runner.get("dist_to_high"),
                runner.get("runner_shape"), runner.get("adr_at_entry"),
                runner.get("d1_date"), runner.get("d1_open"), runner.get("d1_high"),
                runner.get("d1_low"), runner.get("d1_close"),
                runner.get("d1_volume"), runner.get("d1_rvol"), runner.get("d1_gain_pct"),
                runner.get("d2_date"), runner.get("d2_open"), runner.get("d2_high"),
                runner.get("d2_low"), runner.get("d2_close"),
                runner.get("d2_volume"), runner.get("d2_rvol"), runner.get("d2_gap_pct"),
                runner.get("d3_date"), runner.get("d3_open"), runner.get("d3_high"),
                runner.get("d3_low"), runner.get("d3_close"),
                runner.get("d3_volume"), runner.get("d3_rvol"), runner.get("d3_gap_pct"),
                runner.get("total_gain_pct"), runner.get("consecutive_2pct_days"),
                runner.get("runner_score"),
                runner.get("done_ts"), runner.get("done_reason"),
                row["id"],
            ))
        else:
            c.execute("""INSERT INTO runner_tracker
                (ticker, state, entry_ts, entry_date, entry_path,
                 runner_shape, adr_at_entry,
                 swing_score, rts_score, ivp, dist_to_high,
                 d1_date, d1_open, d1_high, d1_low, d1_close,
                 d1_volume, d1_rvol, d1_gain_pct,
                 total_gain_pct, consecutive_2pct_days, runner_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                runner["ticker"], runner["state"], runner["entry_ts"], runner["entry_date"],
                runner.get("entry_path", "SWING"),
                runner.get("runner_shape"), runner.get("adr_at_entry"),
                runner.get("swing_score"), runner.get("rts_score"),
                runner.get("ivp"), runner.get("dist_to_high"),
                runner.get("d1_date"), runner.get("d1_open"), runner.get("d1_high"),
                runner.get("d1_low"), runner.get("d1_close"),
                runner.get("d1_volume"), runner.get("d1_rvol"), runner.get("d1_gain_pct"),
                runner.get("total_gain_pct"), runner.get("consecutive_2pct_days"),
                runner.get("runner_score"),
            ))


async def _close_runner(ticker: str, reason: str) -> None:
    """Move runner to DONE state."""
    runner = _runners.get(ticker)
    if not runner:
        return
    runner["state"] = "DONE"
    runner["done_ts"] = int(time.time())
    runner["done_reason"] = reason
    runner["runner_score"] = _compute_runner_score(runner)
    _persist(runner)
    await _alert_transition(ticker, "DONE", runner)
    _runners.pop(ticker, None)


# ── Main update loop (called from worker.py each cycle) ───────────────


async def update_runners() -> None:
    """Process all runner state transitions. Called after each scan cycle."""
    global _last_date

    if not _is_weekday():
        return

    today = _today()
    date_changed = today != _last_date and _last_date != ""

    # Get swing scanner cached results (no recomputation)
    from .swing_scanner import _swing_cache
    ts, results, meta = _swing_cache
    if not results:
        _last_date = today
        return

    watchlist = {r["ticker"]: r for r in results if r.get("_in_watchlist")}
    snapshot = await cache.snapshot()

    # ── Day finalization (runs once at first cycle of new trading day) ─
    if date_changed:
        await _finalize_day_transitions(snapshot)

    # ── Intraday updates for active runners ───────────────────────────
    to_close: list[tuple[str, str]] = []
    for ticker, runner in list(_runners.items()):
        state = snapshot.get(ticker, {})
        spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot:
            continue

        # Update running OHLCV for current day
        cur_state = runner["state"]
        if cur_state == "DAY1_BREAKOUT":
            prefix = "d1"
        elif cur_state == "DAY2_CONFIRM":
            prefix = "d2"
        elif cur_state == "DAY3_EXPLOSION":
            prefix = "d3"
        else:
            continue

        # Track running high/low through the day
        cur_high = runner.get(f"{prefix}_high") or 0
        cur_low = runner.get(f"{prefix}_low") or float("inf")
        if state.get("_today_high") and state["_today_high"] > cur_high:
            runner[f"{prefix}_high"] = state["_today_high"]
        if state.get("_today_low") and state["_today_low"] < cur_low:
            runner[f"{prefix}_low"] = state["_today_low"]
        runner[f"{prefix}_close"] = spot  # running close
        runner[f"{prefix}_volume"] = state.get("_today_volume") or runner.get(f"{prefix}_volume")

        # Recalculate totals
        entry_close = runner.get("d1_open") or runner.get("d1_close") or spot
        runner["total_gain_pct"] = round((spot - entry_close) / entry_close * 100, 2) if entry_close else 0

        # ── Intraday exit checks ──────────────────────────────────
        exit_reason = _check_intraday_exit(runner, spot)
        if exit_reason:
            to_close.append((ticker, exit_reason))

    for ticker, reason in to_close:
        await _close_runner(ticker, reason)

    # ── New Day 1 breakout detection ──────────────────────────────────
    for ticker, swing in watchlist.items():
        if ticker in _runners:
            continue  # already tracking
        state = snapshot.get(ticker, {})
        spot = state.get("actual_spot") or state.get("_spot") or 0
        prevclose = state.get("_prevclose") or 0
        if not spot or not prevclose:
            continue

        pct_change = (spot - prevclose) / prevclose * 100
        avg_vol = max(state.get("_avg_volume") or 1, 1)
        today_vol = state.get("_today_volume") or 0
        rvol = today_vol / avg_vol
        rts = swing.get("rts_score") or 0

        # ADR-relative entry threshold: scale to the ticker's typical range.
        # MSFT (ADR 1.5%) needs +1.5%; RKLB (ADR 6%) needs +3.6%.
        adr_pct = swing.get("adr_pct") or 2.5
        min_gain = max(1.5, 0.6 * adr_pct)

        if pct_change < min_gain or rvol < 1.1 or rts < 50:
            continue

        # Earnings blackout: swing scanner gates this, but double-check here.
        # A ticker could theoretically exit blackout and trigger Day 1 same cycle.
        try:
            from .signals import _earnings_blackout_cache
            _, bo_set = _earnings_blackout_cache
            if ticker in bo_set:
                continue
        except Exception:
            pass

        # Outcome-aware cooldown (5d COMPLETED, 10d failed)
        if _has_recent_done(ticker):
            continue

        # Classify shape using the swing scanner's ADR
        d1_high = state.get("_today_high") or spot
        d1_low = state.get("_today_low") or spot
        shape = _classify_shape(rvol, d1_high, d1_low, spot, adr_pct)

        runner = {
            "ticker": ticker,
            "state": "DAY1_BREAKOUT",
            "entry_ts": int(time.time()),
            "entry_date": today,
            "entry_path": "SWING",
            "runner_shape": shape,
            "adr_at_entry": round(adr_pct, 2),
            "swing_score": swing.get("swing_score"),
            "rts_score": rts,
            "ivp": state.get("_ivp"),
            "dist_to_high": swing.get("dist_to_high_pct"),
            "d1_date": today,
            "d1_open": state.get("_today_open") or prevclose,
            "d1_high": d1_high,
            "d1_low": d1_low,
            "d1_close": spot,
            "d1_volume": today_vol,
            "d1_rvol": round(rvol, 2),
            "d1_gain_pct": round(pct_change, 2),
            "total_gain_pct": round(pct_change, 2),
            "consecutive_2pct_days": 1,
            "_current_date": today,
        }
        runner["runner_score"] = _compute_runner_score(runner)
        _runners[ticker] = runner
        _persist(runner)
        await _alert_transition(ticker, "DAY1_BREAKOUT", runner)
        print(f"[runner_tracker] DAY1_BREAKOUT [SWING/{shape}]: {ticker} +{pct_change:.1f}% rvol={rvol:.1f}x score={runner['runner_score']:.0f}/20")

    # ── Reclaim path: catch V-bottom mega-cap reclaims that the swing
    # scanner's uptrend-continuation gates filter out (e.g., MSFT Apr 13). ──
    try:
        from .tickers import TIER_1
    except ImportError:
        TIER_1 = []
    reclaim_universe = set(TIER_1) | RECLAIM_EXTRA_TICKERS

    for ticker in reclaim_universe:
        if ticker in _runners:
            continue
        if ticker in watchlist:
            # Path collision: ticker qualified for BOTH paths in this cycle.
            # Swing path already consumed it. Log for future attribution.
            print(f"[runner_tracker] PATH_COLLISION [{ticker}]: swing path took precedence over reclaim")
            continue
        state = snapshot.get(ticker)
        if not state:
            continue
        reclaim_runner = _check_reclaim_entry(ticker, state, today)
        if reclaim_runner:
            reclaim_runner["runner_score"] = _compute_runner_score(reclaim_runner)
            _runners[ticker] = reclaim_runner
            _persist(reclaim_runner)
            await _alert_transition(ticker, "DAY1_BREAKOUT", reclaim_runner)
            shape = reclaim_runner.get("runner_shape", "MEASURED")
            print(f"[runner_tracker] DAY1_BREAKOUT [RECLAIM/{shape}]: {ticker} "
                  f"+{reclaim_runner['d1_gain_pct']:.1f}% "
                  f"rvol={reclaim_runner['d1_rvol']:.1f}x "
                  f"score={reclaim_runner['runner_score']:.0f}/20")

    _last_date = today


async def _finalize_day_transitions(snapshot: dict[str, dict]) -> None:
    """Run once per new trading day: finalize prior day OHLCV and transition states."""
    to_close: list[tuple[str, str]] = []
    transitions: list[tuple[str, str]] = []  # (ticker, new_state)

    for ticker, runner in list(_runners.items()):
        state_data = snapshot.get(ticker, {})
        cur = runner["state"]
        avg_vol = max(state_data.get("_avg_volume") or 1, 1)

        if cur == "DAY1_BREAKOUT":
            # Day 1 is finalized. Now check Day 2 opening conditions.
            d1_close = runner.get("d1_close") or 0
            d2_open = state_data.get("_today_open") or state_data.get("_prevclose") or 0

            if not d1_close or not d2_open:
                continue

            gap_pct = (d2_open - d1_close) / d1_close * 100
            runner["d2_date"] = _today()
            runner["d2_open"] = d2_open
            runner["d2_high"] = state_data.get("_today_high") or d2_open
            runner["d2_low"] = state_data.get("_today_low") or d2_open
            runner["d2_close"] = state_data.get("actual_spot") or state_data.get("_spot") or d2_open
            runner["d2_volume"] = state_data.get("_today_volume") or 0
            runner["d2_rvol"] = round((runner["d2_volume"] or 0) / avg_vol, 2)
            runner["d2_gap_pct"] = round(gap_pct, 2)

            # Gap-down = immediate fail
            if gap_pct < -2.0:
                to_close.append((ticker, "GAP_DOWN_D2"))
            else:
                runner["state"] = "DAY2_CONFIRM"
                runner["consecutive_2pct_days"] = (runner.get("consecutive_2pct_days") or 1)
                # Will increment if Day 2 gain is 2%+ at EOD
                runner["runner_score"] = _compute_runner_score(runner)
                transitions.append((ticker, "DAY2_CONFIRM"))

        elif cur == "DAY2_CONFIRM":
            # Day 2 is finalized. Check if it held.
            d1_close = runner.get("d1_close") or 0
            d2_open = runner.get("d2_open") or 0
            d2_high = runner.get("d2_high") or 0
            d2_low = runner.get("d2_low") or 0
            d2_close = runner.get("d2_close") or 0
            d2_vol = runner.get("d2_volume") or 0
            d1_vol = runner.get("d1_volume") or 1

            # ADR-relative soft failure grace band (ChatGPT v2: fixed 1% too blunt
            # for high-ADR names like TSLA, too loose for low-ADR like MSFT).
            # Formula: grace = max(1%, 0.25 * ADR%). A name with 6% ADR gets a
            # 1.5% grace band; a name with 1.5% ADR gets exactly 1%.
            adr_at_entry = runner.get("adr_at_entry") or 2.5
            grace_pct = max(1.0, 0.25 * adr_at_entry)
            if d2_close and d1_close and d2_close < d1_close * (1 - grace_pct / 100):
                to_close.append((ticker, "FAILED_DAY2"))
                continue

            # Weak-close penalty (ChatGPT v2 edge case): Day 2 gapped up strongly
            # but reversed and closed in the bottom 30% of its range on rising
            # volume — classic distribution. Kill the runner.
            if d2_high > 0 and d2_low > 0 and d2_open > 0:
                d2_range = d2_high - d2_low
                gap_up_strong = d2_open > d1_close * 1.01  # gapped up >1%
                close_in_bottom_30 = d2_range > 0 and (d2_close - d2_low) / d2_range < 0.30
                if gap_up_strong and close_in_bottom_30:
                    to_close.append((ticker, "D2_WEAK_CLOSE"))
                    continue

            # Failure: volume collapsed
            if d1_vol and d2_vol < d1_vol * 0.4:
                to_close.append((ticker, "VOLUME_COLLAPSE_D2"))
                continue

            # Day 2 gain check
            d2_gain = ((d2_close - d1_close) / d1_close * 100) if d1_close else 0
            if d2_gain >= 2.0:
                runner["consecutive_2pct_days"] = (runner.get("consecutive_2pct_days") or 1) + 1

            # Start Day 3
            d3_open = state_data.get("_today_open") or state_data.get("_prevclose") or 0
            runner["d3_date"] = _today()
            runner["d3_open"] = d3_open
            runner["d3_high"] = state_data.get("_today_high") or d3_open
            runner["d3_low"] = state_data.get("_today_low") or d3_open
            runner["d3_close"] = state_data.get("actual_spot") or state_data.get("_spot") or d3_open
            runner["d3_volume"] = state_data.get("_today_volume") or 0
            runner["d3_rvol"] = round((runner["d3_volume"] or 0) / avg_vol, 2)
            runner["d3_gap_pct"] = round(
                ((d3_open - d2_close) / d2_close * 100) if d2_close else 0, 2
            )

            runner["state"] = "DAY3_EXPLOSION"
            runner["runner_score"] = _compute_runner_score(runner)
            transitions.append((ticker, "DAY3_EXPLOSION"))

        elif cur == "DAY3_EXPLOSION":
            # Day 3 is done. Archive.
            d1_open = runner.get("d1_open") or runner.get("d1_close") or 0
            d3_close = runner.get("d3_close") or 0
            if d1_open and d3_close:
                runner["total_gain_pct"] = round((d3_close - d1_open) / d1_open * 100, 2)
            d3_gain = 0
            d2_close = runner.get("d2_close") or 0
            if d2_close and d3_close:
                d3_gain = (d3_close - d2_close) / d2_close * 100
            if d3_gain >= 2.0:
                runner["consecutive_2pct_days"] = (runner.get("consecutive_2pct_days") or 1) + 1
            runner["runner_score"] = _compute_runner_score(runner)
            to_close.append((ticker, "COMPLETED"))

    # Execute transitions
    for ticker, reason in to_close:
        await _close_runner(ticker, reason)

    for ticker, new_state in transitions:
        runner = _runners.get(ticker)
        if runner:
            _persist(runner)
            await _alert_transition(ticker, new_state, runner)
            print(f"[runner_tracker] {new_state}: {ticker} total={runner.get('total_gain_pct', 0):+.1f}% score={runner.get('runner_score', 0):.0f}/20")


def _check_intraday_exit(runner: dict, spot: float) -> str | None:
    """Check if runner should be killed intraday.

    Day 2: forgiving — grace period until 11 AM, only exit on severe breach (-4%).
        Mir rule: "give it 90 minutes before deciding."
        Close-based invalidation handled in _finalize_day_transitions.
    Day 3: strict — break of Day 2 low matters much more, kill immediately.
    """
    cur = runner["state"]
    now_hour = datetime.datetime.now().hour

    if cur == "DAY2_CONFIRM":
        # Morning grace: skip all checks before 11 AM (Mir's 90-min rule)
        if now_hour < 11:
            return None
        # Only intraday kill on SEVERE breach (-4% below d1_close).
        # Soft close-below-d1_close handled at EOD in day transition logic.
        d1_close = runner.get("d1_close") or 0
        if d1_close and spot < d1_close * 0.96:
            return "D2_SEVERE_BREACH"

    elif cur == "DAY3_EXPLOSION":
        # Strict: break of Day 2 low = move is done
        d2_low = runner.get("d2_low") or 0
        if d2_low and spot < d2_low:
            return "BELOW_D2_LOW"

    # Volume collapse (any active state): <30% of Day 1 volume, only check after 11 AM
    if now_hour >= 11:
        d1_vol = runner.get("d1_volume") or 0
        prefix = "d2" if cur == "DAY2_CONFIRM" else ("d3" if cur == "DAY3_EXPLOSION" else "d1")
        cur_vol = runner.get(f"{prefix}_volume") or 0
        if d1_vol and cur_vol and cur_vol < d1_vol * 0.3:
            return "VOLUME_COLLAPSE"

    return None


# ── API helpers ───────────────────────────────────────────────────────


def get_active_runners() -> list[dict]:
    """Return all active (non-DONE) runners for the API."""
    out = []
    for ticker, r in _runners.items():
        # Return a clean copy without internal keys
        out.append({k: v for k, v in r.items() if not k.startswith("_")})
    return sorted(out, key=lambda x: x.get("runner_score", 0), reverse=True)


def get_recent_runners(limit: int = 50) -> list[dict]:
    """Return completed runners from SQLite."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runner_tracker WHERE state = 'DONE' ORDER BY done_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_runner_for_ticker(ticker: str) -> dict | None:
    """Return the active runner for a ticker, or None."""
    r = _runners.get(ticker)
    if r:
        return {k: v for k, v in r.items() if not k.startswith("_")}
    return None
