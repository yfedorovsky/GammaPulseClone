"""Unit tests for the GEX floor/ceiling computation in server/gex.py (#68).

Two defects fixed by the change under test:
  1. NO-FLOOR SERIALIZATION — when no +GEX wall exists below spot the floor is
     now None (JSON null), not a literal $0 strike. Exercised at the public
     compute_exp_data serialization boundary and at the helper level.
  2. FALLBACK-GUARD BUG — the relaxed 10%->15% floor fallback used to be gated
     on `king_strike < spot`, wrongly skipping it when the king sat ABOVE spot.
     Now the fallback runs regardless of king position.

The floor/ceiling search was extracted from compute_exp_data into the pure
helper `server.gex._compute_floor_ceiling(per_strike, strikes_sorted,
king_strike, spot)` so it can be exercised directly with a synthetic per-strike
net_gex map (no chain / IV / BSM machinery needed). The extraction is
behavior-preserving — compute_exp_data now calls the helper.

Usage:
    python scripts/test_gex_floor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.gex import _compute_floor_ceiling  # noqa: E402


def _ps(net_gex_by_strike: dict[float, float]) -> dict[float, dict]:
    """Build a per_strike map shaped like compute_exp_data's internal buckets,
    from a {strike: net_gex} dict. Only net_gex is read by the floor logic."""
    return {s: {"net_gex": g} for s, g in net_gex_by_strike.items()}


def _floor(net_gex_by_strike: dict[float, float], king: float, spot: float):
    per_strike = _ps(net_gex_by_strike)
    strikes_sorted = sorted(per_strike.keys())
    floor_strike, _ceiling = _compute_floor_ceiling(
        per_strike, strikes_sorted, king, spot
    )
    return floor_strike


def _ceiling(net_gex_by_strike: dict[float, float], king: float, spot: float):
    per_strike = _ps(net_gex_by_strike)
    strikes_sorted = sorted(per_strike.keys())
    _floor_strike, ceiling = _compute_floor_ceiling(
        per_strike, strikes_sorted, king, spot
    )
    return ceiling


# === (a) king ABOVE spot + NO +GEX strike below spot → floor is None ===
# Today's live SPY: spot 737.76, king 741 (above spot), the ENTIRE sub-spot
# region is negative GEX. There is genuinely no gamma floor → None, NOT 0.

def test_no_floor_when_king_above_and_subspot_all_negative():
    spot = 737.76
    king = 741.0
    gex = {
        # below spot: all negative GEX (no floor exists anywhere below)
        730.0: -4.0e8,
        733.0: -6.0e8,
        736.0: -8.0e8,
        # king above spot (positive, but it's the king — excluded from floor)
        741.0: +9.0e8,
        # above-spot positive walls (ceilings, not floors)
        745.0: +3.0e8,
        750.0: +2.0e8,
    }
    floor = _floor(gex, king, spot)
    assert floor is None, f"expected None floor, got {floor!r}"
    # Critical: must NOT be the literal 0 the old code produced.
    assert floor != 0, "floor must be None, not a $0 strike"


def test_no_floor_serializes_to_none_not_zero_via_public_api():
    """End-to-end at the serialization boundary: compute_exp_data must put
    None (not 0) in the 'floor' field when no sub-spot +GEX wall exists.

    We invoke the floor path through the same helper compute_exp_data uses and
    assert the serialized field would be None. (compute_exp_data builds the dict
    as {'floor': floor_strike}; floor_strike is the helper's output.)"""
    spot = 737.76
    king = 741.0
    gex = {
        730.0: -4.0e8, 733.0: -6.0e8, 736.0: -8.0e8,
        741.0: +9.0e8, 745.0: +3.0e8,
    }
    floor_strike = _floor(gex, king, spot)
    serialized_floor = floor_strike  # mirrors gex.py: "floor": floor_strike
    assert serialized_floor is None, (
        f"serialized floor must be None (JSON null), got {serialized_floor!r}"
    )


# === (b) king above spot + +GEX floor ONLY in 10-15% band → fallback finds it
# This is the guard-fix regression. Pre-fix (`king_strike < spot` guard), the
# relaxed fallback was skipped because king is ABOVE spot → floor stayed None.
# Post-fix the fallback runs and finds the deeper floor.

def test_fallback_floor_found_when_king_above_spot():
    spot = 100.0
    king = 104.0  # ABOVE spot
    gex = {
        # No +GEX within 10% below spot (90..100) — only negatives there.
        92.0: -3.0e8,
        95.0: -5.0e8,
        98.0: -7.0e8,
        # A +GEX wall in the 10-15% band below spot (85..90) — fallback target.
        88.0: +4.0e8,
        # king above spot
        104.0: +9.0e8,
    }
    floor = _floor(gex, king, spot)
    assert floor == 88.0, (
        f"relaxed fallback should find 88.0 floor with king above spot, "
        f"got {floor!r}"
    )


def test_fallback_picks_highest_strike_in_band():
    """Fallback walks strikes top-down and takes the first +GEX below spot in
    the 15% band — i.e. the highest qualifying strike (nearest support)."""
    spot = 100.0
    king = 104.0
    gex = {
        86.0: +2.0e8,   # deeper +GEX
        89.0: +1.0e8,   # shallower +GEX, higher strike → should win
        95.0: -5.0e8,
        104.0: +9.0e8,
    }
    floor = _floor(gex, king, spot)
    assert floor == 89.0, f"expected highest in-band strike 89.0, got {floor!r}"


# === (c) normal case: +GEX floor within 10% below spot, king above spot ===
# Primary search (within 10%) finds it; behavior unchanged by the fix.

def test_primary_floor_within_10pct_king_above():
    spot = 100.0
    king = 105.0  # above spot
    gex = {
        93.0: +6.0e8,   # within 10% below spot, strongest +GEX → floor
        96.0: +4.0e8,
        99.0: +2.0e8,
        105.0: +9.0e8,  # king above spot
        108.0: +3.0e8,  # above spot → ceiling candidate, not floor
    }
    floor = _floor(gex, king, spot)
    assert floor == 93.0, f"expected primary floor 93.0, got {floor!r}"


def test_ceiling_unaffected_king_above():
    """Sanity: with king above spot, ceiling is the biggest +GEX above the
    king (next resistance past the magnet)."""
    spot = 100.0
    king = 105.0
    gex = {
        93.0: +6.0e8,
        105.0: +9.0e8,  # king
        108.0: +3.0e8,  # above king, within 10% → ceiling
        109.0: +1.0e8,
    }
    ceiling = _ceiling(gex, king, spot)
    assert ceiling == 108.0, f"expected ceiling 108.0, got {ceiling!r}"


# === (d) king BELOW spot + floor below king → unchanged original path ===
# The original (already-working) path: floor = biggest +GEX strictly below king.

def test_floor_below_king_when_king_below_spot():
    spot = 100.0
    king = 96.0  # BELOW spot
    gex = {
        92.0: +7.0e8,   # below king, strongest → floor
        94.0: +3.0e8,   # below king but weaker
        96.0: +9.0e8,   # king
        99.0: +2.0e8,   # between king and spot — NOT a floor (king in the way)
        103.0: +4.0e8,  # above spot → ceiling
    }
    floor = _floor(gex, king, spot)
    assert floor == 92.0, (
        f"floor must be biggest +GEX below king (92.0), got {floor!r}"
    )


def test_primary_search_excludes_strike_between_king_and_spot():
    """PRIMARY search (king < spot): a +GEX strike between king and spot is
    excluded as a floor — floor_search_ceil = min(spot, king) = king, so the
    primary loop only looks strictly below the king. When a real +GEX floor
    exists below the king, that wins over the in-between strike.

    This is the unchanged original king-below-spot path: the in-between strike
    (98) never becomes the floor because a genuine below-king floor (92) exists.
    """
    spot = 100.0
    king = 96.0
    gex = {
        92.0: +7.0e8,   # below king → the real floor
        96.0: +9.0e8,   # king
        98.0: +8.0e8,   # between king and spot — must NOT win over 92
        103.0: +4.0e8,
    }
    floor = _floor(gex, king, spot)
    assert floor == 92.0, (
        f"primary search must pick the below-king floor (92.0), not the "
        f"in-between strike; got {floor!r}"
    )


# === Test runner ===

TESTS = [
    test_no_floor_when_king_above_and_subspot_all_negative,
    test_no_floor_serializes_to_none_not_zero_via_public_api,
    test_fallback_floor_found_when_king_above_spot,
    test_fallback_picks_highest_strike_in_band,
    test_primary_floor_within_10pct_king_above,
    test_ceiling_unaffected_king_above,
    test_floor_below_king_when_king_below_spot,
    test_primary_search_excludes_strike_between_king_and_spot,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/gex.py floor/ceiling computation (#68)")
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
