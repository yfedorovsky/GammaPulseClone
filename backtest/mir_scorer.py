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


def score_mir_pattern(
    ticker: str,
    spot_history: list[float] | None = None,
    dte: int = 14,
    direction: str = "BULL",
) -> tuple[float, list[str]]:
    """Score a trade setup against Mir's 5 rules.

    Returns (score 0-5, reasons).
    Each rule contributes 0 or 1 point.
    """
    score = 0.0
    reasons: list[str] = []

    # Rule 1: DTE alignment
    if dte == 0:
        score += 0.5  # lotto, acceptable but not preferred
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

    # Rule 2: Time of day (we only have daily data, so this is partial)
    # Skip for backtest — would need intraday timestamps
    # Default: assume mid-day entry (neutral, +0.5)
    score += 0.5
    reasons.append("Time: daily data (assuming mid-day entry)")

    # Rule 3: Ticker quality — EMA filter + sector membership
    ticker_score = 0.0
    ticker_reasons = []

    # Sector membership
    if ticker in MIR_APPROVED_TICKERS:
        ticker_score += 0.5
        ticker_reasons.append(f"{ticker} in approved sector")
    else:
        ticker_reasons.append(f"{ticker} not in Mir's sector list")

    # EMA filter: price > EMA21 > EMA50 (bullish structure)
    if spot_history and len(spot_history) >= 50:
        ema_21 = _ema(spot_history, 21)
        ema_50 = _ema(spot_history, 50)
        current = spot_history[-1]

        if direction == "BULL":
            if current > ema_21 > ema_50:
                ticker_score += 0.5
                ticker_reasons.append(f"EMA aligned: price > EMA21 > EMA50")
            elif current > ema_21:
                ticker_score += 0.25
                ticker_reasons.append(f"Price > EMA21 but EMA21 < EMA50")
            else:
                ticker_reasons.append(f"Price below EMA21 -- no bullish structure")
        else:  # BEAR
            if current < ema_21 < ema_50:
                ticker_score += 0.5
                ticker_reasons.append(f"Bearish EMA: price < EMA21 < EMA50")
            elif current < ema_21:
                ticker_score += 0.25
                ticker_reasons.append(f"Price < EMA21 (bearish)")
            else:
                ticker_reasons.append(f"Price above EMA21 -- no bearish structure")
    elif spot_history and len(spot_history) >= 21:
        ema_21 = _ema(spot_history, 21)
        current = spot_history[-1]
        if (direction == "BULL" and current > ema_21) or (direction == "BEAR" and current < ema_21):
            ticker_score += 0.25
            ticker_reasons.append(f"EMA21 aligned (no EMA50 data)")

    score += ticker_score
    reasons.append(f"Ticker quality ({ticker_score:.1f}/1): {'; '.join(ticker_reasons)}")

    # Rule 4: Macro alignment (VIX proxy from spot vol)
    if spot_history and len(spot_history) >= 20:
        # Use realized vol as VIX proxy
        returns = [(spot_history[i] - spot_history[i-1]) / spot_history[i-1]
                   for i in range(-19, 0) if spot_history[i-1] > 0]
        if returns:
            rv_daily = (sum(r**2 for r in returns) / len(returns)) ** 0.5
            rv_annual = rv_daily * math.sqrt(252) * 100  # as percentage

            if rv_annual < 18:
                score += 1.0
                reasons.append(f"Macro: low vol ({rv_annual:.0f}% RV) -- full size")
            elif rv_annual < 25:
                score += 0.5
                reasons.append(f"Macro: moderate vol ({rv_annual:.0f}% RV) -- normal")
            elif rv_annual < 35:
                score += 0.25
                reasons.append(f"Macro: elevated vol ({rv_annual:.0f}% RV) -- reduce size")
            else:
                reasons.append(f"Macro: HIGH vol ({rv_annual:.0f}% RV) -- Mir says go to cash")
    else:
        score += 0.5
        reasons.append("Macro: insufficient data for vol check")

    # Rule 5: Mir conviction (skip in backtest — would need Discord signal)
    # Default: neutral 0.5
    score += 0.5
    reasons.append("Conviction: no Mir signal (backtest default)")

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
