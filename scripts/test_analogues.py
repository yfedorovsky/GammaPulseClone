"""Unit tests for server/analogues.py (task #55 base-rate engine).

Run:  python scripts/test_analogues.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.analogues as an  # noqa: E402

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


def _bars(closes, hl_pad=0.0, opens=None):
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c
        out.append({"date": f"2020-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
                    "open": o, "high": c + hl_pad, "low": c - hl_pad,
                    "close": c, "volume": 1000})
    return out


# ── indicators ────────────────────────────────────────────────────────────
def test_sma():
    s = an.sma([1, 2, 3, 4, 5], 3)
    check("sma warmup None", s[0] is None and s[1] is None)
    check("sma[2]=2", s[2] == 2.0)
    check("sma[4]=4", s[4] == 4.0)


def test_rsi_bounds():
    up = [100 * (1.01 ** i) for i in range(60)]
    dn = [100 * (0.99 ** i) for i in range(60)]
    r_up = an.rsi(up, 14)[-1]
    r_dn = an.rsi(dn, 14)[-1]
    check("rsi uptrend high", r_up is not None and r_up > 70, str(r_up))
    check("rsi downtrend low", r_dn is not None and r_dn < 30, str(r_dn))
    check("rsi in [0,100]", 0 <= r_up <= 100 and 0 <= r_dn <= 100)


def test_ema():
    e = an.ema([10, 10, 10, 10, 10], 3)
    check("ema of constant = constant", e[-1] == 10.0)


# ── detectors (hand-built frames for precision) ───────────────────────────
def test_golden_death_cross():
    F = {"sma50": [None, 9.0, 11.0], "sma200": [None, 10.0, 10.0], "n": 3}
    check("golden cross fires", an._golden_cross(F, 2) is True)
    check("golden cross not at i-1", an._golden_cross(F, 1) is False)
    F2 = {"sma50": [None, 11.0, 9.0], "sma200": [None, 10.0, 10.0], "n": 3}
    check("death cross fires", an._death_cross(F2, 2) is True)


def test_macd_cross():
    F = {"macd": [0.0, -0.1, 0.2], "macd_signal": [0.0, 0.0, 0.0], "n": 3}
    check("macd bull cross", an._macd_bull_cross(F, 2) is True)
    F2 = {"macd": [0.0, 0.1, -0.2], "macd_signal": [0.0, 0.0, 0.0], "n": 3}
    check("macd bear cross", an._macd_bear_cross(F2, 2) is True)


def test_rsi_thrust():
    # rsi dips to 25 then jumps to 65 within window → thrust fires.
    # Need i >= window(15) bars of history before the recovery bar.
    rsis = [50.0] * 20 + [25.0] + [50.0] * 5 + [65.0]
    F = {"rsi": rsis, "n": len(rsis)}
    check("zweig thrust fires", an._rsi_thrust_zweig(F, len(rsis) - 1) is True)
    # no prior dip within window → no thrust (long enough to clear the guard)
    F2 = {"rsi": [55.0] * 20 + [65.0], "n": 21}
    check("no dip -> no thrust", an._rsi_thrust_zweig(F2, 20) is False)


def test_gap_and_streaks():
    F = an.compute_features(_bars([100, 100, 100], opens=[100, 100, 103]))
    check("gap up fires", an._gap_up(F, 2) is True)
    up = an.compute_features(_bars([100, 101, 102, 103, 104, 105]))
    check("consec up 5d", an._consec_up(up, 5) is True)
    dn = an.compute_features(_bars([105, 104, 103, 102, 101, 100]))
    check("consec down 5d", an._consec_down(dn, 5) is True)


# ── forward returns ───────────────────────────────────────────────────────
def test_forward_returns():
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111]
    fwd = an.forward_returns(closes, [0], horizons=(5,))
    # closes[5]/closes[0]-1 = 105/100-1 = 5%
    check("fwd 5d mean = 5.0%", fwd[5]["mean_pct"] == 5.0, str(fwd[5]))
    check("fwd 5d hit_rate 100", fwd[5]["hit_rate"] == 100.0)
    check("fwd 5d n=1", fwd[5]["n"] == 1)
    # index too close to end → excluded
    fwd2 = an.forward_returns(closes, [10], horizons=(5,))
    check("insufficient forward -> n=0", fwd2[5]["n"] == 0)
    # mixed up/down hit rate
    closes2 = [100, 110, 100, 90]  # from idx0 +? use h=1
    fwd3 = an.forward_returns(closes2, [0, 1, 2], horizons=(1,))
    # idx0: 110/100=+10 (up); idx1: 100/110 (down); idx2: 90/100 (down) -> 1/3
    check("mixed hit_rate ~33", fwd3[1]["hit_rate"] == 33.3, str(fwd3[1]))


# ── scan integration ──────────────────────────────────────────────────────
def test_scan_uptrend():
    closes = [100 * (1.01 ** i) for i in range(300)]
    res = an.scan(_bars(closes, hl_pad=0.2))
    check("scan returns active", res["active_count"] >= 1, str(res["active_count"]))
    names = {a["pattern"] for a in res["active"]}
    check("uptrend fires bullish patterns",
          names & {"rsi_overbought", "consec_up_5d", "near_52w_high", "rally_10d_5pct"},
          str(names))
    # structure of a result
    a0 = res["active"][0]
    check("result has occurrences", "occurrences" in a0 and a0["occurrences"] >= 0)
    check("result has forward horizons", set(a0["forward"].keys()) == set(an.FWD_HORIZONS))
    check("as_of set", res["as_of"] is not None)


def test_scan_downtrend():
    closes = [100 * (0.99 ** i) for i in range(300)]
    res = an.scan(_bars(closes, hl_pad=0.2))
    names = {a["pattern"] for a in res["active"]}
    check("downtrend fires bearish patterns",
          names & {"rsi_oversold", "consec_down_5d", "near_52w_low", "below_200d"},
          str(names))


def test_empty_and_short():
    check("empty bars -> no active", an.scan([])["active_count"] == 0)
    short = an.scan(_bars([100, 101, 102]))
    check("short series safe", isinstance(short["active"], list))


def main() -> int:
    print("=== analogues base-rate engine (task #55) tests ===")
    for fn in (test_sma, test_rsi_bounds, test_ema, test_golden_death_cross,
               test_macd_cross, test_rsi_thrust, test_gap_and_streaks,
               test_forward_returns, test_scan_uptrend, test_scan_downtrend,
               test_empty_and_short):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
