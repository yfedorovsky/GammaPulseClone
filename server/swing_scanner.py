"""Swing Watchlist Scanner — Separate from GEX/SOE signals.

5-source consensus (Mir RAG, ChatGPT, Perplexity, Grok, Gemini):
  - 3 continuous scoring factors: RS (40%), RVOL (30%), ADR% (20%)
  - Sector RS as soft multiplier (10%): 1.15x top 3, 1.0x mid, 0.85x bottom 3
  - Binary gates: MA alignment, IV/HV, spread, OI, earnings, regime
  - Hysteresis: enter Top 10, hold until rank 40
  - Two modes: "standard" (7-14 DTE) and "wifey" (14-30 DTE)
"""
from __future__ import annotations

import math
import time
from typing import Any

from .cache import cache
from .snapshots import get_daily_closes
from .tickers import TIER_1

# Mega-cap ADR exception: TIER_1 names with strong RTS can qualify at a
# lower ADR floor. MSFT-style quiet-then-rip runners typically have
# 14-day ADR around 1.2-1.8% in their basing phase, which fails the
# standard 2.5% gate. A TIER_1 name showing RTS >= 65 has already proven
# leadership; loosening ADR to 1.5% catches the setup without opening
# the floodgates to low-vol names broadly.
MEGACAP_ADR_FLOOR = 1.5
MEGACAP_RTS_REQ = 65

# ── Helpers ────────────────────────────────────────────────────────────

def _ema(closes: list[float], period: int) -> float:
    """Exponential Moving Average from list of closes (oldest first)."""
    if len(closes) < period:
        return sum(closes) / len(closes) if closes else 0
    mult = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for val in closes[period:]:
        ema = val * mult + ema * (1 - mult)
    return ema


def _sma(closes: list[float], period: int) -> float:
    """Simple Moving Average from last `period` values."""
    if len(closes) < period:
        return sum(closes) / len(closes) if closes else 0
    return sum(closes[-period:]) / period


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ── Sector ranking ─────────────────────────────────────────────────────

_sector_rank_cache: tuple[float, dict[str, int]] = (0, {})
_SECTOR_RANK_TTL = 3600  # 1 hour


async def _get_sector_ranks() -> dict[str, int]:
    """Rank 11 SPDR sectors by 1-month return. Returns {ETF: rank (1=best)}."""
    global _sector_rank_cache
    ts, cached = _sector_rank_cache
    if time.time() - ts < _SECTOR_RANK_TTL and cached:
        return cached

    from .basket import SECTOR_ETFS
    returns: list[tuple[str, float]] = []
    for etf in SECTOR_ETFS:
        closes = get_daily_closes(etf, 60)
        if len(closes) >= 22:
            ret_1m = (closes[-1] - closes[-22]) / closes[-22] * 100
            returns.append((etf, ret_1m))

    returns.sort(key=lambda x: x[1], reverse=True)
    ranks = {etf: i + 1 for i, (etf, _) in enumerate(returns)}

    _sector_rank_cache = (time.time(), ranks)
    return ranks


# ── ATM option quality check ───────────────────────────────────────────

def _check_atm_options(state: dict[str, Any], spot: float, min_dte: int = 7, max_dte: int = 21) -> dict[str, Any] | None:
    """Find the nearest ATM call in the 7-21 DTE range and check spread/OI."""
    import datetime
    raw = state.get("_raw_contracts", {})
    today = datetime.date.today()

    best = None
    for exp_str, contracts in raw.items():
        try:
            exp_date = datetime.date.fromisoformat(exp_str)
            dte = (exp_date - today).days
            if dte < min_dte or dte > max_dte:
                continue
        except ValueError:
            continue

        calls = [c for c in contracts if (c.get("option_type") or "").lower() == "call" and c.get("strike", 0) >= spot]
        if not calls:
            continue
        atm = min(calls, key=lambda c: abs(c["strike"] - spot))
        bid = atm.get("bid", 0) or 0
        ask = atm.get("ask", 0) or 0
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
        spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999
        oi = atm.get("open_interest", 0) or 0
        vol = atm.get("volume", 0) or 0

        if best is None or abs(dte - 10) < abs(best["dte"] - 10):
            best = {
                "strike": atm["strike"],
                "exp": exp_str,
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": round(spread_pct, 1),
                "oi": oi,
                "volume": vol,
            }

    return best


# ── Hysteresis ─────────────────────────────────────────────────────────

_prev_top: set[str] = set()  # tickers in the previous cycle's top-20


# ── Main scanner ───────────────────────────────────────────────────────

_swing_cache: tuple[float, list[dict], dict] = (0, [], {})
_SWING_CACHE_TTL = 300  # 5 minutes


async def compute_swing_watchlist(mode: str = "standard") -> tuple[list[dict], dict]:
    """Compute the swing watchlist.

    Returns (ranked_tickers, metadata) where metadata includes
    sector_ranks, spy_regime, and gate_stats.
    """
    global _prev_top, _swing_cache

    # Return cached result if fresh
    ts, cached_list, cached_meta = _swing_cache
    if time.time() - ts < _SWING_CACHE_TTL and cached_list:
        if cached_meta.get("mode") == mode:
            return cached_list, cached_meta

    snapshot = await cache.snapshot()
    if len(snapshot) < 10:
        return [], {"error": "Cache not populated yet"}

    # ── Mode-specific thresholds ───────────────────────────────────
    if mode == "wifey":
        rts_min = 65
        adr_min = 2.0
        ivhv_max = 1.5
        oi_min = 750
        earnings_days = 10
        opt_dte_min, opt_dte_max = 14, 45
        # Wifey weights: more RS, less RVOL
        w_rs, w_rvol, w_adr = 0.50, 0.15, 0.15
    else:
        rts_min = 60
        adr_min = 2.5
        ivhv_max = 1.2
        oi_min = 500
        earnings_days = 5
        opt_dte_min, opt_dte_max = 7, 21
        # Standard weights (Gemini-recommended)
        w_rs, w_rvol, w_adr = 0.40, 0.30, 0.20

    # ── SPY regime gate ────────────────────────────────────────────
    spy_closes = get_daily_closes("SPY", 60)
    spy_ema21 = _ema(spy_closes, 21) if len(spy_closes) >= 21 else 0
    spy_spot = spy_closes[-1] if spy_closes else 0
    spy_bullish = spy_spot > spy_ema21 if spy_ema21 else True
    spy_regime = "BULL" if spy_bullish else "BEAR"

    if not spy_bullish:
        return [], {
            "mode": mode,
            "spy_regime": spy_regime,
            "spy_spot": round(spy_spot, 2),
            "spy_ema21": round(spy_ema21, 2),
            "message": "SPY below 21 EMA — long swing scanner paused",
        }

    # ── Earnings blackout set ──────────────────────────────────────
    blackout_set: set[str] = set()
    try:
        from .signals import _fetch_earnings_blackout, _earnings_blackout_cache
        cache_ts, cached_bo = _earnings_blackout_cache
        if time.time() - cache_ts < 3600:
            blackout_set = cached_bo
        else:
            blackout_set = await _fetch_earnings_blackout()
    except Exception:
        pass

    # ── Sector ranks ───────────────────────────────────────────────
    sector_ranks = await _get_sector_ranks()

    # ── Mir basket tickers ─────────────────────────────────────────
    mir_tickers: set[str] = set()
    try:
        from .industry import INDUSTRY_GROUPS
        for group_name, tickers_list in INDUSTRY_GROUPS.items():
            mir_tickers.update(tickers_list)
    except Exception:
        pass

    # ── Scan all tickers ───────────────────────────────────────────
    results: list[dict[str, Any]] = []
    gate_stats = {"total": 0, "passed": 0, "failed": {}}

    def _fail(reason: str):
        gate_stats["failed"][reason] = gate_stats["failed"].get(reason, 0) + 1

    for ticker, state in snapshot.items():
        gate_stats["total"] += 1
        spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot or spot < 5:
            _fail("no_spot")
            continue

        # ── Gate 1: RTS ────────────────────────────────────────────
        rts_data = state.get("_rts")
        if not rts_data or not isinstance(rts_data, dict):
            _fail("no_rts")
            continue
        rts_score = rts_data.get("score", 0)
        if rts_score < rts_min:
            _fail("rts_low")
            continue

        # ── Gate 2: MA alignment ───────────────────────────────────
        closes = get_daily_closes(ticker, 100)
        if len(closes) < 50:
            _fail("insufficient_history")
            continue

        ema21 = _ema(closes, 21)
        sma50 = _sma(closes, 50)
        current = closes[-1]

        if current <= ema21 or current <= sma50:
            _fail("below_ma")
            continue
        if ema21 < sma50:
            _fail("ma_misaligned")
            continue

        # SMA50 slope: 5-day rate of change
        if len(closes) >= 55:
            sma50_5ago = _sma(closes[:-5], 50)
            sma50_slope = (sma50 - sma50_5ago) / sma50_5ago if sma50_5ago else 0
            if sma50_slope <= 0:
                _fail("sma50_falling")
                continue
        else:
            sma50_slope = 0

        # ── Gate 3: ADR% ──────────────────────────────────────────
        # Prefer ATR from RTS if available (needs high/low data).
        # Fallback: estimate from close-to-close daily returns (σ × √(π/2) ≈ ATR).
        atr = rts_data.get("atr")
        if atr and spot:
            adr_pct = atr / spot * 100
        elif len(closes) >= 15:
            # Estimate ADR from daily close-to-close absolute returns
            abs_returns = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100
                           for i in range(-14, 0) if closes[i-1] > 0]
            adr_pct = sum(abs_returns) / len(abs_returns) if abs_returns else 0
        else:
            adr_pct = 0

        # Mega-cap exception: TIER_1 name with RTS >= 65 qualifies at 1.5% ADR.
        # Rationale: MSFT/AAPL/GOOGL-style runners have low absolute ADR in
        # their basing phase but strong options markets + meaningful P&L on
        # modest moves. RTS gate prevents sleepy megas from slipping through.
        effective_adr_min = adr_min
        if ticker in TIER_1 and rts_score >= MEGACAP_RTS_REQ:
            effective_adr_min = min(adr_min, MEGACAP_ADR_FLOOR)

        if adr_pct < effective_adr_min:
            _fail("adr_low")
            continue

        # ── Gate 4: IV/HV ─────────────────────────────────────────
        ivhv = state.get("_ivhv_ratio")
        if ivhv is not None and ivhv > ivhv_max:
            _fail("ivhv_expensive")
            continue

        # ── Gate 5: Options quality ────────────────────────────────
        atm_opt = _check_atm_options(state, spot, opt_dte_min, opt_dte_max)
        if not atm_opt:
            _fail("no_options")
            continue
        if atm_opt["spread_pct"] > 10:
            _fail("spread_wide")
            continue
        if atm_opt["oi"] < oi_min:
            _fail("oi_low")
            continue

        # ── Gate 6: Earnings ───────────────────────────────────────
        if ticker in blackout_set:
            _fail("earnings_soon")
            continue

        # ── Gate 7: Volume ─────────────────────────────────────────
        # Use volume from the latest raw contracts or quote data
        avg_vol = state.get("_avg_volume", 0)
        # Fallback: skip volume gate if data not available yet
        if avg_vol and avg_vol < 1_000_000:
            _fail("volume_low")
            continue

        # ═══ PASSED ALL GATES ═══════════════════════════════════════
        gate_stats["passed"] += 1

        # ── Continuous scoring ─────────────────────────────────────
        rs_norm = rts_score / 100.0  # 0-1

        # RVOL: today's volume vs average (need avg_vol from worker)
        today_vol = state.get("_today_volume", 0)
        if avg_vol and today_vol:
            rvol = today_vol / avg_vol
            rvol_norm = _clamp(rvol / 3.0, 0, 1)  # peaks at 3x
        else:
            rvol = 0
            rvol_norm = 0.5  # neutral if no volume data

        # ADR norm: 2.5% = 0, 5.0% = 1 (Gemini optimal range)
        adr_norm = _clamp((adr_pct - adr_min) / 2.5, 0, 1)

        # Base score
        base_score = w_rs * rs_norm + w_rvol * rvol_norm + w_adr * adr_norm

        # Sector multiplier (soft, not hard gate)
        from .basket import STOCK_SECTORS
        sector_etf = STOCK_SECTORS.get(ticker)
        sector_rank = sector_ranks.get(sector_etf, 6) if sector_etf else 6
        if sector_rank <= 3:
            sector_mult = 1.15
        elif sector_rank >= 9:
            sector_mult = 0.85
        else:
            sector_mult = 1.0

        swing_score = round(base_score * sector_mult * 100, 1)

        # ── Tags ───────────────────────────────────────────────────
        tags: list[str] = []
        if rts_score >= 70:
            tags.append("LEADER")
        if sector_rank <= 3:
            tags.append("TOP_SECTOR")
        if ticker in mir_tickers:
            tags.append("MIR_BASKET")

        # Entry quality tags
        ema21_dist = (current - ema21) / ema21 * 100 if ema21 else 0
        if ema21_dist > 8:
            tags.append("EXTENDED")
        elif ema21_dist < 2:
            tags.append("FIRST_PULLBACK")

        high_20d = max(closes[-20:]) if len(closes) >= 20 else current
        dist_to_high = (high_20d - current) / high_20d * 100 if high_20d else 0
        if dist_to_high < 3:
            tags.append("NEAR_BREAKOUT")

        ivp = state.get("_ivp")
        if ivp is not None and ivp < 30:
            tags.append("CHEAP_IV")

        # SMA100 for extra context
        sma100 = _sma(closes, 100) if len(closes) >= 100 else 0

        results.append({
            "ticker": ticker,
            "swing_score": swing_score,
            "spot": round(spot, 2),
            "rts_score": rts_score,
            "rts_grade": rts_data.get("grade", ""),
            "ema21": round(ema21, 2),
            "sma50": round(sma50, 2),
            "sma100": round(sma100, 2),
            "ema21_dist_pct": round(ema21_dist, 1),
            "sma50_slope_pct": round(sma50_slope * 100, 2),
            "adr_pct": round(adr_pct, 1),
            "rvol": round(rvol, 2) if rvol else None,
            "avg_volume": avg_vol,
            "ivp": ivp,
            "ivhv": ivhv,
            "sector": sector_etf,
            "sector_rank": sector_rank,
            "sector_mult": sector_mult,
            "option": atm_opt,
            "tags": tags,
            "signal": state.get("signal", ""),
            "regime": state.get("regime", ""),
            "king": state.get("king"),
            "floor": state.get("floor"),
            "high_20d": round(high_20d, 2),
            "dist_to_high_pct": round(dist_to_high, 1),
            "extension": rts_data.get("extension", ""),
        })

    # ── Sort by SwingScore descending ──────────────────────────────
    results.sort(key=lambda x: x["swing_score"], reverse=True)

    # ── Hysteresis (Gemini recommendation) ─────────────────────────
    # New ticker enters only if Top 10. Existing stays until rank > 40.
    current_tickers = {r["ticker"] for r in results[:10]}  # Top 10 new entrants
    retained = {r["ticker"] for i, r in enumerate(results) if r["ticker"] in _prev_top and i < 40}
    display_set = current_tickers | retained
    # Mark which are new vs retained
    for r in results:
        r["_new_entry"] = r["ticker"] in current_tickers and r["ticker"] not in _prev_top
        r["_in_watchlist"] = r["ticker"] in display_set
    _prev_top = display_set

    # ── Metadata ───────────────────────────────────────────────────
    meta = {
        "mode": mode,
        "spy_regime": spy_regime,
        "spy_spot": round(spy_spot, 2),
        "spy_ema21": round(spy_ema21, 2),
        "sector_ranks": {etf: rank for etf, rank in sorted(sector_ranks.items(), key=lambda x: x[1])},
        "gate_stats": gate_stats,
        "total_passing": len(results),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _swing_cache = (time.time(), results, meta)
    return results, meta
