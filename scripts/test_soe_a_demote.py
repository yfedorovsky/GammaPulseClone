"""Tests for the SOE_A Telegram demote (#121). Run: python scripts/test_soe_a_demote.py"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import telegram as tg  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_default_demoted():
    os.environ.pop("SOE_A_TELEGRAM", None)
    check("grade A demoted by default", tg.soe_a_demoted("A") is True)
    check("grade A+ NOT demoted", tg.soe_a_demoted("A+") is False)
    check("grade B+ NOT demoted", tg.soe_a_demoted("B+") is False)
    check("None grade NOT demoted", tg.soe_a_demoted(None) is False)
    check("lowercase 'a' demoted (normalized)", tg.soe_a_demoted("a") is True)


def test_env_restores():
    os.environ["SOE_A_TELEGRAM"] = "1"
    try:
        check("SOE_A_TELEGRAM=1 restores grade A", tg.soe_a_demoted("A") is False)
        check("gate on => soe_a_telegram_on True", tg.soe_a_telegram_on() is True)
    finally:
        os.environ.pop("SOE_A_TELEGRAM", None)
    check("gate off by default", tg.soe_a_telegram_on() is False)


def test_signals_imports():
    import importlib
    import server.signals as s
    importlib.reload(s)
    check("signals imports with demote wiring", s is not None)


if __name__ == "__main__":
    print("test_soe_a_demote")
    test_default_demoted()
    test_env_restores()
    test_signals_imports()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
