"""Nonlinear options slippage lookup.

Phase 6A.0c. Per ChatGPT pressure-test (Apr 26 evening): static
percentage-of-premium per ticker is BETTER than $/leg, but still misses
the nonlinear reality:

    "Best-looking trades are your worst-filled trades."

Nonlinear factors:
  - High IV → spreads widen (~+30% friction at IV-rank > 0.80)
  - OTM strikes → wider spreads (~+40-100% vs ATM)
  - Velocity (intraday move > 1.5%) → fills deteriorate (~+25%)
  - Low daily option volume → wider spreads (already in baseline)

This module exposes a single function:

    slippage_lookup(ticker, iv_rank=None, moneyness_pct=0,
                    velocity_pct=None) -> float

returning the round-trip percentage-of-premium friction estimate.

Used by:
  - vega_adjusted_pnl.py for backtest realism
  - liquidity gate (M3) live enforcement (future Phase 6B)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cohort_slippage.json"

# Fallback friction by category if cache is empty/stale
DEFAULT_FRICTION = {
    "LIQUID": 6.0,
    "MEDIUM": 8.0,
    "THIN": 14.0,
    "VERY_THIN": 22.0,
    "UNKNOWN": 18.0,  # conservative when ticker not in cache
}

# Nonlinear adjustment factors (multiplicative)
IV_RANK_HIGH_THRESHOLD = 0.66      # matches IV-rank gate threshold
IV_RANK_HIGH_FACTOR = 1.30          # +30% friction in HIGH-IV regime
IV_RANK_LOW_THRESHOLD = 0.33
IV_RANK_LOW_FACTOR = 0.90           # -10% in LOW-IV regime

MONEYNESS_OTM_5_FACTOR = 1.40       # OTM 5% strikes
MONEYNESS_OTM_10_FACTOR = 2.00      # OTM 10%+ strikes (often 2× ATM spread)

VELOCITY_FAST_THRESHOLD_PCT = 1.5   # underlying moved >1.5% intraday
VELOCITY_FAST_FACTOR = 1.25         # +25% friction during fast moves


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def slippage_lookup(
    ticker: str,
    iv_rank: float | None = None,
    moneyness_pct: float = 0.0,
    velocity_pct: float | None = None,
) -> dict[str, Any]:
    """Return round-trip slippage estimate as percent of premium.

    Args:
        ticker: cohort symbol
        iv_rank: current IV-rank (0-1). None = neutral assumption.
        moneyness_pct: distance OTM as decimal (0 = ATM, 0.05 = 5% OTM,
            -0.10 = 10% ITM call). For puts, sign-flip.
        velocity_pct: intraday underlying move as decimal (None = ignore).

    Returns:
        {
            "round_trip_pct": float,        # final estimate
            "baseline_pct": float,
            "iv_factor": float,
            "moneyness_factor": float,
            "velocity_factor": float,
            "category": str,
            "details": str,
        }
    """
    cache = _load_cache()
    entry = cache.get(ticker.upper(), {})

    # Baseline from category
    category = entry.get("category", "UNKNOWN")
    baseline = entry.get("round_trip_friction_pct", DEFAULT_FRICTION.get(category, 18.0))

    # Nonlinear adjustments
    iv_factor = 1.0
    if iv_rank is not None:
        if iv_rank >= IV_RANK_HIGH_THRESHOLD:
            iv_factor = IV_RANK_HIGH_FACTOR
        elif iv_rank <= IV_RANK_LOW_THRESHOLD:
            iv_factor = IV_RANK_LOW_FACTOR

    moneyness_factor = 1.0
    abs_money = abs(moneyness_pct)
    if abs_money >= 0.10:
        moneyness_factor = MONEYNESS_OTM_10_FACTOR
    elif abs_money >= 0.05:
        moneyness_factor = MONEYNESS_OTM_5_FACTOR
    elif abs_money >= 0.02:
        # Mild OTM (2-5%): linear interpolation
        moneyness_factor = 1.0 + (abs_money - 0.02) / 0.03 * (MONEYNESS_OTM_5_FACTOR - 1.0)

    velocity_factor = 1.0
    if velocity_pct is not None and abs(velocity_pct) >= VELOCITY_FAST_THRESHOLD_PCT / 100.0:
        velocity_factor = VELOCITY_FAST_FACTOR

    final_pct = baseline * iv_factor * moneyness_factor * velocity_factor
    # Cap at 50% (anything higher means trade is impossible to execute)
    final_pct = min(final_pct, 50.0)

    details = (
        f"baseline {baseline:.1f}% × iv_factor {iv_factor:.2f} "
        f"× moneyness {moneyness_factor:.2f} × velocity {velocity_factor:.2f}"
    )

    return {
        "round_trip_pct": round(final_pct, 2),
        "baseline_pct": baseline,
        "iv_factor": iv_factor,
        "moneyness_factor": moneyness_factor,
        "velocity_factor": velocity_factor,
        "category": category,
        "details": details,
    }


def kill_threshold_check(theoretical_edge_pct: float, ticker: str,
                          iv_rank: float | None = None,
                          moneyness_pct: float = 0.0) -> dict[str, Any]:
    """Grok's kill threshold: if theoretical edge < +5pp net of slippage,
    demote or kill the signal.

    Returns:
        {
            "theoretical_edge_pct": float,
            "slippage_pct": float,
            "net_edge_pct": float,
            "verdict": "SHIP" | "DEMOTE" | "KILL",
            "reason": str,
        }
    """
    slip = slippage_lookup(ticker, iv_rank, moneyness_pct)
    slip_pct = slip["round_trip_pct"]
    net = theoretical_edge_pct - slip_pct
    if net >= 5.0:
        verdict = "SHIP"
        reason = f"Net edge {net:+.1f}% ≥ 5% threshold (theoretical {theoretical_edge_pct:+.1f}% - slippage {slip_pct:.1f}%)"
    elif net >= 0:
        verdict = "DEMOTE"
        reason = f"Net edge {net:+.1f}% positive but < 5% threshold; demote to tie-breaker / observation-only"
    else:
        verdict = "KILL"
        reason = f"Net edge {net:+.1f}% negative after slippage; signal is phantom alpha"
    return {
        "theoretical_edge_pct": theoretical_edge_pct,
        "slippage_pct": slip_pct,
        "net_edge_pct": round(net, 2),
        "verdict": verdict,
        "reason": reason,
        "slippage_details": slip,
    }


if __name__ == "__main__":
    print("Slippage model smoke tests:\n")
    test_cases = [
        # (ticker, iv_rank, moneyness, label)
        ("MU", 0.50, 0.0, "MU ATM, neutral IV"),
        ("MU", 0.85, 0.05, "MU 5% OTM in HIGH IV"),
        ("AAOI", 0.50, 0.0, "AAOI ATM, neutral IV"),
        ("AAOI", 0.85, 0.10, "AAOI 10% OTM in HIGH IV (worst case)"),
        ("LASR", 0.30, 0.05, "LASR 5% OTM in LOW IV"),
        ("UNKNOWN_TICKER", 0.50, 0.05, "Unknown ticker fallback"),
    ]
    for ticker, iv_rank, moneyness, label in test_cases:
        r = slippage_lookup(ticker, iv_rank=iv_rank, moneyness_pct=moneyness)
        print(f"  {label}")
        print(f"    Round-trip: {r['round_trip_pct']}%  ({r['details']})")

    print("\nKill threshold tests:")
    for ticker, edge, iv_rank, moneyness, label in [
        ("MU", 11.0, 0.50, 0.05, "MU 5% OTM, IV-rank 0.50, +11pp claimed edge"),
        ("AAOI", 11.0, 0.85, 0.05, "AAOI 5% OTM, IV-rank 0.85, +11pp claimed edge"),
        ("AAOI", 25.0, 0.85, 0.10, "AAOI 10% OTM, IV-rank 0.85, +25pp claimed edge"),
    ]:
        k = kill_threshold_check(edge, ticker, iv_rank=iv_rank, moneyness_pct=moneyness)
        print(f"  {label}")
        print(f"    {k['verdict']}: {k['reason']}")
