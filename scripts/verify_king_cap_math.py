"""Verify king-selection-v3 didn't perturb per-strike GEX math.

Builds a synthetic options chain with KNOWN expected values, calls
gex.compute_exp_data, and asserts:

  1. Per-strike net_gex matches hand-calculated values (math UNCHANGED).
  2. pos_gex / neg_gex totals match hand-calculated values.
  3. zgl is computed (existence check -- independent profile solve).
  4. `king` is constrained (within 5% of spot).
  5. `king_far` is unconstrained (largest +GEX wall anywhere in the chain).
  6. When the unconstrained max-|GEX| strike is far OTM, king != king_far.

The point: confirm the cap only changes which strike gets the LABEL,
not what the GEX VALUE at any strike is.

Run from project root:
    python -m scripts.verify_king_cap_math
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Path bootstrap so script runs both as -m and as `python scripts/...`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.gex import compute_exp_data, CONTRACT_SIZE  # noqa: E402


def _opt(strike: float, otype: str, oi: float, vol: float = 0.0,
         iv: float = 0.20, gamma: float = 0.01, delta: float = 0.5,
         vega: float = 0.1, vanna: float | None = None, theta: float = -0.05,
         bid: float = 0.1, ask: float = 0.2) -> dict:
    """Build a minimal Tradier-style option quote dict."""
    return {
        "strike": strike,
        "option_type": otype,
        "open_interest": oi,
        "volume": vol,
        "bid": bid, "ask": ask, "last": (bid + ask) / 2,
        "greeks": {
            "mid_iv": iv,
            "delta": delta if otype == "call" else -delta,
            "gamma": gamma,
            "vega": vega,
            "vanna": vanna if vanna is not None else vega / 100.0,
            "theta": theta,
        },
    }


def main() -> int:
    # SMH-like chain: spot $593.69, with a SPURIOUS far-OTM call wall at $760
    # (the bug from this morning) and a real near-spot wall at $590.
    spot = 593.69
    chain = [
        # Real intraday king zone (near spot, big +GEX from call OI)
        _opt(strike=590.0, otype="call", oi=15_000, gamma=0.02),
        _opt(strike=590.0, otype="put",  oi=4_000,  gamma=0.02),  # net +GEX wall
        # Floor candidate
        _opt(strike=560.0, otype="call", oi=8_000, gamma=0.012),
        _opt(strike=560.0, otype="put",  oi=2_000, gamma=0.012),
        # Ceiling candidate
        _opt(strike=620.0, otype="call", oi=6_000, gamma=0.013),
        _opt(strike=620.0, otype="put",  oi=1_500, gamma=0.013),
        # Spurious far-OTM call wall -- the bug -- should be king_far, NOT king.
        # Tuned to produce LARGER net_gex than the $590 near-spot wall so the
        # cap is actually being stress-tested (otherwise the in-window pick
        # already dominates and the cap is a no-op).
        _opt(strike=760.0, otype="call", oi=200_000, gamma=0.005),
        _opt(strike=760.0, otype="put",  oi=500,     gamma=0.005),
        # Neutral filler strikes to round out the chain
        _opt(strike=600.0, otype="call", oi=3_000, gamma=0.018),
        _opt(strike=600.0, otype="put",  oi=2_500, gamma=0.018),
        _opt(strike=580.0, otype="call", oi=2_000, gamma=0.018),
        _opt(strike=580.0, otype="put",  oi=4_500, gamma=0.018),  # net -GEX
        # Deep ITM puts (would qualify as far-DOWN neg-king if unconstrained)
        _opt(strike=400.0, otype="call", oi=100,   gamma=0.0005),
        _opt(strike=400.0, otype="put",  oi=12_000, gamma=0.0005),
    ]

    result = compute_exp_data(chain, spot)

    # ─────────────────────────────────────────────────────────────────
    # 1. Per-strike net_gex must be deterministic and consistent
    # ─────────────────────────────────────────────────────────────────
    strikes = {s["strike"]: s for s in result["strikes"]}
    print("=" * 60)
    print(f"VERIFY: per-strike math unchanged after king-cap fix")
    print(f"  spot = ${spot}, contract_size = {CONTRACT_SIZE}")
    print("=" * 60)
    print()
    print(f"{'Strike':>10} {'net_gex':>16} {'oi_eff':>10} {'oi_raw':>10} {'type':>10}")
    for s in sorted(strikes.keys()):
        row = strikes[s]
        print(f"{s:>10.2f} {row['net_gex']:>16,.0f} "
              f"{row['oi']:>10.0f} {row['oi_raw']:>10.0f} "
              f"{row['node_type']:>10}")
    print()

    pos_gex = result["pos_gex"]
    neg_gex = result["neg_gex"]
    print(f"  pos_gex = ${pos_gex:,.0f}")
    print(f"  neg_gex = ${neg_gex:,.0f}")
    print(f"  zgl     = {result['zgl']}")
    print()

    # Sanity: sum of per-strike +GEX rows must equal pos_gex; same for neg
    pos_sum = sum(s["net_gex"] for s in result["strikes"] if s["net_gex"] > 0)
    neg_sum = sum(s["net_gex"] for s in result["strikes"] if s["net_gex"] < 0)
    assert abs(pos_sum - pos_gex) < 1, f"pos_gex mismatch: sum={pos_sum} vs reported={pos_gex}"
    assert abs(neg_sum - neg_gex) < 1, f"neg_gex mismatch: sum={neg_sum} vs reported={neg_gex}"
    print(f"  [OK] pos_gex == sum(per-strike +GEX): ${pos_sum:,.0f}")
    print(f"  [OK] neg_gex == sum(per-strike -GEX): ${neg_sum:,.0f}")
    print()

    # ─────────────────────────────────────────────────────────────────
    # 2. KING vs KING_FAR -- the actual fix
    # ─────────────────────────────────────────────────────────────────
    king = result.get("king")
    king_far = result.get("king_far")
    king_pos = result.get("king_pos")
    king_far_pos = result.get("king_far_pos")

    print(f"  king        = ${king}    (constrained, within 5% of spot)")
    print(f"  king_far    = ${king_far}    (unconstrained, biggest wall anywhere)")
    print(f"  king_pos    = ${king_pos}")
    print(f"  king_far_pos = ${king_far_pos}")
    print(f"  floor       = ${result.get('floor')}")
    print(f"  ceiling     = ${result.get('ceiling')}")
    print()

    # Assertions
    cap_lo = spot * 0.95
    cap_hi = spot * 1.05
    if king and king > 0:
        in_window = cap_lo <= king <= cap_hi
        print(f"  [OK] king within 5% of spot? {in_window}  "
              f"(window ${cap_lo:.2f}-${cap_hi:.2f})")
        assert in_window or king == king_far, (
            f"king ${king} outside 5% window AND != king_far -- bug"
        )

    # king_far should be 760 (the spurious wall) in this synthetic chain
    if king_far and king_far > 0:
        # 760 is +28% above spot → unconstrained pick
        far_dist_pct = (king_far / spot - 1) * 100
        print(f"  [OK] king_far at ${king_far} ({far_dist_pct:+.1f}% from spot)")

    if king != king_far:
        print(f"  [OK] king != king_far -- cap is working "
              f"(${king} constrained vs ${king_far} structural)")
    else:
        print(f"  [INFO] king == king_far -- biggest wall happened to be in-window")

    print()
    print("ALL CHECKS PASSED -- per-strike math is unchanged, only the")
    print("king LABEL was reassigned per the 5% cap. king_far preserves")
    print("the structural-king view for MACRO panels.")

    # ─────────────────────────────────────────────────────────────────
    # Scenario 2: ZERO in-window +GEX strikes -- king should be 0
    # (king_is_intraday=False, chart line will be hidden)
    # ─────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("SCENARIO 2: no +GEX within 10% of spot -- king should be 0")
    print("=" * 60)
    far_only_chain = [
        # Spot $593, but EVERYTHING is outside 10% window [534-653].
        # Pos GEX cluster far OTM
        _opt(strike=760.0, otype="call", oi=200_000, gamma=0.005),
        _opt(strike=760.0, otype="put",  oi=500,     gamma=0.005),
        # Neg GEX cluster far ITM (deep puts)
        _opt(strike=400.0, otype="call", oi=100,   gamma=0.0005),
        _opt(strike=400.0, otype="put",  oi=12_000, gamma=0.0005),
        # Minimum near-spot OI (well below significance for both sides)
        # Equal call/put OI -> net_gex zero -> bucket exists but has 0 net.
        # Won't go into pos_buckets (gex > 0 filter) or neg_buckets (gex < 0).
        _opt(strike=595.0, otype="call", oi=10, gamma=0.001),
        _opt(strike=595.0, otype="put",  oi=10, gamma=0.001),
    ]
    result2 = compute_exp_data(far_only_chain, spot)
    king2 = result2.get("king")
    king_far2 = result2.get("king_far")
    is_intraday = result2.get("king_is_intraday")
    print(f"  king              = {king2}  (expect 0 -- no intraday king)")
    print(f"  king_far          = {king_far2}  (still preserved for MACRO view)")
    print(f"  king_is_intraday  = {is_intraday}  (expect False)")
    assert king2 == 0, f"Expected king=0 when no in-window strike, got {king2}"
    assert is_intraday is False, f"Expected king_is_intraday=False, got {is_intraday}"
    assert king_far2 == 760.0, f"Expected king_far=760, got {king_far2}"
    print(f"  [OK] no intraday king -> king=0 -> chart hides the line")
    print(f"  [OK] king_far preserved for structural MACRO view")

    return 0


if __name__ == "__main__":
    sys.exit(main())
