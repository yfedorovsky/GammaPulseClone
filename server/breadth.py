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
from .market_calendar import is_market_holiday

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
    if is_market_holiday(today):
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
    vix_regime = await get_vix_intraday_regime()
    oil_regime = await get_oil_intraday_regime()

    return {
        "nymo": nymo,
        "namo": namo,
        "vix_term_structure": vix_ts,
        "vix_intraday_regime": vix_regime,
        "oil_intraday_regime": oil_regime,
        "breadth_score": _score_breadth(nymo, namo, vix_ts),
    }


# ── VIX Intraday Regime Detector ──────────────────────────────────────
# Backtest (scripts/backtest_vix_regime.py, 365d, 251 days):
#   VIX_BULL_COMPRESS:  80.3% SPY OC win rate (VIX open<20, closes -3%+)
#   VIX_ELEVATED_COMP:  87.5% WR (VIX 20-25 declining)
#   VIX_LOW_RISING:     13.2% WR — avoid longs
#   VIX_SPIKE:          20.0% WR — fade immediately
# Baseline win rate across all days: 43.2%

_VIX_REGIME_CACHE: tuple[float, dict[str, Any]] = (0, {})
_VIX_REGIME_CACHE_TTL = 120  # 2 min — matches worker cycle
_VIX_DAILY_OPEN_CACHE: dict[str, float] = {}  # date-str -> VIX open


async def get_vix_intraday_regime() -> dict[str, Any]:
    """Classify today's VIX regime using today's open vs current spot.

    Returns:
      {
        regime: "VIX_BULL_COMPRESS" | "VIX_LOW_FLAT" | "VIX_LOW_RISING" |
                "VIX_ELEVATED_COMP" | "VIX_ELEVATED_FLAT" | "VIX_HIGH" | "VIX_SPIKE",
        vix_open: float,
        vix_current: float,
        change_pct: float,
        bull_bias: bool,   # True if regime favors SPY longs
        win_rate_expectation: float,  # historical backtest win rate
        label: str,
      }
    """
    global _VIX_REGIME_CACHE, _VIX_DAILY_OPEN_CACHE
    now_ts = time.time()
    cached_ts, cached = _VIX_REGIME_CACHE
    if now_ts - cached_ts < _VIX_REGIME_CACHE_TTL and cached:
        return cached

    import datetime as _dt
    today = _dt.date.today().isoformat()

    try:
        from .tradier import TradierClient
        t = TradierClient()

        # Get today's VIX open (daily bar) — cache for the day
        if today not in _VIX_DAILY_OPEN_CACHE:
            try:
                bars = await t.history("VIX", interval="daily", start=today, end=today)
                if bars:
                    _VIX_DAILY_OPEN_CACHE[today] = bars[0].get("open", 0)
            except Exception:
                pass

        # Get current VIX spot
        quotes = await t.quotes(["VIX"])
        await t.close()
        vix_current = quotes.get("VIX", 0)
    except Exception:
        _VIX_REGIME_CACHE = (now_ts, {"regime": "UNKNOWN", "error": "quote_fetch_failed"})
        return _VIX_REGIME_CACHE[1]

    vix_open = _VIX_DAILY_OPEN_CACHE.get(today, 0)
    if not vix_open or not vix_current:
        result = {"regime": "UNKNOWN", "vix_open": vix_open, "vix_current": vix_current}
        _VIX_REGIME_CACHE = (now_ts, result)
        return result

    change_pct = (vix_current - vix_open) / vix_open * 100

    # Classification (matches scripts/backtest_vix_regime.py)
    if vix_open < 20:
        if change_pct <= -3:
            regime = "VIX_BULL_COMPRESS"
            bull_bias = True
            wr = 80.3
            label = "VIX bull compress — 80% SPY bull day"
        elif change_pct >= 3:
            regime = "VIX_LOW_RISING"
            bull_bias = False
            wr = 13.2
            label = "VIX rising from low — avoid longs"
        else:
            regime = "VIX_LOW_FLAT"
            bull_bias = False  # neutral, 46% WR
            wr = 46.2
            label = "VIX flat — neutral tape"
    elif vix_open < 25:
        if change_pct <= -3:
            regime = "VIX_ELEVATED_COMP"
            bull_bias = True
            wr = 87.5
            label = "VIX normalizing from stress — strongest bull signal"
        else:
            regime = "VIX_ELEVATED_FLAT"
            bull_bias = False
            wr = 29.2
            label = "VIX stuck elevated — choppy/bearish"
    else:
        if change_pct >= 3:
            regime = "VIX_SPIKE"
            bull_bias = False
            wr = 20.0
            label = "VIX spiking — risk-off, fade longs"
        else:
            regime = "VIX_HIGH"
            bull_bias = False
            wr = 57.9
            label = "VIX high — wide ranges, selective longs"

    result = {
        "regime": regime,
        "vix_open": round(vix_open, 2),
        "vix_current": round(vix_current, 2),
        "change_pct": round(change_pct, 2),
        "bull_bias": bull_bias,
        "win_rate_expectation": wr,
        "label": label,
    }
    _VIX_REGIME_CACHE = (now_ts, result)
    return result


# ── Oil Intraday Regime Detector ──────────────────────────────────────
# 4-LLM consensus (ChatGPT + Grok + Perplexity + Gemini, Apr 16 2026):
# Backtest (scripts/backtest_oil_regime.py, 730d, 502 days):
#   OIL_UP_MILD (USO +2-4%): 42.3% WR, 26 obs — DEPLOYABLE as soft gate
#   OIL_SPIKE (USO +4%+):    0% WR (n=2-3), telegram alert only
#   OIL_CRASH (USO -4%+):   100% WR (n=3-4), deflationary relief
#   Baseline: 52.9% WR
#
# Kilian-Park (2009 AER): supply shocks → equity negative,
#   demand shocks → equity positive. Raw USO threshold conflates both.
#
# Disambiguation via SPY + XLE co-movement (validated by all 4 reviewers):
#   USO↑ + SPY↓ + XLE↑  = OIL_SPIKE_RISKOFF (supply shock) ← target
#   USO↑ + SPY↑ + XLE↑  = OIL_DEMAND_RELIEF (Liberation Day pattern)
#   USO↑ + SPY↓ + XLE↓  = STAGFLATION_FEAR (cost-push inflation)
#   USO↓ + SPY↑ + XLE↓  = OIL_CRASH_RELIEF (deflationary tailwind)

_OIL_REGIME_CACHE: tuple[float, dict[str, Any]] = (0, {})
_OIL_REGIME_CACHE_TTL = 120  # 2 min
_OIL_DAILY_OPEN_CACHE: dict[str, dict[str, float]] = {}  # date -> {USO, SPY, XLE, BNO}


async def get_oil_intraday_regime() -> dict[str, Any]:
    """Classify today's oil regime with SPY + XLE + BNO co-movement filter.

    Returns:
      {
        regime: "OIL_SPIKE_RISKOFF" | "OIL_DEMAND_RELIEF" | "OIL_UP_MILD" |
                "OIL_CALM" | "OIL_DOWN_MILD" | "OIL_CRASH_RELIEF" |
                "STAGFLATION_FEAR" | "UNKNOWN",
        uso_open, uso_current, uso_change_pct,
        spy_change_pct, xle_change_pct, bno_change_pct,
        bull_bias: bool,           # True if regime favors SPY longs
        risk_off: bool,             # True if high-confidence risk-off
        runner_score_modifier: int, # score adjustment for runner tracker
        win_rate_expectation: float,
        label: str,
      }
    """
    global _OIL_REGIME_CACHE, _OIL_DAILY_OPEN_CACHE
    now_ts = time.time()
    cached_ts, cached = _OIL_REGIME_CACHE
    if now_ts - cached_ts < _OIL_REGIME_CACHE_TTL and cached:
        return cached

    import datetime as _dt
    today = _dt.date.today().isoformat()

    try:
        from .tradier import TradierClient
        t = TradierClient()

        # Get today's opens (daily bars) — cache for the day
        if today not in _OIL_DAILY_OPEN_CACHE:
            opens: dict[str, float] = {}
            for sym in ("USO", "SPY", "XLE", "BNO"):
                try:
                    bars = await t.history(sym, interval="daily", start=today, end=today)
                    if bars:
                        opens[sym] = bars[0].get("open", 0) or 0
                except Exception:
                    pass
            if opens:
                _OIL_DAILY_OPEN_CACHE[today] = opens

        # Get current spots
        quotes = await t.quotes(["USO", "SPY", "XLE", "BNO"])
        await t.close()
    except Exception:
        _OIL_REGIME_CACHE = (now_ts, {"regime": "UNKNOWN", "error": "quote_fetch_failed"})
        return _OIL_REGIME_CACHE[1]

    opens = _OIL_DAILY_OPEN_CACHE.get(today, {})
    uso_open = opens.get("USO", 0)
    spy_open = opens.get("SPY", 0)
    xle_open = opens.get("XLE", 0)
    bno_open = opens.get("BNO", 0)
    uso_current = quotes.get("USO", 0)
    spy_current = quotes.get("SPY", 0)
    xle_current = quotes.get("XLE", 0)
    bno_current = quotes.get("BNO", 0)

    if not uso_open or not uso_current:
        result = {
            "regime": "UNKNOWN",
            "uso_open": uso_open, "uso_current": uso_current,
            "error": "missing USO data",
        }
        _OIL_REGIME_CACHE = (now_ts, result)
        return result

    def pct(o, c):
        return (c - o) / o * 100 if o else 0

    uso_pct = pct(uso_open, uso_current)
    spy_pct = pct(spy_open, spy_current)
    xle_pct = pct(xle_open, xle_current)
    bno_pct = pct(bno_open, bno_current)

    # 4-pattern classification — requires SPY + XLE co-movement for risk-off
    if uso_pct >= 4.0:
        if spy_pct < 0 and xle_pct >= 0:
            # Classic supply shock: oil up, equities down, energy sector bid
            regime = "OIL_SPIKE_RISKOFF"
            bull_bias = False
            risk_off = True
            mod = -2  # runner tracker score penalty
            wr = 0.0  # n=2-3, statistically meaningless but directional
            label = "Oil spike + SPY red → geopolitical risk-off"
        elif spy_pct > 0 and xle_pct > 0:
            # Aggregate demand / relief rally — Liberation Day pattern
            regime = "OIL_DEMAND_RELIEF"
            bull_bias = True
            risk_off = False
            mod = 0  # don't penalize longs on demand-repricing days
            wr = 100.0  # Apr 9 2025 single obs, ignore for stats
            label = "Oil spike + SPY green → demand repricing, NOT risk-off"
        elif spy_pct < 0 and xle_pct < 0:
            regime = "STAGFLATION_FEAR"
            bull_bias = False
            risk_off = True
            mod = -1
            wr = 30.0  # no clean backtest; conservative estimate
            label = "Oil spike + everything red → cost-push stagflation fear"
        else:
            regime = "OIL_SPIKE"
            bull_bias = False
            risk_off = False
            mod = 0  # ambiguous, don't act
            wr = 33.3
            label = "Oil spike, mixed equity signal — ambiguous"
    elif uso_pct >= 2.0:
        regime = "OIL_UP_MILD"
        bull_bias = False
        risk_off = False
        mod = -1  # soft caution — n=26 sample, directionally suggestive
        wr = 42.3
        label = "Oil elevated → caution on longs"
    elif uso_pct <= -4.0:
        if spy_pct > 0 and xle_pct <= 0:
            # Supply glut / deflationary tailwind
            regime = "OIL_CRASH_RELIEF"
            bull_bias = True
            risk_off = False
            mod = 1  # bullish tailwind
            wr = 100.0  # n=3-4, small sample
            label = "Oil crash + SPY green → deflationary relief rally"
        else:
            regime = "OIL_CRASH"
            bull_bias = False
            risk_off = False
            mod = 0
            wr = 50.0
            label = "Oil crash — demand destruction signal, mixed equity"
    elif uso_pct <= -2.0:
        regime = "OIL_DOWN_MILD"
        bull_bias = True  # slightly
        risk_off = False
        mod = 0  # no action, just logging
        wr = 56.5
        label = "Oil mildly down — slight tailwind"
    else:
        regime = "OIL_CALM"
        bull_bias = False
        risk_off = False
        mod = 0
        wr = 52.9
        label = "Oil calm — baseline"

    result = {
        "regime": regime,
        "uso_open": round(uso_open, 2),
        "uso_current": round(uso_current, 2),
        "uso_change_pct": round(uso_pct, 2),
        "spy_change_pct": round(spy_pct, 2),
        "xle_change_pct": round(xle_pct, 2),
        "bno_change_pct": round(bno_pct, 2),
        "bull_bias": bull_bias,
        "risk_off": risk_off,
        "runner_score_modifier": mod,
        "win_rate_expectation": wr,
        "label": label,
    }
    _OIL_REGIME_CACHE = (now_ts, result)
    return result


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
