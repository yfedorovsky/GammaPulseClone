# MIXED Tape Regime Refinement — Pre-Registration

**Status: PRE-REGISTERED. May 2 2026.**

The current Tape Regime Classifier (`server/tape_regime.py`) tags
~75% of alert days as `MIXED` (catch-all), and within MIXED, the
n=21 historical sample suggests bimodality:
- Apr 28 (open+0.02%, range 0.89%) — 2 winners on 4 alerts
- May 1 (open-0.03%, range 0.57%) — 3 winners on 11 alerts
- Apr 27 (open+0.11%, range 0.56%) — 0 winners on 1 alert
- Apr 29 (open+0.34%, range 0.77%) — 0 winners on 3 alerts

Winners cluster on **near-zero net move** days; losers on
**mildly-trending** days. n=4 days inside MIXED is too small to
commit thresholds.

## Hypothesis

**H₀**: There is no useful sub-classification within the MIXED
regime — winners and losers are randomly distributed regardless of
finer-grained day characteristics.

**H₁**: A finer split using `open_to_spot_pct` AND `path_efficiency`
features partitions MIXED into a "tradeable rotational" subgroup
(MIXED_RETURN_TO_OPEN) and a "noise drift" subgroup (MIXED_DRIFT)
with materially different hit rates.

## Pre-committed feature set

Use ONLY these annotation features computed at fire time
(`server/alert_annotations.py`):
- `open_to_spot_pct`
- `path_efficiency`
- `open_cross_count`
- `directional_change_count`
- `jump_share`

**Do NOT add features at analysis time.** If the analysis triggers
and the pre-committed features don't show effect, the conclusion is
"MIXED is not refineable with these features," NOT "let's try other
features."

## Pre-committed candidate splits

Three splits to test simultaneously (all on the same forward sample):

**Split A — open-move based**:
- MIXED_RETURN_TO_OPEN: |open_to_spot_pct| < 0.10
- MIXED_DRIFT: |open_to_spot_pct| ≥ 0.20
- MIXED_OTHER: 0.10 ≤ |open_to_spot_pct| < 0.20

**Split B — path-efficiency based**:
- MIXED_ROTATIONAL: path_efficiency < 0.30 AND open_cross_count ≥ 2
- MIXED_DIRECTIONAL: path_efficiency > 0.50 OR open_cross_count = 0
- MIXED_OTHER: anything else

**Split C — combined**:
- MIXED_TRADEABLE: |open_to_spot_pct| < 0.10 AND
                   (path_efficiency < 0.40 OR open_cross_count ≥ 2)
- MIXED_NOISE: |open_to_spot_pct| > 0.20 AND
               path_efficiency > 0.40 AND open_cross_count ≤ 1
- MIXED_OTHER: anything else

## Trigger to run

- Stage 2 of FALSIFICATION_PROTOCOL.md met (≥50 forward fires AND
  ≥20 day clusters), AND
- At least 30 forward alerts have `tape_regime_at_fire = MIXED`
  AND have all 5 features computed, AND
- At least 15 distinct MIXED day clusters

## Pre-committed decision rule

For EACH of the 3 splits independently:
- Compute hit rate in TRADEABLE/RETURN_TO_OPEN/ROTATIONAL subgroup
  (call this `p_yes`)
- Compute hit rate in NOISE/DRIFT/DIRECTIONAL subgroup (`p_no`)
- Cluster bootstrap by day: 2000 resamples; report 95% CI on
  `p_yes - p_no`
- Per-split verdict:
  - **PASS**: p_yes - p_no ≥ +25pp AND 95% CI excludes 0
  - **FAIL**: p_yes - p_no ≤ +5pp OR CI includes 0
  - **MIXED**: anything else

If MULTIPLE splits PASS, prefer Split A (simplest, fewest features).

## What PASS triggers

- Add the winning split's tag to telegram regime banner (annotation
  upgrade only, not a gate)
- Add a new `MIXED_REFINEMENT_RESULTS.md` documenting which split won
- Future workflow rule could conditional-on the refined regime
  (post-Stage-3 design decision; do NOT ship inline)

## What FAIL triggers

- Document conclusively: MIXED is not refineable with these features
- Stop investigating MIXED splits; the bimodality remains unexplained
- Reframe future work toward different feature sources (gamma context,
  macro windows, cross-asset alignment)

## Anti-degree-of-freedom guarantees

- Three splits committed UPFRONT; no fishing for new splits if all 3
  fail
- Hit-rate definition pinned: `peak_pnl_pct > +50%` from
  `intrinsic_capture_analysis.py` methodology (already pre-committed
  in INTRINSIC_CAPTURE_ANALYSIS.md)
- Tertile / threshold values pinned in this doc
- One run, one report. Re-running with different parameters requires
  amending this spec FIRST

## Output

- `scripts/mixed_refinement_analysis.py` (to be written when triggered)
- `docs/research/MIXED_REFINEMENT_RESULTS.md` (one-shot output)

## Source

- OpenAI deep research May 2 (day-state feature catalog: open_reversion,
  path_efficiency, open_cross, jump_share)
- Cross-LLM round 5 convergence on "MIXED is too coarse"
- The n=21 historical pattern of winners on near-zero-net-move days
