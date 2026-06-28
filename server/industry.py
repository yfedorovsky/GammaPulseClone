"""Industry Leadership Layer — Group strength on top of RTS.

Answers: "Is this stock strong inside a strong group?"

Architecture role (Layer 4):
  - GEX = where the trade might work
  - NYMO/NAMO = whether breadth supports it
  - RTS = whether the stock itself is strong
  - Industry = whether the stock is in a strong group

Computes per-industry:
  - industry_score (0-100)
  - industry_state: LEADING / EMERGING / WEAKENING / BROKEN
  - pct_above_20ma, top_tier_count, median_rs
  - per-stock: rank_in_group, industry_tailwind

Data source: RTS scores from scanner cache (no additional API calls).
"""
from __future__ import annotations

import time
from typing import Any

# Industry group definitions (matches scanner theme view)
INDUSTRY_GROUPS = {
    "Index ETFs": ["SPY", "QQQ", "IWM", "DIA", "SMH", "SOXX", "XBI", "IBIT", "UVXY"],
    "Mag 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "Semis / Chips": ["AMD", "AVGO", "INTC", "MU", "MRVL", "TSM", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "ASML", "ARM", "SMCI"],
    "Photonics / Fiber": ["LITE", "COHR", "AAOI", "GLW", "CIEN", "AXTI"],
    "Semi Equipment": ["AEHR", "TER", "AMAT", "LRCX", "KLAC"],
    "Space": ["RKLB", "ASTS"],
    "AI / DC Infra": ["ANET", "VRT", "NET", "SNOW", "PLTR", "CRWD", "PANW", "ZS", "NBIS", "OKLO", "IREN"],
    "Crypto / Fintech": ["COIN", "MSTR", "MARA", "RIOT", "XYZ", "HOOD", "SOFI"],
    "Consumer": ["COST", "WMT", "TGT", "NKE", "SBUX", "MCD", "DIS"],
    "Space / Defense": ["BA", "LMT", "RTX", "NOC", "GD"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "OXY"],
    # XLV top-10 holdings + MRNA (biotech sleeve) — tracks the full healthcare
    # complex for the #123 rotation breadth signal, not just the mega-cap 3.
    "Biotech / Health": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "AMGN", "DHR", "MRNA"],
    "Financials": ["JPM", "BAC", "GS", "MS", "V", "MA"],
}

# Reverse lookup: ticker -> industry
_ticker_to_industry: dict[str, str] = {}
for _ind, _tickers in INDUSTRY_GROUPS.items():
    for _t in _tickers:
        _ticker_to_industry[_t] = _ind

# Cache
_industry_cache: tuple[float, dict[str, dict[str, Any]]] = (0, {})
INDUSTRY_CACHE_TTL = 300  # 5 minutes


def get_ticker_industry(ticker: str) -> str | None:
    return _ticker_to_industry.get(ticker)


def compute_industry_scores(scanner_snapshot: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute industry-level scores from the scanner cache snapshot.

    Returns {industry_name: {score, state, members, ...}}
    """
    global _industry_cache
    now = time.time()
    if now - _industry_cache[0] < INDUSTRY_CACHE_TTL and _industry_cache[1]:
        return _industry_cache[1]

    results: dict[str, dict[str, Any]] = {}

    for industry, tickers in INDUSTRY_GROUPS.items():
        members: list[dict[str, Any]] = []

        for t in tickers:
            state = scanner_snapshot.get(t)
            if not state:
                continue

            rts = state.get("_rts") or {}
            rs_score = rts.get("score", 0)
            grade = rts.get("grade", "N/A")
            extension = rts.get("extension", "NORMAL")
            signal = state.get("signal", "")
            regime = state.get("regime", "")
            spot = state.get("actual_spot", 0)
            king = state.get("king", 0)

            # Check if above 20MA (from RTS mas if available)
            mas = rts.get("mas", {})
            above_20ma = spot > mas.get("ma20", 0) if mas.get("ma20") else None

            members.append({
                "ticker": t,
                "rs_score": rs_score,
                "grade": grade,
                "extension": extension,
                "signal": signal,
                "regime": regime,
                "above_20ma": above_20ma,
                "spot": spot,
                "king": king,
                "king_dist_pct": round((king - spot) / spot * 100, 1) if spot and king else 0,
            })

        if not members:
            continue

        # Industry metrics
        rs_scores = [m["rs_score"] for m in members]
        median_rs = sorted(rs_scores)[len(rs_scores) // 2] if rs_scores else 0
        top_tier = sum(1 for m in members if m["grade"] in ("A+", "A"))
        bullish = sum(1 for m in members if m["signal"] in ("MAGNET UP", "SUPPORT"))
        above_20ma_count = sum(1 for m in members if m["above_20ma"] is True)
        above_20ma_total = sum(1 for m in members if m["above_20ma"] is not None)
        pct_above_20ma = round(above_20ma_count / above_20ma_total * 100) if above_20ma_total else 0

        # Industry score (0-100)
        score = 0
        score += min(40, median_rs * 0.4)  # Median RS contribution (0-40)
        score += min(20, top_tier * 5)  # Top tier count (0-20)
        score += min(20, pct_above_20ma * 0.2)  # % above 20MA (0-20)
        score += min(20, (bullish / len(members) * 100) * 0.2) if members else 0  # Bullish % (0-20)
        score = round(score)

        # Industry state
        if score >= 70 and top_tier >= 2:
            state_label = "LEADING"
        elif score >= 50 or (score >= 40 and top_tier >= 1):
            state_label = "EMERGING"
        elif score >= 30:
            state_label = "NEUTRAL"
        elif score >= 15:
            state_label = "WEAKENING"
        else:
            state_label = "BROKEN"

        # Rank members within group
        members.sort(key=lambda m: m["rs_score"], reverse=True)
        for i, m in enumerate(members):
            m["rank_in_group"] = i + 1
            m["industry_tailwind"] = state_label in ("LEADING", "EMERGING")

        results[industry] = {
            "industry": industry,
            "score": score,
            "state": state_label,
            "median_rs": median_rs,
            "top_tier_count": top_tier,
            "bullish_count": bullish,
            "total": len(members),
            "pct_above_20ma": pct_above_20ma,
            "bullish_pct": round(bullish / len(members) * 100) if members else 0,
            "members": members,
        }

    _industry_cache = (now, results)
    return results


def enrich_ticker_with_industry(
    ticker: str,
    industry_scores: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Get industry context for a single ticker."""
    industry = get_ticker_industry(ticker)
    if not industry or industry not in industry_scores:
        return None

    ind = industry_scores[industry]
    member = next((m for m in ind["members"] if m["ticker"] == ticker), None)

    return {
        "industry": industry,
        "industry_score": ind["score"],
        "industry_state": ind["state"],
        "industry_rank": member["rank_in_group"] if member else None,
        "industry_tailwind": ind["state"] in ("LEADING", "EMERGING"),
        "industry_top_tier": ind["top_tier_count"],
        "industry_total": ind["total"],
        "industry_bullish_pct": ind["bullish_pct"],
    }
