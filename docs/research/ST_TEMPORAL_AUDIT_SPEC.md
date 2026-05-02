# Structural Turn Temporal Audit — Pre-Registration

**Status: PRE-REGISTERED. May 2 2026.**

Pre-registers the methodology for evaluating whether the **temporal-
aware loose-intersection** version of the ST detector (per OpenAI deep
research May 2) would have produced more profitable trades than the
current strict 8-gate boolean-AND.

## Background

OpenAI deep research May 2: *"some gates are slow state variables.
Some are fast triggers. You are currently forcing them to co-occur on
a single minute, which is exactly why they miss each other. Regime,
structural context, spread regime, and broader flow regime should
persist with a TTL on the order of 15-30 minutes. Sweeps, absorption,
and CVD divergence should persist with a TTL of 1-5 minutes."*

The May 1 forensic showed SPY came within 1 gate (volabs) of qualifying
multiple times but the volabs-passing minutes (12 of 390) didn't
temporally overlap with the regime-passing minutes (also rare).
Backfilled annotation confirms: SPY had 10 temporal-near-fire moments
at 14:28-14:33 ET (slow_state=100%, fast=4/5, only volabs missing).

Production logic is FROZEN until Stage 3. This spec pre-registers what
analysis would justify proposing the temporal-aware logic as the v2
production gate AFTER Stage 3 completes.

## Hypothesis

**H₀**: Temporal-near-fire moments (annotated via the loose-intersection
logic in `server/st_near_fire.py`) have NO better expected outcome
than random non-fire minutes on the same days.

**H₁**: Trades entered at temporal-near-fire moments produce
materially better expected outcome than the random_minute_atm baseline,
at a hit rate consistent with what the strict boolean-AND would have
produced if its missing-gate had aligned.

## Pre-committed methodology

### Sample
- Source: `structural_turns.db` for evaluations during the forward
  window (started May 4 2026)
- Use FORWARD-ONLY data — do NOT include the in-sample period
- Identify "temporal-near-fire" moments: rows where
  `temporal_near_fire = 1` AND `qualified = 0` (strict-AND missed
  but loose-intersection would have caught)
- Minimum n: ≥30 temporal-near-fire moments AND ≥10 day clusters

### Trigger to run
- Stage 3 stopping rule met per FALSIFICATION_PROTOCOL.md
  (≥75-100 fires AND ≥25 day clusters), AND
- Forward sample has ≥30 temporal-near-fire moments where
  `qualified = 0` (i.e., strict logic missed but loose caught)

### Primary statistical test
For each temporal-near-fire moment, simulate a paper trade using the
SAME paired_trades infrastructure as the forward window:
- gated_temporal: enter at temporal-near-fire moment, ATM call/put
  per direction, EOD-bid exit (or stop)
- random_minute_atm_match: K=5 random non-fire minutes on the same day,
  same direction, same exit logic — match `paired_trades.py` controls

Compute paired diff: `gated_temporal_pnl - random_atm_pnl` per moment.
Cluster bootstrap by day: 2000 resamples; report 95% CI on mean diff.

**Decision rule (PRE-COMMITTED)**:
- **PASS**: 95% CI excludes 0 on positive side AND day-level effect
  not driven by 1-2 outliers AND temporal-near-fire mean ≥ +20pp
- **FAIL**: CI includes 0 OR temporal mean ≤ +5pp
- **MIXED**: anything else

### What PASS triggers
- Author a v2 ST detector spec proposing temporal-aware logic as the
  production gate (loose-intersection: 4-of-5 fast + slow co-occur
  trailing 15min)
- Spec must include:
  - Pre-registered backtest of the new logic against the in-sample
    27-fire dataset (would more or fewer fires happen?)
  - Pre-registered forward window for the v2 logic
  - Sizing + stopping rules unchanged
- Do NOT ship the v2 logic without going through this full re-vetting
  cycle. We learned in May 1 that "obvious improvements" can be
  artifacts.

### What FAIL triggers
- Document conclusively: temporal-aware loose intersection does not
  produce better trades than strict boolean-AND
- Continue using strict logic; annotation persists for diagnostic
  purposes only
- Reframe future ST work toward different gate definitions, not
  different intersection semantics

## Anti-degree-of-freedom guarantees

- Slow/fast gate split (regime+magnitude+structural_event vs
  proximity+volabs+aggflow+ncp+cvd) is pre-committed in
  `server/st_near_fire.py`
- TTL windows (15min slow / 5min fast) are pre-committed
- Loose-intersection threshold (4-of-5 fast) is pre-committed
- One run, one report. Re-running with different parameters requires
  amending this spec FIRST and explaining why
- Result MUST NOT influence the long-premium forward verdict during
  Stages 1-3 (the primary metric is paired_trades.db cluster-bootstrap)

## Output

- `scripts/st_temporal_audit.py` (to be written when triggered)
- `docs/research/ST_TEMPORAL_AUDIT_RESULTS.md` (one-shot output)

## Source

- OpenAI deep research May 2 (two-timescale latent-state detector)
- Gemini deep research May 2 (continuous exponential-decay scoring;
  related but distinct framing — we test loose-intersection first
  because it's simpler and more interpretable)
- May 1 forensic: SPY 7/8 near-fires at 10:28 + 10 temporal-near-fires
  at 14:28-14:33 demonstrate the temporal-aliasing problem empirically
