"""Unit tests for server/market_read.py synthesis (bear-day capstone).

Run:  python scripts/test_market_read.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.market_read import synthesize  # noqa: E402

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


def _struct(regime="PINNED", risk_off=False, score=10, stale=False):
    return {"regime": regime, "risk_off": risk_off, "score": score, "stale": stale}


def _base(bias="NEUTRAL", score=0, n=0, top=None):
    return {"bias": bias, "score": score, "n_patterns": n, "top": top or []}


def test_risk_off_from_structure():
    r = synthesize(_struct("VOLATILE", risk_off=True, score=80), _base("BULLISH", 50, 3))
    check("structure short-gamma -> RISK_OFF", r["posture"] == "RISK_OFF", r["summary"])
    check("long-flow note advises downside", "down-weight" in r["long_flow_note"])
    check("summary has emoji", r["summary"].startswith("🔴"))


def test_risk_off_from_bearish_baserate():
    r = synthesize(_struct("PINNED", risk_off=False), _base("BEARISH", -40, 2))
    check("bearish base-rate -> RISK_OFF", r["posture"] == "RISK_OFF", r["summary"])


def test_risk_on():
    r = synthesize(_struct("PINNED", risk_off=False), _base("BULLISH", 50, 3))
    check("bullish base-rate + calm tape -> RISK_ON", r["posture"] == "RISK_ON", r["summary"])
    check("risk-on tailwind note", "tailwind" in r["long_flow_note"])


def test_bullish_baserate_but_shortgamma_not_riskon():
    # bullish base-rate but tape is short-gamma → structure wins → RISK_OFF
    r = synthesize(_struct("VOLATILE", risk_off=True, score=70), _base("BULLISH", 50, 3))
    check("short-gamma overrides bullish base-rate", r["posture"] == "RISK_OFF", r["summary"])


def test_neutral():
    r = synthesize(_struct("INFLECTION", risk_off=False), _base("NEUTRAL", 0, 0))
    check("no decisive context -> NEUTRAL", r["posture"] == "NEUTRAL", r["summary"])
    check("neutral note", "no strong tilt" in r["long_flow_note"])


def test_directional_benchmark_text():
    d = {"ok": True, "horizon": 3, "prob_up": 57.8, "wf_auc": 0.485, "trustworthy": False}
    r = synthesize(_struct(), _base("BULLISH", 50, 3), d)
    check("directional shown as benchmark", "benchmark only" in r["summary"], r["summary"])
    check("directional prob in summary", "57.8%" in r["summary"])
    # trusted variant
    d2 = {"ok": True, "horizon": 3, "prob_up": 70, "wf_auc": 0.6, "trustworthy": True}
    r2 = synthesize(_struct(), _base("BULLISH", 50, 3), d2)
    check("trusted directional labeled", "trusted" in r2["summary"], r2["summary"])


def test_directional_absent_ok():
    r = synthesize(_struct(), _base("NEUTRAL", 0, 0), None)
    check("no directional -> still valid", r["posture"] == "NEUTRAL" and "directional" in r)


def main() -> int:
    print("=== market_read synthesis (bear-day capstone) tests ===")
    for fn in (test_risk_off_from_structure, test_risk_off_from_bearish_baserate,
               test_risk_on, test_bullish_baserate_but_shortgamma_not_riskon,
               test_neutral, test_directional_benchmark_text,
               test_directional_absent_ok):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
