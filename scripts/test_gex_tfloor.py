"""Unit tests for the 0DTE true-intraday-T fix in server/gex.py (#72).

The OLD BSM gamma/charm fallback floored time-to-expiry at 0.5 calendar days
(1/720 yr) for EVERY expiration, including same-day (0DTE). For a 0DTE option
observed intraday (e.g. 11:35 ET, ~4.4h to the 16:00 ET close) that OVERSTATED
T by ~2-3x. Since ATM gamma scales ~1/sqrt(T), overstating T UNDERSTATES the
true 0DTE ATM gamma spike at the pin — pushing the king to the wrong strike on
pinning days (the QQQ 6/15 symptom: ours 740 vs upstream 745).

The fix (`server.gex._bsm_t_floor_years`):
  - days == 0  → real seconds-to-16:00-ET-close, clamped at a ~5-min UNDERFLOW
                 floor so BSM stays finite at/after the close.
  - days >= 1  → days / 365.0, IDENTICAL to the pre-#72 formula (unchanged).

These tests are PURE MATH — no chain / IV provider / live data needed. ET
wall-clock is injected via `now_et` so the tests are deterministic.

Usage:
    python scripts/test_gex_tfloor.py
"""
from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.gex import (  # noqa: E402
    _bsm_gamma,
    _bsm_t_floor_years,
    _T_UNDERFLOW_FLOOR_YEARS,
    _MARKET_CLOSE_HOUR_ET,
)

# Try real ET tz for the injected "now"; fall back to naive (math is identical
# because _bsm_t_floor_years only subtracts two same-tz datetimes).
try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None


def _et(hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A 6/15/2026 ET wall-clock time for injection into _bsm_t_floor_years."""
    return datetime(2026, 6, 15, hour, minute, second, tzinfo=_ET)


_YEAR_SECONDS = 365.0 * 24.0 * 60.0 * 60.0


# === (1) 0DTE ATM gamma rises MONOTONICALLY as seconds-to-close shrinks ===
# The core #72 claim: later in the session (less time left) => larger ATM gamma.
# NOTE: this monotonicity holds for an *exactly-ATM* strike (K == S). For an
# OTM strike, BSM gamma peaks and then COLLAPSES toward 0 as T -> 0 (the option
# goes binary) — that's correct theory, not a bug, so we anchor the monotonicity
# claim at the pin where it's the load-bearing #72 effect.

def test_0dte_atm_gamma_monotonic_increasing_into_close():
    S, iv = 743.81, 0.14179  # QQQ 6/15 pin spot + actual 0DTE IV
    K = S  # exactly ATM — the strike whose gamma the #72 fix must un-suppress
    # Walk the session from open toward close: 10:00 .. 15:55.
    times = [_et(10, 0), _et(11, 35), _et(13, 0), _et(14, 30), _et(15, 45),
             _et(15, 55)]
    gammas = []
    for now in times:
        T = _bsm_t_floor_years(0, now_et=now)
        gammas.append(_bsm_gamma(S, K, iv, T))
    # Strictly increasing as we approach the close (T shrinks → ATM gamma grows).
    for earlier, later in zip(gammas, gammas[1:]):
        assert later > earlier, (
            f"ATM gamma must rise into the close; got non-increasing pair "
            f"{earlier:.6f} -> {later:.6f} across {gammas}"
        )


def test_0dte_seconds_to_close_is_true_intraday_T():
    """At 11:35 ET the fallback T must equal the REAL ~4h25m-to-close, not the
    old 0.5-day (12h) floor."""
    now = _et(11, 35)
    T = _bsm_t_floor_years(0, now_et=now)
    expected_seconds = (16 - 11) * 3600 - 35 * 60  # 4h25m to 16:00
    expected_T = expected_seconds / _YEAR_SECONDS
    assert math.isclose(T, expected_T, rel_tol=1e-9), (
        f"0DTE T at 11:35 ET should be {expected_T:.8e} yr "
        f"(~{expected_seconds}s to close), got {T:.8e}"
    )
    old_half_day_T = 0.5 / 365.0
    assert T < old_half_day_T, (
        f"true intraday T ({T:.6e}) must be SMALLER than the old 0.5-day floor "
        f"({old_half_day_T:.6e}) at 11:35 ET"
    )


def test_0dte_true_T_understatement_relative_to_old_floor():
    """Sanity on direction & magnitude: at the 745 pin, true-intraday-T gamma
    must EXCEED old-0.5-day-floor gamma (we were understating it)."""
    S, K, iv = 743.81, 745.0, 0.14179
    now = _et(11, 35)
    true_T = _bsm_t_floor_years(0, now_et=now)
    old_T = 0.5 / 365.0
    g_true = _bsm_gamma(S, K, iv, true_T)
    g_old = _bsm_gamma(S, K, iv, old_T)
    assert g_true > g_old, (
        f"true-T ATM gamma ({g_true:.6f}) must exceed old-floor gamma "
        f"({g_old:.6f}) — the #72 understatement"
    )
    # 1/sqrt(T) ratio: at 11:35 the boost should be ~1.45x (matches diagnosis).
    ratio = g_true / g_old
    assert 1.30 < ratio < 1.60, (
        f"expected ATM gamma boost ~1.45x at 11:35 ET, got {ratio:.3f}x"
    )


# === (2) UNDERFLOW floor caps gamma: finite, no NaN/inf at/after close ===

def test_underflow_floor_at_exactly_close():
    """At exactly 16:00 ET, seconds_to_close == 0 → clamp to underflow floor."""
    T = _bsm_t_floor_years(0, now_et=_et(_MARKET_CLOSE_HOUR_ET, 0, 0))
    assert T == _T_UNDERFLOW_FLOOR_YEARS, (
        f"at 16:00 ET T must equal underflow floor {_T_UNDERFLOW_FLOOR_YEARS:.6e}, "
        f"got {T:.6e}"
    )


def test_underflow_floor_after_close():
    """After the close (16:30 ET) seconds_to_close < 0 → still the floor."""
    T = _bsm_t_floor_years(0, now_et=_et(16, 30))
    assert T == _T_UNDERFLOW_FLOOR_YEARS, (
        f"post-close T must clamp to underflow floor, got {T:.6e}"
    )


def test_gamma_finite_at_and_after_close():
    """ATM gamma must stay finite (no NaN/inf) at and after the close even as
    the option's true life hits zero — that's what the floor guarantees."""
    S, K, iv = 743.81, 745.0, 0.14179
    for now in [_et(16, 0, 0), _et(16, 30), _et(17, 0)]:
        T = _bsm_t_floor_years(0, now_et=now)
        g = _bsm_gamma(S, K, iv, T)
        assert math.isfinite(g), f"gamma not finite at/after close: {g!r} (T={T})"
        assert g > 0.0, f"gamma should be positive & bounded, got {g!r}"


def test_underflow_floor_caps_gamma_just_before_close():
    """One second before close, seconds-to-close (1s) is BELOW the 5-min floor,
    so T clamps to the floor. The floor is PROTECTIVE: at an exactly-ATM strike
    the uncapped 1s gamma would explode (1/sqrt(T) -> huge); the cap holds it at
    a finite, bounded value."""
    one_sec_before = _et(15, 59, 59)
    T = _bsm_t_floor_years(0, now_et=one_sec_before)
    assert T == _T_UNDERFLOW_FLOOR_YEARS, (
        "1s-to-close must clamp to the 5-min underflow floor, not 1s"
    )
    S, K, iv = 743.81, 743.81, 0.14179  # exactly ATM: clean 1/sqrt(T) regime
    g_floor = _bsm_gamma(S, K, iv, _T_UNDERFLOW_FLOOR_YEARS)
    g_1s = _bsm_gamma(S, K, iv, T)
    assert math.isclose(g_1s, g_floor, rel_tol=1e-12), (
        "gamma at 1s-to-close must equal the underflow-floor gamma (capped)"
    )
    assert math.isfinite(g_floor) and g_floor > 0.0, (
        f"capped ATM gamma must be finite & positive, got {g_floor!r}"
    )
    # A true 1s T (uncapped) ATM gamma would be MUCH larger (sqrt(300/1) ~ 17x)
    # — confirming the floor is what bounds the spike.
    g_uncapped = _bsm_gamma(S, K, iv, 1.0 / _YEAR_SECONDS)
    assert g_uncapped > g_floor, (
        "uncapped 1s ATM gamma should exceed the capped value (floor is "
        f"protective): uncapped={g_uncapped:.4f} vs capped={g_floor:.4f}"
    )


# === (3) days >= 1: T IDENTICAL to the prior formula (non-0DTE unchanged) ===

def test_non_0dte_T_identical_to_old_formula():
    """For days >= 1 the fix must reproduce days/365.0 EXACTLY, independent of
    the ET wall-clock (intraday time must NOT leak into non-0DTE)."""
    for days in [1, 2, 3, 7, 30, 45, 200]:
        expected = days / 365.0
        # Same regardless of injected time-of-day.
        for now in [_et(9, 30), _et(11, 35), _et(16, 0), _et(23, 59)]:
            got = _bsm_t_floor_years(days, now_et=now)
            assert got == expected, (
                f"days={days} at {now}: T must be exactly {expected!r}, "
                f"got {got!r}"
            )


def test_non_0dte_gamma_unchanged_vs_explicit_old_formula():
    """End-to-end: BSM gamma for a 3DTE contract must be bit-identical whether
    computed via _bsm_t_floor_years or the literal old days/365 expression."""
    S, K, iv, days = 743.81, 740.0, 0.16, 3
    T_new = _bsm_t_floor_years(days, now_et=_et(11, 35))
    T_old = max(days / 365.0, 0.5 / 365.0)  # old expression; days>=1 so == days/365
    assert _bsm_gamma(S, K, iv, T_new) == _bsm_gamma(S, K, iv, T_old), (
        "non-0DTE gamma must be unchanged by the #72 fix"
    )


def test_boundary_days_zero_vs_one_diverge():
    """days==0 uses intraday seconds; days==1 uses 1/365. They must differ
    (confirms the 0DTE branch is actually special-cased)."""
    now = _et(11, 35)
    t0 = _bsm_t_floor_years(0, now_et=now)
    t1 = _bsm_t_floor_years(1, now_et=now)
    assert t0 != t1, "0DTE and 1DTE T must differ"
    assert t0 < t1, "0DTE T (hours) must be smaller than 1DTE T (1 day)"


# === Test runner ===

TESTS = [
    test_0dte_atm_gamma_monotonic_increasing_into_close,
    test_0dte_seconds_to_close_is_true_intraday_T,
    test_0dte_true_T_understatement_relative_to_old_floor,
    test_underflow_floor_at_exactly_close,
    test_underflow_floor_after_close,
    test_gamma_finite_at_and_after_close,
    test_underflow_floor_caps_gamma_just_before_close,
    test_non_0dte_T_identical_to_old_formula,
    test_non_0dte_gamma_unchanged_vs_explicit_old_formula,
    test_boundary_days_zero_vs_one_diverge,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/gex.py 0DTE true-intraday-T floor (#72)")
    print("=" * 70)
    passed = 0
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  — {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR   {t.__name__}  — {e!r}")
            failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed+failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
