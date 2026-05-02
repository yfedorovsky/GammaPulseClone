# Falsification Protocol — Structural Turn Gate Alpha

Started Apr 30 2026 per Perplexity Q11 protocol. The whole point is to
generate a falsifiable claim about gate alpha vs a fixed-time naive baseline.

## The hypothesis

- **H₀**: For trades taken when all 5 structural gates pass, the trend filter
  is satisfied, and BEARISH-on-POS is blocked, expected P&L of the gated entry
  equals expected P&L of a naive 09:30 ATM same-direction entry on the same day.
- **H₁**: Gated entry has strictly higher expected P&L than naive entry.

## The frozen system (do not modify until experiment delivers a verdict)

In `server/structural_turn.py`:

- Five core gates: floor proximity, structural event, volume absorption,
  aggregate flow, NCP corroboration
- Tier system: A+/A/B (CVD demoted to uplift, not hard gate)
- Trend filter v3 (Apr 30): require alignment past 60min of session
- POS-regime BEARISH block (Apr 30 Perplexity Fix #1)

Exit rule: -30% hard stop, EOD bid liquidation at 15:59 ET. No scaling, no
take-profit. (Per `scripts/exit_rule_sim_with_trajectories.py` validation.)

## What's NOT in the system (deliberate)

- IV regime gate — externally unvalidated against VIX1D−VIX9D
- Any direction-specific tweaks beyond POS-bearish disable
- Any further parameter tuning
- Quote-based flow classification (would replace tick-rule Gate 5 / 8) —
  research target after experiment delivers, not during

## The experiment design

For every qualified fire from the live worker, three trades are computed
on the same day:

**Gated trade**: enter at fire-time NBBO ask; same option (ticker, strike,
right, expiration) the alert specifies; -30% stop or 15:59 EOD exit at bid.

**Random_minute_atm trade — PRIMARY control**: per Perplexity's Apr 30 #2
follow-up, this isolates *timing alpha* by holding direction + strike rule
+ exit logic constant and varying only the entry minute. Sample K=5 random
minutes from [09:30, 15:30) on the same day, excluding any minutes when
the gate fired. For each sampled minute: same direction, ATM strike at
that minute's spot, same expiration, same -30%/EOD exit. The persisted
`pnl_pct` is the mean of the K samples. Deterministic via fire-id-derived
seed so re-runs match.

**Naive_open_atm trade — SECONDARY control**: enter at 09:30 ET same day;
same direction; ATM strike at 09:30 spot; same expiration; same -30%/EOD
exit. Tests the whole-package question: "does the strategy beat a fixed-
time morning bet?" Conflates timing alpha with day/contract selection.

All three persisted to `paired_trades.db` (separate database; not in
production tables). Schema in `server/paired_trades.py`.

## How to run

**Daily EOD job** (after market close):

```bash
python -m server.paired_trades --date 2026-04-30
```

This pulls qualified fires from `structural_turns.db` for the day,
computes both gated + naive paper trades using ThetaData NBBO bars,
persists results.

**For the existing 4/13–4/24 backtest sample** (already loaded):

```bash
python -m server.paired_trades --date 2026-04-21 \
  --csv docs/research/structural_turn_30d_fires.csv
```

**Bootstrap analysis** (run periodically as data accrues):

```bash
python scripts/paired_bootstrap_analysis.py
```

Outputs:
- per-source summary (gated vs naive)
- paired difference (gated − naive) per fire
- cluster-bootstrap-by-day 95% CI on mean difference
- per-day, per-direction breakdowns

## Stopping rule (staged — May 2 2026 revision, futility-only S1+S2)

History:
- Apr 30: ≥30 fires AND ≥5 day clusters (initial)
- May 1: tightened to ≥30 AND ≥15 day clusters across 5-LLM consensus
- **May 2 (current): asymmetric staging per cross-LLM round 3 consensus
  on Q1 (sequential testing).** Stages 1 + 2 are FUTILITY-ONLY (can only
  retire); Stage 3 is the FIRST allowed efficacy decision. This solves
  the multiple-looks Type I inflation concern without requiring formal
  Pocock / O'Brien-Fleming alpha spending.

Why asymmetric: ChatGPT and Gemini both observed that allowing positive
verdicts at three CI looks inflates the unconditional false-positive
rate to ~10-12%. The practical fix is not formal alpha spending (which
implies clinical-trial pretensions we shouldn't claim) but to forbid
positive stopping early. Futility stops do NOT inflate Type I — they
only inflate Type II (false negatives). Killing a marginal +5pp edge
early is acceptable when the deployment threshold is already at
"micro-scale exploratory" sizing.

ChatGPT's MDE math on day-level SD ~30pp: MDE ≈ 2.8 × 30 / √n_clusters
→ 15 clusters ~22pp, 20 ~19pp, 25 ~17pp. Powered for ≥20-30pp true
effects; will NOT reliably detect <10pp even at Stage 3.

The window proceeds in three stages. Each stage gates progression
to the next; do not act on intermediate CIs except in the explicitly
specified futility branches.

**Stage 1 — Data-quality + futility check (≥30 fires AND ≥15 day clusters)**:
Run cluster-bootstrap on PRIMARY metric. **No positive verdict allowed.**

Allowed actions at Stage 1:
- Retire only if ALL of the following hold (asymmetric futility per
  ChatGPT round 3 — strict to avoid false-killing a +5pp edge):
  - 95% CI upper bound < +5pp, AND
  - median daily alpha ≤ 0, AND
  - best-day-removed alpha ≤ 0, AND
  - sign of paired-diff is negative on >50% of day clusters
- Data-quality checks (ALL must pass to continue):
  - per-day fire counts not dominated by 1-2 days
  - spread feed populating (`spread_30m_mean` non-null on ≥80% of fires)
  - paired_trades.db has all three sources (gated, random_minute_atm,
    naive_open_atm) per fire
  - no >1 standard deviation regime change in median daily alpha
    between first and second half of Stage 1 fires
- If any data-quality check fails: pause, fix, and DO NOT advance the
  fire count toward Stage 2 until clean.

If neither retire nor data-quality halt fires → continue to Stage 2.

**Stage 2 — Continued futility check (≥50 fires AND ≥20 day clusters)**:
Same logic as Stage 1, looser futility threshold. **Still no positive
verdict allowed.**

Allowed actions at Stage 2:
- Retire if 95% CI upper bound < 0 AND median daily alpha ≤ 0
  (i.e., the bootstrap is sliding toward the null, not just below
  the production-relevance threshold).
- Otherwise continue to Stage 3.

This stage exists primarily to give the experiment more time to
accrue data before making any positive call. If you find yourself
wanting to "wrap it up at Stage 2 because the CI looks good," that
is exactly the multiple-looks bias the staged design exists to prevent.

**Stage 3 — First allowed efficacy decision (≥75-100 fires AND ≥25 day clusters)**:
THIS is the only stage that can produce a positive verdict.

Decision rules (ALL three must hold for positive):
1. 95% CI on PRIMARY paired-diff excludes 0 on the positive side, AND
2. day-level effect is not carried by 1-2 outlier sessions
   (best-2-days-removed CI still excludes 0), AND
3. sign of paired-diff is positive on >60% of day clusters

If all three hold → "small noisy edge confirmed at hobby scale";
proceed to micro live deployment per Sizing section below.
If any one fails but CI excludes 0 → ambiguous; document and continue
paper-only for additional 25-50 fires before re-evaluating.
If CI includes 0 → retire as production. Keep code as research artifact.

The asymmetry is intentional. The price of late efficacy stopping is
~50 extra calendar days of paper trading. The price of allowing early
efficacy stopping is potentially shipping live on a noise-driven
positive that would have flipped at Stage 3.

The verdict is on the **PRIMARY control** (gated vs random_minute_atm).
The SECONDARY control (gated vs naive_open_atm) is reported alongside
but does NOT determine the verdict. If gated > naive_open_atm but
gated ≈ random_minute_atm, the "edge" is contract/day selection, not
structural detection — that's a different and weaker claim.

## Sizing (revised — May 2 2026)

**Paper-only through Stage 1, Stage 2, and Stage 3.** Do not allocate
live capital on intermediate bootstrap results. Stage 3 is the FIRST
stage that can produce a positive verdict; under the May 2 asymmetric
staging rule, Stages 1 and 2 are futility-only.

If Stage 3 cleared (CI excludes 0, no 1-2-day dominance, sign positive
on >60% of clusters): **fixed tiny size, 0.25–0.5% of account per trade,
exploratory capital only.** Treat the live deployment as data
collection, not income. The point is to see whether the paper effect
survives slippage and execution friction, not to extract returns.

**Do NOT use Kelly sizing language or framing.** Kelly assumes the edge
is known; here the edge is at best a small noisy estimate from a
bootstrap CI that's wide by construction. "Fractional Kelly" still
imports the wrong premise. The right framing is "tiny exploratory
position size" — the dollar amount is justified by the question
("does the edge survive live friction?"), not by an edge estimate.

If/when Stage 3 confirms and the in-the-wild micro deployment also
shows positive expectancy net of slippage, sizing REMAINS tiny.
There is no point in this procedure where significant capital is
justified — the protocol is calibrated to detect "is there anything
here?" not "how big is the edge?"

## Framing — falsification vs premature monetization

Per Perplexity round 2 (May 1): the falsification protocol is
**not about discovering a profitable strategy.** It is about deciding
whether what's been built is *better than break-even enough to justify
any live deployment at all, and if so, at what tiny size.*

Acceptable outcomes, in expected-likelihood order:
1. **Most likely**: forward CI includes 0 or is dominated by 1-2
   outlier days → retire as production, keep as research artifact,
   free up bandwidth to hunt elsewhere. **This is a successful
   experiment.**
2. **Plausible**: forward CI excludes 0, mean diff +10 to +20pp, no
   single-day dominance → micro-scale live risk only. Edge is real
   but small and noisy.
3. **Unlikely**: forward CI excludes 0, mean diff >+20pp, sign
   consistent → still micro-scale; do not scale up. The discipline
   that produced the experiment did not produce a wider-than-expected
   edge; do not let result-stage exuberance erase that.

The point is to know whether what's been built is worth running at all.
Both tails ("this works" and "this doesn't") are valuable answers.
"Inconclusive" is also a valid answer — the staged design is built so
that inconclusive at Stage 1 ≠ inconclusive at Stage 3, but inconclusive
at Stage 3 means the edge is too small for retail-strategy n to detect
and the right move is to retire as production regardless.

## Spread gate — SHADOW MODE (May 2 2026)

Per cross-LLM round 3 consensus
(`docs/feedback/cross_llm_implementation_review_may01.md`), the spread
preflight gate runs in SHADOW MODE during the forward window. It does
NOT block fires. It logs the would-gate decision (alongside live
`spread_30m_mean`) to `structural_turns.spread_*` columns.

Why shadow not hard-block: 3/3 LLMs flagged tail-truncation bias as
the fatal flaw of hard-blocking. Actively gating high-spread fires
would remove them from the dataset, biasing any later regression of
P&L on spread toward "spread doesn't matter" via attenuation on the
truncated independent variable. Shadow mode preserves the full
spread distribution.

Implications for the bootstrap analysis:
- `paired_bootstrap_analysis.py` should report TWO PRIMARY CIs:
  - **PRIMARY-RAW**: gated vs random_minute_atm on ALL fires
    (current production behavior — single internally consistent cohort)
  - **PRIMARY-SHADOW-FILTERED**: same but restricted to fires with
    `would_gate_spread_block = 0` (post-hoc simulation of the spread
    gate without truncating the underlying spread distribution)
- Difference between the two CIs estimates the shadow gate's effect
- The Stage 3 verdict is on PRIMARY-RAW; PRIMARY-SHADOW-FILTERED is
  reported alongside as supporting context

If the shadow-filtered CI is materially better than raw → the spread
gate is worth promoting to a hard-block in a future iteration. If
the two CIs are similar → the in-sample Test #6 effect did not
replicate forward, and the spread gate is not adopted.

## Minimum detectable effect (MDE) expectations

Cluster-bootstrap on day clusters with day-level SD ≈ 30pp (in-sample):

| n clusters | MDE (80% power, α=0.05) |
|---|---|
| 15 | ~22pp |
| 20 | ~19pp |
| 25 | ~17pp |
| 30 | ~15pp |

Implications:
- Powered to detect ≥20–30pp true effects with high probability.
- Marginal power to detect 10–15pp effects — possible but unlikely.
- **Will not reliably detect <10pp effects** even at Stage 3 sample.

This is a hard limitation of retail-strategy n. The right response is
not "collect more data" (3+ months calendar time per stage) but
"accept that effects below 10pp are out of measurement reach and
treat anything in that range as effectively no edge."

## Initial result on the in-sample 27-fire dataset

For reference only — this is the data the gates were fit on, not
out-of-sample:

**PRIMARY (gated − random_minute_atm, timing alpha)**:
```
n fires: 27, n day clusters: 8
mean diff: +28.6pp
95% CI: [+3.8pp, +73.4pp]
14/27 fires gated > random
By direction: BEAR +32pp, BULL +24pp
```

**SECONDARY (gated − naive_open_atm, whole-package alpha)**:
```
n fires: 27, n day clusters: 8
mean diff: +54.1pp
95% CI: [+16.7pp, +107.9pp]
17/27 fires gated > naive_open_atm
```

Both CIs exclude 0 on the positive side in-sample. The +25pp gap
between the two means is contract/day selection alpha that's NOT pure
timing — useful color but not the headline number. The PRIMARY metric
is the timing-alpha CI.

**This does not validate the strategy** — gates were fit on this same
data per Apr 28 commit history. It shows the experimental setup
produces an interpretable result. The forward sample determines whether
the +28.6pp timing alpha holds out-of-sample.

The 4/21 day dominates both bootstrap means (+235pp primary diff vs +13
to +30pp on most other days). Out-of-sample data needs to either confirm
the effect on multiple days OR show the sample is one-event-driven.

## What gets logged passively (for post-experiment analysis)

The live worker also logs (without using as a gate):
- VIX1D and VIX9D prior-day close (regime context)
- regime (POS/NEG) at fire time
- ZGL relative position (`spot_minus_zgl`)
- AVWAP from prior session LOD
- P/C IV ratio at ATM ±5%

After the experiment delivers a verdict, these features can be regressed
against (gated_pnl − naive_pnl) to surface conditioning variables for the
next iteration.
