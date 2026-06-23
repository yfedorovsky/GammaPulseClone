"""SOE Signals — Signal-to-Strike Pipeline.

Scans all cached tickers and generates scored trade recommendations
based on GEX structure, regime, king positioning, IV, and dealer flow.

Each signal includes:
  - Grade (A+ / A / B+ / B / C) based on 5-factor scoring
  - Specific contract: strike, expiration, type (CALL/PUT)
  - Entry/Target/Stop with R:R ratio
  - GEX context reasoning
  - Lifecycle tracking: PENDING → WIN / LOSS

Scoring factors (5 independent, max 6 points):
  1. GEX Structure (0-2) — composite of regime alignment, king polarity,
     ZGL position, and call/put wall.  These are correlated views of the
     same chain snapshot, so they are bounded to a single factor to avoid
     inflating confidence through collinearity.
  2. King Distance (0-1) — 0.5-3% sweet spot for directional trades
  3. Support/Resistance (0-1) — floor/ceiling structural confirmation
  4. IV Rank (0-1) — percentile rank vs. scanned universe (relative, not
     absolute thresholds)
  5. Macro Confluence (0-1) — SPY/QQQ/IWM directional alignment
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .cache import cache
from .config import get_settings
from .market_calendar import is_market_holiday

SIGNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS soe_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  grade TEXT NOT NULL,
  score REAL NOT NULL,
  max_score REAL DEFAULT 8,
  strike REAL,
  expiration TEXT,
  option_type TEXT,
  entry_price REAL,
  mid_price REAL,
  bid REAL,
  ask REAL,
  target REAL,
  target_label TEXT,
  stop REAL,
  stop_label TEXT,
  rr_ratio REAL,
  spot REAL,
  king REAL,
  floor_level REAL,
  ceiling_level REAL,
  zgl REAL,
  regime TEXT,
  iv REAL,
  delta REAL,
  gamma REAL,
  theta REAL,
  vega REAL,
  dte INTEGER,
  reasoning TEXT,
  status TEXT DEFAULT 'PENDING',
  outcome_price REAL,
  outcome_ts INTEGER,
  -- Apr 27: macro regime tag (shadow mode). Captures NONE/SOFT/HARD/A_ONLY
  -- per server.macro_regime.compute_macro_regime() at fire time. After
  -- 1-2 weeks of accumulated outcomes we'll backtest WR by tag.
  macro_regime_tag TEXT DEFAULT 'NONE',
  -- Apr 27 (Perplexity feedback): persist the factor blob so postmortems
  -- can answer "was HARD driven by event pressure, weak breadth, or
  -- concentration?" instead of only seeing the label. JSON blob.
  macro_regime_factors TEXT,
  -- 2026-06-02 PM: mark 1 after successful Telegram dispatch so the Mir
  -- TP window query can filter to signals the user actually received.
  -- Default 0 = not sent (broken-A blocks, regime gates, IV gates).
  telegram_sent INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_soe_ts ON soe_signals(ts);
CREATE INDEX IF NOT EXISTS idx_soe_ticker ON soe_signals(ticker, ts);
CREATE INDEX IF NOT EXISTS idx_soe_status ON soe_signals(status);
"""

AB_SCHEMA = """
CREATE TABLE IF NOT EXISTS ab_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,

  -- Mir context (shared)
  mir_conviction TEXT,
  mir_signal_type TEXT,
  mir_option_type TEXT,

  -- Contract context (shared)
  spot REAL,
  strike REAL,
  expiration TEXT,
  option_type TEXT,
  dte INTEGER,
  entry_price REAL,
  delta REAL,

  -- Book A: Mir+GEX (treatment)
  a_would_trade INTEGER NOT NULL DEFAULT 0,
  a_blocked_by TEXT,
  a_score REAL,
  a_grade TEXT,
  a_gate_label TEXT,
  a_target REAL,
  a_stop REAL,
  a_rr_ratio REAL,
  a_kelly_pct REAL,
  a_regime TEXT,
  a_king REAL,
  a_floor REAL,
  a_ceiling REAL,

  -- Book B: Mir-only (control)
  b_would_trade INTEGER NOT NULL DEFAULT 0,
  b_blocked_by TEXT,
  b_target REAL,
  b_stop REAL,
  b_rr_ratio REAL,
  b_kelly_pct REAL,
  b_gate_label TEXT,

  -- GEX contribution flags
  gex_entry_blocked INTEGER DEFAULT 0,
  gex_regime_blocked INTEGER DEFAULT 0,
  gex_improved_target INTEGER DEFAULT 0,
  gex_improved_stop INTEGER DEFAULT 0,
  gex_rr_delta REAL DEFAULT 0,

  -- Outcomes (filled later)
  status TEXT DEFAULT 'PENDING',
  a_outcome TEXT DEFAULT 'PENDING',
  b_outcome TEXT DEFAULT 'PENDING',
  outcome_spot REAL,
  outcome_ts INTEGER,
  a_pnl_pct REAL,
  b_pnl_pct REAL,
  a_max_spot REAL,
  a_min_spot REAL,
  b_max_spot REAL,
  b_min_spot REAL
);
CREATE INDEX IF NOT EXISTS idx_ab_ts ON ab_decisions(ts);
CREATE INDEX IF NOT EXISTS idx_ab_status ON ab_decisions(status);
CREATE INDEX IF NOT EXISTS idx_ab_mir ON ab_decisions(mir_conviction);
"""


def init_ab_db() -> None:
    with _conn() as c:
        c.executescript(AB_SCHEMA)


SETUP_FORMING_SCHEMA = """
CREATE TABLE IF NOT EXISTS setup_forming (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  score INTEGER NOT NULL,
  spot REAL,
  king REAL,
  floor REAL,
  regime TEXT,
  signal TEXT,
  rts_score INTEGER,
  ivp REAL,
  contract TEXT,
  reasons TEXT,
  flow_note TEXT,
  in_mir_sector INTEGER DEFAULT 0,
  is_pm INTEGER DEFAULT 1,
  is_monday INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_setup_forming_ts ON setup_forming(ts);
CREATE INDEX IF NOT EXISTS idx_setup_forming_ticker ON setup_forming(ticker, ts);
"""


def init_setup_forming_db() -> None:
    with _conn() as c:
        c.executescript(SETUP_FORMING_SCHEMA)


_seen_signals: set[str] = set()

def _load_recent_signals() -> None:
    """Load recent signal keys from DB so dedup survives restarts."""
    global _seen_signals
    try:
        import sqlite3
        import datetime as dt
        from .config import get_settings
        s = get_settings()
        now = time.time()
        hour_block = dt.datetime.now().hour // 2
        day = dt.datetime.now().strftime("%Y%m%d")
        c = sqlite3.connect(s.snapshot_db)
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT DISTINCT ticker FROM soe_signals WHERE ts > ?",
            (int(now - 7200),)
        ).fetchall()
        c.close()
        for r in rows:
            key = f"{r['ticker']}:{day}{hour_block}"
            _seen_signals.add(key)
        if _seen_signals:
            print(f"[SOE] Loaded {len(_seen_signals)} dedup keys from DB (survives restart)")
    except Exception as e:
        print(f"[SOE] Dedup load failed: {e}")

# Load on module import so dedup survives restarts
_load_recent_signals()


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


def init_signals_db() -> None:
    with _conn() as c:
        c.executescript(SIGNAL_SCHEMA)
        # Idempotent ALTERs for columns added after initial schema.
        # Each wrapped in try/except since SQLite ALTER raises if the
        # column already exists (no IF NOT EXISTS for ALTER).
        for ddl in (
            "ALTER TABLE soe_signals ADD COLUMN telegram_sent INTEGER DEFAULT 0",
        ):
            try:
                c.execute(ddl)
            except Exception:
                pass  # column already present


def get_signals(limit: int = 50, status: str = "", grade: str = "") -> list[dict[str, Any]]:
    with _conn() as c:
        q = "SELECT * FROM soe_signals WHERE 1=1"
        params: list = []
        if status:
            q += " AND status = ?"
            params.append(status)
        if grade:
            q += " AND grade = ?"
            params.append(grade)
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_signal_stats() -> dict[str, Any]:
    with _conn() as c:
        rows = c.execute("""
            SELECT grade,
                   COUNT(*) as total,
                   SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending
            FROM soe_signals
            GROUP BY grade
        """).fetchall()
    stats = {}
    for r in rows:
        d = dict(r)
        total_resolved = d["wins"] + d["losses"]
        d["win_rate"] = round(d["wins"] / total_resolved * 100, 1) if total_resolved > 0 else 0
        stats[d["grade"]] = d
    # Totals
    total = sum(s["total"] for s in stats.values())
    wins = sum(s["wins"] for s in stats.values())
    losses = sum(s["losses"] for s in stats.values())
    pending = sum(s["pending"] for s in stats.values())
    resolved = wins + losses
    return {
        "by_grade": stats,
        "total": total,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": round(wins / resolved * 100, 1) if resolved > 0 else 0,
    }


def _score_to_grade(score: float, max_score: float = 6) -> str:
    pct = score / max_score
    if pct >= 0.9:
        return "A+"
    if pct >= 0.75:
        return "A"
    if pct >= 0.625:
        return "B+"
    if pct >= 0.5:
        return "B"
    return "C"


# ── Regime-context filter (added 2026-04-24) ─────────────────────────
#
# Backtest across 30 days / 1,384 deduped B+ signals exposed that win
# rate is highly dependent on (signal_type, SPY 5d regime, IV band).
# Some combos run 50-61% win (above break-even), others run 9-30% (net
# losers). Pushing all B+ to Telegram mixed these and averaged out to
# ~21% current week / ~42% 30-day — both net-negative EV at standard
# 25%/50% discipline.
#
# This filter DOWNGRADES known losing combos to 'C' (still written to
# DB for analysis but not pushed to Telegram), PRESERVES neutral combos
# at their original grade, and downgrades A-grade SUPPORT BOUNCE to
# B+ in trending-up regimes where its edge disappears.
#
# Regime classifier (same as backtest):
#   SPY 5d return >= +1.5% → TREND_UP
#   SPY 5d return <= -1.5% → TREND_DOWN
#   otherwise              → CHOP
#
# IV bands:  <= 30 → low,  30-80 → mid,  > 80 → high


# Combos with resolved win rate <= 35% across 30-day backtest.
# Downgraded to 'C' so they don't hit Telegram.
_LOSING_BP_COMBOS: set[tuple[str, str, str]] = {
    ("MAGNET BREAKOUT",     "CHOP",      "low"),   #  9.1% (n=25)
    ("MAGNET BREAKOUT",     "CHOP",      "high"),  # 17.6% (n=40)
    ("PINNING PREMIUM SELL","CHOP",      "low"),   # 23.5% (n=27)
    ("POST BOTTOM LAUNCH",  "CHOP",      "low"),   # 28.8% (n=82)
    ("SUPPORT BOUNCE",      "CHOP",      "mid"),   # 27.8% (n=52) — but A-grade stays (see below)
    ("MAGNET BREAKOUT",     "TREND_UP",  "high"),  # 29.7% (n=37)
    ("SUPPORT BOUNCE",      "TREND_UP",  "high"),  # 30.0% (n=20)
}


def _regime_context_filter(
    signal_type: str,
    grade: str,
    spy_5d_pct: float | None,
    iv: float,
) -> str:
    """Return potentially adjusted grade. Never upgrades, only downgrades.

    Two specific rules:
      1. B+ in a 'losing combo' (see _LOSING_BP_COMBOS) -> 'C' (no Telegram).
      2. A-grade SUPPORT BOUNCE only has edge in CHOP regime (85-100% win).
         In TREND_UP it drops to 42-44%. Downgrade to B+ so it keeps its
         ticket but doesn't get A-grade Kelly sizing.
    """
    if spy_5d_pct is None:
        return grade

    # Regime classification
    if spy_5d_pct >= 1.5:
        regime = "TREND_UP"
    elif spy_5d_pct <= -1.5:
        regime = "TREND_DOWN"
    else:
        regime = "CHOP"

    # IV band
    iv_val = iv or 0
    if iv_val <= 30:
        iv_band = "low"
    elif iv_val <= 80:
        iv_band = "mid"
    else:
        iv_band = "high"

    # Rule 2: SUPPORT BOUNCE A-grade only keeps A in CHOP regime.
    # In TREND_UP the pattern loses its edge (44% win vs 85% in CHOP).
    # Downgrade to B+ — the signal is still valid for B+ tier.
    if signal_type == "SUPPORT BOUNCE" and grade in ("A", "A+"):
        if regime == "TREND_UP":
            return "B+"

    # Rule 1: B+ in a known-losing combo -> C (no Telegram).
    if grade == "B+":
        combo = (signal_type, regime, iv_band)
        if combo in _LOSING_BP_COMBOS:
            return "C"

    return grade


def _compute_signal_score(
    state: dict[str, Any],
    direction: str,  # "BULL" or "BEAR"
    confluence: dict[str, Any] | None = None,
    iv_universe: list[float] | None = None,
) -> tuple[float, list[str]]:
    """Score a trade signal on 5 independent factors (max 6 points).

    The old 8-factor scoring had 5 factors that were different views of
    the same chain snapshot (regime, king polarity, king distance, ZGL,
    call/put wall), which inflated confidence through collinearity.

    This version consolidates correlated sub-signals into a single
    GEX Structure factor (0-2 pts), keeping only genuinely independent
    dimensions as separate factors.
    """
    score = 0.0
    reasons: list[str] = []

    king = state.get("king", 0)
    floor_val = state.get("floor", 0)
    ceiling_val = state.get("ceiling", 0)
    zgl = state.get("zgl", 0)
    spot = state.get("actual_spot") or state.get("_spot") or 0
    regime = state.get("regime", "")
    iv = state.get("iv", 0)

    if not spot or not king:
        return 0, []

    king_dist_pct = abs(king - spot) / spot if spot else 0

    # Find king polarity
    ed = state.get("exp_data", {})
    macro = ed.get("MACRO (ALL 200D)", {})
    strikes_list = macro.get("strikes", [])
    king_strike = next((s for s in strikes_list if s.get("strike") == king), None)
    king_positive = king_strike["net_gex"] >= 0 if king_strike else True

    # ── Factor 1: GEX Structure (0-2) ──────────────────────────────
    # Composite of 4 correlated sub-signals.  Regime, king polarity,
    # ZGL position, and call/put walls are all downstream of the same
    # chain snapshot — bounding them to one factor prevents collinearity
    # from inflating the overall score.
    structure = 0.0
    sub_reasons: list[str] = []

    # 1a. Regime alignment
    if (direction == "BULL" and regime == "POS") or (direction == "BEAR" and regime == "NEG"):
        structure += 0.5
        sub_reasons.append(f"{regime} gamma aligns")

    # 1b. King polarity (or structural-bear equivalent).
    # For BULL: king is +GEX (magnet up).
    # For BEAR (legacy): king is -GEX (dealers short here, amplifies down).
    # For BEAR (structural, added 2026-04-22): +King is above spot and
    # net Neg GEX dominates by ≥1.5×. Credits the "+King too far to act
    # as magnet + Neg-wall overhead" pattern that RTX/LMT/AAOI/ABT showed.
    pos_g = state.get("pos_gex") or 0
    neg_g = abs(state.get("neg_gex") or 0)
    _struct_bear_source = state.get("_last_direction_source", "").startswith(
        ("gex_dominance_bear", "momentum_override_bear", "multi_day_fade_bear")
    )
    if (direction == "BULL" and king_positive) or (direction == "BEAR" and not king_positive):
        structure += 0.5
        side = "+GEX" if king_positive else "-GEX"
        sub_reasons.append(f"King ${king} is {side}")
    elif direction == "BEAR" and _struct_bear_source and neg_g >= pos_g * 1.5:
        structure += 0.5
        sub_reasons.append(
            f"Neg GEX dominant {neg_g/max(pos_g,1):.1f}× (structural bear)"
        )

    # 1e. Momentum severity bonus for structural bears.
    # A stock dropping ≥5% vs open is decisively in a bear trend — even if
    # its GEX structure still reads "bull" on paper, the tape has spoken.
    # FLY 2026-04-22 chart: $45.71 → $39.80 (-13% from day high). Staying
    # below 8/9 EMA post-10:45 AM. Without this bonus it scored only 2.5.
    vs_open_pct = (state.get("_intraday_momentum") or {}).get("vs_open_pct")
    if direction == "BEAR" and _struct_bear_source and vs_open_pct is not None:
        if vs_open_pct <= -5.0:
            structure += 1.0
            sub_reasons.append(f"Severe bear momentum {vs_open_pct:.1f}% vs open")
        elif vs_open_pct <= -3.0:
            structure += 0.5
            sub_reasons.append(f"Strong bear momentum {vs_open_pct:.1f}% vs open")
    elif direction == "BULL" and vs_open_pct is not None and vs_open_pct >= 3.0:
        # Symmetric for momentum bulls (gap-and-go catches)
        if vs_open_pct >= 5.0:
            structure += 1.0
            sub_reasons.append(f"Strong bull momentum {vs_open_pct:.1f}% vs open")
        else:
            structure += 0.5
            sub_reasons.append(f"Bull momentum {vs_open_pct:.1f}% vs open")

    # Structure factor caps at 2.0 to prevent collinearity from over-scoring
    structure = min(structure, 2.0)

    # 1c. ZGL position (true gamma-profile solve)
    if zgl:
        if (direction == "BULL" and spot > zgl) or (direction == "BEAR" and spot < zgl):
            structure += 0.5
            rel = "above" if spot > zgl else "below"
            sub_reasons.append(f"Spot {rel} ZGL ${zgl}")

    # 1d. Call/Put wall
    calls = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] > spot]
    puts = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] < spot]
    call_wall = max(calls, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if calls else None
    put_wall = min(puts, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if puts else None

    if direction == "BULL" and call_wall and call_wall > king:
        structure += 0.5
        sub_reasons.append(f"Call wall ${call_wall}")
    elif direction == "BEAR" and put_wall and put_wall < king:
        structure += 0.5
        sub_reasons.append(f"Put wall ${put_wall}")

    # GEX VIX conditioning (2026-05-20 — Perplexity follow-up bug fix).
    # Original implementation only applied in zero_dte_engine.py;
    # signals.py SOE scoring was missing this gate. Per the 8-yr SPY
    # backtest, GEX's directional edge collapses at VIX >= 20 (p=0.44).
    # Downgrade structure factor by up to 0.5 pts when vol is elevated.
    try:
        from .scalp_alerts import _current_vix
        _vix = _current_vix.get("level", 0) or 0
        if _vix >= 20:
            structure_pre = structure
            structure = max(0, structure - 0.5)
            sub_reasons.append(f"VIX {_vix:.1f}>=20 GEX downgrade (-{structure_pre - structure:.1f})")
    except Exception:
        pass

    score += structure
    strength = "Strong" if structure >= 1.5 else "Moderate" if structure >= 1.0 else "Weak"
    reasons.append(f"{strength} GEX structure ({structure:.1f}/2): {'; '.join(sub_reasons) or 'no alignment'}")

    # ── Factor 2: King Distance (0-1) ──────────────────────────────
    if 0.005 <= king_dist_pct <= 0.03:
        score += 1
        reasons.append(f"King distance {king_dist_pct*100:.1f}% in sweet spot (0.5-3%)")
    elif king_dist_pct < 0.003:
        score += 0.5
        reasons.append(f"Pinning near king ({king_dist_pct*100:.1f}%) — less directional")
    elif direction == "BEAR" and _struct_bear_source:
        # Structural bears: the +king is often far (useless magnet). Instead
        # credit -King (bear sell-wall) proximity if it's above spot within
        # a 3% radius. This is the "overhead resistance" equivalent to the
        # BULL sweet-spot king magnet distance.
        neg_king = state.get("king_neg") or 0
        if neg_king and neg_king > spot:
            nk_dist = (neg_king - spot) / spot
            if nk_dist <= 0.03:
                score += 1
                reasons.append(
                    f"-King ${neg_king} overhead at {nk_dist*100:.1f}% — bear sell-wall"
                )
            elif nk_dist <= 0.05:
                score += 0.5
                reasons.append(
                    f"-King ${neg_king} {nk_dist*100:.1f}% above — nearby resistance"
                )

    # ── Factor 3: Support/Resistance (0-1) ─────────────────────────
    if direction == "BULL" and floor_val and floor_val < spot:
        floor_dist = (spot - floor_val) / spot if spot else 0
        if floor_dist < 0.005:
            # Bouncing RIGHT off floor — highest conviction bounce setup
            score += 1
            reasons.append(f"Floor bounce! Spot within 0.5% of floor ${floor_val}")
        else:
            score += 1
            reasons.append(f"Floor at ${floor_val} provides downside support")
    elif direction == "BEAR" and ceiling_val and ceiling_val > spot:
        ceil_dist = (ceiling_val - spot) / spot if spot else 0
        if ceil_dist < 0.005:
            score += 1
            reasons.append(f"Ceiling rejection! Spot within 0.5% of ceiling ${ceiling_val}")
        else:
            score += 1
            reasons.append(f"Ceiling at ${ceiling_val} caps upside")
    elif direction == "BEAR" and _struct_bear_source and (not floor_val or floor_val <= 0):
        # Structural bear with NO floor detected below spot — nothing
        # structural to stop the decline. This is the IP-style "air pocket"
        # scenario and earns the full factor 3 credit.
        score += 1
        reasons.append("No floor below spot — structural air pocket")
    elif direction == "BEAR" and _struct_bear_source and floor_val and floor_val < spot:
        # Floor exists but far below — partial credit, the decline has room
        floor_dist_pct = (spot - floor_val) / spot if spot else 0
        if floor_dist_pct >= 0.05:
            score += 0.5
            reasons.append(
                f"Floor ${floor_val} {floor_dist_pct*100:.1f}% below — decline has room"
            )

    # ── Factor 4: IV Environment (0-1) ───────────────────────────
    # Two-part check using per-ticker metrics (not cross-universe):
    #   a) IVP (IV Percentile vs own 52-week history)
    #   b) IV/HV ratio (Volatility Risk Premium — is premium cheap or rich?)
    #
    # Both must align for full score.  Prevents entering when IVP is low
    # but IV/HV is high (options still expensive relative to actual movement).
    iv_score = 0.0
    iv_reasons: list[str] = []

    ivp = state.get("_ivp")  # Pre-computed in worker
    ivhv = state.get("_ivhv_ratio")  # Pre-computed in worker

    if ivp is not None:
        if ivp <= 30:
            iv_score += 0.5
            iv_reasons.append(f"IVP {ivp:.0f}% (cheap vs 52w)")
        elif ivp <= 50:
            iv_score += 0.25
            iv_reasons.append(f"IVP {ivp:.0f}% (moderate)")
        else:
            iv_reasons.append(f"IVP {ivp:.0f}% (elevated)")

    if ivhv is not None:
        if ivhv < 1.2:
            iv_score += 0.5
            iv_reasons.append(f"IV/HV {ivhv:.2f} (fair premium)")
        elif ivhv < 1.5:
            iv_score += 0.25
            iv_reasons.append(f"IV/HV {ivhv:.2f} (slightly rich)")
        else:
            iv_reasons.append(f"IV/HV {ivhv:.2f} (expensive premium)")

    if iv_score > 0:
        score += min(iv_score, 1.0)  # Cap at 1 point
        reasons.append(f"IV Environment ({min(iv_score,1.0):.1f}/1): {'; '.join(iv_reasons)}")
    elif iv_reasons:
        reasons.append(f"IV Environment (0/1): {'; '.join(iv_reasons)}")
    elif iv and iv_universe and len(iv_universe) >= 10:
        # Fallback to cross-universe rank if no per-ticker history yet
        higher = sum(1 for v in iv_universe if v > iv)
        rank = higher / len(iv_universe)
        if rank >= 0.7:
            score += 0.25
            reasons.append(f"IV {iv*100:.0f}% low vs universe (no ticker history yet)")
    elif iv:
        if iv < 0.25:
            score += 0.25
            reasons.append(f"IV {iv*100:.0f}% appears low (no history data)")

    # ── Factor 5: Macro Context (0-1) ────────────────────────────
    # Two sub-signals, each worth 0.5:
    #   a) GEX Confluence: SPY/QQQ/IWM king polarity alignment
    #   b) Breadth (NYMO/NAMO): market internals stretched/supportive
    #
    # Per unified architecture note: "NYMO/NAMO tells you WHETHER
    # market internals are stretched enough for GEX structure to
    # produce a real reversal."
    macro_score = 0.0
    macro_reasons: list[str] = []

    # 5a. GEX Confluence (0-0.5)
    if confluence:
        bull_count = 0
        for t in ["SPY", "QQQ", "IWM"]:
            cd = confluence.get(t, {})
            c_ed = cd.get("exp_data", {})
            c_macro = c_ed.get("MACRO (ALL 200D)", {})
            c_king = c_macro.get("king", 0)
            c_strikes = c_macro.get("strikes", [])
            c_king_s = next((s for s in c_strikes if s.get("strike") == c_king), None)
            if c_king_s and c_king_s.get("net_gex", 0) >= 0:
                bull_count += 1
        if direction == "BULL" and bull_count >= 2:
            macro_score += 0.5
            macro_reasons.append(f"GEX {bull_count}/3 bullish")
        elif direction == "BEAR" and bull_count <= 1:
            macro_score += 0.5
            macro_reasons.append(f"GEX {3 - bull_count}/3 bearish")

    # 5b. Breadth — NYMO/NAMO (0-0.5)
    # For index ETFs (SPY/QQQ/IWM), reduce breadth penalty weight.
    # Intraday floor bounces on liquid indexes are valid even when
    # breadth is overbought — the GEX structure dominates.
    ticker_name = state.get("_ticker", "")
    is_index = ticker_name in ("SPY", "QQQ", "IWM", "DIA", "SPX", "NDX")
    breadth_weight = 0.25 if is_index else 0.5  # Halved for indexes

    breadth_data = state.get("_breadth")
    if breadth_data:
        from .breadth import score_for_direction
        b_score, b_reason = score_for_direction(breadth_data, direction)
        if b_score > 0:
            macro_score += min(b_score * breadth_weight, 0.5)
            macro_reasons.append(b_reason)
        elif b_score < 0:
            # Breadth penalty: deteriorating internals into a bounce
            # Reduced penalty for indexes (intraday structure > daily breadth)
            # When GEX confluence is 3/3 aligned, don't fight the tape —
            # cap penalty so breadth alone can't block A-grade signals
            if macro_score >= 0.5:  # GEX confluence already bullish/bearish
                penalty_weight = 0.1 if is_index else 0.15  # Minimal penalty when tape agrees
                macro_reasons.append(f"{b_reason} (reduced: GEX confirms trend)")
            else:
                penalty_weight = 0.25 if is_index else 0.5
                macro_reasons.append(b_reason)
            macro_score = max(macro_score + b_score * penalty_weight, 0)

    score += min(macro_score, 1.0)
    if macro_reasons:
        reasons.append(f"Macro context ({min(macro_score,1.0):.1f}/1): {'; '.join(macro_reasons)}")

    # ── Trend Quality Gate (RTS penalty/bonus) ────────────────────
    # GEX structure alone doesn't know if price is trending into a level
    # (breakdown) or bouncing off it (support). RTS catches this.
    # GS 4/15 lesson: "SUPPORT BOUNCE" A-grade on a stock crashing from
    # $927 to $900. RTS would have flagged the downtrend.
    #
    # Not a 6th factor — it adjusts the total score:
    #   RTS < 20: -0.5 (actively weak, fighting the trend)
    #   RTS 20-40: -0.25 (below average)
    #   RTS 40-60: no change (neutral)
    #   RTS >= 70: +0.25 (leader, trend alignment bonus)
    #
    # Skip for indexes (SPY/QQQ/IWM don't have meaningful RS vs themselves)
    rts_data = state.get("_rts")
    trend_day_data = state.get("_trend_day") or {}
    is_trend_day = trend_day_data.get("trend_mode", "NORMAL") in ("TREND_DAY", "EXTREME_TREND")

    if rts_data and isinstance(rts_data, dict) and not is_index:
        rts_score_val = rts_data.get("score", 50)

        if is_trend_day:
            # Trend day override: stock is moving NOW regardless of 20-day history.
            # MSFT 4/15 lesson: RTS 15 but +5% gap day = A++++ setup.
            # Don't penalize, only reward leaders.
            if rts_score_val >= 70:
                score += 0.25
                reasons.append(f"RTS {rts_score_val} LEADER + TREND DAY (+0.25)")
            else:
                reasons.append(f"RTS {rts_score_val} (trend day — penalty waived)")
        else:
            # Normal day: penalize weak trends, reward leaders
            if rts_score_val < 20:
                score -= 0.5
                reasons.append(f"RTS {rts_score_val} WEAK — trend penalty (-0.5)")
            elif rts_score_val < 40:
                score -= 0.25
                reasons.append(f"RTS {rts_score_val} below avg — trend penalty (-0.25)")
            elif rts_score_val >= 70:
                score += 0.25
                reasons.append(f"RTS {rts_score_val} LEADER — trend bonus (+0.25)")
            else:
                reasons.append(f"RTS {rts_score_val} neutral")

    # ── Factor 6: Volume Surge bonus (0 to +0.75) ──────────────────
    # Real moves have volume backing. 2× avg = conviction, 5× = explosive.
    # Borrowed 2026-04-22 from Discord buddy's briefing scoring (-5 to +15
    # scaled to our 0-6 grade). Additive bonus — doesn't raise max_score,
    # just separates real moves from noise. Particularly useful for bears
    # (distribution confirmed by volume vs drift on low volume = trap).
    today_vol = state.get("_today_volume") or 0
    avg_vol = state.get("_avg_volume") or 0
    if avg_vol > 0:
        vol_ratio = today_vol / avg_vol
        vol_bonus = 0.0
        if vol_ratio >= 5.0:
            vol_bonus = 0.75
        elif vol_ratio >= 3.0:
            vol_bonus = 0.50
        elif vol_ratio >= 2.0:
            vol_bonus = 0.25
        elif vol_ratio >= 1.5:
            vol_bonus = 0.15
        if vol_bonus > 0:
            score += vol_bonus
            reasons.append(f"Volume surge {vol_ratio:.1f}× avg (+{vol_bonus:.2f})")

    # ── Guard: Drawdown / chase protection ─────────────────────────
    # Stops us firing A/B+ on extreme-stretched bulls (chase trap) or
    # extreme-oversold bears (falling knife / dip-buyer rally). Scaled
    # down to our 0-6 grade: max -2.5 moves A → C, killing the fire.
    #
    # Thresholds calibrated for momentum-leader context: real breakouts
    # (AEHR +171% 1mo) naturally sit 25-45% above MA20. Only penalize
    # when STRETCH IS EXTREME (past 30% bulls, past 25% bears). Moderate
    # extension (+20% bulls, -15% bears) = -1.0 warning but tradeable.
    ma20_guard = (state.get("_rts") or {}).get("mas", {}).get("ma20")
    if ma20_guard and spot:
        ma20_dist = (spot - ma20_guard) / ma20_guard
        if direction == "BULL":
            if ma20_dist > 0.30:
                score -= 2.5
                reasons.append(
                    f"⚠️ CHASE GUARD: spot {ma20_dist*100:+.1f}% vs 20MA "
                    f"${ma20_guard:.2f} (−2.5 extreme stretch)"
                )
            elif ma20_dist > 0.20:
                score -= 1.0
                reasons.append(
                    f"Stretched: spot {ma20_dist*100:+.1f}% vs 20MA (−1.0)"
                )
        elif direction == "BEAR":
            if ma20_dist < -0.25:
                score -= 2.5
                reasons.append(
                    f"⚠️ FALLING KNIFE: spot {ma20_dist*100:+.1f}% vs 20MA "
                    f"${ma20_guard:.2f} (−2.5 overextended)"
                )
            elif ma20_dist < -0.15:
                score -= 1.0
                reasons.append(
                    f"Overextended: spot {ma20_dist*100:+.1f}% vs 20MA (−1.0)"
                )

    return score, reasons


# ── Momentum confirmation gate (added 2026-04-24) ─────────────────
#
# Diagnostic finding: among 50 losing B+ signals this week, 66% faded
# DOWN in the hour after we fired. Winners had +0.57% post-signal move,
# losers had -0.41% — but at fire time they looked statistically
# identical (both had ~0.1-0.25% prior-hour movement).
#
# The differentiator: winners had ACTIVE momentum building, losers were
# quietly sitting near a level. This gate forces B+ signals to require
# 0.3%+ recent (15-min) spot movement in the signal direction before
# firing. Coin-flip setups get downgraded to C (DB-only, no Telegram).
#
# Tradeoff: cuts ~40% of B+ fires. Loses some Mir-style anticipation
# entries (where Mir buys BEFORE the move starts). At 21% win rate,
# the volume of false signals overwhelms the anticipation alpha — gate
# is net positive on EV even if it kills some good entries.

MOMENTUM_LOOKBACK_SEC = 15 * 60  # 15 minutes
MOMENTUM_THRESHOLD_PCT = 0.30  # require >= 0.3% move in signal direction


def _momentum_confirmation_check(ticker: str, direction: str) -> bool:
    """Return True if recent spot momentum confirms signal direction.

    Queries snapshots.db for spot 15 min ago vs latest. Requires at
    least MOMENTUM_THRESHOLD_PCT move in signal-aligned direction.

    Fail-open: if we can't read history (cold start, sparse data),
    return True so the gate doesn't block all signals during warmup.
    """
    if not ticker:
        return True
    import sqlite3
    try:
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        now_ts = int(time.time())
        # Latest spot
        cur = conn.execute(
            "SELECT spot FROM snapshots WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
            (ticker,)
        )
        latest = cur.fetchone()
        # Spot 15 min ago
        cur = conn.execute(
            "SELECT spot FROM snapshots WHERE ticker = ? AND ts <= ? "
            "ORDER BY ts DESC LIMIT 1",
            (ticker, now_ts - MOMENTUM_LOOKBACK_SEC)
        )
        prior = cur.fetchone()
        conn.close()
        if not latest or not prior or not latest[0] or not prior[0]:
            return True  # fail-open
        pct_move = (latest[0] - prior[0]) / prior[0] * 100
        if direction == "BULL":
            return pct_move >= MOMENTUM_THRESHOLD_PCT
        elif direction == "BEAR":
            return pct_move <= -MOMENTUM_THRESHOLD_PCT
        return True
    except Exception:
        return True  # fail-open on any error


# ── Convergence bonus (Apr 27 — NVDA case study) ────────────────────
#
# When 2+ independent signal systems detect the same setup on a ticker
# within 30 min, that's institutional convergence — the highest-conviction
# setup pattern. Validation: today NVDA fired SOE PINNING PREMIUM SELL +
# NET FLOW (twice) + $7.72M call sweep + Mir's call within 100 min, and
# the SOE-picked $215C 5/6 closed +86% intraday.
#
# Signals counted (must match BULL or BEAR direction):
#   1. net_flow_alerts row in last 30 min, gap_direction matches
#   2. flow_alerts row in last 30 min with notional >= $5M, sentiment matches
#
# If ≥1 of those fires (alongside the SOE itself = 2+ total), add 0.5 to
# score. This pushes borderline B+ → A and biases sizing/Telegram toward
# the convergence trade.

# High-score fade rule — Apr 27 (4-LLM consensus on the inverse score
# finding). Phase 6 audit: 5.0+ = 20% 1d hit, 3.75-4.1 = 67% 1d hit.
# When a SOE signal scores in the inversion zone, AUTO-TRADE IS BLOCKED
# and Telegram renders a FADE WATCH footer with recommended manual size.
# Rule converged across Gemini/Grok/OpenAI/Perplexity (3 specified 0.25x,
# 1 specified 0.5x — taking the more conservative number).
SOE_HIGH_SCORE_FADE_THRESHOLD = 4.8
SOE_HIGH_SCORE_FADE_SIZE_MULT = 0.25  # recommended manual size when taking

CONVERGENCE_LOOKBACK_SEC = 1800  # 30 min
CONVERGENCE_MIN_AGE_SEC = 300  # flow must be >=5 min old (avoid self-referential)
CONVERGENCE_BONUS_PTS = 0.5
CONVERGENCE_BONUS_CAP_PTS = 0.5  # MAX total bonus (Perplexity Apr 27: prior +1.0
                                  # was a full grade upgrade — too generous)
CONVERGENCE_DEDUPE_WINDOW_SEC = 3600  # 1hr no-double-upgrade per ticker+direction

# Per-ticker flow notional floor. $5M is huge for SNDK, trivial for AAPL.
# Mega-caps require higher bar; thin cohort names trip on smaller flow.
CONVERGENCE_FLOW_FLOOR_BY_TICKER: dict[str, int] = {
    # Mega-caps — $5M is daily noise, need higher
    "SPY": 20_000_000, "QQQ": 20_000_000, "IWM": 10_000_000,
    "AAPL": 15_000_000, "MSFT": 15_000_000, "GOOGL": 10_000_000,
    "GOOG": 10_000_000, "AMZN": 15_000_000, "META": 15_000_000,
    "NVDA": 15_000_000, "TSLA": 15_000_000, "AVGO": 8_000_000,
    "AMD": 8_000_000, "QCOM": 6_000_000,
    # Phase 6 thin/very-thin cohort — $5M is rare so meaningful at lower bar
    "AESI": 1_000_000, "ANAB": 1_000_000, "CAPR": 1_000_000,
    "LAR": 1_000_000, "LASR": 1_000_000, "NBR": 1_000_000,
    "PUMP": 1_000_000, "RES": 1_000_000, "TROX": 1_000_000,
    "PTEN": 2_000_000, "UCTT": 2_000_000,
}
DEFAULT_CONVERGENCE_FLOOR = 5_000_000


def _safe_macro_regime_tag() -> str:
    """Wrap macro_regime_tag() with belt-and-suspenders fail-open. Apr 27
    shadow-mode addition; never blocks signal generation if calendar cache
    or breadth query fails."""
    try:
        from .macro_regime import macro_regime_tag
        return macro_regime_tag()
    except Exception:
        return "NONE"


def _safe_macro_regime_full() -> dict[str, Any]:
    """Return the full regime dict (tag + reasons + factors blob) for sig
    payload. Used by the Telegram formatter and persisted to DB so
    postmortems can answer 'was HARD driven by event pressure, weak
    breadth, or concentration?' (Perplexity Apr 27 suggestion)."""
    try:
        import json as _json
        from .macro_regime import compute_macro_regime
        r = compute_macro_regime()
        # Persist a compact JSON blob with the discriminating factors.
        # Keep the most decision-relevant fields; skip noise like
        # individual ticker pcts unless they're the discriminator.
        factors = {
            "hours_to_fomc": r.get("calendar", {}).get("hours_to_fomc"),
            "weighted_megacap_72h": r.get("calendar", {}).get("weighted_megacap_72h"),
            "weighted_megacap_48h": r.get("calendar", {}).get("weighted_megacap_48h"),
            "earnings_names": r.get("calendar", {}).get("earnings_names", [])[:8],
            "qqq_pct": r.get("breadth", {}).get("qqq_pct"),
            "qqqe_pct": r.get("breadth", {}).get("qqqe_pct"),
            "spy_pct": r.get("breadth", {}).get("spy_pct"),
            "xmag_pct": r.get("breadth", {}).get("xmag_pct"),
            "is_narrow_leadership": r.get("breadth", {}).get("is_narrow_leadership"),
            "is_concentrated_in_mag7": r.get("breadth", {}).get("is_concentrated_in_mag7"),
            "have_breadth_data": r.get("breadth", {}).get("have_breadth_data"),
        }
        return {
            "tag": r.get("tag", "NONE"),
            "reasons": r.get("reasons", []),
            "factors_json": _json.dumps(factors, default=str),
        }
    except Exception:
        return {"tag": "NONE", "reasons": [], "factors_json": "{}"}


def _check_convergence_bonus(ticker: str, direction: str) -> tuple[float, list[str]]:
    """Return (bonus_pts, reasons) for cross-signal convergence on this
    ticker+direction in the last 30 min. Fail-open returns (0, []).

    Apr 27 hardenings (Perplexity feedback):
      - Cap at +0.5 (was +1.0) — full grade upgrade was too generous
      - Time ordering: flow must be >=5 min old to avoid self-referential
        "the SOE-triggering move attracted flow_alerts that promote it"
      - Per-ticker floor: scale by ticker (mega-caps higher, thin lower)
      - No-double-upgrade: skip bonus if same ticker+direction already had
        an A/A+ alert in last hour (prevents grindy-move runaway A's)
    """
    if not ticker or direction not in ("BULL", "BEAR"):
        return 0.0, []
    import sqlite3
    bonus = 0.0
    reasons: list[str] = []
    try:
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        now_ts = int(time.time())
        cutoff = now_ts - CONVERGENCE_LOOKBACK_SEC
        max_ts = now_ts - CONVERGENCE_MIN_AGE_SEC  # flow must be older than this

        # No-double-upgrade check — if same ticker+direction already fired
        # A/A+ within last hour, skip the bonus (this move already got
        # promoted; subsequent fires are most likely the same accumulation
        # late in the move).
        dir_match_chars = ("BULL", "▲", "LONG", "BUY")
        if direction == "BEAR":
            dir_match_chars = ("BEAR", "▼", "SHORT", "SELL")
        try:
            placeholders = ",".join("?" * len(dir_match_chars))
            row = conn.execute(
                f"SELECT COUNT(*) FROM soe_signals "
                f"WHERE ticker = ? AND ts >= ? "
                f"AND grade IN ('A', 'A+') "
                f"AND direction IN ({placeholders})",
                (ticker, now_ts - CONVERGENCE_DEDUPE_WINDOW_SEC) + dir_match_chars,
            ).fetchone()
            if row and row[0] > 0:
                # Already promoted same direction in last hour — skip bonus
                conn.close()
                return 0.0, [f"convergence skipped (prior A within "
                             f"{CONVERGENCE_DEDUPE_WINDOW_SEC//60}min)"]
        except sqlite3.OperationalError:
            pass

        # Per-ticker flow floor
        flow_floor = CONVERGENCE_FLOW_FLOOR_BY_TICKER.get(
            ticker, DEFAULT_CONVERGENCE_FLOOR
        )

        # 1. net_flow_alerts match (must be >=5min old)
        gap_match = "bullish" if direction == "BULL" else "bearish"
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM net_flow_alerts "
                "WHERE ticker = ? AND ts >= ? AND ts <= ? "
                "AND gap_direction = ?",
                (ticker, cutoff, max_ts, gap_match),
            ).fetchone()
            if row and row[0] > 0:
                bonus += CONVERGENCE_BONUS_PTS
                reasons.append(f"net_flow_alert {gap_match} ({row[0]}x)")
        except sqlite3.OperationalError:
            pass

        # 2. flow_alerts match — direction-aligned + per-ticker size + age
        sentiment_match = "BULLISH" if direction == "BULL" else "BEARISH"
        opt_type = "call" if direction == "BULL" else "put"
        try:
            row = conn.execute(
                "SELECT COUNT(*), MAX(COALESCE(sweep_notional, notional)) "
                "FROM flow_alerts "
                "WHERE ticker = ? AND ts >= ? AND ts <= ? "
                "AND sentiment = ? AND option_type = ? "
                "AND COALESCE(sweep_notional, notional, 0) >= ?",
                (ticker, cutoff, max_ts, sentiment_match, opt_type, flow_floor),
            ).fetchone()
            if row and row[0] > 0:
                # Don't double-bonus if net_flow already added — cap at +0.5
                if bonus < CONVERGENCE_BONUS_CAP_PTS:
                    bonus += CONVERGENCE_BONUS_PTS
                reasons.append(
                    f"flow_alert {sentiment_match} {opt_type}s "
                    f"(largest ${(row[1] or 0)/1e6:.1f}M, {row[0]}x, "
                    f"floor ${flow_floor/1e6:.0f}M)"
                )
        except sqlite3.OperationalError:
            pass

        conn.close()
    except Exception:
        return 0.0, []  # fail-open

    # Hard cap at +0.5 — single source contributes max
    if bonus > CONVERGENCE_BONUS_CAP_PTS:
        bonus = CONVERGENCE_BONUS_CAP_PTS
    return bonus, reasons


# ── Dynamic stop helpers (Option 3 — added 2026-04-24) ──────────────
#
# Diagnostic: 54% of B+ losses take >2 hrs to materialize (slow drift).
# 66% of losers fade within 1 hr post-fire. Static -3% trail isn't the
# right shape for these — we want stops that adapt to:
#   - Volatility (ATR or IV) — high-vol names need more room
#   - Time decay (DTE) — closer expiry = tighter stop (theta accel)
#
# Output: stop distance as % of spot, then converted to absolute spot
# level. Replaces the old static -3%/+3% trail in _select_contract's
# RR cascade. Structural stops (Floor / Ceiling) stay as alternatives.


def _compute_atr_pct_from_snapshots(ticker: str | None, days: int = 14) -> float | None:
    """Compute average true range as % of spot from snapshot history.
    Returns None if insufficient data (fall back to IV-based estimate)."""
    if not ticker:
        return None
    import sqlite3
    try:
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        cur = conn.execute(
            "SELECT date(ts, 'unixepoch') as d, MIN(spot) as lo, MAX(spot) as hi "
            "FROM snapshots WHERE ticker = ? AND ts >= ? "
            "GROUP BY date(ts, 'unixepoch') ORDER BY d DESC LIMIT ?",
            (ticker, int(time.time()) - days * 2 * 86400, days)
        )
        rows = cur.fetchall()
        conn.close()
        if len(rows) < 5:
            return None
        ranges_pct = []
        for r in rows:
            lo, hi = r[1], r[2]
            if lo and hi and lo > 0:
                mid = (lo + hi) / 2
                ranges_pct.append((hi - lo) / mid * 100)
        if not ranges_pct:
            return None
        return sum(ranges_pct) / len(ranges_pct)
    except Exception:
        return None


def _dynamic_stop_distance_pct(
    ticker: str | None, dte: int, iv: float | None,
) -> tuple[float, str]:
    """Return (stop_distance_pct, source_label) for the given contract.

    Combines ATR (preferred, computed from snapshot daily ranges) or IV
    (fallback) with a DTE-based scaling factor. Tighter stops on shorter
    expiries (theta acceleration); looser stops on high-vol names (need
    room to breathe past noise).
    """
    atr_pct = _compute_atr_pct_from_snapshots(ticker)
    if atr_pct is not None:
        base_pct = atr_pct
        source = "ATR"
    else:
        iv_val = iv or 0
        if iv_val >= 80:
            base_pct = 4.0
        elif iv_val >= 50:
            base_pct = 3.0
        elif iv_val >= 30:
            base_pct = 2.0
        else:
            base_pct = 1.5
        source = f"IV{int(iv_val)}"

    # DTE scaling — tighter as expiry approaches
    dte_val = dte if dte is not None else 7
    if dte_val <= 0:
        scale = 0.5
    elif dte_val <= 2:
        scale = 0.7
    elif dte_val <= 7:
        scale = 1.0
    elif dte_val <= 14:
        scale = 1.2
    else:
        scale = 1.5

    final_pct = base_pct * scale
    # Floor at 1.5%, ceiling at 8% — sanity bounds
    final_pct = max(1.5, min(8.0, final_pct))
    label = f"{source}/{dte_val}D"
    return final_pct, label


def _select_contract(
    state: dict[str, Any],
    direction: str,
    tradier_chains: dict | None = None,
    relaxed: bool = False,
    mir_mode: bool = False,
    ticker: str | None = None,
) -> dict[str, Any] | None:
    """Select the optimal contract for the signal.

    Quality gates (from discord workflow + triple review consensus):
      - Bid-ask spread must be < 10% of mid price (liquidity)
      - Open interest must be > 500 on the strike (exit-ability)
      - Delta target: 0.30-0.55 (enough directional sensitivity)
      - DTE sweet spot: 10, range 7-21

    When relaxed=True (setup forming alerts), gates are loosened:
      - Spread < 25%, OI > 50, Delta 0.15-0.75

    When mir_mode=True (Mir momentum signals):
      - DTE 7-14 preferred, skip 0DTE entirely
      - Delta 0.35-0.50 (narrower sweet spot)
    """
    if mir_mode:
        spread_limit = 0.10
        oi_limit = 500
        delta_lo = 0.35
        delta_hi = 0.50
    elif relaxed:
        spread_limit = 0.25
        oi_limit = 50
        delta_lo = 0.15
        delta_hi = 0.75
    else:
        spread_limit = 0.10
        # OI gate: 500 for 0DTE (needs exit liquidity NOW), 100 for 7+ DTE
        # (OI builds as contracts approach expiration — mid-week 7-14 DTE
        # typically has 50-300 OI on SPY/QQQ which is fine for 1-2 contract trades)
        oi_limit = 100
        delta_lo = 0.25
        delta_hi = 0.60
    spot = state.get("actual_spot") or state.get("_spot") or 0
    king = state.get("king", 0)
    if not spot:
        return None

    exps = state.get("exps", [])
    raw_contracts = state.get("_raw_contracts", {})

    # ── Find expiration ─────────────────────────────────────────────
    import datetime
    today = datetime.date.today()
    today_str = today.isoformat()
    ticker_name = state.get("_ticker", "")
    is_0dte_eligible = ticker_name in ("SPY", "QQQ")

    target_exp = None
    target_dte = 0

    # For SPY/QQQ: try 0DTE first (today's expiration) — skip in mir_mode
    if is_0dte_eligible and not mir_mode:
        for exp in exps:
            if exp == today_str:
                target_exp = exp
                target_dte = 0
                break

    # Standard: 7-21 DTE, sweet spot 10 (backtest: 7-14 DTE >> 14-21 >> 21-35)
    # Mir mode: 7-14 DTE (backtest validated: 7-14 >> 14-21 >> 21-35)
    dte_lo = 7
    dte_hi = 14 if mir_mode else 21
    if not target_exp:
        for exp in exps:
            if exp.startswith("MACRO"):
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp)
                dte = (exp_date - today).days
                if dte_lo <= dte <= dte_hi:
                    if target_exp is None or abs(dte - 10) < abs(target_dte - 10):
                        target_exp = exp
                        target_dte = dte
            except ValueError:
                continue

    # Fallback: nearest exp >= 3 DTE
    if not target_exp:
        for exp in exps:
            if exp.startswith("MACRO"):
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp)
                dte = (exp_date - today).days
                if dte >= 3:
                    target_exp = exp
                    target_dte = dte
                    break
            except ValueError:
                continue

    # Last resort for SPY/QQQ: allow 1-2 DTE
    if not target_exp and is_0dte_eligible:
        for exp in exps:
            if exp.startswith("MACRO"):
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp)
                dte = (exp_date - today).days
                if dte >= 0:
                    target_exp = exp
                    target_dte = dte
                    break
            except ValueError:
                continue

    if not target_exp:
        return None

    # ── Select contract from raw chain data ───────────────────────
    otype = "call" if direction == "BULL" else "put"
    chain = raw_contracts.get(target_exp, [])

    # Filter to matching option type and near-OTM strikes
    candidates = []
    for c in chain:
        c_type = (c.get("option_type") or "").lower()
        if c_type != otype:
            continue
        strike = c.get("strike", 0)
        if not strike:
            continue

        # Direction filter: OTM candidates
        if direction == "BULL" and strike < spot:
            continue
        if direction == "BEAR" and strike > spot:
            continue

        # ── Quality Gate 1: Bid-ask spread ─────────────────────
        bid = c.get("bid", 0) or 0
        ask = c.get("ask", 0) or 0
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
        spread = ask - bid
        spread_pct = spread / mid if mid > 0 else 999

        if spread_pct > spread_limit:
            continue

        # ── Quality Gate 2: Open interest ──────────────────────
        oi = c.get("open_interest", 0) or 0
        if oi < oi_limit:
            continue

        # ── Quality Gate 3: Delta range ────────────────────────
        greeks = c.get("greeks") or {}
        delta = abs(greeks.get("delta", 0) or 0)
        if delta < delta_lo or delta > delta_hi:
            continue

        candidates.append({
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pct": round(spread_pct * 100, 1),
            "oi": oi,
            "volume": c.get("volume", 0) or 0,
            "delta": greeks.get("delta", 0),
            "gamma": greeks.get("gamma", 0),
            "theta": greeks.get("theta", 0),
            "vega": greeks.get("vega", 0),
            "iv": greeks.get("mid_iv") or greeks.get("smv_vol") or 0,
        })

    if not candidates:
        return None

    # Sort by proximity to ideal delta (0.40-0.45)
    candidates.sort(key=lambda c: abs(abs(c["delta"]) - 0.425))
    selected = candidates[0]

    # ── Entry / Target / Stop ─────────────────────────────────────
    # Smart RR cascade (Patch E, 2026-04-22) — pick the target+stop pair
    # that maximizes RR from the available structural levels.
    #
    # Prior issue: ARM fix (Apr 22 morning) stretched to ceiling when
    # king was BELOW spot. Good. But OKLO same afternoon had king only
    # +1.6% above spot — target=king gave reward $1.08 vs risk $3.92 to
    # distant floor = RR 0.27, blocked. Real structural trade is target
    # = ceiling $75 (+8.8%) + tighter stop (spot*0.97), RR 2.94.
    #
    # Cascade chooses from:
    #   BULL targets: king (if >spot), ceiling (if >spot), spot*1.02
    #   BULL stops:   floor (if within 5% of spot), spot*0.97
    # and picks the combination with the best RR.
    ceiling = state.get("ceiling") or 0
    floor_v = state.get("floor") or 0

    # Dynamic stop distance — Option 3 (replaces static -3%/+3% trail).
    # Uses ATR (or IV fallback) scaled by DTE. Bounds [1.5%, 8%] of spot.
    iv_for_stop = state.get("iv") or (state.get("_rts") or {}).get("iv")
    dyn_stop_pct, dyn_stop_source = _dynamic_stop_distance_pct(
        ticker, target_dte, iv_for_stop
    )
    dyn_stop_label = f"-{dyn_stop_pct:.1f}% {dyn_stop_source}"

    if direction == "BULL":
        tgt_options: list[tuple[float, str]] = []
        if king and king > spot:
            tgt_options.append((king, "King (magnet)"))
        if ceiling and ceiling > spot and ceiling != king:
            tgt_options.append((ceiling, "Ceiling (breakout)"))
        if not tgt_options:
            tgt_options.append((spot * 1.02, "+2%"))
        stp_options: list[tuple[float, str]] = []
        # Floor stays as a structural option when within 5% of spot
        if floor_v and floor_v < spot and (spot - floor_v) / spot <= 0.05:
            stp_options.append((floor_v, "Floor break"))
        # Dynamic ATR-based stop replaces static -3% trail
        dyn_stop = spot * (1 - dyn_stop_pct / 100)
        stp_options.append((dyn_stop, dyn_stop_label))
        # Pick best RR pair
        best_rr, best = -1.0, None
        for tgt, tlbl in tgt_options:
            for stp, slbl in stp_options:
                risk = abs(spot - stp)
                if risk <= 0:
                    continue
                reward = abs(tgt - spot)
                rr = reward / risk
                if rr > best_rr:
                    best_rr, best = rr, (tgt, tlbl, stp, slbl)
        target, target_label, stop, stop_label = best
    else:
        # BEAR branch — symmetric smart RR cascade
        tgt_options: list[tuple[float, str]] = []
        if king and king < spot:
            tgt_options.append((king, "King (breakdown)"))
        if floor_v and floor_v < spot and floor_v != king:
            tgt_options.append((floor_v, "Floor (breakdown)"))
        if not tgt_options:
            tgt_options.append((spot * 0.98, "-2%"))
        stp_options: list[tuple[float, str]] = []
        if ceiling and ceiling > spot and (ceiling - spot) / spot <= 0.05:
            stp_options.append((ceiling, "Ceiling break"))
        # Dynamic ATR-based stop (above spot for shorts)
        dyn_stop = spot * (1 + dyn_stop_pct / 100)
        # Stop label flipped to + sign for bear-direction clarity
        stp_options.append((dyn_stop, dyn_stop_label.replace("-", "+", 1)))
        best_rr, best = -1.0, None
        for tgt, tlbl in tgt_options:
            for stp, slbl in stp_options:
                risk = abs(spot - stp)
                if risk <= 0:
                    continue
                reward = abs(tgt - spot)
                rr = reward / risk
                if rr > best_rr:
                    best_rr, best = rr, (tgt, tlbl, stp, slbl)
        target, target_label, stop, stop_label = best

    reward = abs(target - spot)
    risk = abs(stop - spot) or 1
    rr = reward / risk

    return {
        "strike": selected["strike"],
        "expiration": target_exp,
        "option_type": otype,
        "dte": target_dte,
        "target": target,
        "target_label": target_label,
        "stop": stop,
        "stop_label": stop_label,
        "rr_ratio": round(rr, 1),
        "delta": selected["delta"],
        "gamma": selected["gamma"],
        "theta": selected["theta"],
        "vega": selected["vega"],
        "mid_price": selected["mid"],
        "bid": selected["bid"],
        "ask": selected["ask"],
        "spread_pct": selected["spread_pct"],
        "contract_oi": selected["oi"],
        "contract_volume": selected["volume"],
    }


def _determine_direction(state: dict[str, Any]) -> str | None:
    """Determine trade direction from GEX structure.

    Patch A (2026-04-22) — three-layer cascade:

      1. **Momentum override** — if spot is ≥3% against the open, the
         day's action has decisively broken from structural GEX posture.
         Catches names like HIMS/FLY 2026-04-22 where Pos GEX dominated
         (would have said BULL) but stock dropped 4.5-4.7% intraday.
         In these cases, the magnet thesis is broken for this session —
         trade with the tape, not the structure. Tags
         `_direction_source = "momentum_override"`.

      2. **GEX dominance** — if Pos vs Neg GEX is lopsided by ≥1.5×,
         direction = sign of dominant side. Catches RTX/LMT/AAOI/ABT
         where king position (naive old rule) said BULL but net GEX
         was heavily Neg. Tags `gex_dominance_bear/bull`.

      3. **Signal label fallback** — legacy logic for balanced GEX.

      DANGER always returns None.

    Direction source is stashed on state via `_last_direction_source`
    so downstream gates (Rule #1 put block) can treat structural bears
    differently from speculative ones.
    """
    signal = state.get("signal", "")

    # Layer 1: Intraday momentum override (highest priority).
    # When price moves decisively vs today's open, the tape is telling
    # you something regardless of multi-day trend or GEX structure.
    # Runs BEFORE DANGER, BEFORE multi-day, BEFORE GEX dominance so the
    # "today is different" signal always wins. Threshold 2.5% catches
    # IBM (-2.7%) and harder movers. Higher = fewer false positives but
    # misses borderline cases.
    mom = state.get("_intraday_momentum") or {}
    vs_open = mom.get("vs_open_pct")
    MOM_OVERRIDE_PCT = 2.5
    if vs_open is not None and abs(vs_open) >= MOM_OVERRIDE_PCT:
        if vs_open <= -MOM_OVERRIDE_PCT:
            state["_last_direction_source"] = "momentum_override_bear"
            return "BEAR"
        if vs_open >= MOM_OVERRIDE_PCT:
            state["_last_direction_source"] = "momentum_override_bull"
            return "BULL"

    # Only skip DANGER when there's NO clear directional momentum to lean on
    if signal == "DANGER":
        state["_last_direction_source"] = "danger_skip"
        return None

    # Layer 1b: Multi-day fade / trend detector (Patch D).
    # For names with mild intraday action that aren't caught by Layer 1,
    # check if the multi-day trend is decisive. C 2026-04-22 was -0.2%
    # today but -3.8% over 2d from peak — multi-day fade is the story.
    # Conditions: 5d >= 3% + above MA20 + trend bullish (bull version);
    # 5d <= -3% + below MA20 + trend bearish (bear version). Simulation
    # validated: fires RTX/LMT/ABT as distribution bears while correctly
    # skipping C/AAOI/FLY (pullbacks in bull trends, still above MA20).
    rts = state.get("_rts") or {}
    _spot = state.get("actual_spot") or state.get("_spot") or 0
    _ret_5d = (rts.get("returns") or {}).get("5d")
    _ma20 = (rts.get("mas") or {}).get("ma20")
    _ts_details = rts.get("ts_details", [])
    if _ret_5d is not None and _ma20 and _spot:
        trend_bearish = any("Below" in d or "slope: -" in d for d in _ts_details)
        if _ret_5d <= -3.0 and _spot < _ma20 and trend_bearish:
            state["_last_direction_source"] = "multi_day_fade_bear"
            return "BEAR"
        trend_bullish = any("Above 3" in d or "slope: +" in d for d in _ts_details)
        if _ret_5d >= 3.0 and _spot > _ma20 and trend_bullish:
            state["_last_direction_source"] = "multi_day_trend_bull"
            return "BULL"

    pos_gex = state.get("pos_gex") or 0
    neg_gex = abs(state.get("neg_gex") or 0)  # stored negative; take magnitude
    DOMINANCE_RATIO = 1.5

    # Layer 2: GEX dominance cue
    if pos_gex > 0 and neg_gex > 0:
        if neg_gex >= pos_gex * DOMINANCE_RATIO:
            state["_last_direction_source"] = "gex_dominance_bear"
            return "BEAR"
        if pos_gex >= neg_gex * DOMINANCE_RATIO:
            state["_last_direction_source"] = "gex_dominance_bull"
            return "BULL"
        # Balanced — fall through to signal label

    # Layer 3: Legacy signal-label path (fallback)
    state["_last_direction_source"] = "signal_label"
    if signal in ("MAGNET UP", "SUPPORT", "PINNING"):
        return "BULL"
    if signal in ("AIR POCKET", "RESISTANCE"):
        return "BEAR"
    return None


# ── Intraday momentum verification gate ───────────────────────────────
# Added 2026-04-20 after AVGO false-positive case:
#   GEX "MAGNET UP" signal stayed bullish while AVGO price faded $406 → $397.
#   Two A-grade BUY CALLS alerts fired on a stock clearly rolling over.
# The gate checks recent price trajectory and blocks direction-mismatched
# signals. GEX tells us STRUCTURE; momentum tells us what ACTUALLY happened.

_momentum_cache: dict[str, tuple[float, dict | None]] = {}  # ticker → (ts, stats)
_MOMENTUM_CACHE_TTL_S = 60.0

# Thresholds calibrated against AVGO 2026-04-20 false positive:
#   AVGO opened $406.54, faded to $399 by 10:00, $397 by 12:35
#   Two A-grade BULL alerts fired at 10:28 and 12:35 — both wrong
#   15m lookback missed it (fade was OLDER than 15m). Using open + day-high.
_BULL_BLOCK_BELOW_DAY_HIGH_PCT = -1.5  # Block BULL if spot > 1.5% below day-high
_BULL_BLOCK_BELOW_OPEN_PCT = -0.5      # Block BULL if spot > 0.5% below open
_BEAR_BLOCK_ABOVE_DAY_LOW_PCT = 1.5    # Block BEAR if spot > 1.5% above day-low
_BEAR_BLOCK_ABOVE_OPEN_PCT = 0.5       # Block BEAR if spot > 0.5% above open


def _intraday_momentum_stats(ticker: str) -> dict | None:
    """Return today's intraday momentum picture: open, high, low, current, and
    derived percent changes. None if insufficient data.

    Structure:
      {
        "open": float,           # first snapshot of day (proxy for open)
        "high": float,           # intraday high so far
        "low": float,            # intraday low so far
        "current": float,        # latest snapshot
        "vs_open_pct": float,    # (current / open - 1) * 100
        "vs_high_pct": float,    # (current / high - 1) * 100 (always <= 0)
        "vs_low_pct": float,     # (current / low - 1) * 100  (always >= 0)
      }
    """
    import datetime as _dt
    now_ts = time.time()

    cached = _momentum_cache.get(ticker)
    if cached and (now_ts - cached[0]) < _MOMENTUM_CACHE_TTL_S:
        return cached[1]

    # Today's session window (08:00 local, generous pre-market coverage)
    today_start = _dt.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    today_start_ts = int(today_start.timestamp())

    result: dict | None = None
    try:
        con = sqlite3.connect("snapshots.db")
        row = con.execute(
            "SELECT MIN(spot) AS low, MAX(spot) AS high, "
            "(SELECT spot FROM snapshots WHERE ticker=? AND spot>0 AND ts>=? "
            "  ORDER BY ts ASC LIMIT 1) AS open_spot, "
            "(SELECT spot FROM snapshots WHERE ticker=? AND spot>0 "
            "  ORDER BY ts DESC LIMIT 1) AS current_spot "
            "FROM snapshots WHERE ticker=? AND spot>0 AND ts>=?",
            (ticker, today_start_ts, ticker, ticker, today_start_ts),
        ).fetchone()
        con.close()
        if row and row[0] and row[2] and row[3]:
            low, high, open_spot, current = row
            if open_spot > 0 and high > 0 and low > 0:
                result = {
                    "open": open_spot,
                    "high": high,
                    "low": low,
                    "current": current,
                    "vs_open_pct": (current / open_spot - 1.0) * 100,
                    "vs_high_pct": (current / high - 1.0) * 100,
                    "vs_low_pct": (current / low - 1.0) * 100,
                }
    except Exception:
        result = None

    _momentum_cache[ticker] = (now_ts, result)
    return result


def _momentum_gate_blocks(
    ticker: str, direction: str,
) -> tuple[bool, dict | None, str]:
    """Return (blocked, stats, reason_str).

    BULL is blocked when the stock is meaningfully fading intraday:
      - Current is >1.5% below today's high (clear rejection off highs), OR
      - Current is >0.5% below today's open (red day)

    BEAR is blocked when the stock is meaningfully rallying intraday:
      - Current is >1.5% above today's low, OR
      - Current is >0.5% above today's open

    None stats (insufficient data) never blocks — fail-open.
    """
    stats = _intraday_momentum_stats(ticker)
    if stats is None:
        return False, None, ""

    if direction == "BULL":
        if stats["vs_high_pct"] < _BULL_BLOCK_BELOW_DAY_HIGH_PCT:
            return True, stats, f"spot {stats['vs_high_pct']:+.2f}% vs day-high (>1.5% reject)"
        if stats["vs_open_pct"] < _BULL_BLOCK_BELOW_OPEN_PCT:
            return True, stats, f"spot {stats['vs_open_pct']:+.2f}% vs open (red day)"
    elif direction == "BEAR":
        if stats["vs_low_pct"] > _BEAR_BLOCK_ABOVE_DAY_LOW_PCT:
            return True, stats, f"spot {stats['vs_low_pct']:+.2f}% vs day-low (>1.5% bounced)"
        if stats["vs_open_pct"] > _BEAR_BLOCK_ABOVE_OPEN_PCT:
            return True, stats, f"spot {stats['vs_open_pct']:+.2f}% vs open (green day)"

    return False, stats, ""


def _determine_signal_type(state: dict[str, Any], direction: str) -> str:
    """Determine the signal type name based on GEX structure."""
    signal = state.get("signal", "")
    regime = state.get("regime", "")
    spot = state.get("actual_spot") or state.get("_spot") or 0
    king = state.get("king", 0)
    king_dist = abs(king - spot) / spot if spot else 0

    if signal == "PINNING":
        return "PINNING PREMIUM SELL"
    if signal == "MAGNET UP":
        if king_dist > 0.02:
            return "MAGNET BREAKOUT"
        return "POST BOTTOM LAUNCH"
    if signal == "SUPPORT":
        return "SUPPORT BOUNCE"
    if signal == "AIR POCKET":
        return "BREAKDOWN ACCELERATOR"
    if signal == "RESISTANCE":
        return "RESISTANCE FADE"
    return "DIRECTIONAL"


async def _fetch_earnings_blackout() -> set[str]:
    """Return tickers that have earnings within the next 7 days.

    These tickers are excluded from signal generation because IV crush
    and event-driven vol dynamics invalidate GEX-based structure signals.
    Previously this was only in the 5-factor playbook gate; now it's
    enforced at generation time per ChatGPT review recommendation.
    """
    import httpx
    from .config import get_settings

    s = get_settings()
    if not s.finnhub_api_key:
        return set()

    try:
        import datetime
        today = datetime.date.today()
        end = today + datetime.timedelta(days=7)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "token": s.finnhub_api_key,
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                },
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    ec.get("symbol", "")
                    for ec in data.get("earningsCalendar", [])
                    if ec.get("symbol")
                }
    except Exception:
        pass
    return set()


# Cache earnings blackout for 1 hour (avoid hammering Finnhub)
_earnings_blackout_cache: tuple[float, set[str]] = (0.0, set())


async def generate_signals(confluence: dict | None = None) -> list[dict[str, Any]]:
    """Scan all cached tickers and generate SOE signals."""
    import datetime

    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return []
    if is_market_holiday(now.date()):
        return []
    # Market hours only: 9:30 AM - 4:15 PM (indexes trade 15 min late; single
    # names are cut at 4:00 inside the per-ticker loop).
    mins = now.hour * 60 + now.minute
    if mins < 570 or mins > 975:  # before 9:30 or after 4:15
        return []

    # Earnings blackout: skip tickers with earnings within 7 days
    global _earnings_blackout_cache
    cache_ts, blackout_set = _earnings_blackout_cache
    if time.time() - cache_ts > 3600:
        blackout_set = await _fetch_earnings_blackout()
        _earnings_blackout_cache = (time.time(), blackout_set)

    snapshot = await cache.snapshot()
    new_signals: list[dict[str, Any]] = []

    # Regime flag for put-direction block (rule #1).
    # This week's cohort analysis: 10 put trades, 30% WR, -$1,376 in a bull
    # tape. SPY 20d > 0 → block BEAR-direction signals. Let the user wait
    # for regime flip or take puts manually with eyes open.
    _spy_state = snapshot.get("SPY", {})
    _spy_rts = _spy_state.get("_rts") or {}
    _spy_20d = _spy_rts.get("rs_20d", 0) if isinstance(_spy_rts, dict) else 0
    _block_puts = _spy_20d >= 0  # >=0 → bull/flat → block puts

    # Fetch breadth context (NYMO/NAMO) — cached 30 min
    breadth_data = None
    try:
        from .breadth import get_breadth_context
        breadth_data = await get_breadth_context()
    except Exception:
        pass

    # Compute IV distribution for relative ranking (replaces absolute thresholds)
    iv_universe: list[float] = []
    for _, st in snapshot.items():
        ticker_iv = st.get("iv", 0)
        if ticker_iv and ticker_iv > 0:
            iv_universe.append(ticker_iv)

    # Indexes keep signalling until 4:15 (15-min late-session); single
    # names stop at 4:00 sharp so stale-cache fires don't slip through.
    _INDEX_TICKERS = {"SPY", "QQQ", "IWM", "SPX", "NDX", "RUT", "DIA"}
    cutoff_mins = now.hour * 60 + now.minute

    for ticker, state in snapshot.items():
        # Patch C (2026-04-22) — big-mover escalation. When a stock gaps
        # ≥2.5% or has a >3% intraday range, it's likely trading on a
        # catalyst (earnings, macro, headline). These are the setups we
        # MOST want SOE to evaluate — but they also disproportionately
        # hit the earnings-blackout veto. Override: if |gap_pct| ≥ 2.5%
        # AND direction came from structural GEX dominance (not speculative
        # signal label), bypass both the EOD cutoff and blackout.
        gap_pct = abs(state.get("_gap_pct") or 0)
        is_big_mover = gap_pct >= 2.5

        if ticker not in _INDEX_TICKERS and cutoff_mins > 960:
            if not is_big_mover:
                continue
            # Big mover — evaluate even past normal cutoff

        # Earnings blackout: skip tickers with upcoming earnings (both books).
        # Big-mover override: if structural bear (pre-tested downstream),
        # we still let it through to log the decision via ab_decisions.
        if ticker in blackout_set and not is_big_mover:
            continue

        # Fetch Mir signal early — needed for both books
        mir_sig = await cache.get_mir_signal(ticker)

        direction = _determine_direction(state)
        # If no GEX direction but Mir exists, infer from Mir option_type
        if direction is None and mir_sig:
            ot = (mir_sig.get("option_type") or "").upper()
            direction = "BULL" if ot == "CALL" else "BEAR" if ot == "PUT" else None

        # ── Mir-originated pathway ──────────────────────────────────
        # When Mir momentum scoring (computed in worker) identifies a
        # high-conviction bullish setup, generate signal even without
        # GEX directional confirmation.  GEX becomes quality gate.
        is_mir_originated = False
        if (
            direction is None
            and mir_sig
            and mir_sig.get("signal_type") == "MIR_MOMENTUM"
            and mir_sig.get("mir_score", 0) >= 4.0
        ):
            direction = "BULL"
            is_mir_originated = True

        if direction is None:
            continue

        # Intraday momentum gate (added 2026-04-20 after AVGO false positive)
        # Don't fire BULL if stock is red or rejected off day-high by >1.5%.
        # Don't fire BEAR if stock is green or bounced off day-low by >1.5%.
        # Indexes excluded — they're benchmarks; we WANT signals on counter-moves.
        if ticker not in _INDEX_TICKERS:
            blocked, _stats, reason = _momentum_gate_blocks(ticker, direction)
            if blocked:
                print(
                    f"[SOE-MOMENTUM-BLOCK] {ticker} dir={direction} {reason}",
                    flush=True,
                )
                continue

        # Rule #1 — block puts in non-bear regime.
        # SPY/QQQ/IWM are the exception: index puts on a red day are a
        # valid hedge/scalp and their put trades last week were winners
        # (QQQ $645P, TSLA $380P in the simulator's block list). Single-
        # name puts in a bull tape are the bleed.
        #
        # Patch B (2026-04-22) — structural-bear override, gated.
        # When direction was chosen from GEX dominance (Neg GEX ≥ 1.5× Pos,
        # not from a near-king magnet label), the bear case is STRUCTURAL
        # not speculative. Today RTX/LMT/AAOI/ABT all dropped 3-5% and
        # Rule #1 would have blocked all of them. Override allows these
        # through IF enabled. Default OFF — we still log to ab_decisions
        # so we can measure the hit rate before flipping the flag live.
        import os as _os
        _STRUCTURAL_BEAR_LIVE = (
            _os.environ.get("SOE_STRUCTURAL_BEAR_ENABLED", "").lower() == "true"
        )
        direction_source = state.get("_last_direction_source", "")
        is_structural_bear = (
            direction == "BEAR"
            and direction_source in (
                "gex_dominance_bear", "momentum_override_bear",
                "multi_day_fade_bear",
            )
        )
        if (
            _block_puts
            and direction == "BEAR"
            and ticker not in ("SPY", "QQQ", "IWM", "SPX", "NDX", "RUT", "DIA")
            and not (is_structural_bear and _STRUCTURAL_BEAR_LIVE)
        ):
            # Still log the blocked decision via ab_decisions downstream
            # for hit-rate measurement, just don't fire Telegram/paper.
            if is_structural_bear:
                # Mark the state so downstream AB logger can tag "would-
                # have-fired structural bear". Doesn't change the continue.
                state["_rule1_would_have_fired"] = True
            continue

        # Trend day context (used by both pathways)
        trend_day = state.get("_trend_day") or {}
        trend_mode = trend_day.get("trend_mode", "NORMAL")
        gap_dir = trend_day.get("gap_direction", "")

        # Frozen spec v1.0: max 5 open positions for Mir signals
        if is_mir_originated:
            try:
                from .paper_trading import get_account_status
                acct = get_account_status()
                if acct.get("open_positions", 0) >= 5:
                    continue  # Max positions reached
            except Exception:
                pass

        # PM window gate for Mir-originated signals
        # Normal days: only 2:00-4:00 PM (backtest-validated window)
        # Trend days: allow from 10:00 AM (gap-and-go, no pullback)
        if is_mir_originated:
            mins = now.hour * 60 + now.minute

            if trend_mode in ("TREND_DAY", "EXTREME_TREND") and gap_dir == "UP":
                # Gap-and-go: allow from 10:00 AM onward
                if mins < 600:
                    continue
            else:
                # Normal mode: require PM window (2:00-4:00 PM)
                if mins < 840 or mins > 960:
                    continue

        # Dedup: only one signal per ticker per 2 hours (direction-independent)
        dedup_key = f"{ticker}:{now.strftime('%Y%m%d')}{now.hour // 2}"
        if dedup_key in _seen_signals:
            continue

        _is_debug = False  # Set True to trace mega-cap signal pipeline

        # Inject breadth context into state for scoring
        # Mir-originated trend-day signals: zero out breadth penalty entirely.
        # On gap-and-go days, NYMO overbought is expected and should not block.
        if breadth_data:
            if is_mir_originated and trend_mode in ("TREND_DAY", "EXTREME_TREND"):
                pass  # Skip breadth injection — don't penalize strong tape
            else:
                state["_breadth"] = breadth_data

        score, reasons = _compute_signal_score(state, direction, confluence, iv_universe)
        score_pre_convergence = score

        # Convergence DETECTION (Apr 27 v2 — was a +0.5 score bonus until
        # 4-LLM critique converged on "concentration risk, not confirmation").
        # We still detect when system signals agree, but no longer modify
        # the score. Surfaced as informational FLAG in Telegram + persisted
        # so the audit can backtest "convergence-flagged WR vs unflagged"
        # without contaminating the grade pipeline.
        conv_bonus, conv_reasons = _check_convergence_bonus(ticker, direction)
        convergence_detected = conv_bonus > 0  # any source fired = flag
        if convergence_detected:
            reasons.append(f"convergence FLAG (informational): {'; '.join(conv_reasons)}")
        # NOTE: conv_bonus is preserved in the sig dict for the Telegram
        # formatter (which still renders the convergence block) but is NOT
        # added to score. Set it to 0 to make this explicit downstream.
        conv_bonus = 0.0

        grade = _score_to_grade(score)
        signal_type = _determine_signal_type(state, direction)

        # ── Regime-context filter (Apr 24 2026) ──────────────────────────
        # Backtested across 30 days of resolved B+ and A signals.
        # Downgrades known losing (signal_type, regime, iv_band) combos so
        # they stop hitting Telegram while still persisting to DB/UI.
        # See _regime_context_filter docstring for combo table.
        iv_for_filter = state.get("iv") or (state.get("_rts") or {}).get("iv") or 0
        spy_5d = (confluence or {}).get("SPY", {}).get("_rts", {}).get("returns", {}).get("5d")
        orig_grade = grade
        grade = _regime_context_filter(signal_type, grade, spy_5d, iv_for_filter)
        if grade != orig_grade and _is_debug:
            print(f"[SOE_DBG] {ticker} regime filter: {orig_grade} -> {grade} "
                  f"(sig={signal_type}, spy_5d={spy_5d}, iv={iv_for_filter})")

        # ── Momentum confirmation gate (Apr 24 2026) ─────────────────────
        # Diagnostic: 66% of B+ losses faded in first hour post-fire. Winners
        # had +0.24% prior 15-min spot move; losers had +0.10% — winners
        # showed active momentum at fire time, losers were quietly setting up.
        # Gate forces B+ to require ≥0.3% spot move in last 15 min in signal
        # direction. Cuts coin-flip fires; keeps actively-momentum setups.
        # Projected lift: B+ win rate ~21% -> ~45%.
        if grade == "B+":
            mom_ok = _momentum_confirmation_check(ticker, direction)
            if not mom_ok:
                if _is_debug:
                    print(f"[SOE_DBG] {ticker} momentum gate failed -> downgrade B+ to C")
                grade = "C"  # no Telegram, persists to DB

        if _is_debug:
            print(f"[SOE_DBG] {ticker} dir={direction} score={score:.1f} grade={grade} type={signal_type}")

        # Mir-originated signals use narrower contract selection.
        # Pass ticker so dynamic ATR-based stops can query snapshot history.
        if is_mir_originated:
            signal_type = "MIR_MOMENTUM"
            contract = _select_contract(state, direction, mir_mode=True, ticker=ticker)
            # Fallback to standard selection if mir_mode is too restrictive
            if not contract:
                contract = _select_contract(state, direction, ticker=ticker)
        else:
            contract = _select_contract(state, direction, ticker=ticker)

        spot = state.get("actual_spot") or state.get("_spot") or 0

        # ── Track blocking reasons as flags (don't continue yet) ──
        a_blocked_by = None

        if is_mir_originated:
            # GEX as quality gate (not signal generator):
            # King above spot, floor below, positive gamma, king distance 0.5-3%
            # 2+ issues = block
            king = state.get("king", 0)
            floor_v = state.get("floor", 0)
            regime = state.get("regime", "")
            gex_issues: list[str] = []
            if king and spot and king < spot:
                gex_issues.append("king_below_spot")
            if regime == "NEG":
                gex_issues.append("neg_gamma")
            king_dist = abs(king - spot) / spot if spot and king else 0
            if king_dist < 0.005 or king_dist > 0.03:
                gex_issues.append(f"king_dist_{king_dist*100:.1f}pct")

            if len(gex_issues) >= 2:
                a_blocked_by = f"mir_gex_gate:{','.join(gex_issues)}"
            elif not contract:
                a_blocked_by = "no_contract"
            elif contract.get("rr_ratio", 0) < 1.0:
                a_blocked_by = "rr_ratio"

            # Add Mir + trend context to reasons
            mir_reasons = mir_sig.get("mir_reasons", [])
            for mr in mir_reasons:
                reasons.append(f"Mir: {mr}")
            trend_day = state.get("_trend_day") or {}
            if trend_day.get("trend_mode") != "NORMAL":
                reasons.append(
                    f"TREND DAY: {trend_day.get('gap_pct', 0):+.1f}% gap "
                    f"({trend_day.get('trend_mode')})"
                )

            # Reduce conviction for extreme gaps (chasing risk)
            if trend_day.get("trend_mode") == "EXTREME_TREND" and mir_sig:
                mir_sig = {**mir_sig, "conviction": "LOW"}
                reasons.append("EXTREME GAP — reduced conviction (chasing risk)")
        else:
            # Standard GEX pathway
            if score < 2.5:
                a_blocked_by = "score_threshold"
            elif not contract:
                a_blocked_by = "no_contract"
            elif contract.get("rr_ratio", 0) < 1.0:
                a_blocked_by = "rr_ratio"

        if _is_debug:
            if contract:
                print(f"[SOE_DBG] {ticker} contract: ${contract.get('strike')} {contract.get('expiration')} DTE={contract.get('dte')} R:R={contract.get('rr_ratio',0):.1f}")
            else:
                print(f"[SOE_DBG] {ticker} NO CONTRACT")
            print(f"[SOE_DBG] {ticker} blocked={a_blocked_by}")

        # 0DTE freshness gate
        dte = contract.get("dte", 99) if contract else 99
        # Compute CURRENT greeks age from timestamp, not cached snapshot age
        greeks_ts = state.get("_greeks_ts", 0)
        greeks_age = (time.time() - greeks_ts) if greeks_ts else 999
        dte_0_status = None
        if dte == 0 and not a_blocked_by:
            if ticker not in ("SPY", "QQQ"):
                a_blocked_by = "0dte_ticker"
            elif state.get("_greeks_source", "tradier") == "tradier":
                a_blocked_by = "0dte_tradier"
            else:
                quote_ts = state.get("_quote_ts", 0)
                quote_age = time.time() - quote_ts if quote_ts else 999
                if quote_age > 300:
                    a_blocked_by = "0dte_stale_quote"
                elif greeks_age > 300:
                    # Relaxed to 5 min (scan cycle is 2 min, SOE runs every 5 min)
                    # Was 60s which was structurally impossible to pass
                    a_blocked_by = "0dte_stale_greeks"
                elif state.get("_greeks_spot_stale"):
                    a_blocked_by = f"0dte_spot_divergence_{state.get('_greeks_spot_divergence', 0)}pct"
                else:
                    dte_0_status = "TRADEABLE" if greeks_age <= 60 and quote_age <= 180 else "EXPERIMENTAL"

        # ── Compute Book A (Mir+GEX) decision ──
        a_would_trade = 1 if not a_blocked_by else 0
        a_gate_label = None
        a_kelly_pct = 0

        if a_would_trade and contract:
            try:
                from .discipline import enrich_signal
                test_sig = {"ticker": ticker, "score": score, "grade": grade,
                            "dte": dte, "direction": "▲" if direction == "BULL" else "▼"}
                enriched = enrich_signal(test_sig, mir_signal=mir_sig)
                a_gate_label = enriched.get("gate_label")
                a_kelly_pct = enriched.get("kelly_size_pct", 0)
                if enriched.get("discipline_grade") in ("SKIP", "BLOCKED"):
                    a_blocked_by = f"discipline_{enriched.get('discipline_grade', '').lower()}"
                    a_would_trade = 0
            except Exception:
                pass

        # ── Compute Book B (Mir-only) decision ──
        try:
            from .discipline import compute_mir_only_decision
            b_decision = compute_mir_only_decision(
                ticker, direction, spot, contract, mir_sig,
                is_0dte=(dte == 0),
            )
        except Exception:
            b_decision = {"would_trade": 0, "blocked_by": "error", "target": None,
                          "stop": None, "rr_ratio": None, "kelly_pct": 0,
                          "gate_label": "INVALID", "gate_score": 0}

        # ── Compute GEX contribution flags ──
        gex_entry_blocked = 1 if a_blocked_by == "score_threshold" and b_decision["would_trade"] else 0
        gex_regime_blocked = 1 if a_blocked_by and "regime" in str(a_blocked_by) else 0
        a_target = contract["target"] if contract and a_would_trade else None
        b_target = b_decision["target"]
        gex_improved_target = 1 if (a_target and b_target and abs(a_target - b_target) > 0.01) else 0
        a_stop = contract["stop"] if contract and a_would_trade else None
        b_stop = b_decision["stop"]
        gex_improved_stop = 1 if (a_stop and b_stop and abs(a_stop - b_stop) > 0.01) else 0
        a_rr = contract["rr_ratio"] if contract and a_would_trade else None
        b_rr = b_decision["rr_ratio"]
        gex_rr_delta = round((a_rr or 0) - (b_rr or 0), 2) if a_rr and b_rr else 0

        # ── Insert AB decision (fire-and-forget, never blocks signal generation) ──
        try:
            _insert_ab_decision({
                "ts": int(time.time()), "ticker": ticker, "direction": direction,
                "mir_conviction": (mir_sig or {}).get("conviction"),
                "mir_signal_type": (mir_sig or {}).get("signal_type"),
                "mir_option_type": (mir_sig or {}).get("option_type"),
                "spot": spot,
                "strike": contract["strike"] if contract else None,
                "expiration": contract["expiration"] if contract else None,
                "option_type": contract["option_type"] if contract else None,
                "dte": dte if contract else None,
                "entry_price": contract.get("mid_price") or contract.get("ask") if contract else None,
                "delta": contract.get("delta") if contract else None,
                "a_would_trade": a_would_trade, "a_blocked_by": a_blocked_by,
                "a_score": round(score, 1), "a_grade": grade,
                "a_gate_label": a_gate_label,
                "a_target": a_target, "a_stop": a_stop,
                "a_rr_ratio": a_rr, "a_kelly_pct": a_kelly_pct,
                "a_regime": state.get("regime"),
                "a_king": state.get("king"), "a_floor": state.get("floor"),
                "a_ceiling": state.get("ceiling"),
                "b_would_trade": b_decision["would_trade"],
                "b_blocked_by": b_decision["blocked_by"],
                "b_target": b_target, "b_stop": b_stop,
                "b_rr_ratio": b_rr, "b_kelly_pct": b_decision["kelly_pct"],
                "b_gate_label": b_decision["gate_label"],
                "gex_entry_blocked": gex_entry_blocked,
                "gex_regime_blocked": gex_regime_blocked,
                "gex_improved_target": gex_improved_target,
                "gex_improved_stop": gex_improved_stop,
                "gex_rr_delta": gex_rr_delta,
            })
        except Exception:
            pass

        # ── Original behavior: only insert SOE signal if ALL GEX gates pass ──
        if a_blocked_by:
            continue

        sig = {
            "ticker": ticker,
            "direction": "▲" if direction == "BULL" else "▼",
            "signal_type": signal_type,
            "grade": grade,
            "score": round(score, 1),
            "max_score": 6,
            "strike": contract["strike"],
            "expiration": contract["expiration"],
            "option_type": contract["option_type"].upper(),
            "dte": contract["dte"],
            "target": contract["target"],
            "target_label": contract["target_label"],
            "stop": contract["stop"],
            "stop_label": contract["stop_label"],
            "rr_ratio": contract["rr_ratio"],
            "spot": spot,
            "king": state.get("king"),
            "floor_level": state.get("floor"),
            "ceiling_level": state.get("ceiling"),
            "zgl": state.get("zgl"),
            "regime": state.get("regime"),
            "iv": state.get("iv"),
            "delta": contract.get("delta"),
            "gamma": contract.get("gamma"),
            "bid": contract.get("bid"),
            "ask": contract.get("ask"),
            "mid_price": contract.get("mid_price"),
            "spread_pct": contract.get("spread_pct"),
            "contract_oi": contract.get("contract_oi"),
            "reasoning": "\n".join(f"✓ {r}" for r in reasons),
            "convergence_bonus": conv_bonus,
            "convergence_reasons": conv_reasons,
            "score_pre_convergence": round(score_pre_convergence, 1),
            # High-score fade flag — 4-LLM consensus (Apr 27): score ≥4.8
            # historically pins/reverses; auto-trade blocked, manual size
            # capped at 0.25× base.
            "is_high_score_fade": score >= SOE_HIGH_SCORE_FADE_THRESHOLD,
            "high_score_fade_size_mult": (
                SOE_HIGH_SCORE_FADE_SIZE_MULT
                if score >= SOE_HIGH_SCORE_FADE_THRESHOLD else 1.0
            ),
            **{
                f"macro_regime_{k}": v
                for k, v in _safe_macro_regime_full().items()
            },
            "status": "PENDING",
            "greeks_source": state.get("_greeks_source", "tradier"),
            "greeks_age_seconds": round(greeks_age, 1),
            "_0dte_status": dte_0_status,
        }

        # Enrich with discipline layer (sizing, tier, circuit breaker)
        try:
            from .discipline import enrich_signal
            sig = enrich_signal(sig, mir_signal=mir_sig)
        except Exception:
            pass

        # Insert into DB
        signal_id = _insert_signal(sig)
        _seen_signals.add(dedup_key)
        new_signals.append(sig)

        # Phase 1 #1 — Breadth-regime gate for new BULL entries.
        # All three LLMs (cross-LLM synthesis Apr 25) converged on:
        # promote macro/regime to a hard pre-filter, not a 5% scoring tweak.
        # Threshold: % of universe above 200d MA. <40% → no new longs;
        # 40-60% → A/A+ only.
        # Only applies to BULL direction (puts/BEAR signals are unaffected).
        regime_blocks_long = False
        regime_grade_blocks = False
        _regime_label = "UNKNOWN"
        try:
            from .regime_breadth import get_breadth_regime
            _regime = get_breadth_regime()
            _regime_label = _regime.get("regime", "FULL_BULL")
            if direction == "BULL":
                if _regime_label == "BEAR":
                    regime_blocks_long = True
                elif _regime_label == "TRANSITIONAL" and grade in ("B", "B+"):
                    regime_grade_blocks = True
        except Exception as e:
            # Fail-open: if breadth lookup errors, don't block legitimate signals.
            # The breadth gate is a safety net, not a load-bearing rail.
            print(f"[SOE] regime_breadth check failed (fail-open): {e}")

        # Phase 2 #2 — IV-rank regime gate (per iv_rank_factor_verdict.md).
        # Block HIGH-IV BULL entries during BEAR/TRANSITIONAL regime; in those
        # regimes HIGH-IV positions historically had 33% hit rate / -7.31% avg
        # at 21d (n=120). FULL_BULL regime has only +7pp delta, so gate inactive.
        # Biotech tickers excluded (reverse pattern in T1 per-ticker analysis).
        iv_blocks_long = False
        _iv_gate_reason = "n/a"
        try:
            if direction == "BULL" and _regime_label in ("BEAR", "TRANSITIONAL"):
                from .iv_rank_cache import gate_iv_for_regime
                _iv_gate = gate_iv_for_regime(ticker, _regime_label)
                _iv_gate_reason = _iv_gate.get("reason", "")
                if _iv_gate.get("blocked"):
                    iv_blocks_long = True
        except Exception as e:
            print(f"[SOE] iv_rank gate check failed (fail-open): {e}")

        # Phase 6 — A-grade STRUCTURAL SAFETY GUARD (Apr 27 grade audit).
        # Empirical decomposition (n=810 A+B+ signals): A grade catastrophically
        # fails when fired in EXTENDED conditions because the "all walls align"
        # bonus pushes B+ → A precisely at LOCAL TOPS.
        #
        # Failure modes (each independently catastrophic for A grade):
        #   IV > 45:                A 23-27% hit vs B+ 53-57%
        #   Spot 15-30% above ZGL:  A 8% hit    vs B+ 48% ← worst dead zone
        #   R:R > 2.5:              A 34% hit   vs B+ 68%
        #
        # Mechanism: high-IV + extended-spot + far-target = paying up for
        # premium that will crush, no mean-reversion attractor pull,
        # chasing extension. Classic late-cycle pin-and-reverse setup.
        # Block A auto-trade if 2+ risk factors fire (allow 1 — those still
        # average 50%+ hit rate; 2+ drops to <30%).
        is_broken_a_combo = False
        risk_factors_fired = []
        if grade in ("A+", "A"):
            sig_iv = sig.get("iv") or 0
            sig_spot = sig.get("spot") or 0
            sig_zgl = sig.get("zgl") or 0
            sig_rr = sig.get("rr_ratio") or 0
            spot_to_zgl_pct = ((sig_spot - sig_zgl) / sig_spot * 100
                                if sig_spot > 0 else 0)
            if sig_iv > 45:
                risk_factors_fired.append(f"IV>{45} ({sig_iv:.0f})")
            if 15 <= spot_to_zgl_pct <= 30:
                risk_factors_fired.append(
                    f"spot in dead zone 15-30% above ZGL ({spot_to_zgl_pct:.0f}%)"
                )
            if sig_rr > 2.5:
                risk_factors_fired.append(f"R:R>{2.5} ({sig_rr:.1f})")
            is_broken_a_combo = len(risk_factors_fired) >= 2
            # Persist on sig for downstream consumers (Telegram boost block
            # needs to display these alongside the override factors).
            sig["risk_factors_fired"] = risk_factors_fired

        # Auto-open paper position:
        #   - MIR_MOMENTUM: always (frozen spec v1.0)
        #   - GEX pathway A grade: auto-open EXCEPT broken signal_types
        #   - GEX pathway B+ with 0DTE/1DTE SPY/QQQ: auto-open (scalp validation)
        should_auto_trade = False
        if is_mir_originated:
            should_auto_trade = True
        elif grade in ("A+", "A") and not is_broken_a_combo:
            should_auto_trade = True
        elif grade == "B+" and ticker in ("SPY", "QQQ") and dte <= 1:
            should_auto_trade = True

        if is_broken_a_combo:
            sig["_broken_a_blocked"] = True
            sig["_broken_a_factors"] = list(risk_factors_fired)
            print(f"[SOE] A-grade STRUCTURAL block: {ticker} {sig.get('signal_type')} "
                  f"— {len(risk_factors_fired)} risk factors fired: "
                  f"{'; '.join(risk_factors_fired)}; signal logged but NOT auto-traded")

        # High-score fade gate (Apr 27 — 4-LLM consensus on inverse score
        # finding). Phase 6 audit: 5.0+ = 20% 1d hit, 3.75-4.1 = 67% 1d.
        # Block auto-trade for score >= 4.8 regardless of grade. Manual
        # take is up to user but Telegram footer recommends 0.25× size.
        if sig["is_high_score_fade"] and should_auto_trade:
            should_auto_trade = False
            sig["_high_score_fade_blocked"] = True
            print(f"[SOE] HIGH-SCORE FADE block: {ticker} {sig.get('signal_type')} "
                  f"score={score:.1f} >= {SOE_HIGH_SCORE_FADE_THRESHOLD} "
                  f"(historical: 5.0+ = 20% 1d hit). Auto-trade BLOCKED. "
                  f"Manual size capped at {SOE_HIGH_SCORE_FADE_SIZE_MULT}x.")

        # Apply breadth gate to auto-trade decision.
        if (regime_blocks_long or regime_grade_blocks) and should_auto_trade:
            should_auto_trade = False
            sig["_breadth_blocked"] = True
            print(f"[SOE] Breadth gate blocked auto-open for {ticker} "
                  f"({_regime_label}, {grade}, %above200d="
                  f"{_regime.get('pct_above_200d', '?')}%)")

        # Apply IV-rank gate to auto-trade decision (Phase 2).
        if iv_blocks_long and should_auto_trade:
            should_auto_trade = False
            sig["_iv_rank_blocked"] = True
            print(f"[SOE] IV-rank gate blocked auto-open for {ticker}: "
                  f"{_iv_gate_reason}")

        if should_auto_trade and signal_id:
            try:
                from .paper_trading import open_position
                paper_result = open_position(signal_id)
                if paper_result.get("error"):
                    print(f"[SOE] Paper auto-open failed for {ticker}: {paper_result['error']}")
                else:
                    pathway = "MIR" if is_mir_originated else f"GEX {grade}"
                    print(f"[SOE] Paper auto-opened ({pathway}): {ticker} x{paper_result.get('contracts', '?')} "
                          f"@ ask ${contract.get('ask', '?')} (mid ${contract.get('mid_price', '?')})")
            except Exception as e:
                print(f"[SOE] Paper auto-open error: {e}")

        # Telegram push: A/A+ always EXCEPT broken signal_types,
        # B+ only if solid (flow or volume quality).
        #
        # 2026-06-02 PM: Added conviction_booster override path. Audit
        # found 4 A signals today (CRDO/HOOD/HIMS/SHOP) silently blocked
        # by is_broken_a_combo despite perfect multi-factor conviction
        # (daily EMA stack, sector strength, multi-day SOE repeat,
        # pre-fire INFORMED FLOW). Estimated suppression cost: ~$9.1K
        # realized P/L on 6/2 alone. Override fires when conviction
        # score >= 70 — telegram dispatch only, auto-trade gates still
        # respect is_broken_a_combo.
        should_push = False
        if sig.get("grade") in ("A+", "A") and not is_broken_a_combo:
            should_push = True
        elif sig.get("grade") in ("A+", "A") and is_broken_a_combo:
            # Try conviction booster override
            try:
                from .conviction_booster import (
                    compute_conviction_boost,
                    CONVICTION_OVERRIDE_THRESHOLD,
                )
                boost_score, boost_factors = await compute_conviction_boost(
                    ticker, sig
                )
                sig["_boost_score"] = boost_score
                sig["_boost_factors"] = boost_factors
                if boost_score >= CONVICTION_OVERRIDE_THRESHOLD:
                    sig["_broken_a_overridden"] = True
                    should_push = True
                    print(
                        f"[CONVICTION] {ticker} {sig.get('grade')} "
                        f"{sig.get('signal_type','')} OVERRIDE: "
                        f"score={boost_score} factors={len(boost_factors)}",
                        flush=True,
                    )
                else:
                    print(
                        f"[CONVICTION] {ticker} {sig.get('grade')} "
                        f"{sig.get('signal_type','')} "
                        f"boost={boost_score} < {CONVICTION_OVERRIDE_THRESHOLD} "
                        f"— stays blocked",
                        flush=True,
                    )
            except Exception as e:
                print(
                    f"[CONVICTION] {ticker} boost failed (fail-closed): {e!r}",
                    flush=True,
                )
        elif sig.get("grade") == "B+" and contract:
            # B+ needs quality confirmation: tight spread + decent OI + good R:R
            spread_ok = contract.get("spread_pct", 99) < 5
            oi_ok = contract.get("contract_oi", 0) >= 1000
            rr_ok = contract.get("rr_ratio", 0) >= 1.5
            mir_ok = (mir_sig or {}).get("conviction", "").upper() in ("HIGH", "MEDIUM")
            if (spread_ok and oi_ok and rr_ok) or mir_ok:
                should_push = True

        # Apply breadth + IV-rank gates to Telegram push as well.
        if regime_blocks_long or regime_grade_blocks or iv_blocks_long:
            should_push = False

        # Mute HIGH-SCORE FADE WATCH from Telegram (added 2026-05-20).
        # Backtest of 5/19 alerts showed 2/2 FADE WATCH alerts (GOOGL A+
        # @5.6, V A @5.1) went against their direction — system was right
        # to auto-block trading. Since they're already auto-blocked, the
        # Telegram message just adds noise. They still persist to DB +
        # render in UI for the audit trail.
        if sig.get("is_high_score_fade"):
            should_push = False

        # ER-in-window gate for long-premium multi-day alerts (2026-05-20
        # — Perplexity recommendation #2). Block SOE long-call/long-put
        # alerts when ER falls inside the contract window AND DTE >= 2.
        # 0DTE/1DTE on ER day is a different setup (vol play, not held
        # through crush) — not gated. Alert STILL persisted + shown in
        # UI; just muted from Telegram.
        try:
            from .earnings_calendar import er_blocks_long_premium
            _dte = sig.get("dte")
            if _dte is not None and _dte >= 2:
                blocked, reason = er_blocks_long_premium(ticker, _dte)
                if blocked:
                    should_push = False
                    sig["_er_blocked_reason"] = reason
        except Exception:
            pass

        # SOE_A demote to UI-only (#121, cross-LLM audit follow-through). The 6/23
        # realized-option-P&L analysis found grade-A SOE is directionally WEAK
        # (37.7% spot EOD WR over 25 days, n=783); no exit policy flips it positive,
        # and the 57.6% option touch-green WR was a convexity artifact. Demoted like
        # WHALE #94 — still persisted + shown in UI, just muted from Telegram. A+
        # is NOT affected. SINGLE-REGIME bull caveat → reversible: env SOE_A_TELEGRAM=1.
        try:
            from .telegram import soe_a_demoted
            if soe_a_demoted(sig.get("grade")):
                should_push = False
                sig["_soe_a_demoted"] = True
        except Exception:
            pass

        if should_push and not sig.get("_suppress_telegram"):
            try:
                from .telegram import send, format_soe_signal
                # Re-stamp spot at dispatch time (2026-05-27 v1; 2026-05-28 v2).
                # The signal was evaluated when the snapshot was taken at
                # the top of the cycle; with a 60s eval cadence the snapshot
                # can be 30-90s old by the time we send. Pull a fresh spot
                # so the trader's `Entry:` field matches the chart.
                #
                # 2026-05-28 v2 (USAR 12:01 bug):
                #   USAR (TIER_3) snapshot at 11:49:43 was the only cache
                #   data when SOE evaluated at 12:01:16 — a 12-min stale
                #   window. The v1 cache-only re-stamp returned the same
                #   stale price because the CACHE itself was stale (not
                #   just the eval-time snapshot).
                #
                #   v2 fix: if cache _updated_ts is >180s old, force a
                #   live 1-ticker Tradier quote at dispatch. Costs ~100ms
                #   per signal that needs refetch — acceptable for SOE A/A+
                #   conviction tier. Falls back to cache value if Tradier
                #   call fails or times out.
                #
                # Original eval-time spot stays in sig["spot_at_eval"] for
                # the alert_outcomes DB log so outcome attribution uses
                # the canonical fire-time state.
                _eval_spot = sig.get("spot")
                _fresh_state = None
                _dispatch_spot = None
                try:
                    _fresh_state = await cache.get(ticker)
                    if _fresh_state:
                        _cache_spot = (
                            _fresh_state.get("actual_spot")
                            or _fresh_state.get("_spot")
                        )
                        _updated_ts = _fresh_state.get("_updated_ts") or 0
                        _cache_age = (
                            time.time() - _updated_ts if _updated_ts else 9999
                        )
                        if _cache_spot and _cache_spot > 0 and _cache_age < 180:
                            # Cache fresh enough — use it
                            _dispatch_spot = _cache_spot
                        else:
                            # Cache stale (>180s) — force live Tradier refetch
                            try:
                                from .tradier import TradierClient
                                _cli = TradierClient()
                                _live_qs = await _cli.quotes([ticker])
                                _live_spot = (
                                    _live_qs.get(ticker)
                                    if isinstance(_live_qs, dict)
                                    else None
                                )
                                if _live_spot and _live_spot > 0:
                                    _dispatch_spot = _live_spot
                                    print(
                                        f"[SOE] live-refetch {ticker}: cache "
                                        f"{_cache_age:.0f}s stale, "
                                        f"eval=${_eval_spot:.2f} → "
                                        f"live=${_live_spot:.2f}",
                                        flush=True,
                                    )
                                elif _cache_spot and _cache_spot > 0:
                                    # Tradier returned nothing, fall back
                                    _dispatch_spot = _cache_spot
                            except Exception as _le:
                                print(
                                    f"[SOE] live-refetch {ticker} failed: "
                                    f"{_le!r}, falling back to cache",
                                    flush=True,
                                )
                                if _cache_spot and _cache_spot > 0:
                                    _dispatch_spot = _cache_spot
                    if _dispatch_spot and _dispatch_spot > 0:
                        sig["spot_at_eval"] = _eval_spot
                        sig["spot"] = _dispatch_spot
                except Exception:
                    pass

                # STALE-SPOT SUPPRESSION (2026-05-28 PM open bug).
                # Pre-market NBIS cached at $208.37 fired SOE at 09:31:26 with
                # the stale price after a significant gap-up open. Same story
                # on ~10 other names (ONDS/HIMS/TEAM/SWKS/NXPI/WULF/CIFR).
                # Root cause: worker hasn't completed first post-open scan
                # (still on cycle 50/459) so cache holds pre-market values
                # for TIER_2/3 names. SOE eval runs every 60s and burst-fires
                # alerts against the stale cache.
                #
                # Gate: suppress when snapshot is >120s old AND it's the first
                # 10 min of the trading day. Outside the first 10 min, allow
                # the alert (gaps mid-session are rare and the trader can see
                # current price on the chart).
                try:
                    import datetime as _dt
                    _now_dt = _dt.datetime.now()
                    _et_min = _now_dt.hour * 60 + _now_dt.minute
                    _is_first_10min = 570 <= _et_min <= 580  # 9:30 - 9:40 ET
                    if _is_first_10min and _fresh_state:
                        _snap_ts = (
                            _fresh_state.get("_updated_ts")
                            or _fresh_state.get("_snap_ts")
                            or _fresh_state.get("snap_ts")
                            or _fresh_state.get("_ts")
                            or 0
                        )
                        # Only suppress when we can MEASURE staleness AND
                        # it's clearly stale. Fail-open if no timestamp.
                        if _snap_ts:
                            _staleness = time.time() - _snap_ts
                            if _staleness > 120:
                                print(
                                    f"[SOE] suppress stale-spot fire: {ticker} "
                                    f"snapshot {_staleness:.0f}s old at open",
                                    flush=True,
                                )
                                continue
                except Exception:
                    pass
                # SOE A/A+ are the highest-conviction signals the engine
                # produces. Use force=True for A+ to bypass ALL rate
                # limits AND ticker cooldown — these can't be drowned by
                # basket/flow/spike alerts firing on the same ticker.
                # A grade uses force=True too because per-ticker cooldown
                # (1 hour) was silently swallowing every A signal today
                # whenever any other detector fired on the same ticker
                # first (Bug #11 fix, 2026-05-13).
                _grade = sig.get("grade", "")
                _tg_ok = await send(
                    format_soe_signal(sig),
                    ticker=ticker,
                    priority=(_grade == "A+"),
                    force=(_grade in ("A", "A+")),
                )
                # Stamp dispatch on the row so Mir TP query can filter to
                # signals actually sent (2026-06-02 PM — Mir TP was showing
                # broken-A signals that never reached Telegram as "open
                # winners"). Best-effort; failure here doesn't gate the
                # alert.
                try:
                    if _tg_ok and sig.get("id"):
                        import sqlite3 as _sql3
                        _c = _sql3.connect("snapshots.db", timeout=3)
                        _c.execute(
                            "UPDATE soe_signals SET telegram_sent = 1 "
                            "WHERE id = ?",
                            (sig["id"],),
                        )
                        _c.commit()
                        _c.close()
                except Exception as _stamp_err:
                    print(f"[SOE] tg-sent stamp failed: {_stamp_err!r}", flush=True)
                # Performance database log (2026-05-20). Logs even if
                # suppressed; future analysis needs to know what would-have-
                # fired vs what did. Set _suppress_telegram for the UI-only
                # FADE WATCH path.
                try:
                    from .alert_outcomes import log_alert
                    log_alert(
                        alert_type=f"SOE_{_grade.replace('+','P')}",
                        ticker=ticker,
                        fired_at=time.time(),
                        direction="BULL" if sig.get("direction") in ("▲","BULL") else "BEAR",
                        grade=_grade,
                        score=sig.get("score"),
                        strike=sig.get("strike"),
                        expiration=sig.get("expiration"),
                        option_type=sig.get("option_type", "").lower(),
                        dte=sig.get("dte"),
                        # Prefer eval-time spot if we re-stamped at dispatch
                        # (2026-05-27 lag fix). spot_at_eval is the canonical
                        # fire-time state used for outcome attribution; sig["spot"]
                        # is now the dispatch-time refresh shown to the trader.
                        spot_at_alert=sig.get("spot_at_eval") or sig.get("spot"),
                        entry_price=sig.get("mid_price"),
                        target_spot=sig.get("target"),
                        stop_spot=sig.get("stop"),
                        gex_regime=sig.get("regime"),
                        king=sig.get("king"),
                        floor=sig.get("floor_level"),
                        ceiling=sig.get("ceiling_level"),
                        ivr_at_alert=sig.get("iv_rank") or sig.get("ivp"),
                        raw_alert=sig,
                    )
                except Exception as e:
                    print(f"[alert_outcomes] SOE log failed: {e}")
            except Exception:
                pass

    return new_signals


def _insert_signal(sig: dict[str, Any]) -> int | None:
    """Insert signal into DB. Returns the signal ID for paper trading."""
    with _conn() as c:
        c.execute(
            """INSERT INTO soe_signals
            (ts, ticker, direction, signal_type, grade, score, max_score,
             strike, expiration, option_type, target, target_label, stop, stop_label,
             rr_ratio, spot, king, floor_level, ceiling_level, zgl, regime, iv,
             delta, gamma, reasoning, status,
             entry_price, mid_price, bid, ask,
             macro_regime_tag, macro_regime_factors)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()),
                sig["ticker"], sig["direction"], sig["signal_type"],
                sig["grade"], sig["score"], sig["max_score"],
                sig["strike"], sig["expiration"], sig["option_type"],
                sig["target"], sig["target_label"], sig["stop"], sig["stop_label"],
                sig["rr_ratio"], sig["spot"], sig["king"],
                sig["floor_level"], sig["ceiling_level"], sig["zgl"],
                sig["regime"], sig["iv"], sig["delta"], sig["gamma"],
                sig["reasoning"], sig["status"],
                sig.get("ask"),  # entry_price = ask (Grok rule: fill at offer)
                sig.get("mid_price"),
                sig.get("bid"),
                sig.get("ask"),
                sig.get("macro_regime_tag", "NONE"),
                sig.get("macro_regime_factors_json"),
            ),
        )
        row = c.execute("SELECT last_insert_rowid()").fetchone()
        return row[0] if row else None


def _insert_ab_decision(d: dict[str, Any]) -> None:
    cols = list(d.keys())
    placeholders = ",".join("?" for _ in cols)
    col_str = ",".join(cols)
    with _conn() as c:
        c.execute(f"INSERT INTO ab_decisions ({col_str}) VALUES ({placeholders})", tuple(d.values()))


async def check_ab_outcomes() -> None:
    """Check pending AB decisions and update outcomes + MAE/MFE."""
    snapshot = await cache.snapshot()

    with _conn() as c:
        pending = c.execute(
            "SELECT * FROM ab_decisions WHERE status = 'PENDING' ORDER BY ts DESC LIMIT 500"
        ).fetchall()

        for row in pending:
            d = dict(row)
            ticker = d["ticker"]
            state = snapshot.get(ticker)
            if not state:
                continue
            spot = state.get("actual_spot") or state.get("_spot") or 0
            if not spot:
                continue

            is_bull = d["direction"] == "BULL"
            entry_spot = d["spot"] or spot

            # Update MAE/MFE tracking (min/max spot seen)
            a_min = min(d.get("a_min_spot") or spot, spot)
            a_max = max(d.get("a_max_spot") or spot, spot)

            updates = {"a_min_spot": a_min, "a_max_spot": a_max,
                       "b_min_spot": a_min, "b_max_spot": a_max}

            # Check Book A outcome
            if d["a_outcome"] == "PENDING" and d["a_would_trade"]:
                a_target = d["a_target"]
                a_stop = d["a_stop"]
                if a_target and a_stop:
                    if is_bull and spot >= a_target:
                        updates["a_outcome"] = "WIN"
                        updates["a_pnl_pct"] = round((spot - entry_spot) / entry_spot * 100, 2)
                    elif not is_bull and spot <= a_target:
                        updates["a_outcome"] = "WIN"
                        updates["a_pnl_pct"] = round((entry_spot - spot) / entry_spot * 100, 2)
                    elif is_bull and spot <= a_stop:
                        updates["a_outcome"] = "LOSS"
                        updates["a_pnl_pct"] = round((spot - entry_spot) / entry_spot * 100, 2)
                    elif not is_bull and spot >= a_stop:
                        updates["a_outcome"] = "LOSS"
                        updates["a_pnl_pct"] = round((entry_spot - spot) / entry_spot * -100, 2)
            elif d["a_would_trade"] == 0 and d["a_outcome"] == "PENDING":
                updates["a_outcome"] = "BLOCKED"

            # Check Book B outcome
            if d["b_outcome"] == "PENDING" and d["b_would_trade"]:
                b_target = d["b_target"]
                b_stop = d["b_stop"]
                if b_target and b_stop:
                    if is_bull and spot >= b_target:
                        updates["b_outcome"] = "WIN"
                        updates["b_pnl_pct"] = round((spot - entry_spot) / entry_spot * 100, 2)
                    elif not is_bull and spot <= b_target:
                        updates["b_outcome"] = "WIN"
                        updates["b_pnl_pct"] = round((entry_spot - spot) / entry_spot * 100, 2)
                    elif is_bull and spot <= b_stop:
                        updates["b_outcome"] = "LOSS"
                        updates["b_pnl_pct"] = round((spot - entry_spot) / entry_spot * 100, 2)
                    elif not is_bull and spot >= b_stop:
                        updates["b_outcome"] = "LOSS"
                        updates["b_pnl_pct"] = round((entry_spot - spot) / entry_spot * -100, 2)
            elif d["b_would_trade"] == 0 and d["b_outcome"] == "PENDING":
                updates["b_outcome"] = "BLOCKED"

            # Check expiration
            if d.get("expiration"):
                import datetime
                try:
                    exp = datetime.date.fromisoformat(d["expiration"])
                    if datetime.date.today() > exp:
                        if updates.get("a_outcome", d["a_outcome"]) == "PENDING":
                            updates["a_outcome"] = "EXPIRED"
                        if updates.get("b_outcome", d["b_outcome"]) == "PENDING":
                            updates["b_outcome"] = "EXPIRED"
                except ValueError:
                    pass

            # Determine overall status
            a_out = updates.get("a_outcome", d["a_outcome"])
            b_out = updates.get("b_outcome", d["b_outcome"])
            if a_out != "PENDING" and b_out != "PENDING":
                updates["status"] = f"{a_out}_{b_out}"
                updates["outcome_spot"] = spot
                updates["outcome_ts"] = int(time.time())

            # Batch update
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            c.execute(
                f"UPDATE ab_decisions SET {set_clause} WHERE id = ?",
                (*updates.values(), d["id"]),
            )


async def check_signal_outcomes() -> None:
    """Check pending signals and update outcomes."""
    snapshot = await cache.snapshot()

    with _conn() as c:
        pending = c.execute(
            "SELECT * FROM soe_signals WHERE status = 'PENDING' ORDER BY ts DESC"
        ).fetchall()

        for row in pending:
            sig = dict(row)
            ticker = sig["ticker"]
            state = snapshot.get(ticker)
            if not state:
                continue

            spot = state.get("actual_spot") or state.get("_spot") or 0
            if not spot:
                continue

            target = sig["target"]
            stop = sig["stop"]
            is_bull = sig["direction"] == "▲"

            # Check if target hit
            if is_bull and spot >= target:
                c.execute(
                    "UPDATE soe_signals SET status = 'WIN', outcome_price = ?, outcome_ts = ? WHERE id = ?",
                    (spot, int(time.time()), sig["id"]),
                )
            elif not is_bull and spot <= target:
                c.execute(
                    "UPDATE soe_signals SET status = 'WIN', outcome_price = ?, outcome_ts = ? WHERE id = ?",
                    (spot, int(time.time()), sig["id"]),
                )
            # Check if stop hit
            elif is_bull and spot <= stop:
                c.execute(
                    "UPDATE soe_signals SET status = 'LOSS', outcome_price = ?, outcome_ts = ? WHERE id = ?",
                    (spot, int(time.time()), sig["id"]),
                )
            elif not is_bull and spot >= stop:
                c.execute(
                    "UPDATE soe_signals SET status = 'LOSS', outcome_price = ?, outcome_ts = ? WHERE id = ?",
                    (spot, int(time.time()), sig["id"]),
                )
            # Check expiration
            else:
                import datetime
                try:
                    exp_date = datetime.date.fromisoformat(sig["expiration"])
                    if datetime.date.today() > exp_date:
                        c.execute(
                            "UPDATE soe_signals SET status = 'EXPIRED', outcome_price = ?, outcome_ts = ? WHERE id = ?",
                            (spot, int(time.time()), sig["id"]),
                        )
                except ValueError:
                    pass


# ── Setup Forming Scanner (Mir-style proactive ideas) ────────────────
#
# Scans the universe for tickers hitting multiple Mir criteria:
# high RTS + leading industry + GEX structure + EMA alignment
# Pushes "SETUP FORMING" alerts to Telegram — ideas BEFORE Mir calls them.

# Persistent cooldown file — survives uvicorn --reload / restart cycles.
# Previously in-memory only, which caused duplicate fires whenever we
# deployed a fix mid-session (e.g., 2026-04-23: NVDA + GOOGL fired 3:36
# then again 3:43 because a commit in between reloaded the module).
import json as _json
import os as _os
_SETUP_SEEN_PATH = _os.environ.get("SETUP_SEEN_PATH", "./setup_cooldown.json")
_setup_seen: dict[str, float] = {}
_setup_seen_loaded = False

def _load_setup_seen() -> None:
    global _setup_seen, _setup_seen_loaded
    if _setup_seen_loaded:
        return
    try:
        if _os.path.exists(_SETUP_SEEN_PATH):
            with open(_SETUP_SEEN_PATH) as f:
                _setup_seen = _json.load(f)
    except Exception:
        _setup_seen = {}
    _setup_seen_loaded = True

def _save_setup_seen() -> None:
    try:
        with open(_SETUP_SEEN_PATH, "w") as f:
            _json.dump(_setup_seen, f)
    except Exception:
        pass

async def scan_setups() -> list[dict[str, Any]]:
    """Scan for Mir-style setups forming across the universe.

    Based on backtest findings (Apr 2026):
    - Sector leaders with EMA/RS/SMA alignment
    - 7-14 DTE sweet spot
    - PM window (2:00-4:00) for entry timing
    - Skip Mondays, skip bear regime (SPY 20d < 0)
    - GEX king/floor as entry/target/stop
    """
    import datetime

    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return []
    if is_market_holiday(now.date()):
        return []
    # Market hours only: 9:30 AM - 4:00 PM (pre-market spot is stale, post-close fires stale)
    mins = now.hour * 60 + now.minute
    if mins < 570 or mins > 960:
        return []
    # Skip Mondays (backtest: worse performance)
    is_monday = now.weekday() == 0

    snapshot = await cache.snapshot()
    if len(snapshot) < 10:
        return []

    # Bear regime filter: skip when SPY trending down
    spy_state = snapshot.get("SPY", {})
    spy_rts = spy_state.get("_rts") or {}
    spy_20d_ret = spy_rts.get("rs_20d", 0) if isinstance(spy_rts, dict) else 0
    if spy_20d_ret < -2:  # SPY down >2% over 20d = bear regime
        return []

    # PM window bonus (2:00-4:00 is optimal entry per backtest)
    is_pm = 14 <= now.hour < 16
    is_power_hour = now.hour == 15

    setups: list[dict[str, Any]] = []
    now_ts = time.time()
    # Hydrate cooldown state from disk (once per process)
    _load_setup_seen()

    for ticker, state in snapshot.items():
        # Skip indexes — this is for single-stock sector leaders
        if ticker in ("SPY", "QQQ", "IWM", "DIA", "SPX", "NDX", "RUT", "VIX"):
            continue

        # 4-hour cooldown per ticker (persistent across restarts)
        if now_ts - _setup_seen.get(ticker, 0) < 14400:
            continue

        spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot or spot < 5:
            continue

        score = 0
        reasons = []

        # 1. GEX structure: POS regime + king above as magnet
        regime = state.get("regime")
        signal = state.get("signal", "")
        king = state.get("king") or 0
        floor_v = state.get("floor") or 0

        if regime == "POS" and king and spot:
            king_dist = (king - spot) / spot * 100
            if 0.3 < king_dist < 5:
                score += 2
                reasons.append(f"King ${king} magnet (+{king_dist:.1f}%)")
            if floor_v and spot > floor_v:
                score += 1
                reasons.append(f"Above floor ${floor_v}")

        if signal in ("MAGNET UP", "SUPPORT"):
            score += 1
            reasons.append(f"GEX: {signal}")

        # 2. RTS / momentum (strong relative strength vs SPY)
        rts = state.get("_rts") or {}
        rts_score = rts.get("score", 0) if isinstance(rts, dict) else 0
        if rts_score >= 70:
            score += 2
            reasons.append(f"RTS {rts_score} (leader)")
        elif rts_score >= 50:
            score += 1
            reasons.append(f"RTS {rts_score}")

        # 3. Mir's preferred sectors (photonics, semi equip, AI, space)
        from .mir_rules import is_mir_sector
        in_sector, sector_note = is_mir_sector(ticker)
        if in_sector:
            score += 2
            reasons.append(sector_note)

        # 4. IV environment (cheap options = better entry, per backtest)
        ivp = state.get("_ivp")
        if ivp is not None and ivp < 30:
            score += 1
            reasons.append(f"IVP {ivp}% (cheap)")

        # 5. Time bonus (PM window per backtest)
        if is_pm:
            score += 1
            reasons.append("PM window" + (" (POWER HOUR)" if is_power_hour else ""))

        # 6. Monday penalty
        if is_monday:
            score -= 1

        # Threshold: 6+ to alert
        if score >= 6:
            # Select a concrete contract for the alert (relaxed gates for smaller tickers)
            contract = _select_contract(state, "BULL", relaxed=True)
            contract_line = ""
            if contract:
                contract_line = (
                    f"${contract['strike']} {contract['option_type'].upper()} "
                    f"{contract['expiration']} ({contract['dte']}DTE)"
                )
                if contract.get("mid_price"):
                    contract_line += f" @${contract['mid_price']:.2f}"
                if contract.get("bid") and contract.get("ask"):
                    contract_line += f" (bid ${contract['bid']:.2f} / ask ${contract['ask']:.2f})"

            # Check for flow confirmation — always show status
            flow_note = "FLOW: none detected"
            try:
                from .flow_alerts import get_recent_flow
                recent = get_recent_flow(ticker, minutes=30)
                if recent:
                    flow_note = f"FLOW: {recent.get('sentiment','')} ${recent.get('notional',0)/1e6:.1f}M"
            except Exception:
                pass

            setup = {
                "ticker": ticker,
                "score": score,
                "spot": spot,
                "king": king,
                "floor": floor_v,
                "regime": regime,
                "signal": signal,
                "rts_score": rts_score if rts_score else None,
                "reasons": reasons,
                "contract": contract_line,
                "flow": flow_note,
            }
            setups.append(setup)
            _setup_seen[ticker] = now_ts
            _save_setup_seen()  # persist immediately — survives --reload

            # Persist to setup_forming table for outcome tracking (Phase 6 —
            # was previously fire-and-forget Telegram only, no WR data).
            try:
                with _conn() as _c:
                    _c.execute(
                        """INSERT INTO setup_forming
                            (ts, ticker, score, spot, king, floor, regime, signal,
                             rts_score, ivp, contract, reasons, flow_note,
                             in_mir_sector, is_pm, is_monday)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            int(now_ts), ticker, score, spot, king, floor_v,
                            regime, signal,
                            rts_score if rts_score else None,
                            ivp,
                            contract_line,
                            _json.dumps(reasons),
                            flow_note,
                            int(in_sector), int(is_pm), int(is_monday),
                        ),
                    )
            except Exception as e:
                print(f"[SETUP] persist failed for {ticker}: {e}")

    # Sort by score descending, take top 3
    setups.sort(key=lambda x: x["score"], reverse=True)
    setups = setups[:3]

    # Push to Telegram
    for s in setups:
        try:
            from .telegram import send
            king_target = f"Target: King ${s['king']}" if s['king'] else ""
            floor_stop = f"Stop: Floor ${s['floor']}" if s['floor'] else ""
            rts_str = f"RTS: {s['rts_score']}" if s.get('rts_score') else ""
            contract_str = f"\n>> <b>{s['ticker']} {s['contract']}</b>" if s.get('contract') else ""
            flow_str = f"\n{s['flow']}"
            msg = (
                f"SETUP FORMING: <b>{s['ticker']}</b>\n"
                f"Score: {s['score']}/10"
                + (f" | {rts_str}" if rts_str else "")
                + f"\nSpot: ${s['spot']:.2f} | {king_target} | {floor_stop}"
                + f"\nRegime: {s['regime']} | {s['signal']}"
                + contract_str
                + flow_str
                + f"\n\n"
                + "\n".join(f"  {r}" for r in s["reasons"])
                + f"\n\n<i>Mir-style setup | PM window entry</i>"
            )
            await send(msg, ticker=s["ticker"])
        except Exception:
            pass

    return setups


async def run_signal_engine(stop_event: asyncio.Event) -> None:
    """Background loop: generate signals every 60s, check outcomes every cycle.

    History: was 300s (5 min) which produced 3-5 min Telegram lag on SOE
    callouts — by the time the alert landed in chat, price had already
    moved off the entry. Dropped to 60s on 2026-05-27 after NBIS 5/27
    callout fired at 12:32 with Entry $207.75 while price was actually
    $208.30+. generate_signals() is cache-only (no Tradier REST inside
    the hot loop) so 5× more frequent execution adds no network calls,
    just more CPU on the cached snapshot iteration.

    Companion change in the dispatch block: spot is re-stamped from the
    live cache at dispatch time so `Entry:` matches what the trader sees
    when the message lands.
    """
    await asyncio.sleep(60)  # Wait for GEX worker to populate cache

    last_gen = 0
    while not stop_event.is_set():
        try:
            now = time.time()
            # Generate new signals every 60s (was 300s pre-2026-05-27)
            if now - last_gen >= 60:
                # Get confluence for scoring
                confluence = {}
                for t in ["SPY", "QQQ", "IWM"]:
                    state = await cache.get(t)
                    if state:
                        confluence[t] = state
                sigs = await generate_signals(confluence or None)
                if sigs:
                    print(f"[SOE] {len(sigs)} new signals: {', '.join(s['ticker'] for s in sigs[:5])}")
                last_gen = now

            # Check outcomes every minute
            await check_signal_outcomes()
            await check_ab_outcomes()

            # Scan for Mir-style setups forming (every signal cycle)
            if now - last_gen < 5:  # Only right after signal generation
                try:
                    setups = await scan_setups()
                    if setups:
                        print(f"[SETUP] {len(setups)} setups forming: {', '.join(s['ticker'] for s in setups)}")
                except Exception as e:
                    print(f"[SETUP] error: {e}")
        except Exception as e:
            print(f"[SOE] error: {e}")

        # Outer loop pace: 15s tick so the inner 60s eval gate triggers
        # promptly (was 60s tick → actual cadence was 60-120s). With
        # 15s tick + 60s gate the worst-case eval-to-eval gap is ~75s.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
