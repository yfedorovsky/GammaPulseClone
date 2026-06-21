---
title: "Dark-pool levels as S/R — findings (Direction-A)"
date: "2026-06-21"
status: "NOT WORTH ADDING. Lit control: DP showed NO incremental value over lit volume in this pilot; pilot signal was a price-path artifact. Calibrated, not a forever-falsification. NIA."
prereg: "docs/research/DARKPOOL_SR_PREREG.md"
harness: "scripts/darkpool_sr_backtest.py (--litcontrol), scripts/darkpool_lit_pull.py"
---

# VERDICT (2026-06-21): NOT WORTH ADDING — no incremental value over lit volume (this pilot)

**Calibration (matters):** this is a SMALL pilot (60 name-days, OPEX week, semis-only,
Nasdaq-lit-only). The decisive comparisons below were directionally clean without large n, so
the conclusion *"in this pilot, dark-pool levels did not demonstrate meaningful incremental
value over ordinary lit volume nodes"* is well-supported — and it's enough to say **don't add
it to alerts**. It is NOT a permanent falsification of the concept. The bar to revisit is now
explicit: a powered (lit + multi-week, non-OPEX, non-semis) test must show DP beats **LIT**
(not random), with a price path built INDEPENDENT of the dark tape.

The decisive **DP-vs-LIT control** ($7.11 Databento pull, lit prints 6/15-6/19) killed it:

| R | DP hold | LIT hold | RANDOM hold | DP-vs-LIT lift | CI95 | perm p |
|---|---|---|---|---|---|---|
| 0.3% | 0.630 | 0.647 | 0.652 | **-1.8pp** | [-7.2, +4.4] | 0.72 |
| 0.6% | 0.593 | 0.594 | 0.626 | **-0.1pp** | [-5.0, +6.9] | 0.53 |

1. **Redundant with lit:** 72% of dark top-levels coincide with a lit top-level; DP holds no
   better than LIT (CI includes 0). Dark-pool concentration adds nothing beyond ordinary volume.
2. **The pilot's +2-5pp was a PRICE-PATH ARTIFACT.** The pilot reconstructed the test-day path
   from the dark (TRF) tape itself, so the path was anchored at the dark levels -> inflated hold
   (~95% base). On a clean LIT-derived path the base drops to ~63% and the DP effect vanishes;
   **random levels hold as well or better than either volume type** (0.652 vs 0.630 at R=0.3%).
   On unbiased data, neither dark NOR lit volume levels beat random for S/R.

**Action: do NOT add DP levels to alerts (not even as context). Do NOT fund the powered pull —
there is nothing to power up.** The $7 lit control saved the $30-55 multi-week spend and a
false feature. Lesson: build the test-day price path from data INDEPENDENT of the levels being
tested (the level-construction was causal, but the path was not).

---
## (superseded) pilot findings — kept for the record

# Do dark-pool (TRF) volume levels act as S/R guardrails? — pilot

**Question.** When price later approaches a price level built from PRIOR days' dark-pool
(FINRA/Nasdaq TRF off-exchange) volume, does it reverse ("hold") more than at a
distance-matched random level?

**Data.** `data/darkpool_cache/*_2026-06-13_2026-06-20.parquet` — 20 semis/chokepoint names,
test days **6/16–6/18** (prior-day levels; OPEX Friday 6/19 NOT in the sample), 60 name-days,
TRF-only. RTH 1-min bars reconstructed from cleaned prints (size>0, ±15% price clip).

## Result (the R-sweep is the story)

| R (reversal/break threshold) | base (random) | DP | lift | day-clustered CI95 | perm p (1-sided) | LOO-min | verdict |
|---|---|---|---|---|---|---|---|
| **0.3% — PRE-REGISTERED** | 94.9% | 96.9% | +2.0pp | **[−0.1, +3.7] grazes 0** | 0.016 | +1.6pp | INCONCLUSIVE |
| 0.6% — post-hoc | 83.9% | 88.9% | +5.0pp | [+0.4, +8.9] excl 0 | 0.0014 | +4.6pp | signal |
| 1.0% — post-hoc | 75.0% | 80.2% | +5.3pp | [−0.5, +9.7] grazes 0 | 0.0052 | +4.5pp | INCONCLUSIVE |

**Consistent across all R:** the lift is **positive** (DP holds more than random), the
**permutation null is significant** (p ≤ 0.016), and it's **LOO-robust** (no single name drives
it; min lift excluding any one name stays positive). Spread evenly across the 3 test days — not
a single-day/OPEX-Friday artifact.

**But the day-clustered bootstrap CI — the stricter, primary test per the pre-reg — only cleanly
excludes 0 at R=0.6%.** At the *pre-registered* R=0.3% it grazes zero.

## Verdict: SUGGESTIVE, NOT CONFIRMED

By my own pre-registration, **R=0.3% is INCONCLUSIVE** (CI grazes 0). The clean signal at
R=0.6% is **post-hoc** (garden-of-forking-paths) — hypothesis-*generating*, not confirmation.
That said, this is the **most promising lead of the session**: a consistently positive,
permutation-significant, LOO-robust effect that strengthens (in magnitude *and* dynamic range)
once the metric isn't ceiling-pinned. It earns a powered follow-up — but three things must be
true before it's real:

## The decisive gaps (why it is NOT yet an edge)
1. **No lit-POC control (THE blocker).** The pilot shows DP beats *random* — but a *lit*
   high-volume node (VWAP/POC) would very likely also beat random. **Without comparing DP levels
   to lit-volume levels of equal prominence, we cannot say the effect is dark-pool-*specific*
   rather than "any volume node is S/R."** This is the single most important next test and it
   needs lit prints (more Databento spend).
2. **Thin + OPEX-week + semis-only.** 60 name-days over 3 days of one OPEX week, all
   semiconductors. Needs more weeks across non-OPEX periods + a non-semis basket.
3. **Ceiling effect / R-sensitivity.** The touch→barrier metric is dominated by generic
   intraday mean-reversion (base hold ~85–95%); the DP effect is a small increment on top, and
   it only clears the CI at one R. A continuous **penetration-depth** metric (how far price
   pierces the level before reversing) would have better dynamic range than the binary hold/break.

## Powered-test spec (pre-register before running)
- **Add the lit-POC control** (DP vs lit volume nodes of matched prominence) — the decisive arm.
- Pull **≥6–8 weeks** of non-OPEX data for the basket + a **non-semis** basket (~$7/week each).
- Switch primary metric to **penetration depth** (continuous), pre-register the barrier grid with
  multiplicity correction, keep prior-day levels + day-clustered CI + permutation null.
- Decision rule unchanged: edge requires CI-excludes-0 **vs the LIT control**, not just random.

Re-run: `python scripts/darkpool_sr_backtest.py [--R 0.006]`. NIA — structure detects context;
this is a suggestive pilot, not a validated edge.
