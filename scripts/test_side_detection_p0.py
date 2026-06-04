"""Regression test for the P0 side-detection bug (task #43).

Replays known whale trades that were mis-classified by the old code
and asserts the new code returns the correct side. Add new cases here
as they're documented in the FL0WG0D / Bullflow / Twitter audit trail.

Each case captures:
  - The snapshot bid/ask/last we saw at the time
  - The vol/oi values that drove V/OI
  - delta/notional for the snapshot stale-last branch
  - The expected side (ASK = buyer-initiated, BID = seller, MID = unknown)
  - Why the old code got it wrong (so we don't regress)

Usage:
    python scripts/test_side_detection_p0.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.flow_alerts import _detect_side  # noqa: E402


CASES = [
    # (label, bid, ask, last, vol, oi, delta, notional, expected_side, why_old_wrong)
    (
        "RKLB 121C 6/18 (FL0WG0D screenshot 6/4)",
        10.30, 10.55, 10.32, 1280, 61, 0.50, 1321000, "ASK",
        "V/OI 21x AND last in bottom 25% of spread fell into 'pass' "
        "deferral, then coin-flip last<mid -> BID. Real trade was a "
        "750-contract ASK sweep at $11.00 avg at 15:50 ET. Snapshot "
        "scanner ran 14 min later; last price had drifted closer to "
        "the bid by then.",
    ),
    (
        "HPE 30.5C 5/15 (Bug #12 part 1, 2026-05-13)",
        0.85, 1.05, 0.95, 3029, 18, 0.30, 287755, "ASK",
        "V/OI 168x with last at exact mid -> old code returned MID. "
        "Theta tape confirmed 1,497 contracts ISO-swept at $0.80 across "
        "3 exchanges in 1ms. Pure buyer-initiated.",
    ),
    (
        "META 620C 0DTE 5/27 (Bug #12 part 2)",
        1.61, 1.81, 1.69, 39435, 3096, 0.45, 6664515, "ASK",
        "V/OI 12.7x, last $1.69 in [$1.61, $1.81] just below mid $1.71. "
        "Old code returned BID -> tagged BEARISH on the META paid-subs "
        "insider catch (615C went $0.14 -> $21.15 = 151x within 5 min).",
    ),
    (
        "ABNB 137C 6/12 (Extreme V/OI shock 5/20)",
        2.50, 2.75, 2.60, 2211, 4, 0.20, 574860, "ASK",
        "V/OI 552x (!!) with last slightly below mid $2.625. Bullflow + "
        "Flowseeker both confirmed 95% ASK fills. Old code coin-flipped "
        "to BID via line 487 fallback.",
    ),
    (
        "GLD 380C 6/18 (Bug #2 prototype, 5/12)",
        54.20, 54.90, 54.05, 1500, 200, 0.85, 8107500, "ASK",
        "Last $54.05 strictly below bid $54.20 = stale-snapshot. Deep "
        "ITM + $8M+ notional. Pre-stale-last fix returned BEARISH; "
        "post-fix should return ASK via line 691 institutional bias.",
    ),
]


def fmt(side: str) -> str:
    return {"ASK": "🟢 ASK", "BID": "🔴 BID", "MID": "🟡 MID"}.get(side, side)


def main() -> int:
    print("=" * 75)
    print("P0 SIDE-DETECTION REGRESSION TEST")
    print("=" * 75)
    failures = 0
    for case in CASES:
        label, bid, ask, last, vol, oi, delta, notional, expected, why = case
        got = _detect_side(
            bid, ask, last,
            delta=delta, vol=vol, oi=oi, notional=notional,
        )
        ok = (got == expected)
        marker = "PASS" if ok else "FAIL"
        print()
        print(f"[{marker}] {label}")
        print(f"        bid=${bid} ask=${ask} last=${last} V/OI={vol/max(oi,1):.1f}x")
        print(f"        expected={fmt(expected)}  got={fmt(got)}")
        if not ok:
            failures += 1
            print(f"        Why the bug existed: {why[:120]}...")
    print()
    print("=" * 75)
    print(f"RESULT: {len(CASES) - failures}/{len(CASES)} passed, {failures} failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
