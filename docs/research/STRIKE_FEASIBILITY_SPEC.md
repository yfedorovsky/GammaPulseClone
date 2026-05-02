# Strike Feasibility Analysis — Pre-Registration

**Status: PRE-REGISTERED. May 2 2026.**

Pre-registers the methodology for evaluating whether `strike_reachability_ratio`
(and related feasibility annotations) predict 0DTE alert outcomes. Per
cross-LLM round 5 consensus and the production freeze, no analysis runs
until the forward window has accrued ≥50 forward alerts across ≥20 day
clusters.

## Hypothesis

**H₀**: `strike_reachability_ratio` (expected EOD move ÷ strike distance)
has no predictive relationship with whether a 0DTE alert produces a
profitable outcome.

**H₁**: Alerts with `reachability ≥ X` (threshold to be set after Stage 2
calibration) have materially higher hit rates than alerts with
`reachability < X`.

## Why this hypothesis matters

OpenAI deep research (May 2): *"the highest-value missing layer is not
another micro-tweak to the current confluence score. It is a day-state
and trade-feasibility layer."*

Gemini deep research (May 2): *"option's mathematical probability of
expiring in the money is not a function of absolute price distance; it
is a function of the underlying asset's expected move."*

Current strike picker uses absolute distance from spot (~0.25% OTM
across all tickers). Reachability ratio normalizes for IV regime —
the same 0.25% OTM strike is more reachable on a high-IV day than a
low-IV day.

## Pre-committed analysis methodology

### Sample
- Source: `zero_dte_alerts.db`, joined to outcomes computed by
  `scripts/intrinsic_capture_analysis.py`
- Use FORWARD-ONLY alerts (fired_at > Stage 1 start date)
- Do NOT include the 21 historical alerts in primary analysis
  (they're used only as "sanity check on direction of effect")
- Minimum n: 50 alerts AND 20 day clusters

### Trigger to run
- Stage 2 stopping rule met (≥50 fires AND ≥20 day clusters) per
  FALSIFICATION_PROTOCOL.md, AND
- Forward sample has at least 30 alerts where `strike_reachability_ratio`
  was successfully computed (i.e., realized vol + day state both
  available)

### Primary statistical test
- Compute reachability tertile splits: low (<33pct), mid (33-67pct),
  high (>67pct) of the forward sample's reachability distribution
- For each tertile: hit rate = (n alerts where `peak_pnl_pct > +50%`) / n
- Cluster bootstrap by day: 2000 resamples; report 95% CI on hit-rate
  difference between high and low tertile
- Decision rule (PRE-COMMITTED):
  - **PASS**: high-tertile hit rate − low-tertile hit rate ≥ +20pp,
    AND CI excludes 0
  - **FAIL**: difference ≤ +5pp OR CI includes 0
  - **MIXED**: anything else

### What PASS triggers
- Add reachability filter to alert dispatcher: skip alerts with
  reachability below the bottom-tertile threshold
- This is a POST-STAGE-3 production change, not a Stage 2 change
- Re-run forward window with filter applied

### What FAIL triggers
- Reachability is not a useful filter
- Document and move on; do not re-test on different thresholds
- Annotation continues for diagnostic purposes only

## Anti-degree-of-freedom guarantees

- Tertile split (vs continuous threshold) is pre-committed to avoid
  threshold-fishing
- Hit-rate definition (`peak_pnl_pct > +50%`) is pre-committed
- Decision thresholds (+20pp / +5pp) are pre-committed
- One run, one report. Re-running with different parameters requires
  amending this spec FIRST and explaining why
- Result MUST NOT influence the long-premium forward verdict
  (which is on cluster-bootstrap of paired_trades.db, not
  alert-level outcomes)

## Output

- `scripts/feasibility_analysis.py` (to be written when triggered)
- `docs/research/STRIKE_FEASIBILITY_RESULTS.md` (one-shot output)

## Source

- OpenAI deep research May 2 (Q4-Q5 cross-cut)
- Gemini deep research May 2 (delta-based strike selection thesis)
- Cross-LLM round 5 consensus on "feasibility layer" being the
  largest missing instrumentation
