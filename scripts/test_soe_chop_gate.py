"""Unit tests for server/soe_chop_gate.py (#122 chop/whipsaw gate).

Run:  python scripts/test_soe_chop_gate.py
Pure-logic — no DB / network. market_wide is injected; `now` is fixed.
"""
import os
import sys
from datetime import datetime, timezone

# Ensure the worktree's server/ wins over any installed copy.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from server import soe_chop_gate as G  # noqa: E402

NOW = datetime(2026, 6, 26, 15, 0, tzinfo=timezone.utc)  # -> ET day 2026-06-26
PBL = "POST BOTTOM LAUNCH"
MAG = "MAGNET BREAKOUT"
SUP = "SUPPORT BOUNCE"
PIN = "PINNING PREMIUM SELL"
BEAR_T = "BREAKDOWN ACCELERATOR"

_passed = 0
_failed = 0


def check(name, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}: got {got!r} want {want!r}")


def fire(tkr, st, bull=True, rts=30, mw=False):
    return G.evaluate_and_record(tkr, st, bull, rts, now=NOW, market_wide=mw)


def demoted(res):
    return res[0]


# 1. first-of-day breakout passes
G.reset()
check("first-of-day breakout passes", demoted(fire("LLY", PBL)), False)

# 2. type-flip: 2nd distinct directional-long type demotes
G.reset()
fire("UBER", PBL)
check("type-flip 2nd distinct type demotes", demoted(fire("UBER", MAG)), True)

# 3. refire-cap: allow up to 2 of same type, demote the 3rd
G.reset()
check("refire #1 same type passes", demoted(fire("DIA", PBL)), False)
check("refire #2 same type passes", demoted(fire("DIA", PBL)), False)
check("refire #3 same type demotes (cap)", demoted(fire("DIA", PBL)), True)

# 4. pin-contradiction: pin then dir-long demotes (AMAT case)
G.reset()
check("pin fire itself exempt", demoted(fire("AMAT", PIN)), False)
check("dir-long after pin demotes", demoted(fire("AMAT", SUP)), True)

# 5. PINNING PREMIUM SELL always exempt
G.reset()
check("pin exempt #1", demoted(fire("X", PIN)), False)
check("pin exempt #2", demoted(fire("X", PIN)), False)
check("pin exempt #3", demoted(fire("X", PIN)), False)

# 6. BEAR never touched, even repeated
G.reset()
check("bear #1 untouched", demoted(fire("Y", BEAR_T, bull=False)), False)
check("bear #2 untouched", demoted(fire("Y", BEAR_T, bull=False)), False)

# 7. RTS trend-leader exempt (LLY guard) — even on a type-flip
G.reset()
fire("LLY", PBL, rts=80)
check("RTS leader exempt on type-flip", demoted(fire("LLY", MAG, rts=80)), False)

# 8. market-wide tighten: only 1st dir-long passes when SPY chop
G.reset()
check("mkt-chop 1st passes", demoted(fire("BA", PBL, mw=True)), False)
check("mkt-chop 2nd same-type demotes", demoted(fire("BA", PBL, mw=True)), True)
# without market-wide, 2nd same-type would pass (no type-flip, under cap)
G.reset()
fire("BA", PBL, mw=False)
check("no-mkt-chop 2nd same-type passes", demoted(fire("BA", PBL, mw=False)), False)

# 9. UBER 4-fire Friday replay: 1 breakout passes, 2 contradictions demote, pin kept
G.reset()
r1 = demoted(fire("UBER", PBL))
r2 = demoted(fire("UBER", MAG))
r3 = demoted(fire("UBER", SUP))
r4 = demoted(fire("UBER", PIN))
check("UBER replay: 1st passes", r1, False)
check("UBER replay: 2nd demotes", r2, True)
check("UBER replay: 3rd demotes", r3, True)
check("UBER replay: pin kept", r4, False)

# 10. recorder is day-scoped (new day resets)
G.reset()
fire("Z", PBL)
fire("Z", MAG)  # demoted today
NEXT = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
r = G.evaluate_and_record("Z", MAG, True, 30, now=NEXT, market_wide=False)
check("new-day reset: first breakout passes", demoted(r), False)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
