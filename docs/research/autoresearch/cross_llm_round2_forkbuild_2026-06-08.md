# Cross-LLM Round 2A — Fork-vs-Build + Validation-Gate Spec Review (AutoResearch)
**Date:** 2026-06-08 · Perplexity · Gemini Deep Research · Grok · ChatGPT (adversarial)

**Framing (important):** Round 1 already settled the *strategy* (build a research
OS + validation engine over our own data, not a public-scrape alpha factory; loop
velocity = retirement timing). **A dedicated build session is ALREADY constructing
Phase 0 + Phase 1 in the background.** So this round is a **parallel pressure-test
to course-correct the in-flight work** — not a go/no-go. We want: (a) confirm or
refute the fork-vs-build call, (b) lock the exact statistical thresholds, (c) catch
anything in the Phase 0/1 design that's wrong or missing before it hardens.

Paste SHARED CONTEXT into each, then the tailored prompt. Collect 4 → synthesize
(template at bottom). A slot is reserved for **Round 2B** (re-run grounded in real
Phase 0 decay numbers once they exist).

---

## 📋 SHARED CONTEXT (paste into all 4 first)

I run a live options-flow trading system ("GammaPulse"). I am NOW building an
**offline AutoResearch loop** on top of it. Round 1 (4-LLM) concluded: build the
research OS + a rigorous validation engine over my OWN proprietary data
(`alert_outcomes.db` + ThetaData replay); mine internal data first; skip X
entirely; the durable edge is *retirement/adaptation timing*, not public-source
discovery. A build session is already implementing Phase 0 and Phase 1.

**What exists / decisions already made:**
- `alert_outcomes.db`: every fired alert logged with fire-time context (regime,
  VIX, GEX, IVR, earnings proximity, opening-vs-closing OI cohort) + backfilled
  outcomes (1h/EOD/next-day WIN/LOSS/FLAT verdict, spot & option MFE/MAE).
  Sample sizes are **n in the hundreds per signal-type cohort**, fewer once split
  by regime. Best discretionary grade "SOE A" = 14.9% WR (n=134); breakeven =
  22.7% at 3.4× R:R.
- **Phase 0 (building now):** decay/retirement monitor — rolling 60d & 90d win
  rate per cohort, Wilson + Clopper-Pearson 95% CIs, verdict
  HEALTHY/WATCH/RETIRE_CANDIDATE; retire trigger = CI lower bound < breakeven.
  Read-only, no live-scoring change.
- **Phase 1 (building now):** the validation/deflation engine — DSR + PBO + CPCV
  (purged+embargoed) + MinTRL/MinBTL + Hansen SPA vs the SOE-A baseline + a
  **global N-trials counter**; economic null (net of realistic slippage);
  shadow→human→ship at n≥200; auto-retire when rolling CI lower bound < breakeven.
  Libs intended: `pypbo`, `mlfinlab`, `arch.bootstrap.SPA`, MLflow, Prefect.
- **Fork-vs-build call made:** build thin from scratch over our substrate; do NOT
  fork **RD-Agent** wholesale (it's Qlib/equity-factor, LLM-knowledge-only,
  validates with IC-dedup only). Borrow ideas: RD-Agent research/dev/feedback
  split + knowledge forest; **AlphaAgent's 3 gates** (AST-novelty, hypothesis-
  factor alignment, complexity); **KX**'s governance/auditability/retirement
  framing. (RD-Agent = Microsoft, MIT. KX Trading Signal Agents = GTC 2026
  enterprise. NeMo Agent Toolkit = orchestration plumbing.)
- **Hard rules:** offline only (LLM never in real-time scoring — protects a
  sub-30s OPRA latency edge); human gate before anything live; no X scraping ever;
  external (arXiv/SSRN/Fed/EDGAR) deferred to a later phase.

---

## 🔬 THE QUESTIONS (for all 4)

**1. Fork-vs-build — confirm or refute.** Given RD-Agent is MIT but Qlib/equity
and weakly-validated, is "build thin over our own substrate, borrow ideas" right?
Or is there specific RD-Agent / AlphaAgent / `mlfinlab` code worth *vendoring
verbatim* (e.g. AST-novelty gate, knowledge-forest store, CPCV implementation,
bandit scheduler) vs reimplementing? Name the modules.

**2. Lock the exact thresholds for OUR situation (n in the hundreds,
non-stationary intraday options, daily-resolution outcomes):**
- **DSR:** confidence cutoff (0.95?), and exactly how to compute the expected-max-
  Sharpe term `E[max SR | N]` for a *continuously running* loop.
- **PBO:** the correct reject cutoff — Round 1 sources gave both **0.05** and
  **0.50**. Which, and why?
- **CPCV:** concrete config for our data — number of groups N, test groups k,
  embargo %, given ~hundreds of obs and overlapping hold horizons (1h/EOD/next-day).
- **MinTRL / MinBTL:** realistic required-N for detecting a 5pp WR improvement over
  22.7% breakeven at our skew/kurtosis — is n-in-hundreds even enough, per cohort?
- **Hansen SPA:** the right loss differential to bootstrap when comparing a
  candidate to the SOE-A baseline (per-trade returns? MAE? economic PnL?).

**3. The global N-trials counter — practical seeding.** We've already run dozens
of ad-hoc backtests + multiple cross-LLM "search" rounds historically. How should
N be seeded so DSR isn't falsely inflated, without making N so large the gate is
impossible? Does prior informal search count? How do real shops bound this?

**4. Power reality check.** After honest deflation, how many *concurrent*
hypotheses can a solo operator realistically afford to test per quarter against an
n-hundreds DB before nothing can clear? Is Phase 2 internal-mining even powered, or
must we pool across cohorts / use hierarchical/Bayesian shrinkage instead of
per-cohort frequentist gates?

**5. Phase 0 decay-monitor design — is the rule right?** Rolling 60/90d windows;
Wilson vs Clopper-Pearson vs Jeffreys for a *retirement* decision; trigger =
lower-bound < breakeven. Does this retire too eagerly (noise) or too late? Since we
re-check the same signal continuously, do we need **sequential-testing / always-
valid confidence sequences** (Howard et al.) instead of fixed-n CIs? What's the
right retirement trigger a desk actually uses?

**6. What's wrong or missing in the Phase 0/1 plan** that we should correct
mid-build?

---

## 🎯 TAILORED PER-LLM PROMPTS

### → PERPLEXITY (tools/libs to vendor vs reimplement; exact configs)
"Answer Q1, Q2, Q6 with current (2026) specifics. For each statistical component
(DSR, PBO, CPCV, MinTRL, SPA), name the exact maintained Python library + the
specific function/class + a sane default config for n-in-hundreds options data,
and flag any that are unmaintained or wrong for non-stationary intraday data.
For fork-vs-build, identify which exact RD-Agent / AlphaAgent / mlfinlab modules
are worth vendoring vs reimplementing, with repo paths/licenses. End with the 3
highest-confidence corrections to apply to the in-flight Phase 0/1 build."

### → GEMINI DEEP RESEARCH (the statistics — thresholds, power, seeding, sequential)
"Deep-research Q2, Q3, Q4, Q5. I need rigorous, quantitative answers: the correct
DSR confidence and E[max SR|N] computation for a continuous loop; the correct PBO
cutoff (resolve 0.05 vs 0.50); CPCV config (N, k, embargo) for ~hundreds of obs
with overlapping labels; realistic MinTRL/MinBTL for a 5pp edge over 22.7%
breakeven given option-return skew/kurtosis; how to seed and bound the global
N-trials counter under prior informal search; whether per-cohort frequentist gates
are even powered at n-in-hundreds or whether hierarchical/Bayesian shrinkage is
required; and whether the decay monitor needs always-valid confidence sequences
(Howard/Ramdas) instead of fixed-n CIs for continuous re-checking. Give concrete
numbers and a corrected fitness-gate spec."

### → GROK (practitioner — what desks actually do, what breaks mid-build)
"Q1, Q4, Q5, Q6 from a practitioner angle. Do real quant/options desks actually
fork frameworks like RD-Agent, or build thin and borrow ideas? What retirement
trigger do live desks actually use to kill a decaying signal (and how do they avoid
killing good signals on a noise streak)? At n-in-hundreds with non-stationary
options flow, what's the realistic number of hypotheses worth testing, and what
practical mistakes break these loops mid-build? Be blunt about what in our Phase
0/1 plan is over-engineered vs under-built."

### → CHATGPT (adversarial — attack the gate itself)
"Be my adversary. Attack the validation gate we're building, not the idea. Steelman
that DSR/PBO/CPCV/SPA is **pseudo-rigor on n-in-hundreds, non-stationary, overlapping
options outcomes** — that purged CV can't manufacture statistical power that isn't
there; that a correctly-seeded global N-trials counter makes the gate so strict
nothing ever clears (so the loop produces nothing, which is its own failure); that
the decay monitor will retire good signals on ordinary variance; and that 'shadow at
n≥200' is theatre if the underlying cohorts are too small/dependent. Then — ONLY
where a defensible version survives — specify the *minimal* gate + decay rule that is
actually honest at our sample sizes, and exactly where we should accept Bayesian/
hierarchical methods instead of frequentist deflation."

---

## 🧩 SYNTHESIS TEMPLATE (after collecting 4)
1. **Fork-vs-build verdict** — confirmed, or specific modules to vendor instead.
2. **Locked thresholds** — the agreed DSR cutoff, PBO cutoff, CPCV config,
   MinTRL/N, SPA loss differential, N-trials seeding rule.
3. **Power verdict** — per-cohort frequentist vs pooled/hierarchical/Bayesian.
4. **Decay-rule correction** — window, CI type, trigger, sequential correction.
5. **Mid-build corrections** — the concrete list to hand the build session.
6. **Honest verdict** — does the gate have real teeth at our sample sizes, or do
   we need to lower ambition (broad cohorts only) to stay honest?

> **Round 2B slot (fill later):** once Phase 0 emits a real signal-health table,
> append the actual per-cohort decay numbers here and re-run Q5 grounded in them.

> Run-state: re-verify every named library/paper/threshold before acting. Bias
> toward the skeptic (ChatGPT) on whether n-in-hundreds can gate anything.

*Kit prepared 2026-06-08. Companion to SYNTHESIS.md + PROJECT.md. Build session is
live on `feature/autoresearch-loop` (Phase 0/1 in flight).*
