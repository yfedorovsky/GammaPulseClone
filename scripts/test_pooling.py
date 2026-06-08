"""Tests for autoresearch/pooling.py (C2 hierarchical partial pooling).

    .venv-autoresearch/Scripts/python scripts/test_pooling.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from autoresearch.pooling import beta_binomial_pool, normal_pool  # noqa: E402


def test_beta_small_group_shrinks_toward_pool():
    # A big anchor group near 0.45 and a tiny extreme group at 5/5=1.0.
    res = beta_binomial_pool({"big": (45, 100), "tiny": (5, 5)})
    big, tiny = res["big"], res["tiny"]
    # Tiny's raw 1.0 must shrink down toward the pooled mean; big barely moves.
    assert tiny.raw_rate == 1.0
    assert tiny.shrunk_rate < 0.95
    assert tiny.shrunk_rate < big.shrunk_rate + 0.5  # pulled toward pool, not stuck at 1
    assert abs(big.shrunk_rate - big.raw_rate) < abs(tiny.shrunk_rate - tiny.raw_rate)


def test_beta_ci_brackets_shrunk_and_in_unit():
    res = beta_binomial_pool({"a": (30, 100), "b": (8, 20), "c": (2, 4)})
    for r in res.values():
        assert 0.0 <= r.ci_low <= r.shrunk_rate <= r.ci_high <= 1.0, r
        # Smaller n -> wider credible interval.
    assert (res["c"].ci_high - res["c"].ci_low) > (res["a"].ci_high - res["a"].ci_low)


def test_beta_prior_mean_is_pooled_rate():
    res = beta_binomial_pool({"a": (50, 100), "b": (50, 100)})
    # Pooled rate = 100/200 = 0.5.
    assert abs(res["a"].prior_mean - 0.5) < 1e-9


def test_normal_small_group_shrinks_toward_grand():
    # Several concordant anchor groups (~0.4) pin a tight grand mean / low tau^2,
    # so a tiny extreme group is recognized as likely noise and shrinks hard.
    rng = np.random.default_rng(0)
    groups = {f"anchor{i}": list(rng.normal(0.4, 1.0, 200)) for i in range(5)}
    groups["small"] = [5.0, 4.0]            # tiny, extreme group
    res = normal_pool(groups)
    assert res["small"].raw_mean > 3.5
    assert res["small"].shrunk_mean < res["small"].raw_mean - 1.0  # pulled toward grand
    # Anchor groups barely move.
    assert abs(res["anchor0"].shrunk_mean - res["anchor0"].raw_mean) < 0.3


def test_normal_winsorize_limits_outlier_influence():
    base = [0.1] * 50
    res_no = normal_pool({"g": base + [100.0]}, winsor_q=0.0)
    res_w = normal_pool({"g": base + [100.0]}, winsor_q=0.05)
    assert res_w["g"].raw_mean < res_no["g"].raw_mean   # winsor pulls the outlier in


def test_empty_inputs_safe():
    assert beta_binomial_pool({}) == {}
    assert normal_pool({}) == {}
    assert beta_binomial_pool({"z": (0, 0)}) == {}      # n=0 dropped


TESTS = [
    test_beta_small_group_shrinks_toward_pool,
    test_beta_ci_brackets_shrunk_and_in_unit,
    test_beta_prior_mean_is_pooled_rate,
    test_normal_small_group_shrinks_toward_grand,
    test_normal_winsorize_limits_outlier_influence,
    test_empty_inputs_safe,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - autoresearch/pooling.py")
    print("=" * 70)
    passed = failed = 0
    for t in TESTS:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  - {e}"); failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  - {e!r}"); failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
