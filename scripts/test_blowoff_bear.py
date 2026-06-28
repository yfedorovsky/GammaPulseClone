"""Integration test for the blow-off exhaustion bear (#122-D).

Verifies _determine_direction routes a stretched + rolled + IV-crushed name to
a structural BEAR (blowoff_exhaustion_bear) — the MU/SNDK 6/25 sell-the-news the
long-only engine missed — while leaving healthy uptrend pullbacks and runners
alone, and preserving momentum-override precedence.

Run:  python scripts/test_blowoff_bear.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server import signals as S          # noqa: E402
from server import euphoria_brake as E   # noqa: E402

# Deterministic catalyst (no DB): monkeypatch the IV-crush helper.
_crush = {"v": True}
E.iv_crush = lambda *a, **k: _crush["v"]

_p = _f = 0


def chk(name, got, want):
    global _p, _f
    if got == want:
        _p += 1; print(f"  PASS  {name}")
    else:
        _f += 1; print(f"  FAIL  {name}: got {got!r} want {want!r}")


def mk(spot, ma20, vs_open, vs_high, signal=""):
    return {"actual_spot": spot, "_rts": {"mas": {"ma20": ma20}},
            "_intraday_momentum": {"vs_open_pct": vs_open, "vs_high_pct": vs_high},
            "signal": signal}


# 1. extended +22% over MA20 + tape rolled + IV crush -> blow-off BEAR
_crush["v"] = True
st = mk(1233, 1010, -0.7, -1.5)
d = S._determine_direction(st, "MU")
chk("MU blow-off -> BEAR", (d, st.get("_last_direction_source")),
    ("BEAR", "blowoff_exhaustion_bear"))

# 2. extended + rolled but NO catalyst -> NOT blow-off (uptrend-pullback guard)
_crush["v"] = False
st = mk(1233, 1010, -0.7, -1.5)
S._determine_direction(st, "MU")
chk("no catalyst -> not blowoff",
    st.get("_last_direction_source") != "blowoff_exhaustion_bear", True)

# 3. up-continuing (not rolled) -> NOT blow-off (ARM-runner guard)
_crush["v"] = True
st = mk(256, 205, 1.2, -0.05)
S._determine_direction(st, "ARM")
chk("ARM up-continuing -> not blowoff",
    st.get("_last_direction_source") != "blowoff_exhaustion_bear", True)

# 4. not extended -> NOT blow-off even if rolled + crush
_crush["v"] = True
st = mk(102, 100, -0.7, -1.5)
S._determine_direction(st, "X")
chk("not extended -> not blowoff",
    st.get("_last_direction_source") != "blowoff_exhaustion_bear", True)

# 5. momentum_override (>2.5% down) still takes precedence
_crush["v"] = True
st = mk(1233, 1010, -3.0, -3.0)
d = S._determine_direction(st, "MU")
chk("momentum_override precedence", (d, st.get("_last_direction_source")),
    ("BEAR", "momentum_override_bear"))

print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
