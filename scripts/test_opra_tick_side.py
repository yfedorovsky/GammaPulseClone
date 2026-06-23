"""Tests for the sub-second OPRA tick-side scaffold (#77).
Run: python scripts/test_opra_tick_side.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.opra_tick_side import (  # noqa: E402
    classify_aggressor, contract_key, SubSecondSideTracker, BUY, SELL, MID,
)

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_classify():
    check("at/above ask -> BUY", classify_aggressor(1.05, 1.00, 1.05) == BUY)
    check("above ask -> BUY", classify_aggressor(1.10, 1.00, 1.05) == BUY)
    check("at/below bid -> SELL", classify_aggressor(1.00, 1.00, 1.05) == SELL)
    check("below bid -> SELL", classify_aggressor(0.90, 1.00, 1.05) == SELL)
    check("above mid -> BUY", classify_aggressor(1.04, 1.00, 1.06) == BUY)
    check("below mid -> SELL", classify_aggressor(1.01, 1.00, 1.06) == SELL)
    check("exact mid -> MID", classify_aggressor(1.03, 1.00, 1.06) == MID)
    check("missing quotes -> MID", classify_aggressor(1.0, None, None) == MID)
    check("bad price -> MID", classify_aggressor("x", 1.0, 1.1) == MID)


def test_recent_side_nets_by_size():
    t = SubSecondSideTracker()
    k = contract_key("MU", 130, "2026-07-18", "call")
    now = 1_000_000.0
    # 3 buys (lift ask) size 10 each, 1 sell (hit bid) size 5 — net BUY
    t.record(k, 1.05, 1.00, 1.05, size=10, ts=now - 1.0)
    t.record(k, 1.06, 1.00, 1.05, size=10, ts=now - 0.8)
    t.record(k, 1.07, 1.00, 1.05, size=10, ts=now - 0.5)
    t.record(k, 1.00, 1.00, 1.05, size=5, ts=now - 0.2)
    r = t.recent_side(k, now=now, max_age_s=2.0)
    check("nets to BUY", r and r["side"] == BUY, str(r))
    check("buy_size 30 / sell_size 5", r and r["buy_size"] == 30 and r["sell_size"] == 5, str(r))
    check("confidence = 25/35", r and abs(r["confidence"] - round(25/35, 3)) < 1e-6, str(r))
    check("n=4", r and r["n"] == 4, str(r))


def test_recency_window_excludes_old():
    t = SubSecondSideTracker()
    k = contract_key("X", 1, "2026-07-18", "p")
    now = 5000.0
    t.record(k, 1.05, 1.0, 1.05, size=10, ts=now - 30.0)  # old BUY (outside 2s)
    r = t.recent_side(k, now=now, max_age_s=2.0)
    check("no recent trade -> None", r is None, str(r))
    t.record(k, 1.0, 1.0, 1.05, size=10, ts=now - 0.5)    # fresh SELL
    r2 = t.recent_side(k, now=now, max_age_s=2.0)
    check("fresh SELL read", r2 and r2["side"] == SELL, str(r2))


def test_prune():
    t = SubSecondSideTracker()
    now = 9000.0
    k1 = contract_key("A", 1, "e", "c")
    k2 = contract_key("B", 2, "e", "c")
    t.record(k1, 1.0, 0.9, 1.0, ts=now - 1)       # fresh
    t.record(k2, 1.0, 0.9, 1.0, ts=now - 1000)    # stale
    removed = t.prune(older_than_s=300, now=now)
    check("prune drops the stale contract only", removed == 1, str(removed))
    check("fresh contract survives", t.recent_side(k1, now=now) is not None)


if __name__ == "__main__":
    print("test_opra_tick_side")
    test_classify()
    test_recent_side_nets_by_size()
    test_recency_window_excludes_old()
    test_prune()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
