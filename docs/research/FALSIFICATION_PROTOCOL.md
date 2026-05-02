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

## Stopping rule (staged — May 1 2026 revision)

Earlier rule was "≥30 fires AND ≥5 day clusters." After the May 1 audit
cycle and 5-LLM critique converged on **at least 15 day clusters as the
absolute floor**, with explicit consensus that 5 clusters lets bootstrap
intervals look more stable than they are. ChatGPT's MDE math applied to
the in-sample day-level SD (~30pp) gives MDE ≈ 2.8 × 30pp / √n_clusters,
so 15 clusters → ~22pp MDE, 20 → ~19pp, 25 → ~17pp. The protocol is
**powered for ≥20–30pp true effects and will NOT detect anything <10pp**
even with full sample. That's an accepted limitation — there is no path
to "small effect" detection at retail-strategy n-availability.

The window proceeds in three stages. Each stage gates progression to
the next; do not act on intermediate CIs.

**Stage 1 — Initial (≥30 fires AND ≥15 day clusters)**:
Run a first cluster-bootstrap on the PRIMARY metric. Treat as a check on
"is the in-sample +28.6pp claim collapsing immediately?" — not a verdict.
- CI strongly negative or 95% CI upper bound < +5pp → retire as
  production immediately; document the result.
- Otherwise continue to Stage 2.

**Stage 2 — Decision (≥50 fires AND ≥20 day clusters)**:
This is the primary verdict point.
- 95% CI excludes 0 on positive side AND day-level effect is not
  carried by 1–2 outlier sessions AND sign of paired-diff is consistent
  across the majority of clusters → move to Stage 3 with optional micro
  live deployment (see sizing below).
- CI excludes 0 but the result is dominated by a single outlier day →
  not falsified, not green-lit; continue paper-only to Stage 3.
- CI includes 0 → retire as production. Keep code as research artifact.

**Stage 3 — Validation (≥75–100 fires AND ≥25 day clusters)**:
Optional confirmatory window. Only worth running if Stage 2 cleared.
Tightens the CI and reduces the chance the Stage 2 result was
borderline noise. If Stage 3 CI also excludes 0 with the same effect
sign and no single-day dominance → "small noisy edge confirmed at
hobby scale," which is the best plausible outcome of this whole exercise
per the FINAL_INTERPRETATION.md honest-expected-outcome section.

The verdict is on the **PRIMARY control** (gated vs random_minute_atm).
The SECONDARY control (gated vs naive_open_atm) is reported alongside
but does NOT determine the verdict. If gated > naive_open_atm but
gated ≈ random_minute_atm, the "edge" is contract/day selection, not
structural detection — that's a different and weaker claim.

## Sizing (revised — May 1 2026)

**Paper-only through Stage 1 and Stage 2.** Do not allocate live capital
on intermediate bootstrap results.

If Stage 2 cleared (CI excludes 0, no single-day dominance, sign
consistent): **fixed tiny size, 0.25–0.5% of account per trade,
exploratory capital only.** Treat the live deployment as data
collection, not income. The point is to see whether the paper effect
survives slippage and execution friction, not to extract returns.

**Do NOT use Kelly sizing language or framing.** Kelly assumes the edge
is known; here the edge is at best a small noisy estimate from a
bootstrap CI that's wide by construction. "Fractional Kelly" still
imports the wrong premise. The right framing is "tiny exploratory
position size" — the dollar amount is justified by the question
("does the edge survive live friction?"), not by an edge estimate.

If/when Stage 3 confirms, sizing remains tiny. There is no point in
the procedure where significant capital is justified.

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
