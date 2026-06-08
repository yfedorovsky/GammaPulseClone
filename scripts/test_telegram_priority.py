"""Unit tests for high-value alert auto-elevation (task #52).

Whale / cluster / ladder / informed / basket banners must bypass the global
rate_window + per-ticker cooldown so they're never dropped on hot names
(MRVL $340M whale 6/8: 10+ alerts fired, ~all rate_window-dropped, user saw 1).

Run:  python scripts/test_telegram_priority.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows cp1252 console chokes on the 🐋 emoji in test names
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import server.telegram as tg  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def _reset():
    tg._message_times.clear()
    tg._ticker_last_sent.clear()
    tg._ticker_daily_count.clear()


# ── _is_high_value_alert ──────────────────────────────────────────────────
def test_detector():
    hi = [
        "🐋🐋🐋 WHALE ACCUMULATION 🐋🐋🐋 $2.4M ASK",
        "🟢 CLUSTER FLOW: MRVL (BULLISH) 11 legs in 60s",
        "⚡ CLUSTER RESOLUTION — MRVL Resolved MIXED-BULL",
        "🐋 MULTI-TENOR LADDER — MRVL 8 expirations",
        "⚡ INTRADAY CLUSTER — NVDA",
        "⚡⚡⚡ INFORMED FLOW (5/6) ⚡⚡⚡",
        "🔴 BASKET — MRVL 2026-06-12 CALL 15 strikes",
    ]
    for t in hi:
        check(f"high-value: {t[:28]!r}", tg._is_high_value_alert(t) is True, t)
    lo = [
        "🟢 FLOW [MEDIUM]: NVDA BUY CALLS",
        "🔴 FLOW [HIGH]: AAPL BUY PUTS",
        "📊 daily scorecard",
    ]
    for t in lo:
        check(f"normal: {t[:28]!r}", tg._is_high_value_alert(t) is False, t)


# ── rate_window bypass via force (what auto-elevation sets) ────────────────
def test_rate_window_bypass():
    _reset()
    # saturate the global window (3 sends)
    for _ in range(tg.MAX_MESSAGES_PER_WINDOW):
        tg._record_sent("")
    # a normal (non-priority, non-force) message is now rate_window-dropped
    allowed, reason = tg._can_send("NVDA", priority=False, force=False)
    check("normal hits rate_window when saturated", not allowed and reason == "rate_window",
          f"{allowed},{reason}")
    # a high-value alert (auto-elevated to force) goes through
    allowed, reason = tg._can_send("NVDA", force=True)
    check("force bypasses rate_window", allowed and reason == "", f"{allowed},{reason}")


# ── ticker cooldown bypass via force (priority does NOT) ───────────────────
def test_cooldown_bypass():
    _reset()
    tg._ticker_last_sent["MRVL"] = time.time()  # MRVL just sent → in cooldown
    # priority alone still gets cooldown-dropped (the MRVL BASKET case on 6/8)
    allowed, reason = tg._can_send("MRVL", priority=True, force=False)
    check("priority still hits ticker_cd", not allowed and reason == "ticker_cd",
          f"{allowed},{reason}")
    # force bypasses the cooldown → multi-tenor whale legs all land
    allowed, reason = tg._can_send("MRVL", force=True)
    check("force bypasses ticker_cd", allowed and reason == "", f"{allowed},{reason}")


# ── daily cap STILL bounds force (no flood) ───────────────────────────────
def test_daily_cap_bounds_force():
    _reset()
    day = tg._today_str()
    tg._ticker_daily_count[("MRVL", day)] = tg.PER_TICKER_DAILY_CAP_PRIORITY  # at cap (6)
    allowed, reason = tg._can_send("MRVL", force=True)
    check("force still bounded by daily cap", not allowed and reason == "daily_cap",
          f"{allowed},{reason}")
    # one below cap → allowed
    tg._ticker_daily_count[("MRVL", day)] = tg.PER_TICKER_DAILY_CAP_PRIORITY - 1
    allowed, reason = tg._can_send("MRVL", force=True)
    check("force allowed below cap", allowed, f"{allowed},{reason}")


# ── replay: busy-tape wall bypassed, but per-ticker cooldown caps spam ─────
def test_busy_tape_bypass():
    """High-value alerts on a SATURATED window still land (the drop fix) —
    one per ticker. priority bypasses rate_window but respects cooldown."""
    _reset()
    for _ in range(3):  # saturate global window
        tg._record_sent("SPY")
    # 4 DIFFERENT hot names each fire one whale — all should land despite the
    # saturated window (this is the MRVL/COIN/DDOG drop fix)
    landed = 0
    for tk in ("MRVL", "COIN", "DDOG", "GOOGL"):
        priority = tg._is_high_value_alert("🐋🐋🐋 WHALE ACCUMULATION 🐋🐋🐋")
        allowed, _ = tg._can_send(tk, priority=priority)
        if allowed:
            landed += 1
            tg._record_sent(tk)
    check("4 different-ticker whales all land on busy tape", landed == 4, f"landed={landed}")


def test_per_ticker_cooldown_caps_spam():
    """The 12:48 fix: a SINGLE hot name can't spam — priority respects the
    per-ticker cooldown, so only the first high-value alert lands."""
    _reset()
    landed = 0
    for i in range(6):  # MRVL tries to fire 6 whales in quick succession
        priority = tg._is_high_value_alert("🐋🐋🐋 WHALE ACCUMULATION 🐋🐋🐋")
        allowed, reason = tg._can_send("MRVL", priority=priority)
        if allowed:
            landed += 1
            tg._record_sent("MRVL")
    check("single name capped to 1 (no spam flood)", landed == 1, f"landed={landed}")


def main() -> int:
    print("=== telegram high-value auto-elevation (task #52) tests ===")
    for fn in (test_detector, test_rate_window_bypass, test_cooldown_bypass,
               test_daily_cap_bounds_force, test_busy_tape_bypass,
               test_per_ticker_cooldown_caps_spam):
        print(f"\n{fn.__name__}:")
        fn()
    _reset()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
