# Layer-1 survivor criteria (the Layer-2 promotion gate)

**Purpose.** A *survivor* gate is deliberately **looser** than the final
`VALIDATED` bar. It answers one question: *is this directional signal real and
robust enough on the underlying to be worth spending ThetaData option-translation
budget on?* Passing it does **not** make a signal tradeable — it only earns a
Layer-2 (real option-fill) test. The final `VALIDATED` status requires both the
strict Layer-1 bar **and** a Layer-2 economic pass.

Two separate verdicts are emitted by `signal_bt.py` for every run:
- `survivor`  — the promotion gate below (loose; gates Layer-2).
- `spec_verdict` — the full 9-criterion bar (strict; the VALIDATED ceiling).

## Survivor gate (ALL must hold) — version `v2-2026-06-21`

| # | Criterion | Threshold | Why this bar (not stricter) |
|---|---|---|---|
| 1 | `n_events` | ≥ 30 | minimum power for the permutation null |
| 2 | signed `lift` | > 0 | must point the predicted direction at all |
| 3 | permutation p | < 0.15 | *screening* bar, not proof. We accept more false positives here because Layer-2 is the real filter; a 0.05 bar would discard borderline signals before the decisive option-cost test |
| 4 | `regimes_positive` | ≥ 3 of 5 | not a single-regime artifact (vol terciles + trend) |
| 5 | `last3_years_positive` | ≥ 2 of 3 | not purely an old-era effect |
| 6 | year breadth `years_pos` | ≥ 60% of years positive | not driven by one or two outlier years |
| 7 | OOS/IS lift ratio | > 0.60 | decay not catastrophic (≤40% haircut) before paying for the option test |
| 8 | cross-sectional breadth `frac_lift_pos` | ≥ 0.60 | **only if** the signal ran `--cross` and ≥10 names cleared `min_events`; a single-name/index-only signal is exempt and judged on its primary card |

`survivor = AND(criteria that apply)`.

**Version log.** `v1` (initial) used breadth ≥0.55 and omitted year-breadth /
OOS-ratio. `v2-2026-06-21` (cross-LLM refinement) tightened breadth to 0.60 and
added criteria 6–7 so a survivor can't be carried by a single year or a sharp
OOS decay. B1 (12-1 momentum) passes both v1 and v2; the 5 wave-1 rejects fail
both. The version is stamped into every result JSON (`survivor.version`).

## What survivor does NOT require (these are the strict VALIDATED-only bars)

- lift 95% bootstrap CI strictly excludes 0
- OOS annualized Sharpe > 0.8  (and overlapping-hold caveat below)
- OOS/IS lift ratio ≥ 0.65
- deflated Sharpe survives the global trial count
- cross breadth ≥ 0.65

These can fail at the survivor stage and the signal still earns a Layer-2 look —
because the option-fill economics often *re-order* signals (a strong-underlying /
weak-magnitude signal can die to premium while a modest-but-clean one survives).

## Known measurement caveats (apply judgment, do not auto-promote on the number)

- **Overlapping holds inflate Sharpe.** A k-day-hold signal entered on many
  consecutive days produces ~(1 − 1/k) autocorrelated trades; the annualized
  Sharpe is overstated. Treat Sharpe as directional, not literal.
- **Always-on signals are beta.** If a signal fires on a large fraction of all
  days (≳25%), it is a *regime/long-bias filter*, not a discrete setup; its win
  rate must be read against the (already drifting) base rate, and Layer-2 must
  show it beats a random-entry option-buy, not merely zero.
- **Survivor ≠ novel.** A survivor may be a known published factor (e.g.
  momentum). Note it; the Layer-2 economic test is what matters, not novelty.

## Layer-2 economic pass (the real bar, applied after promotion)

A survivor becomes `VALIDATED` only if, on a representative recent ThetaData
sample with **ask-in / bid-out** fills, the option trade:
1. has **positive mean P&L%** net of the realistic spread, AND
2. **beats a distance/random-entry option-buy control** of equal size (isolating
   the signal's edge from generic long-call drag), AND
3. is not driven by one or two outliers (median in the same sign as the mean).
