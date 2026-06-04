"""Unit tests for _classify_whale_signature (task #41).

Covers every gate that contributes to the whale tag, the index ETF
exclusion, and the chop suppression path. Includes a positive CVS-class
case based on tonight's FL0WG0D screenshot.

Usage:
    python scripts/test_whale_detector.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.flow_alerts import (  # noqa: E402
    _classify_whale_signature,
    WHALE_MIN_NOTIONAL,
    WHALE_MIN_VOL,
    WHALE_MIN_VOL_OI_RATIO,
)
import server.flow_noise_filter as nf  # noqa: E402


def _alert(
    ticker="CVS", strike=100, expiration="2026-08-21", option_type="call",
    side="ASK", sentiment="BULLISH",
    volume=3000, oi=2090, notional=1_020_000,
):
    return {
        "ticker": ticker, "strike": strike, "expiration": expiration,
        "option_type": option_type,
        "side": side, "sentiment": sentiment,
        "volume": volume, "oi": oi, "notional": notional,
    }


def _reset_chop():
    """Clear any chop state between tests so the chop gate doesn't bleed."""
    nf._ticker_bias_state.clear()


# === Positive case: the CVS canonical pattern ===

def test_cvs_canonical():
    """The exact CVS 100C 8/21 trade from FL0WG0D 6/4 14:40 ET."""
    _reset_chop()
    is_whale, reasons = _classify_whale_signature(_alert())
    assert is_whale == 1, f"CVS canonical should be whale-tagged"
    assert any("$1.0M" in r or "$1M" in r for r in reasons), \
        f"Expected dollar size in reasons: {reasons}"


# === Gate 1: dollar size floor ===

def test_below_dollar_floor_dropped():
    _reset_chop()
    a = _alert(notional=WHALE_MIN_NOTIONAL - 1)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_exactly_at_dollar_floor_kept():
    _reset_chop()
    a = _alert(notional=WHALE_MIN_NOTIONAL)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1


# === Gate 2: ASK side required ===

def test_bid_side_dropped():
    _reset_chop()
    a = _alert(side="BID")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_mid_side_dropped():
    _reset_chop()
    a = _alert(side="MID")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


# === Gate 3: volume floor ===

def test_low_volume_dropped():
    """vol < 500 should drop regardless of dollar size."""
    _reset_chop()
    # 100 contracts at $50 = $500K notional (under $1M anyway), so bump up
    # to make sure VOLUME is the disqualifier not notional
    a = _alert(volume=100, notional=1_500_000, oi=500)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


# === Gate 4: vol/oi ratio ===

def test_low_voi_ratio_dropped():
    """vol must be at least 30% of OI."""
    _reset_chop()
    a = _alert(volume=500, oi=10_000)  # vol/oi = 0.05 << 0.3
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_voi_ratio_above_threshold_kept():
    _reset_chop()
    a = _alert(volume=3000, oi=10_000)  # vol/oi = 0.30 exactly
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1


def test_no_oi_kept():
    """Brand new contract with no prior OI — vol/oi gate skipped."""
    _reset_chop()
    a = _alert(volume=600, oi=0)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1


# === Gate 5: direction alignment ===

def test_bearish_call_dropped():
    """Calls must be BULLISH (long-call thesis) to whale-tag."""
    _reset_chop()
    a = _alert(option_type="call", sentiment="BEARISH")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_bullish_put_dropped():
    """Puts must be BEARISH (long-put thesis) to whale-tag."""
    _reset_chop()
    a = _alert(option_type="put", sentiment="BULLISH")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_bearish_put_kept():
    _reset_chop()
    a = _alert(option_type="put", sentiment="BEARISH")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1


# === Gate 6: index ETF exclusion ===

def test_spy_dropped():
    _reset_chop()
    a = _alert(ticker="SPY", notional=50_000_000)  # huge but excluded
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_qqq_dropped():
    _reset_chop()
    a = _alert(ticker="QQQ", notional=50_000_000)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_soxl_dropped():
    """Leveraged ETFs are excluded too."""
    _reset_chop()
    a = _alert(ticker="SOXL", notional=5_000_000)
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_single_name_not_excluded():
    _reset_chop()
    a = _alert(ticker="NVDA")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1


# === Gate 7: chop suppression ===

def test_chop_ticker_suppressed():
    """When a ticker is in CHOP, even a clean whale signature is suppressed."""
    _reset_chop()
    # Manually put TSLA in chop state via the bias accumulator
    from datetime import date
    key = ("TSLA", date.today().isoformat())
    nf._ticker_bias_state[key] = {
        "bull_buy": 100_000_000,
        "bear_buy": 100_000_000,  # exact balance
    }
    a = _alert(ticker="TSLA")
    is_whale, reasons = _classify_whale_signature(a)
    assert is_whale == 0
    assert any("CHOP" in r for r in reasons)


# === Empty/malformed input ===

def test_empty_ticker_dropped():
    _reset_chop()
    a = _alert(ticker="")
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


def test_none_ticker_dropped():
    _reset_chop()
    a = _alert()
    a["ticker"] = None
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 0


# === Threshold pinning ===

def test_threshold_dollar_floor():
    assert WHALE_MIN_NOTIONAL == 1_000_000


def test_threshold_volume_floor():
    assert WHALE_MIN_VOL == 500


def test_threshold_voi_ratio():
    assert WHALE_MIN_VOL_OI_RATIO == 0.30


# === Test runner ===

TESTS = [
    test_cvs_canonical,
    test_below_dollar_floor_dropped,
    test_exactly_at_dollar_floor_kept,
    test_bid_side_dropped,
    test_mid_side_dropped,
    test_low_volume_dropped,
    test_low_voi_ratio_dropped,
    test_voi_ratio_above_threshold_kept,
    test_no_oi_kept,
    test_bearish_call_dropped,
    test_bullish_put_dropped,
    test_bearish_put_kept,
    test_spy_dropped,
    test_qqq_dropped,
    test_soxl_dropped,
    test_single_name_not_excluded,
    test_chop_ticker_suppressed,
    test_empty_ticker_dropped,
    test_none_ticker_dropped,
    test_threshold_dollar_floor,
    test_threshold_volume_floor,
    test_threshold_voi_ratio,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — _classify_whale_signature (task #41)")
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
