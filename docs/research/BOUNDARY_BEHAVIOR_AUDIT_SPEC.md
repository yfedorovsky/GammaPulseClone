# GEX Boundary-Behavior Audit — Pre-Registration

**Status: PRE-REGISTERED. May 2 2026 — AMENDED with v2 methodology
fix (May 2 2026 evening) after the original v1 run produced a
mechanically biased FAIL.**

## Amendment history

### v1 (initial pre-registration, committed cedd310)

Original methodology used a random ATM-rounded strike sampled from
±0.5% of spot as the matched control. Run produced verdict FAIL with
a 40pp bounce-rate gap favoring random — a result so one-sided that it
suggested mechanical bias rather than a real signal.

### v2 (this amendment)

The bias: GEX-approach events filter on `|spot − level| ≤ 0.3%`, so
GEX levels are systematically CLOSER to spot than the random controls
(which sample from a wider ±0.5% universe). Closer levels require
larger directional moves to qualify as "bounced past level by 0.3%
without first breaching by 0.2%" — so further-from-spot levels
trivially win on the bounce metric.

The fix: distance-matched random controls. For each GEX-approach
event with the level X% from spot, the random control is sampled at
exactly the same |X|% distance from spot (random direction
above/below spot). This makes the comparison apples-to-apples.

The amendment is justified because the asymmetry is INDEPENDENT of
the result direction — it would have biased the FAIL verdict
regardless of GEX's true behavior. Re-running with the fix is
"repairing a bad matched-control design," not "p-hacking until the
result looks good." The v2 result is the audit's actual answer; the
v1 result is preserved for the audit trail in
`BOUNDARY_BEHAVIOR_AUDIT_RESULTS_v1.md` (renamed from the original
output) but does NOT inform any decision.

This amendment-then-rerun pattern is allowed exactly once. If the v2
result also shows a methodological asymmetry, the audit retires as
inconclusive — no v3 silent re-runs.

This audit is **explicitly exploratory secondary analysis** per cross-LLM
round 4 policy guidance:

> "Allowed now: the GEX boundary-behavior audit, because it does not touch
> production code or the primary forward verdict. Required discipline:
> write the audit as an explicitly exploratory / strategy-class-pivot
> analysis, and do not let its result influence the current forward window."

The forward window for the long-premium structural-turn detector
(FALSIFICATION_PROTOCOL.md) is the PRIMARY experiment. Its verdict
is determined ONLY by the cluster-bootstrap on `paired_trades.db`.
This audit's result MUST NOT influence the long-premium forward
verdict, sizing, gate logic, or stopping decisions in any way.

The audit's purpose is to test a DIFFERENT hypothesis on existing
data so that — in the most likely scenario where the long-premium
forward window returns inconclusive or weak — the next program
(credit-spread variant at GEX boundaries) is either pre-validated
or pre-killed before the calendar-time wait completes.

## The hypothesis

**H₀ (null)**: GEX levels (king, floor, ceiling) act as price boundaries
no more reliably than equivalent-distance random ATM-rounded strike
levels.

**H₁ (alternative)**: GEX levels contain price (act as boundaries to
fade) at a materially higher rate than random levels of similar
distance from spot.

If H₁ holds → the spatial-boundary thesis (Gemini round 1 reframe) is
real. Credit-spread variant at GEX levels is worth pursuing.

If H₀ cannot be rejected → the spatial-boundary thesis is wrong. GEX
levels are price points, not boundaries. The credit-spread pivot
loses its theoretical motivation. Hunt elsewhere.

## Data

- **Source**: `snapshots.db` (production GEX snapshots, ~32 per day for
  SPY/QQQ/IWM), 2025-08-06 to 2026-05-02. ~193 trading days × 3
  tickers ≈ 18,000 snapshots with king/floor populated.
- **Forward-looking price**: yfinance 5-min OHLCV bars (per ticker per
  day) for max/min in the 30-min and 60-min window after each snapshot.
  If yfinance is unavailable for a given (ticker, date), drop that
  snapshot from the audit; do not impute.
- **EOD closing**: yfinance daily close for the trading day of each
  snapshot.

## Approach event definition

For each snapshot at time t, for each level L ∈ {king, floor, ceiling}:

- L is an "approach event" iff `|spot_t - L| / L <= APPROACH_TOL`
- `APPROACH_TOL = 0.003` (0.3% — matches the production
  `FLOOR_PROXIMITY_PCT` constant in `server/structural_turn.py`)
- **v2 distance-matched random control (May 2 amendment)**: for each
  GEX-approach event, the random control is sampled at the SAME
  |spot − level| distance as the GEX level being controlled.
  Specifically: if GEX level L has `dist = (L - spot) / spot`, the
  random control is at `spot * (1 + sign * |dist|)` where `sign` is
  randomly chosen (deterministic seed) from {+1, −1}, then rounded
  to the nearest valid strike ($1 for SPY/QQQ/IWM). The sign-flip
  averages over above/below symmetry; the absolute distance is
  preserved so bounce/breach thresholds are equally challenging.
  - Exclude any random level that lands within $0.50 of any actual
    GEX level (king/floor/ceiling) on this snapshot. If exclusion
    leaves no valid strike at the matched distance, drop this
    approach from the audit.
- Sample K=1 random level per real-level approach (matched-pair
  design — each GEX approach gets exactly one random control approach
  on the SAME snapshot, so day/regime effects net out)

## Outcome metrics (per approach)

For the 30-min and 60-min windows after t, using forward yfinance bars:

1. **`max_breach_pct`**: max percentage breach BEYOND the level. For a
   floor at $570 with spot $570, the next 30-min low of $568 yields
   max_breach_pct = (570-568)/570 = 0.35%. Negative if the level was
   never breached.

2. **`bounced`** (binary): True iff
   - The level was approached from one side, AND
   - Price reached at least 0.3% past the level (`reverse_threshold`),
   - WITHOUT first breaching by more than 0.2% (`breach_threshold`)
   - Within the window.
   This captures "level held; price bounced off."

3. **`breached`** (binary): True iff price closed BEYOND the level by
   ≥ 0.2% at any minute during the window.

4. **`reclaimed`** (binary, only meaningful if `breached=True`): True
   iff after breaching, price closed back on the original side by
   end of window.

5. **`eod_side`**: 'above' / 'below' / 'at' — where price closed
   relative to the level at session close (15:59 ET). 'at' if within
   ±0.1%.

## Pre-committed decision rule

The audit reports four PRIMARY metrics, GEX vs random, paired by
snapshot:

| Metric | Window | Direction of "boundary works" |
|---|---|---|
| Mean `max_breach_pct` | 30-min | LOWER for GEX than random |
| Mean `max_breach_pct` | 60-min | LOWER for GEX than random |
| `bounced` rate | 30-min | HIGHER for GEX than random |
| `bounced` rate | 60-min | HIGHER for GEX than random |

**Decision**:

- **PASS** (boundary thesis supported): all 4 metrics show GEX better
  than random AND the differences are large enough to matter
  (Cohen's d ≥ 0.2 OR proportion difference ≥ 5pp on bounced rate;
  paired bootstrap on per-snapshot diffs).
- **FAIL** (boundary thesis rejected): 0 or 1 of 4 metrics show GEX
  better, OR all differences are within Cohen's d < 0.1.
- **MIXED**: 2-3 of 4 favor GEX, but effects are small (d < 0.2). Not
  decisive in either direction. Default action: do not pursue
  credit-spread variant on this evidence alone.

## Pre-committed: what the result does NOT do

- **Does NOT inform the long-premium forward verdict.** That window
  has its own primary metric (cluster-bootstrap on paired_trades).
- **Does NOT activate the IC logging analysis.** The IC analysis
  decision tree in `BACKLOG.md` requires BOTH this audit passing AND
  IC structure winning on different days than long-premium. This
  audit is necessary but not sufficient for the credit-spread pivot.
- **Does NOT modify any production code, gates, or thresholds.**
- **Does NOT inform sizing in the long-premium forward window.**

## Statistical methodology

- **Pairing**: each GEX approach event has one random-control approach
  on the same snapshot. The unit of analysis is the per-snapshot
  paired difference.
- **Clustering**: cluster by trading day (same as long-premium
  protocol). Days with < 5 GEX approaches drop from the day-cluster
  bootstrap (insufficient within-day n).
- **Bootstrap**: 2000 cluster-bootstrap resamples for the 95% CI on
  the mean paired difference per metric.
- **No p-values reported as primary.** The decision rule above is on
  CI exclusion + effect size, not on null-hypothesis significance.

## Output

- `scripts/gex_boundary_behavior_audit.py` (the script)
- `docs/research/BOUNDARY_BEHAVIOR_AUDIT_RESULTS.md` (the result —
  written ONCE, immediately after the script runs, no re-runs without
  also amending this spec)

## Anti-degree-of-freedom guarantees

- Approach tolerance, breach/reverse thresholds, and decision rule are
  all pre-committed in this document and frozen before the script
  runs.
- Random control is generated with a deterministic seed derived from
  (ticker, date, snapshot_ts) so the audit is reproducible.
- One run, one report. Re-running the script with different parameters
  requires amending this spec FIRST and explaining why.
- Result MUST NOT inform any change to the long-premium forward
  experiment.
