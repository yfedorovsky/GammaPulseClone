"""Unit tests for server/opex_pin_detector.py (Detector B, OPEX-pin arm) + its
integration with Detector A (single-name qualification).

Validates the arming signature against the MRVL 6/18 forensic: the final pre-break
window (15:25-15:45 — spot ~328 sandwiched between floor 327.5 and call wall 330,
net_GEX > 0) must ARM; looser/earlier structure must NOT. Plus: registry TTL, the
off-OPEX / not-long-gamma / wall-too-far negatives, and that A's maybe_fire fires
on an armed single name but skips an unarmed one.

Usage: python scripts/test_opex_pin_detector.py
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import opex_pin_detector as B  # noqa: E402
from server.opex_pin_detector import evaluate_pin_arm  # noqa: E402
from server.opex_velocity_detector import maybe_fire  # noqa: E402

_FORENSIC = Path(__file__).resolve().parent.parent / "data" / "mrvl_forensic_20260618.json"


def _opex_ts(hh: int, mm: int) -> float:
    return datetime.datetime(2026, 6, 18, hh, mm).timestamp()  # 6/18 = OPEX


# ── pure arming ──────────────────────────────────────────────────────

def test_arms_on_mrvl_pre_break_structure():
    # 15:45: spot 328.65, ceiling 330, floor 327.5, net_GEX +223M
    r = evaluate_pin_arm(328.65, 330.0, 327.5, 223e6, is_opex=True)
    assert r["armed"] is True, r
    assert r["call_wall"] == 330.0 and r["floor"] == 327.5


def test_not_armed_off_opex():
    r = evaluate_pin_arm(328.65, 330.0, 327.5, 223e6, is_opex=False)
    assert r["armed"] is False and "not_opex" in r["reasons"]


def test_not_armed_when_short_gamma():
    r = evaluate_pin_arm(328.65, 330.0, 327.5, -50e6, is_opex=True)
    assert r["armed"] is False and "not_long_gamma" in r["reasons"]


def test_not_armed_when_wall_too_far():
    # 11:00 MRVL: spot 323.74, ceiling 330 (+1.93%) — wall beyond CEIL_MAX 1.2%.
    r = evaluate_pin_arm(323.74, 330.0, 320.0, 140e6, is_opex=True)
    assert r["armed"] is False and "wall_not_above_or_too_far" in r["reasons"]


def test_not_armed_when_floor_too_far():
    # wall close (0.3%) but floor 2% below — not a tight sandwich.
    r = evaluate_pin_arm(329.0, 330.0, 322.4, 200e6, is_opex=True)
    assert r["armed"] is False and "floor_not_below_or_too_far" in r["reasons"]


def test_not_armed_when_missing_levels():
    assert evaluate_pin_arm(328.0, None, 327.5, 200e6, True)["armed"] is False
    assert evaluate_pin_arm(328.0, 330.0, None, 200e6, True)["armed"] is False


def test_mrvl_forensic_arms_pre_break_window():
    if not _FORENSIC.exists():
        print("    (skip: forensic JSON absent)")
        return
    tl = json.load(open(_FORENSIC))["gex_charm_timeline"]
    by_t = {g["t"]: g for g in tl}
    # final pre-break window (floor stepped up to 327.5) must arm
    for t in ("15:25", "15:30", "15:35", "15:45"):
        g = by_t[t]
        r = evaluate_pin_arm(g["spot"], g["ceiling"], g["floor"], g["net_gex"], True)
        assert r["armed"] is True, (t, r)
    # a loose mid-day bar (11:00, ceiling 1.9% away) must NOT arm
    g = by_t["11:00"]
    assert evaluate_pin_arm(g["spot"], g["ceiling"], g["floor"], g["net_gex"], True)["armed"] is False


# ── registry + TTL ───────────────────────────────────────────────────

def test_registry_arm_and_ttl():
    B._ARMED.clear()
    now = _opex_ts(15, 45)
    B._ARMED["MRVL"] = ({"armed": True, "call_wall": 330.0, "floor": 327.5}, now)
    assert B.is_armed("MRVL", now) is True
    assert B.armed_details("mrvl", now)["call_wall"] == 330.0
    # expires after TTL
    assert B.is_armed("MRVL", now + B.ARM_TTL_S + 1) is False
    assert "MRVL" not in B._ARMED  # eviction on stale read


# ── A <-> B integration ──────────────────────────────────────────────

def test_velocity_fires_on_armed_single_name():
    B._ARMED.clear()
    t0, t1 = _opex_ts(15, 49), _opex_ts(15, 50)
    B._ARMED["MRVL"] = ({"armed": True, "call_wall": 330.0, "floor": 327.5}, t1)
    from server.opex_velocity_detector import get_monitor
    get_monitor()._samples.clear()
    get_monitor()._last_fire_ts.clear()
    assert maybe_fire({"MRVL": 328.0}, t0) == []          # seed
    fires = maybe_fire({"MRVL": 316.5}, t1)               # −3.5%
    assert len(fires) == 1 and fires[0]["pin_armed"] is True, fires
    assert fires[0]["call_wall"] == 330.0


def test_velocity_skips_unarmed_single_name():
    B._ARMED.clear()
    t0, t1 = _opex_ts(13, 0), _opex_ts(13, 1)
    from server.opex_velocity_detector import get_monitor
    get_monitor()._samples.clear()
    get_monitor()._last_fire_ts.clear()
    maybe_fire({"ZZZZ": 100.0}, t0)
    assert maybe_fire({"ZZZZ": 98.0}, t1) == []           # −2% but unarmed -> skip


def test_velocity_index_fires_without_arm():
    B._ARMED.clear()
    t0, t1 = _opex_ts(11, 0), _opex_ts(11, 1)
    from server.opex_velocity_detector import get_monitor
    get_monitor()._samples.clear()
    get_monitor()._last_fire_ts.clear()
    maybe_fire({"SPY": 600.0}, t0)
    fires = maybe_fire({"SPY": 590.0}, t1)                # index always in scope
    assert len(fires) == 1 and not fires[0].get("pin_armed"), fires


TESTS = [
    test_arms_on_mrvl_pre_break_structure,
    test_not_armed_off_opex,
    test_not_armed_when_short_gamma,
    test_not_armed_when_wall_too_far,
    test_not_armed_when_floor_too_far,
    test_not_armed_when_missing_levels,
    test_mrvl_forensic_arms_pre_break_window,
    test_registry_arm_and_ttl,
    test_velocity_fires_on_armed_single_name,
    test_velocity_skips_unarmed_single_name,
    test_velocity_index_fires_without_arm,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/opex_pin_detector.py (Detector B) + A integration")
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
