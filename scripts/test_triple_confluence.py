"""Unit tests for server/triple_confluence.py.

Covers direction normalization, ticker exclusion, gate thresholds.
The detect_confluences() integration test is in
scripts/backtest_triple_confluence.py (which replays historical data).

Usage:
    python scripts/test_triple_confluence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.triple_confluence import (  # noqa: E402
    _flow_direction,
    _soe_direction,
    _kingmig_direction,
    _EXCLUDED_TICKERS,
    MIN_INFORMED_FLOW_UNIQUE_STRIKES,
    MIN_SOE_APLUS,
    MIN_KMIG_DELTA_PCT,
)


# === Direction normalization ===

def test_flow_direction_bull_call():
    """BULLISH call → BULL (long call)."""
    assert _flow_direction("call", "BULLISH") == "BULL"


def test_flow_direction_bull_put():
    """BEARISH put → BULL? No — BEAR (long put)."""
    assert _flow_direction("put", "BEARISH") == "BULL"


def test_flow_direction_bear_call():
    assert _flow_direction("call", "BEARISH") == "BEAR"


def test_flow_direction_bear_put():
    assert _flow_direction("put", "BULLISH") == "BEAR"


def test_flow_direction_neutral():
    assert _flow_direction("call", "NEUTRAL") == "BEAR"  # falls to else branch
    assert _flow_direction(None, "BULLISH") == "NEUTRAL"
    assert _flow_direction("call", None) == "BEAR"  # None sentiment → not BULLISH → BEAR


def test_soe_direction_arrow_up():
    assert _soe_direction("▲") == "BULL"


def test_soe_direction_arrow_down():
    assert _soe_direction("▼") == "BEAR"


def test_soe_direction_literal_bull():
    assert _soe_direction("BULL") == "BULL"


def test_soe_direction_literal_bear():
    assert _soe_direction("BEAR") == "BEAR"


def test_soe_direction_none():
    assert _soe_direction(None) == "NEUTRAL"
    assert _soe_direction("") == "NEUTRAL"


def test_kingmig_direction_up():
    assert _kingmig_direction("UP") == "BULL"


def test_kingmig_direction_down():
    assert _kingmig_direction("DOWN") == "BEAR"


def test_kingmig_direction_unknown():
    assert _kingmig_direction("SIDEWAYS") == "NEUTRAL"


# === Ticker exclusion ===

def test_excludes_indexes():
    assert "SPY" in _EXCLUDED_TICKERS
    assert "QQQ" in _EXCLUDED_TICKERS
    assert "SPX" in _EXCLUDED_TICKERS
    assert "IWM" in _EXCLUDED_TICKERS
    assert "VIX" in _EXCLUDED_TICKERS


def test_excludes_leveraged_etfs():
    assert "SOXL" in _EXCLUDED_TICKERS
    assert "TQQQ" in _EXCLUDED_TICKERS
    assert "SQQQ" in _EXCLUDED_TICKERS


def test_includes_single_names():
    """Single-name tickers like NVDA should NOT be excluded."""
    assert "NVDA" not in _EXCLUDED_TICKERS
    assert "MRVL" not in _EXCLUDED_TICKERS
    assert "RKLB" not in _EXCLUDED_TICKERS


# === Threshold pinning ===

def test_min_flow_unique_strikes():
    """Pin the minimum unique strikes for an INFORMED FLOW confluence."""
    assert MIN_INFORMED_FLOW_UNIQUE_STRIKES == 2


def test_min_soe_aplus():
    """A+ minimum is the quality gate that drops noisy fires."""
    assert MIN_SOE_APLUS == 1


def test_min_kmig_delta_pct():
    """King migration must move >=1.5% of spot to count."""
    assert MIN_KMIG_DELTA_PCT == 1.5


# === Test runner ===

TESTS = [
    test_flow_direction_bull_call,
    test_flow_direction_bull_put,
    test_flow_direction_bear_call,
    test_flow_direction_bear_put,
    test_flow_direction_neutral,
    test_soe_direction_arrow_up,
    test_soe_direction_arrow_down,
    test_soe_direction_literal_bull,
    test_soe_direction_literal_bear,
    test_soe_direction_none,
    test_kingmig_direction_up,
    test_kingmig_direction_down,
    test_kingmig_direction_unknown,
    test_excludes_indexes,
    test_excludes_leveraged_etfs,
    test_includes_single_names,
    test_min_flow_unique_strikes,
    test_min_soe_aplus,
    test_min_kmig_delta_pct,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/triple_confluence.py")
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
