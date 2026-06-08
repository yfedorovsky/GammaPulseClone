"""Combinatorial Purged Cross-Validation (CPCV) with embargo.

Reference:
  Lopez de Prado (2018), "Advances in Financial Machine Learning", ch. 7 & 12
  (purging, embargo, combinatorial backtest paths).

The leakage CPCV defends against: when a sample's label/outcome is realized over a
holding horizon, a training sample whose horizon OVERLAPS a test sample leaks
future information. CPCV (a) forms test sets combinatorially (choose k of G
groups) to produce many OOS paths, (b) PURGES training samples whose horizon
overlaps the test span, and (c) EMBARGOES a buffer of training samples
immediately following each test block.

Time is discretized to integer sample positions (the per-trade series is ordered
in time). ``t1[i]`` is the position at which sample i's outcome is realized
(default: i itself — instantaneous). Embargo is a fraction of total samples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Optional, Sequence

import numpy as np

from .deflated_sharpe import sharpe_ratio


@dataclass
class CPCVSplit:
    test_idx: np.ndarray
    train_idx: np.ndarray
    test_groups: tuple[int, ...]


def _contiguous_blocks(sorted_idx: np.ndarray) -> list[tuple[int, int]]:
    """Collapse a sorted index array into [start, end] contiguous runs."""
    if sorted_idx.size == 0:
        return []
    blocks = []
    start = prev = int(sorted_idx[0])
    for v in sorted_idx[1:]:
        v = int(v)
        if v == prev + 1:
            prev = v
        else:
            blocks.append((start, prev))
            start = prev = v
    blocks.append((start, prev))
    return blocks


def cpcv_splits(n_samples: int, n_groups: int = 6, k_test: int = 2,
                t1: Optional[Sequence[int]] = None,
                embargo_pct: float = 0.01) -> list[CPCVSplit]:
    """Generate purged + embargoed combinatorial train/test splits.

    Args:
        n_samples: number of ordered samples.
        n_groups: G, number of contiguous groups to partition samples into.
        k_test: number of groups per test set. C(G, k_test) splits are produced.
        t1: per-sample realization position (horizon end). Default = identity.
        embargo_pct: embargo length as a fraction of n_samples.

    Returns:
        list of CPCVSplit (test_idx, train_idx, test_groups).
    """
    if n_samples < n_groups:
        raise ValueError("n_samples must be >= n_groups")
    if not (1 <= k_test < n_groups):
        raise ValueError("require 1 <= k_test < n_groups")

    idx = np.arange(n_samples)
    if t1 is None:
        t1_arr = idx.copy()
    else:
        t1_arr = np.asarray(t1, dtype=int)
        if t1_arr.shape[0] != n_samples:
            raise ValueError("t1 must have length n_samples")
    embargo = int(math.ceil(embargo_pct * n_samples))

    groups = np.array_split(idx, n_groups)  # contiguous, near-equal.

    splits: list[CPCVSplit] = []
    for test_grp in combinations(range(n_groups), k_test):
        test_idx = np.sort(np.concatenate([groups[g] for g in test_grp]))
        in_test = np.zeros(n_samples, dtype=bool)
        in_test[test_idx] = True
        train_keep = ~in_test

        # For each contiguous test block, purge overlapping train obs + embargo.
        for (t_start, t_end) in _contiguous_blocks(test_idx):
            # Test block's realized time span (labels can extend past t_end).
            span_start = t_start
            span_end = int(max(t_end, t1_arr[t_start:t_end + 1].max()))
            # Purge train obs whose horizon [j, t1[j]] overlaps [span_start, span_end].
            # Overlap iff  j <= span_end  AND  t1[j] >= span_start.
            overlap = (idx <= span_end) & (t1_arr >= span_start)
            train_keep &= ~overlap
            # Embargo: drop the `embargo` train obs immediately after the block.
            if embargo > 0:
                emb_lo = t_end + 1
                emb_hi = min(n_samples, t_end + 1 + embargo)
                if emb_lo < emb_hi:
                    train_keep[emb_lo:emb_hi] = False

        train_idx = idx[train_keep]
        splits.append(CPCVSplit(test_idx=test_idx, train_idx=train_idx,
                                test_groups=test_grp))
    return splits


def cpcv_oos_sharpes(returns: Sequence[float], splits: list[CPCVSplit]) -> list[float]:
    """OOS Sharpe of a single return series over each split's test set.

    Produces the distribution of OOS Sharpes the gate inspects (median/fraction
    positive) — the combinatorial analogue of a single walk-forward number.
    """
    r = np.asarray(returns, dtype=float)
    out = []
    for sp in splits:
        seg = r[sp.test_idx]
        out.append(sharpe_ratio(seg))
    return out


__all__ = ["cpcv_splits", "cpcv_oos_sharpes", "CPCVSplit"]
