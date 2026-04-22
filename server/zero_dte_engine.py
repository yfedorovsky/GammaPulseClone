"""0DTE Confluence Alert Engine — combines GEX + NetFlow + Sweep + Golden
signals into actionable trade tickets with A+/A/B+/B/C grading.

## What this is

Every ~10 seconds, for each of SPY/SPX/QQQ/IWM, evaluate FIVE independent
confluence factors:

  1. GEX STRUCTURE  — spot position vs king/floor/ceiling (direction + level)
  2. FAST NETFLOW   — 2-min NCP/NPP rate-of-change (flow leading direction?)
  3. NETFLOW REGIME — longer-term regime classification (FLOW_LEADS_UP etc)
  4. SWEEP BURST    — ISO sweeps in last 2 min aligned with thesis direction
  5. GOLDEN CLUSTER — active GOLDEN alerts on this ticker in last 5 min

Score each 0-4 points. Total → letter grade:
  17-20  → A+   (fire Telegram, high conviction)
  13-16  → A    (fire Telegram, high conviction)
  9-12   → B+   (fire Telegram, medium conviction — consider smaller size)
  5-8    → B    (UI-only, under conviction threshold)
  0-4    → C    (UI-only, mostly noise)

## Thesis direction logic

Before scoring, decide BULLISH vs BEARISH thesis:
  - If GEX signal is MAGNET UP + spot < king  → bullish
  - If GEX signal is AIR POCKET / DANGER + spot > neg_king → bearish
  - If NCP rising + NPP flat → bullish
  - If NPP rising + NCP flat → bearish
  - Ambiguous → no fire

Only once direction is clear do we score. Prevents "high score" noise
where factors point different directions.

## Cooldown

Per (ticker, direction): 10-minute minimum between fires. Prevents
re-alerting the same setup multiple times during a trending move.
Upgraded-grade re-fires are allowed (if a B fires, then 15min later the
same setup strengthens to A+, the A+ fires).

Shipped 2026-04-22 overnight.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any


# ── Configuration ─────────────────────────────────────────────────

TRACKED_TICKERS: tuple[str, ...] = ("SPY", "SPX", "QQQ", "IWM")

# Scan interval — how often we re-evaluate every ticker
EVAL_INTERVAL_S = 10

# Cooldown in seconds for same (ticker, direction) alert
COOLDOWN_S = 600  # 10 min

# Grade thresholds (total 0-20)
GRADE_THRESHOLDS = {
    "A+": 17,
    "A": 13,
    "B+": 9,
    "B": 5,
    "C": 0,
}

# Minimum grade to fire Telegram push
MIN_TELEGRAM_GRADE = "B+"

# How fresh sweeps must be to count as supporting evidence (seconds)
SWEEP_FRESHNESS_S = 120

# How fresh Golden alerts must be (seconds)
GOLDEN_FRESHNESS_S = 300


# ── Data structures ───────────────────────────────────────────────


@dataclass
class FactorScore:
    """Single confluence factor's contribution."""
    name: str          # 'gex' | 'fast_flow' | 'regime' | 'sweep' | 'golden'
    points: int        # 0-4
    reasoning: str     # human-readable "why"


@dataclass
class ConfluenceEval:
    """Full evaluation for a ticker at a moment in time."""
    ticker: str
    direction: str | None       # 'bullish' | 'bearish' | None (ambiguous)
    total_points: int
    max_points: int
    grade: str                  # 'A+' | 'A' | 'B+' | 'B' | 'C'
    factors: list[FactorScore] = field(default_factory=list)
    # Context snapshots for downstream ticket construction
    spot: float | None = None
    king_pos: float | None = None
    king_neg: float | None = None
    floor: float | None = None
    ceiling: float | None = None
    gex_signal: str | None = None
    flow_regime: str | None = None
    target_level: float | None = None   # the GEX wall we're trading toward
    # Timestamps
    eval_ts: float = 0.0

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "total_points": self.total_points,
            "max_points": self.max_points,
            "grade": self.grade,
            "factors": [
                {"name": f.name, "points": f.points, "reasoning": f.reasoning}
                for f in self.factors
            ],
            "spot": self.spot,
            "king_pos": self.king_pos,
            "king_neg": self.king_neg,
            "floor": self.floor,
            "ceiling": self.ceiling,
            "gex_signal": self.gex_signal,
            "flow_regime": self.flow_regime,
            "target_level": self.target_level,
            "eval_ts": self.eval_ts,
            "eval_ts_iso": (
                dt.datetime.utcfromtimestamp(self.eval_ts).isoformat() + "Z"
                if self.eval_ts else None
            ),
        }


# ── Direction resolver ────────────────────────────────────────────


def _resolve_direction(
    spot: float | None,
    king_pos: float | None,
    king_neg: float | None,
    gex_signal: str | None,
    ncp_roc: float,
    npp_roc: float,
) -> tuple[str | None, float | None, str]:
    """Determine thesis direction + target level + reasoning.

    Returns (direction, target_level, reasoning_str).
    direction ∈ {'bullish', 'bearish', None}
    target_level = the level we trade toward (usually king_pos for bullish,
    king_neg or floor for bearish).
    """
    if spot is None or spot <= 0:
        return None, None, "no spot"

    bull_votes = 0
    bear_votes = 0
    reasons = []

    # GEX signal vote
    if gex_signal == "MAGNET UP":
        bull_votes += 2
        reasons.append("GEX MAGNET UP")
    elif gex_signal == "SUPPORT":
        bull_votes += 1
        reasons.append("GEX SUPPORT")
    elif gex_signal == "DANGER":
        bear_votes += 2
        reasons.append("GEX DANGER")
    elif gex_signal == "AIR POCKET":
        bear_votes += 2
        reasons.append("GEX AIR POCKET")
    elif gex_signal == "RESISTANCE":
        bear_votes += 1
        reasons.append("GEX RESISTANCE")

    # King positioning vote
    if king_pos is not None and king_pos > spot:
        bull_votes += 1  # magnet pull up
    if king_neg is not None and spot < king_neg * 1.002:
        # spot near-or-below neg king = dangerous
        bear_votes += 1

    # Fast flow vote — direction of NCP/NPP change
    # Thresholds: $500K/2min moderate, $2M strong
    if ncp_roc > 500_000 and npp_roc < 500_000:
        bull_votes += 2 if ncp_roc > 2_000_000 else 1
        reasons.append(f"NCP +${ncp_roc/1e6:.1f}M")
    if npp_roc > 500_000 and ncp_roc < 500_000:
        bear_votes += 2 if npp_roc > 2_000_000 else 1
        reasons.append(f"NPP +${npp_roc/1e6:.1f}M")
    if ncp_roc < -500_000:
        bear_votes += 1
    if npp_roc < -500_000:
        bull_votes += 1

    # Resolve
    if bull_votes >= 3 and bull_votes > bear_votes + 1:
        direction = "bullish"
        target = king_pos if king_pos else None
    elif bear_votes >= 3 and bear_votes > bull_votes + 1:
        direction = "bearish"
        # For bearish, target is king_neg (danger zone) or floor if king_neg is None
        target = king_neg if king_neg else None
    else:
        return None, None, f"ambiguous (bull={bull_votes} bear={bear_votes})"

    return direction, target, " · ".join(reasons)


# ── Factor scorers ────────────────────────────────────────────────


def _score_gex(
    direction: str,
    spot: float | None,
    king_pos: float | None,
    king_neg: float | None,
    floor: float | None,
    ceiling: float | None,
    gex_signal: str | None,
) -> FactorScore:
    """Score GEX structure alignment with thesis direction. 0-4 points.

    Bullish gets 4 when:
      - MAGNET UP signal + spot < king_pos + meaningful distance to travel
    Bearish gets 4 when:
      - DANGER/AIR POCKET signal + spot near king_neg or above ceiling
    """
    if spot is None or spot <= 0:
        return FactorScore("gex", 0, "no spot")

    if direction == "bullish":
        if gex_signal == "MAGNET UP" and king_pos and king_pos > spot:
            dist_pct = (king_pos - spot) / spot
            # Room to run gets higher score
            if 0.002 <= dist_pct <= 0.015:
                return FactorScore(
                    "gex", 4,
                    f"MAGNET UP with {dist_pct*100:.2f}% to king ${king_pos:g}"
                )
            elif dist_pct > 0.015:
                return FactorScore(
                    "gex", 3,
                    f"MAGNET UP but king ${king_pos:g} far ({dist_pct*100:.2f}%)"
                )
            else:
                return FactorScore(
                    "gex", 2,
                    f"MAGNET UP but nearly at king ${king_pos:g}"
                )
        if gex_signal == "SUPPORT":
            return FactorScore("gex", 2, "SUPPORT signal")
        if gex_signal == "PINNING":
            return FactorScore("gex", 1, "PINNING — limited upside")
        return FactorScore("gex", 0, f"GEX {gex_signal} not bullish")

    elif direction == "bearish":
        if gex_signal in ("DANGER", "AIR POCKET") and king_neg:
            dist_pct = abs(spot - king_neg) / spot
            if dist_pct <= 0.003:
                return FactorScore(
                    "gex", 4,
                    f"{gex_signal} at neg_king ${king_neg:g}"
                )
            else:
                return FactorScore(
                    "gex", 3,
                    f"{gex_signal} within {dist_pct*100:.2f}% of neg_king"
                )
        if gex_signal == "RESISTANCE":
            return FactorScore("gex", 2, "RESISTANCE above spot")
        return FactorScore("gex", 0, f"GEX {gex_signal} not bearish")

    return FactorScore("gex", 0, "no direction")


def _score_fast_flow(
    direction: str,
    ncp_roc: float,
    npp_roc: float,
    burst_signed: float,
    is_stalled: bool,
) -> FactorScore:
    """Score fast-tick flow. Uses 2-min ROC AND 30s burst.

    Bullish fires on: large NCP gain, OR large NPP drop (covering shorts)
    Bearish fires on: large NPP gain, OR large NCP drop
    """
    if is_stalled:
        return FactorScore("fast_flow", 0, "flow stalled")

    if direction == "bullish":
        # Primary: NCP rising
        score = 0
        reasons = []
        if ncp_roc > 2_000_000:
            score = max(score, 4)
            reasons.append(f"NCP +${ncp_roc/1e6:.1f}M/2m")
        elif ncp_roc > 1_000_000:
            score = max(score, 3)
            reasons.append(f"NCP +${ncp_roc/1e6:.1f}M/2m")
        elif ncp_roc > 500_000:
            score = max(score, 2)
            reasons.append(f"NCP +${ncp_roc/1e6:.1f}M/2m")
        # Secondary: NPP dropping (short covering / put sellers emboldened)
        if npp_roc < -1_000_000:
            score = max(score, 3)
            reasons.append(f"NPP -${abs(npp_roc)/1e6:.1f}M")
        # Burst in last 30s
        if burst_signed > 500_000:
            score = min(4, score + 1)
            reasons.append(f"30s burst +${burst_signed/1e3:.0f}K")
        return FactorScore(
            "fast_flow", score,
            " · ".join(reasons) if reasons else "weak bullish flow",
        )

    elif direction == "bearish":
        score = 0
        reasons = []
        if npp_roc > 2_000_000:
            score = max(score, 4)
            reasons.append(f"NPP +${npp_roc/1e6:.1f}M/2m")
        elif npp_roc > 1_000_000:
            score = max(score, 3)
            reasons.append(f"NPP +${npp_roc/1e6:.1f}M/2m")
        elif npp_roc > 500_000:
            score = max(score, 2)
            reasons.append(f"NPP +${npp_roc/1e6:.1f}M/2m")
        if ncp_roc < -1_000_000:
            score = max(score, 3)
            reasons.append(f"NCP -${abs(ncp_roc)/1e6:.1f}M")
        if burst_signed < -500_000:
            score = min(4, score + 1)
            reasons.append(f"30s burst -${abs(burst_signed)/1e3:.0f}K")
        return FactorScore(
            "fast_flow", score,
            " · ".join(reasons) if reasons else "weak bearish flow",
        )

    return FactorScore("fast_flow", 0, "no direction")


def _score_regime(direction: str, regime: str | None, confidence: str | None) -> FactorScore:
    """Score the longer-term NetFlow regime classification."""
    if not regime or regime == "NO_SIGNAL":
        return FactorScore("regime", 0, "no regime")

    conf_bonus = {"high": 2, "medium": 1, "low": 0}.get(confidence or "low", 0)

    if direction == "bullish":
        if regime == "FLOW_LEADS_UP":
            return FactorScore("regime", 2 + conf_bonus, f"FLOW_LEADS_UP {confidence}")
        if regime == "BULLISH_DIVERGENCE":
            return FactorScore("regime", 1 + conf_bonus, f"BULLISH_DIVERGENCE {confidence}")
        if regime == "DOUBLE_STALL":
            return FactorScore("regime", 0, "DOUBLE_STALL — flow stalled")
        return FactorScore("regime", 0, f"{regime} not supportive")
    elif direction == "bearish":
        if regime == "FLOW_LEADS_DOWN":
            return FactorScore("regime", 2 + conf_bonus, f"FLOW_LEADS_DOWN {confidence}")
        if regime == "BEARISH_DIVERGENCE":
            return FactorScore("regime", 1 + conf_bonus, f"BEARISH_DIVERGENCE {confidence}")
        return FactorScore("regime", 0, f"{regime} not supportive")
    return FactorScore("regime", 0, "no direction")


def _score_sweeps(direction: str, sweeps: list[dict[str, Any]]) -> FactorScore:
    """Score recent ISO sweep activity aligned with thesis direction.

    Each recent sweep within SWEEP_FRESHNESS_S contributes. Call sweeps
    support bullish, put sweeps support bearish. Size matters too.
    """
    if not sweeps:
        return FactorScore("sweep", 0, "no recent sweeps")

    now = time.time()
    aligned_count = 0
    aligned_notional = 0.0
    reasons = []

    for s in sweeps:
        ts = s.get("ts") or 0
        # Sweep record may store ts as epoch float or iso string — try both
        if isinstance(ts, str):
            try:
                ts = dt.datetime.fromisoformat(ts.replace("Z", "")).timestamp()
            except ValueError:
                continue
        if now - ts > SWEEP_FRESHNESS_S:
            continue

        right = (s.get("option_type") or "").lower()
        notional = float(s.get("sweep_notional") or 0)

        if direction == "bullish" and right == "call":
            aligned_count += 1
            aligned_notional += notional
        elif direction == "bearish" and right == "put":
            aligned_count += 1
            aligned_notional += notional

    if aligned_count == 0:
        return FactorScore("sweep", 0, "no aligned sweeps")

    # Score: 1pt for any, +1 for 3+ sweeps, +1 for >$500K aggregate,
    # +1 for >$2M aggregate
    pts = 1
    if aligned_count >= 3:
        pts += 1
    if aligned_notional > 500_000:
        pts += 1
    if aligned_notional > 2_000_000:
        pts += 1
    pts = min(4, pts)

    return FactorScore(
        "sweep",
        pts,
        f"{aligned_count} aligned sweeps in 2min, ${aligned_notional/1e6:.2f}M aggregate",
    )


def _score_golden(direction: str, goldens: list[dict[str, Any]]) -> FactorScore:
    """Score recent GOLDEN alerts on this ticker aligned with direction."""
    if not goldens:
        return FactorScore("golden", 0, "no recent GOLDEN")

    now = time.time()
    aligned_count = 0
    reasons = []
    for g in goldens:
        ts = g.get("ts") or g.get("fired_at") or 0
        if isinstance(ts, str):
            try:
                ts = dt.datetime.fromisoformat(ts.replace("Z", "")).timestamp()
            except ValueError:
                continue
        if now - ts > GOLDEN_FRESHNESS_S:
            continue

        option_type = (g.get("option_type") or "").lower()
        side = g.get("side") or ""  # BUY/SELL
        # CALL+BUY or PUT+SELL = bullish-for-stock
        is_bull = (option_type == "call" and side == "BUY") or (option_type == "put" and side == "SELL")
        is_bear = (option_type == "put" and side == "BUY") or (option_type == "call" and side == "SELL")
        if direction == "bullish" and is_bull:
            aligned_count += 1
            grade = g.get("grade", "?")
            reasons.append(f"{grade}")
        elif direction == "bearish" and is_bear:
            aligned_count += 1
            grade = g.get("grade", "?")
            reasons.append(f"{grade}")

    if aligned_count == 0:
        return FactorScore("golden", 0, "no aligned GOLDEN")

    pts = min(4, aligned_count * 2)
    return FactorScore(
        "golden", pts,
        f"{aligned_count} aligned GOLDEN ({', '.join(reasons[:3])})"
    )


# ── Grade mapping ─────────────────────────────────────────────────


def _grade(points: int) -> str:
    for g, threshold in GRADE_THRESHOLDS.items():
        if points >= threshold:
            return g
    return "C"


# ── Main evaluator ────────────────────────────────────────────────


def evaluate(
    ticker: str,
    gex_state: dict[str, Any] | None,
    fast_flow_snap: Any,  # FastFlowSnapshot or None
    regime: str | None,
    regime_confidence: str | None,
    recent_sweeps: list[dict[str, Any]],
    recent_goldens: list[dict[str, Any]],
) -> ConfluenceEval:
    """Full confluence evaluation for one ticker."""
    ticker = ticker.upper()

    # Pull needed fields from gex_state (may be None)
    gex_state = gex_state or {}
    spot = gex_state.get("actual_spot") or gex_state.get("spot") or gex_state.get("_spot")
    gex_signal = gex_state.get("signal")
    king_pos = gex_state.get("king_pos") or gex_state.get("king")
    king_neg = gex_state.get("king_neg") or gex_state.get("neg_king")
    floor = gex_state.get("floor")
    ceiling = gex_state.get("ceiling")

    # If we have MACRO exp_data, lift bifurcated king fields from there
    try:
        ed = gex_state.get("exp_data") or {}
        macro = ed.get("MACRO (ALL 200D)") or {}
        if macro.get("king_pos"):
            king_pos = macro.get("king_pos")
        if macro.get("king_neg"):
            king_neg = macro.get("king_neg")
    except Exception:
        pass

    # Fast-flow numbers
    if fast_flow_snap is None:
        ncp_roc = 0.0
        npp_roc = 0.0
        burst_signed = 0.0
        is_stalled = True
    else:
        ncp_roc = fast_flow_snap.ncp_roc_2min_dollars
        npp_roc = fast_flow_snap.npp_roc_2min_dollars
        burst_signed = fast_flow_snap.burst_signed_30s
        is_stalled = fast_flow_snap.is_stalled
        if fast_flow_snap.price:
            spot = spot or fast_flow_snap.price

    # Resolve direction + target
    direction, target_level, _dir_reason = _resolve_direction(
        spot, king_pos, king_neg, gex_signal, ncp_roc, npp_roc
    )

    if direction is None:
        # Ambiguous — return low-grade eval with zero points
        return ConfluenceEval(
            ticker=ticker,
            direction=None,
            total_points=0,
            max_points=20,
            grade="C",
            factors=[FactorScore("direction", 0, _dir_reason)],
            spot=spot,
            king_pos=king_pos,
            king_neg=king_neg,
            floor=floor,
            ceiling=ceiling,
            gex_signal=gex_signal,
            flow_regime=regime,
            eval_ts=time.time(),
        )

    # Score each factor
    gex_f = _score_gex(direction, spot, king_pos, king_neg, floor, ceiling, gex_signal)
    flow_f = _score_fast_flow(direction, ncp_roc, npp_roc, burst_signed, is_stalled)
    regime_f = _score_regime(direction, regime, regime_confidence)
    sweep_f = _score_sweeps(direction, recent_sweeps)
    golden_f = _score_golden(direction, recent_goldens)

    factors = [gex_f, flow_f, regime_f, sweep_f, golden_f]
    total = sum(f.points for f in factors)
    max_pts = 4 * len(factors)

    return ConfluenceEval(
        ticker=ticker,
        direction=direction,
        total_points=total,
        max_points=max_pts,
        grade=_grade(total),
        factors=factors,
        spot=spot,
        king_pos=king_pos,
        king_neg=king_neg,
        floor=floor,
        ceiling=ceiling,
        gex_signal=gex_signal,
        flow_regime=regime,
        target_level=target_level,
        eval_ts=time.time(),
    )
