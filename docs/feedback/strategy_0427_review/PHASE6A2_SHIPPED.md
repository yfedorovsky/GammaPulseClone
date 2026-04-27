# Phase 6A.2 — Shipped Sun Apr 26 Late Night

Three small architectural cleanups that close convergent LLM critiques.

## What shipped

| # | Item | New module | Wired into |
|---|---|---|---|
| 1 | `combine_sizing()` policy with min() semantics | [server/sizing_policy.py](../../../server/sizing_policy.py) | [server/paper_trading.py](../../../server/paper_trading.py) |
| 2 | Hysteresis filter (N-cycle + dual-threshold) | [server/hysteresis.py](../../../server/hysteresis.py) | [server/macro_context.py](../../../server/macro_context.py) headline |
| 3 | Dynamic Bayesian shrinkage | [backtest/shrinkage.py](../../../backtest/shrinkage.py) `shrunk_win_rate_dynamic()` | [server/discipline.py](../../../server/discipline.py) `compute_kelly_size()` |

## Why these matter

### #1 — min() sizing semantics
**Problem:** Stacking 4-6 multiplicative size modifiers (grade × breadth × stress × alignment × IV-rank × ...) double-clips correlated signals. ChatGPT, Perplexity, Gemini, Grok all converged on this.

**Fix:** Final size = `kelly × grade × min(regime_modifiers)`. Grade is signal-quality (orthogonal). Regime modifiers are correlated → most-restrictive wins.

**Critical scenario** the smoke test verified:
- 4 regime mods all at 0.85: stacked = 0.52 (chokes 48%); min() = 0.85 (preserves 85%)

**Production state:** `paper_trading.py` now routes through `combine_sizing()`. Ready for future regime-mod wiring without re-architecting.

### #2 — Hysteresis dual-threshold
**Problem:** User reported "danger sign keeps switching with bullish reversal" — classic flicker when continuous variable hovers near binary threshold.

**Fix:** Two filter modes:
- **N-cycle persistence** for discrete states — flip only after N consecutive observations
- **Dual-threshold dead-band** for continuous variables — activate at +25, hold until -15 (etc.)

Both convergent across ChatGPT (3-cycle), Perplexity (3-cycle), Gemini (dual-threshold).

**Production state:** Wired into `macro_context.headline`. Dashboard now shows "BULL aligned" stable for 3 cycles before flipping. Transitioning state shows `[transitioning N/3]` marker for transparency.

### #3 — Dynamic James-Stein shrinkage
**Problem:** Hardcoded k=20 in Empirical Bayes formula was hand-set. Perplexity flagged it as uncalibrated; Gemini gave the formal James-Stein/Empirical Bayes formula:

```
k_dynamic = p(1-p) / sigma_prior_sq
```

**Behavior:**
- High ticker variance (extreme p) → smaller k → trust the ticker more
- Tightly clustered cohort → larger k → shrink heavily to mean
- Highly disparate cohort → smaller k → trust each ticker

**Empirical validation** on cohort-like distribution (std=0.099):
- p=50%: dynamic k = 25.4 (vs static 20) — heavier shrinkage
- p=80%: dynamic k = 16.2 (vs static 20) — lighter shrinkage on extreme

Static k=20 was reasonable but now adapts.

**Production state:**
- `compute_kelly_size()` uses dynamic when ≥5 cohort tickers have trades
- Falls back to static k=20 otherwise (edge case for fresh deployments)
- Output `debias_reason` shows which path: `k_dyn=16.2` or `k=20 static`

## Total session output (Apr 26 evening + late night)

Tonight's two phases (6A.0/6A.1 + 6A.2) shipped 9 items total:

**6A.0 — Validation:**
1. ZBT/Whaley validation against NYMO backfill (6/7 events)
2. Per-name slippage measurement (18/19 cohort)
3. Nonlinear slippage model
4. Edge survival kill-threshold test

**6A.1 — Production restrictions:**
5. IV-rank gate restricted to LIQUID/MEDIUM tier (16→7 names)
6. Zone-A 1.2× bonus DEMOTED to observation
7. Vega PnL applies nonlinear slippage

**6A.2 — Architectural cleanup:**
8. min() sizing semantics
9. Hysteresis dual-threshold
10. Dynamic James-Stein shrinkage

## Phase 6 status after tonight

**COMPLETE:**
- 6A.0 validation
- 6A.1 production restrictions
- 6A.2 architectural cleanup

**NEXT SESSION (6A.3+):**
- Point-in-time cohort reconstitution (monthly rebalance, Gemini spec)
- 2022 historical replay with all Phase 6 changes applied
- Momentum crash indicator (Daniel-Moskowitz framework)
- Investigate BULL+HIGH-IV finding (vega-PnL flipped from +10.5% to -12.1% under slippage — extend gate?)
- PEAD entry-zone module (Perplexity spec: top quintile, days 1-10, debit spreads, MU-excluded)

**DEFERRED FOREVER:**
- Multi-timeframe ladder (replaced by hysteresis)
- Universe expansion to 1500 NYSE
- Catalyst-API for biotech (clinicaltrials.gov scrape too brittle)
- Cross-sectional dispersion (overlaps existing regime gates)
- Composite circuit breaker (still wait for live data)

## Honest assessment

Tonight's work transformed the system from "celebrated Phase 5 completion with phantom-alpha edges" into a system that is **rigorously honest about what it can actually trade profitably**.

The slippage measurement was the kill-shot: most cohort names cannot survive realistic friction for short-DTE OTM directional trades. By restricting auto-trade to 7 names, demoting Zone-A bonus, and adding architectural primitives (min() policy, hysteresis, dynamic shrinkage), the system is positioned to actually win net of execution costs.

Tomorrow's market open is the first day with the restricted gate live. Real validation begins.

Files added: 4 new modules + 3 production wire-ins + 4 docs in `docs/feedback/strategy_0427_review/`.

Total tonight: ~25 hours of Sunday work compressed into one session. Time to sleep.
