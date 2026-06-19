"""Unit tests for server/collar_detector.py (JHEQX collar detection, #81).

Guards the two real regression risks:
  1. QUARTER-END SELECTION — quarter_end_expiry must pick the NEAREST future
     quarter-end, not the first month-3 match of next year (the bug fixed during
     build: month-then-year iteration returned 2027-03-31 before 2026-06-30).
  2. BAND-GATING CONTAMINATION — a deep-ITM round-number call with huge OI
     (e.g. 6000C when spot=7500) must NOT be mislabeled the short-call cap; the
     in-band near-OTM call (7600C) must win. Likewise the 5%-OTM hedge wall must
     not be mislabeled the short put.

Pure-logic tests (no DB / network). Usage: python scripts/test_collar_detector.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.collar_detector import (  # noqa: E402
    _pick_leg,
    _SHORT_CALL_BAND,
    _LONG_PUT_BAND,
    _SHORT_PUT_BAND,
    quarter_end_expiry,
)


# Synthetic 6/30 SPX OI shaped like the real 6/18 capture (spot 7500): the
# collar legs (7600C / 7000P / 6000P) plus the contamination (6000C round-number
# ITM, independent 7000P-class hedgers already folded into the leg OI).
SPOT = 7500.0
_OI = {
    ("C", 6000.0): 19920,   # deep-ITM round-number — MUST NOT be the cap
    ("C", 7000.0): 18283,   # ITM — outside the short-call band
    ("C", 7500.0): 10686,   # ATM
    ("C", 7600.0): 13090,   # the real short-call cap (+1.3%)
    ("C", 8000.0): 9540,    # also in-band but smaller than 7600
    ("P", 7000.0): 26110,   # long put (-6.7%)
    ("P", 6800.0): 14866,
    ("P", 6000.0): 66522,   # short put (-20%)
    ("P", 5900.0): 54146,
    ("P", 7400.0): 11695,   # near-money put — outside the long-put band's deep side
}
_MEDIAN = sorted(_OI.values())[len(_OI) // 2]


def test_quarter_end_picks_nearest_future():
    # From mid-Q2 2026, the next quarter-end is 2026-06-30, NOT 2027-03-31.
    got = quarter_end_expiry(datetime.date(2026, 6, 18))
    assert got == "2026-06-30", got


def test_quarter_end_rolls_past_expiry():
    # Day after a quarter-end rolls to the next quarter.
    got = quarter_end_expiry(datetime.date(2026, 7, 1))
    assert got == "2026-09-30", got


def test_quarter_end_is_weekday():
    for d in (datetime.date(2026, 1, 1), datetime.date(2026, 11, 15)):
        got = datetime.date.fromisoformat(quarter_end_expiry(d))
        assert got.weekday() < 5, got


def test_short_call_ignores_deep_itm_round_number():
    # Use a realistic full-chain median (thousands of near-zero strikes -> tiny
    # median); the toy 10-strike _MEDIAN is unrepresentative for the abnormal gate.
    leg = _pick_leg(_OI, "C", SPOT, _SHORT_CALL_BAND, median_oi=100)
    assert leg is not None
    # 6000C (19,920) is the largest call OI overall but is 20% ITM — gated out.
    assert leg["strike"] == 7600.0, leg
    assert leg["abnormal"] is True


def test_long_put_is_near_otm_not_the_floor():
    leg = _pick_leg(_OI, "P", SPOT, _LONG_PUT_BAND, _MEDIAN)
    assert leg is not None
    # 6000P (66,522) is the biggest put OI but is 20% OTM — belongs to the floor
    # band, not the long-put band. Long put = 7000P.
    assert leg["strike"] == 7000.0, leg


def test_short_put_is_the_deep_otm_floor():
    leg = _pick_leg(_OI, "P", SPOT, _SHORT_PUT_BAND, _MEDIAN)
    assert leg is not None
    assert leg["strike"] == 6000.0, leg


def test_three_legs_are_distinct():
    sc = _pick_leg(_OI, "C", SPOT, _SHORT_CALL_BAND, _MEDIAN)
    lp = _pick_leg(_OI, "P", SPOT, _LONG_PUT_BAND, _MEDIAN)
    sp = _pick_leg(_OI, "P", SPOT, _SHORT_PUT_BAND, _MEDIAN)
    strikes = {sc["strike"], lp["strike"], sp["strike"]}
    assert strikes == {7600.0, 7000.0, 6000.0}, strikes


def test_empty_band_returns_none():
    # No calls between spot and +12% in a puts-only map.
    only_puts = {("P", 6000.0): 50000}
    assert _pick_leg(only_puts, "C", SPOT, _SHORT_CALL_BAND, 50000) is None


def test_abnormal_flag_requires_4x_median():
    # A single tiny in-band call is found but flagged not-abnormal.
    tiny = {("C", 7600.0): 5}
    leg = _pick_leg(tiny, "C", SPOT, _SHORT_CALL_BAND, median_oi=1000)
    assert leg is not None and leg["abnormal"] is False, leg


TESTS = [
    test_quarter_end_picks_nearest_future,
    test_quarter_end_rolls_past_expiry,
    test_quarter_end_is_weekday,
    test_short_call_ignores_deep_itm_round_number,
    test_long_put_is_near_otm_not_the_floor,
    test_short_put_is_the_deep_otm_floor,
    test_three_legs_are_distinct,
    test_empty_band_returns_none,
    test_abnormal_flag_requires_4x_median,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/collar_detector.py (JHEQX collar, #81)")
    print("=" * 70)
    passed = failed = 0
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
