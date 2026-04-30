"""Structural Turn Detector — synthesizes 5 conditions into one trigger.

Builds on Apr 28 2026 audit finding: the 13:30 SPY/QQQ bounce had every
piece visible to the system but was never aggregated into a single
actionable alert. This detector closes that gap.

## The 5 conditions (ALL must be present)

  1. Price within 0.5% of GEX floor (or above), in correct regime
     - SPY/QQQ NEG regime: floor below = mechanical bid
     - POS regime: floor below = strong support
  2. Floor migration UP within last RECLAIM_WINDOW_SEC (e.g. QQQ 645→655)
     -- OR a 'floor hold' (price tested floor 3+ times within 90min and
        bounced each time)
  3. Volume absorption on underlying: 1-min bar ≥ 2× rolling 20-min avg
     AT a price low (within 0.2% of session LOD or local low)
  4. Aggregate same-side flow ≥ AGG_FLOW_THRESHOLD ($10M default) in
     last AGG_FLOW_WINDOW_SEC (30 min) — sweeps, deep-ITM calls, or
     conviction=HIGH alerts
  5. Same-direction NCP/NPP within last NFA_WINDOW_SEC (30 min) on this
     ticker OR its index parent (SPY ↔ SPX, QQQ ↔ NDX/QQQ)

## Output

Records to `structural_turns` table for backfill/replay; in live mode,
fires a Telegram alert when all 5 gates pass.

## Replay validation

Run scripts/structural_turn_replay_apr28.py to verify the detector
would have fired at 13:30 on SPY and QQQ.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

# ── Configuration ─────────────────────────────────────────────────

# Price-vs-floor tolerance (price can be this fraction below floor and still qualify)
FLOOR_PROXIMITY_PCT = 0.005  # 0.5%

# How far back to look for a qualifying floor migration / reclaim
RECLAIM_WINDOW_SEC = 30 * 60  # 30 min

# How far back to look for the floor-hold pattern
FLOOR_HOLD_WINDOW_SEC = 90 * 60  # 90 min
FLOOR_HOLD_MIN_TESTS = 3  # number of touches at the floor zone

# Volume absorption threshold
VOL_ABSORPTION_MULT = 2.0  # 2x the 20-min rolling average
PRICE_LOW_TOL_PCT = 0.002  # within 0.2% of LOD/local low

# Aggregate flow threshold (USD) and window
AGG_FLOW_THRESHOLD = 10_000_000  # $10M same-side
AGG_FLOW_WINDOW_SEC = 30 * 60

# Tier 1 (cross-LLM consensus, Apr 28): ISO sweep RATE spike — alternate
# path to passing Gate 4 when absolute notional hasn't accumulated yet but
# institutional urgency is detectable via rate-of-change.
ISO_SWEEP_RATE_LOOKBACK_SEC = 5 * 60     # 5-min look at sweep rate
ISO_SWEEP_RATE_BASELINE_SEC = 20 * 60    # 20-min baseline avg
ISO_SWEEP_RATE_MULTIPLIER = 3.0          # current rate must be 3× baseline

# Tier 1: CVD bullish/bearish divergence window
CVD_DIVERGENCE_LOOKBACK_SEC = 30 * 60    # find prior pivot in last 30min
CVD_DIVERGENCE_TOL_PCT = 0.001           # 0.1% price tolerance to declare "same level"

# NCP/NPP correlation window
NFA_WINDOW_SEC = 30 * 60

# Gate 6: GEX magnitude floor — min(|pos_gex|, |neg_gex|) must clear this
# to prove the floor/king level is "real" and not toy OI. Tuned based on
# SPY/QQQ baseline (typical levels are $50-200M).
MAGNITUDE_FLOOR_USD = 20_000_000

# Gate 7: regime-and-ratio compatibility map
#   BULLISH ok if EITHER:
#     (a) POS regime + ratio >= 2.0  (long-gamma support, magnet-up bias)
#     (b) NEG regime + ratio <= 0.7  (mechanical bid at floor under short-gamma)
#   BEARISH ok if EITHER:
#     (c) NEG regime + ratio <= 0.5  (heavy puts, ceiling rejection accelerates)
#     (d) POS regime + ratio >= 1.5  (king rejection in long-gamma exhaustion)
RATIO_GATE_BULL_POS = 2.0
RATIO_GATE_BULL_NEG = 0.7
RATIO_GATE_BEAR_NEG = 0.5
RATIO_GATE_BEAR_POS = 1.5

# Cross-asset NCP corroboration:
#   - SPY/QQQ/IWM are index ETFs; their NCP can be hedge-unwind noise.
#     Pull SPX as the broader-market authority (Apr 28 finding: SPX flow
#     was right while SPY/QQQ NCPs were wrong).
#   - Each ticker checks itself + its index parent + SPX.
INDEX_PARENT = {
    "SPY": ["SPX"],
    "QQQ": ["NDX", "SPX"],   # QQQ NCP itself was bearish 13:12; SPX bull was the truth
    "IWM": ["RUT", "SPX"],
}

STRUCTURAL_TURN_DB_PATH = os.environ.get(
    "STRUCTURAL_TURN_DB_PATH", "./structural_turns.db"
)

STRUCTURAL_TURN_SCHEMA = """
CREATE TABLE IF NOT EXISTS structural_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  ts INTEGER NOT NULL,
  iso TEXT NOT NULL,
  direction TEXT NOT NULL,             -- 'BULLISH' / 'BEARISH'
  spot REAL,
  king REAL,
  floor REAL,
  regime TEXT,
  pos_gex REAL,
  neg_gex REAL,
  ratio REAL,
  zgl REAL,                              -- Zero gamma line (Gemini "flip", info only)
  spot_minus_zgl REAL,                   -- Distance to flip
  avwap_prior_low REAL,                  -- AVWAP from session LOD (info)
  spot_minus_avwap REAL,
  pc_iv_ratio REAL,                      -- Put/Call IV ratio at ATM ±5% strikes
  pc_iv_ratio_z REAL,                    -- Z-score vs 5-min rolling
  -- Gate evaluations (5 original + 2 magnitude/regime)
  gate_floor_proximity INTEGER,
  gate_floor_event INTEGER,             -- migration UP/DOWN OR hold pattern
  gate_volume_absorption INTEGER,        -- absorption (bull) / distribution (bear)
  gate_agg_flow INTEGER,
  gate_ncp_corroboration INTEGER,
  gate_magnitude INTEGER,                -- Gate 6: |gex| >= MAGNITUDE_FLOOR
  gate_regime_match INTEGER,             -- Gate 7: regime + ratio compatible
  gate_cvd_divergence INTEGER,           -- Gate 8: CVD bullish/bearish divergence (Tier 1)
  tier TEXT,                             -- 'A+' (8/8) | 'A' (7/8 no CVD) | 'B' (7/8 fuzzy regime) | NULL
  qualified INTEGER NOT NULL,
  evidence_json TEXT,
  reasons TEXT,
  UNIQUE(ticker, ts)
);
CREATE INDEX IF NOT EXISTS idx_st_ts ON structural_turns(ts);
CREATE INDEX IF NOT EXISTS idx_st_ticker ON structural_turns(ticker, ts);
CREATE INDEX IF NOT EXISTS idx_st_qualified ON structural_turns(qualified, ts);
"""


@dataclass
class StructuralTurnEvent:
    ticker: str
    ts: int
    direction: str  # BULLISH / BEARISH
    spot: float
    king: float | None
    floor: float | None
    regime: str | None
    pos_gex: float | None = None
    neg_gex: float | None = None
    ratio: float | None = None
    # Apr 28 — info-only fields (computed, logged, not gated):
    zgl: float | None = None                # Zero gamma line (Gemini's "gamma flip")
    spot_minus_zgl: float | None = None     # >0 = above flip, <0 = below
    avwap_prior_low: float | None = None    # Anchored VWAP from prior session LOD
    spot_minus_avwap: float | None = None
    pc_iv_ratio: float | None = None        # Put/call IV ratio at ATM ±5%
    pc_iv_ratio_z: float | None = None      # Z-score vs 5-min rolling baseline

    gate_floor_proximity: bool = False
    gate_floor_event: bool = False
    gate_volume_absorption: bool = False
    gate_agg_flow: bool = False
    gate_ncp_corroboration: bool = False
    gate_magnitude: bool = False
    gate_regime_match: bool = False
    gate_cvd_divergence: bool = False  # Gate 8 — Tier 1 absorption confirmation

    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def core_5_passed(self) -> bool:
        """The 5 structural gates — proximity, floor-event, volume, flow, NCP."""
        return all([
            self.gate_floor_proximity,
            self.gate_floor_event,
            self.gate_volume_absorption,
            self.gate_agg_flow,
            self.gate_ncp_corroboration,
        ])

    @property
    def tier(self) -> str:
        """CVD is an UPLIFT signal (Apr 28 finding — tick-rule retail proxy is
        too noisy to use as a hard gate; it filters real winners).

           A+: core 5 + magnitude + regime + CVD (8/8) — highest conviction
           A:  core 5 + magnitude + regime (7/8, CVD optional)
           B:  core 5 + magnitude (regime fuzzy, CVD optional uplift info)
           —:  core 5 + magnitude required minimum"""
        if not (self.core_5_passed and self.gate_magnitude):
            return "—"
        if self.gate_regime_match:
            return "A+" if self.gate_cvd_divergence else "A"
        # Regime is fuzzy — fire as B regardless of CVD (CVD just adds info)
        return "B"

    @property
    def qualified(self) -> bool:
        """A or B both fire. Tier distinguishes conviction."""
        return self.tier in ("A", "B")

    @property
    def gate_count(self) -> int:
        return sum([
            self.gate_floor_proximity, self.gate_floor_event,
            self.gate_volume_absorption, self.gate_agg_flow,
            self.gate_ncp_corroboration,
            self.gate_magnitude, self.gate_regime_match,
            self.gate_cvd_divergence,
        ])

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "ts": self.ts,
            "iso": dt.datetime.utcfromtimestamp(self.ts).isoformat() + "Z",
            "direction": self.direction,
            "spot": self.spot,
            "king": self.king,
            "floor": self.floor,
            "regime": self.regime,
            "pos_gex": self.pos_gex,
            "neg_gex": self.neg_gex,
            "ratio": self.ratio,
            "zgl": self.zgl,
            "spot_minus_zgl": self.spot_minus_zgl,
            "avwap_prior_low": self.avwap_prior_low,
            "spot_minus_avwap": self.spot_minus_avwap,
            "pc_iv_ratio": self.pc_iv_ratio,
            "pc_iv_ratio_z": self.pc_iv_ratio_z,
            "gate_floor_proximity": int(self.gate_floor_proximity),
            "gate_floor_event": int(self.gate_floor_event),
            "gate_volume_absorption": int(self.gate_volume_absorption),
            "gate_agg_flow": int(self.gate_agg_flow),
            "gate_ncp_corroboration": int(self.gate_ncp_corroboration),
            "gate_magnitude": int(self.gate_magnitude),
            "gate_regime_match": int(self.gate_regime_match),
            "gate_cvd_divergence": int(self.gate_cvd_divergence),
            "tier": self.tier if self.tier in ("A+", "A", "B") else None,
            "qualified": int(self.qualified),
            "evidence_json": json.dumps(self.evidence, default=str),
            "reasons": " | ".join(self.reasons),
        }


# ── Gate evaluators ───────────────────────────────────────────────
# BULLISH gates target the floor/support side; BEARISH gates target the
# king/ceiling side. The structure is symmetric.


def _gate_proximity(direction: str, spot: float,
                    floor: float | None, king: float | None,
                    ceiling: float | None) -> tuple[bool, str]:
    """BULLISH: spot near floor; BEARISH: spot near king/ceiling."""
    if direction == "BULLISH":
        if floor is None or floor <= 0:
            return False, "no floor data"
        tol = floor * FLOOR_PROXIMITY_PCT
        if spot >= floor - tol and spot <= floor * 1.02:
            gap_pct = (spot / floor - 1) * 100
            return True, f"spot ${spot:.2f} {gap_pct:+.2f}% from floor ${floor:.0f}"
        return False, f"spot ${spot:.2f} too far from floor ${floor:.0f}"
    else:  # BEARISH — proximity to king OR ceiling (whichever is closer above)
        levels = []
        if king and king > 0:
            levels.append(("king", king))
        if ceiling and ceiling > 0:
            levels.append(("ceiling", ceiling))
        if not levels:
            return False, "no king/ceiling data"
        # Pick the resistance closest to spot from above
        candidates = [(name, lvl) for name, lvl in levels if lvl >= spot * 0.98]
        if not candidates:
            return False, f"spot ${spot:.2f} above all resistances"
        name, lvl = min(candidates, key=lambda x: x[1])
        tol = lvl * FLOOR_PROXIMITY_PCT
        if spot <= lvl + tol and spot >= lvl * 0.98:
            gap_pct = (spot / lvl - 1) * 100
            return True, f"spot ${spot:.2f} {gap_pct:+.2f}% from {name} ${lvl:.0f}"
        return False, f"spot ${spot:.2f} too far from {name} ${lvl:.0f}"


# Backward-compat alias (older call sites)
def _gate_floor_proximity(spot: float, floor: float | None) -> tuple[bool, str]:
    return _gate_proximity("BULLISH", spot, floor, None, None)


def _gate_structural_event(
    direction: str, ticker: str, ts: int, snapshots: list[dict],
    floor_migrations_db: str | None = None,
) -> tuple[bool, str, dict]:
    """BULLISH: floor migration UP OR floor-hold pattern.
       BEARISH: floor migration DOWN (breakdown) OR ceiling/king hold pattern
                (price tested ceiling 3+ times without breaking)."""
    cutoff = ts - RECLAIM_WINDOW_SEC

    if direction == "BULLISH":
        if floor_migrations_db:
            try:
                conn = sqlite3.connect(floor_migrations_db)
                cur = conn.execute(
                    """SELECT migration_ts, old_floor, new_floor, is_reclaim
                       FROM floor_migrations
                       WHERE ticker = ? AND ts >= migration_ts AND migration_ts >= ?
                         AND direction = 'UP' AND qualified = 1
                       ORDER BY migration_ts DESC LIMIT 1""",
                    (ticker, cutoff),
                )
                row = cur.fetchone()
                conn.close()
                if row is not None:
                    age_min = (ts - row[0]) // 60
                    tag = "RECLAIM" if row[3] else "UP"
                    return True, f"floor migration {tag} ${row[1]:.0f}→${row[2]:.0f} ({age_min}min ago)", \
                           {"event": "migration_up", "old": row[1], "new": row[2],
                            "is_reclaim": bool(row[3]), "age_min": age_min}
            except sqlite3.Error:
                pass

        # Floor-hold pattern
        hold_cutoff = ts - FLOOR_HOLD_WINDOW_SEC
        relevant = [s for s in snapshots
                    if s["ts"] >= hold_cutoff and s["ts"] <= ts and s.get("floor")]
        if not relevant:
            return False, "no floor data in window", {}
        floor_now = relevant[-1]["floor"]
        tol = floor_now * 0.005
        touches = sum(1 for s in relevant
                      if s.get("spot") and abs(s["spot"] - floor_now) <= tol)
        if touches >= FLOOR_HOLD_MIN_TESTS:
            return True, f"floor-hold pattern: {touches} touches of ${floor_now:.0f} in {FLOOR_HOLD_WINDOW_SEC // 60}min", \
                   {"event": "floor_hold", "touches": touches, "level": floor_now}
        return False, f"only {touches} floor touches (need {FLOOR_HOLD_MIN_TESTS})", {}

    else:  # BEARISH
        # (a) Floor migration DOWN (breakdown) — significant bearish event
        if floor_migrations_db:
            try:
                conn = sqlite3.connect(floor_migrations_db)
                cur = conn.execute(
                    """SELECT migration_ts, old_floor, new_floor
                       FROM floor_migrations
                       WHERE ticker = ? AND migration_ts >= ?
                         AND direction = 'DOWN' AND qualified = 1
                       ORDER BY migration_ts DESC LIMIT 1""",
                    (ticker, cutoff),
                )
                row = cur.fetchone()
                conn.close()
                if row is not None:
                    age_min = (ts - row[0]) // 60
                    return True, f"floor BREAKDOWN ${row[1]:.0f}→${row[2]:.0f} ({age_min}min ago)", \
                           {"event": "migration_down", "old": row[1], "new": row[2],
                            "age_min": age_min}
            except sqlite3.Error:
                pass

        # (b) Ceiling/king-hold pattern: price tested resistance 3+ times
        hold_cutoff = ts - FLOOR_HOLD_WINDOW_SEC
        relevant = [s for s in snapshots
                    if s["ts"] >= hold_cutoff and s["ts"] <= ts]
        if not relevant:
            return False, "no snapshots in window", {}
        # Pick the resistance level — prefer king if close, else ceiling
        last = relevant[-1]
        spot_now = last.get("spot") or 0
        candidates = []
        if last.get("king") and last["king"] > 0:
            candidates.append(("king", last["king"]))
        if last.get("ceiling") and last["ceiling"] > 0:
            candidates.append(("ceiling", last["ceiling"]))
        candidates = [c for c in candidates if c[1] >= spot_now * 0.98]
        if not candidates:
            return False, "no king/ceiling resistance above spot", {}
        name, level = min(candidates, key=lambda x: x[1])
        tol = level * 0.005
        touches = sum(1 for s in relevant
                      if s.get("spot") and abs(s["spot"] - level) <= tol)
        if touches >= FLOOR_HOLD_MIN_TESTS:
            return True, f"{name}-hold: {touches} touches of ${level:.0f} in {FLOOR_HOLD_WINDOW_SEC // 60}min", \
                   {"event": f"{name}_hold", "touches": touches, "level": level}
        return False, f"only {touches} {name} touches (need {FLOOR_HOLD_MIN_TESTS})", {}


# Backward-compat alias
def _gate_floor_event(
    ticker: str, ts: int, snapshots: list[dict],
    floor_migrations_db: str | None = None,
) -> tuple[bool, str, dict]:
    return _gate_structural_event("BULLISH", ticker, ts, snapshots, floor_migrations_db)


def _gate_volume_extremity(
    direction: str, ticker: str, ts: int, minute_bars: list[dict],
) -> tuple[bool, str, dict]:
    """BULLISH: volume absorption at session LOD.
       BEARISH: volume distribution at session HOD."""
    if not minute_bars:
        return False, "no minute bars", {}
    window = [b for b in minute_bars if b["ts"] <= ts and b["ts"] >= ts - 15 * 60]
    if not window:
        return False, "no minute bars in 15min window", {}
    session = [b for b in minute_bars if b["ts"] <= ts]
    if not session:
        return False, "no session bars", {}
    if direction == "BULLISH":
        extremity = min(b["low"] for b in session)
        edge_field = "low"
        label = "LOD"
    else:
        extremity = max(b["high"] for b in session)
        edge_field = "high"
        label = "HOD"

    best = None
    for b in window:
        bar_ts = b["ts"]
        prior_20 = [bb for bb in minute_bars
                    if bb["ts"] < bar_ts and bb["ts"] >= bar_ts - 20 * 60]
        if len(prior_20) < 5:
            continue
        avg_v = sum(bb["volume"] for bb in prior_20) / len(prior_20)
        if avg_v <= 0:
            continue
        ratio = b["volume"] / avg_v
        edge_dist_pct = abs(b[edge_field] - extremity) / extremity if extremity > 0 else 1
        if ratio >= VOL_ABSORPTION_MULT and edge_dist_pct <= PRICE_LOW_TOL_PCT:
            if best is None or ratio > best["ratio"]:
                best = {"ts": bar_ts, "ratio": ratio,
                        edge_field: b[edge_field], "session_extremity": extremity,
                        "volume": b["volume"], "avg_20": avg_v}
    if best is not None:
        bar_dt = dt.datetime.fromtimestamp(best["ts"]).strftime("%H:%M")
        verb = "absorption" if direction == "BULLISH" else "distribution"
        return True, f"{verb} at {bar_dt}: {best['ratio']:.1f}× avg vol at {label} ${best[edge_field]:.2f}", \
               best
    return False, f"no qualifying {label} volume bar found", {}


# Backward-compat alias
def _gate_volume_absorption(
    ticker: str, ts: int, minute_bars: list[dict],
) -> tuple[bool, str, dict]:
    return _gate_volume_extremity("BULLISH", ticker, ts, minute_bars)


def _gate_agg_flow(
    ticker: str, ts: int, direction: str, snapshots_db: str,
) -> tuple[bool, str, dict]:
    """Pass if EITHER:
       (a) absolute notional ≥ $10M same-side in 30min (original gate), OR
       (b) ISO sweep RATE spike: sweep count in last 5min ≥ 3× 20-min baseline
           (Tier 1 upgrade per cross-LLM consensus Apr 28 — institutional
           urgency detectable before notional accumulates).
    """
    cutoff = ts - AGG_FLOW_WINDOW_SEC
    sentiment = "BULLISH" if direction == "BULLISH" else "BEARISH"
    conn = sqlite3.connect(snapshots_db)
    try:
        # Path (a): aggregate notional
        cur = conn.execute(
            """SELECT COALESCE(SUM(notional), 0), COUNT(*)
               FROM flow_alerts
               WHERE ticker = ? AND ts BETWEEN ? AND ?
                 AND (sentiment = ? OR is_sweep = 1 OR conviction = 'HIGH')""",
            (ticker, cutoff, ts, sentiment),
        )
        notional, count = cur.fetchone()

        # Path (b): ISO sweep rate spike. Count same-direction (or NEUTRAL)
        # ISO sweeps in the last 5min vs the 20-min baseline rate.
        recent_cutoff = ts - ISO_SWEEP_RATE_LOOKBACK_SEC
        baseline_cutoff = ts - ISO_SWEEP_RATE_BASELINE_SEC
        cur2 = conn.execute(
            """SELECT
                 SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) AS recent_n,
                 COUNT(*) AS baseline_n
               FROM flow_alerts
               WHERE ticker = ? AND ts BETWEEN ? AND ?
                 AND is_sweep = 1
                 AND (sentiment = ? OR sentiment = 'NEUTRAL')""",
            (recent_cutoff, ticker, baseline_cutoff, ts, sentiment),
        )
        recent_n, baseline_n = cur2.fetchone()
        recent_n = recent_n or 0
        baseline_n = baseline_n or 0
    finally:
        conn.close()

    # Compute rate spike
    # baseline_n is total in 20min window; recent_n is subset in last 5min.
    # Recent rate = recent_n / 5min; baseline rate = baseline_n / 20min.
    # If recent_n ≥ 3× (baseline_n / 4) i.e. recent_n × 4 ≥ 3 × baseline_n
    rate_spike = False
    rate_msg = ""
    if baseline_n >= 4:  # need at least some baseline to compare
        # recent rate per minute = recent_n / 5
        # baseline rate per minute = baseline_n / 20
        recent_rate = recent_n / 5
        baseline_rate = baseline_n / 20
        if baseline_rate > 0 and recent_rate / baseline_rate >= ISO_SWEEP_RATE_MULTIPLIER:
            rate_spike = True
            rate_msg = (f"ISO sweep rate spike {recent_rate:.2f}/min "
                        f"vs baseline {baseline_rate:.2f}/min "
                        f"({recent_rate/baseline_rate:.1f}× ≥ {ISO_SWEEP_RATE_MULTIPLIER}×)")
    elif recent_n >= 3:
        # No baseline but multiple sweeps in last 5min = urgency burst from cold start
        rate_spike = True
        rate_msg = f"ISO sweep burst {recent_n} in last 5min (cold start)"

    if notional and notional >= AGG_FLOW_THRESHOLD:
        return True, f"agg {sentiment.lower()}-side flow ${notional/1e6:.1f}M ({count} alerts)", \
               {"notional": notional, "count": count, "path": "absolute"}
    if rate_spike:
        return True, rate_msg, \
               {"notional": notional or 0, "count": count or 0,
                "recent_n": recent_n, "baseline_n": baseline_n,
                "path": "rate_spike"}
    return False, f"agg flow ${notional/1e6:.1f}M < ${AGG_FLOW_THRESHOLD/1e6:.0f}M and no ISO rate spike", \
           {"notional": notional or 0, "count": count or 0,
            "recent_n": recent_n, "baseline_n": baseline_n}


def _gate_magnitude(
    pos_gex: float | None, neg_gex: float | None,
) -> tuple[bool, str, dict]:
    """Min(|pos|, |neg|) must clear MAGNITUDE_FLOOR_USD. Kills toy levels."""
    p = abs(pos_gex or 0)
    n = abs(neg_gex or 0)
    smaller = min(p, n) if p > 0 and n > 0 else max(p, n)
    if smaller >= MAGNITUDE_FLOOR_USD:
        return True, f"|gex| ${smaller/1e6:.0f}M ≥ ${MAGNITUDE_FLOOR_USD/1e6:.0f}M floor", \
               {"pos_gex": p, "neg_gex": n, "smaller": smaller}
    return False, f"|gex| ${smaller/1e6:.0f}M < ${MAGNITUDE_FLOOR_USD/1e6:.0f}M floor (toy level)", \
           {"pos_gex": p, "neg_gex": n, "smaller": smaller}


def _gate_regime_match(
    direction: str, regime: str | None,
    pos_gex: float | None, neg_gex: float | None,
) -> tuple[bool, str, dict]:
    """Regime + ratio compatibility check (Apr 28 finding):
       BULLISH ok if (POS+ratio>=2.0) or (NEG+ratio<=0.7);
       BEARISH ok if (NEG+ratio<=0.5) or (POS+ratio>=1.5)."""
    p = pos_gex or 0
    n = abs(neg_gex or 0)
    if n <= 0:
        ratio = float("inf") if p > 0 else 0
    else:
        ratio = p / n
    ev = {"regime": regime, "ratio": round(ratio, 2)}
    if regime not in ("POS", "NEG"):
        return False, f"regime={regime} not POS/NEG", ev
    if direction == "BULLISH":
        if regime == "POS" and ratio >= RATIO_GATE_BULL_POS:
            return True, f"POS regime + ratio {ratio:.2f} ≥ {RATIO_GATE_BULL_POS} (long-gamma support)", ev
        if regime == "NEG" and ratio <= RATIO_GATE_BULL_NEG:
            return True, f"NEG regime + ratio {ratio:.2f} ≤ {RATIO_GATE_BULL_NEG} (mechanical bid at floor)", ev
        return False, f"{regime} regime + ratio {ratio:.2f} not BULLISH-compatible", ev
    else:  # BEARISH
        if regime == "NEG" and ratio <= RATIO_GATE_BEAR_NEG:
            return True, f"NEG regime + ratio {ratio:.2f} ≤ {RATIO_GATE_BEAR_NEG} (heavy puts, ceiling rejection)", ev
        if regime == "POS" and ratio >= RATIO_GATE_BEAR_POS:
            return True, f"POS regime + ratio {ratio:.2f} ≥ {RATIO_GATE_BEAR_POS} (king-rejection exhaustion)", ev
        return False, f"{regime} regime + ratio {ratio:.2f} not BEARISH-compatible", ev


def _compute_pc_iv_ratio(
    ticker: str, ts: int, spot: float,
    iv_lookup_fn: Any | None = None,
) -> tuple[float | None, float | None]:
    """Compute put/call IV ratio at ATM ±5% strikes (Beckmeyer 2024 inspired,
    Tier 2 cross-LLM Apr 28).

    Mechanism: at a structural support test (PML/floor), elevated put IV
    relative to call IV (skew steep) = demand for downside protection. As
    selling exhausts, put IV decays back toward call IV. Detect peak-and-
    decline within 1-2 bars of PML touch.

    Returns (ratio, z_score). Ratio = avg_put_iv / avg_call_iv across
    strikes within ±5% of spot. Z-score is computed against a 5-min
    rolling baseline if iv_lookup_fn supports historical pulls.

    For a backtest, iv_lookup_fn must accept (ticker, ts, strikes, side)
    and return list of IVs. For live, hook into ThetaData snapshot greeks.

    Without an injected lookup fn, returns (None, None) — caller decides
    whether to skip or warn."""
    if iv_lookup_fn is None or spot <= 0:
        return None, None
    try:
        # Strikes within ±5% of spot, $1 increments for stock ETFs, $5 for SPX
        if ticker == "SPX":
            step = 5
        else:
            step = 1
        lo = round(spot * 0.95 / step) * step
        hi = round(spot * 1.05 / step) * step
        strikes = list(range(int(lo), int(hi) + step, step))
        if not strikes:
            return None, None
        call_ivs = iv_lookup_fn(ticker, ts, strikes, "C") or []
        put_ivs = iv_lookup_fn(ticker, ts, strikes, "P") or []
        valid_calls = [iv for iv in call_ivs if iv is not None and iv > 0]
        valid_puts = [iv for iv in put_ivs if iv is not None and iv > 0]
        if not valid_calls or not valid_puts:
            return None, None
        avg_call = sum(valid_calls) / len(valid_calls)
        avg_put = sum(valid_puts) / len(valid_puts)
        if avg_call == 0:
            return None, None
        ratio = avg_put / avg_call
        # Z-score: compute baseline by sampling 5 min ago and 10 min ago
        baselines = []
        for offset in (5 * 60, 10 * 60, 15 * 60):
            past_calls = iv_lookup_fn(ticker, ts - offset, strikes, "C") or []
            past_puts = iv_lookup_fn(ticker, ts - offset, strikes, "P") or []
            pc = [iv for iv in past_calls if iv is not None and iv > 0]
            pp = [iv for iv in past_puts if iv is not None and iv > 0]
            if pc and pp:
                ac = sum(pc) / len(pc)
                ap = sum(pp) / len(pp)
                if ac > 0:
                    baselines.append(ap / ac)
        if len(baselines) >= 2:
            mean = sum(baselines) / len(baselines)
            var = sum((b - mean) ** 2 for b in baselines) / len(baselines)
            std = var ** 0.5
            z = (ratio - mean) / std if std > 0 else 0
            return ratio, z
        return ratio, None
    except Exception:
        return None, None


def _compute_anchored_vwap_from_low(minute_bars: list[dict]) -> tuple[float | None, int | None]:
    """Anchored VWAP from the SESSION LOD.

    Walks bars to find the lowest low; computes volume-weighted typical price
    from that anchor forward. Returns (avwap, anchor_ts).

    Tier 2 (Apr 28 cross-LLM): all four LLMs cited AVWAP from prior session
    low as a structural cost-basis defense level. We use the current
    session's LOD as a proxy (intraday version) — same mechanism applies."""
    if not minute_bars:
        return None, None
    # Find session low up to current time
    low_idx = min(range(len(minute_bars)), key=lambda i: minute_bars[i]["low"])
    anchor_ts = minute_bars[low_idx]["ts"]
    # VWAP from anchor forward
    cum_pv = 0.0
    cum_v = 0
    for b in minute_bars[low_idx:]:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += typical * b["volume"]
        cum_v += b["volume"]
    if cum_v == 0:
        return None, anchor_ts
    return cum_pv / cum_v, anchor_ts


def _compute_cvd_series(minute_bars: list[dict]) -> list[float]:
    """Tick-rule CVD approximation from 1-min OHLC+volume bars.

    Without true tick-level bid/ask data (would require ThetaData Value
    Stock sub or a futures CVD feed), we use the standard tick-rule proxy:
    sign of close-vs-prior-close × volume. This is a coarse but standard
    practitioner approximation; the academic OFI literature (Cont 2014)
    treats it as the retail-accessible proxy.

    Returns cumulative CVD per bar (running sum).
    """
    if not minute_bars:
        return []
    cvd = 0.0
    out = []
    prev_close = None
    for b in minute_bars:
        if prev_close is None:
            tick_dir = 0
        elif b["close"] > prev_close:
            tick_dir = 1
        elif b["close"] < prev_close:
            tick_dir = -1
        else:
            tick_dir = 0
        cvd += b["volume"] * tick_dir
        out.append(cvd)
        prev_close = b["close"]
    return out


def _gate_cvd_divergence(
    direction: str, ts: int, minute_bars: list[dict],
) -> tuple[bool, str, dict]:
    """BULLISH: price makes equal/lower low at ts vs prior pivot in 30min,
              while CVD makes a HIGHER low (selling exhausting).
    BEARISH: price makes equal/higher high vs prior pivot, CVD makes a
             LOWER high (buying exhausting).

    Approximation note: tick-rule CVD without true bid/ask split. Real
    CVD requires Level 2 / quote-classified trades. This is the closest
    retail-accessible proxy."""
    if not minute_bars:
        return False, "no minute bars", {}
    cvd_series = _compute_cvd_series(minute_bars)

    # Find current bar index (closest at-or-before ts)
    cur_idx = None
    for i in range(len(minute_bars) - 1, -1, -1):
        if minute_bars[i]["ts"] <= ts:
            cur_idx = i
            break
    if cur_idx is None or cur_idx < 5:
        return False, "insufficient bars before evaluation time", {}

    # Look back over CVD_DIVERGENCE_LOOKBACK_SEC for the prior pivot
    cutoff = ts - CVD_DIVERGENCE_LOOKBACK_SEC
    window = [(i, b) for i, b in enumerate(minute_bars[:cur_idx + 1])
              if b["ts"] >= cutoff]
    if len(window) < 10:
        return False, f"only {len(window)} bars in 30min window", {}

    cur_bar = minute_bars[cur_idx]
    cur_cvd = cvd_series[cur_idx]

    if direction == "BULLISH":
        # Find prior local low (excluding last 3 bars to avoid same-low compare)
        prior_window = window[:-3] if len(window) > 3 else window
        if not prior_window:
            return False, "no prior pivot window", {}
        prior_low_idx, prior_low_bar = min(prior_window,
                                           key=lambda x: x[1]["low"])
        prior_low_price = prior_low_bar["low"]
        prior_low_cvd = cvd_series[prior_low_idx]

        # Current low = the last 3 bars' lowest
        cur_low_window = minute_bars[max(cur_idx - 2, 0):cur_idx + 1]
        cur_low_price = min(b["low"] for b in cur_low_window)

        # Tolerance: must be at-or-below prior low (within +0.1%)
        tol = prior_low_price * CVD_DIVERGENCE_TOL_PCT
        price_lower_or_equal = cur_low_price <= prior_low_price + tol
        cvd_higher = cur_cvd > prior_low_cvd

        prior_t = dt.datetime.fromtimestamp(prior_low_bar["ts"]).strftime("%H:%M") \
            if isinstance(prior_low_bar["ts"], int) else str(prior_low_bar["ts"])
        ev = {"prior_low_price": prior_low_price, "prior_low_cvd": prior_low_cvd,
              "cur_low_price": cur_low_price, "cur_cvd": cur_cvd,
              "prior_t": prior_t}

        if price_lower_or_equal and cvd_higher:
            return True, (f"CVD bullish divergence: price LL "
                          f"${cur_low_price:.2f} vs prior ${prior_low_price:.2f} ({prior_t}) "
                          f"BUT CVD HL {prior_low_cvd:.0f} → {cur_cvd:.0f}"), ev
        elif not price_lower_or_equal:
            return False, f"price not at/below prior low (${cur_low_price:.2f} vs ${prior_low_price:.2f})", ev
        else:
            return False, f"CVD failed to make HL ({prior_low_cvd:.0f} → {cur_cvd:.0f})", ev

    else:  # BEARISH
        prior_window = window[:-3] if len(window) > 3 else window
        if not prior_window:
            return False, "no prior pivot window", {}
        prior_high_idx, prior_high_bar = max(prior_window,
                                             key=lambda x: x[1]["high"])
        prior_high_price = prior_high_bar["high"]
        prior_high_cvd = cvd_series[prior_high_idx]

        cur_high_window = minute_bars[max(cur_idx - 2, 0):cur_idx + 1]
        cur_high_price = max(b["high"] for b in cur_high_window)

        tol = prior_high_price * CVD_DIVERGENCE_TOL_PCT
        price_higher_or_equal = cur_high_price >= prior_high_price - tol
        cvd_lower = cur_cvd < prior_high_cvd

        prior_t = dt.datetime.fromtimestamp(prior_high_bar["ts"]).strftime("%H:%M") \
            if isinstance(prior_high_bar["ts"], int) else str(prior_high_bar["ts"])
        ev = {"prior_high_price": prior_high_price, "prior_high_cvd": prior_high_cvd,
              "cur_high_price": cur_high_price, "cur_cvd": cur_cvd,
              "prior_t": prior_t}

        if price_higher_or_equal and cvd_lower:
            return True, (f"CVD bearish divergence: price HH "
                          f"${cur_high_price:.2f} vs prior ${prior_high_price:.2f} ({prior_t}) "
                          f"BUT CVD LH {prior_high_cvd:.0f} → {cur_cvd:.0f}"), ev
        elif not price_higher_or_equal:
            return False, f"price not at/above prior high", ev
        else:
            return False, f"CVD failed to make LH", ev


def _gate_ncp_corroboration(
    ticker: str, ts: int, direction: str, snapshots_db: str,
) -> tuple[bool, str, dict]:
    """Same-direction NCP/NPP on this ticker OR its index parent."""
    cutoff = ts - NFA_WINDOW_SEC
    parents = INDEX_PARENT.get(ticker, [])
    tickers = [ticker] + parents
    placeholders = ",".join("?" * len(tickers))
    conn = sqlite3.connect(snapshots_db)
    try:
        cur = conn.execute(
            f"""SELECT ticker, signal, gap_direction, ts, spot
                FROM net_flow_alerts
                WHERE ticker IN ({placeholders}) AND ts BETWEEN ? AND ?
                ORDER BY ts DESC""",
            (*tickers, cutoff, ts),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    target_dir = "bullish" if direction == "BULLISH" else "bearish"
    matching = [r for r in rows if r[2] == target_dir]
    if matching:
        r = matching[0]
        age_min = (ts - r[3]) // 60
        return True, f"{r[0]} NCP {r[1]} {r[2]} ({age_min}min ago)", \
               {"ticker": r[0], "signal": r[1], "dir": r[2], "age_min": age_min}
    return False, f"no same-direction NCP on {tickers} in 30min", {}


# ── Main detector ────────────────────────────────────────────────


def evaluate_turn(
    ticker: str, ts: int, direction: str,
    snapshots_in_window: list[dict],
    minute_bars: list[dict],
    snapshots_db: str = "./snapshots.db",
    floor_migrations_db: str | None = "./floor_migrations.db",
    iv_lookup_fn: Any | None = None,
) -> StructuralTurnEvent:
    """Evaluate all 5 gates at a given (ticker, ts, direction)."""
    cur_snap = next(
        (s for s in reversed(snapshots_in_window) if s["ts"] <= ts), None
    )
    if cur_snap is None:
        # No snapshot — bail with a non-qualifying event
        return StructuralTurnEvent(
            ticker=ticker, ts=ts, direction=direction, spot=0,
            king=None, floor=None, regime=None,
            reasons=["no snapshot at evaluation time"],
        )
    spot = cur_snap.get("spot") or 0
    king = cur_snap.get("king")
    floor = cur_snap.get("floor")
    ceiling = cur_snap.get("ceiling")
    regime = cur_snap.get("regime")
    pos_gex = cur_snap.get("pos_gex")
    neg_gex = cur_snap.get("neg_gex")
    zgl = cur_snap.get("zgl")  # Gamma flip — info only (Gemini Apr 28 critique)
    p_abs = abs(pos_gex or 0)
    n_abs = abs(neg_gex or 0)
    ratio = (p_abs / n_abs) if n_abs > 0 else (float("inf") if p_abs > 0 else 0)
    spot_minus_zgl = (spot - zgl) if (spot and zgl) else None

    ev = StructuralTurnEvent(
        ticker=ticker, ts=ts, direction=direction,
        spot=spot, king=king, floor=floor, regime=regime,
        pos_gex=pos_gex, neg_gex=neg_gex, ratio=ratio,
        zgl=zgl, spot_minus_zgl=spot_minus_zgl,
    )

    # Gate 1 — proximity to support (BULLISH) or resistance (BEARISH)
    ok, msg = _gate_proximity(direction, spot, floor, king, ceiling)
    ev.gate_floor_proximity = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["floor_proximity"] = {"ok": ok, "msg": msg}

    # Gate 2 — structural event (floor migration UP / floor-hold for bullish;
    #           floor breakdown DOWN / king-hold for bearish)
    ok, msg, ev_data = _gate_structural_event(
        direction, ticker, ts, snapshots_in_window, floor_migrations_db,
    )
    ev.gate_floor_event = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["floor_event"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 3 — volume extremity (absorption at LOD for bullish; distribution at HOD for bearish)
    ok, msg, ev_data = _gate_volume_extremity(direction, ticker, ts, minute_bars)
    ev.gate_volume_absorption = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["volume_absorption"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 4
    ok, msg, ev_data = _gate_agg_flow(ticker, ts, direction, snapshots_db)
    ev.gate_agg_flow = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["agg_flow"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 5
    ok, msg, ev_data = _gate_ncp_corroboration(ticker, ts, direction, snapshots_db)
    ev.gate_ncp_corroboration = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["ncp_corroboration"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 6 — GEX magnitude floor (kills toy levels)
    ok, msg, ev_data = _gate_magnitude(pos_gex, neg_gex)
    ev.gate_magnitude = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["magnitude"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 7 — regime + ratio compatibility
    ok, msg, ev_data = _gate_regime_match(direction, regime, pos_gex, neg_gex)
    ev.gate_regime_match = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["regime_match"] = {"ok": ok, "msg": msg, **ev_data}

    # Gate 8 — CVD bullish/bearish divergence (Tier 1, Apr 28 cross-LLM consensus)
    ok, msg, ev_data = _gate_cvd_divergence(direction, ts, minute_bars)
    ev.gate_cvd_divergence = ok
    ev.reasons.append(("✅ " if ok else "❌ ") + msg)
    ev.evidence["cvd_divergence"] = {"ok": ok, "msg": msg, **ev_data}

    # Info-only — Anchored VWAP from session LOD (Tier 2 Apr 28)
    bars_to_now = [b for b in minute_bars if b["ts"] <= ts]
    if bars_to_now:
        avwap, anchor_ts = _compute_anchored_vwap_from_low(bars_to_now)
        if avwap is not None:
            ev.avwap_prior_low = avwap
            ev.spot_minus_avwap = spot - avwap
            anchor_hhmm = dt.datetime.fromtimestamp(anchor_ts).strftime("%H:%M") \
                if anchor_ts else "?"
            ev.evidence["avwap"] = {
                "avwap": avwap, "anchor_ts": anchor_ts,
                "anchor_hhmm": anchor_hhmm,
                "spot_minus_avwap": spot - avwap,
                "msg": f"AVWAP from {anchor_hhmm} LOD: ${avwap:.2f} "
                       f"(spot {('+' if spot>=avwap else '-')}${abs(spot-avwap):.2f})"
            }

    # Info-only — Put/Call IV ratio at ATM ±5% (Tier 2 Apr 28, Beckmeyer 2024)
    if iv_lookup_fn is not None:
        ratio, z = _compute_pc_iv_ratio(ticker, ts, spot, iv_lookup_fn)
        if ratio is not None:
            ev.pc_iv_ratio = ratio
            ev.pc_iv_ratio_z = z
            z_str = f"z={z:+.2f}" if z is not None else "z=?"
            ev.evidence["pc_iv_ratio"] = {
                "ratio": ratio, "z_score": z,
                "msg": f"P/C IV ratio {ratio:.2f} ({z_str})"
            }

    return ev


# ── Live loop ────────────────────────────────────────────────────
# Runs every 60s during market hours. For SPY/QQQ/IWM (and tickers in
# WATCH_LIST), evaluates BULLISH structural-turn gates. Logs everything
# to structural_turns.db; fires shadow-mode Telegram when 5/5 qualified.
import asyncio
import time as _time

# Tickers to watch for structural turns. Index ETFs first (highest signal
# value); add catalyst-driven names as we expand. Keep small so the
# yfinance pull stays fast (60s budget).
WATCH_LIST = ["SPY", "QQQ", "IWM"]

# Per-ticker fire cooldown — once we fire, don't re-fire same ticker for 30 min
LIVE_FIRE_COOLDOWN_SEC = 30 * 60

_live_last_fired: dict[str, int] = {}


async def _fetch_minute_bars_yf(ticker: str) -> list[dict]:
    """Pull today's 1-min bars via yfinance. Sync call wrapped in to_thread."""
    def _pull() -> list[dict]:
        try:
            import yfinance as yf
            df = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=False)
            if df.empty:
                return []
            df.index = df.index.tz_convert("America/New_York")
            return [
                {
                    "ts": int(t.timestamp()),
                    "open": float(r["Open"]), "high": float(r["High"]),
                    "low": float(r["Low"]), "close": float(r["Close"]),
                    "volume": int(r["Volume"]),
                }
                for t, r in df.iterrows()
            ]
        except Exception as e:
            print(f"[ST] yfinance pull failed for {ticker}: {e}")
            return []
    return await asyncio.to_thread(_pull)


async def _fetch_recent_snapshots(ticker: str, lookback_sec: int = 7200) -> list[dict]:
    """Pull recent snapshots for floor-hold pattern + current GEX state."""
    def _pull() -> list[dict]:
        cutoff = int(_time.time()) - lookback_sec
        conn = sqlite3.connect("./snapshots.db")
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """SELECT ts, spot, king, floor, ceiling, regime, signal,
                          pos_gex, neg_gex, net_delta, zgl
                   FROM snapshots
                   WHERE ticker = ? AND ts >= ?
                   ORDER BY ts""",
                (ticker, cutoff),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    return await asyncio.to_thread(_pull)


def _check_recent_0dte_confirmation(
    ticker: str, direction: str, ts: int,
    lookback_sec: int = 90 * 60,
    db_path: str = "./zero_dte_alerts.db",
) -> dict | None:
    """Cross-confirmation rule (Apr 29): if a 0DTE Engine alert fired same-
    direction same-ticker within 90 min before this Structural Turn, the ST
    is the CONFIRMATION the trader was waiting for. Returns the matching
    alert's metadata, else None.

    The proposed workflow:
      - 0DTE Engine fires B+ alone → watchlist, no entry
      - 0DTE Engine + Structural Turn (within 90min) → take it
      - Structural Turn alone → take it (independent signal)
    """
    cutoff = ts - lookback_sec
    # 0DTE alerts use 'bullish'/'bearish' (lowercase)
    target_dir = direction.lower()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT alert_id, fired_at, grade, total_points, max_points,
                      strike, right, expiration, est_entry_price
               FROM zero_dte_alerts
               WHERE ticker = ? AND direction = ?
                 AND fired_at BETWEEN ? AND ?
               ORDER BY fired_at DESC LIMIT 1""",
            (ticker, target_dir, cutoff, ts),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return None
        return dict(row)
    except sqlite3.Error:
        return None


async def _send_structural_turn_telegram(ev: StructuralTurnEvent) -> None:
    """Shadow-mode Telegram. Tier A = ⚡ (auto-trade candidate),
    Tier B = 👁 (watchlist; regime fuzzy).

    Apr 29: also check for recent 0DTE Engine alert in same direction within
    90min — if found, prepend CONFIRMS banner (this is the workflow rule)."""
    from .alert_gates import should_send_alert
    ok, reason = should_send_alert()
    if not ok:
        print(f"[ST] gated ({reason}) — {ev.ticker} {ev.direction} tier={ev.tier}")
        return
    try:
        from .telegram import send
    except ImportError:
        return
    arrow = "🟢" if ev.direction == "BULLISH" else "🔴"
    tier_emoji = {"A+": "⚡⚡", "A": "⚡", "B": "👁"}.get(ev.tier, "?")
    tier_label = {
        "A+": "TIER A+ — highest conviction (all 8 gates incl. CVD)",
        "A":  "TIER A — auto-trade candidate (7/8 gates, CVD inconclusive)",
        "B":  "TIER B — watchlist (regime ambiguous, 6-7/8 gates)",
    }.get(ev.tier, "?")
    pos_m = abs(ev.pos_gex or 0) / 1e6
    neg_m = abs(ev.neg_gex or 0) / 1e6
    ratio_str = f"{ev.ratio:.2f}" if ev.ratio is not None else "?"

    # Check for recent 0DTE Engine confirmation (Apr 29 workflow rule)
    confirm = _check_recent_0dte_confirmation(ev.ticker, ev.direction, ev.ts)

    lines = []
    if confirm:
        # CONFIRMS prior 0DTE Engine alert — this is the entry trigger
        confirm_t = dt.datetime.fromtimestamp(int(confirm["fired_at"])).strftime("%H:%M")
        confirm_age_min = int((ev.ts - confirm["fired_at"]) / 60)
        lines.append(f"🔗 CONFIRMS prior 0DTE Engine {confirm['grade']} alert "
                     f"({confirm_t}, {confirm_age_min}min ago)")
        lines.append(f"   0DTE: {confirm['strike']:.0f}{confirm['right']} "
                     f"@ ${confirm['est_entry_price']:.2f} | now ENTER on this ST signal")
        lines.append("")

    lines.extend([
        f"{tier_emoji} [SHADOW] STRUCTURAL TURN — {ev.ticker} {arrow} {ev.direction}",
        tier_label,
        "",
        f"Spot ${ev.spot:.2f}  |  Floor ${ev.floor or 0:.0f}  |  King ${ev.king or 0:.0f}",
        f"Regime {ev.regime or '?'}  |  Pos/Neg ${pos_m:.0f}M/${neg_m:.0f}M (ratio {ratio_str})",
    ])
    # Info-only fields
    if ev.zgl is not None and ev.spot_minus_zgl is not None:
        flip_state = "above" if ev.spot_minus_zgl > 0 else "below"
        lines.append(f"ZGL ${ev.zgl:.2f}  ({flip_state} flip {abs(ev.spot_minus_zgl):+.2f})")
    if ev.avwap_prior_low is not None and ev.spot_minus_avwap is not None:
        lines.append(f"AVWAP-LOD ${ev.avwap_prior_low:.2f}  "
                     f"(spot {('+' if ev.spot_minus_avwap >= 0 else '')}{ev.spot_minus_avwap:.2f})")
    if ev.pc_iv_ratio is not None:
        z_str = f"z={ev.pc_iv_ratio_z:+.2f}" if ev.pc_iv_ratio_z is not None else "z=?"
        lines.append(f"P/C IV ratio {ev.pc_iv_ratio:.2f}  ({z_str})")

    lines.extend(["", "Evidence:"])
    for r in ev.reasons:
        lines.append(f"  {r}")
    lines.append("")

    # Play guidance — sharper if confirms 0DTE Engine
    if confirm:
        lines.append(f"⚡ PLAY: enter {confirm['strike']:.0f}{confirm['right']} 0DTE "
                     f"NOW @ ask. -50% stop, TP1 +100% (sell half), TP2 +200% (sell qtr), trail rest.")
    elif ev.tier in ("A", "A+"):
        play_dir = "ATM 0DTE call" if ev.direction == "BULLISH" else "ATM 0DTE put"
        lines.append(f"Play: {play_dir}. Size half. -50% stop, "
                     f"TP1 +100% (sell half), TP2 +200% (sell qtr), trail rest.")
    else:
        lines.append("Play: TIER B — smaller size, validate against chart. Skip if discretionary read disagrees.")

    lines.append("")
    lines.append("Shadow mode — no auto-trade. Logging to structural_turns.db.")
    text = "\n".join(lines)
    try:
        # force=True bypasses telegram.py's global rate limit + 1h per-ticker
        # cooldown. ST has its own 30-min LIVE_FIRE_COOLDOWN_SEC at the loop
        # level — the global cooldown was silently swallowing alerts (Apr 29
        # bug: 22 DB fires, 0 telegrams reached the user).
        result = await send(text, ticker=ev.ticker, force=True)
        if not result:
            print(f"[ST] telegram returned False for {ev.ticker} (token/chat?)")
    except Exception as e:
        print(f"[ST] telegram failed: {e}")


async def _eval_ticker_live(ticker: str) -> None:
    """One-cycle eval for a ticker. Pulls bars + snapshots, evaluates,
    persists every result, fires shadow Telegram if qualified."""
    now_ts = int(_time.time())

    bars = await _fetch_minute_bars_yf(ticker)
    if not bars:
        return
    snaps = await _fetch_recent_snapshots(ticker, lookback_sec=2 * 3600)
    if not snaps:
        return

    ev = evaluate_turn(
        ticker=ticker, ts=now_ts, direction="BULLISH",
        snapshots_in_window=snaps, minute_bars=bars,
        snapshots_db="./snapshots.db",
        floor_migrations_db="./floor_migrations.db",
    )
    try:
        persist_event(ev)
    except Exception as e:
        print(f"[ST] persist error {ticker}: {e}")

    if ev.qualified:
        last_fire = _live_last_fired.get(ticker, 0)
        if now_ts - last_fire >= LIVE_FIRE_COOLDOWN_SEC:
            _live_last_fired[ticker] = now_ts
            print(f"[ST] QUALIFIED {ticker} {ev.direction} 5/5 spot=${ev.spot:.2f}")
            asyncio.create_task(_send_structural_turn_telegram(ev))


async def run_structural_turn_live_loop(stop_event) -> None:
    """Background task — evaluate WATCH_LIST every 60s during market hours."""
    print(f"[ST] live loop starting — tickers={WATCH_LIST}, interval=60s (shadow mode)")
    # Warm up
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=90.0)
        return
    except asyncio.TimeoutError:
        pass
    while not stop_event.is_set():
        # Skip outside US market hours (rough check)
        from datetime import datetime as _dt
        try:
            import pytz
            ny = _dt.now(pytz.timezone("America/New_York"))
        except Exception:
            ny = _dt.utcnow()
        if ny.weekday() >= 5 or not (9 <= ny.hour < 16):
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300.0)
                break
            except asyncio.TimeoutError:
                continue

        for ticker in WATCH_LIST:
            try:
                await _eval_ticker_live(ticker)
            except Exception as e:
                print(f"[ST] {ticker} eval error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60.0)
            break
        except asyncio.TimeoutError:
            pass
    print("[ST] live loop stopped")


def persist_event(ev: StructuralTurnEvent) -> None:
    conn = sqlite3.connect(STRUCTURAL_TURN_DB_PATH)
    try:
        conn.executescript(STRUCTURAL_TURN_SCHEMA)
        row = ev.to_row()
        conn.execute(
            """INSERT OR IGNORE INTO structural_turns (
                 ticker, ts, iso, direction, spot, king, floor, regime,
                 pos_gex, neg_gex, ratio,
                 zgl, spot_minus_zgl, avwap_prior_low, spot_minus_avwap,
                 pc_iv_ratio, pc_iv_ratio_z,
                 gate_floor_proximity, gate_floor_event,
                 gate_volume_absorption, gate_agg_flow, gate_ncp_corroboration,
                 gate_magnitude, gate_regime_match, gate_cvd_divergence, tier,
                 qualified, evidence_json, reasons
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["ticker"], row["ts"], row["iso"], row["direction"],
             row["spot"], row["king"], row["floor"], row["regime"],
             row["pos_gex"], row["neg_gex"], row["ratio"],
             row["zgl"], row["spot_minus_zgl"], row["avwap_prior_low"],
             row["spot_minus_avwap"], row["pc_iv_ratio"], row["pc_iv_ratio_z"],
             row["gate_floor_proximity"], row["gate_floor_event"],
             row["gate_volume_absorption"], row["gate_agg_flow"],
             row["gate_ncp_corroboration"],
             row["gate_magnitude"], row["gate_regime_match"],
             row["gate_cvd_divergence"], row["tier"],
             row["qualified"], row["evidence_json"], row["reasons"]),
        )
        conn.commit()
    finally:
        conn.close()
