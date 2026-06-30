"""GEX boundary-behavior audit — SPX variant (2026-06-30).

Ports scripts/gex_boundary_behavior_audit.py to SPX WITHOUT changing the frozen
methodology: identical approach tolerance, breach/bounce thresholds, distance-
matched random control, day-cluster bootstrap, and PASS/FAIL/MIXED decision rule.
Only three things change for SPX:
  1. underlying = SPX (snapshots.db ticker='SPX', native SPX GEX levels)
  2. intraday bars = the ^GSPC index 5-min series (SPX = S&P 500 index, same points)
  3. strike grid = $5 (SPX/SPXW) instead of $1, so the random control rounds to a
     realistic SPX strike and the exclusion radius is half a strike ($2.50)

WHY: the original audit (SPY/QQQ/IWM) FAILED — GEX levels were no better boundaries
than random (bounce 44.7% vs 44.1%, d~0.03). The anticipatory SPX scanner leans on
SPX levels as defined-risk LIMIT locations; this checks whether SPX's own (cleanest,
highest-OI) gamma structure is any better a boundary than SPY's was. Pre-build gate
per the spx-anticipatory-scanner-design workflow STEP 0.

Run:  python scripts/gex_boundary_behavior_audit_spx.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gex_boundary_behavior_audit as base  # the frozen methodology  # noqa: E402

# ── SPX overrides (monkeypatched onto the frozen module so run_ticker/analyze
#    use the SAME code path, only the data + grid differ) ──────────────────────

_SPX_YF_SYMBOL = "^GSPC"  # SPX = S&P 500 index; ^GSPC is the index 5-min series
_SPX_STRIKE_STEP = 5.0    # SPX/SPXW strikes are $5
_SPX_EXCLUDE_RADIUS = 2.5  # half a strike

_orig_get_day_bars = base.get_day_bars


def _spx_get_day_bars(ticker, day):
    """Fetch SPX intraday bars from the ^GSPC index series (cached under ^GSPC)."""
    return _orig_get_day_bars(_SPX_YF_SYMBOL, day)


def _spx_random_control(ticker, snap, exclude_levels, rng, real_level=None):
    """Distance-matched random control rounded to the nearest $5 SPX strike,
    excluding any strike within half a strike of an actual GEX level. Same logic
    as base.random_control_levels, only the grid is $5 not $1."""
    if real_level is None:
        return None
    spot = float(snap["spot"])
    if spot <= 0:
        return None
    abs_dist = abs(spot - float(real_level))
    if abs_dist <= 0:
        return None
    signs = [+1.0, -1.0]
    rng.shuffle(signs)
    for sign in signs:
        candidate_raw = spot + sign * abs_dist
        candidate = float(round(candidate_raw / _SPX_STRIKE_STEP) * _SPX_STRIKE_STEP)
        if candidate <= 0:
            continue
        if any(abs(candidate - x) < _SPX_EXCLUDE_RADIUS for x in exclude_levels):
            continue
        side = "above" if spot >= candidate else "below"
        return candidate, side
    return None


def main() -> int:
    # Patch the frozen module in place, then drive its own run/analyze/render.
    base.get_day_bars = _spx_get_day_bars
    base.random_control_levels = _spx_random_control
    base.TICKERS = ["SPX"]
    base.RESULTS_PATH = ROOT / "docs" / "research" / "BOUNDARY_BEHAVIOR_AUDIT_SPX_RESULTS.md"

    print("[boundary-spx] SPX GEX boundary-behavior audit starting", flush=True)
    print(f"[boundary-spx] bars={_SPX_YF_SYMBOL}  strike_step=${_SPX_STRIKE_STEP}  "
          f"approach={base.APPROACH_TOL}  breach={base.BREACH_THRESHOLD}", flush=True)

    rows = base.run_ticker("SPX")
    print(f"[boundary-spx] SPX: {len(rows)} approach events recorded", flush=True)
    if not rows:
        print("[boundary-spx] no data — aborting (yfinance 5m only goes ~60d back)", flush=True)
        return 1

    result = base.analyze(rows)
    print(f"[boundary-spx] VERDICT: {result['verdict']}  "
          f"(n={result['n_approaches']} approaches, {result['n_days']} days)", flush=True)

    out = base.render_results(result).replace(
        "# GEX Boundary-Behavior Audit — Results",
        "# GEX Boundary-Behavior Audit — SPX (2026-06-30)")
    base.RESULTS_PATH.write_text(out, encoding="utf-8")
    base.RESULTS_PATH.with_suffix(".json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"[boundary-spx] wrote {base.RESULTS_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
