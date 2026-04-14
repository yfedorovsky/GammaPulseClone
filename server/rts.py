"""RTS (Relative Trend Strength) — Vehicle selection layer.

Ranks individual stocks by relative momentum and trend quality to
answer: "Which names are the best vehicles for expressing a trade?"

Architecture role (from unified architecture note):
  - GEX tells you WHERE dealer structure may matter
  - NYMO/NAMO tells you WHETHER breadth supports it
  - RTS tells you WHICH stocks are the best vehicles
  - This is Layer 3 in the decision engine

Scoring (0-100 composite):
  Relative Strength block (50%):
    - 20D return vs SPY
    - 60D return vs SPY
    - Percentile rank within scanned universe

  Trend Strength block (50%):
    - Price above 20/50/100 MA
    - MA alignment (20 > 50 > 100 = bullish)
    - 20MA slope (positive = uptrend)

  Extension flag (separate, NOT in score):
    - NORMAL: < 2 ATR above 20MA
    - EXTENDED: 2-3 ATR above 20MA
    - OVEREXTENDED: > 3 ATR above 20MA
"""
from __future__ import annotations

import math
import time
from typing import Any

from .config import get_settings

# Cache RTS scores (refresh every 30 min — based on daily data)
_rts_cache: dict[str, tuple[float, dict[str, Any]]] = {}
RTS_CACHE_TTL = 1800  # 30 minutes

# SPY benchmark returns (cached separately)
_spy_returns: tuple[float, dict[str, float]] = (0, {})


def _compute_returns(closes: list[float]) -> dict[str, float]:
    """Compute period returns from daily close prices."""
    if len(closes) < 2:
        return {}
    results: dict[str, float] = {}
    current = closes[-1]

    for period, label in [(5, "5d"), (20, "20d"), (60, "60d")]:
        if len(closes) > period:
            prev = closes[-(period + 1)]
            if prev > 0:
                results[label] = (current - prev) / prev
    return results


def _compute_mas(closes: list[float]) -> dict[str, float | None]:
    """Compute moving averages."""
    results: dict[str, float | None] = {}
    for period, label in [(20, "ma20"), (50, "ma50"), (100, "ma100")]:
        if len(closes) >= period:
            results[label] = sum(closes[-period:]) / period
        else:
            results[label] = None
    return results


def _compute_atr(highs: list[float], lows: list[float], closes: list[float],
                 period: int = 14) -> float | None:
    """Compute Average True Range."""
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(-period, 0):
        h = highs[i] if i < len(highs) else closes[i]
        l = lows[i] if i < len(lows) else closes[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def compute_rts(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    spy_returns: dict[str, float] | None = None,
    universe_returns_20d: list[float] | None = None,
) -> dict[str, Any]:
    """Compute RTS score for a single ticker.

    Args:
        closes: Daily close prices (oldest first, at least 100 days ideal)
        highs: Daily highs (for ATR, optional)
        lows: Daily lows (for ATR, optional)
        spy_returns: SPY benchmark returns {5d, 20d, 60d}
        universe_returns_20d: All tickers' 20d returns for percentile ranking

    Returns dict with score (0-100), components, and extension flag.
    """
    if len(closes) < 20:
        return {"score": 0, "grade": "N/A", "extension": "UNKNOWN",
                "reason": "Insufficient price history"}

    current = closes[-1]
    returns = _compute_returns(closes)
    mas = _compute_mas(closes)

    # ── Relative Strength block (0-50) ────────────────────────────
    rs_score = 0.0
    rs_details: list[str] = []

    # 20D return vs SPY (0-20)
    ret_20d = returns.get("20d", 0)
    spy_20d = (spy_returns or {}).get("20d", 0)
    excess_20d = ret_20d - spy_20d

    if excess_20d > 0.05:
        rs_score += 20
    elif excess_20d > 0.02:
        rs_score += 15
    elif excess_20d > 0:
        rs_score += 10
    elif excess_20d > -0.02:
        rs_score += 5
    rs_details.append(f"20d: {ret_20d:+.1%} vs SPY {spy_20d:+.1%}")

    # 60D return vs SPY (0-20)
    ret_60d = returns.get("60d", 0)
    spy_60d = (spy_returns or {}).get("60d", 0)
    excess_60d = ret_60d - spy_60d

    if excess_60d > 0.10:
        rs_score += 20
    elif excess_60d > 0.05:
        rs_score += 15
    elif excess_60d > 0:
        rs_score += 10
    elif excess_60d > -0.05:
        rs_score += 5
    rs_details.append(f"60d: {ret_60d:+.1%} vs SPY {spy_60d:+.1%}")

    # Percentile rank within universe (0-10)
    if universe_returns_20d and len(universe_returns_20d) >= 10:
        lower = sum(1 for r in universe_returns_20d if r < ret_20d)
        pct_rank = lower / len(universe_returns_20d) * 100
        if pct_rank >= 90:
            rs_score += 10
        elif pct_rank >= 70:
            rs_score += 7
        elif pct_rank >= 50:
            rs_score += 4
        rs_details.append(f"Rank: {pct_rank:.0f}th percentile")

    # ── Trend Strength block (0-50) ───────────────────────────────
    ts_score = 0.0
    ts_details: list[str] = []

    ma20 = mas.get("ma20")
    ma50 = mas.get("ma50")
    ma100 = mas.get("ma100")

    # Price above MAs (0-15)
    above_count = 0
    if ma20 and current > ma20:
        above_count += 1
    if ma50 and current > ma50:
        above_count += 1
    if ma100 and current > ma100:
        above_count += 1
    ts_score += above_count * 5
    ts_details.append(f"Above {above_count}/3 MAs")

    # MA alignment — bullish: 20 > 50 > 100 (0-15)
    if ma20 and ma50 and ma100:
        if ma20 > ma50 > ma100:
            ts_score += 15
            ts_details.append("MA alignment: bullish (20>50>100)")
        elif ma20 > ma50:
            ts_score += 10
            ts_details.append("MA alignment: partial (20>50)")
        elif ma50 > ma100:
            ts_score += 5
            ts_details.append("MA alignment: base (50>100)")
        else:
            ts_details.append("MA alignment: bearish")

    # 20MA slope (0-10)
    if len(closes) >= 25:
        ma20_5ago = sum(closes[-25:-5]) / 20
        if ma20 and ma20_5ago:
            slope_pct = (ma20 - ma20_5ago) / ma20_5ago
            if slope_pct > 0.02:
                ts_score += 10
                ts_details.append(f"20MA slope: +{slope_pct:.1%}")
            elif slope_pct > 0:
                ts_score += 5
                ts_details.append(f"20MA slope: +{slope_pct:.1%} (flat)")
            else:
                ts_details.append(f"20MA slope: {slope_pct:.1%} (declining)")

    # 50MA slope (0-10)
    if len(closes) >= 55:
        ma50_5ago = sum(closes[-55:-5]) / 50
        if ma50 and ma50_5ago:
            slope_pct = (ma50 - ma50_5ago) / ma50_5ago
            if slope_pct > 0.02:
                ts_score += 10
            elif slope_pct > 0:
                ts_score += 5

    # ── Composite score ──────────────────────────────────────────
    total = round(rs_score + ts_score)

    # Grade
    if total >= 80:
        grade = "A+"
    elif total >= 70:
        grade = "A"
    elif total >= 55:
        grade = "B+"
    elif total >= 40:
        grade = "B"
    elif total >= 25:
        grade = "C"
    else:
        grade = "D"

    # ── Extension flag (SEPARATE from score) ─────────────────────
    extension = "NORMAL"
    atr = None
    if highs and lows and len(highs) >= 14:
        atr = _compute_atr(highs, lows, closes, period=14)
    if atr and ma20 and atr > 0:
        distance_from_ma20 = (current - ma20) / atr
        if distance_from_ma20 > 3:
            extension = "OVEREXTENDED"
        elif distance_from_ma20 > 2:
            extension = "EXTENDED"
        elif distance_from_ma20 < -2:
            extension = "OVERSOLD"

    return {
        "score": total,
        "grade": grade,
        "extension": extension,
        "rs_score": round(rs_score),
        "ts_score": round(ts_score),
        "rs_details": rs_details,
        "ts_details": ts_details,
        "returns": {k: round(v * 100, 1) for k, v in returns.items()},
        "mas": {k: round(v, 2) if v else None for k, v in mas.items()},
        "atr": round(atr, 2) if atr else None,
        "current": current,
    }


async def compute_rts_universe(
    tradier_client: Any,
    tickers: list[str],
) -> dict[str, dict[str, Any]]:
    """Compute RTS scores for a list of tickers.

    Fetches daily history from Tradier, computes SPY benchmark,
    then scores each ticker.

    Returns {ticker: rts_result, ...}
    """
    import asyncio

    # Check cache first
    now = time.time()
    cached_all = True
    for t in tickers:
        if t not in _rts_cache or (now - _rts_cache[t][0]) > RTS_CACHE_TTL:
            cached_all = False
            break
    if cached_all and tickers:
        return {t: _rts_cache[t][1] for t in tickers if t in _rts_cache}

    # Fetch SPY benchmark first
    global _spy_returns
    if now - _spy_returns[0] > RTS_CACHE_TTL:
        spy_bars = await tradier_client.history("SPY", interval="daily")
        if spy_bars:
            spy_closes = [b["close"] for b in spy_bars]
            _spy_returns = (now, _compute_returns(spy_closes))

    spy_ret = _spy_returns[1]

    # Fetch all tickers (batch, with concurrency limit)
    sem = asyncio.Semaphore(6)
    results: dict[str, dict[str, Any]] = {}

    async def fetch_one(ticker: str) -> None:
        # Use cache if fresh
        if ticker in _rts_cache and (now - _rts_cache[ticker][0]) < RTS_CACHE_TTL:
            results[ticker] = _rts_cache[ticker][1]
            return

        async with sem:
            try:
                bars = await tradier_client.history(ticker, interval="daily")
                if not bars or len(bars) < 20:
                    return
                closes = [b["close"] for b in bars]
                highs = [b.get("high", b["close"]) for b in bars]
                lows = [b.get("low", b["close"]) for b in bars]

                rts = compute_rts(closes, highs, lows, spy_ret)
                rts["ticker"] = ticker
                results[ticker] = rts
                _rts_cache[ticker] = (now, rts)
            except Exception:
                pass

    await asyncio.gather(*(fetch_one(t) for t in tickers))

    # Compute universe percentile ranks (post-hoc)
    all_20d = [r.get("returns", {}).get("20d", 0) for r in results.values()]
    if len(all_20d) >= 10:
        for ticker, rts in results.items():
            ret = rts.get("returns", {}).get("20d", 0)
            lower = sum(1 for r in all_20d if r < ret)
            rts["universe_rank"] = round(lower / len(all_20d) * 100)

    return results


def rank_tickers(
    rts_results: dict[str, dict[str, Any]],
    direction: str = "BULL",
) -> list[dict[str, Any]]:
    """Rank tickers by RTS score, optionally filtered by direction.

    For BULL: rank by score descending (leaders first)
    For BEAR: rank by score ascending (laggards first, potential puts)
    """
    items = list(rts_results.values())

    if direction == "BULL":
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
    else:
        items.sort(key=lambda x: x.get("score", 0))

    return items
