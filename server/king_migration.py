"""King Migration Detector — runner roll-up signal.

Detects +King magnet migration events across option snapshots. Pattern
documented 2026-04-22 from ARM runner audit (4/13 $157 → 4/22 $195).

## The pattern

A "runner" stock has its +King (highest positive GEX strike) stable at
level X, then abruptly migrates up to X+N as new call OI accumulates one
or more strikes higher. Mir's pattern: buy the NEW king strike on the
migration event — not a delta-based OTM strike. Catches the gamma
squeeze as dealers must chase spot higher.

## Example — ARM migrations we missed rolling correctly

  4/17 06:17 AM  $160 → $165  ratio 3.7 → 6.8  (fresh OI accumulation)
  4/17 08:22 AM  $165 → $170  ratio 6.1 → 6.7  (momentum)
  4/20 11:26 AM  $170 → $180  ratio 2.9 → 5.4  <- Mir's roll #2 timing
  4/22 10:18 AM  $180 → $200  ratio 8.0 → 8.9  <- Mir's roll #3 timing

## The 5-gate qualifier

  1. signal == MAGNET UP (call wall target above spot)
  2. king migrated upward by >= MIN_MIGRATION_PTS since last snapshot
  3. pos/neg GEX ratio >= RATIO_GATE before migration (mature structure)
  4. new floor >= old king (floor-floor leapfrog confirms real migration)
  5. net dealer delta growing (dealers increasingly short → forced chase)

## Intended use

  Historical: run_backfill() over snapshots.db to verify pattern.
  Live (later): poll every eval cycle per ticker, fire alert on qualify.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


# ── Configuration ─────────────────────────────────────────────────

# Minimum king jump in dollars to qualify as a migration. Empirically,
# valid ARM migrations were +5 to +20. Anything smaller is noise (fractional
# OI shuffle within an existing magnet).
MIN_MIGRATION_PTS = 5

# Minimum pos/neg GEX ratio before migration. Below this the structure
# is too immature to trust the call-side accumulation (could be transient).
# Was 4.0 empirically — all 5 ARM migrations had pre-ratio >= 2.85.
# Using 2.5 to catch the weekend-reset case (Mir roll #2 was 2.85 → 5.36).
RATIO_GATE = 2.5

# Window — how far back to look for the "before" snapshot. Migrations
# happen fast (within minutes) but the "before" state should be the
# prior stable snapshot, not 24h ago. 4 hours captures overnight and
# pre-market while excluding cross-day baseline drift.
PREV_LOOKBACK_SEC = 4 * 3600

# De-migration (DOWN) threshold — bearish gamma unwind. Spec: drop is
# "significant" when >= 1 strike spacing OR >= 2% of spot. We take the
# smaller of the two so either condition satisfies the test.
DOWN_DROP_PCT = 0.02

# Storage
KING_MIGRATION_DB_PATH = os.environ.get("KING_MIGRATION_DB_PATH", "./king_migrations.db")

KING_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS king_migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  migration_ts INTEGER NOT NULL,
  migration_iso TEXT NOT NULL,
  old_king REAL,
  new_king REAL,
  delta_pts REAL,
  old_floor REAL,
  new_floor REAL,
  old_ceiling REAL,
  new_ceiling REAL,
  spot REAL,
  signal TEXT,
  ratio_before REAL,
  ratio_after REAL,
  net_delta_before REAL,
  net_delta_after REAL,
  gate_signal_magnet_up INTEGER,
  gate_migration_min INTEGER,
  gate_ratio INTEGER,
  gate_floor_leapfrog INTEGER,
  gate_net_delta_growing INTEGER,
  qualified INTEGER NOT NULL,
  qualified_reasons TEXT,
  migration_type TEXT NOT NULL DEFAULT 'UP',
  UNIQUE(ticker, migration_ts)
);
CREATE INDEX IF NOT EXISTS idx_kmig_ts ON king_migrations(migration_ts);
CREATE INDEX IF NOT EXISTS idx_kmig_ticker ON king_migrations(ticker, migration_ts);
CREATE INDEX IF NOT EXISTS idx_kmig_qualified ON king_migrations(qualified, migration_ts);
CREATE INDEX IF NOT EXISTS idx_kmig_type ON king_migrations(migration_type, migration_ts);
"""


# ── Data structures ───────────────────────────────────────────────


@dataclass
class Snapshot:
    """Minimal GEX snapshot row needed for migration detection."""
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
class MigrationEvent:
    """One qualifying or non-qualifying king migration.

    `migration_type` is 'UP' (institutional gamma climb) or 'DOWN'
    (gamma unwind / king retreat). UP events run the 5-gate qualifier;
    DOWN events qualify on a single magnitude check (gate_migration_min).
    """
    ticker: str
    migration_ts: int
    before: Snapshot
    after: Snapshot
    migration_type: str = "UP"  # 'UP' | 'DOWN'

    # Gate outcomes (True if passed). UP uses all five; DOWN uses only
    # gate_migration_min and leaves the rest False/N-A.
    gate_signal_magnet_up: bool = False
    gate_migration_min: bool = False
    gate_ratio: bool = False
    gate_floor_leapfrog: bool = False
    gate_net_delta_growing: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> bool:
        if self.migration_type == "DOWN":
            return self.gate_migration_min
        return all([
            self.gate_signal_magnet_up,
            self.gate_migration_min,
            self.gate_ratio,
            self.gate_floor_leapfrog,
            self.gate_net_delta_growing,
        ])

    @property
    def delta_pts(self) -> float:
        return (self.after.king or 0) - (self.before.king or 0)

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "migration_ts": self.migration_ts,
            "migration_iso": (
                dt.datetime.utcfromtimestamp(self.migration_ts).isoformat() + "Z"
            ),
            "old_king": self.before.king,
            "new_king": self.after.king,
            "delta_pts": self.delta_pts,
            "old_floor": self.before.floor,
            "new_floor": self.after.floor,
            "old_ceiling": self.before.ceiling,
            "new_ceiling": self.after.ceiling,
            "spot": self.after.spot,
            "signal": self.after.signal,
            "ratio_before": round(self.before.ratio, 3),
            "ratio_after": round(self.after.ratio, 3),
            "net_delta_before": self.before.net_delta,
            "net_delta_after": self.after.net_delta,
            "gate_signal_magnet_up": int(self.gate_signal_magnet_up),
            "gate_migration_min": int(self.gate_migration_min),
            "gate_ratio": int(self.gate_ratio),
            "gate_floor_leapfrog": int(self.gate_floor_leapfrog),
            "gate_net_delta_growing": int(self.gate_net_delta_growing),
            "qualified": int(self.qualified),
            "qualified_reasons": " | ".join(self.reasons),
            "migration_type": self.migration_type,
        }


# ── Core detection ────────────────────────────────────────────────


def _down_threshold(ticker: str, spot: float | None) -> float:
    """Magnitude (in dollars) a king drop must clear to count as a
    de-migration. Spec: >= 1 strike spacing OR >= 2% of spot — we use the
    smaller so either condition satisfies."""
    s = float(spot or 0)
    try:
        from .root_config import get_strike_step
        step = get_strike_step(ticker, s) if s > 0 else 1.0
    except Exception:
        step = 1.0
    pct_floor = DOWN_DROP_PCT * s if s > 0 else step
    return min(step, pct_floor) if pct_floor > 0 else step


def _qualify_gates_down(before: Snapshot, after: Snapshot) -> MigrationEvent:
    """De-migration qualifier — single magnitude gate. A DOWN event
    is recorded whenever king retreats by >= 1 strike spacing OR >= 2%
    of spot. Other gate columns stay False/0 for downstream analysis."""
    ev = MigrationEvent(
        ticker=after.ticker,
        migration_ts=after.ts,
        before=before,
        after=after,
        migration_type="DOWN",
    )
    drop = -ev.delta_pts  # positive number for retreat magnitude
    threshold = _down_threshold(after.ticker, after.spot)
    ev.gate_migration_min = drop >= threshold
    pct = (drop / after.spot * 100.0) if (after.spot or 0) > 0 else 0.0
    if ev.gate_migration_min:
        ev.reasons.append(
            f"retreat -${drop:.2f} ({pct:.1f}%) >= threshold ${threshold:.2f}"
        )
    else:
        ev.reasons.append(
            f"retreat -${drop:.2f} ({pct:.1f}%) below threshold ${threshold:.2f}"
        )
    return ev


def _qualify_gates(before: Snapshot, after: Snapshot) -> MigrationEvent:
    """Run all 5 gates; return event with gate outcomes + reasons."""
    ev = MigrationEvent(
        ticker=after.ticker,
        migration_ts=after.ts,
        before=before,
        after=after,
        migration_type="UP",
    )

    # 1. Signal == MAGNET UP on the after-snapshot (the new magnet is active)
    ev.gate_signal_magnet_up = (after.signal == "MAGNET UP")
    if not ev.gate_signal_magnet_up:
        ev.reasons.append(f"signal={after.signal} not MAGNET UP")

    # 2. King jump >= MIN_MIGRATION_PTS
    dp = ev.delta_pts
    ev.gate_migration_min = dp >= MIN_MIGRATION_PTS
    if not ev.gate_migration_min:
        ev.reasons.append(f"migration {dp:+.1f}pts below threshold")
    else:
        ev.reasons.append(f"migration +${dp:.0f}")

    # 3. Ratio before migration — proves structure existed before fresh OI
    r_before = before.ratio
    ev.gate_ratio = r_before >= RATIO_GATE
    if not ev.gate_ratio:
        ev.reasons.append(f"pre-ratio {r_before:.2f} below {RATIO_GATE}")
    else:
        ev.reasons.append(f"pre-ratio {r_before:.2f}")

    # 4. Floor leapfrog — new floor at or above old king = real migration
    # not merely a fleeting transient jump. ARM 4/17 $160→$165: floor stayed
    # at $155 (didn't leapfrog) — rejected. 4/20 11:26: floor went $160→$170
    # (leapfrog). This is the key "real migration" confirmation.
    #
    # Relaxed threshold: new_floor >= old_king - 5 (tolerates step-floor by
    # one level). Strict equality (new_floor >= old_king) is too strict:
    # ARM 4/22 10:18 had old_king=$180, new_floor=$180 — exactly meets.
    # ARM 4/20 11:26 had old_king=$170, new_floor=$170 — also exactly meets.
    old_king = before.king or 0
    new_floor = after.floor or 0
    ev.gate_floor_leapfrog = new_floor >= old_king - 5
    if not ev.gate_floor_leapfrog:
        ev.reasons.append(
            f"floor ${new_floor:.0f} below old king ${old_king:.0f} (no leapfrog)"
        )
    else:
        ev.reasons.append(f"floor-leapfrog ${new_floor:.0f}")

    # 5. Net delta growing — dealers getting shorter = forced chase.
    # Both must be positive AND after > before. Zero or negative = no signal.
    #
    # Mature-structure bypass (added 2026-05-06 after missing DELL $220→$240
    # at 13:17 ET): when before.ratio ≥ 5, the call wall is already so
    # one-sided that demanding strictly-growing dealer delta is overkill —
    # the migration alone is the trigger. Without this bypass, DELL's
    # pre_ratio 11.63 + floor-leapfrog migration was rejected.
    nd_b = before.net_delta or 0
    nd_a = after.net_delta or 0
    if before.ratio >= 5.0 and nd_a > 0:
        ev.gate_net_delta_growing = True
        ev.reasons.append(
            f"net_delta {nd_b/1e6:.1f}M→{nd_a/1e6:.1f}M "
            f"(bypass: pre-ratio {before.ratio:.1f} ≥ 5)"
        )
    else:
        ev.gate_net_delta_growing = nd_a > nd_b and nd_a > 0
        if not ev.gate_net_delta_growing:
            ev.reasons.append(
                f"net_delta {nd_b/1e6:.1f}M→{nd_a/1e6:.1f}M not growing"
            )
        else:
            ev.reasons.append(f"net_delta {nd_b/1e6:.1f}M→{nd_a/1e6:.1f}M (+{(nd_a-nd_b)/1e6:.1f}M)")

    return ev


def detect_migrations_for_ticker(
    ticker: str,
    snapshots: list[Snapshot],
) -> list[MigrationEvent]:
    """Scan a time-ordered list of snapshots for king jumps.

    Algorithm: walk forward. For each row, compare king to prior row's king.
    If it moved upward >= MIN_MIGRATION_PTS AND prior row was within
    PREV_LOOKBACK_SEC, qualify the event via all 5 gates.

    Returns all migration events (qualified + non-qualified) for inspection.
    """
    events: list[MigrationEvent] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        cur = snapshots[i]
        if prev.king is None or cur.king is None:
            continue
        if (cur.ts - prev.ts) > PREV_LOOKBACK_SEC:
            continue
        delta = cur.king - prev.king
        if delta >= MIN_MIGRATION_PTS:
            events.append(_qualify_gates(prev, cur))
        elif delta < 0 and -delta >= _down_threshold(ticker, cur.spot):
            events.append(_qualify_gates_down(prev, cur))
    return events


# ── Persistence ───────────────────────────────────────────────────


_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    conn = sqlite3.connect(KING_MIGRATION_DB_PATH)
    try:
        # Migrate first so the executescript's idx_kmig_type CREATE INDEX
        # below sees migration_type on pre-existing tables.
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='king_migrations'"
        ).fetchone()
        if table_exists:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(king_migrations)")}
            if "migration_type" not in cols:
                conn.execute(
                    "ALTER TABLE king_migrations "
                    "ADD COLUMN migration_type TEXT NOT NULL DEFAULT 'UP'"
                )
        conn.executescript(KING_MIGRATION_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _schema_ready = True


def persist_event(ev: MigrationEvent) -> None:
    """Write event row to sqlite. Idempotent (UNIQUE on ticker+ts)."""
    _ensure_schema()
    row = ev.to_row()
    conn = sqlite3.connect(KING_MIGRATION_DB_PATH)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO king_migrations (
              ticker, migration_ts, migration_iso,
              old_king, new_king, delta_pts,
              old_floor, new_floor, old_ceiling, new_ceiling,
              spot, signal, ratio_before, ratio_after,
              net_delta_before, net_delta_after,
              gate_signal_magnet_up, gate_migration_min, gate_ratio,
              gate_floor_leapfrog, gate_net_delta_growing,
              qualified, qualified_reasons, migration_type
            ) VALUES (
              ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?,
              ?, ?, ?,
              ?, ?,
              ?, ?, ?
            )
            """,
            (
                row["ticker"], row["migration_ts"], row["migration_iso"],
                row["old_king"], row["new_king"], row["delta_pts"],
                row["old_floor"], row["new_floor"],
                row["old_ceiling"], row["new_ceiling"],
                row["spot"], row["signal"], row["ratio_before"], row["ratio_after"],
                row["net_delta_before"], row["net_delta_after"],
                row["gate_signal_magnet_up"], row["gate_migration_min"],
                row["gate_ratio"], row["gate_floor_leapfrog"],
                row["gate_net_delta_growing"],
                row["qualified"], row["qualified_reasons"],
                row["migration_type"],
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
    """API read: newest first, filter by ticker / qualified status."""
    _ensure_schema()
    conn = sqlite3.connect(KING_MIGRATION_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM king_migrations WHERE 1=1"
        params: list[Any] = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        if qualified_only:
            sql += " AND qualified = 1"
        sql += " ORDER BY migration_ts DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Snapshot source adapter ───────────────────────────────────────


def load_snapshots_from_db(
    snapshot_db_path: str,
    ticker: str,
    since_ts: int = 0,
) -> list[Snapshot]:
    """Pull ARM-style per-ticker snapshots from the main snapshots.db.

    Columns assumed: ts, spot, king, floor, ceiling, pos_gex, neg_gex,
    net_delta, signal (matches server/snapshots.py schema in use).
    """
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
        out: list[Snapshot] = []
        for r in cur.fetchall():
            out.append(Snapshot(
                ticker=ticker.upper(),
                ts=int(r["ts"]),
                spot=r["spot"],
                king=r["king"],
                floor=r["floor"],
                ceiling=r["ceiling"],
                pos_gex=r["pos_gex"],
                neg_gex=r["neg_gex"],
                net_delta=r["net_delta"],
                signal=r["signal"],
            ))
        return out
    finally:
        conn.close()


# ── Live detection loop (added 2026-04-24) ───────────────────────
#
# Fires king-migration alerts in real-time by polling the worker's
# in-memory cache for king changes on each scan cycle. Missed ARM
# 250C migration 2026-04-24 at 9:35 AM because detector was
# backfill-only — this wires it live.
#
# Design:
#  - Per-ticker 'last seen king' tracked in memory
#  - When cache-snapshot king differs from last seen, build a
#    (prev, cur) Snapshot pair and run _qualify_gates
#  - If qualified, persist + Telegram push (subject to alert gates)
#  - 60-min cooldown per ticker to prevent migration-flicker spam

import asyncio


# Module-scope state — resets on process restart (acceptable; migrations
# are rare and a missed one isn't catastrophic). Persistence via sqlite
# means any fired events survive.
#
# 2026-05-06: was tracking only the prior (king, ts). The `before` Snapshot
# was then built using the CURRENT spot/ratio/net_delta with the prior king,
# so before == after for every gate that compared the two. DELL $220→$240
# migration showed `net_delta 11.9M→11.9M not growing` because both values
# were the same cache read. Fixed by storing the full prior Snapshot.
_live_last_state: dict[str, "Snapshot"] = {}  # ticker -> last full Snapshot
_live_last_fired: dict[str, int] = {}  # ticker -> ts of last UP fire
_live_last_fired_down: dict[str, int] = {}  # ticker -> ts of last DOWN fire
LIVE_FIRE_COOLDOWN_SEC = 60 * 60  # 1 hour per ticker (per direction)


async def _send_king_migration_telegram(ev: "MigrationEvent") -> None:
    """Push a king-migration Telegram alert."""
    from .alert_gates import should_send_alert
    ok, reason = should_send_alert()
    if not ok:
        print(f"[KING_MIG] gated ({reason}) — {ev.ticker} ${ev.before.king:.0f}->${ev.after.king:.0f}")
        return
    try:
        from .telegram import send
    except ImportError:
        return
    emoji = "👑"
    text = (
        f"{emoji} KING MIGRATION: {ev.ticker}\n"
        f"${ev.before.king:.0f} → ${ev.after.king:.0f}  (+${ev.delta_pts:.0f})\n"
        f"Spot: ${ev.after.spot:.2f}  |  Floor leap: ${ev.before.floor or 0:.0f} → ${ev.after.floor or 0:.0f}\n"
        f"Pos/Neg: {ev.before.ratio:.2f} → {ev.after.ratio:.2f}\n"
        f"Net Δ: {(ev.before.net_delta or 0)/1e6:.1f}M → {(ev.after.net_delta or 0)/1e6:.1f}M\n"
        f"\n"
        f"Play: buy ${ev.after.king:.0f} call, 5-10 DTE, stop on spot < ${ev.after.floor or 0:.0f}\n"
        f"Pattern docs: new king = new magnet target"
    )
    try:
        await send(text, ticker=ev.ticker)
    except Exception as e:
        print(f"[KING_MIG] telegram failed: {e}")


async def _send_king_demigration_telegram(ev: "MigrationEvent") -> None:
    """Push a king de-migration (retreat) Telegram alert — bearish unwind."""
    from .alert_gates import should_send_alert
    ok, reason = should_send_alert()
    if not ok:
        print(f"[KING_MIG] gated ({reason}) — DOWN {ev.ticker} ${ev.before.king:.0f}->${ev.after.king:.0f}")
        return
    try:
        from .telegram import send
    except ImportError:
        return
    drop = -ev.delta_pts
    pct = (drop / ev.before.king * 100.0) if (ev.before.king or 0) > 0 else 0.0
    text = (
        f"🔻 KING RETREAT: {ev.ticker} king moved "
        f"${ev.before.king:.0f} → ${ev.after.king:.0f} (-{pct:.1f}%) — bearish gamma unwind\n"
        f"Spot: ${ev.after.spot:.2f}  |  Floor: ${ev.before.floor or 0:.0f} → ${ev.after.floor or 0:.0f}\n"
        f"Pos/Neg: {ev.before.ratio:.2f} → {ev.after.ratio:.2f}\n"
        f"Net Δ: {(ev.before.net_delta or 0)/1e6:.1f}M → {(ev.after.net_delta or 0)/1e6:.1f}M"
    )
    try:
        await send(text, ticker=ev.ticker)
    except Exception as e:
        print(f"[KING_MIG] telegram failed: {e}")


async def _check_ticker_live(ticker: str, state: dict) -> None:
    """Build Snapshot from cache state, compare to last-seen full Snapshot,
    fire if migration qualifies. Called per-ticker from the live loop."""
    spot = state.get("actual_spot") or state.get("_spot") or 0
    king = state.get("king") or 0
    if not spot or not king:
        return

    now_ts = int(time.time())
    cur = Snapshot(
        ticker=ticker, ts=now_ts,
        spot=spot, king=king,
        floor=state.get("floor") or 0,
        ceiling=state.get("ceiling") or 0,
        pos_gex=state.get("pos_gex") or 0,
        neg_gex=state.get("neg_gex") or 0,
        net_delta=state.get("net_delta") or 0,
        signal=state.get("signal") or "",
    )

    prev = _live_last_state.get(ticker)
    # Always update last-seen so the *next* tick has a true prior snapshot.
    _live_last_state[ticker] = cur

    if prev is None or prev.king is None:
        return

    # Classify direction. UP requires the existing >= MIN_MIGRATION_PTS
    # jump. DOWN requires retreat >= min(strike_step, 2% spot).
    delta_pts = king - prev.king
    direction: str | None = None
    if delta_pts >= MIN_MIGRATION_PTS:
        direction = "UP"
    elif delta_pts < 0 and -delta_pts >= _down_threshold(ticker, spot):
        direction = "DOWN"

    if direction is None:
        return

    ev = _qualify_gates(prev, cur) if direction == "UP" else _qualify_gates_down(prev, cur)

    # Persist regardless (qualified or not — useful for analysis)
    try:
        persist_event(ev)
    except Exception as e:
        print(f"[KING_MIG] persist error {ticker}: {e}")

    # Fire only on qualified + cooldown elapsed (separate cooldown per direction)
    if ev.qualified:
        cooldown_map = _live_last_fired if direction == "UP" else _live_last_fired_down
        last_fire = cooldown_map.get(ticker, 0)
        if now_ts - last_fire >= LIVE_FIRE_COOLDOWN_SEC:
            cooldown_map[ticker] = now_ts
            print(
                f"[KING_MIG] QUALIFIED {direction} {ticker}  "
                f"${prev.king:.0f}->${king:.0f} spot=${spot:.2f} "
                f"ratio={prev.ratio:.2f}->{cur.ratio:.2f}"
            )
            if direction == "UP":
                asyncio.create_task(_send_king_migration_telegram(ev))
            else:
                asyncio.create_task(_send_king_demigration_telegram(ev))


async def run_king_migration_live_loop(stop_event) -> None:
    """Background task — poll cache every 30s for king changes.

    Integration: started from main.py lifespan alongside worker.
    """
    from .cache import cache

    print("[KING_MIG] live loop starting — interval=30s")
    # Warm up: wait 60s for first worker cycle to populate cache
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
                    print(f"[KING_MIG] {ticker} check error: {e}")
        except Exception as e:
            print(f"[KING_MIG] loop error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30.0)
            break
        except asyncio.TimeoutError:
            pass

    print("[KING_MIG] live loop stopped")


# ── Backfill CLI ──────────────────────────────────────────────────


def run_backfill(
    snapshot_db_path: str = "./snapshots.db",
    tickers: Iterable[str] | None = None,
    since_days: int = 14,
) -> dict[str, Any]:
    """Run detection retroactively on snapshots.db and persist all events.

    Call from the command line:
        python -m server.king_migration

    Returns summary dict: {tickers_scanned, events_total, events_qualified}.
    """
    if tickers is None:
        # Default: scan all distinct tickers in the snapshots window
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
    total = 0
    qualified = 0
    by_ticker: dict[str, dict[str, int]] = {}
    for ticker in tickers:
        snaps = load_snapshots_from_db(snapshot_db_path, ticker, since_ts=since_ts)
        events = detect_migrations_for_ticker(ticker, snaps)
        q = sum(1 for e in events if e.qualified)
        total += len(events)
        qualified += q
        by_ticker[ticker] = {"events": len(events), "qualified": q}
        for e in events:
            persist_event(e)
    return {
        "tickers_scanned": len(list(tickers)),
        "events_total": total,
        "events_qualified": qualified,
        "by_ticker": by_ticker,
    }


if __name__ == "__main__":
    import sys
    since_days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(f"Running king-migration backfill — last {since_days} days…")
    summary = run_backfill(since_days=since_days)
    print(json.dumps(summary, indent=2))
