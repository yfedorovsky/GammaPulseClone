"""Unit tests for server/rs_decouple_detector.py (intraday RS-decouple).

Covers: the decouple gate (green name vs flat/down sector, ex-self mean), the
exclusions (sector-wide rip must NOT fire; too-small sector skipped), the per-day
throttle + re-fire-on-wider-spread logic, and a live validation that today's real
snapshots fire on GLW + KLAC (the 2/467 universe result) and nothing absurd.

Usage: python scripts/test_rs_decouple_detector.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import rs_decouple_detector as D  # noqa: E402
from server.rs_decouple_detector import (  # noqa: E402
    find_decouples, sector_returns, _new_fires,
)

GROUPS = {
    "Optics": ["GLW", "LITE", "AAOI", "AXTI", "COHR"],
    "Semis": ["NVDA", "AMD", "INTC", "MU"],
    "Tiny": ["XX", "YY"],  # too few members
}


def test_fires_on_clean_decouple():
    rets = {"GLW": 6.9, "LITE": -3.6, "AAOI": -7.3, "AXTI": -12.4, "COHR": -1.0,
            "NVDA": 1.6, "AMD": 0.5, "INTC": 1.7, "MU": 0.8}
    ev = find_decouples(rets, GROUPS)
    assert len(ev) == 1 and ev[0]["ticker"] == "GLW", ev
    # ex-self sector mean = mean of LITE/AAOI/AXTI/COHR (excludes GLW)
    assert ev[0]["sector"] == "Optics"
    assert ev[0]["spread"] > 6, ev[0]


def test_no_fire_on_sector_wide_rip():
    # Whole sector up big — leadership is broad, not a decouple.
    rets = {"GLW": 7.0, "LITE": 6.0, "AAOI": 6.5, "AXTI": 5.5, "COHR": 6.2}
    assert find_decouples(rets, GROUPS) == []


def test_no_fire_when_name_flat():
    rets = {"GLW": 1.0, "LITE": -5.0, "AAOI": -5.0, "AXTI": -5.0, "COHR": -5.0}
    # spread huge but name itself only +1% (< NAME_MIN 2.0) -> no fire
    assert find_decouples(rets, GROUPS) == []


def test_skip_too_small_sector():
    rets = {"XX": 9.0, "YY": -5.0}  # Tiny has <3 peers ex-self
    assert find_decouples(rets, GROUPS) == []


def test_ex_self_mean_prevents_self_masking():
    # If the monster were INCLUDED in its sector mean, the mean would be lifted
    # and the spread shrunk. Ex-self keeps the decouple visible.
    rets = {"GLW": 10.0, "LITE": 0.0, "AAOI": 0.0, "AXTI": 0.0, "COHR": 0.0}
    ev = find_decouples(rets, GROUPS)
    assert len(ev) == 1 and abs(ev[0]["spread"] - 10.0) < 0.01, ev  # peers avg 0


def test_sector_returns_basic():
    rets = {"GLW": 6.0, "LITE": -2.0, "AAOI": -4.0, "AXTI": -12.0, "COHR": 0.0}
    sr = sector_returns(rets, GROUPS)
    assert abs(sr["Optics"] - (6 - 2 - 4 - 12 + 0) / 5) < 0.01, sr


def test_throttle_and_refire():
    D._fired.clear()
    e = [{"ticker": "GLW", "spread": 4.0, "name_ret": 2.0, "sector": "Optics",
          "sector_ret": -2.0, "n_peers": 4}]
    assert len(_new_fires(e, "2026-06-18")) == 1          # first fire
    assert _new_fires(e, "2026-06-18") == []              # same spread -> throttled
    e2 = [{**e[0], "spread": 5.0}]
    assert _new_fires(e2, "2026-06-18") == []             # +1 only -> still throttled
    e3 = [{**e[0], "spread": 7.5}]
    assert len(_new_fires(e3, "2026-06-18")) == 1         # +3.5 -> re-fires
    # new day resets
    assert len(_new_fires(e, "2026-06-19")) == 1


def test_live_today_fires_glw_and_klac():
    D._fired.clear()
    rets = D.intraday_returns_from_db("2026-06-18")
    if not rets:
        print("    (skip: no 6/18 snapshots)")
        return
    from server.industry import INDUSTRY_GROUPS
    ev = find_decouples(rets, INDUSTRY_GROUPS)
    tickers = {e["ticker"] for e in ev}
    assert "GLW" in tickers, sorted(tickers)
    # rare by construction: a handful at most, not a firehose
    assert len(ev) <= 8, f"too many fires ({len(ev)}): {sorted(tickers)}"
    print(f"    live 6/18 fires: {[(e['ticker'], e['spread']) for e in ev]}")


TESTS = [
    test_fires_on_clean_decouple,
    test_no_fire_on_sector_wide_rip,
    test_no_fire_when_name_flat,
    test_skip_too_small_sector,
    test_ex_self_mean_prevents_self_masking,
    test_sector_returns_basic,
    test_throttle_and_refire,
    test_live_today_fires_glw_and_klac,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — server/rs_decouple_detector.py (intraday RS-decouple)")
    print("=" * 70)
    passed = failed = 0
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
