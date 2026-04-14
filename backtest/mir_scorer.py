"""Mir's Trading Rules — standalone scorer for backtest.

Implements the 5-rule scoring from MIR_RULES_FOR_BACKTEST.md.
Can run independently OR combined with SOE GEX scoring.

When combined: GEX tells you WHERE (levels), Mir tells you WHEN (momentum).
"""
from __future__ import annotations

import math
from typing import Any


# Mir's approved sector tickers
MIR_SECTORS = {
    "Photonics": ["AAOI", "LITE", "COHR", "GLW", "CIEN", "AXTI"],
    "Semi Equipment": ["AEHR", "TER", "AMAT", "LRCX", "KLAC"],
    "Space": ["RKLB", "ASTS"],
    "AI/Compute": ["NBIS", "OKLO", "IREN", "VRT", "ANET"],
    "Memory": ["MU", "WDC"],
}
MIR_APPROVED_TICKERS = set()
for tickers in MIR_SECTORS.values():
    MIR_APPROVED_TICKERS.update(tickers)
# Also always allow indices
MIR_APPROVED_TICKERS.update(["SPY", "QQQ", "SMH", "IWM"])


def compute_relative_strength(
    ticker: str,
    spot_history: list[float],
    sector_histories: dict[str, list[float]] | None = None,
    period: int = 20,
) -> tuple[float, str]:
    """Compute relative strength rank within sector.

    Returns (rank 0-1 where 1 = strongest, label).
    Mir: "find the strongest relative strength names in the market"
    """
    if not spot_history or len(spot_history) < period:
        return 0.5, "insufficient data"

    my_return = (spot_history[-1] - spot_history[-period]) / spot_history[-period] * 100

    if not sector_histories:
        return 0.5, f"{my_return:+.1f}% (no sector comparison)"

    # Rank against sector peers
    returns = []
    for peer, hist in sector_histories.items():
        if len(hist) >= period:
            peer_ret = (hist[-1] - hist[-period]) / hist[-period] * 100
            returns.append((peer, peer_ret))

    if not returns:
        return 0.5, f"{my_return:+.1f}% (no peers)"

    returns.sort(key=lambda x: x[1], reverse=True)
    rank_idx = next((i for i, (p, _) in enumerate(returns) if p == ticker), len(returns))
    rank = 1 - (rank_idx / max(len(returns), 1))

    return rank, f"{my_return:+.1f}% (rank {rank_idx+1}/{len(returns)} in sector)"


def check_sma_filter(spot_history: list[float]) -> tuple[bool, str]:
    """Mir's Finviz filter: price above SMA 20, 50, AND 200 (strict).

    From his exact words: "These filters help you find the strongest
    relative strength names in the market."
    """
    if not spot_history or len(spot_history) < 200:
        if spot_history and len(spot_history) >= 50:
            sma_20 = sum(spot_history[-20:]) / 20
            sma_50 = sum(spot_history[-50:]) / 50
            current = spot_history[-1]
            if current > sma_20 and current > sma_50:
                return True, f"Above SMA20 + SMA50 (no SMA200 data)"
            return False, f"Below SMA20 or SMA50"
        return False, "insufficient data for SMA filter"

    current = spot_history[-1]
    sma_20 = sum(spot_history[-20:]) / 20
    sma_50 = sum(spot_history[-50:]) / 50
    sma_200 = sum(spot_history[-200:]) / 200

    if current > sma_20 > sma_50 > sma_200:
        return True, f"STRONG: price > SMA20 > SMA50 > SMA200 (perfect alignment)"
    elif current > sma_20 and current > sma_50 and current > sma_200:
        return True, f"Above all 3 SMAs (not perfectly stacked)"
    elif current > sma_20 and current > sma_50:
        return False, f"Above SMA20/50 but below SMA200"
    else:
        return False, f"Below SMA20 or SMA50 -- no bullish structure"


def score_mir_pattern(
    ticker: str,
    spot_history: list[float] | None = None,
    dte: int = 14,
    direction: str = "BULL",
    sector_histories: dict[str, list[float]] | None = None,
) -> tuple[float, list[str]]:
    """Score a trade setup against Mir's rules (enhanced with RAG insights).

    Returns (score 0-6, reasons).
    6 rules, each contributing 0-1 point.
    """
    score = 0.0
    reasons: list[str] = []

    # Rule 1: DTE alignment
    if dte == 0:
        score += 0.5
        reasons.append(f"DTE {dte}: lotto (size for zero)")
    elif 1 <= dte <= 7:
        score += 0.75
        reasons.append(f"DTE {dte}: day trade / short swing")
    elif 7 <= dte <= 21:
        score += 1.0
        reasons.append(f"DTE {dte}: sweet spot for catalyst plays")
    elif 21 <= dte <= 45:
        score += 0.75
        reasons.append(f"DTE {dte}: thematic swing")
    else:
        score += 0.25
        reasons.append(f"DTE {dte}: LEAPS/macro only")

    # Rule 2: SMA Filter (Mir's Finviz scanner -- price > SMA 20/50/200)
    # From RAG: "Market cap: Mid (over $2B), Price: Over $5, Price above SMA20/50/200"
    if spot_history:
        sma_pass, sma_detail = check_sma_filter(spot_history)
        if sma_pass:
            score += 1.0
            reasons.append(f"SMA filter PASS: {sma_detail}")
        else:
            reasons.append(f"SMA filter FAIL: {sma_detail}")
    else:
        reasons.append("SMA filter: no data")

    # Rule 3: Relative Strength (strongest name in sector)
    # From RAG: "find the strongest relative strength names"
    # Also from hourly 50SMA trick: "hovering above = very strong trend"
    rs_rank, rs_detail = compute_relative_strength(
        ticker, spot_history or [], sector_histories, period=20,
    )
    if rs_rank >= 0.75:
        score += 1.0
        reasons.append(f"RS top quartile: {rs_detail}")
    elif rs_rank >= 0.5:
        score += 0.5
        reasons.append(f"RS above median: {rs_detail}")
    else:
        reasons.append(f"RS below median: {rs_detail}")

    # Rule 4: EMA Structure (EMA21 > EMA50 for trend confirmation)
    if spot_history and len(spot_history) >= 50:
        ema_21 = _ema(spot_history, 21)
        ema_50 = _ema(spot_history, 50)
        current = spot_history[-1]

        if direction == "BULL" and current > ema_21 > ema_50:
            score += 1.0
            reasons.append(f"EMA aligned: price > EMA21 > EMA50")
        elif direction == "BULL" and current > ema_21:
            score += 0.5
            reasons.append(f"Price > EMA21 but EMAs not stacked")
        elif direction == "BEAR" and current < ema_21 < ema_50:
            score += 1.0
            reasons.append(f"Bearish EMA: price < EMA21 < EMA50")
        else:
            reasons.append(f"EMA not aligned with {direction}")

    # Rule 5: Macro / Volatility regime
    if spot_history and len(spot_history) >= 20:
        returns = [(spot_history[i] - spot_history[i-1]) / spot_history[i-1]
                   for i in range(-19, 0) if spot_history[i-1] > 0]
        if returns:
            rv_daily = (sum(r**2 for r in returns) / len(returns)) ** 0.5
            rv_annual = rv_daily * math.sqrt(252) * 100

            if rv_annual < 18:
                score += 1.0
                reasons.append(f"Macro: low vol ({rv_annual:.0f}% RV)")
            elif rv_annual < 25:
                score += 0.5
                reasons.append(f"Macro: moderate vol ({rv_annual:.0f}% RV)")
            elif rv_annual < 35:
                score += 0.25
                reasons.append(f"Macro: elevated ({rv_annual:.0f}% RV) -- reduce size")
            else:
                reasons.append(f"Macro: HIGH vol ({rv_annual:.0f}% RV) -- Mir says cash")

    # Rule 6: Sector membership (approved tickers)
    if ticker in MIR_APPROVED_TICKERS:
        score += 0.5
        reasons.append(f"{ticker} in Mir's approved sectors")
    else:
        reasons.append(f"{ticker} not in Mir's sector list")

    return score, reasons


def mir_stop_and_target(dte: int) -> dict[str, Any]:
    """Get Mir's stop/target rules based on DTE.

    Returns {stop_pct, target_pct, scale_out_pct, label}.
    """
    if dte == 0:
        return {
            "stop_pct": None,  # no stop, sized for zero
            "target_pct": 200,
            "scale_out_pct": 0,  # no scaling, let it ride
            "label": "0DTE Lotto: no stop, target +200%",
        }
    elif dte <= 7:
        return {
            "stop_pct": 50,
            "target_pct": 100,
            "scale_out_pct": 67,  # take 2/3 off at target
            "label": "Weekly: -50% stop, +100% target, scale 2/3",
        }
    else:
        return {
            "stop_pct": 50,
            "target_pct": 100,
            "scale_out_pct": 50,  # take 50% off at doubling
            "label": "Swing: -50% stop, +100% target (scale 50%)",
        }


def mir_size_pct(conviction: str = "MEDIUM", dte: int = 14) -> float:
    """Get Mir's position sizing as % of account.

    Returns max % of account for this trade.
    """
    # DTE cap
    if dte == 0:
        return 2.0  # "size for zero"

    # Conviction-based
    sizes = {"HIGH": 10.0, "MEDIUM": 5.0, "LOW": 2.0}
    return sizes.get(conviction, 5.0)


def _ema(data: list[float], period: int) -> float:
    """Compute EMA of the last N values."""
    if len(data) < period:
        return sum(data) / len(data)
    multiplier = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for val in data[period:]:
        ema = (val - ema) * multiplier + ema
    return ema
