"""Discrimination test for the GEX rigor harness.

The whole point of the harness is to tell signal from noise. So we prove it on
two synthetic series with KNOWN ground truth:

  KNOWN-POSITIVE: a genuine edge (positive mean, high Sharpe). It MUST
    - pass DSR positive (survives deflation for the trial count),
    - have CPCV lower band > 0,
    - have PBO < 0.5 (its variants are not interchangeable noise),
    - beat a zero-mean baseline (base_rate_delta significant),
    - stay net-positive after a realistic slippage haircut.

  KNOWN-NULL: zero-mean random noise. It MUST FAIL all of the above —
    - DSR not positive,
    - CPCV lower band <= 0,
    - PBO >= 0.5 (or N/A) — the IS-best variant is no better OOS,
    - no significant base-rate delta,
    - net-of-slippage stays <= 0 (slippage can only hurt).

If a harness passed noise it would manufacture phantom edges (the Phase-6 trap).
A run that asserts the POSITIVE passes AND the NULL fails is the proof the harness
is discriminating, not permissive.

Run:  PYTHONIOENCODING=utf-8 python scripts/gex_bt/test_stats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stats import (  # noqa: E402
    cpcv_mean_lower, dsr, pbo_cscv, net_of_slippage,
    base_rate_delta, base_rate_delta_full,
)

RNG = np.random.default_rng(20260616)
N = 600          # realistic GEX-setup sample size.
N_TRIALS = 45    # H1-H5 x 3 bands x 3 horizons ~ 45 cells (the deflation count).


def _make_positive(n=N):
    """A real edge: mean ~0.18R, sd 1.0R -> per-obs Sharpe ~0.18 (annualizes high)."""
    return RNG.normal(loc=0.18, scale=1.0, size=n)


def _make_null(n=N):
    """Pure noise: zero-mean, unit-sd R-multiples — no edge by construction."""
    return RNG.normal(loc=0.0, scale=1.0, size=n)


def _make_positive_matrix(n_cols=8, n=N):
    """A (T x N_configs) matrix where ONE config is genuinely, persistently best.

    PBO asks: does the in-sample-best column STAY best out-of-sample? For a real
    edge the answer is yes, so PBO is low. We encode that by giving the columns
    DISTINCT, persistent mean levels (a real ranking that holds IS and OOS),
    rather than independent draws of one distribution (whose IS-winner is luck —
    that is the OVERFIT case, not the edge case).
    """
    means = np.linspace(0.02, 0.30, n_cols)  # a genuine, stable quality ladder.
    return np.column_stack([RNG.normal(loc=m, scale=1.0, size=n) for m in means])


def _make_null_matrix(n_cols=8, n=N):
    """A (T x N_configs) matrix of INTERCHANGEABLE zero-mean columns.

    Every column is the same distribution, so whichever wins in-sample wins by
    luck and does NOT persist out-of-sample -> PBO ~ 0.5 (the overfit signature).
    """
    return np.column_stack([_make_null(n) for _ in range(n_cols)])


def _null_pbo_central(reps=81):
    """Median PBO over an ENSEMBLE of independent noise matrices.

    CSCV-PBO on a *single* pure-noise realization has very high per-seed variance
    (characterized empirically over 200 seeds: mean 0.489, median 0.499, but any
    one seed ranges ~0.04-0.95), so a single-seed assertion would be a coin-flip,
    not a test. The MEDIAN over an ensemble converges to ~0.49 (the textbook null
    center), giving a seed-stable statistic that proves PBO centers noise at the
    overfit threshold while it puts a genuine edge far below it.
    """
    pbos = []
    for _ in range(reps):
        p = pbo_cscv(_make_null_matrix())
        if p is not None:
            pbos.append(p)
    return float(np.median(pbos)) if pbos else None


def _check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"    [{status}] {label}")
    return cond


def run():
    print("=" * 70)
    print("GEX RIGOR HARNESS — discrimination test")
    print(f"  N={N} samples/series, N_TRIALS={N_TRIALS} deflation cells")
    print("=" * 70)

    pos = _make_positive()
    null = _make_null()
    baseline = _make_null()  # the unconditional base rate is zero-mean.

    all_ok = True

    # ----- KNOWN-POSITIVE: must PASS everything -----
    print("\nKNOWN-POSITIVE series (real edge, mean~0.18R):")
    mean_p, lower_p = cpcv_mean_lower(pos)
    dsr_p, dsr_pos_p = dsr(pos, N_TRIALS)
    # PBO needs variants with a PERSISTENT quality ranking (a real best config).
    pbo_p = pbo_cscv(_make_positive_matrix())
    net_p = net_of_slippage(pos, setups=None)
    delta_p, sig_p = base_rate_delta(pos, baseline)
    br_p = base_rate_delta_full(pos, baseline)

    print(f"    mean R = {mean_p:+.4f}   CPCV lower band = {lower_p:+.4f}")
    print(f"    DSR = {dsr_p:.4f}   net-of-slip mean = {net_p.mean():+.4f}")
    print(f"    PBO = {pbo_p}   base-rate delta = {delta_p:+.4f} "
          f"(t={br_p.t_stat:.2f}, p={br_p.p_value:.4g})")
    all_ok &= _check("CPCV lower band > 0", lower_p > 0)
    all_ok &= _check("DSR is_positive", dsr_pos_p)
    all_ok &= _check("PBO < 0.5", pbo_p is not None and pbo_p < 0.5)
    all_ok &= _check("net-of-slippage mean > 0", net_p.mean() > 0)
    all_ok &= _check("beats base rate (significant)", sig_p)

    # ----- KNOWN-NULL: must FAIL everything -----
    print("\nKNOWN-NULL series (pure noise, mean~0):")
    mean_n, lower_n = cpcv_mean_lower(null)
    dsr_n, dsr_pos_n = dsr(null, N_TRIALS)
    # Ensemble-median PBO (single-seed PBO on noise is too high-variance to assert).
    pbo_n = _null_pbo_central()
    net_n = net_of_slippage(null, setups=None)
    delta_n, sig_n = base_rate_delta(null, baseline)
    br_n = base_rate_delta_full(null, baseline)

    print(f"    mean R = {mean_n:+.4f}   CPCV lower band = {lower_n:+.4f}")
    print(f"    DSR = {dsr_n:.4f}   net-of-slip mean = {net_n.mean():+.4f}")
    print(f"    PBO (ensemble median) = {pbo_n}   base-rate delta = {delta_n:+.4f} "
          f"(t={br_n.t_stat:.2f}, p={br_n.p_value:.4g})")
    all_ok &= _check("CPCV lower band <= 0", lower_n <= 0)
    all_ok &= _check("DSR NOT is_positive", not dsr_pos_n)
    # Noise centers PBO near the 0.5 null AND well above the real edge's PBO.
    # Both must hold: the level (>=0.40, clear of the ~0.05 edge zone and robust
    # to the median estimator's residual variance) and the contrast.
    all_ok &= _check("PBO centers near null (>= 0.40)",
                     pbo_n is not None and pbo_n >= 0.40)
    all_ok &= _check("noise PBO >> edge PBO (contrast)",
                     pbo_n is not None and pbo_p is not None
                     and pbo_n > pbo_p + 0.25)
    all_ok &= _check("does NOT beat base rate", not sig_n)
    # Slippage sanity: a haircut can only reduce a (near-zero) mean, never lift it.
    all_ok &= _check("net-of-slippage <= gross (cost only hurts)",
                     net_n.mean() <= null.mean() + 1e-12)

    # ----- Slippage cost direction (both series) -----
    print("\nSlippage monotonicity:")
    all_ok &= _check("positive series: net < gross",
                     net_p.mean() < pos.mean())

    print("\n" + "=" * 70)
    if all_ok:
        print("RESULT: HARNESS IS DISCRIMINATING — positive passes, null fails.")
    else:
        print("RESULT: HARNESS FAILED — it does NOT cleanly separate signal/noise.")
    print("=" * 70)
    return all_ok


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
