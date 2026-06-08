"""Unit tests for the 0DTE put-side override (task #58, 6/5 forensic).

Run:  python scripts/test_0dte_put_side.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.flow_alerts import _0dte_put_directional_override as ovr  # noqa: E402
import server.structure_regime as sr  # noqa: E402

_passed = 0
_failed = 0
TODAY = date.today().isoformat()
FUTURE = (date.today() + timedelta(days=5)).isoformat()


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def call(**kw):
    base = dict(otype="put", side="MID", sentiment="NEUTRAL", opt_exp=TODAY,
               strike=750, spot=747.0, vol=20000, oi=2000, notional=94_000_000,
               gex_regime="NEG", gex_signal="DANGER")
    base.update(kw)
    return ovr(base["otype"], base["side"], base["sentiment"],
               opt_exp=base["opt_exp"], strike=base["strike"], spot=base["spot"],
               vol=base["vol"], oi=base["oi"], notional=base["notional"],
               gex_regime=base["gex_regime"], gex_signal=base["gex_signal"])


def main() -> int:
    print("=== 0DTE put-side override (task #58) tests ===")
    sr._reset_for_test()  # ensure structure cache empty (no accidental risk-off)

    # canonical 6/5: SPY 750P $94M MID on a NEG/DANGER tape → BEARISH
    s, flip = call()
    check("canonical SPY 750P -> BEARISH", s == "BEARISH" and flip is True, f"{s},{flip}")

    # DANGER signal alone (regime missing) still triggers
    s, flip = call(gex_regime=None, gex_signal="DANGER")
    check("DANGER signal triggers", s == "BEARISH" and flip, f"{s},{flip}")

    # MAGNET FADE triggers
    s, flip = call(gex_regime=None, gex_signal="MAGNET FADE")
    check("MAGNET FADE triggers", flip is True)

    # NOT risk-off (POS regime, benign signal, no index structure) → no flip
    s, flip = call(gex_regime="POS", gex_signal="MAGNET UP")
    check("not risk-off -> no flip", s == "NEUTRAL" and flip is False, f"{s},{flip}")

    # not a put → no flip
    s, flip = call(otype="call")
    check("call -> no flip", flip is False)

    # not MID (already directional) → untouched
    s, flip = call(side="ASK", sentiment="BEARISH")
    check("ASK/BEARISH untouched", s == "BEARISH" and flip is False)

    # not 0DTE → no flip
    s, flip = call(opt_exp=FUTURE)
    check("future expiry -> no flip", flip is False)

    # not near-the-money (far OTM) → no flip
    s, flip = call(strike=700)  # 700 vs 747 = 6.3% away
    check("far OTM -> no flip", flip is False)

    # low notional → no flip
    s, flip = call(notional=500_000)
    check("low notional -> no flip", flip is False)

    # low vol/oi (stale OI, not fresh directional) → no flip
    s, flip = call(vol=2000, oi=2000)  # voi=1.0
    check("low voi -> no flip", flip is False)

    # index-structure fallback: no ticker GEX context, but market risk-off
    sr._reset_for_test()
    sr.update_index_structure("SPY", {
        "structure_regime": "VOLATILE", "structure_score": 80,
        "structure_risk_off": True, "net_cex": -5e9, "charm_anchor": {},
        "pos_gex": 1e9, "neg_gex": -6e9, "zgl": 700, "_oi_mode": "raw",
    }, 747.0)
    s, flip = call(gex_regime=None, gex_signal=None)
    check("index-structure risk-off triggers", s == "BEARISH" and flip, f"{s},{flip}")
    sr._reset_for_test()
    # and with structure cleared → no flip
    s, flip = call(gex_regime=None, gex_signal=None)
    check("no context anywhere -> no flip", flip is False)

    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
