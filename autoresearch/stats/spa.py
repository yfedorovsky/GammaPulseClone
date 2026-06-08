"""Hansen's Superior Predictive Ability (SPA) test — beat-the-baseline gate.

Reference:
  Hansen (2005), "A Test for Superior Predictive Ability", JBES.
  (White's 2000 Reality Check is the precursor; SPA corrects for poor/irrelevant
  alternatives via studentization.)

This is the ONE stage backed by an external library: ``arch.bootstrap.SPA`` with a
stationary block bootstrap. The economic point: a candidate must STATISTICALLY
BEAT the live baseline (SOE A), not merely beat zero. We frame performance as
LOSS = -return (SPA tests for a model with significantly LOWER expected loss than
the benchmark), so the benchmark is the baseline's losses and the model is the
candidate's losses.

Alignment: SPA requires the benchmark and model loss series to be the SAME length
T (one loss per common observation). Callers must align candidate and baseline to
a common per-period grid (e.g. daily P/L) before calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from arch.bootstrap import SPA


@dataclass
class SPAResult:
    beats_baseline: bool
    pvalue_consistent: float
    pvalue_lower: float
    pvalue_upper: float
    candidate_mean: float
    baseline_mean: float
    T: int


def spa_beats_baseline(candidate_returns: Sequence[float],
                       baseline_returns: Sequence[float],
                       *, alpha: float = 0.05, reps: int = 1000,
                       block_size: Optional[int] = None,
                       seed: Optional[int] = 12345) -> SPAResult:
    """Test whether ``candidate`` significantly beats ``baseline`` (Hansen SPA).

    Args:
        candidate_returns, baseline_returns: aligned per-period returns, equal length.
        alpha: significance level; ``beats_baseline`` is ``p_consistent < alpha``.
        reps: bootstrap replications.
        block_size: stationary-bootstrap mean block length; default ~ T**(1/3).
        seed: RNG seed for reproducibility.

    Returns:
        SPAResult. ``beats_baseline`` is True only when the candidate's mean return
        exceeds the baseline's AND the consistent SPA p-value < alpha.
    """
    cand = np.asarray(candidate_returns, dtype=float)
    base = np.asarray(baseline_returns, dtype=float)
    if cand.shape[0] != base.shape[0]:
        raise ValueError(
            f"candidate ({cand.shape[0]}) and baseline ({base.shape[0]}) must be "
            "aligned to equal length before SPA"
        )
    T = int(cand.shape[0])
    if T < 8:
        raise ValueError("SPA needs a non-trivial sample (T >= 8)")
    if block_size is None:
        block_size = max(1, int(round(T ** (1.0 / 3.0))))

    # SPA is in LOSS space: lower loss == better. loss = -return.
    benchmark_loss = -base
    model_loss = -cand.reshape(-1, 1)

    spa = SPA(benchmark_loss, model_loss, reps=reps, block_size=block_size,
              bootstrap="stationary", seed=seed)
    spa.compute()
    pvals = spa.pvalues  # pandas Series indexed lower/consistent/upper.
    p_consistent = float(pvals["consistent"])
    p_lower = float(pvals["lower"])
    p_upper = float(pvals["upper"])

    cand_mean = float(cand.mean())
    base_mean = float(base.mean())
    beats = bool(cand_mean > base_mean and p_consistent < alpha)
    return SPAResult(
        beats_baseline=beats,
        pvalue_consistent=p_consistent,
        pvalue_lower=p_lower,
        pvalue_upper=p_upper,
        candidate_mean=cand_mean,
        baseline_mean=base_mean,
        T=T,
    )


__all__ = ["spa_beats_baseline", "SPAResult"]
