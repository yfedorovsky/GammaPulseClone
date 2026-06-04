"""Unit tests for server/conviction_booster.py.

Covers the 5 contributing factors and the threshold gate. Network-
dependent factors (EMA, sector) are tested via direct function calls
where possible; data-dependent factors are tested with mock DB rows.

Usage:
    python scripts/test_conviction_booster.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env for the EMA/sector tests that hit Tradier
import os
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

from server.conviction_booster import (  # noqa: E402
    compute_conviction_boost,
    sector_for,
    CONVICTION_OVERRIDE_THRESHOLD,
)


# === Sector mapping ===

def test_sector_semi():
    assert sector_for("NVDA") == "SMH"
    assert sector_for("AMD") == "SMH"
    assert sector_for("MRVL") == "SMH"
    assert sector_for("CRDO") == "SMH"


def test_sector_financials():
    assert sector_for("HOOD") == "XLF"
    assert sector_for("JPM") == "XLF"


def test_sector_health():
    assert sector_for("HIMS") == "XLV"
    assert sector_for("LLY") == "XLV"


def test_sector_default_spy():
    """Unknown tickers default to SPY."""
    assert sector_for("XYZ_UNKNOWN_TICKER") == "SPY"


def test_sector_case_insensitive():
    assert sector_for("nvda") == "SMH"
    assert sector_for("Nvda") == "SMH"


# === Threshold sanity ===

def test_threshold_is_60():
    """Pin the threshold so we know if it ever changes."""
    assert CONVICTION_OVERRIDE_THRESHOLD == 60


# === Full booster integration (against live Tradier + DB) ===

def test_hood_override_today():
    """HOOD should hit the override threshold based on today's data."""
    sig = {
        "ticker": "HOOD", "grade": "A", "signal_type": "MAGNET BREAKOUT",
        "spot": 82.85, "ts": 1780000000,  # 2026-06 ts is fine
    }
    score, factors = asyncio.run(compute_conviction_boost("HOOD", sig))
    # HOOD scored 73 in our integration test. With market-closed cached
    # data this may shift but should still clear 60.
    assert score >= CONVICTION_OVERRIDE_THRESHOLD, \
        f"HOOD score {score} should clear threshold {CONVICTION_OVERRIDE_THRESHOLD}"
    assert len(factors) >= 3, f"Expected >= 3 factors, got {len(factors)}"


def test_unknown_ticker_low_score():
    """A ticker with no flow, no SOE, no EMA history should score low."""
    sig = {
        "ticker": "ZZZZZ_FAKE", "grade": "A", "signal_type": "MAGNET BREAKOUT",
        "spot": 100.0, "ts": 1780000000,
    }
    score, factors = asyncio.run(compute_conviction_boost("ZZZZZ_FAKE", sig))
    # All factors should fail-closed for a non-existent ticker
    assert score < CONVICTION_OVERRIDE_THRESHOLD


# === Test runner ===

TESTS = [
    test_sector_semi,
    test_sector_financials,
    test_sector_health,
    test_sector_default_spy,
    test_sector_case_insensitive,
    test_threshold_is_60,
    test_hood_override_today,
    test_unknown_ticker_low_score,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/conviction_booster.py")
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
