"""Deflated Sharpe Ratio family (Bailey & Lopez de Prado).

References:
  - Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
    Selection Bias, Backtest Overfitting and Non-Normality", J. Portfolio Mgmt.
  - Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier",
    J. Risk  (PSR + Minimum Track Record Length).
  - Bailey, Borwein, Lopez de Prado, Zhu (2014), "Pseudo-Mathematics and
    Financial Charlatanism", Notices of the AMS  (Minimum Backtest Length).

Conventions:
  - All Sharpe ratios here are PER-OBSERVATION (non-annualized); ``T`` is the
    number of observations behind the ratio. Annualization cancels out of PSR/DSR.
  - ``kurtosis`` is NON-EXCESS (a normal distribution has kurtosis == 3.0).
  - ``N`` for DSR is the GLOBAL trial count (every backtest ever run), supplied
    via the trials ledger, NOT a per-signal count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.stats import norm

EULER_MASCHERONI = 0.5772156649015329


def sharpe_ratio(returns: Sequence[float]) -> float:
    """Per-observation Sharpe = mean / std (population std, ddof=0)."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd)


def _moments(returns: Sequence[float]) -> tuple[float, float]:
    """Return (skewness, NON-excess kurtosis) of a return series."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 3:
        return 0.0, 3.0
    m = r.mean()
    sd = r.std(ddof=0)
    if sd == 0:
        return 0.0, 3.0
    skew = float(np.mean(((r - m) / sd) ** 3))
    kurt = float(np.mean(((r - m) / sd) ** 4))  # non-excess
    return skew, kurt


def probabilistic_sharpe_ratio(sr: float, sr_star: float, T: int,
                               skew: float = 0.0, kurt: float = 3.0) -> float:
    """PSR: P(true SR > sr_star) given observed SR, length T, skew & kurtosis.

        PSR = Phi( (SR - SR*) * sqrt(T - 1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )
    """
    if T < 2:
        return float("nan")
    denom_sq = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom_sq <= 0:
        # Degenerate (extreme skew/kurt); fall back to the Gaussian denominator.
        denom_sq = max(1e-12, 1.0 + 0.5 * sr * sr)
    z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(denom_sq)
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max Sharpe] across ``n_trials`` independent trials under the null.

        E[max] = sqrt(Var(SR)) * [ (1-g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e)) ]

    where g is the Euler-Mascheroni constant. With one trial there is no
    multiple-testing inflation, so E[max] == 0.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1 or sr_variance <= 0:
        return 0.0
    sqrt_var = math.sqrt(sr_variance)
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(sqrt_var * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2))


@dataclass
class DSRResult:
    dsr: float            # Deflated Sharpe Ratio (a probability in [0, 1]).
    sr_observed: float
    sr0: float            # E[max Sharpe | N] benchmark that SR must beat.
    n_trials: int
    sr_variance: float
    T: int


def deflated_sharpe_ratio(sr_observed: float, sr_estimates: Sequence[float],
                          T: int, skew: float = 0.0, kurt: float = 3.0) -> DSRResult:
    """DSR = PSR evaluated at SR* = E[max Sharpe | N trials].

    Args:
        sr_observed: the candidate's per-observation Sharpe.
        sr_estimates: ALL trial Sharpes (global) — supplies both N (=len) and the
            cross-trial variance Var(SR) that the E[max] estimator needs.
        T: observation count behind ``sr_observed``.
        skew, kurt: candidate's skew and NON-excess kurtosis.
    """
    est = np.asarray(sr_estimates, dtype=float)
    n = int(est.size)
    var = float(est.var(ddof=1)) if n >= 2 else 0.0
    sr0 = expected_max_sharpe(max(n, 1), var)
    dsr = probabilistic_sharpe_ratio(sr_observed, sr0, T, skew, kurt)
    return DSRResult(dsr=dsr, sr_observed=sr_observed, sr0=sr0,
                     n_trials=n, sr_variance=var, T=T)


def min_track_record_length(sr: float, skew: float, kurt: float,
                            sr_star: float = 0.0, prob: float = 0.95) -> float:
    """MinTRL: min observations so PSR(sr_star) >= prob.

        MinTRL = 1 + (1 - skew*SR + (kurt-1)/4 * SR^2) * (Z_prob / (SR - SR*))^2
    """
    if sr <= sr_star:
        return float("inf")
    z = norm.ppf(prob)
    denom_sq = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom_sq <= 0:
        denom_sq = max(1e-12, 1.0 + 0.5 * sr * sr)
    return float(1.0 + denom_sq * (z / (sr - sr_star)) ** 2)


def min_backtest_length(n_trials: int, sr_target: float = 1.0) -> float:
    """MinBTL: min observations so the null N-trial max Sharpe stays below target.

        E[max SR | null] ~ sqrt(2 ln N / T)   =>   T >= 2 ln N / sr_target^2

    (Bailey-Borwein-LdP-Zhu 2014.) Returns observations T. With < 2 trials there
    is no multiple-testing floor, so returns 0.
    """
    if n_trials < 2:
        return 0.0
    if sr_target <= 0:
        raise ValueError("sr_target must be > 0")
    return float(2.0 * math.log(n_trials) / (sr_target * sr_target))


__all__ = [
    "sharpe_ratio", "probabilistic_sharpe_ratio", "expected_max_sharpe",
    "deflated_sharpe_ratio", "DSRResult", "min_track_record_length",
    "min_backtest_length", "_moments", "EULER_MASCHERONI",
]
