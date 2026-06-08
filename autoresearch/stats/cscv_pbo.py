"""Probability of Backtest Overfitting via Combinatorially-Symmetric CV (CSCV).

Reference:
  Bailey, Borwein, Lopez de Prado, Zhu (2017), "The Probability of Backtest
  Overfitting", Journal of Computational Finance.

Idea: given a matrix ``M`` of shape (T observations, N strategy configurations),
split the T rows into S equal blocks. For every way of choosing S/2 blocks as the
in-sample (IS) set (the complement is out-of-sample, OOS):
  1. pick the config that is BEST in-sample (n* = argmax IS performance),
  2. find that same config's relative rank OOS, omega in (0, 1),
  3. logit lambda = ln(omega / (1 - omega)).
PBO = P(lambda <= 0) = the fraction of splits where the IS-winner lands below the
OOS median. PBO near 0.5 == the IS choice is no better than random OOS == severe
overfitting. The gate requires PBO < 0.05.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Optional, Sequence

import numpy as np
from scipy.stats import rankdata


def _sharpe_cols(block: np.ndarray) -> np.ndarray:
    """Per-column Sharpe (mean/std, ddof=1) of a (rows, N) block."""
    mean = block.mean(axis=0)
    sd = block.std(axis=0, ddof=1)
    out = np.zeros_like(mean)
    nz = sd > 0
    out[nz] = mean[nz] / sd[nz]
    return out


@dataclass
class PBOResult:
    pbo: float                      # probability of backtest overfitting in [0, 1].
    n_combinations: int
    n_configs: int
    n_blocks: int
    logits: list[float] = field(default_factory=list)
    # Median OOS performance of the IS-best config, across splits (diagnostic).
    median_oos_rank_of_is_best: float = float("nan")


def cscv_pbo(M, n_blocks: int = 16,
             perf: Optional[Callable[[np.ndarray], np.ndarray]] = None) -> PBOResult:
    """Compute PBO from a (T, N) performance matrix via CSCV.

    Args:
        M: array-like, shape (T observations, N configurations). Each column is
           one strategy variant's per-observation returns.
        n_blocks: S, an EVEN number of disjoint row blocks (default 16).
        perf: per-column performance metric on a block -> length-N vector.
              Defaults to per-column Sharpe.

    Returns:
        PBOResult with ``pbo`` and the full logit distribution.
    """
    if perf is None:
        perf = _sharpe_cols
    M = np.asarray(M, dtype=float)
    if M.ndim != 2:
        raise ValueError("M must be 2-D (T observations x N configs)")
    T, N = M.shape
    if N < 2:
        raise ValueError("need >= 2 configurations to assess overfitting")
    if n_blocks < 2 or n_blocks % 2 != 0:
        raise ValueError("n_blocks (S) must be an even integer >= 2")
    if T < n_blocks:
        raise ValueError(f"need at least n_blocks={n_blocks} observations, got T={T}")

    # Equal blocks; trim the remainder rows so blocks are exactly equal-sized.
    block_size = T // n_blocks
    usable = block_size * n_blocks
    rows = np.arange(usable).reshape(n_blocks, block_size)  # block index -> row idx
    block_ids = list(range(n_blocks))
    half = n_blocks // 2

    logits: list[float] = []
    oos_ranks: list[float] = []
    for is_blocks in combinations(block_ids, half):
        is_set = set(is_blocks)
        is_rows = np.concatenate([rows[b] for b in block_ids if b in is_set])
        oos_rows = np.concatenate([rows[b] for b in block_ids if b not in is_set])

        r_is = perf(M[is_rows])
        r_oos = perf(M[oos_rows])

        n_star = int(np.argmax(r_is))                  # best config in-sample.
        ranks = rankdata(r_oos, method="ordinal")      # 1..N ascending OOS.
        rank_star = float(ranks[n_star])
        omega = rank_star / (N + 1.0)                  # relative rank in (0, 1).
        omega = min(max(omega, 1e-12), 1.0 - 1e-12)
        logits.append(float(np.log(omega / (1.0 - omega))))
        oos_ranks.append(rank_star / N)

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr <= 0.0))
    return PBOResult(
        pbo=pbo,
        n_combinations=len(logits),
        n_configs=N,
        n_blocks=n_blocks,
        logits=logits,
        median_oos_rank_of_is_best=float(np.median(oos_ranks)),
    )


__all__ = ["cscv_pbo", "PBOResult"]
