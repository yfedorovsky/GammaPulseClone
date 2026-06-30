"""Tests for the spread/vol-regime gate (SPX scanner GATE 0).
Run: python scripts/test_spread_regime_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import spread_regime_gate as g  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def _opt(exp, strike, otype, bid, ask):
    return {"expiration_date": exp, "strike": strike, "option_type": otype,
            "bid": bid, "ask": ask}


def test_atm_spread_pct():
    spot = 7499.0
    contracts = [
        # front expiry — ATM is 7500; call+put both 10% of mid
        _opt("2026-07-01", 7495.0, "call", 12.0, 13.0),
        _opt("2026-07-01", 7500.0, "call", 9.5, 10.5),   # mid 10, spread 1 -> 10%
        _opt("2026-07-01", 7500.0, "put", 9.5, 10.5),    # 10%
        _opt("2026-07-01", 7505.0, "call", 7.0, 8.0),    # off-ATM, ignored
        # later expiry — must be IGNORED (front only)
        _opt("2026-07-08", 7500.0, "call", 20.0, 30.0),  # 40% — would skew if used
    ]
    pct = g.atm_spread_pct(contracts, spot)
    check("ATM front-expiry straddle spread ~10%", pct is not None and abs(pct - 0.10) < 0.005, str(pct))
    check("returns None on empty", g.atm_spread_pct([], spot) is None)
    check("returns None on no two-sided quotes",
          g.atm_spread_pct([_opt("2026-07-01", 7500.0, "call", 0, 0)], spot) is None)


def test_day_relative_high():
    t = g.SpreadRegimeTracker()
    base = 1_790_000_000
    # 25 calm samples OUTSIDE the 30-min trailing window (build the day distribution)
    for i in range(25):
        t.observe(0.04, base - 3600 + i * 60)   # base-3600 .. base-2160 (all >30m old)
    # a few toxic spikes INSIDE the trailing window
    for i in range(3):
        t.observe(0.20, base - 200 + i * 60)
    r = t.assess(base)
    check("HIGH: trailing spike > day p90", r["is_high"] is True, str(r))
    check("HIGH: basis is day_p90 (enough samples)", r["basis"] == "day_p90", str(r))
    check("HIGH: trailing ~0.20", abs(r["trailing_30m_pct"] - 0.20) < 1e-6, str(r))

    # calm tape: 25 samples all calm INSIDE the trailing window
    t2 = g.SpreadRegimeTracker()
    for i in range(25):
        t2.observe(0.04, base - 1400 + i * 50)
    r2 = t2.assess(base)
    check("NORMAL: calm trailing not > day p90", r2["is_high"] is False, str(r2))


def test_early_session_abs_fallback():
    base = 1_790_000_000
    t = g.SpreadRegimeTracker()
    for i in range(5):  # <20 samples -> abs fallback
        t.observe(0.15, base - 200 + i * 30)
    r = t.assess(base)
    check("early HIGH via abs fallback (0.15 > 0.12)", r["is_high"] is True and r["basis"] == "abs_fallback", str(r))
    t2 = g.SpreadRegimeTracker()
    for i in range(5):
        t2.observe(0.05, base - 200 + i * 30)
    r2 = t2.assess(base)
    check("early NORMAL via abs fallback (0.05 < 0.12)", r2["is_high"] is False and r2["basis"] == "abs_fallback", str(r2))
    check("no data -> is_high None", t2.assess(base + 5 * 86400)["is_high"] is None)


def test_day_gc():
    base = 1_790_000_000
    t = g.SpreadRegimeTracker()
    t.observe(0.04, base)               # day 1
    t.observe(0.05, base + 86400)        # day 2 (next ET day) -> day 1 GC'd
    check("only current day retained", len(t._by_day) == 1, str(list(t._by_day)))


def test_check_glue():
    # the live adapter extracts contracts + spot from a state dict
    state = {
        "actual_spot": 7499.0,
        "_raw_contracts": {
            "2026-07-01": [
                _opt("2026-07-01", 7500.0, "call", 9.5, 10.5),
                _opt("2026-07-01", 7500.0, "put", 9.5, 10.5),
            ]
        },
    }
    r = g.check_spread_regime(state, now=1_790_000_500)
    check("glue extracts current_spread_pct ~10%", abs(r["current_spread_pct"] - 0.10) < 0.005, str(r))
    check("glue returns a verdict dict", "is_high" in r and "basis" in r, str(r))


if __name__ == "__main__":
    print("test_spread_regime_gate")
    test_atm_spread_pct()
    test_day_relative_high()
    test_early_session_abs_fallback()
    test_day_gc()
    test_check_glue()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
