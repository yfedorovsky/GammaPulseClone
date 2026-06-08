"""Unit tests for server/analogue_confluence.py (task #55 follow-up).

Run:  python scripts/test_analogue_confluence.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.analogue_confluence as ac  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def mk_scan(symbol, patterns):
    """patterns: list of (name, hit20, n20)."""
    active = []
    for name, hit, n in patterns:
        active.append({
            "pattern": name, "bias": "bull", "occurrences": n,
            "forward": {5: {}, 10: {}, 20: {"n": n, "mean_pct": 1.0,
                                            "median_pct": 1.0, "hit_rate": hit}},
        })
    return {"symbol": symbol, "active": active}


# ── compute_market_bias ───────────────────────────────────────────────────
def test_bias_bullish():
    scans = [mk_scan("SPX", [("a", 65, 100), ("b", 64, 100)]),
             mk_scan("NDX", [("c", 60, 100)])]
    mb = ac.compute_market_bias(scans)
    check("bullish bias", mb["bias"] == "BULLISH", str(mb))
    check("positive score", mb["score"] > 0)
    check("n_patterns 3", mb["n_patterns"] == 3)
    check("top populated", len(mb["top"]) >= 1)


def test_bias_bearish():
    scans = [mk_scan("SPX", [("a", 38, 100), ("b", 40, 100)])]
    mb = ac.compute_market_bias(scans)
    check("bearish bias", mb["bias"] == "BEARISH", str(mb))
    check("negative score", mb["score"] < 0)


def test_bias_neutral_mixed():
    scans = [mk_scan("SPX", [("a", 65, 100), ("b", 35, 100)])]  # +15 and -15
    mb = ac.compute_market_bias(scans)
    check("mixed -> neutral", mb["bias"] == "NEUTRAL", str(mb))


def test_thin_sample_damped():
    # 70% hit but n<25 → vote (70-50)*0.5 = +10, below the 12 threshold alone
    scans = [mk_scan("SPX", [("a", 70, 15)])]
    mb = ac.compute_market_bias(scans)
    check("thin single -> not enough for bias", mb["bias"] == "NEUTRAL", str(mb))
    check("thin vote halved", abs(mb["net_vote"] - 10.0) < 0.01, str(mb["net_vote"]))


def test_min_n_filter():
    scans = [mk_scan("SPX", [("a", 90, 5)])]  # n<10 ignored
    mb = ac.compute_market_bias(scans)
    check("below MIN_N ignored", mb["n_patterns"] == 0)


def test_empty():
    mb = ac.compute_market_bias([])
    check("empty -> neutral", mb["bias"] == "NEUTRAL" and mb["n_patterns"] == 0)


# ── evaluate_flow_confluence ──────────────────────────────────────────────
def test_confluence_aligned():
    mb = {"bias": "BULLISH", "score": 60, "net_vote": 30, "n_patterns": 3,
          "top": [("SPX", "rsi_thrust_zweig", 15.0, 100)]}
    v = ac.evaluate_flow_confluence("BULLISH", mb)
    check("aligned True", v["aligned"] is True)
    check("confluence tag", "CONFLUENCE" in (v["tag"] or ""), str(v))
    vc = ac.evaluate_flow_confluence("CALL", mb)
    check("CALL treated bullish", vc["aligned"] is True)


def test_confluence_counter():
    mb = {"bias": "BEARISH", "score": -40, "net_vote": -20, "n_patterns": 2,
          "top": [("SPX", "death_cross", -12.0, 80)]}
    v = ac.evaluate_flow_confluence("BULLISH", mb)
    check("counter aligned False", v["aligned"] is False)
    check("counter tag", "counter" in (v["tag"] or "").lower(), str(v))


def test_confluence_neutral_no_tag():
    mb = {"bias": "NEUTRAL", "score": 0, "net_vote": 0, "n_patterns": 0, "top": []}
    v = ac.evaluate_flow_confluence("BULLISH", mb)
    check("neutral -> no tag", v["tag"] is None)


def test_confluence_nondirectional():
    mb = {"bias": "BULLISH", "score": 60, "net_vote": 30, "n_patterns": 3, "top": []}
    v = ac.evaluate_flow_confluence("NEUTRAL", mb)
    check("non-directional -> no tag", v["tag"] is None)


# ── cache ─────────────────────────────────────────────────────────────────
def test_cache():
    ac._reset_for_test()
    mb = ac.get_market_bias()
    check("default cache neutral", mb["bias"] == "NEUTRAL")
    ac._market_bias = {"bias": "BULLISH", "score": 50, "net_vote": 25,
                       "n_patterns": 2, "top": []}
    check("reads injected cache", ac.get_market_bias()["bias"] == "BULLISH")
    # evaluate_flow_confluence falls back to cache when no bias passed
    v = ac.evaluate_flow_confluence("BULLISH")
    check("evaluate uses cache", v["aligned"] is True)
    ac._reset_for_test()


def test_telegram_banner_render():
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
    check("no tag -> no analogue banner", "ANALOGUE CONFLUENCE" not in format_flow_alert(dict(base)))
    tagged = dict(base)
    tagged["_analogue_tag"] = "🎯 ANALOGUE CONFLUENCE (BULLISH base-rate)"
    tagged["_analogue_note"] = "index base-rate aligns (rsi_thrust_zweig, score 60)"
    msg = format_flow_alert(tagged)
    check("analogue banner rendered", "ANALOGUE CONFLUENCE" in msg, msg[:80])
    check("analogue note rendered", "base-rate aligns" in msg)


def main() -> int:
    print("=== analogue_confluence (task #55 follow-up) tests ===")
    for fn in (test_bias_bullish, test_bias_bearish, test_bias_neutral_mixed,
               test_thin_sample_damped, test_min_n_filter, test_empty,
               test_confluence_aligned, test_confluence_counter,
               test_confluence_neutral_no_tag, test_confluence_nondirectional,
               test_cache, test_telegram_banner_render):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
