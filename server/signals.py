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
  outcome_ts INTEGER
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

    # 1b. King polarity
    if (direction == "BULL" and king_positive) or (direction == "BEAR" and not king_positive):
        structure += 0.5
        side = "+GEX" if king_positive else "-GEX"
        sub_reasons.append(f"King ${king} is {side}")

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

    return score, reasons


def _select_contract(
    state: dict[str, Any],
    direction: str,
    tradier_chains: dict | None = None,
    relaxed: bool = False,
    mir_mode: bool = False,
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
        oi_limit = 500
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
    if direction == "BULL":
        target = king if king > spot else (spot * 1.02)
        target_label = "King (magnet)" if king > spot else "+2%"
        stop = state.get("floor", spot * 0.98)
        stop_label = "Floor break"
    else:
        target = king if king < spot else (spot * 0.98)
        target_label = "King (breakdown)" if king < spot else "-2%"
        stop = state.get("ceiling", spot * 1.02)
        stop_label = "Ceiling break"

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
    """Determine trade direction from GEX structure."""
    signal = state.get("signal", "")
    if signal in ("MAGNET UP", "SUPPORT", "PINNING"):
        return "BULL"
    elif signal in ("AIR POCKET", "RESISTANCE"):
        return "BEAR"
    elif signal == "DANGER":
        return None  # Too risky
    return None


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
    # Allow pre-market signal scanning from 7 AM (chains available before open)
    if now.hour < 7:
        return []
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return []

    # Earnings blackout: skip tickers with earnings within 7 days
    global _earnings_blackout_cache
    cache_ts, blackout_set = _earnings_blackout_cache
    if time.time() - cache_ts > 3600:
        blackout_set = await _fetch_earnings_blackout()
        _earnings_blackout_cache = (time.time(), blackout_set)

    snapshot = await cache.snapshot()
    new_signals: list[dict[str, Any]] = []

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

    for ticker, state in snapshot.items():
        # Earnings blackout: skip tickers with upcoming earnings (both books)
        if ticker in blackout_set:
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

        # Trend day context (used by both pathways)
        trend_day = state.get("_trend_day") or {}
        trend_mode = trend_day.get("trend_mode", "NORMAL")
        gap_dir = trend_day.get("gap_direction", "")

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

        # Inject breadth context into state for scoring
        # Mir-originated trend-day signals: zero out breadth penalty entirely.
        # On gap-and-go days, NYMO overbought is expected and should not block.
        if breadth_data:
            if is_mir_originated and trend_mode in ("TREND_DAY", "EXTREME_TREND"):
                pass  # Skip breadth injection — don't penalize strong tape
            else:
                state["_breadth"] = breadth_data

        score, reasons = _compute_signal_score(state, direction, confluence, iv_universe)
        grade = _score_to_grade(score)
        signal_type = _determine_signal_type(state, direction)

        # Mir-originated signals use narrower contract selection
        if is_mir_originated:
            signal_type = "MIR_MOMENTUM"
            contract = _select_contract(state, direction, mir_mode=True)
            # Fallback to standard selection if mir_mode is too restrictive
            if not contract:
                contract = _select_contract(state, direction)
        else:
            contract = _select_contract(state, direction)

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
            "reasoning": "\n".join(f"✓ {r}" for r in reasons),
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
        _insert_signal(sig)
        _seen_signals.add(dedup_key)
        new_signals.append(sig)

        # Telegram push: A/A+ always, B+ only if solid (flow or volume quality)
        should_push = False
        if sig.get("grade") in ("A+", "A"):
            should_push = True
        elif sig.get("grade") == "B+" and contract:
            # B+ needs quality confirmation: tight spread + decent OI + good R:R
            spread_ok = contract.get("spread_pct", 99) < 5
            oi_ok = contract.get("contract_oi", 0) >= 1000
            rr_ok = contract.get("rr_ratio", 0) >= 1.5
            mir_ok = (mir_sig or {}).get("conviction", "").upper() in ("HIGH", "MEDIUM")
            if (spread_ok and oi_ok and rr_ok) or mir_ok:
                should_push = True

        if should_push and not sig.get("_suppress_telegram"):
            try:
                from .telegram import send, format_soe_signal
                await send(
                    format_soe_signal(sig),
                    ticker=ticker,
                    priority=(sig["grade"] == "A+"),
                )
            except Exception:
                pass

    return new_signals


def _insert_signal(sig: dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO soe_signals
            (ts, ticker, direction, signal_type, grade, score, max_score,
             strike, expiration, option_type, target, target_label, stop, stop_label,
             rr_ratio, spot, king, floor_level, ceiling_level, zgl, regime, iv,
             delta, gamma, reasoning, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            ),
        )


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

_setup_seen: dict[str, float] = {}  # ticker -> last alert ts (4hr cooldown)

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
    if now.weekday() >= 5 or now.hour < 9 or now.hour > 16:
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

    for ticker, state in snapshot.items():
        # Skip indexes — this is for single-stock sector leaders
        if ticker in ("SPY", "QQQ", "IWM", "DIA", "SPX", "NDX", "RUT", "VIX"):
            continue

        # 4-hour cooldown per ticker
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

            # Check for flow confirmation
            flow_note = ""
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
            flow_str = f"\n{s['flow']}" if s.get('flow') else ""
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
    """Background loop: generate signals every 5 min, check outcomes every 1 min."""
    await asyncio.sleep(60)  # Wait for GEX worker to populate cache

    last_gen = 0
    while not stop_event.is_set():
        try:
            now = time.time()
            # Generate new signals every 5 minutes
            if now - last_gen >= 300:
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

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
