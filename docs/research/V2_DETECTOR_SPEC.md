# v2 Detector — Pre-committed design conditional on audit results

**Status: speculative blueprint, not for implementation. Pre-commits the
design space so when the seven audits return results we know exactly
which branches to walk and which to abandon.**

The whole point of writing this *before* the data is in: prevent the
"oh look at this number, let me build a gate around it" reflex that
data-snooped the v1 thresholds. By specifying the decision tree first,
we either build what we already pre-committed to or we don't build at
all — no silent threshold tuning between data and code.

## Decision tree

The seven audits and their pre-committed implications:

```
┌─────────────────────────────────────────────────────────────────┐
│  Test #1 — Microstructure profile of fires vs random minutes   │
│  Question: do gates fire at distinctive moments?               │
├─────────────────────────────────────────────────────────────────┤
│  ↑  ANY feature shows |Cohen's d| ≥ 0.5                        │
│  →  Gates have flow-side signal. Continue down the tree.       │
│                                                                 │
│  ✗  No feature ≥ 0.5d                                          │
│  →  RETIRE THE STRATEGY. The detector is finding GEX-level    │
│     coincidences with no microstructure correlate. No amount   │
│     of v2 gate work fixes a v1 that doesn't pick real flow.    │
└─────────────────────────────────────────────────────────────────┘
                              │  (continue if Test #1 passes)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #2 — OFI predictive power on raw tape (Cont 2014)        │
│  Question: does OFI predict 5/15/30-min returns?               │
├─────────────────────────────────────────────────────────────────┤
│  ↑  Max R² ≥ 0.05 (any ticker × any horizon)                   │
│  →  OFI gate is justified. Use OFI percentiles from Test #4    │
│     for thresholds.                                             │
│                                                                 │
│  ⚠  Max R² 0.02-0.05                                           │
│  →  Borderline. Build OFI gate as INFO-ONLY (logged but not    │
│     gated) for v2.0. Re-evaluate with forward sample.          │
│                                                                 │
│  ✗  Max R² < 0.02                                              │
│  →  No OFI gate. The Cont 2014 result doesn't transfer.        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #3 — VIX1D quartile vs day-microstructure                │
│  Question: does vol regime carry microstructure information?   │
├─────────────────────────────────────────────────────────────────┤
│  ↑  ≥2 features show K-W p<0.05 across quartiles               │
│  →  v2 IV regime gate using VIX1D quartile (PRIOR-DAY CLOSE,    │
│     NOT intraday). Threshold = top-quartile VIX1D triggers a   │
│     "tighter rules" mode. Pre-committed external indicator.    │
│                                                                 │
│  ✗  <2 features significant                                    │
│  →  No IV regime gate. Stays retired permanently.              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #4 — Background distributions for v2 thresholds          │
│  Provides the percentile lookup tables.                         │
│  No verdict — these tables are inputs to whichever gates the    │
│  other tests justify building.                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #5 — Trade-size cohorts                                   │
│  Question: which size-cohort's CVD predicts gated outcomes?     │
├─────────────────────────────────────────────────────────────────┤
│  ↑  One cohort shows |corr(aligned CVD, opt_eod_pnl)| > 0.3    │
│     and others show <0.15                                       │
│  →  v2 Gate 8 weights that cohort 2× the others                │
│                                                                 │
│  ⚠  Mixed                                                       │
│  →  Aggregate CVD only — don't split by size                   │
│                                                                 │
│  ✗  No cohort > 0.15 absolute correlation                      │
│  →  Drop CVD entirely. Trade direction classification at this   │
│     resolution doesn't predict outcomes.                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #6 — Spread regime                                        │
│  Question: do high-spread fires underperform?                   │
├─────────────────────────────────────────────────────────────────┤
│  ↑  Normal-spread mean PnL > High-spread mean PnL by ≥ 30pp     │
│  →  v2 hard gate: do not fire when 30-min mean spread > day p90 │
│                                                                 │
│  ⚠  10-30pp difference                                          │
│  →  Soft gate (warn but don't block). Or: scale position size   │
│     down by 50% when spread is elevated.                        │
│                                                                 │
│  ✗  <10pp difference or reversed                                │
│  →  No spread gate.                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test #7 — SPY/QQQ lead-lag                                     │
│  Question: does one ETF lead the other at minute resolution?    │
├─────────────────────────────────────────────────────────────────┤
│  ↑  Peak corr at lag ≠ 0, with |peak − lag0| > 0.05             │
│  →  v2 cross-confirm uses lagged OFI from the leading ticker    │
│                                                                 │
│  ✗  Peak at lag 0                                               │
│  →  Keep current same-second cross-confirm logic                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       BUILD v2 OR DON'T
```

## v2 architecture (assuming favorable audit outcomes)

If Tests 1, 2, 5, 6 all return favorable results (OFI predictive +
microstructure-distinctive fires + cohort signal + spread gate
justified), the v2 detector looks like:

### Preflight (before any gate)

1. **Trend filter** (carry over from v1) — require tape alignment past
   60 min of session.
2. **POS-regime BEARISH block** (carry over from v1) — block bearish
   on POS-gex days.
3. **NEW: Spread regime gate** — if 30-min trailing mean spread for the
   ticker exceeds that day's p90 (computed online from morning data),
   block the fire. This is conditional on Test #6 passing.

### Replace tick-rule gates

Currently Gates 5 (NCP corroboration) and 8 (CVD divergence) use
tick-rule classification on minute-bar proxies.

**Gate 5 v2**: aggregate Lee-Ready CVD over the [fire − 30min, fire]
window using the contributing trade-size cohort identified by Test #5.
Threshold pre-committed from Test #4 percentiles: require absolute
direction-aligned CVD > p75 of historical (ticker × TOD-bucket)
distribution.

**Gate 8 v2**: replace minute-bar close-direction proxy with tick-level
Lee-Ready CVD divergence. Same divergence pattern logic as v1 (price
makes equal/lower low, CVD makes higher low for bullish), but on tick
data not minute bars.

### Add new gates from microstructure

**Gate 9 (NEW): OFI alignment** — direction-aligned OFI in the [fire − 5min,
fire] window must exceed p75 of (ticker × TOD-bucket) distribution from
Test #4. Conditional on Test #2 returning R² ≥ 0.05.

**Gate 10 (NEW): Microprice deviation** — at fire time, microprice
deviation from mid (sign-aligned) must be in the top tertile of recent
distribution. Indicates stack imbalance favoring the trade direction.

### Modified cross-confirm

If Test #7 finds lead-lag asymmetry, cross-confirmation becomes:
"the LEADING ticker's OFI at lag = peak_lag must be aligned with the
fire direction." Replaces the same-second OR-of-fireability check.

### Position sizing input

If Test #3 confirms VIX1D regime carries information, position size
becomes regime-conditional:
- VIX1D Q1 (calm): full size
- VIX1D Q2-Q3 (normal): 0.75× size
- VIX1D Q4 (stressed): 0.5× size or skip

This is *separate* from gate qualification — qualified fires still fire,
just with different position weight.

## What v2 does NOT change

- The 5 core structural gates (proximity, structural event, magnitude,
  regime match, GEX magnitude floor) stay as v1.
- Tier system (A+/A/B) preserves the v1 conviction grade meaning.
- Falsification protocol: v2 ALSO enters its own paired-trade
  experiment with random_minute_atm baseline before going live. We
  do not skip the validation step just because the gates look more
  principled.
- Frozen thresholds: every threshold added to v2 is set against
  Test #4 percentiles or Test #1 effect sizes — never re-tuned by
  observing the experiment.

## Stop conditions

Build v2 ONLY if:

1. v1 forward falsification (paired_bootstrap_analysis.py on 30+ live
   fires) shows positive timing alpha CI, AND
2. Test #1 returns at least one feature with |d| ≥ 0.5, AND
3. At least one of Tests #2, #5, #6 returns a clear positive verdict.

If v1 doesn't validate, don't waste time building v2. The gates
themselves are the problem, not their tick-vs-bar implementation.

If Test #1 fails, the strategy framework lacks flow-side signal
entirely. v2 doesn't fix that.

If Tests #2, #5, #6 all return null, there's no upgrade path even if
v1 validates — keep v1 as-is and accept the n=27 ceiling.

## Implementation effort estimate (conditional on go)

- Add spread regime gate: 1-2 hours
- Replace Gate 8 with tick Lee-Ready CVD: 2-3 hours
- Replace Gate 5 NCP with size-cohort weighted CVD: 2-3 hours
- New Gate 9 (OFI alignment): 2-3 hours
- New Gate 10 (microprice deviation): 1-2 hours
- Lead-lag-aware cross-confirm: 2-3 hours
- VIX1D-regime position sizing: 1 hour
- v2 paper-trade tracker (parallel to v1's paired_trades.db): 2-3 hours
- Tests + smoke: 3-5 hours

**Total: ~16-25 hours of focused engineering**, conditional on Tests
delivering positive results. Don't start until you've read the audit
reports.

## What to do tomorrow morning

1. Read the seven audit reports in `docs/research/`:
   - gate8_audit.md
   - microstructure_profile_audit.md
   - ofi_predictive_power.md
   - day_regime_audit.md
   - background_distributions.md
   - trade_size_cohort_audit.md
   - spread_regime_audit.md
   - lead_lag_audit.md (note: lead-lag is conceptually separate; runs same chain)

2. Walk the decision tree above with the actual numbers from each report.

3. Decide: **build v2 yes/no.** If yes, exactly which gates per the spec.
   If no, the v1 forward experiment continues unchanged.

4. Either way: do not modify v1 production code. The frozen-gates rule
   for the live falsification holds until the bootstrap on 30+ paired
   observations delivers a verdict.
