"""Tests for the stale-spot circuit-breaker (cross-LLM audit rec).
Run: python scripts/test_stale_guard.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import stale_guard as sg  # noqa: E402
from server.structure_regime import apply_notch  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_shadow_default():
    os.environ.pop("STALE_GUARD_ACTIVE", None)
    r = sg.evaluate_stale("DIA", fetcher=lambda t: 1)
    check("stale detected", r["stale"] is True, str(r))
    check("tag set", r["tag"] == "stale-spot", str(r))
    check("SHADOW: notch_delta = 0 (no behaviour change)", r["notch_delta"] == 0, str(r))


def test_active_demotes():
    os.environ["STALE_GUARD_ACTIVE"] = "1"
    try:
        r = sg.evaluate_stale("DIA", fetcher=lambda t: 1)
        check("ACTIVE: notch_delta = -1", r["notch_delta"] == -1, str(r))
        check("HIGH demotes to MEDIUM under active guard",
              apply_notch("HIGH", r["notch_delta"]) == "MEDIUM", str(r))
    finally:
        os.environ.pop("STALE_GUARD_ACTIVE", None)


def test_fresh_is_noop():
    r = sg.evaluate_stale("SPY", fetcher=lambda t: 0)
    check("fresh -> not stale", r["stale"] is False, str(r))
    check("fresh -> no tag", r["tag"] is None, str(r))
    check("fresh -> notch 0", r["notch_delta"] == 0, str(r))


def test_fail_soft():
    def boom(t):
        raise RuntimeError("db down")
    r = sg.evaluate_stale("SPY", fetcher=boom)
    check("fetcher error -> fail-soft not stale", r["stale"] is False, str(r))


def test_banner():
    check("banner is a non-empty string", isinstance(sg.stale_banner(), str) and len(sg.stale_banner()) > 5)


def test_flow_alerts_imports():
    import importlib
    import server.flow_alerts as fa
    importlib.reload(fa)
    check("flow_alerts imports with stale-guard wiring", fa is not None)


if __name__ == "__main__":
    print("test_stale_guard")
    test_shadow_default()
    test_active_demotes()
    test_fresh_is_noop()
    test_fail_soft()
    test_banner()
    test_flow_alerts_imports()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
