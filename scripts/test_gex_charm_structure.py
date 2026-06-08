"""Unit tests for gex.py charm/CEX + dealer-structure-regime + pure-OI mode.

Covers task #54 Layer 1 (gex.py foundation):
  - _bsm_charm sanity (finite, per-day magnitude, call/put asymmetry)
  - _structure_regime classification across PINNED..VOLATILE + risk_off
  - compute_exp_data: new keys present, net_cex computed, charm_anchor,
    oi_mode "raw" vs "effective" diverge, backward-compat keys intact,
    bear-day (put-heavy/neg-dominant) chain → structure_risk_off True.

Run:  python scripts/test_gex_charm_structure.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.gex import (  # noqa: E402
    _bsm_charm,
    _structure_regime,
    compute_exp_data,
    build_signal,
)

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def mk(strike, otype, oi, *, iv=0.25, exp="2026-07-17", gamma=0.0, vol=0,
       delta=None, charm=0.0):
    """Synthetic Tradier-style option dict. gamma=0 triggers BSM synth path."""
    if delta is None:
        delta = 0.5 if otype == "call" else -0.5
    return {
        "strike": strike,
        "option_type": otype,
        "open_interest": oi,
        "volume": vol,
        "expiration_date": exp,
        "bid": 1.0, "ask": 1.1, "last": 1.05,
        "greeks": {
            "gamma": gamma, "vega": 0.1, "delta": delta,
            "mid_iv": iv, "theta": -0.05, "charm": charm,
        },
    }


# ── _bsm_charm ────────────────────────────────────────────────────────────
def test_charm_math():
    S, K, sig, T = 100.0, 100.0, 0.25, 40 / 365.0
    cc = _bsm_charm(S, K, sig, T, is_call=True)
    cp = _bsm_charm(S, K, sig, T, is_call=False)
    check("charm finite", all(abs(x) < 1.0 for x in (cc, cp)), f"{cc},{cp}")
    check("charm per-day small", abs(cc) < 0.05, f"{cc}")
    check("charm call != put (asymmetry)", abs(cc - cp) > 1e-9, f"{cc} vs {cp}")
    check("charm zero on bad input", _bsm_charm(0, K, sig, T) == 0.0)
    check("charm zero on T=0", _bsm_charm(S, K, sig, 0.0) == 0.0)


# ── _structure_regime ─────────────────────────────────────────────────────
def test_structure_regime():
    # spot well above flip, positive-gamma dominant → PINNED, not risk-off
    lab, score, ro = _structure_regime(100.0, 95.0, pos_gex=5e9, neg_gex=-1e9,
                                       has_real_flip=True)
    check("PINNED above flip pos-dom", lab == "PINNED" and not ro, f"{lab},{ro}")

    # spot well below flip → VOLATILE, risk-off
    lab, score, ro = _structure_regime(100.0, 106.0, pos_gex=1e9, neg_gex=-5e9,
                                       has_real_flip=True)
    check("VOLATILE below flip neg-dom", lab == "VOLATILE" and ro, f"{lab},{ro}")
    check("score high when risk-off", score >= 60, f"{score}")

    # spot right on the flip → INFLECTION
    lab, _, _ = _structure_regime(100.0, 100.1, pos_gex=3e9, neg_gex=-2.9e9,
                                  has_real_flip=True)
    check("INFLECTION on flip", lab == "INFLECTION", f"{lab}")

    # no real flip + neg dominant → VOLATILE + risk_off (SPY-Friday signature)
    lab, _, ro = _structure_regime(100.0, 70.0, pos_gex=1e9, neg_gex=-7e9,
                                   has_real_flip=False)
    check("no-flip neg-dom -> VOLATILE risk-off", lab == "VOLATILE" and ro,
          f"{lab},{ro}")

    # no real flip + pos dominant → PINNED
    lab, _, ro = _structure_regime(100.0, 130.0, pos_gex=8e9, neg_gex=-1e9,
                                   has_real_flip=False)
    check("no-flip pos-dom -> PINNED", lab == "PINNED", f"{lab}")

    # degenerate (no zgl) → NEUTRAL when pos-dom
    lab, _, ro = _structure_regime(100.0, 0.0, pos_gex=5e9, neg_gex=-1e9,
                                   has_real_flip=False)
    check("no zgl pos-dom -> NEUTRAL", lab == "NEUTRAL" and not ro, f"{lab}")


# ── compute_exp_data integration ──────────────────────────────────────────
def _bull_chain(spot=100.0):
    # call-heavy positive gamma clustered above spot
    cs = [mk(s, "call", oi=20000) for s in (102, 105, 108, 110)]
    ps = [mk(s, "put", oi=2000) for s in (92, 95, 98)]
    return cs + ps, spot


def _bear_chain(spot=100.0):
    # put-heavy → negative-gamma dominant, walls below spot
    ps = [mk(s, "put", oi=30000) for s in (90, 93, 95, 97, 99)]
    cs = [mk(s, "call", oi=1500) for s in (103, 106)]
    return ps + cs, spot


def test_compute_new_keys():
    contracts, spot = _bull_chain()
    ed = compute_exp_data(contracts, spot)
    for k in ("net_cex", "charm_anchor", "structure_regime", "structure_score",
              "structure_risk_off"):
        check(f"key present: {k}", k in ed, str(list(ed.keys())[:6]))
    # backward-compat: old keys still present
    for k in ("strikes", "king", "zgl", "pos_gex", "neg_gex", "net_vanna"):
        check(f"backward-compat key: {k}", k in ed)
    # per-strike rows carry net_cex
    check("per-strike net_cex present",
          ed["strikes"] and "net_cex" in ed["strikes"][0])
    # net_cex computed nonzero (BSM charm fallback fired)
    check("net_cex nonzero", abs(ed["net_cex"]) > 0.0, f"{ed['net_cex']}")
    # build_signal still works on the extended dict
    sig, regime, kp = build_signal(ed, spot)
    check("build_signal still returns", isinstance(sig, str) and regime in ("POS", "NEG"))


def test_bear_chain_risk_off():
    contracts, spot = _bear_chain()
    ed = compute_exp_data(contracts, spot)
    check("bear chain neg-dominant", ed["neg_gex"] and abs(ed["neg_gex"]) > ed["pos_gex"],
          f"pos={ed['pos_gex']:.0f} neg={ed['neg_gex']:.0f}")
    check("bear chain structure_risk_off True", ed["structure_risk_off"] is True,
          f"{ed['structure_regime']}")
    check("bear chain regime short-gamma label",
          ed["structure_regime"] in ("VOLATILE", "LEAN_VOL", "INFLECTION"),
          ed["structure_regime"])
    if ed.get("charm_anchor"):
        check("charm_anchor has side", ed["charm_anchor"].get("side") in ("below", "above", "at"))


def test_bull_chain_not_risk_off():
    contracts, spot = _bull_chain()
    ed = compute_exp_data(contracts, spot)
    check("bull chain pos-dominant", ed["pos_gex"] > abs(ed["neg_gex"] or 0),
          f"pos={ed['pos_gex']:.0f} neg={ed['neg_gex']:.0f}")
    check("bull chain not risk-off", ed["structure_risk_off"] is False,
          f"{ed['structure_regime']}")


def test_oi_mode_diverges():
    # add heavy volume so effective-OI inflation is visible vs raw
    contracts = [mk(s, "call", oi=10000, vol=50000) for s in (102, 105, 108)]
    contracts += [mk(s, "put", oi=10000, vol=50000) for s in (92, 95, 98)]
    spot = 100.0
    eff = compute_exp_data(contracts, spot, oi_mode="effective")
    raw = compute_exp_data(contracts, spot, oi_mode="raw")
    check("oi_mode tag set", eff["_oi_mode"] == "effective" and raw["_oi_mode"] == "raw")
    # effective inflates OI → larger |pos_gex| than raw
    check("effective OI inflates magnitude", eff["pos_gex"] > raw["pos_gex"],
          f"eff={eff['pos_gex']:.0f} raw={raw['pos_gex']:.0f}")
    # default == effective (backward compat)
    default = compute_exp_data(contracts, spot)
    check("default mode == effective",
          abs(default["pos_gex"] - eff["pos_gex"]) < 1.0)


def test_empty_chain():
    ed = compute_exp_data([], 100.0)
    check("empty chain has structure_regime", ed.get("structure_regime") == "NEUTRAL")
    check("empty chain not risk-off", ed.get("structure_risk_off") is False)


def main() -> int:
    print("=== gex charm/CEX + structure-regime tests ===")
    for fn in (test_charm_math, test_structure_regime, test_compute_new_keys,
               test_bear_chain_risk_off, test_bull_chain_not_risk_off,
               test_oi_mode_diverges, test_empty_chain):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
