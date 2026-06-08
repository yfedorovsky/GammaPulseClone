"""Tests for the vendored stats core (autoresearch/stats/*).

MUST run under the autoresearch venv (numpy/scipy/arch):
    .venv-autoresearch/Scripts/python scripts/test_stats_core.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from autoresearch.stats.deflated_sharpe import (  # noqa: E402
    sharpe_ratio, probabilistic_sharpe_ratio, expected_max_sharpe,
    deflated_sharpe_ratio, min_track_record_length, min_backtest_length, _moments,
)
from autoresearch.stats.cscv_pbo import cscv_pbo  # noqa: E402
from autoresearch.stats.cpcv import cpcv_splits, cpcv_oos_sharpes  # noqa: E402
from autoresearch.stats.spa import spa_beats_baseline  # noqa: E402


# === deflated_sharpe ===

def test_sharpe_basic():
    r = np.array([0.01, -0.005, 0.02, 0.0, 0.015])
    assert abs(sharpe_ratio(r) - (r.mean() / r.std(ddof=1))) < 1e-12
    assert sharpe_ratio([1.0]) == 0.0          # too short
    assert sharpe_ratio([0.0, 0.0, 0.0]) == 0.0  # zero variance


def test_psr_monotone_and_midpoint():
    # PSR at sr_star == sr is exactly 0.5 (Phi(0)).
    assert abs(probabilistic_sharpe_ratio(0.5, 0.5, 200) - 0.5) < 1e-9
    # Higher observed SR -> higher PSR.
    lo = probabilistic_sharpe_ratio(0.2, 0.0, 200)
    hi = probabilistic_sharpe_ratio(0.6, 0.0, 200)
    assert hi > lo > 0.5


def test_expected_max_sharpe_monotone():
    assert expected_max_sharpe(1, 1.0) == 0.0          # one trial -> no inflation
    e10 = expected_max_sharpe(10, 1.0)
    e100 = expected_max_sharpe(100, 1.0)
    e1000 = expected_max_sharpe(1000, 1.0)
    assert 0 < e10 < e100 < e1000                       # grows with N
    # Scales with sqrt(variance).
    assert abs(expected_max_sharpe(100, 4.0) - 2.0 * expected_max_sharpe(100, 1.0)) < 1e-9


def test_dsr_deflates_with_more_trials():
    # Same observed Sharpe; more trials (with dispersion) -> lower DSR.
    rng = np.random.default_rng(0)
    few = list(rng.normal(0, 0.3, 5))
    many = list(rng.normal(0, 0.3, 500))
    d_few = deflated_sharpe_ratio(0.8, few, T=250).dsr
    d_many = deflated_sharpe_ratio(0.8, many, T=250).dsr
    assert d_many < d_few
    assert 0.0 <= d_many <= 1.0 and 0.0 <= d_few <= 1.0


def test_dsr_high_for_strong_unique_signal():
    # A strong Sharpe with few, low-dispersion trials should deflate to ~1.
    res = deflated_sharpe_ratio(1.2, [0.1, 0.0, -0.05], T=500)
    assert res.dsr > 0.95, res


def test_min_track_record_length():
    assert min_track_record_length(0.0, 0.0, 3.0) == float("inf")  # no edge
    assert min_track_record_length(-0.3, 0.0, 3.0) == float("inf")
    t_strong = min_track_record_length(0.8, 0.0, 3.0)
    t_weak = min_track_record_length(0.2, 0.0, 3.0)
    assert t_weak > t_strong > 1.0   # weaker edge needs a longer track record


def test_min_backtest_length():
    assert min_backtest_length(1) == 0.0
    assert min_backtest_length(10) < min_backtest_length(1000)   # grows with N
    # T = 2 ln N / target^2
    assert abs(min_backtest_length(100, 1.0) - 2.0 * np.log(100)) < 1e-9


def test_moments_normal_like():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 1, 200_000)
    skew, kurt = _moments(r)
    assert abs(skew) < 0.05
    assert abs(kurt - 3.0) < 0.1   # non-excess kurtosis of a normal ~ 3


# === CSCV / PBO ===

def test_pbo_low_for_genuine_signal():
    rng = np.random.default_rng(7)
    T, N = 1600, 10
    M = rng.normal(0.0, 1.0, (T, N))
    M[:, 0] += 0.5            # column 0 has a real edge (per-obs Sharpe ~ 0.5).
    res = cscv_pbo(M, n_blocks=16)
    assert res.pbo < 0.10, res.pbo
    assert res.n_combinations == 12870  # C(16, 8)


def test_pbo_high_for_pure_noise():
    rng = np.random.default_rng(8)
    M = rng.normal(0.0, 1.0, (1600, 20))   # all noise, no real best
    res = cscv_pbo(M, n_blocks=14)
    assert res.pbo > 0.40, res.pbo         # IS-winner is ~random OOS


def test_pbo_input_validation():
    rng = np.random.default_rng(9)
    for bad in (lambda: cscv_pbo(rng.normal(size=(100, 5)), n_blocks=15),  # odd S
                lambda: cscv_pbo(rng.normal(size=(100, 1)), n_blocks=8),   # N<2
                lambda: cscv_pbo(rng.normal(size=(4, 5)), n_blocks=8)):    # T<S
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


# === CPCV ===

def test_cpcv_split_count_and_disjoint():
    splits = cpcv_splits(120, n_groups=6, k_test=2, embargo_pct=0.0)
    assert len(splits) == 15  # C(6, 2)
    for sp in splits:
        assert set(sp.train_idx).isdisjoint(set(sp.test_idx))


def test_cpcv_no_horizon_no_embargo_is_complement():
    n = 120
    splits = cpcv_splits(n, n_groups=6, k_test=2, t1=None, embargo_pct=0.0)
    sp = splits[0]
    # With instantaneous labels and no embargo, train == everything not in test.
    expected_train = sorted(set(range(n)) - set(sp.test_idx.tolist()))
    assert sp.train_idx.tolist() == expected_train


def test_cpcv_purges_overlapping_horizon():
    n = 120
    horizon = 5
    t1 = [min(i + horizon, n - 1) for i in range(n)]
    no_purge = cpcv_splits(n, 6, 2, t1=None, embargo_pct=0.0)[0]
    purged = cpcv_splits(n, 6, 2, t1=t1, embargo_pct=0.0)[0]
    # Purging with a horizon must remove some training rows that the no-horizon
    # split kept (those whose label window reaches into a test block).
    assert len(purged.train_idx) < len(no_purge.train_idx)
    assert set(purged.train_idx).isdisjoint(set(purged.test_idx))


def test_cpcv_embargo_removes_post_test_rows():
    n = 200
    no_emb = cpcv_splits(n, 5, 1, embargo_pct=0.0)
    emb = cpcv_splits(n, 5, 1, embargo_pct=0.05)  # embargo 10 rows
    # The first test group starts at index 0, so there are rows after it to embargo.
    assert len(emb[0].train_idx) < len(no_emb[0].train_idx)


def test_cpcv_oos_sharpe_distribution():
    rng = np.random.default_rng(3)
    returns = rng.normal(0.05, 1.0, 300)         # small positive edge
    splits = cpcv_splits(300, 6, 2, embargo_pct=0.01)
    sharpes = cpcv_oos_sharpes(returns, splits)
    assert len(sharpes) == len(splits)
    assert np.median(sharpes) > 0                # edge shows up OOS on average


# === SPA ===

def test_spa_detects_superior_candidate():
    rng = np.random.default_rng(11)
    base = rng.normal(0.0, 1.0, 400)
    cand = base + rng.normal(0.25, 0.2, 400)     # clearly higher mean return
    res = spa_beats_baseline(cand, base, reps=500, seed=1)
    assert res.beats_baseline is True, res
    assert res.pvalue_consistent < 0.05


def test_spa_rejects_non_superior_candidate():
    rng = np.random.default_rng(12)
    base = rng.normal(0.05, 1.0, 400)
    cand = rng.normal(0.0, 1.0, 400)             # worse mean than baseline
    res = spa_beats_baseline(cand, base, reps=500, seed=1)
    assert res.beats_baseline is False, res


def test_spa_length_mismatch_raises():
    try:
        spa_beats_baseline([0.1] * 10, [0.1] * 9, reps=100)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on length mismatch")


TESTS = [
    test_sharpe_basic,
    test_psr_monotone_and_midpoint,
    test_expected_max_sharpe_monotone,
    test_dsr_deflates_with_more_trials,
    test_dsr_high_for_strong_unique_signal,
    test_min_track_record_length,
    test_min_backtest_length,
    test_moments_normal_like,
    test_pbo_low_for_genuine_signal,
    test_pbo_high_for_pure_noise,
    test_pbo_input_validation,
    test_cpcv_split_count_and_disjoint,
    test_cpcv_no_horizon_no_embargo_is_complement,
    test_cpcv_purges_overlapping_horizon,
    test_cpcv_embargo_removes_post_test_rows,
    test_cpcv_oos_sharpe_distribution,
    test_spa_detects_superior_candidate,
    test_spa_rejects_non_superior_candidate,
    test_spa_length_mismatch_raises,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - autoresearch/stats core")
    print("=" * 70)
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  - {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  - {e!r}")
            failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
