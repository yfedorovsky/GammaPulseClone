"""Sizing policy — single source of truth for combining size modifiers.

Phase 6A.2 (Apr 26 night) per cross-LLM convergence (ChatGPT + Perplexity
+ Gemini + Grok all agree):

    Stacking 4-6 multiplicative size modifiers is double-clipping:
    they measure the same underlying market phenomenon (regime/breadth/
    volatility) and treating them as orthogonal mathematically chokes
    sizing on correlated signals.

The right policy:

    final_pct = kelly_pct × grade_mult × min(regime_modifiers)

Where:
  - kelly_pct: Kelly fraction with shrinkage + clipping (existing)
  - grade_mult: GRADE-FAMILY (A+ 1.0, A 1.0, B+ 0.5, B 0.33). Multiplies
    because grade is signal-quality, orthogonal to market regime.
  - min(regime_modifiers): take MOST RESTRICTIVE of:
      * breadth_regime modifier
      * stress_composite modifier
      * regime_alignment modifier
      * IV-rank-driven modifier
      * (any future regime-family modifier)
    These all measure the same underlying phenomenon — use the strictest.

This module exposes:
    combine_sizing(
        kelly_pct, grade_mult,
        breadth_mod=1.0, stress_mod=1.0,
        alignment_mod=1.0, iv_mod=1.0,
        ...
    ) -> {final_pct, components, binding_constraint, ...}

The `binding_constraint` field tells you WHICH regime modifier was the
limiting factor — useful for dashboard display + post-trade analysis.
"""
from __future__ import annotations

from typing import Any


def combine_sizing(
    kelly_pct: float,
    grade_mult: float = 1.0,
    breadth_mod: float | None = None,
    stress_mod: float | None = None,
    alignment_mod: float | None = None,
    iv_rank_mod: float | None = None,
    custom_regime_mods: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Combine kelly sizing with grade and regime modifiers using min() semantics
    on regime-family inputs.

    Args:
        kelly_pct: base Kelly position size (% of account)
        grade_mult: signal-quality modifier (A+ 1.0, B+ 0.5, etc.)
        breadth_mod: breadth-gate-derived size multiplier (None = inactive)
        stress_mod: stress-composite size multiplier (None = inactive)
        alignment_mod: regime-alignment size multiplier (None = inactive)
        iv_rank_mod: IV-rank-derived size multiplier (None = inactive)
        custom_regime_mods: dict of {label: float} for additional regime mods

    Returns:
        {
            "final_pct": float,                   # final sizing %
            "kelly_pct": float,
            "grade_mult": float,
            "regime_min_mult": float,             # min of active regime mods
            "binding_constraint": str,            # which regime mod bound
            "active_regime_mods": dict,
            "policy": str,
        }
    """
    # Collect all active regime-family modifiers
    regime_mods: dict[str, float] = {}
    if breadth_mod is not None:
        regime_mods["breadth"] = breadth_mod
    if stress_mod is not None:
        regime_mods["stress"] = stress_mod
    if alignment_mod is not None:
        regime_mods["alignment"] = alignment_mod
    if iv_rank_mod is not None:
        regime_mods["iv_rank"] = iv_rank_mod
    if custom_regime_mods:
        for k, v in custom_regime_mods.items():
            regime_mods[k] = v

    # min() semantics across regime family — most restrictive wins
    if regime_mods:
        binding_label = min(regime_mods, key=lambda k: regime_mods[k])
        regime_min = regime_mods[binding_label]
    else:
        binding_label = "none"
        regime_min = 1.0

    # Grade × min(regime) is the only multiplication
    final_pct = kelly_pct * grade_mult * regime_min

    return {
        "final_pct": round(final_pct, 3),
        "kelly_pct": round(kelly_pct, 3),
        "grade_mult": round(grade_mult, 3),
        "regime_min_mult": round(regime_min, 3),
        "binding_constraint": binding_label,
        "active_regime_mods": {k: round(v, 3) for k, v in regime_mods.items()},
        "policy": ("grade × min(regime_mods); no stacked multiplication "
                   "of regime-family signals (cross-LLM convergence Apr 26)"),
    }


if __name__ == "__main__":
    # Smoke test scenarios
    scenarios = [
        ("All regimes neutral", dict(kelly_pct=2.0, grade_mult=1.0)),
        ("A+ in FULL_BULL", dict(kelly_pct=2.0, grade_mult=1.0,
                                   breadth_mod=1.0, stress_mod=1.0)),
        ("B+ in FULL_BULL", dict(kelly_pct=2.0, grade_mult=0.5,
                                   breadth_mod=1.0)),
        ("A+ in TRANSITIONAL (breadth tightens)",
            dict(kelly_pct=2.0, grade_mult=1.0,
                 breadth_mod=0.625, stress_mod=0.85)),
        ("A+ in BEAR (breadth blocks)",
            dict(kelly_pct=2.0, grade_mult=1.0,
                 breadth_mod=0.0, stress_mod=0.5)),
        ("Multiple modifiers all 0.85 — would compound to 0.61 if stacked, "
         "but min() = 0.85",
            dict(kelly_pct=2.0, grade_mult=1.0,
                 breadth_mod=0.85, stress_mod=0.85, alignment_mod=0.85,
                 iv_rank_mod=0.85)),
    ]
    print("Sizing policy smoke tests:\n")
    for label, args in scenarios:
        r = combine_sizing(**args)
        print(f"  {label}")
        print(f"    final {r['final_pct']:.2f}%  "
              f"(kelly {r['kelly_pct']:.2f} × grade {r['grade_mult']:.2f} "
              f"× regime_min {r['regime_min_mult']:.2f})")
        print(f"    binding: {r['binding_constraint']}  "
              f"active mods: {r['active_regime_mods']}")
        print()
