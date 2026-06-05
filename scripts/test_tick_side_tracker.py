"""Unit tests for tick_side_tracker.latest_side.

Regression coverage that pins the standard-path classifier. Especially
important because MIN_WINDOW_SIZE measures CONTRACTS (sum of trade sizes)
not trade count — a misreading of that semantics could lead someone to
add an unnecessary "first-print fallback" thinking single big sweeps
return None (they don't).

Coverage:
  - Single 5,000-contract whale sweep returns ASK (no fallback needed)
  - Single tiny print (< 20 contracts) returns None
  - Boundary at MIN_WINDOW_SIZE (19 vs 20 contracts)
  - Dominance ratio applied at the standard 1.3x floor
  - Pruning on stale ticks

Usage:
    python scripts/test_tick_side_tracker.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.tick_side_tracker import (  # noqa: E402
    TickSideTracker,
    MIN_WINDOW_SIZE,
    DOMINANCE_RATIO,
    WINDOW_SECONDS,
)
from server.thetadata import ThetaTrade  # noqa: E402


def _make_trade(
    ticker="NBIS", strike=350.0, expiration="20260918", right="call",
    size=200, side="BUY",
):
    """Build a ThetaTrade with bid/ask/price arranged so classify_side
    returns the requested BUY/SELL/NEUTRAL naturally."""
    bid, ask = 6.50, 6.80
    if side == "BUY":
        price = ask
    elif side == "SELL":
        price = bid
    else:
        price = (bid + ask) / 2
    return ThetaTrade(
        ticker=ticker, expiration=expiration, strike=strike, right=right,
        timestamp_ms=int(time.time() * 1000), sequence=0,
        price=price, size=size, condition=0, exchange=1,
        bid=bid, ask=ask,
    )


# === The headline case: single big sweep without prior history ===

def test_single_5000_contract_sweep_returns_ASK():
    """The canonical "cold-contract whale" case. A single 5,000-contract
    ASK trade with no prior history must classify as ASK — the standard
    path already handles this because MIN_WINDOW_SIZE measures contracts,
    not trades."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=5000, side="BUY"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "ASK"


def test_single_5000_contract_sweep_at_BID_returns_BID():
    """Same case, opposite side — single 5,000-contract BID sweep."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=5000, side="SELL"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "BID"


def test_single_5000_contract_print_at_MID_returns_MID():
    """Single big MID print — neither bid nor ask dominates."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=5000, side="NEUTRAL"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "MID"


# === MIN_WINDOW_SIZE boundary tests ===

def test_below_min_window_size_returns_None():
    """19 contracts is below the 20-contract floor → None."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=19, side="BUY"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") is None


def test_at_min_window_size_returns_ASK():
    """Exactly 20 contracts of pure ASK clears the floor."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=20, side="BUY"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "ASK"


# === Standard dominance logic ===

def test_dominance_threshold_ask_dominant():
    """ASK 1.5x BID — clears the 1.3x DOMINANCE_RATIO → ASK."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=150, side="BUY"))
    t.add_trade(_make_trade(size=100, side="SELL"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "ASK"


def test_dominance_threshold_balanced_returns_MID():
    """ASK 1.1x BID — below the 1.3x DOMINANCE_RATIO → MID."""
    t = TickSideTracker()
    t.add_trade(_make_trade(size=110, side="BUY"))
    t.add_trade(_make_trade(size=100, side="SELL"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "MID"


# === No bucket / pruned-empty path ===

def test_no_bucket_returns_None():
    """Contract never seen → None."""
    t = TickSideTracker()
    assert t.latest_side("NBIS", 350.0, "20260918", "call") is None


def test_pruned_stale_trades_returns_None():
    """All trades pruned (older than WINDOW_SECONDS) → None."""
    t = TickSideTracker()
    trade = _make_trade(size=5000, side="BUY")
    t.add_trade(trade)
    # Manually age all trades in the bucket past the window
    key = TickSideTracker._key("NBIS", 350.0, "20260918", "call")
    bucket = t._buckets[key]
    bucket.trades.clear()
    bucket.ask_vol = 0
    bucket.bid_vol = 0
    bucket.mid_vol = 0
    bucket.add(time.time() - WINDOW_SECONDS - 1, 5000, "ASK")
    assert t.latest_side("NBIS", 350.0, "20260918", "call") is None


# === Threshold pinning ===

def test_pin_MIN_WINDOW_SIZE():
    assert MIN_WINDOW_SIZE == 20


def test_pin_DOMINANCE_RATIO():
    assert DOMINANCE_RATIO == 1.3


# === Counter integration ===

def test_fallback_counter_increments_on_None():
    t = TickSideTracker()
    t.latest_side("XYZ", 0.0, "20260918", "call")
    assert t.fallback_triggered == 1
    assert t.lookups == 1


def test_fallback_counter_unchanged_on_successful_classification():
    t = TickSideTracker()
    t.add_trade(_make_trade(size=5000, side="BUY"))
    assert t.latest_side("NBIS", 350.0, "20260918", "call") == "ASK"
    assert t.fallback_triggered == 0


# === Test runner ===

TESTS = [
    test_single_5000_contract_sweep_returns_ASK,
    test_single_5000_contract_sweep_at_BID_returns_BID,
    test_single_5000_contract_print_at_MID_returns_MID,
    test_below_min_window_size_returns_None,
    test_at_min_window_size_returns_ASK,
    test_dominance_threshold_ask_dominant,
    test_dominance_threshold_balanced_returns_MID,
    test_no_bucket_returns_None,
    test_pruned_stale_trades_returns_None,
    test_pin_MIN_WINDOW_SIZE,
    test_pin_DOMINANCE_RATIO,
    test_fallback_counter_increments_on_None,
    test_fallback_counter_unchanged_on_successful_classification,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - tick_side_tracker.latest_side")
    print("=" * 70)
    passed = 0
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  - {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR   {t.__name__}  - {e!r}")
            failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed+failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
