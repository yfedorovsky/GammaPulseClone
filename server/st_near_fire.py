"""ST near-fire score — annotation for the temporal-aliasing problem.

Per OpenAI deep research May 2: the structural-turn detector's 8-gate
boolean-AND requires all 8 gates to evaluate True in the SAME 1-min
bar. In high-frequency microstructure, these gates correlate
asynchronously — a 7/8 evaluation where the missing gate has been
qualifying in nearby minutes is meaningfully different from a 7/8
evaluation where the missing gate has been cold all day.

OpenAI's two-timescale latent-state framing:
  - SLOW gates (state variables, 15-30 min TTL): regime, magnitude,
    structural_event
  - FAST gates (triggers, 1-5 min TTL): proximity, volume_absorption,
    agg_flow, ncp, cvd

A semantically richer "near-fire" definition: SLOW state has been
active for most of trailing 15 min AND FAST trigger fired in trailing
5 min. This is the architecturally-correct framing per OpenAI; it's
NOT shipped as a behavioral change to qualified=1/0 (production
freeze), but it's logged as annotation so we can validate post-Stage-3
whether the temporal-aware scoring would have produced more, fewer,
or different qualified fires.

CRITICAL: this is annotation only. The qualified column and the
StructuralTurnEvent.tier property are unchanged. Per
FALSIFICATION_PROTOCOL.md, no behavioral change to the gate logic
during the forward window.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

# Slow/fast gate split per OpenAI's two-timescale framing
SLOW_GATES = ("regime_match", "magnitude", "floor_event")
FAST_GATES = ("floor_proximity", "volume_absorption", "agg_flow",
              "ncp_corroboration", "cvd_divergence")

# TTL windows for slow/fast (in seconds)
SLOW_TTL_SEC = 15 * 60   # 15 min
FAST_TTL_SEC = 5 * 60    # 5 min

# Threshold: slow gate is "active" if it passed ≥ X% of recent evaluations
SLOW_ACTIVE_PCT = 0.5    # ≥50% of trailing 15-min evals had slow gate ON
# Fast trigger threshold: ≥1 evaluation in trailing 5-min had fast gate ON
FAST_TRIGGER_THRESHOLD = 1

# Gate name → schema column mapping
GATE_COL = {
    "floor_proximity":   "gate_floor_proximity",
    "floor_event":       "gate_floor_event",
    "volume_absorption": "gate_volume_absorption",
    "agg_flow":          "gate_agg_flow",
    "ncp_corroboration": "gate_ncp_corroboration",
    "magnitude":         "gate_magnitude",
    "regime_match":      "gate_regime_match",
    "cvd_divergence":    "gate_cvd_divergence",
}


# ── Schema migrations ──────────────────────────────────────────────

ST_NEAR_FIRE_MIGRATIONS = [
    # Continuous "near-fire score" — count of gates passing this minute
    # (already implicit in boolean columns; surfaced as integer for ease)
    "ALTER TABLE structural_turns ADD COLUMN near_fire_score INTEGER",
    # Name of the gate that's failing, when 7/8 passed
    "ALTER TABLE structural_turns ADD COLUMN missing_gate_name TEXT",
    # Slow/fast group activity
    "ALTER TABLE structural_turns ADD COLUMN n_slow_active INTEGER",
    "ALTER TABLE structural_turns ADD COLUMN n_fast_active INTEGER",
    # Two-timescale composite: slow_state_pct (0-1) over trailing 15min
    # AND fast_trigger_count over trailing 5min
    "ALTER TABLE structural_turns ADD COLUMN slow_state_pct_15m REAL",
    "ALTER TABLE structural_turns ADD COLUMN fast_trigger_count_5m INTEGER",
    # Composite "would-fire under temporal-aware logic" indicator
    # (annotation only — does NOT affect qualified column)
    "ALTER TABLE structural_turns ADD COLUMN temporal_near_fire INTEGER",
]


def apply_migrations(db_path: str = "structural_turns.db") -> int:
    conn = sqlite3.connect(db_path)
    n = 0
    for stmt in ST_NEAR_FIRE_MIGRATIONS:
        try:
            conn.execute(stmt)
            n += 1
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()
    return n


# ── Per-evaluation feature compute ─────────────────────────────────


@dataclass
class NearFireFeatures:
    near_fire_score: int
    missing_gate_name: str | None
    n_slow_active: int
    n_fast_active: int
    slow_state_pct_15m: float | None
    fast_trigger_count_5m: int | None
    temporal_near_fire: bool


def _gate_value(eval_row: dict, gate: str) -> int:
    return int(eval_row.get(GATE_COL[gate]) or 0)


def compute_near_fire_features(
    eval_row: dict, history: list[dict],
) -> NearFireFeatures:
    """Compute near-fire features for ONE evaluation, given the history
    of prior evaluations on this (ticker) up to and including this row.

    `eval_row` and entries in `history` should all be dicts with the
    structural_turns row schema (gate_floor_proximity, gate_*, ts, etc.).
    History is assumed sorted by ts ascending. The current eval should
    be the LAST entry in history.
    """
    # 1. Current near-fire score: count of gates passing this minute
    score = sum(_gate_value(eval_row, g) for g in GATE_COL.keys())

    # 2. Missing gate name (if 7/8 — i.e. one short of qualifying)
    missing = None
    if score == 7:
        for g in GATE_COL.keys():
            if not _gate_value(eval_row, g):
                missing = g
                break
    elif score == 6:
        # Could still be informative — list two missing gates joined
        missing_list = [g for g in GATE_COL.keys() if not _gate_value(eval_row, g)]
        if len(missing_list) <= 2:
            missing = "+".join(missing_list)

    # 3. Slow/fast group activity at THIS minute
    n_slow = sum(_gate_value(eval_row, g) for g in SLOW_GATES)
    n_fast = sum(_gate_value(eval_row, g) for g in FAST_GATES)

    # 4. Trailing-window analysis (slow over 15min, fast over 5min)
    # Per OpenAI's "loose intersection" framing: fast triggers don't need
    # to all fire simultaneously — each fast gate just needs to fire AT
    # LEAST ONCE in the trailing 5-min window. This respects the
    # asynchronous nature of microstructure events.
    cur_ts = int(eval_row["ts"])
    slow_cutoff = cur_ts - SLOW_TTL_SEC
    fast_cutoff = cur_ts - FAST_TTL_SEC

    slow_window = [r for r in history if int(r["ts"]) >= slow_cutoff]
    fast_window = [r for r in history if int(r["ts"]) >= fast_cutoff]

    # SLOW: % of trailing 15-min evals where ALL slow gates passed
    # simultaneously (state-variable definition — slow gates SHOULD
    # co-occur because they're describing a regime)
    if slow_window:
        all_slow_passed = sum(
            1 for r in slow_window
            if all(_gate_value(r, g) for g in SLOW_GATES)
        )
        slow_state_pct = all_slow_passed / len(slow_window)
    else:
        slow_state_pct = None

    # FAST: count of distinct fast gates that fired ≥1 minute in trailing
    # 5-min window. NOT "all simultaneously" — that's the boolean-AND
    # mistake. The loose-intersection: each fast trigger has occurred
    # recently, even if asynchronously.
    if fast_window:
        n_fast_gates_recently_active = sum(
            1 for g in FAST_GATES
            if any(_gate_value(r, g) for r in fast_window)
        )
        fast_trigger_count = n_fast_gates_recently_active
    else:
        fast_trigger_count = None

    # Composite "would have fired under temporal-aware logic":
    #   - SLOW state has been active in trailing 15min (≥50% of evals had
    #     all slow gates passing simultaneously) AND
    #   - At least 4 of 5 FAST gates have each fired ≥1 minute in trailing
    #     5min. The 4-of-5 threshold is loose-intersection: one fast gate
    #     can be "structurally absent" for the day (e.g. volabs on a no-LOD-
    #     retest day) without disqualifying the moment.
    #
    # This is annotation only; production qualified=1 still requires the
    # original strict 8-gate boolean intersection. Post-Stage-3 analysis
    # can validate whether temporal_near_fire moments would have produced
    # profitable trades.
    TEMPORAL_FAST_THRESHOLD = max(len(FAST_GATES) - 1, 1)  # 4 of 5
    temporal_near = (
        slow_state_pct is not None and slow_state_pct >= SLOW_ACTIVE_PCT
        and fast_trigger_count is not None
        and fast_trigger_count >= TEMPORAL_FAST_THRESHOLD
    )

    return NearFireFeatures(
        near_fire_score=score,
        missing_gate_name=missing,
        n_slow_active=n_slow,
        n_fast_active=n_fast,
        slow_state_pct_15m=round(slow_state_pct, 3) if slow_state_pct is not None else None,
        fast_trigger_count_5m=fast_trigger_count,
        temporal_near_fire=temporal_near,
    )


# ── Bulk backfill / live persist ───────────────────────────────────


def annotate_evaluation(
    eval_row_id: int, ticker: str, ts: int,
    db_path: str = "structural_turns.db",
) -> NearFireFeatures | None:
    """Compute and UPDATE near-fire features for one evaluation row.

    Looks up the eval row + its 15-min history from the DB.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Pull the row + history (15 min before current ts on this ticker)
        cur = conn.execute(
            """SELECT id, ts, ticker,
                      gate_floor_proximity, gate_floor_event,
                      gate_volume_absorption, gate_agg_flow,
                      gate_ncp_corroboration, gate_magnitude,
                      gate_regime_match, gate_cvd_divergence
               FROM structural_turns
               WHERE ticker = ? AND ts BETWEEN ? AND ?
               ORDER BY ts""",
            (ticker, ts - SLOW_TTL_SEC, ts),
        )
        history = [dict(r) for r in cur.fetchall()]
        if not history:
            return None
        eval_row = history[-1]
        if int(eval_row["id"]) != int(eval_row_id):
            # The current eval might not be in history (e.g., not yet persisted)
            # — fetch it explicitly
            cur2 = conn.execute(
                """SELECT id, ts, ticker,
                          gate_floor_proximity, gate_floor_event,
                          gate_volume_absorption, gate_agg_flow,
                          gate_ncp_corroboration, gate_magnitude,
                          gate_regime_match, gate_cvd_divergence
                   FROM structural_turns WHERE id = ?""", (eval_row_id,),
            )
            row = cur2.fetchone()
            if row is None:
                return None
            eval_row = dict(row)
            history.append(eval_row)

        feats = compute_near_fire_features(eval_row, history)
        conn.execute(
            """UPDATE structural_turns
               SET near_fire_score = ?, missing_gate_name = ?,
                   n_slow_active = ?, n_fast_active = ?,
                   slow_state_pct_15m = ?, fast_trigger_count_5m = ?,
                   temporal_near_fire = ?
               WHERE id = ?""",
            (
                feats.near_fire_score, feats.missing_gate_name,
                feats.n_slow_active, feats.n_fast_active,
                feats.slow_state_pct_15m, feats.fast_trigger_count_5m,
                int(feats.temporal_near_fire), eval_row_id,
            ),
        )
        conn.commit()
        return feats
    finally:
        conn.close()


def backfill_all(db_path: str = "structural_turns.db",
                 batch_size: int = 500) -> dict:
    """Backfill near-fire features across ALL existing evaluations.

    More efficient than per-row: loads each ticker's full history,
    computes features in-memory in chronological order, batches updates.
    """
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all tickers
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM structural_turns"
    ).fetchall()]

    n_total = 0
    per_ticker: dict[str, int] = {}
    for ticker in tickers:
        cur = conn.execute(
            """SELECT id, ts, ticker,
                      gate_floor_proximity, gate_floor_event,
                      gate_volume_absorption, gate_agg_flow,
                      gate_ncp_corroboration, gate_magnitude,
                      gate_regime_match, gate_cvd_divergence
               FROM structural_turns
               WHERE ticker = ?
               ORDER BY ts""",
            (ticker,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            continue

        # Compute features per row using running history slice
        updates = []
        for i, r in enumerate(rows):
            ts = int(r["ts"])
            cutoff = ts - SLOW_TTL_SEC
            # Find leftmost index with ts >= cutoff
            history_slice = [
                rr for rr in rows[max(0, i - 60):i + 1]
                if int(rr["ts"]) >= cutoff
            ]
            if not history_slice:
                history_slice = [r]
            feats = compute_near_fire_features(r, history_slice)
            updates.append((
                feats.near_fire_score, feats.missing_gate_name,
                feats.n_slow_active, feats.n_fast_active,
                feats.slow_state_pct_15m, feats.fast_trigger_count_5m,
                int(feats.temporal_near_fire), r["id"],
            ))

        # Batch UPDATE
        for j in range(0, len(updates), batch_size):
            conn.executemany(
                """UPDATE structural_turns
                   SET near_fire_score = ?, missing_gate_name = ?,
                       n_slow_active = ?, n_fast_active = ?,
                       slow_state_pct_15m = ?, fast_trigger_count_5m = ?,
                       temporal_near_fire = ?
                   WHERE id = ?""",
                updates[j:j + batch_size],
            )
            conn.commit()

        per_ticker[ticker] = len(updates)
        n_total += len(updates)

    conn.close()
    return {"total": n_total, "per_ticker": per_ticker}
