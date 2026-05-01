# Final Interpretation — May 1 2026 Audit Cycle

This document is the single source of truth on what the audit cycle
returned and what to do with it. It supersedes the earlier
`AUDIT_SYNTHESIS.md` (which followed the strict spec stop-at-Test-#1
logic and didn't surface the full picture).

## TL;DR

After a full Databento-data audit (8 tests, 6 months SPY+QQQ tick
data, ~96k per-minute observations) and cross-LLM critique
(Perplexity-free + Gemini Pro), the verdict is:

1. **Don't build v2 in any meaningful sense.** Three independent v2
   spending paths are dead (Lee-Ready, OFI, intraday VIX1D). Test #1
   FAIL pre-committed to RETIRE branch.
2. **One exception: add the spread preflight gate** (one-liner, both
   LLMs endorse, large empirical effect, theoretically grounded).
3. **Forward paper-trade window** with stricter stopping rule than v1:
   ≥30 fires AND ≥15 day clusters (Gemini's recommendation; both LLMs
   converged on minimum 10-15 clusters).
4. **Sizing language** strips the "Kelly" framing — "fixed tiny size,
   exploratory capital" only.
5. **Honest expected outcome of the forward experiment**: small,
   noisy edge that justifies hobby-scale live risk at most. Not a
   scalable strategy. Both LLMs concur.
6. **One reframe worth chewing on later** (Gemini): use GEX levels as
   *spatial boundaries to fade*, not as *timing triggers*. Different
   strategy class. Backlog item.

## The eight audits, with numbers

| Test | Verdict per spec | Key number | Implication |
|---|---|---|---|
| Gate 8 (LR vs bar) | TIE / BAR_WINS | LR corr +0.30, bar +0.33 | Don't replace Gate 8. Don't buy OPRA tick options data. |
| #1 microstructure profile | **FAIL** | Largest Cohen's d=0.49 (volume), all others <0.4 | RETIRE branch fires. Gates aren't keyed to microstructure singularities. |
| #2 OFI predictive (Cont 2014 replication) | **FAIL** | Max R²=0.0002 across 6 cells, n=44k each | OFI signal arbitraged out in 2025-26 SPY/QQQ. Don't build OFI gates. |
| #3 VIX1D regime vs day-microstructure | **PASS** | 12 of 16 K-W tests p<0.05 | Vol regime correlates with spread/volume/mp_dev at day level. |
| #4 Background distributions | OK | 96,304 obs, percentiles per (ticker × TOD) | Pre-committed thresholds available for any v2 gate. |
| #5 Trade-size cohort CVD | MIXED | small +0.32, medium +0.23, large +0.07 | Surprise: small > large. Not strong enough for cohort weighting. |
| #6 Spread regime | **PASS** | Normal-spread +63%/40% WR vs HIGH -14%/30%; 77pp diff | **Build the spread gate.** Largest empirical effect we measured. |
| #7 SPY/QQQ minute-OFI lead-lag | FAIL | Lag-0 corr +0.36, all other lags ~0 | Same-second cross-confirm is correct. |

## How Test #1 FAIL and Test #6 PASS coexist

Both LLMs converged on the same reading, articulated cleanly by
Gemini:

> Test #1 asks: "Does the tape look weird exactly when the strategy
> fires?" Answer: No, it looks like a normal high-volume minute.
>
> Test #6 asks: "Given that a fire has occurred, does background
> liquidity predict the outcome?" Answer: Yes, wide spreads destroy
> the edge.
>
> Conclusion: gates are not keyed to unique microstructure moments,
> but spread clearly marks bad ones. v2 is dead, but a single
> preflight spread gate on v1 is still worth considering.

## Cross-LLM consensus on actions

### Both LLMs agree

- Test #1 FAIL is decisive for v2 (do not move the d≥0.5 bar after
  seeing 0.49 — textbook researcher degrees-of-freedom)
- v1 isn't dead — Test #1 just rules out microstructure-singularity
  framing
- Spread gate worth adding (one line)
- OFI is arbitraged out, not a methodology bug
- Paper-only sizing until forward window completes
- Forward window is the only path forward

### Where they diverge / new content

- **Stopping rule strictness**: Perplexity says ≥50 fires AND ≥10
  clusters. Gemini says ≥30 fires AND ≥15 clusters. Conservative
  consensus: minimum 15 day clusters.
- **Sizing language**: Perplexity strips "Kelly" entirely; Gemini is
  more permissive but still says paper-only first.
- **Q4 spread-vs-VIX proxy test** (Gemini new): logistic regression
  predicting trade success with spread + VIX1D + RV. If spread
  coefficient drops to zero with VIX controls, it's a proxy. Still
  more in-sample work — pre-commit threshold first if we ever do it.
- **Q7 strategy reframe** (Gemini new): GEX levels as spatial
  boundaries to fade structural liquidity, not as timing triggers.
  Different strategy class (credit spreads vs long premium). Backlog
  item, not tonight's work.

## Forward action items

In order of urgency:

### Tomorrow (or whenever)

1. **Update `docs/research/FALSIFICATION_PROTOCOL.md`**:
   - Stopping rule: "≥30 fires AND ≥15 day clusters" (was 30/5)
   - Sizing: strip "Kelly" framing, replace with "fixed tiny size,
     0.25-0.5% of account per trade, exploratory capital — NOT Kelly"
   - Add: "honest expected outcome is small noisy edge at hobby scale"

2. **Add spread preflight gate to `server/structural_turn.py`**:
   - One-line check: if 30-min trailing mean spread > day p90, do
     not fire
   - Spread distributions per ticker × TOD bucket pre-committed in
     `docs/research/background_distributions.md`
   - For SPY morning, p90 = 0.049 (~5 cents). For QQQ morning, p90 =
     0.053. Read the table for other TOD buckets.

3. **Update `docs/research/V2_DETECTOR_SPEC.md`**:
   - Record audit results
   - Confirm RETIRE branch fired on Test #1 FAIL
   - Add: "do NOT relax d=0.5 threshold; result was 0.49, retire is
     decisive"

4. **Update `docs/BACKLOG.md`**:
   - Add: "GEX-as-spatial-boundary credit-spread strategy variant"
     as a separate research program with its own pre-commitments

### Next 2-6 weeks

5. **Let the forward window run.** Don't run more in-sample analysis.
   Calendar time is the only information path forward.
6. **Daily after market close**: `python -m server.paired_trades --date YYYY-MM-DD`
   — populates paired_trades.db with gated + random_minute_atm +
   naive_open_atm rows.
7. **Weekly check-in**: `python scripts/paired_bootstrap_analysis.py`
   to monitor CI evolution. Don't act on intermediate results.
8. **Stopping condition met (≥30 fires AND ≥15 clusters)**: run final
   bootstrap. If CI excludes 0 positive AND day-level effect not
   carried by 1-2 outliers AND sign of delta consistent across days
   → small live trade size. Otherwise → retire as production idea,
   keep as research artifact.

## Honest expected outcome

Both LLMs concur on Q7 framing:

> The falsification protocol is not about proving you've found a
> massive institutional edge. It's about deciding whether what you've
> built is better than break-even enough to justify any live
> deployment at all, and if so, at what tiny size.

In the best plausible forward outcome:
- Forward mean diff: +10-20pp
- Forward 95% CI: roughly [+2pp, +30pp] if you're lucky
- That justifies micro-scale live risk (~$100-200/trade on $50k account)
- Does NOT justify "serious capital" or scaled sizing

Acceptable ending: **"There might be a small timing edge here, but
not one large or stable enough to justify the operational complexity.
Retire as production, keep as research artifact, free up bandwidth
to hunt elsewhere."**

That's a successful experiment. The point is not to discover gold;
it's to know whether what you built is worth running at all.

## What's been built tonight (research artifacts)

- 6 months of multi-venue tick data on SPY+QQQ ($1k-$5k commercial
  replacement value, $0 net cost via $125 free credit)
- 8 audit scripts + synthesis runner
- Falsification experiment infrastructure (paired_trades.py +
  bootstrap analysis)
- Pre-committed v2 decision tree (V2_DETECTOR_SPEC.md)
- Pre-committed external thresholds (background_distributions.md
  percentile lookups)
- Memory-efficient streaming OLS (ofi_predictive_power_v2.py)
- 25+ commits pushed, 8+ research documents

The strategy itself isn't "better." But the framework around it is
honest, falsifiable, and disciplined. That's the actual asset.

## What NOT to do

- Don't relax the d≥0.5 threshold
- Don't run more in-sample analysis on the existing 27 fires
- Don't ship live with significant size before forward CI completes
- Don't use Kelly sizing language (premise of "you know the edge"
  doesn't hold)
- Don't call the spread gate "validated" — it's a hypothesis with
  large in-sample effect, not yet proven out-of-sample
- Don't start the GEX-as-spatial-boundary alternative tonight (it's
  a separate program; finish current experiment first)
- Don't lose the Databento data — back it up off-machine

## Closing note

Tonight's session prevented shipping a contaminated +21% claim.
That's a successful outcome regardless of what the forward window
returns. The discipline — pre-committed thresholds, RETIRE branches,
LLM cross-checks, refusing to relax bars after seeing borderline
results — is the actual product. The strategy is incidental.
