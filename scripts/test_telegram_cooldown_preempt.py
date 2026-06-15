"""Unit tests for the significance-aware per-ticker cooldown preemption (#71).

A big longer-dated whale must not be silenced by an earlier small 0DTE on the
same name (AAPL 6/15: $7.7M 9/18 + $5.6M LEAP dropped by ticker_cd while only
4/25 sent). Preemption is bounded by a 5-min anti-spam floor + the daily cap.

    python scripts/test_telegram_cooldown_preempt.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.telegram as tg  # noqa: E402

WH = dict(priority=True, top_value=True)  # whale-class dispatch flags


def _reset() -> None:
    tg._ticker_last_sent.clear()
    tg._ticker_daily_count.clear()
    tg._message_times.clear()
    tg._priority_times.clear()
    tg._top_value_times.clear()


def test_big_whale_preempts_within_cooldown():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 600  # 10m ago: in 1h cd, past 5m floor
    allowed, reason = tg._can_send("AAPL", significance=7.7, **WH)
    assert allowed and reason == "", f"big whale should preempt, got {allowed},{reason}"


def test_small_alert_blocked_within_cooldown():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 600
    allowed, reason = tg._can_send("AAPL", significance=1.0, **WH)
    assert not allowed and reason == "ticker_cd", \
        f"small alert must still ticker_cd, got {allowed},{reason}"


def test_big_whale_blocked_within_antispam_floor():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 120  # 2m ago: inside 5m floor
    allowed, reason = tg._can_send("AAPL", significance=7.7, **WH)
    assert not allowed and reason == "ticker_cd", \
        f"too-soon big whale must ticker_cd (anti-spam), got {allowed},{reason}"


def test_just_under_threshold_blocked():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 600
    allowed, reason = tg._can_send("AAPL", significance=tg.TICKER_COOLDOWN_PREEMPT_SIG - 0.1, **WH)
    assert not allowed and reason == "ticker_cd", \
        f"sub-threshold sig must ticker_cd, got {allowed},{reason}"


def test_after_cooldown_allowed_normally():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 3700  # past 1h cooldown
    allowed, reason = tg._can_send("AAPL", significance=1.0, **WH)
    assert allowed and reason == "", f"post-cooldown should allow, got {allowed},{reason}"


def test_daily_cap_still_binds_for_big_whale():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 600
    tg._ticker_daily_count[("AAPL", tg._today_str())] = tg.PER_TICKER_DAILY_CAP_PRIORITY
    allowed, reason = tg._can_send("AAPL", significance=7.7, **WH)
    assert not allowed and reason == "daily_cap", \
        f"daily cap must bind even for a preempting whale, got {allowed},{reason}"


def test_disable_flag_restores_old_behavior():
    _reset()
    tg._ticker_last_sent["AAPL"] = time.time() - 600
    orig = tg.TICKER_COOLDOWN_PREEMPT_SIG
    tg.TICKER_COOLDOWN_PREEMPT_SIG = 0
    try:
        allowed, reason = tg._can_send("AAPL", significance=7.7, **WH)
        assert not allowed and reason == "ticker_cd", \
            f"disabled preemption must ticker_cd, got {allowed},{reason}"
    finally:
        tg.TICKER_COOLDOWN_PREEMPT_SIG = orig


def test_aapl_today_scenario():
    """The real 6/15 sequence: first whale sends, then $5.6M LEAP +7m and $7.7M
    9/18 +33m both preempt (previously both ticker_cd-dropped)."""
    _reset()
    t0 = time.time() - 3300  # ~55 min ago, first AAPL send
    tg._ticker_last_sent["AAPL"] = t0
    # $5.6M LEAP, 7 min after the first send
    tg._ticker_last_sent["AAPL"] = time.time() - (33 * 60)  # simulate last send 33m ago
    leg1, r1 = tg._can_send("AAPL", significance=5.6, **WH)
    assert leg1, f"$5.6M LEAP should preempt, got {leg1},{r1}"
    # $7.7M 9/18, last send 26 min ago
    tg._ticker_last_sent["AAPL"] = time.time() - (26 * 60)
    leg2, r2 = tg._can_send("AAPL", significance=7.7, **WH)
    assert leg2, f"$7.7M 9/18 should preempt, got {leg2},{r2}"


TESTS = [
    test_big_whale_preempts_within_cooldown,
    test_small_alert_blocked_within_cooldown,
    test_big_whale_blocked_within_antispam_floor,
    test_just_under_threshold_blocked,
    test_after_cooldown_allowed_normally,
    test_daily_cap_still_binds_for_big_whale,
    test_disable_flag_restores_old_behavior,
    test_aapl_today_scenario,
]


def main() -> int:
    print("=" * 66)
    print("UNIT TESTS — telegram per-ticker cooldown preemption (#71)")
    print("=" * 66)
    p = f = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            p += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  — {e}")
            f += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  — {e!r}")
            f += 1
    print("=" * 66)
    print(f"RESULT: {p}/{p+f} passed, {f} failed")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
