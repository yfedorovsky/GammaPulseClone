"""King Breakout Detector — gamma-squeeze trigger signal.

Sibling to king_migration.py. Documented 2026-04-23 after missing
Mir's live $ARM 220C trade at 9:53 AM ($4.35 → $7.50 in 80 min).

## The pattern

Migration detector catches: new call OI accumulates *above* spot → king
migrates up → spot follows. That's the slow runner pattern.

Breakout detector catches the *opposite*: spot accumulates momentum and
breaks THROUGH a stable king from below. The king hasn't migrated yet;
spot arrived first. Dealers who are short those calls now HAVE to hedge,
which unwinds the positive gamma wall and accelerates price.

## Example — ARM 4/23 missed trade

  09:29 AM: spot $196.57, king $200, pos/neg 10.14 (structure ready)
  09:49 AM: spot $199.20 (approaching king)
  09:53 AM: Mir buys 220C @ $4.35 (reads the impending breakout)
  10:14 AM: spot $201.17 (broke through) — our signal flipped SUPPORT
  11:04 AM: spot $208.48 (+4% from breakout)

  Our prior behavior: PINNING PREMIUM SELL at 10:05 — told user to
  SELL premium at the exact moment Mir was buying calls for the squeeze.

## The 5-gate qualifier

  1. Spot just crossed king from below (prev < king, cur >= king)
  2. Pos/neg ratio >= RATIO_GATE (mature structure — dealers meaningfully
     short the calls = hedging pressure on breakout)
  3. King stable for >= KING_STABILITY_MIN_SEC (not a recent migration —
     if king just moved, spot is *chasing* the new king, not breaking out
     of an entrenched one)
  4. Last signal was MAGNET UP (bullish approach, not PINNING chop)
  5. Net delta positive (dealers net short — forced chasing on breakout)

## Intended use

  Historical: run_backfill_with_returns() computes hit rates across N
  days to validate signal quality BEFORE live-wiring.

  Live (later): poll every eval cycle per ticker, fire alert on qualify.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


# ── Configuration ─────────────────────────────────────────────────

# Minimum pos/neg ratio before breakout. ARM 4/23 was at 10.14, so 3.0
# is conservative but catches more marginal setups. Lower = more noise.
RATIO_GATE = 3.0

# King must have been stable at this level for at least N seconds BEFORE
# spot broke through. This distinguishes a breakout-through-stable-king
# (what we want) from spot chasing a just-migrated king (different trade).
KING_STABILITY_MIN_SEC = 2 * 3600  # 2 hours

# Maximum lookback for "previous" snapshot — if prior data point is
# >45 min ago, assume it's pre-market or after-hours and skip.
PREV_LOOKBACK_SEC = 45 * 60

# Storage
KING_BREAKOUT_DB_PATH = os.environ.get("KING_BREAKOUT_DB_PATH", "./king_breakouts.db")

KING_BREAKOUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS king_breakouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  breakout_ts INTEGER NOT NULL,
  breakout_iso TEXT NOT NULL,
  king REAL,
  spot_before REAL,
  spot_break REAL,
  breakout_pct REAL,
  ratio_at_break REAL,
  net_delta_at_break REAL,
  king_stable_sec INTEGER,
  prev_signal TEXT,
  cur_signal TEXT,
  floor REAL,
  ceiling REAL,
  gate_crossed INTEGER,
  gate_ratio INTEGER,
  gate_stability INTEGER,
  gate_magnet_up INTEGER,
  gate_net_delta INTEGER,
  qualified INTEGER NOT NULL,
  qualified_reasons TEXT,
  fwd_return_30m REAL,
  fwd_return_60m REAL,
  fwd_return_2h REAL,
  fwd_return_4h REAL,
  fwd_ceiling_hit INTEGER,
  UNIQUE(ticker, breakout_ts)
);
CREATE INDEX IF NOT EXISTS idx_kb_ts ON king_breakouts(breakout_ts);
CREATE INDEX IF NOT EXISTS idx_kb_ticker ON king_breakouts(ticker, breakout_ts);
CREATE INDEX IF NOT EXISTS idx_kb_qualified ON king_breakouts(qualified, breakout_ts);
"""


# ── Data structures ───────────────────────────────────────────────


@dataclass
class Snapshot:
    ticker: str
    ts: int
    spot: float | None
    king: float | None
    floor: float | None
    ceiling: float | None
    pos_gex: float | None
    neg_gex: float | None
    net_delta: float | None
    signal: str | None

    @property
    def ratio(self) -> float:
        pos = self.pos_gex or 0
        neg = abs(self.neg_gex or 0)
        return pos / neg if neg > 0 else 0.0


@dataclass
class BreakoutEvent:
    ticker: str
    breakout_ts: int
    before: Snapshot
    after: Snapshot
    king_stable_sec: int = 0

    # Gate outcomes
    gate_crossed: bool = False
    gate_ratio: bool = False
    gate_stability: bool = False
    gate_magnet_up: bool = False
    gate_net_delta: bool = False
    reasons: list[str] = field(default_factory=list)

    # Forward-return backtest fields (populated post-detection)
    fwd_return_30m: float | None = None
    fwd_return_60m: float | None = None
    fwd_return_2h: float | None = None
    fwd_return_4h: float | None = None
    fwd_ceiling_hit: bool = False

    @property
    def qualified(self) -> bool:
        return all([
            self.gate_crossed,
            self.gate_ratio,
            self.gate_stability,
            self.gate_magnet_up,
            self.gate_net_delta,
        ])

    @property
    def breakout_pct(self) -> float:
        king = self.after.king or 0
        spot = self.after.spot or 0
        return ((spot - king) / king * 100) if king else 0.0

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "breakout_ts": self.breakout_ts,
            "breakout_iso": dt.datetime.utcfromtimestamp(self.breakout_ts).isoformat() + "Z",
            "king": self.after.king,
            "spot_before": self.before.spot,
            "spot_break": self.after.spot,
            "breakout_pct": round(self.breakout_pct, 3),
            "ratio_at_break": round(self.after.ratio, 3),
            "net_delta_at_break": self.after.net_delta,
            "king_stable_sec": self.king_stable_sec,
            "prev_signal": self.before.signal,
            "cur_signal": self.after.signal,
            "floor": self.after.floor,
            "ceiling": self.after.ceiling,
            "gate_crossed": int(self.gate_crossed),
            "gate_ratio": int(self.gate_ratio),
            "gate_stability": int(self.gate_stability),
            "gate_magnet_up": int(self.gate_magnet_up),
            "gate_net_delta": int(self.gate_net_delta),
            "qualified": int(self.qualified),
            "qualified_reasons": " | ".join(self.reasons),
            "fwd_return_30m": self.fwd_return_30m,
            "fwd_return_60m": self.fwd_return_60m,
            "fwd_return_2h": self.fwd_return_2h,
            "fwd_return_4h": self.fwd_return_4h,
            "fwd_ceiling_hit": int(self.fwd_ceiling_hit),
        }


# ── Core detection ────────────────────────────────────────────────


def _king_stable_duration(snapshots: list[Snapshot], idx: int) -> int:
    """Seconds the king at snapshots[idx] has been at its current value
    in the preceding snapshot series. Returns 0 if we can't determine."""
    if idx <= 0:
        return 0
    cur_king = snapshots[idx].king
    if cur_king is None:
        return 0
    # Walk backward until king changes
    for j in range(idx - 1, -1, -1):
        if snapshots[j].king != cur_king:
            # Stability started at j+1
            return snapshots[idx].ts - snapshots[j + 1].ts
    # Never changed in the window we have
    return snapshots[idx].ts - snapshots[0].ts


def _qualify_gates(before: Snapshot, after: Snapshot, king_stable_sec: int) -> BreakoutEvent:
    ev = BreakoutEvent(
        ticker=after.ticker,
        breakout_ts=after.ts,
        before=before,
        after=after,
        king_stable_sec=king_stable_sec,
    )

    # 1. Spot crossed king from below
    if (before.spot is None or after.spot is None or after.king is None
            or before.king is None):
        ev.reasons.append("missing spot/king")
        return ev
    ev.gate_crossed = (before.spot < before.king) and (after.spot >= after.king)
    if not ev.gate_crossed:
        ev.reasons.append(
            f"no crossing (prev=${before.spot:.2f}/${before.king:.0f}, "
            f"cur=${after.spot:.2f}/${after.king:.0f})"
        )
    else:
        ev.reasons.append(f"crossed ${after.king:.0f} ({after.spot:.2f} vs {before.spot:.2f})")

    # 2. Ratio at break
    r = after.ratio
    ev.gate_ratio = r >= RATIO_GATE
    if not ev.gate_ratio:
        ev.reasons.append(f"pos/neg {r:.2f} < {RATIO_GATE}")
    else:
        ev.reasons.append(f"pos/neg {r:.2f}")

    # 3. King stability
    ev.gate_stability = king_stable_sec >= KING_STABILITY_MIN_SEC
    if not ev.gate_stability:
        ev.reasons.append(f"king stable only {king_stable_sec//60}min")
    else:
        ev.reasons.append(f"king stable {king_stable_sec//3600}h")

    # 4. Prior signal was bullish-structural (MAGNET UP or high-ratio PINNING).
    # PINNING at the king edge with strong pos/neg is the transitional state
    # right BEFORE a breakout — excluding it (original design) blocked ARM
    # today's live trade. Accept it when pos/neg ≥ 5 (mature bull structure
    # gives PINNING a directional bias toward breakout-up, not fade-down).
    prev_sig = before.signal
    if prev_sig == "MAGNET UP":
        ev.gate_magnet_up = True
        ev.reasons.append("prev MAGNET UP")
    elif prev_sig == "PINNING" and before.ratio >= 5.0:
        ev.gate_magnet_up = True
        ev.reasons.append(f"prev PINNING (pos/neg {before.ratio:.1f} ≥ 5)")
    else:
        ev.gate_magnet_up = False
        ev.reasons.append(f"prev signal={prev_sig} (ratio {before.ratio:.1f}) not bullish-structural")

    # 5. Net delta positive at breakout moment
    nd = after.net_delta or 0
    ev.gate_net_delta = nd > 0
    if not ev.gate_net_delta:
        ev.reasons.append(f"net_delta {nd/1e6:.1f}M not positive")
    else:
        ev.reasons.append(f"net_delta {nd/1e6:.1f}M")

    return ev


def detect_breakouts_for_ticker(
    ticker: str, snapshots: list[Snapshot]
) -> list[BreakoutEvent]:
    """Walk forward through a time-ordered snapshot series; emit a
    BreakoutEvent whenever spot crosses king from below."""
    events: list[BreakoutEvent] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        cur = snapshots[i]
        if prev.spot is None or cur.spot is None:
            continue
        if prev.king is None or cur.king is None:
            continue
        if (cur.ts - prev.ts) > PREV_LOOKBACK_SEC:
            continue
        # Detect crossing: prev below king, cur at or above king
        if prev.spot < prev.king and cur.spot >= cur.king:
            stab = _king_stable_duration(snapshots, i)
            events.append(_qualify_gates(prev, cur, stab))
    return events


# ── Forward-return computation ────────────────────────────────────


def compute_forward_returns(
    ev: BreakoutEvent,
    all_snapshots: list[Snapshot],
    idx: int,
) -> None:
    """Populate ev.fwd_return_* by looking forward in the snapshot series.
    idx = index in all_snapshots of the breakout event."""
    breakout_spot = ev.after.spot or 0
    if breakout_spot <= 0:
        return
    ceiling = ev.after.ceiling or 0
    horizons_sec = {
        "fwd_return_30m": 30 * 60,
        "fwd_return_60m": 60 * 60,
        "fwd_return_2h": 2 * 60 * 60,
        "fwd_return_4h": 4 * 60 * 60,
    }
    for field_name, target_sec in horizons_sec.items():
        target_ts = ev.breakout_ts + target_sec
        # Find closest snapshot at or after target_ts
        for j in range(idx + 1, len(all_snapshots)):
            s = all_snapshots[j]
            if s.ts >= target_ts and s.spot is not None:
                ret = (s.spot - breakout_spot) / breakout_spot * 100
                setattr(ev, field_name, round(ret, 3))
                break
    # Did price reach ceiling within 4h?
    if ceiling > breakout_spot:
        window_end = ev.breakout_ts + 4 * 60 * 60
        for j in range(idx + 1, len(all_snapshots)):
            s = all_snapshots[j]
            if s.ts > window_end:
                break
            if s.spot is not None and s.spot >= ceiling:
                ev.fwd_ceiling_hit = True
                break


# ── Persistence ───────────────────────────────────────────────────


_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    conn = sqlite3.connect(KING_BREAKOUT_DB_PATH)
    try:
        conn.executescript(KING_BREAKOUT_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _schema_ready = True


def persist_event(ev: BreakoutEvent) -> None:
    _ensure_schema()
    r = ev.to_row()
    conn = sqlite3.connect(KING_BREAKOUT_DB_PATH)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO king_breakouts (
              ticker, breakout_ts, breakout_iso,
              king, spot_before, spot_break, breakout_pct,
              ratio_at_break, net_delta_at_break, king_stable_sec,
              prev_signal, cur_signal, floor, ceiling,
              gate_crossed, gate_ratio, gate_stability, gate_magnet_up, gate_net_delta,
              qualified, qualified_reasons,
              fwd_return_30m, fwd_return_60m, fwd_return_2h, fwd_return_4h,
              fwd_ceiling_hit
            ) VALUES (
              ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?, ?, ?,
              ?, ?,
              ?, ?, ?, ?,
              ?
            )
            """,
            (
                r["ticker"], r["breakout_ts"], r["breakout_iso"],
                r["king"], r["spot_before"], r["spot_break"], r["breakout_pct"],
                r["ratio_at_break"], r["net_delta_at_break"], r["king_stable_sec"],
                r["prev_signal"], r["cur_signal"], r["floor"], r["ceiling"],
                r["gate_crossed"], r["gate_ratio"], r["gate_stability"],
                r["gate_magnet_up"], r["gate_net_delta"],
                r["qualified"], r["qualified_reasons"],
                r["fwd_return_30m"], r["fwd_return_60m"], r["fwd_return_2h"], r["fwd_return_4h"],
                r["fwd_ceiling_hit"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_recent(
    limit: int = 100,
    ticker: str | None = None,
    qualified_only: bool = False,
) -> list[dict[str, Any]]:
    _ensure_schema()
    conn = sqlite3.connect(KING_BREAKOUT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM king_breakouts WHERE 1=1"
        params: list[Any] = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        if qualified_only:
            sql += " AND qualified = 1"
        sql += " ORDER BY breakout_ts DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Snapshot source adapter ───────────────────────────────────────


# ── Live detection loop (added 2026-05-06) ───────────────────────
#
# Polls the worker's in-memory cache for spot-crosses-king-from-below
# events on each scan cycle. Sibling to king_migration.run_..._live_loop
# but triggers on the breakout pattern (spot through stable king) instead
# of the migration pattern (king itself jumping).
#
# Missed DELL 2026-05-06 9:40 AM cross of king $220 ($216 → $222.20)
# because the breakout detector was backfill-only.
#
# Design:
#  - Per-ticker FULL prior state cached (not just spot/king — we need
#    the prior pos_gex/neg_gex/net_delta/signal for the `before` Snapshot,
#    otherwise gates that compare before vs after collapse to identity).
#    See king_migration live-loop bug 2026-05-06 for the cautionary tale.
#  - On each tick: build current Snapshot, compare spot/king to prior.
#    If prev.spot < prev.king and cur.spot >= cur.king → qualify gates.
#  - Persist regardless; Telegram-fire only if qualified + cooldown elapsed.

import asyncio


_live_last_state: dict[str, Snapshot] = {}  # ticker -> last full Snapshot
_live_last_fired: dict[str, int] = {}       # ticker -> ts of last Telegram fire
LIVE_FIRE_COOLDOWN_SEC = 60 * 60  # 1 hour per ticker


def _snapshot_from_cache_state(ticker: str, state: dict, ts: int) -> Snapshot | None:
    spot = state.get("actual_spot") or state.get("_spot")
    king = state.get("king")
    if not spot or not king:
        return None
    return Snapshot(
        ticker=ticker, ts=ts,
        spot=spot, king=king,
        floor=state.get("floor"), ceiling=state.get("ceiling"),
        pos_gex=state.get("pos_gex"), neg_gex=state.get("neg_gex"),
        net_delta=state.get("net_delta"), signal=state.get("signal") or "",
    )


def _stable_duration_from_history(
    history: list[Snapshot], current_king: float, now_ts: int
) -> int:
    """Walk backward through prior snapshots; return seconds the king has
    held its current value. Cache history is short (one prior snap), so
    fall back to the in-memory tracking. Returns 0 if unknown."""
    if not history:
        return 0
    for snap in reversed(history):
        if snap.king != current_king:
            return now_ts - snap.ts
    return now_ts - history[0].ts


_live_king_history: dict[str, list[tuple[int, float]]] = {}  # ticker -> [(ts, king),...]
_LIVE_KING_HISTORY_LIMIT = 50  # ~25 minutes at 30s ticks


async def _send_king_breakout_telegram(ev: BreakoutEvent) -> None:
    from .alert_gates import should_send_alert
    ok, reason = should_send_alert()
    if not ok:
        print(f"[KING_BRK] gated ({reason}) — {ev.ticker} ${ev.after.spot:.2f} through ${ev.after.king:.0f}")
        return
    try:
        from .telegram import send
    except ImportError:
        return
    text = (
        f"🚀 KING BREAKOUT: {ev.ticker}\n"
        f"Spot ${ev.before.spot:.2f} → ${ev.after.spot:.2f} through king ${ev.after.king:.0f}\n"
        f"Pos/Neg: {ev.after.ratio:.2f}  |  Net Δ: {(ev.after.net_delta or 0)/1e6:.1f}M\n"
        f"King stable {ev.king_stable_sec//3600}h{(ev.king_stable_sec%3600)//60}m\n"
        f"\n"
        f"Play: buy ${ev.after.king:.0f} call, 5-10 DTE, "
        f"stop on spot < ${ev.after.king * 0.99:.2f}"
    )
    try:
        await send(text, ticker=ev.ticker)
    except Exception as e:
        print(f"[KING_BRK] telegram failed: {e}")


async def _check_ticker_live(ticker: str, state: dict) -> None:
    now_ts = int(time.time())
    cur = _snapshot_from_cache_state(ticker, state, now_ts)
    if cur is None:
        return

    # Track king history for stability calc (cheap, bounded).
    hist = _live_king_history.setdefault(ticker, [])
    if not hist or hist[-1][1] != cur.king:
        hist.append((cur.ts, cur.king))
        if len(hist) > _LIVE_KING_HISTORY_LIMIT:
            del hist[: len(hist) - _LIVE_KING_HISTORY_LIMIT]

    prev = _live_last_state.get(ticker)
    _live_last_state[ticker] = cur

    if prev is None:
        return
    if prev.spot is None or prev.king is None or cur.spot is None or cur.king is None:
        return

    # Detect crossing: prev below king, cur at or above king.
    if not (prev.spot < prev.king and cur.spot >= cur.king):
        return

    # King-stability lookup. Find the earliest entry in history that has
    # the same king as `cur` and isn't followed by a different king.
    stable_sec = 0
    for ts, k in hist:
        if k == cur.king:
            stable_sec = cur.ts - ts
            break

    ev = _qualify_gates(prev, cur, stable_sec)

    try:
        persist_event(ev)
    except Exception as e:
        print(f"[KING_BRK] persist error {ticker}: {e}")

    if ev.qualified:
        last_fire = _live_last_fired.get(ticker, 0)
        if now_ts - last_fire >= LIVE_FIRE_COOLDOWN_SEC:
            _live_last_fired[ticker] = now_ts
            print(
                f"[KING_BRK] QUALIFIED {ticker}  "
                f"spot ${prev.spot:.2f}->${cur.spot:.2f} king ${cur.king:.0f} "
                f"ratio {cur.ratio:.2f} stable {stable_sec//60}m"
            )
            asyncio.create_task(_send_king_breakout_telegram(ev))


async def run_king_breakout_live_loop(stop_event) -> None:
    """Background task — poll cache every 30s for spot-through-king events.

    Integration: started from main.py lifespan alongside king_migration.
    """
    from .cache import cache

    print("[KING_BRK] live loop starting — interval=30s")
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=60.0)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            snapshot = await cache.snapshot()
            for ticker, state in snapshot.items():
                try:
                    await _check_ticker_live(ticker, state)
                except Exception as e:
                    print(f"[KING_BRK] {ticker} check error: {e}")
        except Exception as e:
            print(f"[KING_BRK] loop error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30.0)
            break
        except asyncio.TimeoutError:
            pass

    print("[KING_BRK] live loop stopped")


# ── Snapshot source adapter ───────────────────────────────────────


def load_snapshots_from_db(
    snapshot_db_path: str, ticker: str, since_ts: int = 0,
) -> list[Snapshot]:
    conn = sqlite3.connect(snapshot_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT ts, spot, king, floor, ceiling, pos_gex, neg_gex,
                   net_delta, signal
            FROM snapshots
            WHERE ticker = ? AND ts >= ?
            ORDER BY ts ASC
            """,
            (ticker.upper(), since_ts),
        )
        return [Snapshot(
            ticker=ticker.upper(), ts=int(r["ts"]),
            spot=r["spot"], king=r["king"], floor=r["floor"], ceiling=r["ceiling"],
            pos_gex=r["pos_gex"], neg_gex=r["neg_gex"],
            net_delta=r["net_delta"], signal=r["signal"],
        ) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Backtest CLI ──────────────────────────────────────────────────


def run_backfill_with_returns(
    snapshot_db_path: str = "./snapshots.db",
    tickers: Iterable[str] | None = None,
    since_days: int = 14,
) -> dict[str, Any]:
    """Detect breakouts + compute forward returns + persist.

    Returns aggregate stats including hit rate (positive-return fraction)
    and avg forward return by horizon — the core backtest output.
    """
    if tickers is None:
        conn = sqlite3.connect(snapshot_db_path)
        try:
            since_ts = int(time.time()) - since_days * 86400
            cur = conn.execute(
                "SELECT DISTINCT ticker FROM snapshots WHERE ts >= ?",
                (since_ts,),
            )
            tickers = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
    tickers = list(tickers)
    since_ts = int(time.time()) - since_days * 86400

    total = 0
    qualified_evs: list[BreakoutEvent] = []
    for ticker in tickers:
        snaps = load_snapshots_from_db(snapshot_db_path, ticker, since_ts=since_ts)
        if len(snaps) < 3:
            continue
        events = detect_breakouts_for_ticker(ticker, snaps)
        # For each event, compute forward returns + persist
        # Build index map: ts -> index for fast lookup
        ts_to_idx = {s.ts: i for i, s in enumerate(snaps)}
        for ev in events:
            idx = ts_to_idx.get(ev.after.ts)
            if idx is not None:
                compute_forward_returns(ev, snaps, idx)
            persist_event(ev)
            total += 1
            if ev.qualified:
                qualified_evs.append(ev)

    # Aggregate stats for qualified events
    def _stats(events: list[BreakoutEvent], field_name: str) -> dict[str, Any]:
        vals = [getattr(e, field_name) for e in events if getattr(e, field_name) is not None]
        if not vals:
            return {"n": 0, "avg": None, "hit_rate": None}
        wins = sum(1 for v in vals if v > 0)
        return {
            "n": len(vals),
            "avg_pct": round(sum(vals) / len(vals), 3),
            "hit_rate_pct": round(wins / len(vals) * 100, 1),
            "max_pct": round(max(vals), 3),
            "min_pct": round(min(vals), 3),
        }

    ceiling_hits = sum(1 for e in qualified_evs if e.fwd_ceiling_hit)

    return {
        "tickers_scanned": len(tickers),
        "events_total": total,
        "events_qualified": len(qualified_evs),
        "ceiling_hit_rate": (
            round(ceiling_hits / len(qualified_evs) * 100, 1)
            if qualified_evs else None
        ),
        "by_horizon": {
            "30m": _stats(qualified_evs, "fwd_return_30m"),
            "60m": _stats(qualified_evs, "fwd_return_60m"),
            "2h":  _stats(qualified_evs, "fwd_return_2h"),
            "4h":  _stats(qualified_evs, "fwd_return_4h"),
        },
    }


if __name__ == "__main__":
    import sys
    since_days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(f"Running king-breakout backfill + backtest — last {since_days} days…")
    summary = run_backfill_with_returns(since_days=since_days)
    print(json.dumps(summary, indent=2))
