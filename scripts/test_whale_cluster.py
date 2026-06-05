"""Unit tests for server.whale_cluster (Phase 3 of overnight sequence).

Validates the multi-strike whale ladder detector. The canonical NVDA 6/4
case had 11 whale-tagged BULL prints across 4 expirations in 3 hours —
this module collapses those into a single CLUSTER alert.

Coverage:
  - 2-strike same-direction within window → cluster fires
  - 1 strike → no cluster
  - Different directions in same ticker → 2 separate clusters
  - Cross-expiration ladder counts as distinct legs
  - Same (strike, exp) re-firing doesn't double-count
  - Dedup: cluster can't re-fire within 30 min
  - Non-whale alerts rejected
  - GC bounds memory growth
  - Format renders MULTI-TENOR badge for 3+ expirations

Usage:
    python scripts/test_whale_cluster.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.whale_cluster as wc  # noqa: E402


def _alert(
    ticker="NVDA", strike=215.0, expiration="2026-07-02",
    option_type="call", sentiment="BULLISH", side="ASK",
    notional=3_730_000, volume=3313, oi=1281, is_whale=1,
):
    return {
        "ticker": ticker, "strike": strike, "expiration": expiration,
        "option_type": option_type, "sentiment": sentiment, "side": side,
        "notional": notional, "volume": volume, "oi": oi,
        "is_whale": is_whale,
    }


def _reset():
    wc._recent_whale_fires.clear()
    wc._whale_cluster_dedup.clear()


# === Single-strike no-cluster path ===

def test_single_strike_no_cluster():
    """One whale fire alone is NOT a cluster (needs 2+ strikes)."""
    _reset()
    cluster = wc.record_and_check(_alert())
    assert cluster is None


# === Two-strike cluster fires ===

def test_two_strike_same_exp_cluster_fires():
    """2 distinct strikes same expiration same direction → cluster."""
    _reset()
    wc.record_and_check(_alert(strike=215.0))
    cluster = wc.record_and_check(_alert(strike=220.0))
    assert cluster is not None
    assert cluster["n_strikes"] == 2
    assert cluster["direction"] == "BULL"
    assert cluster["n_expirations"] == 1


def test_two_strike_cross_exp_cluster_fires():
    """Cross-expiration ladder — counts as 2 distinct legs."""
    _reset()
    wc.record_and_check(_alert(strike=215.0, expiration="2026-07-02"))
    cluster = wc.record_and_check(_alert(strike=200.0, expiration="2027-01-15"))
    assert cluster is not None
    assert cluster["n_strikes"] == 2
    assert cluster["n_expirations"] == 2


# === NVDA 6/4 canonical case: 11 prints, 4 expirations ===

def test_nvda_canonical_ladder():
    """The motivation case — multi-tenor NVDA BULL accumulation."""
    _reset()
    # Build out the actual NVDA 6/4 whale ladder
    whales = [
        # weeklies
        (230.0, "2026-06-18"), (220.0, "2026-06-18"), (200.0, "2026-06-18"),
        # near monthly
        (215.0, "2026-07-02"),
        # August monthly
        (230.0, "2026-08-21"), (200.0, "2026-08-21"), (160.0, "2026-08-21"),
        # 1/15/27 LEAP
        (200.0, "2027-01-15"), (230.0, "2027-01-15"),
        (250.0, "2027-01-15"), (300.0, "2027-01-15"),
    ]
    last_cluster = None
    for strike, exp in whales:
        result = wc.record_and_check(
            _alert(strike=strike, expiration=exp, notional=2_500_000)
        )
        if result is not None:
            last_cluster = result
    # Cluster dedup: should have fired ONCE (the first 2-strike completion)
    # but the cluster contents now reflect the full ladder via the roster
    assert last_cluster is not None, "NVDA canonical must produce a cluster"
    # Cluster fires when 2nd distinct leg arrives, so n_strikes at fire time = 2
    assert last_cluster["n_strikes"] == 2


# === Direction segregation ===

def test_bull_and_bear_are_separate_clusters():
    """Same ticker BULL and BEAR are tracked independently."""
    _reset()
    # BULL: 2 calls ASK
    wc.record_and_check(_alert(strike=215.0, option_type="call", sentiment="BULLISH"))
    bull_cluster = wc.record_and_check(
        _alert(strike=220.0, option_type="call", sentiment="BULLISH")
    )
    # BEAR: 2 puts ASK
    wc.record_and_check(_alert(strike=210.0, option_type="put", sentiment="BEARISH"))
    bear_cluster = wc.record_and_check(
        _alert(strike=205.0, option_type="put", sentiment="BEARISH")
    )
    assert bull_cluster is not None
    assert bull_cluster["direction"] == "BULL"
    assert bear_cluster is not None
    assert bear_cluster["direction"] == "BEAR"


# === Non-whale rejection ===

def test_non_whale_alert_rejected():
    """Defense in depth — record_and_check ignores alerts without is_whale=1."""
    _reset()
    wc.record_and_check(_alert(strike=215.0, is_whale=0))
    cluster = wc.record_and_check(_alert(strike=220.0, is_whale=0))
    assert cluster is None
    assert not wc._recent_whale_fires


# === Empty-ticker rejection ===

def test_empty_ticker_rejected():
    _reset()
    a = _alert()
    a["ticker"] = ""
    cluster = wc.record_and_check(a)
    assert cluster is None


# === Same (strike, exp) re-firing ===

def test_same_strike_exp_no_double_count():
    """Same (strike, exp) firing twice = still 1 distinct leg, not 2."""
    _reset()
    wc.record_and_check(_alert(strike=215.0, expiration="2026-07-02"))
    cluster = wc.record_and_check(_alert(strike=215.0, expiration="2026-07-02"))
    # Same strike+exp = same leg → no cluster (still only 1 distinct)
    assert cluster is None


def test_same_strike_diff_exp_counts_as_2_legs():
    """Same strike on different expirations = 2 legs (ladder pattern)."""
    _reset()
    wc.record_and_check(_alert(strike=215.0, expiration="2026-07-02"))
    cluster = wc.record_and_check(_alert(strike=215.0, expiration="2027-01-15"))
    assert cluster is not None
    assert cluster["n_strikes"] == 2


# === Dedup ===

def test_dedup_within_ttl_blocks_repeat_cluster():
    """Same (ticker, direction) cluster can't re-fire within 30-min dedup."""
    _reset()
    wc.record_and_check(_alert(strike=215.0))
    first = wc.record_and_check(_alert(strike=220.0))
    assert first is not None
    # New 3rd strike arrives — would extend cluster but dedup blocks
    second = wc.record_and_check(_alert(strike=225.0))
    assert second is None


# === GC ===

def test_gc_drops_old_entries():
    """gc_old_entries cleans state older than 2× window."""
    _reset()
    wc.record_and_check(_alert(strike=215.0))
    # Age the entry past the GC cutoff
    key = ("NVDA", "BULL")
    for entry in wc._recent_whale_fires[key]:
        entry["ts"] = time.time() - 3 * wc.WHALE_CLUSTER_WINDOW_SEC
    removed = wc.gc_old_entries()
    assert removed >= 1
    assert "NVDA" not in [k[0] for k in wc._recent_whale_fires]


# === Format ===

def test_format_renders_telegram_text():
    """Format produces a non-empty Telegram-safe string with key elements."""
    _reset()
    wc.record_and_check(_alert(strike=215.0))
    cluster = wc.record_and_check(_alert(strike=220.0))
    text = wc.format_cluster_telegram(cluster)
    assert "WHALE CLUSTER" in text
    assert "NVDA" in text
    assert "BULLISH" in text


def test_format_multi_tenor_badge_3_exps():
    """3+ expirations → MULTI-TENOR LADDER banner appears."""
    _reset()
    wc.record_and_check(_alert(strike=215.0, expiration="2026-07-02"))
    wc.record_and_check(_alert(strike=220.0, expiration="2026-08-21"))
    cluster = wc.record_and_check(_alert(strike=230.0, expiration="2027-01-15"))
    # Above fires at strike #2 (cluster dedup blocks strike #3) so we need
    # to reset dedup or simulate the in-progress roster state.
    # Use the recorded roster directly to build a cluster dict
    wc._whale_cluster_dedup.clear()
    cluster = wc.record_and_check(_alert(strike=300.0, expiration="2026-09-18"))
    text = wc.format_cluster_telegram(cluster)
    assert "MULTI-TENOR" in text


# === Threshold pinning ===

def test_pin_min_strikes():
    assert wc.MIN_WHALE_CLUSTER_STRIKES == 2


def test_pin_min_telegram_strikes():
    assert wc.MIN_WHALE_CLUSTER_TELEGRAM_STRIKES == 2


def test_pin_window_sec():
    assert wc.WHALE_CLUSTER_WINDOW_SEC == 30 * 60


def test_pin_dedup_ttl_sec():
    assert wc.WHALE_CLUSTER_DEDUP_TTL_SEC == 30 * 60


# === Window expiry ===

def test_old_entries_excluded_from_cluster_count():
    """Sibling fires older than the window don't contribute to cluster."""
    _reset()
    wc.record_and_check(_alert(strike=215.0))
    # Age the entry past the window
    key = ("NVDA", "BULL")
    for entry in wc._recent_whale_fires[key]:
        entry["ts"] = time.time() - wc.WHALE_CLUSTER_WINDOW_SEC - 60
    # Now add another strike — first is stale, so this is solo, no cluster
    cluster = wc.record_and_check(_alert(strike=220.0))
    assert cluster is None


# === Test runner ===

TESTS = [
    test_single_strike_no_cluster,
    test_two_strike_same_exp_cluster_fires,
    test_two_strike_cross_exp_cluster_fires,
    test_nvda_canonical_ladder,
    test_bull_and_bear_are_separate_clusters,
    test_non_whale_alert_rejected,
    test_empty_ticker_rejected,
    test_same_strike_exp_no_double_count,
    test_same_strike_diff_exp_counts_as_2_legs,
    test_dedup_within_ttl_blocks_repeat_cluster,
    test_gc_drops_old_entries,
    test_format_renders_telegram_text,
    test_format_multi_tenor_badge_3_exps,
    test_pin_min_strikes,
    test_pin_min_telegram_strikes,
    test_pin_window_sec,
    test_pin_dedup_ttl_sec,
    test_old_entries_excluded_from_cluster_count,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - server.whale_cluster (overnight Phase 3)")
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
