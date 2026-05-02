# Logistic Regression Spec — Pre-registered conditioning analysis

**Status: PRE-REGISTERED. Do NOT run until forward window completes
Stage 2 (≥50 fires AND ≥20 day clusters) per FALSIFICATION_PROTOCOL.md.**

This document pre-commits the methodology, predictors, target,
significance threshold, and interpretation rules for a single descriptive
regression of fire-level outcome against microstructure context. Pre-
registering prevents the "researcher degrees of freedom" contamination
that would otherwise occur if we ran multiple specifications and
reported the cleanest one.

## Why this exists

Gemini Pro round 1 (May 1) proposed: build a logistic / probit model of
trade success with predictors (spread_regime, VIX1D, RV, volume, OFI).
Test whether the spread coefficient remains significant when controlling
for the others. If spread → 0 with VIX1D in the model, the Test #6
spread effect is a vol-regime proxy, not an independent signal.

This is more in-sample analysis if run on the existing 27 fires —
which Perplexity round 2 explicitly warned against. The compromise is:
**don't run on in-sample data at all.** Run only on the forward sample
once Stage 2 stopping is met, treat as descriptive (not confirmatory),
and pre-commit everything below so the run is mechanical.

## Pre-registration — methodology

### Sample

- Use ALL fires from the forward window at the moment Stage 2 stopping
  rule is met (≥50 fires AND ≥20 day clusters).
- **Do NOT include the in-sample 27 fires.** This regression is
  forward-only.
- Do not run on Stage 1 sample. Do not run intermediate refits.
- One regression. One report. No model selection over specifications.

### Target variable

`win_flag` (binary): 1 if `gated_pnl_pct > 0`, else 0.

Secondary continuous target reported alongside but not used for the
hypothesis test: `opt_eod_pnl_pct`.

### Predictors (fixed list — do not add or drop)

1. `spread_30m_mean_log` — log of 30-min trailing mean stock spread
   at fire time (already collected for the spread gate).
2. `vix1d_close_prior` — VIX1D close from prior trading session.
3. `rv_30m` — realized vol over 30-min trailing window of underlying
   1-min log returns.
4. `volume_z` — z-score of underlying 1-min volume at fire vs that
   day's session minute-volume mean / SD.
5. `aggressive_flow_notional_log` — log(1 + Gate 4 aggressive notional
   at fire). Already in the live worker output.

All predictors are standardized (mean 0, SD 1) over the forward sample
before fitting, so coefficients are comparable in magnitude.

### Model

Single logistic regression:

```
logit(P[win_flag = 1]) = β₀ + β₁·spread + β₂·vix1d + β₃·rv + β₄·volume + β₅·aggflow
```

Fit via `statsmodels.api.Logit` with HC1 robust standard errors
clustered by trading day. **No interaction terms. No transformations
beyond log + standardize. No regularization.** If statsmodels reports
quasi-separation or non-convergence, the result is "inconclusive";
do not switch to penalized regression to "save" the fit.

### The pre-committed test

**Primary hypothesis**: the standardized coefficient on
`spread_30m_mean_log` (β₁) is non-zero at p < 0.05 (two-sided).

If β₁ p-value < 0.05 with negative sign (more spread → lower
P[win]) → spread is an independent signal, the gate is justified
on its own, even controlling for vol regime.

If β₁ p-value ≥ 0.05 → cannot reject "spread effect is fully
absorbed by vol regime / other predictors." Spread gate stays
in production (pre-committed before this regression) but the
*causal* interpretation weakens to "spread happens to mark
unfavorable regimes."

**Do NOT remove the spread gate based on this regression.** The gate
is a pre-committed v2 modification supported by a 77pp in-sample
effect. The regression only informs interpretation, not gate inclusion.

### Reporting

A single `docs/research/LOGISTIC_REGRESSION_RESULTS.md` produced once
the run completes:
- Coefficient table with point estimates, robust SEs, p-values
- McFadden pseudo-R²
- Confusion matrix at decision threshold P=0.5
- The verdict on β₁ per the rule above
- All 5 coefficients reported (no cherry-picking)

Do NOT report alternative specifications. Do NOT add predictors and
re-run. The pre-registered specification is the only specification.

## Decision tree (pre-committed)

| β₁ p-value | β₁ sign | Interpretation | Action |
|---|---|---|---|
| < 0.05 | negative | Spread is independent signal | Spread gate stays; document |
| < 0.05 | positive | Anomaly (wide spread → more wins) | Investigate; spread gate stays for now (pre-committed) |
| ≥ 0.05 | any | Cannot distinguish from VIX/RV proxy | Spread gate stays; reframe as "marks unfavorable regimes" |

In all branches the spread gate REMAINS. This regression is descriptive,
not gate-deciding. Gate inclusion was pre-committed in V2_DETECTOR_SPEC.md
based on the Test #6 in-sample effect.

## What this regression does NOT do

- It does not validate the strategy edge — that is the job of the
  cluster-bootstrap on paired diffs.
- It does not let us add new gates. New gates require their own pre-
  registered audit on a separate sample.
- It does not let us tune predictors. The predictor list above is
  closed.
- It does not let us re-run on a richer sample later. One run, at
  Stage 2 stopping, on the forward fires only. Done.

## Source

- Gemini Pro round 1 (May 1 2026), Q4
- Perplexity round 2 (May 1 2026), warning on in-sample contamination
- Compromise per FINAL_INTERPRETATION.md: pre-register, run forward-only,
  treat descriptively
