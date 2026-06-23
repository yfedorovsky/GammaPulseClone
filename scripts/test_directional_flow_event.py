"""Tests for the Directional Flow Event normalizer (ChatGPT rec #9).
Run: python scripts/test_directional_flow_event.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.directional_flow_event import DirectionalFlowEvent as DFE  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_flow_normalization():
    e = DFE.from_flow({
        "ticker": "mu", "sentiment": "BULLISH", "option_type": "call",
        "notional": 5_000_000, "vol_oi": 18.0, "side_source": "tick",
        "conviction": "HIGH", "strike": 130, "expiration": "2026-07-18",
        "earnings_in_window": 1,
    }, source="INFORMED_FLOW")
    check("ticker upper", e.ticker == "MU")
    check("direction BULL", e.direction == "BULL")
    check("dollar_size", e.dollar_size == 5_000_000)
    check("breadth 1 for single", e.cluster_breadth == 1)
    check("tick -> aggressor HIGH", e.aggressor_quality == "HIGH")
    check("catalyst flag passed through", e.catalyst_in_window == 1)


def test_put_direction_and_snapshot_quality():
    e = DFE.from_flow({"ticker": "SPY", "sentiment": "BULLISH", "option_type": "put",
                       "notional": 1e6, "side_source": "snapshot", "conviction": "LOW"})
    check("bullish PUT -> BEAR", e.direction == "BEAR")
    check("snapshot -> LOW quality", e.aggressor_quality == "LOW")


def test_whale_override_quality():
    e = DFE.from_flow({"ticker": "X", "sentiment": "BULLISH", "option_type": "call",
                       "notional": 3e6, "_whale_override": "A", "conviction": "HIGH"})
    check("override -> MED quality", e.aggressor_quality == "MED")


def test_cluster_normalization():
    c = DFE.from_cluster({
        "ticker": "AVGO", "direction": "BULL", "option_type": "call",
        "total_notional": 12_000_000, "n_strikes": 4, "duration_min": 18.0,
        "avg_vol_oi": 14.0, "expiration": "2026-07-18",
    })
    check("cluster source default", c.source == "INFORMED_CLUSTER")
    check("breadth = n_strikes", c.cluster_breadth == 4)
    check("time concentration carried", c.time_concentration_min == 18.0)
    check("cluster aggressor MED", c.aggressor_quality == "MED")


def test_significance_ordering():
    big = DFE.from_flow({"ticker": "A", "sentiment": "BULLISH", "option_type": "call",
                         "notional": 1e7, "side_source": "tick", "conviction": "HIGH"})
    small = DFE.from_flow({"ticker": "B", "sentiment": "BULLISH", "option_type": "call",
                           "notional": 1e5, "side_source": "snapshot", "conviction": "LOW"})
    check("bigger/cleaner ranks higher", big.significance() > small.significance(),
          f"{big.significance()} vs {small.significance()}")
    # catalyst discount
    cat = DFE.from_flow({"ticker": "C", "sentiment": "BULLISH", "option_type": "call",
                         "notional": 1e7, "side_source": "tick", "conviction": "HIGH",
                         "earnings_in_window": 1})
    check("catalyst discounts significance", cat.significance() < big.significance(),
          f"{cat.significance()} vs {big.significance()}")


def test_summary_and_dict():
    e = DFE.from_cluster({"ticker": "MU", "direction": "BULL", "total_notional": 6e6,
                          "n_strikes": 3, "duration_min": 10, "earnings_in_window": 1})
    s = e.summary()
    check("summary has ticker + strikes + ER", "MU" in s and "3 strikes" in s and "ER-in-window" in s, s)
    d = e.to_dict()
    check("to_dict has significance", "significance" in d and isinstance(d["significance"], (int, float)))


if __name__ == "__main__":
    print("test_directional_flow_event")
    test_flow_normalization()
    test_put_direction_and_snapshot_quality()
    test_whale_override_quality()
    test_cluster_normalization()
    test_significance_ordering()
    test_summary_and_dict()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
