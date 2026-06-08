"""C2 — hierarchical / Bayesian partial pooling for subgroups.

Per-cohort frequentist gates at n-in-the-hundreds are ~100% false-negative after
honest deflation (a 14.9%->20% lift gives t~2.1, fails Harvey-Liu-Zhu t>3). The
fix the Round-2 follow-up converged on: keep frequentist DEFLATION only at
top-level candidate admission, but estimate SUBGROUP effects (regime x OI x
sub-signal x horizon) with partial pooling that shrinks small cohorts toward the
pooled mean — so a thin subgroup borrows strength instead of being dismissed.

Two estimators:
  - ``beta_binomial_pool`` — empirical-Bayes Beta-Binomial for WIN RATE. Prior
    (alpha,beta) estimated by method-of-moments across subgroups; each subgroup's
    posterior shrinks toward the pooled rate, strongly when n is small.
  - ``normal_pool`` — DerSimonian-Laird random-effects partial pooling for the mean
    R-MULTIPLE (values winsorized first ≈ a robust hierarchical-t), shrinking
    small/noisy groups toward the grand mean.

Needs numpy/scipy -> autoresearch venv.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy.stats import beta as _beta


@dataclass
class PooledRate:
    name: str
    n: int
    wins: int
    raw_rate: float
    shrunk_rate: float          # empirical-Bayes posterior mean.
    ci_low: float               # 95% credible interval (Beta posterior).
    ci_high: float
    prior_mean: float
    prior_strength: float       # alpha + beta.


def beta_binomial_pool(subgroups: Mapping[str, tuple[int, int]],
                       kappa_bounds: tuple[float, float] = (2.0, 1000.0),
                       cred_mass: float = 0.95) -> dict[str, PooledRate]:
    """Empirical-Bayes Beta-Binomial pooling of subgroup win rates.

    Args:
        subgroups: name -> (wins, n).
        kappa_bounds: clamp for the estimated prior strength alpha+beta.
        cred_mass: credible-interval mass (0.95 -> 2.5/97.5 percentiles).

    Returns: name -> PooledRate.
    """
    items = [(name, int(w), int(n)) for name, (w, n) in subgroups.items() if n > 0]
    if not items:
        return {}
    total_w = sum(w for _, w, _ in items)
    total_n = sum(n for _, _, n in items)
    m = total_w / total_n                      # pooled (grand) rate = prior mean.

    # Method-of-moments prior strength from between-subgroup dispersion of rates.
    rates = np.array([w / n for _, w, n in items], dtype=float)
    if rates.size >= 2:
        v = float(rates.var(ddof=1))
        if v > 1e-12 and 0.0 < m < 1.0:
            kappa = m * (1.0 - m) / v - 1.0
        else:
            kappa = kappa_bounds[1]            # no dispersion -> strong pooling.
    else:
        kappa = float(np.median([n for _, _, n in items]))
    kappa = float(min(max(kappa, kappa_bounds[0]), kappa_bounds[1]))
    alpha0, beta0 = m * kappa, (1.0 - m) * kappa

    lo_q, hi_q = (1 - cred_mass) / 2, 1 - (1 - cred_mass) / 2
    out: dict[str, PooledRate] = {}
    for name, w, n in items:
        a, b = alpha0 + w, beta0 + (n - w)
        out[name] = PooledRate(
            name=name, n=n, wins=w, raw_rate=w / n,
            shrunk_rate=a / (a + b),
            ci_low=float(_beta.ppf(lo_q, a, b)),
            ci_high=float(_beta.ppf(hi_q, a, b)),
            prior_mean=m, prior_strength=kappa,
        )
    return out


@dataclass
class PooledMean:
    name: str
    n: int
    raw_mean: float
    shrunk_mean: float          # random-effects posterior mean.
    se: float                   # within-group standard error (after winsorizing).
    grand_mean: float
    tau2: float                 # estimated between-group variance.


def _winsorize(x: np.ndarray, q: float) -> np.ndarray:
    if q <= 0 or x.size < 5:
        return x
    lo, hi = np.quantile(x, [q, 1 - q])
    return np.clip(x, lo, hi)


def normal_pool(subgroups: Mapping[str, Sequence[float]],
                winsor_q: float = 0.05) -> dict[str, PooledMean]:
    """DerSimonian-Laird random-effects partial pooling of subgroup means.

    Values are winsorized per group (robust ≈ hierarchical-t). Small/noisy groups
    shrink toward the precision-weighted grand mean.
    """
    groups = []
    for name, vals in subgroups.items():
        a = _winsorize(np.asarray(vals, dtype=float), winsor_q)
        if a.size == 0:
            continue
        ybar = float(a.mean())
        # SE^2 of the mean; guard tiny/zero variance with a floor.
        s2 = float(a.var(ddof=1)) / a.size if a.size >= 2 else 1.0
        s2 = max(s2, 1e-9)
        groups.append([name, a.size, ybar, s2])
    if not groups:
        return {}

    w = np.array([1.0 / g[3] for g in groups])         # fixed-effect weights.
    y = np.array([g[2] for g in groups])
    fe_mean = float((w * y).sum() / w.sum())
    Q = float((w * (y - fe_mean) ** 2).sum())
    df = len(groups) - 1
    if df > 0:
        c = w.sum() - (w ** 2).sum() / w.sum()
        tau2 = max(0.0, (Q - df) / c) if c > 0 else 0.0
    else:
        tau2 = 0.0

    v = 1.0 / (np.array([g[3] for g in groups]) + tau2)
    grand = float((v * y).sum() / v.sum())

    out: dict[str, PooledMean] = {}
    for name, n, ybar, s2 in groups:
        if tau2 > 0:
            shrunk = (ybar / s2 + grand / tau2) / (1.0 / s2 + 1.0 / tau2)
        else:
            shrunk = grand                              # no between-group variance -> full pooling.
        out[name] = PooledMean(name=name, n=n, raw_mean=ybar, shrunk_mean=float(shrunk),
                               se=float(np.sqrt(s2)), grand_mean=grand, tau2=tau2)
    return out


__all__ = ["PooledRate", "beta_binomial_pool", "PooledMean", "normal_pool"]
