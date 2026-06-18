"""Alert outcomes performance database.

The foundational change recommended by Perplexity's 5/20 evaluation:
every Telegram alert that fires gets logged with full context, then a
background task backfills outcomes (1h, EOD, 1d, target-hit, stop-hit,
MFE, MAE) when the evaluation window closes.

Without this, every filter threshold, every score band, every alert-type
deprecation decision is guided by anecdote. With this, after 60 trading
days we have ~1,200 outcome rows to validate every architectural
hypothesis empirically.

Schema philosophy:
  - Flat table, one row per alert fire
  - Context fields capture the alert state at fire time
  - Outcome fields are NULL until backfill task fills them
  - Regime fields (VIX, GEX, earnings, IVR) enable regime-conditional
    analysis (Perplexity flagged: GEX edge disappears in VIX>20)

Background task `run_outcome_backfill_loop` runs every 30 min during RTH
+ once at 18:00 ET for EOD evaluation. Idempotent — re-running just
re-fills NULL columns.

Shipped 2026-05-20 night.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = "./alert_outcomes.db"  # standalone DB so it survives main DB migrations

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_outcomes (
    alert_id           TEXT PRIMARY KEY,
    fired_at           REAL NOT NULL,
    alert_type         TEXT NOT NULL,    -- SOE_A, SOE_AP, GEX_MAGNET, ZERO_DTE, FLOW_MEDIUM, CLUSTER, MIR, KING_MIGRATION, etc
    ticker             TEXT NOT NULL,
    direction          TEXT,             -- BULL/BEAR/NEUTRAL
    grade              TEXT,             -- A+/A/B+/B/C or score
    score              REAL,
    -- Contract spec (NULL for info-only alerts)
    strike             REAL,
    expiration         TEXT,
    option_type        TEXT,             -- call/put
    dte                INTEGER,
    -- Entry/exit plan (as published in alert)
    spot_at_alert      REAL,
    entry_price        REAL,             -- option mid at fire time
    target_spot        REAL,             -- spot target
    stop_spot          REAL,
    target_premium     REAL,             -- option-price target (if specified)
    stop_premium       REAL,
    -- Context fields (Perplexity emphasis: regime conditioning)
    vix_at_alert       REAL,
    gex_regime         TEXT,             -- POS/NEG/null
    gex_signal         TEXT,             -- MAGNET UP / MAGNET FADE / etc
    king               REAL,
    floor              REAL,
    ceiling            REAL,
    earnings_in_window INTEGER,          -- 0/1 — DOES the contract span an earnings date
    earnings_days_to   INTEGER,          -- days to next earnings (NULL if none in window)
    ivr_at_alert       REAL,             -- IV rank 0-100
    -- 2026-05-20 PM (Perplexity follow-up): additional regime fields
    -- recommended for proper regime-conditional analysis. Backfilled
    -- where possible; NULL on alerts before this ship.
    atm_iv             REAL,             -- ATM IV at alert time (different from IVR)
    skew_25d           REAL,             -- 25-delta skew (put IV - call IV) at alert
    macro_event_flag   TEXT,             -- 'FOMC' | 'CPI' | 'NFP' | 'EARNINGS_HEAVY' | NULL
    alert_source_cluster TEXT,           -- e.g. 'WHALE_CALL_CLUSTER' for downstream
                                         --   alerts that fired from a parent cluster
    -- Outcome columns (NULL until backfilled)
    outcome_status     TEXT,             -- pending / target_hit / stop_hit / time_expired / flat
    outcome_resolved_at REAL,            -- epoch when outcome became known
    outcome_resolution_spot REAL,
    -- Spot MFE/MAE relative to alert spot
    spot_high_after    REAL,             -- max spot in window
    spot_low_after     REAL,             -- min spot in window
    spot_mfe_pct       REAL,             -- in direction of thesis
    spot_mae_pct       REAL,             -- against thesis
    -- Option MFE/MAE
    opt_high_after     REAL,
    opt_low_after      REAL,
    opt_mfe_pct        REAL,             -- option premium MFE vs entry
    opt_mae_pct        REAL,
    opt_close_eod      REAL,             -- option close on alert day
    opt_close_next_day REAL,             -- next trading day close
    -- Win/loss verdict by window
    verdict_1h         TEXT,             -- WIN/LOSS/FLAT relative to 1-hour
    verdict_eod        TEXT,             -- WIN/LOSS/FLAT relative to alert-day close
    verdict_next_day   TEXT,             -- WIN/LOSS/FLAT relative to next-day close
    -- Raw payload for debugging
    raw_alert_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_outcomes_type ON alert_outcomes(alert_type, fired_at);
CREATE INDEX IF NOT EXISTS idx_alert_outcomes_ticker ON alert_outcomes(ticker, fired_at);
CREATE INDEX IF NOT EXISTS idx_alert_outcomes_pending ON alert_outcomes(outcome_status, fired_at)
    WHERE outcome_status = 'pending';
"""


def _ensure_schema(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # Idempotent ADD COLUMN migrations for tables that pre-date the
        # PM 5/20 follow-up schema additions.
        for col, decl in [
            ("atm_iv", "REAL"),
            ("skew_25d", "REAL"),
            ("macro_event_flag", "TEXT"),
            ("alert_source_cluster", "TEXT"),
            # entry_was_stale is written by the INSERT but was never in the
            # CREATE/migration path — fine on prod (column predates a since-
            # edited list) but breaks fresh DBs. Add it so new DBs match.
            ("entry_was_stale", "INTEGER"),
            # #60 (4-LLM synthesis 6/8): next-morning settled-OI confirmation.
            # Pan-Poteshman: predictive power is in buy-to-OPEN volume. A flagged
            # contract whose settled OI rises by ≥ a fraction of the flagged
            # volume by next morning = genuine new positioning (opening); one
            # whose OI doesn't rise was a close/churn. Splitting win rates by
            # this cohort is the operational gate for that construct.
            ("oi_at_fire", "INTEGER"),       # OI on the contract at alert time
            ("flagged_volume", "INTEGER"),   # the alert's contract volume
            ("oi_next_morning", "INTEGER"),  # settled OI next trading morning
            ("oi_delta", "INTEGER"),         # oi_next_morning − oi_at_fire
            ("oi_confirmed", "INTEGER"),     # 1 opening / 0 closing-churn / NULL pending
            ("oi_status", "TEXT"),           # confirmed/unconfirmed/no_data/expired_no_data
            ("oi_checked_at", "REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE alert_outcomes ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                # Column already exists — fine
                pass
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Writer
# ─────────────────────────────────────────────────────────────────────────────


def make_alert_id(ticker: str, alert_type: str, fired_at: float,
                  strike: float | None = None, exp: str | None = None) -> str:
    """Deterministic ID for an alert — supports re-runs without dupes."""
    key = f"{ticker}|{alert_type}|{int(fired_at)}|{strike or ''}|{exp or ''}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def log_alert(
    *,
    alert_type: str,
    ticker: str,
    fired_at: float | None = None,
    direction: str | None = None,
    grade: str | None = None,
    score: float | None = None,
    strike: float | None = None,
    expiration: str | None = None,
    option_type: str | None = None,
    dte: int | None = None,
    spot_at_alert: float | None = None,
    entry_price: float | None = None,
    target_spot: float | None = None,
    stop_spot: float | None = None,
    target_premium: float | None = None,
    stop_premium: float | None = None,
    vix_at_alert: float | None = None,
    gex_regime: str | None = None,
    gex_signal: str | None = None,
    king: float | None = None,
    floor: float | None = None,
    ceiling: float | None = None,
    earnings_in_window: int | None = None,
    earnings_days_to: int | None = None,
    ivr_at_alert: float | None = None,
    oi_at_fire: int | None = None,
    flagged_volume: int | None = None,
    raw_alert: dict | None = None,
    db_path: str = DB_PATH,
) -> str | None:
    """Log a fired alert with full context. Returns alert_id, or None on
    error. ALL outcome columns start NULL — backfill task populates them.

    Best-effort: never raises. Alert logging failure should never block
    the actual Telegram send. If logging fails silently for a day, we
    lose 1 day of data — not a position.
    """
    try:
        _ensure_schema(db_path)
        ts = fired_at or time.time()
        aid = make_alert_id(ticker, alert_type, ts, strike, expiration)
        # #60: capture OI + volume at fire time for next-morning confirmation.
        # Auto-extract from the raw payload when not passed explicitly, so the
        # contract-bearing call sites (flow/cluster/whale) need no changes.
        if (oi_at_fire is None or flagged_volume is None) and raw_alert:
            if oi_at_fire is None:
                _o = raw_alert.get("oi", raw_alert.get("open_interest"))
                oi_at_fire = int(_o) if _o not in (None, "") else None
            if flagged_volume is None:
                _v = raw_alert.get("volume", raw_alert.get("vol"))
                flagged_volume = int(_v) if _v not in (None, "") else None
        # Pull the latest snapshot's is_stale flag for this ticker. If the most
        # recent snapshot was flagged stale, the alert was scored against
        # frozen data and should be marked. Added 2026-05-21 PM.
        try:
            from .snapshots import is_latest_stale
            entry_was_stale = is_latest_stale(ticker)
        except Exception:
            entry_was_stale = 0
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO alert_outcomes (
                    alert_id, fired_at, alert_type, ticker, direction, grade,
                    score, strike, expiration, option_type, dte,
                    spot_at_alert, entry_price, target_spot, stop_spot,
                    target_premium, stop_premium, vix_at_alert, gex_regime,
                    gex_signal, king, floor, ceiling, earnings_in_window,
                    earnings_days_to, ivr_at_alert, outcome_status, raw_alert_json,
                    entry_was_stale, oi_at_fire, flagged_volume
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, 'pending', ?,
                    ?, ?, ?
                )""",
                (
                    aid, ts, alert_type, ticker.upper(), direction, grade,
                    score, strike, expiration, option_type, dte,
                    spot_at_alert, entry_price, target_spot, stop_spot,
                    target_premium, stop_premium, vix_at_alert, gex_regime,
                    gex_signal, king, floor, ceiling, earnings_in_window,
                    earnings_days_to, ivr_at_alert,
                    json.dumps(raw_alert, default=str) if raw_alert else None,
                    entry_was_stale, oi_at_fire, flagged_volume,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return aid
    except Exception as e:
        print(f"[alert_outcomes] log_alert failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Outcome backfill — runs every 30 min
# ─────────────────────────────────────────────────────────────────────────────


def _verdict(spot_change_pct: float, threshold: float = 0.3) -> str:
    """Classify a spot move as WIN/LOSS/FLAT based on directional change."""
    if spot_change_pct > threshold:
        return "WIN"
    if spot_change_pct < -threshold:
        return "LOSS"
    return "FLAT"


async def backfill_outcomes(db_path: str = DB_PATH, max_age_days: int = 7) -> dict:
    """Walk all pending alerts where the evaluation window has closed,
    compute outcomes from Tradier/Theta history, and update rows.

    Evaluation windows:
      - 1h after alert: WIN if spot moved >0.3% in thesis direction
      - EOD of alert day: same
      - Next trading day close: same
      - Target hit: spot reached target_spot at any point after alert
      - Stop hit: spot reached stop_spot at any point after alert

    Returns stats dict.
    """
    from server.tradier import TradierClient

    _ensure_schema(db_path)
    now = time.time()
    cutoff_min = now - max_age_days * 86400  # don't backfill ancient
    conn = sqlite3.connect(db_path)
    try:
        # Pull pending alerts whose alert-day has fully closed
        # (i.e., it's now past 4:00 PM ET on the alert day)
        rows = conn.execute(
            """SELECT alert_id, fired_at, alert_type, ticker, direction,
                      spot_at_alert, entry_price, target_spot, stop_spot,
                      strike, expiration, option_type, dte
               FROM alert_outcomes
               WHERE outcome_status = 'pending'
                 AND fired_at > ?
                 AND fired_at < ?""",
            (cutoff_min, now - 3600),  # at least 1h old
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"processed": 0, "updated": 0, "skipped": 0}

    print(f"[alert_outcomes] backfilling {len(rows)} pending alerts")

    stats = {"processed": 0, "updated": 0, "skipped": 0, "errors": 0}
    tradier = TradierClient()
    try:
        # Group by ticker to minimize API calls
        from collections import defaultdict
        by_ticker: dict[str, list] = defaultdict(list)
        for r in rows:
            by_ticker[r[3]].append(r)

        for ticker, ticker_rows in by_ticker.items():
            stats["processed"] += len(ticker_rows)
            # Pull intraday history covering all alert times for this ticker
            min_fired = min(r[1] for r in ticker_rows)
            max_fired = max(r[1] for r in ticker_rows)
            start = _dt.datetime.fromtimestamp(min_fired).date()
            end = (_dt.datetime.fromtimestamp(max_fired).date()
                   + _dt.timedelta(days=3))
            try:
                bars_5m = await tradier.history(
                    ticker, interval="5min",
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
                bars_daily = await tradier.history(
                    ticker, interval="daily",
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
            except Exception as e:
                print(f"[alert_outcomes] history fetch failed for {ticker}: {e}")
                stats["errors"] += len(ticker_rows)
                continue

            for row in ticker_rows:
                (alert_id, fired_at, alert_type, _t, direction,
                 spot_alert, entry_price, target_spot, stop_spot,
                 strike, exp, otype, dte) = row

                # Find 1h window, EOD window, next-day window
                fired_dt = _dt.datetime.fromtimestamp(fired_at)

                # Filter 5min bars to the windows we care about.
                # Bug fix 2026-05-20: Tradier intraday history returns `time`
                # as an epoch integer, not an ISO string. Original code used
                # fromisoformat() which silently failed (ValueError caught by
                # the except), filtering everything out and leaving every
                # alert in 'pending' status despite the backfill reporting
                # "updated".
                def _bars_in_window(start_ts: float, end_ts: float):
                    out = []
                    for b in bars_5m:
                        t_val = b.get("time")
                        if t_val is None:
                            continue
                        try:
                            if isinstance(t_val, (int, float)):
                                bt = float(t_val)
                            else:
                                bt = _dt.datetime.fromisoformat(t_val).timestamp()
                        except (ValueError, TypeError):
                            continue
                        if start_ts <= bt <= end_ts:
                            out.append({"ts": bt, "high": b.get("high"),
                                       "low": b.get("low"),
                                       "close": b.get("close")})
                    return out

                w_1h = _bars_in_window(fired_at, fired_at + 3600)

                # Alert-day EOD = 16:00 ET on fired_dt's date
                eod_ts = fired_dt.replace(hour=16, minute=0, second=0,
                                          microsecond=0).timestamp()
                if eod_ts <= fired_at:
                    eod_ts = fired_at + 86400  # in case fired after close
                w_eod = _bars_in_window(fired_at, eod_ts)

                # Compute spot MFE/MAE in window
                is_bull = direction == "BULL" if direction else None
                spot_high = max((b["high"] for b in w_eod if b.get("high")),
                               default=None)
                spot_low = min((b["low"] for b in w_eod if b.get("low")),
                              default=None)
                spot_eod_close = w_eod[-1]["close"] if w_eod else None

                # Spot MFE/MAE relative to alert spot
                spot_mfe = None
                spot_mae = None
                if spot_alert and spot_high and spot_low and is_bull is not None:
                    if is_bull:
                        spot_mfe = (spot_high - spot_alert) / spot_alert * 100
                        spot_mae = (spot_low - spot_alert) / spot_alert * 100
                    else:
                        spot_mfe = (spot_alert - spot_low) / spot_alert * 100
                        spot_mae = (spot_alert - spot_high) / spot_alert * 100

                # Target/stop hits
                target_hit = False
                stop_hit = False
                resolution_status = "pending"
                resolution_ts = None
                resolution_spot = None

                if target_spot and stop_spot and is_bull is not None and w_eod:
                    for b in w_eod:
                        if is_bull:
                            if b["high"] and b["high"] >= target_spot:
                                target_hit = True
                                resolution_status = "target_hit"
                                resolution_ts = b["ts"]
                                resolution_spot = target_spot
                                break
                            if b["low"] and b["low"] <= stop_spot:
                                stop_hit = True
                                resolution_status = "stop_hit"
                                resolution_ts = b["ts"]
                                resolution_spot = stop_spot
                                break
                        else:
                            if b["low"] and b["low"] <= target_spot:
                                target_hit = True
                                resolution_status = "target_hit"
                                resolution_ts = b["ts"]
                                resolution_spot = target_spot
                                break
                            if b["high"] and b["high"] >= stop_spot:
                                stop_hit = True
                                resolution_status = "stop_hit"
                                resolution_ts = b["ts"]
                                resolution_spot = stop_spot
                                break
                    if not target_hit and not stop_hit:
                        resolution_status = "time_expired"
                        resolution_ts = eod_ts
                        resolution_spot = spot_eod_close
                elif w_eod:
                    # Info-only alerts (FLOW_MEDIUM, CLUSTER, MIR, SETUP_FORMING)
                    # don't have explicit target/stop. Score them by spot move
                    # alone — bug fix 2026-05-20 post-deploy: original
                    # logic left these in 'pending' status forever.
                    resolution_status = "info_only"
                    resolution_ts = eod_ts
                    resolution_spot = spot_eod_close

                # Verdict computations
                def _verdict_from_close(close_spot):
                    if not close_spot or not spot_alert or is_bull is None:
                        return None
                    delta = (close_spot - spot_alert) / spot_alert * 100
                    if not is_bull:
                        delta = -delta
                    return _verdict(delta)

                # 1h verdict
                w_1h_close = w_1h[-1]["close"] if w_1h else None
                v_1h = _verdict_from_close(w_1h_close)
                v_eod = _verdict_from_close(spot_eod_close)

                # Next-day close
                fired_date_str = fired_dt.date().isoformat()
                next_day_close = None
                found_alert_day = False
                for b in bars_daily:
                    if b.get("time") == fired_date_str:
                        found_alert_day = True
                        continue
                    if found_alert_day:
                        next_day_close = b.get("close")
                        break
                v_next = _verdict_from_close(next_day_close)

                # Apply update
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        """UPDATE alert_outcomes SET
                            outcome_status = ?,
                            outcome_resolved_at = ?,
                            outcome_resolution_spot = ?,
                            spot_high_after = ?,
                            spot_low_after = ?,
                            spot_mfe_pct = ?,
                            spot_mae_pct = ?,
                            verdict_1h = ?,
                            verdict_eod = ?,
                            verdict_next_day = ?
                           WHERE alert_id = ?""",
                        (
                            resolution_status, resolution_ts, resolution_spot,
                            spot_high, spot_low, spot_mfe, spot_mae,
                            v_1h, v_eod, v_next, alert_id,
                        ),
                    )
                    conn.commit()
                    stats["updated"] += 1
                except Exception as e:
                    print(f"[alert_outcomes] update failed for {alert_id}: {e}")
                    stats["errors"] += 1
                finally:
                    conn.close()
    finally:
        await tradier.close()

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# #60 — next-morning settled-OI confirmation cohort (4-LLM synthesis 6/8)
# ─────────────────────────────────────────────────────────────────────────────

# Settled OI must rise by ≥ this fraction of the flagged volume for the alert to
# count as genuine new positioning (opening). Below it, the flagged volume was
# mostly closing/churn against existing OI.
OI_CONFIRM_FRACTION: float = 0.50


def classify_oi(oi_now: int | None, oi_at_fire: int | None,
                flagged_volume: int | None,
                frac: float = OI_CONFIRM_FRACTION) -> tuple[int | None, str]:
    """Pure classifier. Returns (oi_confirmed, oi_status).

    confirmed (1) : ΔOI ≥ frac · flagged_volume → opening / new positioning
    unconfirmed(0): ΔOI below that → close or churn against existing OI
    no_data       : missing inputs → cannot classify
    """
    if oi_now is None or oi_at_fire is None or not flagged_volume:
        return None, "no_data"
    delta = oi_now - oi_at_fire
    if delta >= frac * flagged_volume:
        return 1, "confirmed"
    return 0, "unconfirmed"


def _today_midnight_local() -> float:
    n = _dt.datetime.now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _select_oi_pending(db_path: str, now: float, max_age_days: int) -> list:
    """Contract-bearing rows fired on a PRIOR day with no OI verdict yet.
    Fired-before-today gate ensures OCC settled OI has updated overnight."""
    _ensure_schema(db_path)
    cutoff_min = now - max_age_days * 86400
    before = _today_midnight_local()
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """SELECT alert_id, ticker, expiration, strike, option_type,
                      oi_at_fire, flagged_volume
               FROM alert_outcomes
               WHERE oi_status IS NULL
                 AND strike IS NOT NULL AND expiration IS NOT NULL
                 AND option_type IS NOT NULL
                 AND fired_at > ? AND fired_at < ?""",
            (cutoff_min, before),
        ).fetchall()
    finally:
        conn.close()


def _write_oi_result(db_path: str, alert_id: str, oi_now: int | None,
                     oi_at_fire: int | None, flagged_volume: int | None,
                     confirmed: int | None, status: str, now: float) -> None:
    oi_delta = (oi_now - oi_at_fire) if (oi_now is not None and oi_at_fire is not None) else None
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE alert_outcomes SET
                oi_next_morning = ?, oi_delta = ?, oi_confirmed = ?,
                oi_status = ?, oi_checked_at = ?
               WHERE alert_id = ?""",
            (oi_now, oi_delta, confirmed, status, now, alert_id),
        )
        conn.commit()
    finally:
        conn.close()


async def _tradier_chain_oi(tradier, ticker: str, exp: str) -> dict[tuple[float, str], int]:
    """{(strike, option_type) -> open_interest} for one expiration."""
    out: dict[tuple[float, str], int] = {}
    try:
        chain = await tradier.chain(ticker, exp)
    except Exception as e:
        print(f"[alert_outcomes] OI chain fetch failed {ticker} {exp}: {e!r}")
        return out
    for o in chain or []:
        try:
            k = (float(o.get("strike")), (o.get("option_type") or "").lower())
            out[k] = int(o.get("open_interest") or 0)
        except (TypeError, ValueError):
            continue
    return out


async def run_oi_confirmation(db_path: str = DB_PATH, max_age_days: int = 7,
                              now: float | None = None, fetcher=None) -> dict:
    """Record whether each flagged contract's settled OI GREW by next morning
    (descriptive `oi_confirmed` = "settled-OI-grew", NOT a validated "opening"
    vs "closing-churn" read). Idempotent — only touches rows whose oi_status is
    still NULL and that fired on a prior day. `fetcher(ticker, exp)` is
    injectable for tests; defaults to a Tradier chain lookup.

    ⚠️ DISPUTED INTERPRETATION (#80, red-team 2026-06-18): the Pan-Poteshman
    premise that OI-growth ("opening") flow out-performs non-growth ("churn")
    was DOWNGRADED to a mechanical liquidity/price tilt — fragile under a
    liquidity control, dead on options. This cohort is DESCRIPTIVE ONLY; do NOT
    feed `oi_confirmed` into conviction/dispatch scoring or promote it to a gate.
    """
    now = now if now is not None else time.time()
    rows = _select_oi_pending(db_path, now, max_age_days)
    stats = {"processed": 0, "confirmed": 0, "unconfirmed": 0,
             "no_data": 0, "expired_no_data": 0, "deferred": 0}
    if not rows:
        return stats

    from collections import defaultdict
    by_exp: dict[tuple[str, str], list] = defaultdict(list)
    for r in rows:
        by_exp[(r[1], r[2])].append(r)

    tradier = None
    if fetcher is None:
        from server.tradier import TradierClient
        tradier = TradierClient()

        async def fetcher(tk, ex):  # noqa: ANN001
            return await _tradier_chain_oi(tradier, tk, ex)

    today_date = _dt.date.fromtimestamp(now)
    try:
        for (ticker, exp), grp in by_exp.items():
            # Expiration already passed → settled OI is meaningless; stop retrying.
            exp_passed = False
            try:
                exp_passed = _dt.date.fromisoformat(exp) < today_date
            except (ValueError, TypeError):
                exp_passed = False

            oi_map = {} if exp_passed else await fetcher(ticker, exp)
            for (alert_id, _t, _e, strike, otype, oi_fire, fvol) in grp:
                stats["processed"] += 1
                oi_now = None
                if not exp_passed:
                    oi_now = oi_map.get((float(strike), (otype or "").lower()))
                if oi_now is None and not exp_passed and oi_map:
                    # chain returned but contract absent → treat as 0 settled OI
                    oi_now = 0
                if oi_now is None and not exp_passed and not oi_map:
                    # provider miss this run — leave pending, retry next loop
                    stats["deferred"] += 1
                    continue
                if exp_passed:
                    _write_oi_result(db_path, alert_id, None, oi_fire, fvol,
                                     None, "expired_no_data", now)
                    stats["expired_no_data"] += 1
                    continue
                confirmed, status = classify_oi(oi_now, oi_fire, fvol)
                _write_oi_result(db_path, alert_id, oi_now, oi_fire, fvol,
                                 confirmed, status, now)
                stats[status] = stats.get(status, 0) + 1
    finally:
        if tradier is not None:
            await tradier.close()
    return stats


def get_oi_confirmation_report(days: int = 30, db_path: str = DB_PATH) -> list[dict[str, Any]]:
    """Win rates split by settled-OI-growth cohort per alert type — DESCRIPTIVE
    measurement only. ⚠️ The synthesis hypothesis (confirmed/"opening" flow
    out-wins unconfirmed/"churn") is DISPUTED: the red-team (2026-06-18, #80)
    found it is a mechanical liquidity tilt, not informed positioning. Do NOT
    promote this cohort to a gate or wire `oi_confirmed` into conviction."""
    _ensure_schema(db_path)
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT alert_type,
                      CASE oi_confirmed WHEN 1 THEN 'confirmed'
                           WHEN 0 THEN 'unconfirmed' ELSE 'unknown' END AS cohort,
                      COUNT(*) AS n,
                      SUM(CASE WHEN verdict_eod='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN verdict_eod='LOSS' THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN verdict_eod='FLAT' THEN 1 ELSE 0 END) AS flat
               FROM alert_outcomes
               WHERE fired_at > ? AND outcome_status != 'pending'
                 AND oi_confirmed IS NOT NULL
               GROUP BY alert_type, cohort
               ORDER BY alert_type, cohort""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        decided = r[2] - r[5]  # exclude FLAT from win-rate denominator
        out.append({
            "alert_type": r[0], "cohort": r[1], "n": r[2],
            "wins": r[3], "losses": r[4], "flat": r[5],
            "win_rate_eod": (r[3] / decided * 100) if decided > 0 else None,
        })
    return out


async def run_outcome_backfill_loop(stop_event: asyncio.Event,
                                     interval_s: int = 1800) -> None:
    """Background task: backfill outcomes every 30 min during RTH + once
    at 18:00 ET for EOD evaluation."""
    print(f"[alert_outcomes] backfill loop starting — interval={interval_s}s")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            break
        except asyncio.TimeoutError:
            pass
        try:
            stats = await backfill_outcomes()
            if stats["processed"] > 0:
                print(f"[alert_outcomes] backfill: {stats}")
        except Exception as e:
            print(f"[alert_outcomes] backfill loop error: {e}")
        # #60: confirm next-morning OI growth on prior-day flagged contracts.
        # Idempotent + self-limiting (only NULL-status prior-day rows), so it's
        # safe to run every loop — it no-ops once the morning pass is done.
        try:
            oi_stats = await run_oi_confirmation()
            if oi_stats["processed"] > 0:
                print(f"[alert_outcomes] OI confirmation: {oi_stats}")
        except Exception as e:
            print(f"[alert_outcomes] OI confirmation error: {e}")
    print("[alert_outcomes] backfill loop stopped")


# ─────────────────────────────────────────────────────────────────────────────
# Analytics helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_win_rate_by_type(
    days: int = 30, db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    """Return win rate stats per alert type over the last N days.

    Used by the daily Telegram digest + the eventual UI dashboard.
    """
    _ensure_schema(db_path)
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT alert_type,
                      COUNT(*) AS n,
                      SUM(CASE WHEN verdict_eod = 'WIN' THEN 1 ELSE 0 END) AS wins_eod,
                      SUM(CASE WHEN verdict_eod = 'LOSS' THEN 1 ELSE 0 END) AS losses_eod,
                      SUM(CASE WHEN verdict_eod = 'FLAT' THEN 1 ELSE 0 END) AS flat_eod,
                      AVG(spot_mfe_pct) AS avg_mfe,
                      AVG(spot_mae_pct) AS avg_mae
               FROM alert_outcomes
               WHERE fired_at > ?
                 AND outcome_status != 'pending'
               GROUP BY alert_type
               ORDER BY n DESC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [{
        "alert_type": r[0],
        "n": r[1],
        "wins_eod": r[2],
        "losses_eod": r[3],
        "flat_eod": r[4],
        "win_rate_eod": (r[2] / max(r[1] - r[4], 1)) * 100 if (r[1] - r[4]) > 0 else None,
        "avg_mfe_pct": r[5],
        "avg_mae_pct": r[6],
    } for r in rows]


def get_win_rate_by_type_and_regime(
    days: int = 30, db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    """Win rate by (alert_type, vix_regime) — Perplexity's key ask:
    'separate win rates for VIX < 15, VIX 15-25, VIX > 25'."""
    _ensure_schema(db_path)
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT alert_type,
                      CASE
                          WHEN vix_at_alert IS NULL THEN 'UNKNOWN'
                          WHEN vix_at_alert < 15 THEN 'LOW'
                          WHEN vix_at_alert < 25 THEN 'MED'
                          ELSE 'HIGH'
                      END AS vix_regime,
                      COUNT(*) AS n,
                      SUM(CASE WHEN verdict_eod = 'WIN' THEN 1 ELSE 0 END) AS wins
               FROM alert_outcomes
               WHERE fired_at > ?
                 AND outcome_status != 'pending'
                 AND verdict_eod IS NOT NULL
               GROUP BY alert_type, vix_regime
               ORDER BY alert_type, vix_regime""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [{
        "alert_type": r[0], "vix_regime": r[1],
        "n": r[2], "wins": r[3],
        "win_rate": (r[3] / r[2]) * 100 if r[2] > 0 else None,
    } for r in rows]
