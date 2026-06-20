"""Regression test for the OTHER -> UI-only Telegram demotion (task #91).

The residual "OTHER" telegram category (soft-context flags: net_flow, swing,
rs-accel EOD, gex-magnet, price-watch, runner, macro-pivot) is suppressed from
Telegram (UI/DB untouched) unless OTHER_TELEGRAM=1. MANDATORY carve-out:
🚀 RS DECOUPLE is genuine edge and is KEPT. Categorized members of the 10 known
marker groups (WHALE/KING/SOE/etc.) are NOT touched by this gate.

Run: python scripts/test_other_demote.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import telegram as T  # noqa: E402

CASES = [
    # OTHER soft-context flags -> demote
    ("💹 NET FLOW: KLAC\n📈 FLOW LEADS UP  🔵 HIGH BULLISH\nSpot $812.40", True,
     "net flow -> demote"),
    ("🔍 NEW SWING WATCHLIST ENTRY #2\n$WDC (Tech)\nSoft signal — watchlist entry.", True,
     "swing watchlist -> demote"),
    # Carve-out: the once-daily 📈 RS ACCELERATION EOD leaderboard digest is KEPT.
    ("📈 RS ACCELERATION — EOD (multi-day relative-strength momentum)\nClimbing: NOW +14", False,
     "rs-accel EOD digest -> KEEP (carve-out)"),
    ("🧲 GEX MAGNET ENTRY — TSM\nSpot $182.30 pinned toward the $185 magnet\nGEX regime POS", True,
     "gex magnet (no King word) -> demote"),
    # Categorizer quirk: a magnet message that mentions the GEX *King* strike
    # routes to KING (and is suppressed by the KING cut), not OTHER. Documented.
    ("🧲 GEX MAGNET ENTRY — TSM\nSpot $182.30 pinned toward King $185 magnet", False,
     "gex magnet mentioning King -> routes to KING (not other)"),
    ("🏃 RUNNER DAY 3 — PLTR\nholding the trend", True, "runner -> demote"),
    ("🔥 MACRO PIVOT DETECTED\nrisk-on rotation", True, "macro pivot -> demote"),
    ("PRICE WATCH — NVDA approaching $1300", True, "price watch -> demote"),
    # MANDATORY carve-out: RS DECOUPLE is genuine edge -> KEEP
    ("🚀 RS DECOUPLE — NOW\n+3.2% while XLK sector +0.4%\nCONTEXT — high-conviction flag.", False,
     "RS DECOUPLE -> KEEP (carve-out)"),
    # Categorized (non-OTHER) messages -> NOT this gate's business
    ("🐋 WHALE FLOW [A]: TSLA", False, "whale -> not other"),
    ("🐋 MULTI-TENOR LADDER: MU 9 exp $331M", False, "ladder -> not other"),
    ("👑 KING BREAKOUT: AMD", False, "king -> not other"),
    ("⚡ INFORMED CLUSTER: META 620C", False, "informed -> not other"),
    ("SWEEP: AMD 170C ISO sweep", False, "sweep -> not other"),
    ("SOE A+ signal: COST", False, "soe -> not other"),
    ("0DTE runway: SPY 600C", False, "zero-dte -> not other"),
    ("🎯 TAKE PROFIT: NVDA +50%", False, "exit/TP -> not other"),
    ("", False, "empty -> not other"),
]


def main() -> int:
    fails = 0
    for text, expected, desc in CASES:
        got = T.is_demoted_other(text)
        ok = got == expected
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}: {got}")

    os.environ.pop("OTHER_TELEGRAM", None)
    assert T.other_telegram_on() is False, "default must suppress (other_telegram_on False)"
    for v in ("1", "true", "YES", "on"):
        os.environ["OTHER_TELEGRAM"] = v
        assert T.other_telegram_on() is True, f"OTHER_TELEGRAM={v} must restore"
    os.environ.pop("OTHER_TELEGRAM", None)
    print("  [PASS] env polarity (default suppress, OTHER_TELEGRAM=1 restores)")

    # The other category cuts must remain intact (no cross-contamination).
    assert T.is_demoted_whale("🐋 WHALE FLOW [A]: TSLA") is True, "whale gate intact"
    assert T.is_demoted_king("👑 KING BREAKOUT: AMD") is True, "king gate intact"
    print("  [PASS] whale + king gates still intact")

    print("ALL TESTS PASSED" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
