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
    _is_parity_arb_call,
    WHALE_MIN_NOTIONAL,
    WHALE_MIN_VOL,
    WHALE_MIN_VOL_OI_RATIO,
    WHALE_PARITY_EXTRINSIC_PCT,
    WHALE_PARITY_DEEP_ITM_DELTA,
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


# === Dividend-arb / parity filter (task #49) ===

def _parity_alert(
    ticker="NEE", strike=40.0, expiration="2027-01-15",
    spot=85.65, last=45.62, delta=1.0, notional=327_000_000,
    volume=3000, oi=5000, option_type="call",
    side="ASK", sentiment="BULLISH",
):
    return {
        "ticker": ticker, "strike": strike, "expiration": expiration,
        "option_type": option_type, "side": side, "sentiment": sentiment,
        "volume": volume, "oi": oi, "notional": notional,
        "spot": spot, "last": last, "delta": delta,
    }


def test_parity_nee_40c_canonical():
    """NEE $40 Jan'27 call — the canonical dividend-arb case from 6/4.
    Intrinsic $45.65, last $45.62, extrinsic -$0.03 → parity."""
    _reset_chop()
    a = _parity_alert()
    assert _is_parity_arb_call(a) is True
    is_whale, reasons = _classify_whale_signature(a)
    assert is_whale == 0, "NEE dividend-arb must NOT be whale-tagged"
    assert any("PARITY_ARB" in r for r in reasons)


def test_parity_nee_65c():
    """NEE $65 6/18 — intrinsic $20.65, last $20.49, extrinsic -$0.16."""
    _reset_chop()
    a = _parity_alert(strike=65.0, expiration="2026-06-18", last=20.49,
                      notional=62_800_000)
    assert _is_parity_arb_call(a) is True


def test_parity_realtime_path_no_delta():
    """Realtime WHALE-RT path has delta=0 — strike-vs-spot proxy must
    still catch the dividend-arb signature."""
    _reset_chop()
    a = _parity_alert(strike=65.0, last=20.45, delta=0.0)
    # strike 65 <= spot 85.65 * 0.95 = 81.4 → deep ITM via proxy
    assert _is_parity_arb_call(a) is True


def test_parity_legit_directional_deep_itm_kept():
    """A real directional deep-ITM buy pays POSITIVE time premium —
    must NOT be flagged. NVDA 200C, spot 217, last 25.50, extrinsic
    8.50 = 3.9% of spot."""
    _reset_chop()
    a = _parity_alert(ticker="NVDA", strike=200.0, expiration="2026-08-21",
                      spot=217.0, last=25.50, delta=0.78, notional=5_000_000,
                      oi=2000)
    assert _is_parity_arb_call(a) is False
    is_whale, _ = _classify_whale_signature(a)
    assert is_whale == 1, "legit directional deep-ITM must stay whale-tagged"


def test_parity_otm_call_not_flagged():
    """OTM call has intrinsic=0 so extrinsic=full premium — never parity."""
    _reset_chop()
    a = _parity_alert(ticker="TSLA", strike=450.0, expiration="2026-06-18",
                      spot=425.0, last=12.0, delta=0.35, oi=2000)
    assert _is_parity_arb_call(a) is False


def test_parity_put_not_flagged():
    """Filter only applies to calls — deep-ITM puts pass through."""
    _reset_chop()
    a = _parity_alert(ticker="NEE", strike=130.0, expiration="2026-06-18",
                      spot=85.65, last=44.40, delta=-1.0,
                      option_type="put", sentiment="BEARISH")
    assert _is_parity_arb_call(a) is False


def test_parity_missing_spot_returns_false():
    """No spot data → can't compute parity → don't suppress (fail open)."""
    _reset_chop()
    a = _parity_alert(spot=0)
    assert _is_parity_arb_call(a) is False


def test_parity_ultra_deep_synthetic_flagged():
    """Strike $5 on a $373 stock (GOOGL 6/4) = synthetic/box trade, not
    directional. Extrinsic near zero → flagged."""
    _reset_chop()
    a = _parity_alert(ticker="GOOGL", strike=5.0, expiration="2026-06-18",
                      spot=373.10, last=367.40, delta=1.0)
    assert _is_parity_arb_call(a) is True


def test_parity_thresholds_pinned():
    assert WHALE_PARITY_EXTRINSIC_PCT == 0.003
    assert WHALE_PARITY_DEEP_ITM_DELTA == 0.85


# === Real-time WHALE dispatch (task #44, 2026-06-04 PM) ===
#
# Validates the new sub-30-second dispatch path that bypasses the chain-
# snapshot scanner. Each test exercises one gate in _maybe_dispatch_realtime_whale
# so a regression in any gate is caught in isolation.

import time as _time  # noqa: E402

import server.sweep_detector as sd  # noqa: E402


class _StubTickSideTracker:
    """Minimal stand-in for tick_side_tracker.

    Returns a configurable side regardless of input. The real tracker
    classifies based on rolling NBBO ticks; here we control the answer
    so the dispatch test isolates the dispatch logic from the (already
    unit-tested) NBBO classifier.
    """
    def __init__(self, side="ASK"):
        self._side = side

    def latest_side(self, ticker, strike, expiration, right):
        return self._side


class _StubStream:
    """Minimal stand-in for ThetaStream so SweepDetector can be constructed."""
    _out_queue = None
    _subscriptions = {}
    subscription_count = 0


def _make_detector(side="ASK"):
    det = sd.SweepDetector(stream=_StubStream(), flow_aggregator=None)
    det.tick_side_tracker = _StubTickSideTracker(side=side)
    return det


def _make_rollup(
    ticker="NBIS", strike=350.0, expiration="20260918", option_type="call",
    notional=4_000_000, contracts=600, venues=4,
):
    """Build a SweepRollup matching the NBIS 350C 9/18 FL0WG0D canonical case."""
    r = sd.SweepRollup(
        ticker=ticker,
        strike=strike,
        expiration=expiration,
        option_type=option_type,
        window_start=_time.time(),
    )
    r.total_notional = notional
    r.total_contracts = contracts
    r.print_count = max(1, venues)
    r.exchanges = set(range(venues))
    r.first_price = 6.50
    r.last_price = 6.80
    r.prices = [6.50, 6.65, 6.70, 6.80]
    r.max_print_size = max(1, contracts // venues)
    return r


def _reset_realtime_dispatch():
    """Clear dedup state so tests don't bleed into each other."""
    sd._whale_realtime_dispatch.clear()


import asyncio as _asyncio  # noqa: E402


class _CreateTaskPatcher:
    """Context manager: replace asyncio.create_task with a stub that closes
    the coroutine instead of scheduling it. Lets the sync test runner exercise
    _maybe_dispatch_realtime_whale without a live event loop. The counter
    increments BEFORE create_task is called, so verification still works."""
    def __enter__(self):
        self._orig = _asyncio.create_task
        def _stub(coro):
            try:
                coro.close()
            except Exception:
                pass
            return None
        _asyncio.create_task = _stub
        return self

    def __exit__(self, *exc):
        _asyncio.create_task = self._orig
        return False


def test_realtime_dispatch_fires_on_canonical_nbis():
    """NBIS 350C 9/18 $4M ASK — the canonical missed case. Must fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup()
    fired_before = det.realtime_whales_fired
    with _CreateTaskPatcher():
        det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == fired_before + 1, \
        "NBIS canonical must fire realtime whale"


def test_realtime_dispatch_under_dollar_floor_blocked():
    """$2M notional is below the $3M Telegram floor — must not fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup(notional=2_000_000)
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_low_volume_blocked():
    """Volume below 500 must not fire even at huge notional."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup(notional=10_000_000, contracts=200)
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_bid_side_blocked():
    """When tick_side_tracker reports BID, must not fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side="BID")
    rollup = _make_rollup()
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_mid_side_blocked():
    """When tick_side_tracker reports MID, must not fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side="MID")
    rollup = _make_rollup()
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_none_side_blocked():
    """When tick_side_tracker bucket is thin (returns None), must not fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side=None)
    rollup = _make_rollup()
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_index_etf_blocked():
    """SPY/QQQ/SPX/etc. are excluded regardless of notional."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup(ticker="SPY", notional=20_000_000)
    det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 0


def test_realtime_dispatch_dedup_within_ttl():
    """Same contract within 10 min TTL must dedup — only the first fires."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup1 = _make_rollup()
    with _CreateTaskPatcher():
        det._maybe_dispatch_realtime_whale(rollup1)
        assert det.realtime_whales_fired == 1
        # Second rollup on the same contract — even larger notional
        rollup2 = _make_rollup(notional=10_000_000, contracts=2000)
        det._maybe_dispatch_realtime_whale(rollup2)
    assert det.realtime_whales_fired == 1, "dedup should suppress repeat"


def test_realtime_dispatch_distinct_contracts_both_fire():
    """Different strikes on same ticker are tracked separately."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    r1 = _make_rollup(ticker="NBIS", strike=350.0)
    r2 = _make_rollup(ticker="NBIS", strike=400.0)
    r3 = _make_rollup(ticker="MSFT", strike=500.0)
    with _CreateTaskPatcher():
        det._maybe_dispatch_realtime_whale(r1)
        det._maybe_dispatch_realtime_whale(r2)
        det._maybe_dispatch_realtime_whale(r3)
    assert det.realtime_whales_fired == 3


def test_realtime_dispatch_under_30s_latency():
    """Latency from rollup-open to dispatch decision must be under 30s.

    Confirms the in-window check path is sub-30s (the whole point of #44).
    Measures the wall time from rollup creation through the gate stack
    to dispatch scheduling — no actual Telegram round-trip.
    """
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup()
    t0 = _time.time()
    with _CreateTaskPatcher():
        det._maybe_dispatch_realtime_whale(rollup)
    elapsed = _time.time() - t0
    assert det.realtime_whales_fired == 1
    assert elapsed < 30.0, f"dispatch took {elapsed:.2f}s, must be <30s"
    # In practice this is sub-millisecond. The 30s ceiling is the SLA.


def test_realtime_dispatch_put_bearish_fires():
    """Put + ASK = bearish institutional protection. Must fire."""
    _reset_realtime_dispatch()
    det = _make_detector(side="ASK")
    rollup = _make_rollup(ticker="TSLA", option_type="put")
    with _CreateTaskPatcher():
        det._maybe_dispatch_realtime_whale(rollup)
    assert det.realtime_whales_fired == 1


def test_realtime_dispatch_dedup_key_normalization():
    """Dedup key normalizes ticker case + option type so repeat fires don't
    sneak through case mismatches."""
    _reset_realtime_dispatch()
    r1 = _make_rollup(ticker="nbis", option_type="call")
    r2 = _make_rollup(ticker="NBIS", option_type="call")
    k1 = sd._whale_dedup_key(r1)
    k2 = sd._whale_dedup_key(r2)
    assert k1 == k2, "dedup key must normalize case"


def test_realtime_threshold_pinning():
    """Pin the real-time dispatch config to known good values."""
    assert sd.WHALE_REALTIME_MIN_NOTIONAL == 3_000_000
    assert sd.WHALE_REALTIME_MIN_VOL == 500
    assert sd.WHALE_REALTIME_DEDUP_TTL_SEC == 600


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
    # === task #49 dividend-arb parity filter ===
    test_parity_nee_40c_canonical,
    test_parity_nee_65c,
    test_parity_realtime_path_no_delta,
    test_parity_legit_directional_deep_itm_kept,
    test_parity_otm_call_not_flagged,
    test_parity_put_not_flagged,
    test_parity_missing_spot_returns_false,
    test_parity_ultra_deep_synthetic_flagged,
    test_parity_thresholds_pinned,
    # === task #44 real-time WHALE dispatch ===
    test_realtime_dispatch_fires_on_canonical_nbis,
    test_realtime_dispatch_under_dollar_floor_blocked,
    test_realtime_dispatch_low_volume_blocked,
    test_realtime_dispatch_bid_side_blocked,
    test_realtime_dispatch_mid_side_blocked,
    test_realtime_dispatch_none_side_blocked,
    test_realtime_dispatch_index_etf_blocked,
    test_realtime_dispatch_dedup_within_ttl,
    test_realtime_dispatch_distinct_contracts_both_fire,
    test_realtime_dispatch_under_30s_latency,
    test_realtime_dispatch_put_bearish_fires,
    test_realtime_dispatch_dedup_key_normalization,
    test_realtime_threshold_pinning,
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
