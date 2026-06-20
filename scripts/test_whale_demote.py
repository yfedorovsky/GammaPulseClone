"""Regression test for the WHALE -> UI-only Telegram demotion (task #94).

Single-WHALE banners are suppressed from Telegram (UI/DB untouched) unless
WHALE_TELEGRAM=1; multi-tenor LADDER whales are KEPT. Run: python scripts/test_whale_demote.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import telegram as T  # noqa: E402

CASES = [
    ("🐋 WHALE FLOW [A]: TSLA", True, "single whale -> demote"),
    ("🐋🐋🐋 WHALE: NVDA $3M ASK BUYING", True, "whale banner -> demote"),
    ("🐋 MULTI-TENOR LADDER: MU 9 exp $331M", False, "ladder -> KEEP"),
    ("🐋 WHALE CLUSTER LADDER: AVGO", False, "ladder cluster -> KEEP"),
    ("⚡ INFORMED CLUSTER: META 620C", False, "informed -> not whale"),
    ("SWEEP: AMD 170C ISO sweep", False, "sweep -> not whale"),
    ("", False, "empty -> not whale"),
]


def main() -> int:
    fails = 0
    for text, expected, desc in CASES:
        got = T.is_demoted_whale(text)
        ok = got == expected
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}: {got}")
    os.environ.pop("WHALE_TELEGRAM", None)
    assert T.whale_telegram_on() is False, "default must suppress (whale_telegram_on False)"
    for v in ("1", "true", "YES", "on"):
        os.environ["WHALE_TELEGRAM"] = v
        assert T.whale_telegram_on() is True, f"WHALE_TELEGRAM={v} must restore"
    os.environ.pop("WHALE_TELEGRAM", None)
    print("  [PASS] env polarity (default suppress, WHALE_TELEGRAM=1 restores)")
    print("ALL TESTS PASSED" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
