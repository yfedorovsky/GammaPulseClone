"""Unified macro context — Phase 4 dashboard panel.

Bundles #1 (regime alignment), #2 (stress composite), and #3 (conditional
base rate forecasts) into a single coherent read for dashboard display.

Usage:
    from server.macro_context import get_macro_context
    ctx = await get_macro_context()
    # Render in dashboard / log / alert footer

This is NOT an autonomous trade gate — it's a context layer. The Phase 1+2
gates (breadth, IV-rank, sector-cap) remain the load-bearing rails.
"""
from __future__ import annotations

import asyncio
from typing import Any


async def get_macro_context() -> dict[str, Any]:
    """Compose the three Phase 4 macro signals into one dashboard payload."""
    from .regime_alignment import get_alignment
    from .stress_composite import get_stress_composite

    align_task = asyncio.create_task(get_alignment())
    stress_task = asyncio.create_task(get_stress_composite())

    align = await align_task
    stress = await stress_task

    # Conditional base rate forecast — synchronous (just a JSON cache lookup
    # plus a tiny SPY refresh for current regime)
    forecast: dict[str, Any] = {}
    try:
        from backtest.conditional_base_rates import lookup_today
        forecast = lookup_today()
    except Exception as e:
        forecast = {"error": str(e)}

    # Phase 5: SPY VEX state (vanna exposure direction below/above spot)
    vex_state: dict[str, Any] | None = None
    try:
        from .vex_engine import get_spy_vex_state
        vex_state = await get_spy_vex_state()
    except Exception as e:
        vex_state = {"error": str(e)}

    # Combined sizing modifier — most-restrictive rule wins.
    # Both regime alignment and stress have a size_modifier; take the lower.
    align_mod = align.get("size_modifier", 1.0)
    stress_mod = stress.get("size_modifier", 1.0)
    combined_mod = min(align_mod, stress_mod)

    # Phase 6A.2: apply hysteresis to the dashboard label so the user
    # doesn't see "danger sign" flipping between cycles when underlying
    # signals hover near thresholds. 3-cycle persistence on the dominant
    # regime label.
    raw_dominant = align["dominant"]
    try:
        from .hysteresis import persistence
        h = persistence("macro_context_dominant", raw_dominant, n_cycles=3)
        filtered_dominant = h["displayed_state"]
        is_changing = h["is_changing"]
        cycles_in_new = h["cycles_in_new_state"]
    except Exception:
        filtered_dominant = raw_dominant
        is_changing = False
        cycles_in_new = 0

    # Headline label for dashboard (uses FILTERED dominant)
    transition_marker = ""
    if is_changing:
        transition_marker = f" [transitioning {cycles_in_new}/3]"
    if stress.get("blocks_new_longs"):
        headline = f"BLOOD ({stress['score']}/100) — no new BULL longs"
    elif stress["band"] == "STRESSED":
        headline = (f"STRESSED ({stress['score']}/100, {filtered_dominant} "
                    f"{align['alignment_pct']}%){transition_marker}")
    elif filtered_dominant == "BULL" and stress["band"] in ("LOW", "ELEVATED"):
        headline = (f"BULL aligned ({align['alignment_pct']}%, "
                    f"stress {stress['score']}/100){transition_marker}")
    elif filtered_dominant == "BEAR":
        headline = (f"BEAR aligned ({align['alignment_pct']}%, "
                    f"stress {stress['score']}/100){transition_marker}")
    else:
        headline = (f"MIXED ({align['bull']}B/{align['bear']}-, "
                    f"stress {stress['score']}/100){transition_marker}")

    return {
        "headline": headline,
        "combined_size_modifier": round(combined_mod, 3),
        "regime_alignment": align,
        "stress_composite": stress,
        "spy_forecast": forecast,
        "spy_vex": vex_state,
        "dominant_filtered": filtered_dominant,
        "dominant_raw": raw_dominant,
        "in_transition": is_changing,
    }


if __name__ == "__main__":
    ctx = asyncio.run(get_macro_context())
    print(f"\n=== MACRO CONTEXT ===")
    print(f"\n  HEADLINE: {ctx['headline']}")
    print(f"  Combined size modifier: {ctx['combined_size_modifier']}")

    a = ctx["regime_alignment"]
    print(f"\n  Regime alignment: {a['bull']}B / {a['neutral']}N / {a['bear']}- "
          f"  dominant={a['dominant']}  alignment={a['alignment_pct']:.0f}%")
    for d in a["details"]:
        marker = {"BULL": "++", "BEAR": "--", "NEUTRAL": " ."}[d["vote"]]
        print(f"    {marker}  {d['name']:<20}  {d['reason']}")

    s = ctx["stress_composite"]
    print(f"\n  Stress composite: {s['score']:.1f} / 100  ({s['band']})  "
          f"  size_mod={s['size_modifier']:.2f}")
    for n, c in s["components"].items():
        print(f"    {n:<10}  {c['label']:<28}  scaled={c['scaled']:>5.1f}  "
              f"× {c['weight']:.2f}")

    v = ctx.get("spy_vex")
    if v is None:
        print(f"\n  SPY VEX: no data (live worker not populating per_strike cache)")
    elif "error" in v:
        print(f"\n  SPY VEX: {v.get('error')}")
    else:
        print(f"\n  SPY VEX: {v.get('summary', '?')}")
        print(f"    direction below spot: {v.get('direction_below_spot')}")
        print(f"    direction above spot: {v.get('direction_above_spot')}")
        print(f"    flip strike: {v.get('vex_flip_strike')}")

    f = ctx["spy_forecast"]
    if "forecast" in f and "error" not in f.get("forecast", {}):
        fc = f["forecast"]
        pooled = f["pooled_baseline"]
        print(f"\n  SPY forecast (cell {f['cell_key']}, N={fc['n_bars_in_cell']}):")
        for h in [3, 10, 20]:
            d = fc[f"{h}d"]
            shr = " (shrunk)" if d["is_shrunk"] else ""
            print(f"    {h:>2}d: hit={d['hit_shrunk_pct']:>5.1f}% (±{d['hit_se_pct']:.1f}%)  "
                  f"avg={d['avg_shrunk_pct']:>+5.2f}%  "
                  f"vs base: {d['vs_baseline_hit']:+.1f}pp hit, "
                  f"{d['vs_baseline_avg']:+.2f}pp avg{shr}")
