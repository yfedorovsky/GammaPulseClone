# Implementation Review — Closing the May 1 Audit Cycle

For Perplexity and Gemini Pro. Round 3.

You both gave round-2 feedback that converged on a 6-item post-audit
checklist. I've now shipped all 6 items in two commits (`9534844` and
`3ed9eb3`). Before the forward window starts running, I want a final
adversarial pass on what was implemented. The window then runs for
4-6 weeks of calendar time with no further parameter changes.

This doc has three parts:
1. Brief summary of what shipped, item by item
2. Five specific implementation questions where I'd like sharper input
3. One open structural question (Q5) where I'm uncertain whether the
   design itself is right

If you only have time for one section, do (2). If you only have time
for one question in (2), do Q1.

---

## Part 1 — What shipped

### Item 1: Spread preflight gate — `server/structural_turn.py`
- New `_gate_spread_regime(ticker, ts, spread_30m_mean)`
- Static p90 lookup from `docs/research/background_distributions.md`,
  per (ticker × TOD bucket). Frozen May 1.
- Bypass branches: feed=None (dormant), <=0 (measurement error),
  off-hours, ticker-not-calibrated (IWM/SPX → no historical sample yet)
- Active branch: 30m-trailing mean > p90 → block fire with reason string
  citing Test #6's -14%/30%WR finding
- **Live spread feed wiring is NOT in the live worker yet** — backlog'd
  as a separate ~2-3hr Tradier `quotes_full()` extension. Until then
  the gate is dormant on production and fires proceed exactly as
  current frozen v1.

### Item 2: `FALSIFICATION_PROTOCOL.md` updated
- Staged stopping rule: Stage 1 (≥30 fires AND ≥15 day clusters) →
  Stage 2 (≥50 AND ≥20) → Stage 3 (≥75-100 AND ≥25)
- Stage 1 = check, Stage 2 = decision, Stage 3 = optional confirmation
- Sizing: stripped Kelly entirely, replaced with "fixed tiny size
  0.25-0.5%, exploratory capital only"
- Added MDE table: powered for ≥20-30pp, marginal for 10-15pp,
  not powered for <10pp
- Added "falsification vs premature monetization" framing per
  Perplexity round 2

### Item 3: Iron condor passive logging — `server/paired_trades.py`
- New `iron_condor_logs` table, UNIQUE(fire_id)
- For every gated fire, log credit (mid) of two pre-committed IC
  structures at fire_hhmm AND at 15:59:
  - **ATM IC**: short C/P at spot-rounded strike, long wings ±wing
  - **OTM IC**: short C at king (rounded), short P at floor (rounded),
    long wings ±wing
- Wing widths frozen: $5 SPY/QQQ/IWM, $25 SPX
- Falls back to spot ± wing for OTM if king/floor missing
- Wired into `run_eod` orchestrator with isolation (IC failure ≠
  long-premium failure)
- No analysis logic until forward window completes; per BACKLOG.md
  decision tree (boundary audit must pass first AND IC must win on
  different days than long-premium to justify pivot)

### Item 4: `V2_DETECTOR_SPEC.md` updated (in commit 9534844)
- Audit results table mapping pre-committed thresholds to actuals
- Discipline note: did not relax d=0.5 threshold even at d=0.49
- What shipped (spread gate, IC logging) vs what's NOT shipping

### Item 5: `BACKLOG.md` updated (in commit 9534844)
- Added: live spread feed wiring as PREREQUISITE for spread gate
- Added: GEX boundary-behavior audit (separate from credit-spread MVP)
- Added: GEX-as-spatial-boundary credit-spread variant (full pivot
  conditions documented)

### Item 6: `LOGISTIC_REGRESSION_SPEC.md` (new)
- Pre-registered: target = `win_flag`, predictors fixed
  (spread_30m_mean_log, vix1d, rv_30m, volume_z, aggflow_log)
- Significance threshold pre-committed: p<0.05 on β₁(spread)
- HC1 robust SE clustered by trading day
- One run, after Stage 2 stops; descriptive only
- Decision tree pre-committed: spread gate stays in production
  regardless of regression outcome

---

## Part 2 — Five implementation questions

### Q1. Is the staged stopping rule (30/15 → 50/20 → 75-100/25) actually well-designed, or am I sequential-testing without correction?

The protocol says "Stage 1 = check, Stage 2 = decision, Stage 3 =
confirmation." But each stage involves running a cluster-bootstrap
on the accumulated data and making a continue/stop decision based
on the CI. That's a sequential testing procedure with three looks at
the data — and the stage CIs are not adjusted for that.

Two specific concerns:

(a) **Type I inflation at Stage 1.** Stage 1 says "retire if upper
bound < +5pp." Suppose true effect is +5pp exactly. There's some
probability the Stage 1 CI upper bound is < +5pp by chance. We
retire. If we'd waited to Stage 2 we wouldn't have. Is the +5pp
threshold strict enough that this matters, or is it conservative
enough that it doesn't?

(b) **Multiple-look penalty at Stage 2.** If we stop at Stage 1 OR
Stage 2 with a positive verdict, the unconditional false-positive
rate is higher than the per-stage 5%. Should the Stage 2 CI use
α=0.025 (Pocock-style) or α=0.04 (O'Brien-Fleming-style) instead of
α=0.05? Does it matter at this n?

I'm willing to accept "the Type I inflation is small at this n
and the cost of stopping early is low; don't bother adjusting." But
I want that to be the explicit answer, not the silent assumption.

### Q2. Iron condor MVP — is the design "wrong" in a way that pre-commits the experiment to fail?

The OTM IC uses king as short-call strike and floor as short-put
strike, both rounded to the nearest valid strike. Wing width is $5
($25 for SPX). Two specific concerns:

(a) **Wing width might be too narrow on high-vol days.** $5 SPY wing
at 0DTE during a vol expansion gives a max-loss of $5 - credit, but
the credit might be $4+ on those days, so the structure becomes
near-zero-EV. Is $5 the wrong choice? Should it scale with VIX1D?

(b) **King and floor are computed by the live worker at fire time
from THAT minute's GEX snapshot.** They're not static day-level
values. So short-call strike picks the king AT THAT MOMENT, which
might be different from the morning king. Is this fine (the gate
fired BECAUSE of that moment's structure, so we want that moment's
boundary), or should we use the morning's king?

Pre-committed; not changing without strong argument. But I'd rather
pre-commit something defensible than something mechanical-looking.

### Q3. Spread gate dormancy — is "ship it dormant, wire later" actually safe?

The gate is implemented but inactive (no live spread feed). When
the live wiring lands in week 2-3 of the forward window, the gate
becomes active mid-experiment.

Two ways to handle this:

(a) **Ship dormant now, activate when wired.** What I did. Forward
window has two regimes (no-gate-applied, gate-applied) and the
final analysis has to acknowledge that. Cleaner code. But the
in-stage CIs change meaning when the gate flips on.

(b) **Hold the entire forward window until wiring is done.** Delays
the experiment 2-3 hours of work + however long it takes me to
prioritize it (could be a week). But the window is then internally
consistent.

I picked (a) on the assumption that gate activation will block
≤10-15% of fires (Test #6's HIGH-spread frequency was ~10%). So
the regime change is small relative to the staged sample. Is this
actually defensible, or am I just optimizing for shipping speed
over experimental cleanliness?

### Q4. Logistic regression spec — is "run only after Stage 2 stopping" the right gate, or should it be Stage 3?

The spec says: run the regression once Stage 2 stopping is met
(≥50 fires AND ≥20 day clusters). It's described as "descriptive,"
not gate-deciding.

Concern: Stage 2 is the *decision* stage. Running the regression
at Stage 2 stopping means the regression result might inform whether
to continue to Stage 3 or to size up. Even if the spec says "the
spread gate stays in production regardless of regression outcome,"
in practice if β₁(spread) shows wrong-sign or tiny coefficient I'll
notice and behave differently.

Should the regression be deferred to AFTER Stage 3 (or after the
whole window completes), so it's purely retrospective and can't
contaminate the Stage 2 → Stage 3 decision?

### Q5. Did I miss anything on the 6-item list, or was the list itself incomplete?

The list came from synthesizing Perplexity round 2 + Gemini round 2 +
ChatGPT into a 6-bullet checklist. Reviewing the implementation, two
things I notice were NOT on the list:

(a) **No update to the live worker to passively log `spread_30m_mean`
even when the gate isn't filtering.** Once Tradier wiring lands, we
should also pre-populate the spread column on existing fires so the
logistic regression has spread as a predictor. Without this, the
regression's β₁(spread) is estimated only on fires WHERE THE GATE
DIDN'T BLOCK (tail-truncated). Is this a real bias, and if so, do I
need to log spread separately from gating on it?

(b) **No verification that the IC mid pull works against ThetaData
for the historical 27-fire sample.** I implemented it but haven't
backfilled the existing 27 fires through it. Should I do that as
sanity-check (cheap — same code path the forward window uses), or
treat the in-sample IC mids as "would have been" data and skip?

---

## Part 3 — One open structural question

### Q6. (open) The spread gate is dormant. The IC logging requires forward fires. The logistic regression doesn't run for 4-8 weeks. The "ship it" event for any of these is the forward window cohort accruing.

Steelman the alternative: don't ship Items 1/3/6 at all. Just run
the forward window with v1-frozen, get a clean N=50 cluster-bootstrap
verdict, and decide what to do post-experiment based on that single
result.

The argument FOR what I did: pre-commit the methodology (gate
threshold, IC structures, regression spec) so the post-experiment
analysis isn't post-hoc-rationalized. Pre-committed external thresholds
are the whole defense against researcher-degrees-of-freedom.

The argument AGAINST: the gate is dormant; the IC logging isn't
analyzed; the regression doesn't run. None of it touches the actual
forward verdict. I've spent 2-3 hours producing infrastructure that
sits idle for 4-6 weeks then gets used once.

Is this right? Or am I overengineering a forward window that's
simple by design (one bootstrap, one CI, one decision)?

---

## What I'd find most useful

Rank: Q1 (sequential testing) > Q5a (spread bias from tail truncation)
> Q2 (IC design) > Q6 (overengineering steelman) > Q3 (dormant gate) >
Q4 (regression timing) > Q5b (backfill IC mids).

Q1 and Q5a are the ones I genuinely don't have an answer for. The
others I have priors on but want them stress-tested.

If you push back on Q6 hard ("yes, you overbuilt"), I'm willing to
revert Items 1/3/6 and ship just the FALSIFICATION_PROTOCOL update
+ run the window. But the bar is high — I need a concrete
methodological argument, not just "less code is better."
