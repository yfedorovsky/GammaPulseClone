"""Unit tests for server/euphoria_brake.py (#122-B).

Run:  python scripts/test_euphoria_brake.py
All inputs injected — no DB. The headline test is the ARM-runner guard:
an extended, IV-crushed, but UP-CONTINUING tape must PASS (the verifier's
fix for the original self-defeating clean-continuation guard).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server import euphoria_brake as E  # noqa: E402

_p = _f = 0


def check(name, got, want):
    global _p, _f
    if got == want:
        _p += 1; print(f"  PASS  {name}")
    else:
        _f += 1; print(f"  FAIL  {name}: got {got!r} want {want!r}")


ROLLED = {"vs_high_pct": -1.5, "vs_open_pct": -0.7}      # off the high, red
UP = {"vs_high_pct": -0.05, "vs_open_pct": +1.2}         # up-continuing
FLAT_OPEN = {"vs_high_pct": -0.1, "vs_open_pct": -0.25}  # just below open

# 1. MU Thursday: +22% over MA20, post-print IV crush, tape rolled -> SUPPRESS
s = E.euphoria_state("MU", 1233, ma20=1010, intraday=ROLLED, iv_now=96, iv_prior=120)
check("MU blow-off rolled -> SUPPRESS", s["verdict"], "SUPPRESS")

# 2. ARM-runner guard: extended + IV crush BUT up-continuing -> PASS (critical)
s = E.euphoria_state("ARM", 256, ma20=205, intraday=UP, iv_now=100, iv_prior=136)
check("ARM runner up-continuing -> PASS", s["verdict"], "PASS")
check("ARM was extended", s["extended"], True)
check("ARM iv crushed", s["iv_crush"], True)
check("ARM tape NOT rolled", s["tape_rolled"], False)

# 3. not extended -> PASS even with catalyst + rolled
s = E.euphoria_state("X", 102, ma20=100, intraday=ROLLED, iv_now=80, iv_prior=120)
check("not extended -> PASS", s["verdict"], "PASS")

# 4. extended + rolled but NO catalyst -> PASS
s = E.euphoria_state("X", 130, ma20=100, intraday=ROLLED, iv_now=100, iv_prior=101)
check("no catalyst -> PASS", s["verdict"], "PASS")

# 5. blow-off extreme (>=25% over MA20) + catalyst + rolled -> INVERT
s = E.euphoria_state("MU", 1285, ma20=1010, intraday=ROLLED, iv_now=96, iv_prior=120)
check("blow-off extreme -> INVERT", s["verdict"], "INVERT")

# 6. pre-catalyst path: forward ER inside bounded window + rolled -> SUPPRESS
# (+20% over MA20: extended but below the +25% INVERT extreme)
s = E.euphoria_state("Y", 120, ma20=100, dte=3, er_in_window_days=2,
                     intraday=ROLLED, iv_now=100, iv_prior=100)
check("pre-ER window -> SUPPRESS", s["verdict"], "SUPPRESS")

# 7. pre-catalyst too far out (ER 20d, dte 30) -> PASS (bounded window)
s = E.euphoria_state("Y", 130, ma20=100, dte=30, er_in_window_days=20,
                     intraday=ROLLED, iv_now=100, iv_prior=100)
check("ER a month out -> PASS", s["verdict"], "PASS")

# 8. tape_rolled helper
check("rolled: off high", E.tape_rolled({"vs_high_pct": -0.6, "vs_open_pct": 0.5}), True)
check("rolled: below open", E.tape_rolled({"vs_high_pct": -0.1, "vs_open_pct": -0.3}), True)
check("not rolled: up", E.tape_rolled(UP), False)
check("not rolled: no data", E.tape_rolled(None), False)

# 9. ATR path: 2.0 ATR suppresses, 2.8 inverts
e = E.extension(spot=130, ma20=100, atr=15)  # (130-100)/15 = 2.0
check("ATR 2.0 -> suppress", e["suppress"], True)
check("ATR 2.0 not invert", e["invert"], False)
e = E.extension(spot=145, ma20=100, atr=15)  # 3.0 ATR
check("ATR 3.0 -> invert", e["invert"], True)

# 10. iv_crush threshold
check("iv crush 20% -> True", E.iv_crush("Z", iv_now=80, iv_prior=100), True)
check("iv crush 3% -> False", E.iv_crush("Z", iv_now=97, iv_prior=100), False)

print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
