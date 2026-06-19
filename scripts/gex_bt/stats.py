"""GEX-backtest rigor harness — the shared scoring spine for Direction A.

This is the *same* deflation/overfitting machinery that graded (and killed) the
whale flow edge. We do NOT re-implement CPCV / DSR / PBO / slippage here — we
VENDOR-IN the Fable autoresearch modules under
``.claude/worktrees/feature+autoresearch-loop/autoresearch/`` so every GEX cell is
scored byte-for-byte the way a whale cohort was. Re-implementing would risk a
subtly different deflation and let a GEX "edge" pass a softer bar than whales
faced — exactly the asymmetry the pre-registration forbids.

Public surface (per the build spec):
  cpcv_mean_lower(returns)            -> (mean, lower_band)
  dsr(returns, n_trials)             -> (stat, is_positive)
  pbo_cscv(matrix)                   -> prob in [0,1]   (None if data insufficient)
  net_of_slippage(returns, setups)   -> haircut-applied returns
  base_rate_delta(edge, baseline)    -> (delta, significant)

Conventions pinned to the pre-reg (GEX_BACKTEST_PREREG.md):
  - Returns are per-setup signed R-multiples (move / fixed per-setup risk), the
    same economic unit the whale grader used (full stop ~= -1R).
  - DSR ``n_trials`` is the GLOBAL hypothesis x band x horizon trial count — the
    deflation must pay for every cell we looked at, not just the winner.
  - Slippage for GEX is SPOT-direction (these setups are spot trades, not a
    specific option contract), so the realistic analogue of the whale ask-in/
    bid-out fill is a per-side bps haircut on entry AND exit. Default 2 bps/side
    (4 bps round-trip) is the liquid-ETF/large-cap spot convention; callers can
    raise it per setup. This mirrors the parametric "spread haircut" arm of
    scripts/realistic_slippage_backtest.py, adapted from option premium to spot.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

# --- Vendor-in the Fable autoresearch stats (consistency with whale grading) ---
# We load the modules by FILE PATH under private names rather than putting the
# autoresearch dir on sys.path: this repo's scripts/gex_bt/ already defines a
# module called ``stats`` (this file), which would shadow the autoresearch
# ``stats`` PACKAGE on a plain import. Loading by spec sidesteps the name clash
# while still running the *exact* Fable code (same byte-for-byte deflation).
_AUTORESEARCH = (Path(__file__).resolve().parents[2]
                 / ".claude" / "worktrees" / "feature+autoresearch-loop"
                 / "autoresearch" / "stats")
if not _AUTORESEARCH.exists():  # pragma: no cover - environment guard
    raise RuntimeError(f"autoresearch stats dir not found: {_AUTORESEARCH}")


# Register the autoresearch ``stats`` dir as a PROPER package under a private
# name (``_fable_stats``) so the submodules' relative imports
# (``from .deflated_sharpe import ...``) resolve correctly — without colliding
# with this file, which the caller imports as the top-level ``stats`` module.
_PKG = "_fable_stats"
if _PKG not in sys.modules:
    pkg_spec = importlib.util.spec_from_file_location(
        _PKG, _AUTORESEARCH / "__init__.py",
        submodule_search_locations=[str(_AUTORESEARCH)])
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[_PKG] = pkg
    pkg_spec.loader.exec_module(pkg)


def _load(modname: str):
    """Import an autoresearch stats submodule under the private package."""
    full = f"{_PKG}.{modname}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, _AUTORESEARCH / f"{modname}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


_ds = _load("deflated_sharpe")
_cpcv = _load("cpcv")
_cscv = _load("cscv_pbo")

cpcv_splits = _cpcv.cpcv_splits
cpcv_oos_sharpes = _cpcv.cpcv_oos_sharpes
sharpe_ratio = _ds.sharpe_ratio
deflated_sharpe_ratio = _ds.deflated_sharpe_ratio
_moments = _ds._moments
cscv_pbo = _cscv.cscv_pbo

# Round-trip spot slippage: 2 bps per side (entry ask, exit bid) on the move's
# notional, the liquid-instrument analogue of the whale ask-in/bid-out haircut.
DEFAULT_SLIP_BPS_PER_SIDE = 2.0


# --------------------------------------------------------------------------- #
# 1. CPCV mean + lower band
# --------------------------------------------------------------------------- #
def cpcv_mean_lower(returns: Sequence[float],
                    n_groups: int = 6, k_test: int = 2,
                    embargo_pct: float = 0.01,
                    z: float = 1.645) -> tuple[float, float]:
    """Pooled mean R and a CPCV out-of-sample LOWER band.

    Runs the purged+embargoed combinatorial splits (the same machinery as the
    whale gate) and, for each OOS test block, records the block's mean R. The
    lower band is ``mean(oos_means) - z * sd(oos_means)`` — a one-sided
    (default 95%, z=1.645) floor on the out-of-sample mean. The pre-reg pass bar
    is ``lower_band > 0``.

    Why OOS-block means (not the single-series Sharpe path): the pass bar is
    stated on mean R, so the band must be on the mean. CPCV gives us many
    near-independent OOS estimates of that mean; their spread is the honest
    uncertainty after purging horizon-overlap leakage.

    Returns (pooled_mean, lower_band). Degenerate (too few samples) -> the
    pooled mean with a lower band of -inf (cannot clear the bar).
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    pooled = float(r.mean()) if n else 0.0
    if n < max(n_groups, 4):
        return pooled, float("-inf")
    splits = cpcv_splits(n, n_groups=n_groups, k_test=k_test,
                         embargo_pct=embargo_pct)
    oos_means = []
    for sp in splits:
        seg = r[sp.test_idx]
        if seg.size:
            oos_means.append(float(seg.mean()))
    if len(oos_means) < 2:
        return pooled, float("-inf")
    arr = np.asarray(oos_means, dtype=float)
    lower = float(arr.mean() - z * arr.std(ddof=1))
    return pooled, lower


# --------------------------------------------------------------------------- #
# 2. Deflated Sharpe
# --------------------------------------------------------------------------- #
def dsr(returns: Sequence[float], n_trials: int) -> tuple[float, bool]:
    """Deflated Sharpe of a return series, deflated for ``n_trials`` selections.

    ``n_trials`` is the GLOBAL hypothesis x band x horizon trial count (every
    cell we examined), so the E[max Sharpe | N] hurdle pays for selection across
    the whole matrix — not a per-cell freebie. The cross-trial Sharpe variance is
    estimated by the CPCV OOS-Sharpe spread of THIS series (a conservative,
    self-contained proxy when the family's full Sharpe vector isn't threaded in).

    Returns (dsr_stat, is_positive) where dsr_stat is P(true SR > E[max SR | N])
    in [0,1] and is_positive := dsr_stat > 0.5 (more likely than not the SR
    survives deflation). NaN/degenerate -> (0.0, False).
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    T = r.size
    if T < 3:
        return 0.0, False
    sr = sharpe_ratio(r)
    skew, kurt = _moments(r)
    # Cross-trial Sharpe variance proxy: the CPCV OOS-Sharpe dispersion of this
    # series. Falls back to a single-trial (no inflation) estimate if too short.
    try:
        splits = cpcv_splits(T, n_groups=min(6, max(2, T // 5)), k_test=2)
        sr_estimates = cpcv_oos_sharpes(r, splits)
    except Exception:
        sr_estimates = [sr]
    if len(sr_estimates) < 2:
        sr_estimates = [sr, sr]
    res = deflated_sharpe_ratio(sr_observed=sr, sr_estimates=sr_estimates, T=T,
                                skew=skew, kurt=kurt,
                                n_trials=max(int(n_trials), 1))
    stat = float(res.dsr)
    if not np.isfinite(stat):
        return 0.0, False
    return stat, stat > 0.5


# --------------------------------------------------------------------------- #
# 3. PBO via CSCV
# --------------------------------------------------------------------------- #
def pbo_cscv(matrix) -> Optional[float]:
    """Probability of Backtest Overfitting from a (T observations x N configs)
    matrix, one column per (band x horizon) variant of a hypothesis.

    Thin pass-through to the Fable CSCV implementation (auto block-count by T).
    Returns the PBO probability in [0,1], or None when T is too small for a
    meaningful PBO (INSUFFICIENT_DATA) — callers MUST treat None as N/A, never as
    danger. Pre-reg pass bar: PBO < 0.5.
    """
    M = np.asarray(matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        return None
    res = cscv_pbo(M)
    return res.pbo  # None when status == INSUFFICIENT_DATA.


# --------------------------------------------------------------------------- #
# 4. Net-of-slippage
# --------------------------------------------------------------------------- #
def net_of_slippage(returns: Sequence[float],
                    setups: Optional[Sequence[dict]] = None,
                    slip_bps_per_side: float = DEFAULT_SLIP_BPS_PER_SIDE
                    ) -> np.ndarray:
    """Apply a realistic ask/bid haircut to per-setup R-multiples.

    GEX setups are SPOT-direction trades. The realistic-fill analogue of the
    whale ask-in/bid-out model is a per-side bps haircut on both entry and exit,
    charged in R units (haircut / per-setup risk). Round-trip cost in price terms
    is ``2 * slip_bps_per_side`` bps of the instrument's notional.

    ``setups`` (parallel to ``returns``) may carry per-row context to size the
    haircut honestly:
      - ``risk_pct``  : the fixed per-setup risk (band width / ATR fraction) in
                        percent that R is denominated in; the bps cost is divided
                        by it to convert price-cost -> R-cost. Defaults to the
                        round-trip bps itself (=> -1.0 R cost floor avoided) when
                        absent.
      - ``slip_bps_per_side`` : per-row override (wider for illiquid names).
    With no ``setups``, a uniform round-trip haircut of
    ``2*slip_bps_per_side`` bps converted at a 1%-risk default is applied.

    Returns a float array of net R-multiples (same length as ``returns``).
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    out = r.copy()
    if n == 0:
        return out
    for i in range(n):
        bps_side = slip_bps_per_side
        risk_pct = 1.0  # default: R denominated in 1% risk units.
        if setups is not None and i < len(setups) and isinstance(setups[i], dict):
            s = setups[i]
            bps_side = float(s.get("slip_bps_per_side", bps_side))
            rp = s.get("risk_pct")
            if rp is not None and float(rp) > 0:
                risk_pct = float(rp)
        rt_cost_pct = 2.0 * bps_side / 100.0  # bps -> percent of notional.
        cost_R = rt_cost_pct / risk_pct       # price-cost -> R units.
        out[i] = r[i] - cost_R                # cost always reduces the edge.
    return out


# --------------------------------------------------------------------------- #
# 5. Base-rate delta
# --------------------------------------------------------------------------- #
@dataclass
class BaseRateResult:
    delta: float
    significant: bool
    t_stat: float
    p_value: float
    n_edge: int
    n_base: int


def base_rate_delta(edge_returns: Sequence[float],
                    baseline_returns: Sequence[float],
                    alpha: float = 0.05) -> tuple[float, bool]:
    """Does the conditioned (GEX-setup) return beat the unconditional base rate?

    delta = mean(edge) - mean(baseline). Significance via Welch's t-test
    (unequal variance, unequal n) — the edge sample is small and the base-rate
    sample is large, so equal-variance pooling would understate the SE. One-sided
    at ``alpha``: significant := delta > 0 AND one-sided p < alpha.

    Returns (delta, significant). The pre-reg requires the edge to BEAT the
    per-ticker base rate, not merely be > 0 in absolute terms.
    """
    e = np.asarray(edge_returns, dtype=float)
    b = np.asarray(baseline_returns, dtype=float)
    e = e[np.isfinite(e)]
    b = b[np.isfinite(b)]
    ne, nb = e.size, b.size
    if ne < 2 or nb < 2:
        return (float(e.mean() - b.mean()) if ne and nb else 0.0), False
    me, mb = e.mean(), b.mean()
    delta = float(me - mb)
    ve, vb = e.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(ve / ne + vb / nb)
    if se == 0:
        return delta, delta > 0
    t = delta / se
    # Welch-Satterthwaite dof.
    num = (ve / ne + vb / nb) ** 2
    den = (ve / ne) ** 2 / (ne - 1) + (vb / nb) ** 2 / (nb - 1)
    dof = num / den if den > 0 else (ne + nb - 2)
    from scipy.stats import t as _t
    p_one_sided = float(_t.sf(t, dof))  # P(T > t): upper tail.
    significant = (delta > 0) and (p_one_sided < alpha)
    return delta, significant


def base_rate_delta_full(edge_returns, baseline_returns, alpha=0.05) -> BaseRateResult:
    """Same as base_rate_delta but returns the full diagnostic record."""
    e = np.asarray(edge_returns, dtype=float)
    b = np.asarray(baseline_returns, dtype=float)
    e = e[np.isfinite(e)]; b = b[np.isfinite(b)]
    ne, nb = e.size, b.size
    delta, sig = base_rate_delta(e, b, alpha)
    if ne < 2 or nb < 2:
        return BaseRateResult(delta, sig, 0.0, 1.0, ne, nb)
    ve, vb = e.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(ve / ne + vb / nb)
    t = delta / se if se else 0.0
    num = (ve / ne + vb / nb) ** 2
    den = (ve / ne) ** 2 / (ne - 1) + (vb / nb) ** 2 / (nb - 1)
    dof = num / den if den > 0 else (ne + nb - 2)
    from scipy.stats import t as _t
    p = float(_t.sf(t, dof))
    return BaseRateResult(delta, sig, float(t), p, ne, nb)


__all__ = [
    "cpcv_mean_lower", "dsr", "pbo_cscv", "net_of_slippage",
    "base_rate_delta", "base_rate_delta_full", "BaseRateResult",
    "DEFAULT_SLIP_BPS_PER_SIDE",
]
