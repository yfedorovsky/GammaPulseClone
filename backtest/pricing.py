"""Black-Scholes option repricing for realistic backtest P&L.

Replaces the DTE-based leverage approximation with actual BSM repricing
using the Greeks from EODHD data. Critical for high-vol names (photonics)
where the leverage model overstates returns.
"""
from __future__ import annotations

import math
from typing import Any


def _norm_cdf(x: float) -> float:
    """Standard normal CDF without scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(
    spot: float,
    strike: float,
    dte_years: float,
    iv: float,
    r: float = 0.05,
    option_type: str = "CALL",
) -> float:
    """Black-Scholes option price.

    Args:
        spot: current underlying price
        strike: option strike price
        dte_years: time to expiration in years (e.g. 14/365.25)
        iv: implied volatility as decimal (e.g. 0.25 for 25%)
        r: risk-free rate (default 5%)
        option_type: "CALL" or "PUT"

    Returns: theoretical option price
    """
    if dte_years <= 0:
        if option_type == "CALL":
            return max(spot - strike, 0)
        return max(strike - spot, 0)

    if iv <= 0 or spot <= 0 or strike <= 0:
        return 0

    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * dte_years) / (iv * math.sqrt(dte_years))
    d2 = d1 - iv * math.sqrt(dte_years)

    if option_type == "CALL":
        return spot * _norm_cdf(d1) - strike * math.exp(-r * dte_years) * _norm_cdf(d2)
    else:
        return strike * math.exp(-r * dte_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def estimate_option_pnl(
    entry_spot: float,
    exit_spot: float,
    strike: float,
    entry_dte: int,
    days_held: int,
    iv: float,
    option_type: str = "CALL",
    r: float = 0.05,
) -> float:
    """Estimate option P&L using Black-Scholes repricing.

    Computes the option price at entry and exit using BSM, then calculates
    the percentage return. Accounts for:
    - Delta (directional move)
    - Gamma (convexity)
    - Theta (time decay)
    - Vega stays constant (no IV change assumption — conservative)

    Args:
        entry_spot: spot price at entry
        exit_spot: spot price at exit
        strike: option strike
        entry_dte: DTE at entry
        days_held: number of days held
        iv: implied volatility (decimal, e.g. 0.30)
        option_type: "CALL" or "PUT"

    Returns: option P&L as percentage (e.g. +45.0 means +45%)
    """
    if iv <= 0:
        iv = 0.25  # fallback

    entry_dte_years = max(entry_dte, 1) / 365.25
    exit_dte_years = max(entry_dte - days_held, 0) / 365.25

    entry_price = black_scholes(entry_spot, strike, entry_dte_years, iv, r, option_type)
    exit_price = black_scholes(exit_spot, strike, exit_dte_years, iv, r, option_type)

    if entry_price <= 0.01:
        # Option was nearly worthless at entry — can't compute meaningful %
        # Fall back to intrinsic value change
        if option_type == "CALL":
            entry_intrinsic = max(entry_spot - strike, 0.01)
            exit_intrinsic = max(exit_spot - strike, 0)
        else:
            entry_intrinsic = max(strike - entry_spot, 0.01)
            exit_intrinsic = max(strike - exit_spot, 0)
        return ((exit_intrinsic - entry_intrinsic) / entry_intrinsic) * 100

    pnl_pct = ((exit_price - entry_price) / entry_price) * 100

    # Cap at -100% (can't lose more than premium paid)
    return max(-100.0, pnl_pct)
