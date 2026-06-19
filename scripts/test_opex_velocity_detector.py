"""Unit tests for server/opex_velocity_detector.py (Detector A, #84).

Covers the three things that must not regress:
  1. OPEX-DAY GATE is holiday-shift aware. June 2026 OPEX is 6/18 (Thursday)
     because the 3rd Friday 6/19 is Juneteenth. Normal months = 3rd Friday.
  2. PURE DETECTOR reproduces the MRVL 6/18 validation: exactly 1 velocity break
     (the 15:50 −3.41% candle), 0 false positives at the 1.5% threshold.
  3. LIVE MONITOR rolling-window logic: fires on a ~1-min drop, respects cooldown
     (one fire per cascade), and stays silent off-OPEX.

Usage: python scripts/test_opex_velocity_detector.py
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.opex_velocity_detector import (  # noqa: E402
    OpexVelocityMonitor,
    detect_velocity_breaks,
    is_opex_day,
    is_quad_witch_day,
    opex_date,
)

_FORENSIC = Path(__file__).resolve().parent.parent / "data" / "mrvl_forensic_20260618.json"


# 1. OPEX-day gate ----------------------------------------------------

def test_june_2026_opex_shifts_off_juneteenth():
    # 3rd Friday = 6/19 (Juneteenth holiday) -> OPEX rolls back to Thu 6/18.
    assert opex_date(2026, 6) == datetime.date(2026, 6, 18), opex_date(2026, 6)
    assert is_opex_day(datetime.date(2026, 6, 18)) is True
    assert is_opex_day(datetime.date(2026, 6, 19)) is False


def test_normal_month_opex_is_third_friday():
    # July 2026 3rd Friday = 7/17, no holiday -> unshifted.
    assert opex_date(2026, 7) == datetime.date(2026, 7, 17), opex_date(2026, 7)
    assert is_opex_day(datetime.date(2026, 7, 17)) is True


def test_non_opex_day_is_false():
    assert is_opex_day(datetime.date(2026, 6, 18)) is True
    assert is_opex_day(datetime.date(2026, 6, 17)) is False


def test_quad_witch_flag():
    # June is a quarterly (quad-witch) month; July is not.
    assert is_quad_witch_day(datetime.date(2026, 6, 18)) is True
    assert is_quad_witch_day(datetime.date(2026, 7, 17)) is False


# 2. Pure detector ----------------------------------------------------

def test_pure_detector_single_synthetic_break():
    closes = [("a", 100.0), ("b", 99.8), ("c", 98.0), ("d", 97.9)]  # c = −1.8%
    fires = detect_velocity_breaks(closes, threshold_pct=1.5)
    assert len(fires) == 1 and fires[0]["label"] == "c", fires


def test_pure_detector_ignores_subthreshold():
    closes = [("a", 100.0), ("b", 99.0), ("c", 98.5)]  # −1.0%, −0.5%
    assert detect_velocity_breaks(closes, threshold_pct=1.5) == []


def test_mrvl_6_18_one_fire_zero_fp():
    if not _FORENSIC.exists():
        print("    (skip: forensic JSON absent)")
        return
    bars = json.load(open(_FORENSIC))["bars_1min"]
    closes = [(b["t"], b["c"]) for b in bars]
    fires = detect_velocity_breaks(closes, threshold_pct=1.5)
    assert len(fires) == 1, [f["label"] for f in fires]
    assert fires[0]["label"] == "15:50", fires[0]
    assert fires[0]["ret_pct"] <= -3.0, fires[0]


# 3. Live monitor -----------------------------------------------------

def _ts(hh: int, mm: int) -> float:
    # epoch for 2026-06-18 local; date.fromtimestamp must read 6/18 but we pass
    # force_opex anyway, so absolute tz is irrelevant — spacing is what matters.
    base = datetime.datetime(2026, 6, 18, hh, mm)
    return base.timestamp()


def test_monitor_fires_on_minute_drop():
    m = OpexVelocityMonitor(threshold_pct=1.5)
    assert m.update("MRVL", 328.0, _ts(15, 49), force_opex=True) is None  # seed
    fire = m.update("MRVL", 316.5, _ts(15, 50), force_opex=True)          # −3.5%
    assert fire is not None and fire["dir"] == "down", fire
    assert fire["kind"] == "OPEX_VELOCITY_BREAK"


def test_monitor_cooldown_suppresses_second():
    m = OpexVelocityMonitor(threshold_pct=1.5)
    m.update("MRVL", 328.0, _ts(15, 49), force_opex=True)
    assert m.update("MRVL", 316.5, _ts(15, 50), force_opex=True) is not None
    # 60s later, still dropping — cooldown (120s) suppresses the duplicate.
    assert m.update("MRVL", 311.0, _ts(15, 51), force_opex=True) is None


def test_monitor_silent_off_opex():
    m = OpexVelocityMonitor(threshold_pct=1.5)
    m.update("MRVL", 328.0, _ts(15, 49), force_opex=False)
    assert m.update("MRVL", 316.5, _ts(15, 50), force_opex=False) is None


def test_monitor_ignores_subthreshold_drift():
    m = OpexVelocityMonitor(threshold_pct=1.5)
    m.update("SPY", 600.0, _ts(10, 0), force_opex=True)
    assert m.update("SPY", 597.5, _ts(10, 1), force_opex=True) is None  # −0.42%


def test_monitor_replay_mrvl_one_fire():
    if not _FORENSIC.exists():
        print("    (skip: forensic JSON absent)")
        return
    bars = json.load(open(_FORENSIC))["bars_1min"]
    m = OpexVelocityMonitor(threshold_pct=1.5)
    fires = []
    for b in bars:
        hh, mm = int(b["t"][:2]), int(b["t"][3:5])
        f = m.update("MRVL", b["c"], _ts(hh, mm), force_opex=True)
        if f:
            fires.append(f)
    assert len(fires) == 1, [(f["ticker"], f["ret_pct"]) for f in fires]
    assert fires[0]["ret_pct"] <= -3.0, fires[0]


TESTS = [
    test_june_2026_opex_shifts_off_juneteenth,
    test_normal_month_opex_is_third_friday,
    test_non_opex_day_is_false,
    test_quad_witch_flag,
    test_pure_detector_single_synthetic_break,
    test_pure_detector_ignores_subthreshold,
    test_mrvl_6_18_one_fire_zero_fp,
    test_monitor_fires_on_minute_drop,
    test_monitor_cooldown_suppresses_second,
    test_monitor_silent_off_opex,
    test_monitor_ignores_subthreshold_drift,
    test_monitor_replay_mrvl_one_fire,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/opex_velocity_detector.py (Detector A, #84)")
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
