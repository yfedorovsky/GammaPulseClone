"""Tests for the bottleneck context hook (framework #4 wiring).

Covers context_for() lookup + the pure flow-summary/watch logic in
bottleneck_phase_watch (no DB needed). Run: python scripts/test_bottleneck_context.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bottleneck_scorecard as SC  # noqa: E402
import bottleneck_phase_watch as PW  # noqa: E402


def check(cond, desc):
    print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")
    return 0 if cond else 1


def main() -> int:
    fails = 0

    # context_for: in-universe vs not
    axti = SC.context_for("axti")  # case-insensitive
    fails += check(axti is not None and axti["layer"] == "PHOTONICS" and axti["phase"] == 2,
                   "context_for(AXTI) -> PHOTONICS Phase 2")
    fails += check(SC.context_for("SPY") is None, "context_for(SPY) -> None (not a bottleneck name)")
    fails += check(SC.context_for("") is None, "context_for('') -> None")
    fails += check(SC.context_for("AVGO")["phase"] == 3, "context_for(AVGO) -> Phase 3 (consensus)")

    # summarize_flow aggregation
    rows = [
        {"ticker": "AXTI", "sentiment": "BULLISH", "conviction": "HIGH", "notional": 1_000_000,
         "is_sweep": 1, "is_insider": 0, "is_whale": 0},
        {"ticker": "AXTI", "sentiment": "BULLISH", "conviction": "SWEEP", "notional": 500_000,
         "is_sweep": 0, "is_insider": 1, "is_whale": 0},
        {"ticker": "AVGO", "sentiment": "BEARISH", "conviction": "LOW", "notional": 2_000_000,
         "is_sweep": 0, "is_insider": 0, "is_whale": 1},
        {"ticker": "SPY", "sentiment": "NEUTRAL", "conviction": "LOW", "notional": 9_000_000,
         "is_sweep": 0, "is_insider": 0, "is_whale": 0},  # not in universe
    ]
    agg = PW.summarize_flow(rows)
    fails += check(agg["AXTI"]["n"] == 2 and agg["AXTI"]["notional"] == 1_500_000,
                   "summarize_flow: AXTI n=2, notional summed")
    fails += check(agg["AXTI"]["dominant_sentiment"] == "BULLISH" and agg["AXTI"]["sweep"]
                   and agg["AXTI"]["insider"], "summarize_flow: AXTI dominant=BULLISH, sweep+insider flagged")

    # build_watch: Phase 1-2 flagged + sorted watch-first; non-universe dropped
    watch = PW.build_watch(agg)
    tickers = [r["ticker"] for r in watch]
    fails += check("SPY" not in tickers, "build_watch: drops non-universe SPY")
    fails += check(watch[0]["ticker"] == "AXTI" and watch[0]["is_watch"] is True,
                   "build_watch: AXTI (Phase 2) sorts first as asymmetric watch")
    fails += check(any(r["ticker"] == "AVGO" and r["is_watch"] is False for r in watch),
                   "build_watch: AVGO (Phase 3) present, is_watch False")
    fails += check(watch[0]["validation_signal"] == axti["watch"],
                   "build_watch: carries the validation signal to confirm")

    # watch_only filter
    watch_only = PW.build_watch(agg, watch_only=True)
    fails += check(all(r["is_watch"] for r in watch_only) and "AVGO" not in [r["ticker"] for r in watch_only],
                   "build_watch(watch_only): only Phase 1-2 names")

    print("ALL TESTS PASSED" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
