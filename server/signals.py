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
            penalty_weight = 0.25 if is_index else 0.5
            macro_score = max(macro_score + b_score * penalty_weight, 0)
            macro_reasons.append(b_reason)

    score += min(macro_score, 1.0)
    if macro_reasons:
        reasons.append(f"Macro context ({min(macro_score,1.0):.1f}/1): {'; '.join(macro_reasons)}")

    return score, reasons


def _select_contract(
    state: dict[str, Any],
    direction: str,
    tradier_chains: dict | None = None,
) -> dict[str, Any] | None:
    """Select the optimal contract for the signal.

    Quality gates (from discord workflow + triple review consensus):
      - Bid-ask spread must be < 10% of mid price (liquidity)
      - Open interest must be > 500 on the strike (exit-ability)
      - Delta target: 0.30-0.55 (enough directional sensitivity)
      - DTE sweet spot: 14, range 7-28
    """
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

    # For SPY/QQQ: try 0DTE first (today's expiration)
    if is_0dte_eligible:
        for exp in exps:
            if exp == today_str:
                target_exp = exp
                target_dte = 0
                break

    # Standard: 7-28 DTE, sweet spot 14
    if not target_exp:
        for exp in exps:
            if exp.startswith("MACRO"):
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp)
                dte = (exp_date - today).days
                if 7 <= dte <= 28:
                    if target_exp is None or abs(dte - 14) < abs(target_dte - 14):
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

        if spread_pct > 0.10:  # > 10% of mid = too wide, skip
            continue

        # ── Quality Gate 2: Open interest ──────────────────────
        oi = c.get("open_interest", 0) or 0
        if oi < 500:
            continue

        # ── Quality Gate 3: Delta range ────────────────────────
        greeks = c.get("greeks") or {}
        delta = abs(greeks.get("delta", 0) or 0)
        # Accept 0.25-0.60 delta range (covers 0.30-0.55 target)
        if delta < 0.25 or delta > 0.60:
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
        # Earnings blackout: skip tickers with upcoming earnings
        if ticker in blackout_set:
            continue

        direction = _determine_direction(state)
        if direction is None:
            continue

        # Dedup: only one signal per ticker per 2 hours (direction-independent)
        # Prevents the same ticker from spamming regardless of signal flip
        dedup_key = f"{ticker}:{now.strftime('%Y%m%d')}{now.hour // 2}"
        if dedup_key in _seen_signals:
            continue

        # Inject breadth context into state for scoring
        if breadth_data:
            state["_breadth"] = breadth_data

        score, reasons = _compute_signal_score(state, direction, confluence, iv_universe)

        # Minimum score threshold (2.5/6 ≈ 42%, was 3.5/8 ≈ 44%)
        if score < 2.5:
            continue

        grade = _score_to_grade(score)
        signal_type = _determine_signal_type(state, direction)

        contract = _select_contract(state, direction)
        if not contract:
            continue

        # ── Minimum R:R Gate ──────────────────────────────────
        # Reject setups where risk > reward. A 0.3x R:R means you need
        # 77% win rate just to break even — not realistic for directional.
        if contract.get("rr_ratio", 0) < 1.0:
            continue

        # ── 0DTE Freshness Gate ────────────────────────────────────
        # 0DTE signals require fresh Greeks — stale hourly data from
        # Tradier is not safe for same-day expiry trades.
        dte = contract.get("dte", 99)
        greeks_age = state.get("_greeks_age_seconds", 999)
        dte_0_status = None

        if dte == 0:
            # 0DTE experimental: SPY/QQQ only
            if ticker not in ("SPY", "QQQ"):
                continue
            # Hard block if Greeks source is Tradier (ORATS, unverified for 0DTE)
            greeks_source = state.get("_greeks_source", "tradier")
            if greeks_source == "tradier":
                continue
            # Gate on quote freshness — allow within scan cycle (120s)
            quote_ts = state.get("_quote_ts", 0)
            quote_age = time.time() - quote_ts if quote_ts else 999
            if quote_age > 180:
                continue  # Spot price too stale for 0DTE (3 min max)
            # Blocked: Greeks too stale for 0DTE
            if greeks_age > 60:
                continue
            # Classify freshness
            if greeks_age <= 60 and quote_age <= 180:
                dte_0_status = "TRADEABLE"
            else:
                dte_0_status = "EXPERIMENTAL"

        spot = state.get("actual_spot") or state.get("_spot") or 0

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
            "_0dte_status": dte_0_status,  # None for non-0DTE, "TRADEABLE" or "EXPERIMENTAL"
        }

        # Enrich with discipline layer (sizing, tier, circuit breaker)
        try:
            from .discipline import enrich_signal
            # Fetch real Mir conviction from cache (if Mac Mini bridge is active)
            mir_sig = await cache.get_mir_signal(ticker)
            sig = enrich_signal(sig, mir_signal=mir_sig)
        except Exception:
            pass

        # Insert into DB
        _insert_signal(sig)
        _seen_signals.add(dedup_key)
        new_signals.append(sig)

        # Telegram push for A/A+ signals (rate-limited, not spammy)
        if sig.get("grade") in ("A+", "A") and not sig.get("_suppress_telegram"):
            try:
                from .telegram import send, format_soe_signal
                await send(
                    format_soe_signal(sig),
                    ticker=ticker,
                    priority=(sig["grade"] == "A+"),  # A+ bypasses global rate limit
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
        except Exception as e:
            print(f"[SOE] error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
