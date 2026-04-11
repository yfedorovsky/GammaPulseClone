"""SOE Signals — Signal-to-Strike Pipeline.

Scans all cached tickers and generates scored trade recommendations
based on GEX structure, regime, king positioning, IV, and dealer flow.

Each signal includes:
  - Grade (A+ / A / B+ / B / C) based on 8-factor scoring
  - Specific contract: strike, expiration, type (CALL/PUT)
  - Entry/Target/Stop with R:R ratio
  - GEX context reasoning
  - Lifecycle tracking: PENDING → WIN / LOSS

Scoring factors (8 total):
  1. Regime alignment (POS γ for calls, NEG γ for puts)
  2. King polarity matches direction (+GEX king above = bullish)
  3. King distance (0.5-3% sweet spot)
  4. Floor/ceiling confirmation (floor below for calls, ceiling above for puts)
  5. ZGL position (above ZGL = stable for calls)
  6. IV level (low IV = cheap options = higher score)
  7. Confluence alignment (3/3 SPY/QQQ/IWM)
  8. Call/Put wall alignment (call wall above for calls = runway)
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


def _score_to_grade(score: float, max_score: float = 8) -> str:
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
) -> tuple[float, list[str]]:
    """Score a potential trade signal out of 8 factors. Returns (score, reasons)."""
    score = 0.0
    reasons: list[str] = []

    king = state.get("king", 0)
    floor_val = state.get("floor", 0)
    ceiling_val = state.get("ceiling", 0)
    zgl = state.get("zgl", 0)
    spot = state.get("actual_spot") or state.get("_spot") or 0
    regime = state.get("regime", "")
    signal = state.get("signal", "")
    iv = state.get("iv", 0)
    pos_gex = state.get("pos_gex", 0)
    neg_gex = state.get("neg_gex", 0)

    if not spot or not king:
        return 0, []

    king_dist_pct = abs(king - spot) / spot if spot else 0

    # Find king polarity
    ed = state.get("exp_data", {})
    macro = ed.get("MACRO (ALL 200D)", {})
    strikes_list = macro.get("strikes", [])
    king_strike = next((s for s in strikes_list if s.get("strike") == king), None)
    king_positive = king_strike["net_gex"] >= 0 if king_strike else True

    # 1. Regime alignment
    if direction == "BULL" and regime == "POS":
        score += 1
        reasons.append("Positive gamma — dealers buy dips, supporting upside")
    elif direction == "BEAR" and regime == "NEG":
        score += 1
        reasons.append("Negative gamma — dealers amplify moves, confirming downside")
    elif direction == "BULL" and regime == "NEG":
        reasons.append("NEG gamma regime — counter-trend, reduced conviction")
    elif direction == "BEAR" and regime == "POS":
        reasons.append("POS gamma regime — counter-trend, reduced conviction")

    # 2. King polarity alignment
    if direction == "BULL" and king_positive and king > spot:
        score += 1
        reasons.append(f"King ${king} above acts as magnet (+{king_dist_pct*100:.1f}%)")
    elif direction == "BEAR" and not king_positive and king < spot:
        score += 1
        reasons.append(f"-GEX King ${king} below = breakdown target (-{king_dist_pct*100:.1f}%)")
    elif direction == "BULL" and king_positive and king <= spot:
        score += 0.5
        reasons.append(f"+GEX King ${king} acts as support below")
    elif direction == "BEAR" and not king_positive and king >= spot:
        score += 0.5
        reasons.append(f"-GEX King ${king} above = resistance")

    # 3. King distance (0.5-3% sweet spot)
    if 0.005 <= king_dist_pct <= 0.03:
        score += 1
        reasons.append(f"King distance {king_dist_pct*100:.1f}% in sweet spot")
    elif king_dist_pct < 0.003:
        score += 0.5  # Pinning — less directional edge

    # 4. Floor/ceiling confirmation
    if direction == "BULL" and floor_val and floor_val < spot:
        score += 1
        reasons.append(f"Floor at ${floor_val} provides support below")
    elif direction == "BEAR" and ceiling_val and ceiling_val > spot:
        score += 1
        reasons.append(f"Ceiling at ${ceiling_val} caps upside")

    # 5. ZGL position
    if zgl:
        if direction == "BULL" and spot > zgl:
            score += 1
            reasons.append("Above ZGL — stable regime supports long positions")
        elif direction == "BEAR" and spot < zgl:
            score += 1
            reasons.append("Below ZGL — volatile regime supports short positions")

    # 6. IV level
    if iv:
        if iv < 0.25:
            score += 1
            reasons.append(f"IV low at {iv*100:.0f}% — options are cheap")
        elif iv < 0.35:
            score += 0.5
            reasons.append(f"IV moderate at {iv*100:.0f}%")
        else:
            reasons.append(f"IV elevated at {iv*100:.0f}% — options are expensive")

    # 7. Confluence alignment
    if confluence:
        bull_count = 0
        for t in ["SPY", "QQQ", "IWM"]:
            cd = confluence.get(t, {})
            c_ed = cd.get("exp_data", {})
            c_macro = c_ed.get("MACRO (ALL 200D)", {})
            c_king = c_macro.get("king", 0)
            c_spot = cd.get("spot", 0)
            c_strikes = c_macro.get("strikes", [])
            c_king_s = next((s for s in c_strikes if s.get("strike") == c_king), None)
            if c_king_s and c_king_s.get("net_gex", 0) >= 0:
                bull_count += 1
        if direction == "BULL" and bull_count >= 2:
            score += 1
            reasons.append(f"Macro confluence: {bull_count}/3 bullish")
        elif direction == "BEAR" and bull_count <= 1:
            score += 1
            reasons.append(f"Macro confluence: {3 - bull_count}/3 bearish")

    # 8. Call/Put wall alignment
    # Find highest-OI call strike (call wall) and put strike (put wall)
    calls = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] > spot]
    puts = [s for s in strikes_list if s.get("net_gex", 0) > 0 and s["strike"] < spot]
    call_wall = max(calls, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if calls else None
    put_wall = min(puts, key=lambda s: abs(s.get("net_gex", 0))).get("strike") if puts else None

    if direction == "BULL" and call_wall and call_wall > king:
        score += 1
        reasons.append(f"Call wall at ${call_wall} (+{((call_wall-spot)/spot)*100:.1f}%) = upside runway")
    elif direction == "BEAR" and put_wall and put_wall < king:
        score += 1
        reasons.append(f"Put wall at ${put_wall} (-{((spot-put_wall)/spot)*100:.1f}%) = downside target")

    return score, reasons


def _select_contract(
    state: dict[str, Any],
    direction: str,
    tradier_chains: dict | None = None,
) -> dict[str, Any] | None:
    """Select the optimal contract for the signal."""
    spot = state.get("actual_spot") or state.get("_spot") or 0
    king = state.get("king", 0)
    if not spot:
        return None

    ed = state.get("exp_data", {})
    exps = state.get("exps", [])

    # Find expiration 10-21 DTE (sweet spot for directional)
    import datetime
    today = datetime.date.today()
    target_exp = None
    target_dte = 0

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

    if not target_exp:
        # Fallback to nearest exp > 3 DTE
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

    if not target_exp:
        return None

    # Select strike: slightly OTM (0.3-0.5 delta equivalent)
    otype = "call" if direction == "BULL" else "put"
    exp_data = ed.get(target_exp, {})
    strikes = exp_data.get("strikes", [])

    if not strikes:
        return None

    # For calls: pick strike just above spot (OTM). For puts: just below.
    if direction == "BULL":
        candidates = [s for s in strikes if s["strike"] >= spot]
        candidates.sort(key=lambda s: s["strike"])
    else:
        candidates = [s for s in strikes if s["strike"] <= spot]
        candidates.sort(key=lambda s: s["strike"], reverse=True)

    # Pick the 2nd or 3rd OTM strike (slightly OTM, not deep)
    idx = min(2, len(candidates) - 1) if candidates else -1
    if idx < 0:
        return None

    selected = candidates[idx]
    strike = selected["strike"]

    # Compute entry, target, stop
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
        "strike": strike,
        "expiration": target_exp,
        "option_type": otype,
        "dte": target_dte,
        "target": target,
        "target_label": target_label,
        "stop": stop,
        "stop_label": stop_label,
        "rr_ratio": round(rr, 1),
        "delta": selected.get("delta", 0),
        "gamma": selected.get("gamma", 0),
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


async def generate_signals(confluence: dict | None = None) -> list[dict[str, Any]]:
    """Scan all cached tickers and generate SOE signals."""
    import datetime

    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return []
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return []

    snapshot = await cache.snapshot()
    new_signals: list[dict[str, Any]] = []

    for ticker, state in snapshot.items():
        direction = _determine_direction(state)
        if direction is None:
            continue

        # Dedup: only one signal per ticker per hour
        hour_key = f"{ticker}:{direction}:{now.strftime('%Y%m%d%H')}"
        if hour_key in _seen_signals:
            continue

        score, reasons = _compute_signal_score(state, direction, confluence)

        # Minimum score threshold
        if score < 3.5:
            continue

        grade = _score_to_grade(score)
        signal_type = _determine_signal_type(state, direction)

        contract = _select_contract(state, direction)
        if not contract:
            continue

        spot = state.get("actual_spot") or state.get("_spot") or 0

        sig = {
            "ticker": ticker,
            "direction": "▲" if direction == "BULL" else "▼",
            "signal_type": signal_type,
            "grade": grade,
            "score": round(score, 1),
            "max_score": 8,
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
        }

        # Insert into DB
        _insert_signal(sig)
        _seen_signals.add(hour_key)
        new_signals.append(sig)

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
