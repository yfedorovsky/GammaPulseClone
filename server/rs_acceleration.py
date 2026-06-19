"""RS acceleration + breadth-weighted sector tiering (AION-teardown task #56).

Two borrows from AION's AION-Index page, both operating on the per-ticker RTS
composite we already compute (`rts.py:compute_rts` → 0-100 score + universe_rank):

1. ACCELERATION / DECELERATION — rate-of-change of a ticker's RTS score over
   recent days (recent-window avg minus prior-window avg). Surfaces a top
   leader that is *fading* (next to roll off) — something a level-only
   leaderboard misses. AION's `computeAccelDecel`.

2. BREADTH-WEIGHTED SECTOR SCORE — tiered participation: count a sector's
   members in the universe's top 10%/20%/30% (via `universe_rank`), weight
   names deeper in the leader pool more heavily, normalize by basket size.
   Rewards deep/broad leadership over one megacap outlier. AION's
   `computeSectorComposition` (Avg Score vs Breadth-Wtd).

RTS scores aren't otherwise persisted, so this module owns a small daily
`rts_history` table (oi_delta.py pattern). Snapshot once per day at EOD; read
recent series to compute deltas.
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings

# ── Schema / config ───────────────────────────────────────────────────────
RTS_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS rts_history (
    date          TEXT NOT NULL,      -- YYYY-MM-DD (EOD capture)
    ticker        TEXT NOT NULL,
    rts_score     REAL,               -- 0-100 composite
    rs_score      REAL,               -- relative-strength block
    ts_score      REAL,               -- trend-strength block
    universe_rank INTEGER,            -- percentile 0-100
    captured_ts   INTEGER NOT NULL,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_rtsh_ticker_date ON rts_history(ticker, date);
CREATE INDEX IF NOT EXISTS idx_rtsh_date ON rts_history(date);
"""

RETENTION_DAYS = 60
ACCEL_WINDOW = 3            # days per recent/prior averaging window
ACCEL_THRESHOLD = 2.0      # |accel| above this → ACCELERATING / DECELERATING
ACCEL_LOOKBACK_DAYS = 12   # how many recent days to pull for the series

# tiered-participation weights (top 10% counts most)
TIER_WEIGHTS = {"TOP_10": 0.6, "TOP_20": 0.3, "TOP_30": 0.1, "BELOW_30": 0.0}

# tests may point this at a temp DB; None → production snapshots.db
_DB_PATH_OVERRIDE: str | None = None


@contextmanager
def _conn():
    path = _DB_PATH_OVERRIDE or get_settings().snapshot_db
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_rts_history_db() -> None:
    with _conn() as c:
        c.executescript(RTS_HISTORY_SCHEMA)


# ── Pure cores (no DB — fully unit-testable) ──────────────────────────────
def tier_of_rank(rank: float | None) -> str:
    """Map a universe percentile rank (0-100) to a leadership tier."""
    if rank is None:
        return "BELOW_30"
    if rank >= 90:
        return "TOP_10"
    if rank >= 80:
        return "TOP_20"
    if rank >= 70:
        return "TOP_30"
    return "BELOW_30"


def accel_from_series(
    scores: list[float], window: int = ACCEL_WINDOW,
    threshold: float = ACCEL_THRESHOLD,
) -> dict[str, Any]:
    """Acceleration = recent-window avg minus prior-window avg of an RTS series.

    `scores` is ordered oldest → newest. Returns {accel, recent_avg, prior_avg,
    direction, n, latest}. Degrades gracefully on short series.
    """
    s = [float(x) for x in scores if x is not None]
    n = len(s)
    if n < 2:
        return {"accel": 0.0, "recent_avg": (s[-1] if s else None),
                "prior_avg": None, "direction": "FLAT", "n": n,
                "latest": (s[-1] if s else None)}
    w = max(1, min(window, n // 2))
    recent = sum(s[-w:]) / w
    if n >= 2 * w:
        prior = sum(s[-2 * w:-w]) / w
    else:
        prior = sum(s[:-w]) / max(1, n - w)
    accel = recent - prior
    if accel > threshold:
        direction = "ACCELERATING"
    elif accel < -threshold:
        direction = "DECELERATING"
    else:
        direction = "STABLE"
    return {"accel": round(accel, 2), "recent_avg": round(recent, 1),
            "prior_avg": round(prior, 1), "direction": direction,
            "n": n, "latest": round(s[-1], 1)}


def sector_breadth(
    universe: dict[str, dict[str, Any]], groups: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Breadth-weighted sector composition (AION computeSectorComposition).

    universe: {ticker: {"score": 0-100, "universe_rank": 0-100}}
    groups:   {sector_name: [tickers]}

    Returns sectors sorted by Breadth-Wtd desc, each with avg_score (straight
    mean — "how strong is the typical member") and breadth_wtd (tiered
    participation — "how deep/broad is leadership"). The two can diverge: a
    sector carried by one monster name posts a high avg but soft breadth_wtd.
    """
    out: list[dict[str, Any]] = []
    for sector, members in groups.items():
        present = [(t, universe[t]) for t in members if t in universe]
        if not present:
            continue
        basket = len(present)
        scores = [float(u.get("score", 0) or 0) for _, u in present]
        tiers = [tier_of_rank(u.get("universe_rank")) for _, u in present]
        counts = {k: tiers.count(k) for k in TIER_WEIGHTS}
        breadth_wtd = round(
            100.0 * sum(TIER_WEIGHTS[k] * counts[k] for k in TIER_WEIGHTS) / basket,
            1,
        )
        out.append({
            "sector": sector,
            "basket": basket,
            "avg_score": round(sum(scores) / basket, 1),
            "breadth_wtd": breadth_wtd,
            "in_top10": counts["TOP_10"],
            "in_top20": counts["TOP_20"],
            "in_top30": counts["TOP_30"],
        })
    out.sort(key=lambda x: x["breadth_wtd"], reverse=True)
    return out


# ── DB layer (persist / read history) ─────────────────────────────────────
def record_rts_snapshot(
    universe: dict[str, dict[str, Any]], date: str | None = None,
) -> int:
    """Persist one EOD row per ticker from a compute_rts_universe() result.
    Idempotent (INSERT OR REPLACE on (date, ticker)). Prunes > RETENTION_DAYS.
    Returns rows written."""
    d = date or datetime.date.today().isoformat()
    ts = int(time.time())
    rows = [
        (d, t.upper(), u.get("score"), u.get("rs_score"), u.get("ts_score"),
         u.get("universe_rank"), ts)
        for t, u in universe.items()
    ]
    if not rows:
        return 0
    cutoff = (datetime.date.today() - datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    with _conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO rts_history
               (date, ticker, rts_score, rs_score, ts_score, universe_rank, captured_ts)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
        c.execute("DELETE FROM rts_history WHERE date < ?", (cutoff,))
    return len(rows)


def fetch_series(ticker: str, days: int = ACCEL_LOOKBACK_DAYS) -> list[float]:
    """Most-recent `days` RTS scores for a ticker, oldest → newest."""
    with _conn() as c:
        rows = c.execute(
            "SELECT rts_score FROM rts_history WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker.upper(), days),
        ).fetchall()
    return [r["rts_score"] for r in reversed(rows) if r["rts_score"] is not None]


def compute_all_acceleration(
    days: int = ACCEL_LOOKBACK_DAYS, window: int = ACCEL_WINDOW,
) -> list[dict[str, Any]]:
    """Acceleration for every ticker with enough history. Sorted accel desc
    (top = strongest accelerators; bottom = fastest decelerators)."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    by_ticker: dict[str, list[float]] = {}
    with _conn() as c:
        rows = c.execute(
            "SELECT ticker, rts_score FROM rts_history "
            "WHERE date >= ? ORDER BY ticker, date",
            (cutoff,),
        ).fetchall()
    for r in rows:
        if r["rts_score"] is not None:
            by_ticker.setdefault(r["ticker"], []).append(r["rts_score"])
    out = []
    for ticker, series in by_ticker.items():
        a = accel_from_series(series, window=window)
        if a["n"] >= 2:
            out.append({"ticker": ticker, **a})
    out.sort(key=lambda x: x["accel"], reverse=True)
    return out


def accelerators(limit: int = 20) -> list[dict[str, Any]]:
    return [r for r in compute_all_acceleration() if r["accel"] > 0][:limit]


def decelerators(limit: int = 20) -> list[dict[str, Any]]:
    rows = [r for r in compute_all_acceleration() if r["accel"] < 0]
    rows.sort(key=lambda x: x["accel"])  # most negative first
    return rows[:limit]


# ── EOD recorder (self-gated, once per day) ───────────────────────────────
_last_eod_record_date: str | None = None


def _now_et():
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("America/New_York"))


async def maybe_record_eod_rts(tradier_client: Any) -> bool:
    """Snapshot the RTS universe to rts_history once per trading day, in the
    16:00-16:30 ET window. Cheap no-op outside the window or after the first
    fire of the day. Mirrors maybe_fire_eod_leaderboard's self-gating.

    Burn-in: deltas need >= 2 days of history, so acceleration is meaningful
    from the second recorded session onward.
    """
    global _last_eod_record_date
    try:
        now = _now_et()
    except Exception:
        return False
    if now.weekday() >= 5:  # weekend
        return False
    # window: 16:00 <= t <= 16:30 ET
    if not (now.hour == 16 and now.minute <= 30):
        return False
    today = now.date().isoformat()
    if _last_eod_record_date == today:
        return False

    try:
        from .tickers import all_tickers
        from .rts import compute_rts_universe
        tickers = all_tickers()
        universe = await compute_rts_universe(tradier_client, tickers)
    except Exception as e:
        print(f"[RTS-HISTORY] universe compute failed: {e!r}", flush=True)
        return False

    n = record_rts_snapshot(universe, date=today)
    _last_eod_record_date = today
    print(f"[RTS-HISTORY] recorded {n} tickers for {today}", flush=True)
    return True


_last_accel_digest_date: str | None = None


async def maybe_fire_eod_accel_digest() -> bool:
    """Once-per-day EOD Telegram digest of the RS-acceleration leaderboard — who's
    CLIMBING vs ROLLING OFF the relative-strength ranks over recent days. This is
    the SWING complement to the intraday rs_decouple_detector: multi-day momentum,
    no same-day lead, but it surfaces names BUILDING leadership before they break.
    Self-gates to 16:10-16:45 ET (after the RTS snapshot records), once/day."""
    global _last_accel_digest_date
    try:
        now = _now_et()
    except Exception:
        return False
    if now.weekday() >= 5:
        return False
    if not (now.hour == 16 and 10 <= now.minute <= 45):
        return False
    today = now.date().isoformat()
    if _last_accel_digest_date == today:
        return False

    accel = accelerators(limit=6)
    decel = decelerators(limit=4)
    if not accel and not decel:
        return False
    lines = ["📈 RS ACCELERATION — EOD (multi-day relative-strength momentum)"]
    if accel:
        lines.append("Climbing: " + ", ".join(
            f"{a['ticker']} +{a['accel']:.0f} (rts {a['latest']:.0f})" for a in accel))
    if decel:
        lines.append("Rolling off: " + ", ".join(
            f"{d['ticker']} {d['accel']:.0f}" for d in decel))
    lines.append("Context — leaderboard momentum over days, NOT an intraday signal.")
    try:
        from . import telegram
        await telegram.send("\n".join(lines), priority=True)
    except Exception as e:
        print(f"[RS-ACCEL-DIGEST] send failed: {e!r}", flush=True)
        return False
    _last_accel_digest_date = today
    print(f"[RS-ACCEL-DIGEST] sent {len(accel)} climbing / {len(decel)} rolling for {today}", flush=True)
    return True


def sector_breadth_from_universe(
    universe: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convenience: compute breadth-weighted sector composition against the
    static INDUSTRY_GROUPS basket map."""
    try:
        from .industry import INDUSTRY_GROUPS
    except Exception:
        return []
    return sector_breadth(universe, INDUSTRY_GROUPS)
