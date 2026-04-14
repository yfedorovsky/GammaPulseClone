"""NYMO/NAMO Breadth Module — Market internals context layer.

Computes McClellan Oscillator for NYSE (NYMO) and NASDAQ (NAMO)
from advance/decline data, with proper exchange classification.

Architecture role (from unified architecture note):
  - GEX tells you WHERE dealer structure may matter
  - NYMO/NAMO tells you WHETHER market internals are stretched enough
    for that structure to produce a real reversal

Data source: Massive/Polygon
  - /v3/reference/tickers for exchange classification (XNYS, XNAS)
  - /v2/aggs/grouped/locale/us/market/stocks/{date} for daily A/D
  - Stored in SQLite breadth_daily table (one row per exchange per day)

McClellan Oscillator = EMA(19) of Net Advances - EMA(39) of Net Advances
  where Net Advances = Advancing Issues - Declining Issues
  Advance = today close > prior close (not open-to-close)
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

import httpx

from .config import get_settings

# ── Schema ────────────────────────────────────────────────────────────
BREADTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS breadth_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    exchange TEXT NOT NULL,
    advancers INTEGER,
    decliners INTEGER,
    unchanged INTEGER,
    net_advances INTEGER,
    ema19 REAL,
    ema39 REAL,
    oscillator REAL,
    UNIQUE(date, exchange)
);
CREATE INDEX IF NOT EXISTS idx_breadth_date ON breadth_daily(date);
"""

# ── Exchange classification cache ─────────────────────────────────────
_exchange_map: dict[str, str] = {}  # ticker -> "NYSE" | "NASDAQ"
_exchange_loaded = False

# ── In-memory cache ──────────────────────────────────────────────────
_breadth_cache: dict[str, tuple[float, dict[str, Any]]] = {}
BREADTH_CACHE_TTL = 1800  # 30 minutes


def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    return c


def init_breadth_db() -> None:
    c = _conn()
    c.executescript(BREADTH_SCHEMA)
    c.close()


def _ema(values: list[float], period: int) -> list[float]:
    """Compute exponential moving average."""
    if not values:
        return []
    multiplier = 2.0 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * multiplier + ema[-1] * (1 - multiplier))
    return ema


async def _load_exchange_map() -> None:
    """Load ticker -> exchange mapping from Massive reference endpoint.

    Filters to common stocks only (type=CS), excludes ETFs/warrants/preferreds.
    XNYS = NYSE, XNAS = NASDAQ. Cached in memory.
    """
    global _exchange_map, _exchange_loaded

    if _exchange_loaded:
        return

    s = get_settings()
    if not s.massive_api_key:
        return

    print("[BREADTH] Loading exchange classification from Massive...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            next_url: str | None = None
            first = True
            page = 0

            while (first or next_url) and page < 20:
                first = False
                page += 1

                if next_url:
                    sep = "&" if "?" in next_url else "?"
                    r = await httpx.AsyncClient(timeout=30).get(
                        f"{next_url}{sep}apiKey={s.massive_api_key}"
                    )
                else:
                    r = await client.get(
                        f"{s.massive_base_url}/v3/reference/tickers",
                        params={
                            "apiKey": s.massive_api_key,
                            "market": "stocks",
                            "type": "CS",  # Common stocks only
                            "active": "true",
                            "limit": "1000",
                        },
                    )

                if r.status_code != 200:
                    break

                data = r.json()
                for t in data.get("results", []):
                    ticker = t.get("ticker", "")
                    exchange = t.get("primary_exchange", "")
                    if ticker and exchange:
                        if exchange in ("XNYS",):
                            _exchange_map[ticker] = "NYSE"
                        elif exchange in ("XNAS",):
                            _exchange_map[ticker] = "NASDAQ"

                next_url = data.get("next_url")
                if not next_url:
                    break

    except Exception as e:
        print(f"[BREADTH] Exchange map load error: {e}")

    _exchange_loaded = True
    nyse_count = sum(1 for v in _exchange_map.values() if v == "NYSE")
    nasdaq_count = sum(1 for v in _exchange_map.values() if v == "NASDAQ")
    print(f"[BREADTH] Exchange map: {nyse_count} NYSE + {nasdaq_count} NASDAQ = {len(_exchange_map)} common stocks")


async def compute_daily_breadth(date_str: str) -> dict[str, dict[str, int]] | None:
    """Compute advance/decline for a specific date from Massive grouped daily.

    Returns {"NYSE": {adv, dec, unch, net}, "NASDAQ": {adv, dec, unch, net}}
    """
    s = get_settings()
    if not s.massive_api_key:
        return None

    await _load_exchange_map()
    if not _exchange_map:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{s.massive_base_url}/v2/aggs/grouped/locale/us/market/stocks/{date_str}",
                params={"apiKey": s.massive_api_key, "adjusted": "true"},
            )
            if r.status_code != 200:
                return None

            data = r.json()
            tickers = data.get("results", [])
            if not tickers:
                return None

        counts: dict[str, dict[str, int]] = {
            "NYSE": {"adv": 0, "dec": 0, "unch": 0},
            "NASDAQ": {"adv": 0, "dec": 0, "unch": 0},
        }

        for t in tickers:
            sym = t.get("T", "")
            exchange = _exchange_map.get(sym)
            if not exchange:
                continue

            close = t.get("c", 0)
            prev_close = t.get("pc", t.get("o", 0))  # Use prev close if available, else open
            if close > prev_close:
                counts[exchange]["adv"] += 1
            elif close < prev_close:
                counts[exchange]["dec"] += 1
            else:
                counts[exchange]["unch"] += 1

        for exchange in counts:
            counts[exchange]["net"] = counts[exchange]["adv"] - counts[exchange]["dec"]

        return counts

    except Exception as e:
        print(f"[BREADTH] Daily computation error for {date_str}: {e}")
        return None


def _get_oscillator_history(exchange: str, limit: int = 60) -> list[dict[str, Any]]:
    """Read stored oscillator history from SQLite."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM breadth_daily WHERE exchange = ? ORDER BY date ASC LIMIT ?",
            (exchange, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def _store_daily(date_str: str, exchange: str, adv: int, dec: int, unch: int,
                 net: int, ema19: float, ema39: float, osc: float) -> None:
    """Store a day's breadth data (upsert)."""
    c = _conn()
    try:
        c.execute(
            """INSERT OR REPLACE INTO breadth_daily
               (date, exchange, advancers, decliners, unchanged, net_advances, ema19, ema39, oscillator)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date_str, exchange, adv, dec, unch, net, ema19, ema39, osc),
        )
        c.commit()
    finally:
        c.close()


def _compute_oscillator_from_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute current McClellan state from stored history."""
    if len(history) < 5:
        return {"value": 0, "regime": "INSUFFICIENT_DATA"}

    net_adv = [h["net_advances"] for h in history]
    ema19_vals = _ema(net_adv, 19)
    ema39_vals = _ema(net_adv, 39)
    osc_vals = [e19 - e39 for e19, e39 in zip(ema19_vals, ema39_vals)]

    current = osc_vals[-1]
    prev = osc_vals[-2] if len(osc_vals) >= 2 else current

    # Classify regime
    if current < -60:
        regime = "EXTREME_OVERSOLD"
    elif current < -40:
        regime = "OVERSOLD"
    elif current > 60:
        regime = "EXTREME_OVERBOUGHT"
    elif current > 40:
        regime = "OVERBOUGHT"
    else:
        regime = "NEUTRAL"

    turning_up = current > prev and prev < 0
    turning_down = current < prev and prev > 0

    recent_5 = osc_vals[-5:] if len(osc_vals) >= 5 else osc_vals
    higher_low = len(recent_5) >= 5 and min(recent_5[-2:]) > min(recent_5[:3])
    lower_high = len(recent_5) >= 5 and max(recent_5[-2:]) < max(recent_5[:3])

    return {
        "value": round(current, 2),
        "prev": round(prev, 2),
        "ema19": round(ema19_vals[-1], 2),
        "ema39": round(ema39_vals[-1], 2),
        "regime": regime,
        "turning_up": turning_up,
        "turning_down": turning_down,
        "bullish_divergence": higher_low and current < 0,
        "bearish_divergence": lower_high and current > 0,
        "history_5d": [round(v, 2) for v in osc_vals[-5:]],
        "latest_date": history[-1]["date"] if history else "",
    }


async def update_breadth_today() -> None:
    """Fetch today's breadth data and update the oscillator.

    Call this once per day (or from a background task).
    Idempotent — safe to call multiple times.
    """
    import datetime
    today = datetime.date.today()
    if today.weekday() >= 5:
        return

    date_str = today.isoformat()

    # Check if we already have today
    c = _conn()
    try:
        existing = c.execute(
            "SELECT 1 FROM breadth_daily WHERE date = ? AND exchange = 'NYSE'",
            (date_str,),
        ).fetchone()
    finally:
        c.close()

    if existing:
        return  # Already computed

    counts = await compute_daily_breadth(date_str)
    if not counts:
        return

    for exchange in ("NYSE", "NASDAQ"):
        ec = counts.get(exchange, {})
        adv = ec.get("adv", 0)
        dec = ec.get("dec", 0)
        unch = ec.get("unch", 0)
        net = ec.get("net", 0)

        # Get history to compute running EMAs
        history = _get_oscillator_history(exchange, limit=60)
        all_net = [h["net_advances"] for h in history] + [net]

        ema19_vals = _ema(all_net, 19)
        ema39_vals = _ema(all_net, 39)
        osc = ema19_vals[-1] - ema39_vals[-1] if ema19_vals and ema39_vals else 0

        _store_daily(date_str, exchange, adv, dec, unch, net,
                     ema19_vals[-1] if ema19_vals else 0,
                     ema39_vals[-1] if ema39_vals else 0,
                     osc)

    print(f"[BREADTH] Updated for {date_str}: NYSE {counts['NYSE']} | NASDAQ {counts['NASDAQ']}")


async def get_nymo() -> dict[str, Any]:
    """Get NYSE McClellan Oscillator (NYMO)."""
    cached = _breadth_cache.get("nymo")
    if cached and (time.time() - cached[0]) < BREADTH_CACHE_TTL:
        return cached[1]

    await update_breadth_today()
    history = _get_oscillator_history("NYSE", limit=60)
    result = _compute_oscillator_from_history(history)
    result["source"] = "massive"
    result["exchange"] = "NYSE"
    result["label"] = "NYMO"

    _breadth_cache["nymo"] = (time.time(), result)
    return result


async def get_namo() -> dict[str, Any]:
    """Get NASDAQ McClellan Oscillator (NAMO)."""
    cached = _breadth_cache.get("namo")
    if cached and (time.time() - cached[0]) < BREADTH_CACHE_TTL:
        return cached[1]

    await update_breadth_today()
    history = _get_oscillator_history("NASDAQ", limit=60)
    result = _compute_oscillator_from_history(history)
    result["source"] = "massive"
    result["exchange"] = "NASDAQ"
    result["label"] = "NAMO"

    _breadth_cache["namo"] = (time.time(), result)
    return result


async def get_vix_term_structure() -> dict[str, Any]:
    """Get VIX term structure (contango/backwardation) from Tradier.

    Contango (VIX < VIX3M) = normal, bullish
    Backwardation (VIX > VIX3M) = fear, bearish
    """
    cached = _breadth_cache.get("vix_ts")
    if cached and (time.time() - cached[0]) < BREADTH_CACHE_TTL:
        return cached[1]

    try:
        from .tradier import TradierClient
        t = TradierClient()
        quotes = await t.quotes(["VIX", "VIX3M", "UVXY"])
        await t.close()

        vix = quotes.get("VIX", 0)
        vix3m = quotes.get("VIX3M", 0)

        if vix and vix3m:
            ratio = round(vix / vix3m, 3)
            spread = round(vix - vix3m, 2)
            if ratio > 1.05:
                structure = "BACKWARDATION"  # Fear — bearish
            elif ratio < 0.95:
                structure = "CONTANGO"  # Normal — bullish
            else:
                structure = "FLAT"
        else:
            ratio = 0
            spread = 0
            structure = "NO_DATA"

        result = {
            "vix": vix,
            "vix3m": vix3m,
            "ratio": ratio,
            "spread": spread,
            "structure": structure,
        }
    except Exception:
        result = {"vix": 0, "vix3m": 0, "ratio": 0, "spread": 0, "structure": "NO_DATA"}

    _breadth_cache["vix_ts"] = (time.time(), result)
    return result


async def get_breadth_context() -> dict[str, Any]:
    """Get combined breadth context for the signal engine."""
    nymo = await get_nymo()
    namo = await get_namo()
    vix_ts = await get_vix_term_structure()

    return {
        "nymo": nymo,
        "namo": namo,
        "vix_term_structure": vix_ts,
        "breadth_score": _score_breadth(nymo, namo, vix_ts),
    }


def _score_breadth(nymo: dict[str, Any], namo: dict[str, Any], vix_ts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score breadth for SOE integration.

    Returns {score, max, reasons, bias}
    """
    score = 0.0
    reasons: list[str] = []

    nymo_val = nymo.get("value", 0)
    nymo_regime = nymo.get("regime", "NEUTRAL")
    namo_val = namo.get("value", 0)

    if nymo_regime in ("NO_DATA", "INSUFFICIENT_DATA"):
        return {"score": 0, "max": 1.0, "reasons": ["Breadth: insufficient history (building...)"], "bias": "NEUTRAL"}

    # Bullish signals
    bullish = 0
    if nymo_val < -40:
        bullish += 1
        reasons.append(f"NYMO oversold {nymo_val:.0f}")
    if nymo.get("bullish_divergence"):
        bullish += 1
        reasons.append("NYMO bullish divergence")
    if nymo.get("turning_up") and nymo_val < 0:
        bullish += 1
        reasons.append("NYMO turning up")
    if namo_val < -40 or namo.get("turning_up"):
        bullish += 1
        reasons.append(f"NAMO confirms {namo_val:.0f}")

    if bullish >= 3:
        score = 1.0
    elif bullish >= 2:
        score = 0.5
    elif bullish >= 1:
        score = 0.25

    # Bearish signals
    if score == 0:
        bearish = 0
        if nymo_val > 80:
            bearish += 1
            reasons.append(f"NYMO overbought {nymo_val:.0f}")
        elif nymo_val > 120:
            bearish += 2  # Extreme overbought — strong warning
            reasons.append(f"NYMO extreme overbought {nymo_val:.0f}")
        if nymo.get("bearish_divergence"):
            bearish += 1
            reasons.append("NYMO bearish divergence")
        if nymo.get("turning_down") and nymo_val > 60:
            bearish += 1
            reasons.append("NYMO turning down from elevated")
        if bearish >= 2:
            score = -0.5
            reasons.append("Breadth deteriorating")

    # VIX term structure confirmation
    if vix_ts and vix_ts.get("structure") not in ("NO_DATA", None):
        structure = vix_ts["structure"]
        if structure == "BACKWARDATION" and score >= 0:
            score -= 0.25
            reasons.append(f"VIX backwardation ({vix_ts['ratio']}) — fear elevated")
        elif structure == "CONTANGO" and score <= 0:
            score += 0.25
            reasons.append(f"VIX contango ({vix_ts['ratio']}) — normal risk appetite")
        elif structure == "BACKWARDATION":
            reasons.append(f"VIX backwardation confirms bearish ({vix_ts['ratio']})")
        elif structure == "CONTANGO":
            reasons.append(f"VIX contango confirms bullish ({vix_ts['ratio']})")

    bias = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
    if not reasons:
        reasons.append(f"NYMO {nymo_val:.0f} neutral")

    return {
        "score": score,
        "max": 1.0,
        "reasons": reasons,
        "bias": bias,
        "nymo_value": nymo_val,
        "namo_value": namo_val,
        "vix_structure": vix_ts.get("structure") if vix_ts else None,
        "vix_ratio": vix_ts.get("ratio") if vix_ts else None,
    }


def score_for_direction(
    breadth: dict[str, Any],
    direction: str,
) -> tuple[float, str]:
    """Return (score_contribution, reason) for SOE scoring."""
    bs = breadth.get("breadth_score", {})
    bias = bs.get("bias", "NEUTRAL")
    raw_score = bs.get("score", 0)
    reasons = bs.get("reasons", [])
    reason_str = "; ".join(reasons) if reasons else "No breadth signal"

    if direction == "BULL":
        if bias == "BULLISH":
            return min(raw_score, 1.0), f"Breadth supports bounce ({reason_str})"
        elif bias == "BEARISH":
            return max(raw_score, -0.5), f"Breadth warns against longs ({reason_str})"
        return 0.0, f"Breadth neutral ({reason_str})"

    elif direction == "BEAR":
        if bias == "BEARISH":
            return min(abs(raw_score), 1.0), f"Breadth supports fade ({reason_str})"
        elif bias == "BULLISH":
            return 0.0, f"Breadth favors bounce, not fade ({reason_str})"
        return 0.0, f"Breadth neutral ({reason_str})"

    return 0.0, "Unknown direction"
