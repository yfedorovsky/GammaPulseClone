"""Tests for the SPX STARS-ALIGN orchestrator (gate composition + throttle).
Run: python scripts/test_spx_stars_align.py
"""
from __future__ import annotations

import datetime as _dt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import spread_regime_gate as srg  # noqa: E402
from server import spx_stars_align as g  # noqa: E402

# We're testing the gate logic, not the clock or live data sources.
g._is_rth = lambda: True
# Soft gates hit live modules (snapshots DB / model training / net-flow) — stub to
# pass by default so the hard-gate tests are deterministic; veto-tested separately.
g._opening_drive_ok = lambda now: (True, "drive_up")
g._directional_ok = lambda: (True, "prior_ok")
g._flow_not_fighting = lambda: (True, "flow_ok")

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def _reset():
    g._fires_today.clear()
    srg._TRACKER._by_day.clear()


def _state(spot=7500.0, regime="POS", signal="MAGNET UP", risk_off=False,
           king_pos=7495.0, floor=7480.0, ceiling=7560.0, zgl=7470.0,
           atm_spread=0.04, exps=None):
    today = _dt.date.today()
    if exps is None:
        exps = ["MACRO", (today + _dt.timedelta(days=3)).isoformat()]
    raw = {}
    front = next((e for e in exps if e != "MACRO"), None)
    if front and atm_spread is not None:
        mid, half = 20.0, 20.0 * atm_spread / 2.0
        raw[front] = [
            {"expiration_date": front, "strike": 7500.0, "option_type": "call", "bid": mid - half, "ask": mid + half},
            {"expiration_date": front, "strike": 7500.0, "option_type": "put", "bid": mid - half, "ask": mid + half},
        ]
    return {
        "actual_spot": spot, "regime": regime, "signal": signal,
        "king_pos": king_pos, "king": king_pos, "floor": floor,
        "ceiling": ceiling, "zgl": zgl, "exps": exps, "_raw_contracts": raw,
        "exp_data": {"MACRO": {"structure_risk_off": risk_off}},
    }


def test_fire_path():
    _reset()
    sig, reason = g.evaluate(_state(), now=time.time())
    check("fully aligned -> FIRE", reason == "FIRE" and sig is not None, reason)
    if sig:
        check("limit at nearest support (king_pos 7495)", sig.support_name == "king_pos" and sig.support_level == 7495.0, str(sig))
        check("target = ceiling 7560", sig.target == 7560.0, str(sig))
        check("stop below support", sig.stop < sig.support_level, str(sig))
        check("weekly call strike $5-rounded ATM", sig.sugg_strike == 7500.0, str(sig))
        check("weekly DTE in [1,5]", 1 <= sig.sugg_dte <= 5, str(sig))


def test_gate_vetoes():
    cases = [
        ("spread_high", _state(atm_spread=0.15), "spread_high"),       # 15% single sample > abs fallback
        ("regime_NEG", _state(regime="NEG"), "regime_NEG"),
        ("signal_DANGER", _state(signal="DANGER"), "signal_DANGER"),
        ("structure_risk_off", _state(risk_off=True), "structure_risk_off"),
        ("not_at_support", _state(king_pos=7400.0, floor=7350.0, zgl=7300.0), "not_at_support"),
        ("no_weekly", _state(exps=["MACRO", (_dt.date.today() + _dt.timedelta(days=10)).isoformat()]), "no_weekly_expiry"),
    ]
    for label, st, expect in cases:
        _reset()
        sig, reason = g.evaluate(st, now=time.time())
        check(f"veto: {label}", sig is None and reason.startswith(expect.split('(')[0]), f"got {reason}")


def test_market_risk_off_veto():
    import server.structure_regime as sr
    saved = sr.get_market_structure
    sr.get_market_structure = lambda: {"risk_off": True}
    try:
        _reset()
        _, r = g.evaluate(_state(), now=time.time())  # _state() has no macro risk_off → falls to market read
        check("market-wide settled-OI risk_off vetoes", r == "market_risk_off", r)
    finally:
        sr.get_market_structure = saved


def test_daily_throttle():
    _reset()
    r = [g.evaluate(_state(), now=time.time())[1] for _ in range(3)]
    check("first two fire", r[0] == "FIRE" and r[1] == "FIRE", str(r))
    check("third blocked by daily_throttle", r[2] == "daily_throttle", str(r))


def test_soft_gate_vetoes():
    saved = (g._opening_drive_ok, g._directional_ok, g._flow_not_fighting)
    base = (lambda now: (True, "drive_up"), lambda: (True, "prior_ok"), lambda: (True, "flow_ok"))
    try:
        _reset(); g._opening_drive_ok, g._directional_ok, g._flow_not_fighting = base
        g._opening_drive_ok = lambda now: (False, "opening_drive_down")
        check("soft veto: opening_drive_down", g.evaluate(_state(), now=time.time())[1] == "opening_drive_down")
        _reset(); g._opening_drive_ok, g._directional_ok, g._flow_not_fighting = base
        g._directional_ok = lambda: (False, "prior_down(40)")
        check("soft veto: prior_down", g.evaluate(_state(), now=time.time())[1].startswith("prior_down"))
        _reset(); g._opening_drive_ok, g._directional_ok, g._flow_not_fighting = base
        g._flow_not_fighting = lambda: (False, "flow_BEARISH_DIVERGENCE")
        check("soft veto: flow bearish", g.evaluate(_state(), now=time.time())[1].startswith("flow_"))
    finally:
        g._opening_drive_ok, g._directional_ok, g._flow_not_fighting = saved


def test_adversarial_controls_logged():
    import server.alert_outcomes as ao
    calls: list = []
    saved = ao.log_alert
    ao.log_alert = lambda **kw: (calls.append(kw), "id")[1]
    try:
        _reset()
        sig, r = g.evaluate(_state(), now=time.time())
        check("setup fires for control test", r == "FIRE" and sig is not None, r)
        g._log_opposite(sig)
        put = [c for c in calls if c.get("alert_type") == "SPX_STARS_PUT"]
        check("opposite-direction PUT control logged (put/BEAR, same strike)",
              len(put) == 1 and put[0]["option_type"] == "put" and put[0]["direction"] == "BEAR"
              and put[0]["strike"] == sig.sugg_strike, str(put))
        # random-moment: force RTH + random trigger
        calls.clear(); g._rand_today.clear()
        orig = g._random.random
        g._random.random = lambda: 0.0
        try:
            g._maybe_log_random_moment(_state(), time.time())
        finally:
            g._random.random = orig
        rm = [c for c in calls if c.get("alert_type") == "SPX_STARS_RANDMOMENT"]
        check("random-moment CALL control logged (call/BULL)",
              len(rm) == 1 and rm[0]["option_type"] == "call" and rm[0]["direction"] == "BULL", str(rm))
        # random-moment respects its own daily cap
        calls.clear()
        g._random.random = lambda: 0.0
        try:
            for _ in range(5):
                g._maybe_log_random_moment(_state(), time.time())
        finally:
            g._random.random = orig
        check("random-moment capped at MAX_FIRES_PER_DAY",
              len([c for c in calls if c.get("alert_type") == "SPX_STARS_RANDMOMENT"]) <= g.MAX_FIRES_PER_DAY, str(len(calls)))
    finally:
        ao.log_alert = saved


def test_shadow_default_no_telegram():
    check("STARS_ALIGN_ACTIVE defaults off (shadow)", g._active() is False)
    sig, _ = g.evaluate(_state(), now=time.time()) if not g._fires_today else (None, "")
    # format_telegram must render without error
    _reset()
    sig, _ = g.evaluate(_state(), now=time.time())
    if sig:
        txt = g.format_telegram(sig)
        check("format_telegram renders", "SPX STARS-ALIGN" in txt and "BUY-LIMIT" in txt, txt[:60])


if __name__ == "__main__":
    print("test_spx_stars_align")
    test_fire_path()
    test_gate_vetoes()
    test_soft_gate_vetoes()
    test_adversarial_controls_logged()
    test_market_risk_off_veto()
    test_daily_throttle()
    test_shadow_default_no_telegram()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
