"""Unit tests for server/flow_noise_filter.py.

Covers the 5 noise-reduction rules + state-reset behavior. Each test is
self-contained — state is cleared between tests via the public reset.

Usage:
    python scripts/test_noise_filter.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.flow_noise_filter as nf  # noqa: E402
from server.flow_noise_filter import (  # noqa: E402
    should_insert,
    is_ticker_in_chop,
    _voi_band,
    CHOP_BALANCE_PCT,
    CHOP_MIN_NOTIONAL,
)


def _reset() -> None:
    """Clear filter state between tests.

    Important: use the module namespace (nf.X) not imported references,
    because _reset_state_if_new_day() inside the module reassigns
    _contract_state via `global` — any module-level import gets a
    stale reference. Also force the date-tracker so internal reset
    doesn't run during the test.
    """
    nf._contract_state.clear()
    nf._ticker_bias_state.clear()
    # Pin the date so _reset_state_if_new_day inside should_insert
    # doesn't trigger another reassignment.
    from datetime import date
    nf._last_state_date = date.today()


def _alert(
    ticker="AAPL", strike=200, expiration="2026-06-12", option_type="call",
    conviction="HIGH", side="ASK", sentiment="BULLISH",
    vol_oi=15.0, notional=1_500_000,
):
    return {
        "ticker": ticker, "strike": strike, "expiration": expiration,
        "option_type": option_type, "conviction": conviction,
        "side": side, "sentiment": sentiment,
        "vol_oi": vol_oi, "notional": notional,
    }


# === Fix #1: contract-snapshot dedup ===

def test_first_fire_kept():
    _reset()
    keep, _ = should_insert(_alert())
    assert keep is True


def test_dup_band_dropped():
    _reset()
    a = _alert(vol_oi=12.0)
    should_insert(a)
    keep, reason = should_insert(a)
    assert keep is False
    assert "dup band" in (reason or "")


def test_voi_escalation_kept():
    """Same contract but V/OI crosses a band → re-fire."""
    _reset()
    a1 = _alert(vol_oi=12.0)   # band 10
    a2 = _alert(vol_oi=27.0)   # band 25
    should_insert(a1)
    keep, _ = should_insert(a2)
    assert keep is True


def test_voi_de_escalation_dropped():
    """Same contract but V/OI drops back below prior band → dup."""
    _reset()
    a1 = _alert(vol_oi=27.0)  # band 25
    a2 = _alert(vol_oi=12.0)  # band 10, below 25
    should_insert(a1)
    keep, _ = should_insert(a2)
    # State has last_voi_band=25, new band=10 (below). Not an escalation.
    # Time has not passed, so refire window not satisfied. Drop.
    assert keep is False


def test_voi_band_calc():
    """V/OI band thresholds: 10, 25, 50, 100, 250."""
    assert _voi_band(9.9) == 0
    assert _voi_band(10.0) == 10
    assert _voi_band(24.9) == 10
    assert _voi_band(25.0) == 25
    assert _voi_band(99.5) == 50
    assert _voi_band(250.0) == 250
    assert _voi_band(9999.0) == 250


# === Fix #2: drop LOW conviction ===

def test_low_conviction_dropped():
    _reset()
    keep, reason = should_insert(_alert(conviction="LOW"))
    assert keep is False
    assert reason == "LOW conviction"


def test_medium_conviction_kept():
    _reset()
    keep, _ = should_insert(_alert(conviction="MEDIUM"))
    assert keep is True


def test_high_conviction_kept():
    _reset()
    keep, _ = should_insert(_alert(conviction="HIGH"))
    assert keep is True


def test_sweep_conviction_kept():
    _reset()
    keep, _ = should_insert(_alert(conviction="SWEEP"))
    assert keep is True


# === Fix #3: drop small-dollar MID ===

def test_mid_under_1m_dropped():
    _reset()
    keep, reason = should_insert(_alert(side="MID", notional=500_000))
    assert keep is False
    assert "MID" in (reason or "")


def test_mid_over_1m_kept():
    """Institutional MID crosses ($1M+) should be preserved."""
    _reset()
    keep, _ = should_insert(_alert(side="MID", notional=5_000_000))
    assert keep is True


def test_mid_exactly_at_threshold():
    """Right at $1M threshold is the boundary case — must keep."""
    _reset()
    keep, _ = should_insert(_alert(side="MID", notional=1_000_000))
    assert keep is True


# === Fix #4: per-ticker chop detection ===

def test_chop_not_flagged_with_no_data():
    _reset()
    assert is_ticker_in_chop("TSLA") is False


def test_chop_flagged_when_balanced():
    """Bull-buy == bear-buy on same ticker → CHOP."""
    _reset()
    # Insert calls that accumulate bias
    for _ in range(3):
        # Bull-buy adds to bull_buy bucket
        a = _alert(ticker="TSLA", sentiment="BULLISH", side="ASK",
                   option_type="call", notional=2_000_000, vol_oi=15.0,
                   strike=200 + _,  # unique strike each iter to bypass dedup
                   expiration="2026-06-05")
        should_insert(a)
        # Bear-buy puts add to bear_buy bucket
        a2 = _alert(ticker="TSLA", sentiment="BEARISH", side="ASK",
                    option_type="put", notional=2_000_000, vol_oi=15.0,
                    strike=200 + _, expiration="2026-06-05")
        should_insert(a2)
    assert is_ticker_in_chop("TSLA") is True


def test_chop_NOT_flagged_when_imbalanced():
    """Strong directional bias → NOT chop."""
    _reset()
    for i in range(3):
        # All bullish
        a = _alert(ticker="NVDA", sentiment="BULLISH", side="ASK",
                   option_type="call", notional=3_000_000, vol_oi=15.0,
                   strike=200 + i, expiration="2026-06-05")
        should_insert(a)
    # No bear-buy → bias is 100% bull → NOT chop
    assert is_ticker_in_chop("NVDA") is False


def test_chop_min_notional_threshold():
    """Below CHOP_MIN_NOTIONAL ($5M each side) → don't flag CHOP from noise."""
    _reset()
    # Tiny balanced flow — should NOT trigger CHOP
    a1 = _alert(ticker="ABC", sentiment="BULLISH", side="ASK",
                option_type="call", notional=1_000_000, vol_oi=15.0)
    a2 = _alert(ticker="ABC", sentiment="BEARISH", side="ASK",
                option_type="put", notional=1_000_000, vol_oi=15.0,
                strike=210)  # different strike to bypass dedup
    should_insert(a1)
    should_insert(a2)
    # Balanced but each side < $5M → not chop
    assert is_ticker_in_chop("ABC") is False


# === Test runner ===

TESTS = [
    test_first_fire_kept,
    test_dup_band_dropped,
    test_voi_escalation_kept,
    test_voi_de_escalation_dropped,
    test_voi_band_calc,
    test_low_conviction_dropped,
    test_medium_conviction_kept,
    test_high_conviction_kept,
    test_sweep_conviction_kept,
    test_mid_under_1m_dropped,
    test_mid_over_1m_kept,
    test_mid_exactly_at_threshold,
    test_chop_not_flagged_with_no_data,
    test_chop_flagged_when_balanced,
    test_chop_NOT_flagged_when_imbalanced,
    test_chop_min_notional_threshold,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/flow_noise_filter.py")
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
