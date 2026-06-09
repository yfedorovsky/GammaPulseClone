"""Betting confidence sequence for a bounded mean (pure-stdlib).

Resolves the FIX-2 caveat: the verified `confseq` library has no Windows wheel and
needs boost/C++ that won't build here, so the decay monitor fell back to a
hand-rolled empirical-Bernstein bound with an *unverified* log-log constant. This
module replaces that with the **hedged-capital betting confidence sequence**
(Waudby-Smith & Ramdas 2023, "Estimating means of bounded random variables by
betting") — the near-optimal, time-uniform CS — implemented transparently and
**validated by a Monte-Carlo coverage simulation** (scripts/test_betting_cs.py),
so it is empirically verified rather than asserted.

Construction (X_i in [0,1], testing each candidate mean m on a grid):
  K_t^+(m) = prod (1 + lam_i (X_i - m))      bets mean > m
  K_t^-(m) = prod (1 - lam_i (X_i - m))      bets mean < m
  K_t(m)   = 0.5 K_t^+(m) + 0.5 K_t^-(m)     (hedged, two-sided)
  CS_t     = { m : K_t(m) < 1/alpha }        (a sub-interval of [0,1])
``lam_i`` is the PREDICTABLE plug-in bet (uses X_1..X_{i-1} only), truncated to
[0, 0.5] which keeps BOTH capital processes non-negative for every m in (0,1).
Ville's inequality makes this a valid (1-alpha) time-uniform confidence sequence.
"""
from __future__ import annotations

import math
from typing import Sequence

_LAM_CAP = 0.5          # global truncation; keeps K^+ and K^- >= 0 for all m in (0,1).
_VAR_FLOOR = 1e-4       # variance floor for the predictable lambda.
_VAR_INIT = 0.25        # max variance of a [0,1] variable (no data yet).


def _predictable_lambdas(xs: Sequence[float], alpha: float) -> list[float]:
    """lam_i from a running (Welford) mean/variance of X_1..X_{i-1} only.

    lam_i = sqrt( 2 ln(2/alpha) / (var_{i-1} * i * ln(i+1)) ), truncated to [0, cap].
    """
    c = 2.0 * math.log(2.0 / alpha)
    lams: list[float] = []
    mean = 0.0
    m2 = 0.0
    count = 0
    for i, x in enumerate(xs, start=1):
        var_prev = (m2 / count) if count >= 1 else _VAR_INIT  # population var of prior points
        var_prev = max(var_prev, _VAR_FLOOR)
        lam = math.sqrt(c / (var_prev * i * math.log(i + 1)))
        lams.append(min(_LAM_CAP, lam))
        # Welford update (so next step's var is predictable).
        count += 1
        d = x - mean
        mean += d / count
        m2 += d * (x - mean)
    return lams


def _hedged_capital(xs: Sequence[float], lams: Sequence[float], m: float) -> float:
    """K_t(m) = 0.5*prod(1+lam(x-m)) + 0.5*prod(1-lam(x-m)). Log-space for stability."""
    log_kp = 0.0
    log_km = 0.0
    for x, lam in zip(xs, lams):
        d = lam * (x - m)
        # 1 +/- d are guaranteed > 0 by the lambda cap; clamp epsilon for safety.
        log_kp += math.log(max(1.0 + d, 1e-300))
        log_km += math.log(max(1.0 - d, 1e-300))
    hi = max(log_kp, log_km)
    return math.exp(hi) * 0.5 * (math.exp(log_kp - hi) + math.exp(log_km - hi))


def betting_ci(xs: Sequence[float], alpha: float = 0.05,
               grid_n: int = 200) -> tuple[float, float]:
    """(lower, upper) endpoints of the hedged betting CS after observing ``xs``.

    Time-uniform / anytime-valid: re-evaluating after each new observation carries
    no optional-stopping penalty. Returns (0.0, 1.0) with no data.
    """
    xs = [float(x) for x in xs]
    if not xs:
        return (0.0, 1.0)
    lams = _predictable_lambdas(xs, alpha)
    thresh = 1.0 / alpha
    in_cs = [m / grid_n for m in range(grid_n + 1)
             if _hedged_capital(xs, lams, m / grid_n) < thresh]
    if not in_cs:                      # everything rejected (degenerate) -> widest.
        return (0.0, 1.0)
    return (min(in_cs), max(in_cs))


def betting_lcb_stream(xs: Sequence[float], alpha: float = 0.05,
                       grid_n: int = 200) -> float:
    """One-sided lower bound from an ORDERED [0,1] stream (= betting_ci lower).

    IMPORTANT: the betting CS is sequential — it must be fed the real observation
    ORDER. Do NOT reconstruct it from (wins, n) counts: an arbitrary order
    (e.g. all wins first) makes the bound anti-conservative / INVALID (verified by
    the coverage simulation). Count-only callers must use a count-valid bound
    (e.g. the empirical-Bernstein fallback), not this.
    """
    if not xs:
        return 0.0
    return betting_ci(xs, alpha, grid_n)[0]


__all__ = ["betting_ci", "betting_lcb_stream"]
