"""Unit tests for server/structure_regime.py (task #54, Layer 2).

Covers the index-structure cache + market synthesis + shadow/active gating.

Run:  python scripts/test_structure_regime.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.structure_regime as sr  # noqa: E402

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


def _ed(regime, score, risk_off, *, pos=1e9, neg=-6e9, anchor_side="below"):
    return {
        "structure_regime": regime,
        "structure_score": score,
        "structure_risk_off": risk_off,
        "net_cex": -5e9 if risk_off else 1e8,
        "charm_anchor": {"strike": 700, "side": anchor_side, "cex": -2e8},
        "pos_gex": pos,
        "neg_gex": neg,
        "zgl": 517,
        "_oi_mode": "raw",
    }


def _age(ticker, seconds):
    """Backdate a cached record's ts to simulate staleness."""
    with sr._lock:
        if ticker in sr._index_structure:
            sr._index_structure[ticker]["ts"] = time.time() - seconds


# ── cache writes ──────────────────────────────────────────────────────────
def test_cache_writes():
    sr._reset_for_test()
    sr.update_index_structure("SPY", _ed("VOLATILE", 80, True), 737.5)
    sr.update_index_structure("QQQ", _ed("PINNED", 5, False, pos=8e9, neg=-1e9), 500.0)
    sr.update_index_structure("NVDA", _ed("VOLATILE", 90, True), 100.0)  # ignored
    snap = sr.snapshot()
    check("SPY cached", "SPY" in snap["indices"])
    check("QQQ cached", "QQQ" in snap["indices"])
    check("non-index ignored", "NVDA" not in snap["indices"])


# ── market synthesis ──────────────────────────────────────────────────────
def test_no_data_neutral():
    sr._reset_for_test()
    ms = sr.get_market_structure()
    check("no data -> stale", ms["stale"] is True)
    check("no data -> not risk_off", ms["risk_off"] is False)
    check("no data -> NEUTRAL bias", ms["bias"] == "NEUTRAL")


def test_risk_off_when_index_short_gamma():
    sr._reset_for_test()
    sr.update_index_structure("SPY", _ed("VOLATILE", 80, True), 737.5)
    sr.update_index_structure("QQQ", _ed("PINNED", 5, False, pos=8e9, neg=-1e9), 500.0)
    ms = sr.get_market_structure()
    check("risk_off True (SPY short-gamma)", ms["risk_off"] is True, ms["reason"])
    check("bias RISK_OFF", ms["bias"] == "RISK_OFF")
    check("score = max (80)", ms["score"] == 80, str(ms["score"]))
    check("worst regime = VOLATILE", ms["regime"] == "VOLATILE")
    check("sources listed", len(ms["sources"]) == 2)


def test_risk_on_when_calm():
    sr._reset_for_test()
    sr.update_index_structure("SPY", _ed("PINNED", 5, False, pos=8e9, neg=-1e9), 737.5)
    sr.update_index_structure("QQQ", _ed("PINNED", 8, False, pos=8e9, neg=-1e9), 500.0)
    ms = sr.get_market_structure()
    check("calm -> not risk_off", ms["risk_off"] is False)
    check("calm -> RISK_ON bias", ms["bias"] == "RISK_ON", str(ms["score"]))


def test_score_floor_gate():
    # risk_off flag set but score below floor → not gated risk-off
    sr._reset_for_test()
    sr.update_index_structure("SPY", _ed("LEAN_VOL", 40, True), 737.5)
    ms = sr.get_market_structure()
    check("below score floor -> not risk_off", ms["risk_off"] is False,
          f"score={ms['score']} floor={sr.STRUCTURE_RISK_OFF_SCORE}")


def test_staleness():
    sr._reset_for_test()
    sr.update_index_structure("SPY", _ed("VOLATILE", 80, True), 737.5)
    _age("SPY", sr.STRUCTURE_STALE_SEC + 100)  # too old
    ms = sr.get_market_structure()
    check("stale data ignored -> stale", ms["stale"] is True)
    check("stale -> not risk_off (no gating)", ms["risk_off"] is False)


# ── per-alert evaluation (shadow vs active) ───────────────────────────────
def test_evaluate_shadow_mode():
    sr._reset_for_test()
    sr.STRUCTURE_GATE_ACTIVE = False  # shadow
    sr.update_index_structure("SPY", _ed("VOLATILE", 80, True), 737.5)
    v = sr.evaluate_alert("BULLISH", "NVDA")
    check("bullish risk-off: tag set", bool(v["tag"]), str(v))
    check("bullish risk-off SHADOW: notch 0", v["notch_delta"] == 0, str(v["notch_delta"]))
    vb = sr.evaluate_alert("BEARISH", "NVDA")
    check("bearish risk-off: confirm tag", "confirm" in (vb["tag"] or "").lower())
    check("bearish: no notch", vb["notch_delta"] == 0)


def test_evaluate_active_mode():
    sr._reset_for_test()
    sr.STRUCTURE_GATE_ACTIVE = True  # live gate
    sr.update_index_structure("SPY", _ed("VOLATILE", 80, True), 737.5)
    try:
        v = sr.evaluate_alert("BULLISH", "NVDA")
        check("bullish risk-off ACTIVE: demote notch",
              v["notch_delta"] == -sr.STRUCTURE_DEMOTE_NOTCHES, str(v["notch_delta"]))
    finally:
        sr.STRUCTURE_GATE_ACTIVE = False  # restore


def test_evaluate_calm_tape_no_tag():
    sr._reset_for_test()
    sr.STRUCTURE_GATE_ACTIVE = False
    sr.update_index_structure("SPY", _ed("PINNED", 5, False, pos=8e9, neg=-1e9), 737.5)
    v = sr.evaluate_alert("BULLISH", "NVDA")
    check("calm tape: no tag", v["tag"] is None)
    check("calm tape: no notch", v["notch_delta"] == 0)


# ── notch ladder math ─────────────────────────────────────────────────────
def test_apply_notch():
    check("HIGH -1 -> MEDIUM", sr.apply_notch("HIGH", -1) == "MEDIUM")
    check("MEDIUM -1 -> LOW", sr.apply_notch("MEDIUM", -1) == "LOW")
    check("LOW -1 -> LOW (clamp)", sr.apply_notch("LOW", -1) == "LOW")
    check("HIGH +1 -> HIGH (clamp)", sr.apply_notch("HIGH", 1) == "HIGH")
    check("notch 0 -> unchanged", sr.apply_notch("MEDIUM", 0) == "MEDIUM")
    check("unknown grade unchanged", sr.apply_notch("WHALE", -1) == "WHALE")


def test_telegram_banner_render():
    """Layer 3: format_flow_alert surfaces the structure banner when tagged."""
    try:
        from server.telegram import format_flow_alert
    except Exception as e:  # pragma: no cover
        check("telegram import", False, repr(e))
        return
    base = {
        "ticker": "NVDA", "sentiment": "BULLISH", "conviction": "MEDIUM",
        "option_type": "call", "side": "ASK", "spot": 100.0, "king": 105,
        "expiration": "2026-07-17", "strike": 105, "volume": 5000, "oi": 2000,
        "vol_oi": 2.5, "notional": 1_500_000, "last": 3.0, "bid": 2.9, "ask": 3.1,
        "iv": 0.4, "delta": 0.4, "floor": 95, "ceiling": 110,
        "signal": "MAGNET UP", "regime": "POS",
    }
    # without tag → no banner
    msg0 = format_flow_alert(dict(base))
    check("no tag -> no short-gamma banner", "SHORT-GAMMA" not in msg0)
    # with tag → banner present
    tagged = dict(base)
    tagged["_structure_tag"] = "⚠️ SHORT-GAMMA TAPE (VOLATILE)"
    tagged["_structure_reason"] = "long flagged on risk-off tape — short-gamma index tape: SPY"
    msg1 = format_flow_alert(tagged)
    check("tagged -> banner rendered", "SHORT-GAMMA TAPE" in msg1, msg1[:80])
    check("tagged -> reason rendered", "risk-off tape" in msg1)


def main() -> int:
    print("=== structure_regime (Layer 2+3) tests ===")
    for fn in (test_cache_writes, test_no_data_neutral,
               test_risk_off_when_index_short_gamma, test_risk_on_when_calm,
               test_score_floor_gate, test_staleness, test_evaluate_shadow_mode,
               test_evaluate_active_mode, test_evaluate_calm_tape_no_tag,
               test_apply_notch, test_telegram_banner_render):
        print(f"\n{fn.__name__}:")
        fn()
    # ensure shadow restored
    sr.STRUCTURE_GATE_ACTIVE = False
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
