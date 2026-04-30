"""Floor Migration Detector — structural support shift signal.

Mirrors king_migration.py but tracks the FLOOR (highest negative-GEX put wall
acting as support). Floor changes are bullish-reversal tells when floor moves
UP after price has tested the prior floor — dealers re-establishing long-put
positioning at a higher level = stronger structural bid.

## Why this matters (Apr 28 2026 finding)

QQQ's floor flipped 7× during the session: 655 → 645 → 655 → 645 → 655 →
645 → 655. The last flip 645→655 happened at 13:30:07, exactly coinciding
with the bottom of the day at $654.80 and the start of the rip to $659+.
The system tracked it (snapshots.db) but didn't surface it as an alert.

## Floor migration semantics

  Floor UP migration:
    - Bullish reversal signal (especially after price had broken below)
    - Dealer put-wall reconstituting at higher level
    - "FLOOR RECLAIM" pattern: floor X → Y → X again ⇒ Y was a flush

  Floor DOWN migration:
    - Bearish breakdown signal
    - Support level capitulating downward
    - Often precedes acceleration of a downtrend

## The 5-gate qualifier (UP migration)

  1. Floor jumped up by ≥ MIN_MIGRATION_PTS
  2. Spot is at or above new floor (floor is acting as support, not gap)
  3. Pos/Neg ratio not deteriorating (no concurrent gex blowout)
  4. King above spot (room to magnet up — confirms bullish structure)
  5. Floor RECLAIM: new floor matches a prior floor that was broken in
     last RECLAIM_LOOKBACK_SEC (the killer gate — distinguishes new
     accumulation from random noise)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .king_migration import Snapshot, load_snapshots_from_db


# ── Configuration ─────────────────────────────────────────────────

# Minimum floor jump in dollars. Smaller than king (more granular) since
# floors move with put-wall reshuffling. QQQ 645→655 = +10, SPY +1 to +3
# typical per ARM/SPY data. Use 2 to catch index-level reclaims.
MIN_MIGRATION_PTS = 2

# Lookback for "reclaim" pattern detection — was this floor a prior floor
# that was broken? Default 90 min covers a typical chop session and the
# QQQ 645↔655 pattern (~30 min between flips today).
RECLAIM_LOOKBACK_SEC = 90 * 60

# Window — same as king. 4h covers overnight + premarket without crossing
# day baselines.
PREV_LOOKBACK_SEC = 4 * 3600

FLOOR_MIGRATION_DB_PATH = os.environ.get(
    "FLOOR_MIGRATION_DB_PATH", "./floor_migrations.db"
)

FLOOR_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS floor_migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  migration_ts INTEGER NOT NULL,
  migration_iso TEXT NOT NULL,
  direction TEXT NOT NULL,            -- 'UP' or 'DOWN'
  old_floor REAL,
  new_floor REAL,
  delta_pts REAL,
  old_king REAL,
  new_king REAL,
  spot REAL,
  signal TEXT,
  regime TEXT,
  ratio_before REAL,
  ratio_after REAL,
  net_delta_before REAL,
  net_delta_after REAL,
  is_reclaim INTEGER,                 -- 1 if new_floor matches prior broken floor
  reclaim_age_sec INTEGER,            -- seconds since floor was at this level
  gate_min_jump INTEGER,
  gate_spot_above_floor INTEGER,
  gate_ratio_stable INTEGER,
  gate_king_above_spot INTEGER,
  gate_reclaim INTEGER,
  qualified INTEGER NOT NULL,
  qualified_reasons TEXT,
  UNIQUE(ticker, migration_ts)
);
CREATE INDEX IF NOT EXISTS idx_fmig_ts ON floor_migrations(migration_ts);
CREATE INDEX IF NOT EXISTS idx_fmig_ticker ON floor_migrations(ticker, migration_ts);
CREATE INDEX IF NOT EXISTS idx_fmig_qualified ON floor_migrations(qualified, migration_ts);
CREATE INDEX IF NOT EXISTS idx_fmig_direction ON floor_migrations(direction, migration_ts);
"""


@dataclass
class FloorMigrationEvent:
    ticker: str
    migration_ts: int
    direction: str  # "UP" or "DOWN"
    before: Snapshot
    after: Snapshot
    is_reclaim: bool = False
    reclaim_age_sec: int | None = None

    gate_min_jump: bool = False
    gate_spot_above_floor: bool = False
    gate_ratio_stable: bool = False
    gate_king_above_spot: bool = False
    gate_reclaim: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> bool:
        # UP migrations qualify on all 5 gates
        # DOWN migrations qualify if any breakdown indicator is set —
        # we record but don't gate symmetrically (different alert class)
        if self.direction == "UP":
            return all([
                self.gate_min_jump,
                self.gate_spot_above_floor,
                self.gate_ratio_stable,
                self.gate_king_above_spot,
                self.gate_reclaim,
            ])
        else:
            # DOWN: just record; "qualified" means significant breakdown
            return self.gate_min_jump and not self.gate_spot_above_floor

    @property
    def delta_pts(self) -> float:
        return (self.after.floor or 0) - (self.before.floor or 0)

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "migration_ts": self.migration_ts,
            "migration_iso": dt.datetime.utcfromtimestamp(self.migration_ts).isoformat() + "Z",
            "direction": self.direction,
            "old_floor": self.before.floor,
            "new_floor": self.after.floor,
            "delta_pts": self.delta_pts,
            "old_king": self.before.king,
            "new_king": self.after.king,
            "spot": self.after.spot,
            "signal": self.after.signal,
            "regime": getattr(self.after, "regime", None),
            "ratio_before": round(self.before.ratio, 3),
            "ratio_after": round(self.after.ratio, 3),
            "net_delta_before": self.before.net_delta,
            "net_delta_after": self.after.net_delta,
            "is_reclaim": int(self.is_reclaim),
            "reclaim_age_sec": self.reclaim_age_sec,
            "gate_min_jump": int(self.gate_min_jump),
            "gate_spot_above_floor": int(self.gate_spot_above_floor),
            "gate_ratio_stable": int(self.gate_ratio_stable),
            "gate_king_above_spot": int(self.gate_king_above_spot),
            "gate_reclaim": int(self.gate_reclaim),
            "qualified": int(self.qualified),
            "qualified_reasons": " | ".join(self.reasons),
        }


def _qualify_gates_up(
    before: Snapshot,
    after: Snapshot,
    history: list[Snapshot],
) -> FloorMigrationEvent:
    """Run gates for an UP-migration. history = prior snapshots for reclaim check."""
    ev = FloorMigrationEvent(
        ticker=after.ticker, migration_ts=after.ts, direction="UP",
        before=before, after=after,
    )
    dp = ev.delta_pts

    # 1. Min jump
    ev.gate_min_jump = dp >= MIN_MIGRATION_PTS
    if not ev.gate_min_jump:
        ev.reasons.append(f"jump {dp:+.1f}pts below threshold")
    else:
        ev.reasons.append(f"floor +${dp:.0f}")

    # 2. Spot at or above new floor (floor is acting as support, not far above)
    spot = after.spot or 0
    new_floor = after.floor or 0
    # Tolerance: spot can be up to 0.5% below new floor (just-broken-and-coming-back)
    tol = new_floor * 0.005
    ev.gate_spot_above_floor = spot >= (new_floor - tol)
    if not ev.gate_spot_above_floor:
        ev.reasons.append(f"spot ${spot:.2f} below new floor ${new_floor:.0f} (>0.5%)")
    else:
        ev.reasons.append(f"spot ${spot:.2f} ≥ floor ${new_floor:.0f}")

    # 3. Ratio not deteriorating
    r_before = before.ratio
    r_after = after.ratio
    ev.gate_ratio_stable = r_after >= 0.5  # avoid full inversion
    if not ev.gate_ratio_stable:
        ev.reasons.append(f"ratio inverted {r_after:.2f}")
    else:
        ev.reasons.append(f"ratio {r_before:.2f}→{r_after:.2f}")

    # 4. King above spot
    king = after.king or 0
    ev.gate_king_above_spot = king > spot
    if not ev.gate_king_above_spot:
        ev.reasons.append(f"king ${king:.0f} not above spot ${spot:.2f}")
    else:
        ev.reasons.append(f"king ${king:.0f} above spot")

    # 5. Reclaim — was new_floor a prior floor that was broken?
    # Walk back through history for a snapshot whose floor == new_floor
    cutoff = after.ts - RECLAIM_LOOKBACK_SEC
    reclaim_snap: Snapshot | None = None
    for h in reversed(history):
        if h.ts < cutoff:
            break
        if h.ts >= before.ts:
            continue
        if h.floor is None:
            continue
        # Match within $0.50 (handles fractional-strike tickers)
        if abs(h.floor - new_floor) <= 0.5:
            reclaim_snap = h
            break
    ev.is_reclaim = reclaim_snap is not None
    ev.gate_reclaim = ev.is_reclaim
    if reclaim_snap is not None:
        age = after.ts - reclaim_snap.ts
        ev.reclaim_age_sec = age
        ev.reasons.append(f"RECLAIM (broken {age // 60}min ago)")
    else:
        ev.reasons.append("no prior floor at this level (not a reclaim)")

    return ev


def _qualify_gates_down(
    before: Snapshot, after: Snapshot
) -> FloorMigrationEvent:
    """Lighter gates for DOWN — we just want to record breakdowns."""
    ev = FloorMigrationEvent(
        ticker=after.ticker, migration_ts=after.ts, direction="DOWN",
        before=before, after=after,
    )
    dp = abs(ev.delta_pts)
    ev.gate_min_jump = dp >= MIN_MIGRATION_PTS
    if ev.gate_min_jump:
        ev.reasons.append(f"floor -${dp:.0f}")
    spot = after.spot or 0
    nf = after.floor or 0
    ev.gate_spot_above_floor = spot >= nf
    if not ev.gate_spot_above_floor:
        ev.reasons.append(f"BREAKDOWN — spot ${spot:.2f} below new floor ${nf:.0f}")
    return ev


def detect_floor_migrations_for_ticker(
    ticker: str, snapshots: list[Snapshot]
) -> list[FloorMigrationEvent]:
    """Walk forward through snapshots; record floor changes UP and DOWN."""
    events: list[FloorMigrationEvent] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        cur = snapshots[i]
        if prev.floor is None or cur.floor is None:
            continue
        if (cur.ts - prev.ts) > PREV_LOOKBACK_SEC:
            continue
        delta = cur.floor - prev.floor
        if abs(delta) < MIN_MIGRATION_PTS:
            continue
        if delta > 0:
            ev = _qualify_gates_up(prev, cur, snapshots[:i])
        else:
            ev = _qualify_gates_down(prev, cur)
        events.append(ev)
    return events


# ── Persistence ───────────────────────────────────────────────────


_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    conn = sqlite3.connect(FLOOR_MIGRATION_DB_PATH)
    try:
        conn.executescript(FLOOR_MIGRATION_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _schema_ready = True


def persist_event(ev: FloorMigrationEvent) -> None:
    _ensure_schema()
    row = ev.to_row()
    conn = sqlite3.connect(FLOOR_MIGRATION_DB_PATH)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO floor_migrations (
              ticker, migration_ts, migration_iso, direction,
              old_floor, new_floor, delta_pts,
              old_king, new_king, spot, signal, regime,
              ratio_before, ratio_after,
              net_delta_before, net_delta_after,
              is_reclaim, reclaim_age_sec,
              gate_min_jump, gate_spot_above_floor, gate_ratio_stable,
              gate_king_above_spot, gate_reclaim,
              qualified, qualified_reasons
            ) VALUES (
              ?, ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?,
              ?, ?, ?, ?, ?,
              ?, ?
            )
            """,
            (
                row["ticker"], row["migration_ts"], row["migration_iso"], row["direction"],
                row["old_floor"], row["new_floor"], row["delta_pts"],
                row["old_king"], row["new_king"], row["spot"], row["signal"], row["regime"],
                row["ratio_before"], row["ratio_after"],
                row["net_delta_before"], row["net_delta_after"],
                row["is_reclaim"], row["reclaim_age_sec"],
                row["gate_min_jump"], row["gate_spot_above_floor"], row["gate_ratio_stable"],
                row["gate_king_above_spot"], row["gate_reclaim"],
                row["qualified"], row["qualified_reasons"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_recent(
    limit: int = 100,
    ticker: str | None = None,
    qualified_only: bool = False,
    direction: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_schema()
    conn = sqlite3.connect(FLOOR_MIGRATION_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM floor_migrations WHERE 1=1"
        params: list[Any] = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        if qualified_only:
            sql += " AND qualified = 1"
        if direction:
            sql += " AND direction = ?"
            params.append(direction.upper())
        sql += " ORDER BY migration_ts DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def run_backfill(
    snapshot_db_path: str = "./snapshots.db",
    tickers: Iterable[str] | None = None,
    since_days: int = 14,
) -> dict[str, Any]:
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

    since_ts = int(time.time()) - since_days * 86400
    total = up = down = qualified = reclaims = 0
    by_ticker: dict[str, dict[str, int]] = {}
    for ticker in tickers:
        snaps = load_snapshots_from_db(snapshot_db_path, ticker, since_ts=since_ts)
        events = detect_floor_migrations_for_ticker(ticker, snaps)
        u = sum(1 for e in events if e.direction == "UP")
        d = sum(1 for e in events if e.direction == "DOWN")
        q = sum(1 for e in events if e.qualified)
        rc = sum(1 for e in events if e.is_reclaim)
        total += len(events); up += u; down += d; qualified += q; reclaims += rc
        by_ticker[ticker] = {"events": len(events), "up": u, "down": d,
                             "qualified": q, "reclaims": rc}
        for e in events:
            persist_event(e)
    return {
        "tickers_scanned": len(list(tickers)),
        "events_total": total, "up": up, "down": down,
        "qualified_up": qualified, "reclaims": reclaims,
        "by_ticker": by_ticker,
    }


# ── Live detection loop ──────────────────────────────────────────
# Mirrors king_migration live loop. Polls cache every 30s for floor
# changes; persists every change, fires shadow Telegram on qualified UP.
import asyncio


_live_last_floor: dict[str, tuple[float, int]] = {}
_live_last_fired: dict[str, int] = {}
LIVE_FIRE_COOLDOWN_SEC = 30 * 60  # 30 min cooldown


async def _send_floor_migration_telegram(ev: FloorMigrationEvent) -> None:
    """Shadow-mode Telegram. Tagged [SHADOW] — informational, not actionable."""
    from .alert_gates import should_send_alert
    ok, reason = should_send_alert()
    if not ok:
        print(f"[FLOOR_MIG] gated ({reason}) — {ev.ticker} ${ev.before.floor:.0f}->${ev.after.floor:.0f}")
        return
    try:
        from .telegram import send
    except ImportError:
        return
    tag = "RECLAIM" if ev.is_reclaim else "FLOOR ↑"
    text = (
        f"🛡 [SHADOW] {tag} — {ev.ticker}\n"
        f"Floor ${ev.before.floor or 0:.0f} → ${ev.after.floor or 0:.0f}  "
        f"(spot ${ev.after.spot or 0:.2f})\n"
        f"King ${ev.after.king or 0:.0f} | regime {getattr(ev.after, 'signal', '')}\n"
        f"Pos/Neg: {ev.before.ratio:.2f} → {ev.after.ratio:.2f}\n"
        f"Shadow mode — no action; data going to floor_migrations.db"
    )
    try:
        # force=True bypasses telegram.py's 1h per-ticker cooldown — same fix
        # as ST (Apr 29). Floor migrations have their own 30min LIVE_FIRE_COOLDOWN_SEC.
        result = await send(text, ticker=ev.ticker, force=True)
        if not result:
            print(f"[FLOOR_MIG] telegram returned False for {ev.ticker} (token/chat?)")
    except Exception as e:
        print(f"[FLOOR_MIG] telegram failed: {e}")


async def _check_ticker_live(ticker: str, state: dict) -> None:
    spot = state.get("actual_spot") or state.get("_spot") or 0
    floor = state.get("floor") or 0
    king = state.get("king") or 0
    pos_gex = state.get("pos_gex") or 0
    neg_gex = state.get("neg_gex") or 0
    net_delta = state.get("net_delta") or 0
    signal = state.get("signal") or ""
    ceiling = state.get("ceiling") or 0
    if not spot or not floor:
        return

    now_ts = int(time.time())
    last_floor, last_ts = _live_last_floor.get(ticker, (None, 0))
    if last_floor is None:
        _live_last_floor[ticker] = (floor, now_ts)
        return
    if floor == last_floor:
        _live_last_floor[ticker] = (floor, now_ts)
        return
    delta = floor - last_floor
    if abs(delta) < MIN_MIGRATION_PTS:
        _live_last_floor[ticker] = (floor, now_ts)
        return

    before = Snapshot(
        ticker=ticker, ts=last_ts, spot=spot, king=king,
        floor=last_floor, ceiling=ceiling, pos_gex=pos_gex, neg_gex=neg_gex,
        net_delta=net_delta, signal=signal,
    )
    after = Snapshot(
        ticker=ticker, ts=now_ts, spot=spot, king=king,
        floor=floor, ceiling=ceiling, pos_gex=pos_gex, neg_gex=neg_gex,
        net_delta=net_delta, signal=signal,
    )
    if delta > 0:
        # For reclaim check we'd need history; live loop uses simple gates only.
        # The "gate_reclaim" fails without history but we still record.
        ev = _qualify_gates_up(before, after, history=[])
    else:
        ev = _qualify_gates_down(before, after)

    try:
        persist_event(ev)
    except Exception as e:
        print(f"[FLOOR_MIG] persist error {ticker}: {e}")

    if ev.qualified:
        last_fire = _live_last_fired.get(ticker, 0)
        if now_ts - last_fire >= LIVE_FIRE_COOLDOWN_SEC:
            _live_last_fired[ticker] = now_ts
            print(f"[FLOOR_MIG] QUALIFIED {ticker} ${last_floor:.0f}->${floor:.0f} "
                  f"spot=${spot:.2f}")
            asyncio.create_task(_send_floor_migration_telegram(ev))

    _live_last_floor[ticker] = (floor, now_ts)


async def run_floor_migration_live_loop(stop_event) -> None:
    from .cache import cache
    print("[FLOOR_MIG] live loop starting — interval=30s (shadow mode)")
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
                    print(f"[FLOOR_MIG] {ticker} check error: {e}")
        except Exception as e:
            print(f"[FLOOR_MIG] loop error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30.0)
            break
        except asyncio.TimeoutError:
            pass
    print("[FLOOR_MIG] live loop stopped")


if __name__ == "__main__":
    import sys
    since_days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"Running floor-migration backfill — last {since_days} days...")
    summary = run_backfill(since_days=since_days)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_ticker"}, indent=2))
    by_t = summary["by_ticker"]
    top = sorted(by_t.items(), key=lambda x: x[1]["reclaims"], reverse=True)[:10]
    print("\nTop 10 tickers by reclaim count:")
    for t, s in top:
        print(f"  {t}: {s['events']} events, {s['up']} UP, {s['down']} DOWN, "
              f"{s['qualified']} qualified, {s['reclaims']} reclaims")
