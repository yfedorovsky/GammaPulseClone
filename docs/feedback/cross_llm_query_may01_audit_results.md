# Cross-LLM Critique — Post-Audit Strategy Decision

Update on a 0DTE long-premium structural-turn detector (SPY/QQQ/IWM/SPX,
n=27 in-sample fires from Apr 13–24 2026). Prior Perplexity exchanges
established that the +21% in-sample expectancy was contaminated (gate
constants were first introduced *after* the backtest data existed),
and laid out a falsification protocol: paper-trade live forward fires
with three controls (gated, random_minute_atm, naive_open_atm),
cluster-bootstrap by day, stopping rule of ≥30 paired observations
across ≥5 distinct day clusters.

In the meantime, acquired 6 months of Databento US Equities Mini MBP-1
data on SPY+QQQ (multi-venue aggregated NBBO at tick level, 1.3 billion
events, 125 trading days, 2025-10-30 → 2026-04-30, $0 net cost via the
$125 new-account credit). Ran 8 audits on this data tonight. Looking
for outside critique on the verdicts and the proposed next steps.

## What the audits returned

| # | Test | Verdict | Key number |
|---|---|---|---|
| Gate 8 | Lee-Ready vs minute-bar tick proxy | TIE / BAR_WINS | LR corr +0.30 vs bar +0.33 |
| 1 | Microstructure profile of fires vs same-day random minutes | FAIL | Largest Cohen's d = 0.49 (volume), all others < 0.4 |
| 2 | OFI predictive power on raw tape (Cont 2014 replication) | FAIL | Max R² = 0.0002 across 6 (ticker × horizon) cells, n=44k each |
| 3 | VIX1D quartile vs day-microstructure (K-W tests) | PASS | 12 of 16 (feature × ticker) tests p<0.05 |
| 4 | Background distributions (percentile lookup) | OK | (No verdict — provides v2 thresholds if any are built) |
| 5 | Trade-size cohort CVD correlation with outcomes | MIXED | small +0.32, medium +0.23, large +0.07 |
| 6 | Spread regime (high-spread vs normal-spread fires) | PASS | Normal-spread +63% / 40% WR; HIGH-spread −14% / 30% WR; **77pp difference** |
| 7 | SPY/QQQ minute-OFI lead-lag | FAIL | Lag-0 corr +0.36 dwarfs all other lags (~0) |

Pre-committed decision tree (`docs/research/V2_DETECTOR_SPEC.md`,
written before audits ran): if Test #1 FAILS → "RETIRE strategy
framework, do not build v2." Test #1 returned FAIL with d=0.49 (just
under the 0.5 medium-effect threshold), so the spec fires the RETIRE
branch.

## Current paired-trade falsification result (in-sample, 27 fires, 8 day clusters)

```
PRIMARY (gated − random_minute_atm, isolates timing alpha):
  mean diff: +28.6pp
  95% CI:    [+3.8pp, +73.4pp]   ← excludes 0 but lower bound is small
  14/27 fires gated > random
  By direction: BEAR +32pp, BULL +24pp
```

The 4/21 day contributes most of the mean (+235pp diff vs +0 to +30pp
on most other days).

## Proposed action plan

1. **Don't build v2.** Test #1 FAIL plus Test #2 FAIL (OFI predictive
   R²=0.0002, vs literature 0.05-0.15) plus Gate 8 TIE means three
   separate v2-spending paths are all dead.

2. **One exception**: add a single preflight gate to v1, "if 30-min
   trailing mean spread > day p90, do not fire." Single line in code,
   theoretically grounded (wide spread = adverse cost of round-trip on
   0DTE), empirically the largest single effect we measured (77pp).
   Test #6 ran on the 17 SPY+QQQ fires; the effect is large but n is
   small.

3. **Forward paper-trade window**: 30+ paired observations across 5+
   day clusters. paired_trades.db captures per-fire gated +
   random_minute_atm + naive_open_atm. Cluster-bootstrap on (gated −
   random_minute_atm). If forward CI excludes 0 positive AND not
   carried by 1-2 outlier days, real edge. Otherwise retire.

4. **Position sizing**: paper-only until forward CI delivers. If
   eventually live, eighth-Kelly max — the forward CI's lower bound
   even in the in-sample case was just +3.8pp.

5. **No more in-sample analysis**. Calendar time is the only
   information path forward.

## Where I want pushback

**Q1. Is Test #1 FAIL actually decisive?** d=0.49 on volume is right at
the boundary. With n=17 fires and 170 random samples, statistical power
is limited. Could a more sensitive test (different feature set, sub-
minute granularity, or different baseline) reveal microstructure
distinctiveness that this one missed?

**Q2. Test #1 FAIL says "no microstructure-distinctive moments" but
Test #6 PASS says "spread differentiates fire outcomes." How to
reconcile?** My current read: Test #1 measures *whether fires happen
at distinctive moments*; Test #6 measures *whether fires that happen
during high-spread underperform*. Different questions. Test #1 says
gates fire somewhat indiscriminately; Test #6 says one specific filter
catches most of the bad fires. Coherent or contradictory?

**Q3. OFI R² = 0.0002 vs literature 0.05-0.15.** Cont/Kukanov/Stoikov
2014 was 11 years ago. Is the signal arbitraged out on liquid index
ETFs by 2025-26? Or does this suggest something specific about my
sample / methodology / regime? Anything about the test design that
might be hiding a real signal?

**Q4. The 77pp spread regime effect (Test #6) — is this real edge or
selection artifact?** 10 of 17 fires occurred during high-spread
conditions. Maybe the gates literally fire more often during stress
(high spread = low confidence dealer market = strong directional
imbalance more likely to reach a structural level), and during stress
the trade is just bad regardless. If true, the spread gate doesn't add
information — it just kills one specific tail outcome that happens to
be in the "high spread" bucket. How would you test the difference
between "spread gate adds information" vs "spread is a noisy proxy
for general stress that's already captured elsewhere"?

**Q5. Sizing decision before forward result.** Three options on the
table: (a) paper-only for 4-6 weeks, (b) eighth-Kelly live in parallel
with paper, (c) live but BEAR-disabled (BULL had higher in-sample WR).
What's the rigorous answer? My gut says (a), but I'm aware that
"paper trades" famously have more discipline than real trades, so
forward paper-trade results can overstate live edge.

**Q6. What's the right minimum n for the forward stopping rule?**
Currently set to 30+ paired observations across 5+ days (Perplexity's
recommendation). Is that defensible given the right-skewed P&L
distribution and the fact that day-clusters are the unit of
independence (so n=30 fires across 5 days is effectively n=5 for
inference purposes)? Should we be aiming for 50+ fires or 10+ days as
the actual stopping condition?

**Q7. The painful question.** Given the in-sample CI lower bound on
timing alpha is +3.8pp — which is barely above noise — and given the
paired-trade design measures the *narrowest possible* version of the
edge (timing only, not direction selection or contract pick), is
there any reasonable scenario in which the forward result returns a
verdict large enough to justify shipping live with significant size?
Or am I in the position of running an experiment that even in its
best plausible outcome shows "tiny edge with wide CI"?

---

**TL;DR**: 8 audits returned 3 PASS / 5 FAIL or MIXED. Decision tree
fires RETIRE branch. One exception (spread preflight gate) is
theoretically grounded and empirically large. Forward paper-trade
window is the only information path forward. Want pushback on whether
the audit verdicts are right, whether to add the spread gate now or
later, and whether the experimental design is even capable of
returning a useful verdict given the small in-sample effect.
