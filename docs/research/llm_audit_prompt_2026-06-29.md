# 4-LLM System Audit Prompt — 2026-06-29

**Purpose:** External cross-LLM audit of GammaPulse. Paste verbatim into **Gemini, ChatGPT,
Perplexity, Grok** (deep-research / web-enabled modes), then bring all 4 back for the
cross-LLM synthesis (same workflow as the prior 4-LLM audits).

**Design note:** the prompt front-loads the *edge verdict + falsified hypotheses* on purpose,
so the LLMs don't burn the response re-suggesting "follow the smart-money flow" / "build a
regime model" (already falsified). It forces them onto the real frontier: is a context-engine
+ risk-mgmt + latency stack the right game, or should the operator narrow to the ~10 names
where edge exists, or change instruments/timeframe entirely.

**Operator's 4 questions:** (1) reacting fast enough to remove bias & flip direction;
(2) can a retail setup predict from multi-factor (rotation/politics/innovation/supply-demand);
(3) efficiency vs Jane Street/Citadel — *should* a solo retail trader even try; (4) what CAN
improve WR/performance.

**NEXT STEP after results arrive:** cross-LLM synthesis → agreement (high-confidence) vs
divergence (open questions) → concrete this-week action list against the codebase.

---

```
You are a brutally honest senior quantitative trading strategist and market-microstructure
expert. I am a SOLO RETAIL options trader auditing my own system. I do not want validation,
encouragement, or generic advice. I want you to challenge my premises, find my blind spots,
and give falsifiable, prioritized recommendations. Use your research/web tools to ground
your answer in current market structure and recent developments. If I am asking the wrong
questions, tell me.

═══════════════════════════════════════════════════════════════════════
PART 1 — THE SYSTEM (be grounded; the system is real and described accurately)
═══════════════════════════════════════════════════════════════════════
"GammaPulse" — a self-built live options-flow + gamma-exposure (GEX) CONTEXT engine for
discretionary options trading. Stack: Python/FastAPI, ~20 asyncio detector loops, single-
writer SQLite, React dashboard, Telegram alerts.

DATA: Tradier (equity/option quotes + chains), ThetaData (real-time OPRA options TICK stream,
PRO tier — every option trade with NBBO side-classification, sub-second). ~494-name scanned
universe (semis, AI-infra, mega-cap tech, healthcare, energy, plus thematic adds). NO co-
location, NO direct exchange feeds, retail-grade latency (seconds, not microseconds).

WHAT IT COMPUTES: per-strike net dealer GEX/VEX, gamma king/floor/ceiling/zero-gamma-flip
levels, positive- vs negative-gamma regime, relative-strength scores, sector/industry rotation
+ a cap-weighted GICS sector-ETF RS board, IV percentile, realized vol, and a real-time
OPRA-tick "cluster" flow detector (N option legs same strike/expiry/direction in 60s).

KEY DETECTORS (with honest status from my own backtesting):
- INFORMED CLUSTER flow (LIVE, the validated edge): 3+ strikes same exp/direction; ~89% hit
  rate at the cluster threshold in a narrow set of liquid AI/semis names.
- SOE (8-factor GEX-quality directional scorer): DEMOTED to dashboard-only — 37.7% win rate
  on real option P&L over 25 days (n=783); directionally weak net of cost.
- WHALE-following (large single sweeps): DEMOTED — dilutes to ~zero edge across 113 names;
  only real in ~10 AI/semis names.
- TRIPLE-confluence: SUPPRESSED — 36.4% WR, anti-predictive.
- Sector ROTATION alert, euphoria/exhaustion brake, chop gate, bearish-flow escalator
  (newer, mostly shadow-gated).

═══════════════════════════════════════════════════════════════════════
PART 2 — WHAT I HAVE ALREADY ESTABLISHED (do NOT re-suggest these unless you can show my
prior test was wrong)
═══════════════════════════════════════════════════════════════════════
After ~6 months of slippage-realistic backtesting and forward testing, my honest conclusion:

1. THE SYSTEM HAS NO STANDALONE DIRECTIONAL ALPHA NET OF COST. Flow-as-a-trigger and GEX-
   structure-as-a-trigger were both FALSIFIED as predictive signals. The detectors are
   structurally LONG-biased.
2. THE VALIDATED EDGE is two things only: (a) RISK MANAGEMENT — disciplined exposure caps,
   "don't cap your winners" exits (let OTM winners run, scale partials), concurrent-exposure
   limits; and (b) LATENCY/AWARENESS — the system surfaces context (rotation, gamma walls,
   informed clusters) faster than I could manually, which improves decision quality and
   timing, not signal accuracy.
3. The system is best understood as a CONTEXT / SITUATIONAL-AWARENESS engine, NOT a signal/
   alpha engine.
4. Behavioral findings: late flow INTO a known catalyst tends to be retail holding the bag
   (a fade, not a follow); parabolic moves into an event are exhaustion-prone.

═══════════════════════════════════════════════════════════════════════
PART 3 — WHO I AM (constraints are real; do not hand-wave them)
═══════════════════════════════════════════════════════════════════════
Solo retail trader. Brokers: E-Trade + Tradier. Instruments: equity OPTIONS (incl. 0DTE).
Retail capital, retail data, retail latency. Engineering background, not finance/PhD. I trade
the system's context DISCRETIONARILY — it informs my entries, exits, sizing, and direction.
I am self-aware that I am nowhere near Jane Street / Citadel / HFT shops (PhD quants, co-lo,
$10k/day infra). I do not know whether trying to be is even the right goal.

═══════════════════════════════════════════════════════════════════════
PART 4 — THE FOUR QUESTIONS (answer each explicitly, with a clear verdict)
═══════════════════════════════════════════════════════════════════════
Q1. REACTION SPEED & BIAS-FLIPPING: Am I reacting fast enough to (a) strip out my directional
    bias and (b) flip from long to short (or vice versa) when the tape regime changes? What
    concrete mechanism (signal, rule, or process) would let a discretionary retail options
    trader flip stance reliably and unemotionally — and how do I measure whether I'm too slow?

Q2. MULTI-FACTOR PREDICTION: Can a retail setup like mine realistically PREDICT market
    behavior by combining factors — sector rotation, internal/external politics, technological
    innovation, supply/demand? Is this tractable at all for one person, or is it a trap? If
    tractable, what is the minimum viable version, and which factors actually carry signal vs
    noise for a retail options trader?

Q3. EFFICIENCY vs INSTITUTIONS — THE HONEST ONE: How efficient is my system relative to Jane
    Street / Citadel / Two Sigma? And SHOULD I even be trying to compete with PhD-quant HFT
    shops? Where can a solo retail options trader have REAL, durable edge that institutions
    structurally CANNOT or WILL NOT capture (small size, patience, no redemptions, no career
    risk, niche illiquidity, holding through noise, specific behavioral/structural edges)?
    Where can I NEVER compete? Be specific about the boundary.

Q4. IMPROVING WIN-RATE / PERFORMANCE: Given everything above — and given that my directional
    detectors are falsified and my validated edge is risk-management + latency — what is the
    HIGHEST-ROI thing I can actually do to improve performance? Should the goal even be a higher
    directional win rate, or should it be expectancy via sizing/exits, or should I change the
    game entirely (different instruments, timeframes, or a narrower niche)?

═══════════════════════════════════════════════════════════════════════
PART 5 — HOW TO ANSWER (non-negotiable)
═══════════════════════════════════════════════════════════════════════
- Lead with a 3-sentence BLUNT verdict on whether I'm directing my effort correctly.
- Answer each of Q1–Q4 with a clear position, not "it depends."
- Every recommendation must be SPECIFIC and FALSIFIABLE: not "improve risk management" but
  "do X, measured by metric Y, with target Z." State how I'd know if it's working in 30 days.
- PRIORITIZE all recommendations by (expected impact × feasibility for a solo trader). Give
  me the top 3 to do this month and what to ignore.
- Explicitly separate "achievable for a retail options trader" from "institutional fantasy."
- If my validated-edge conclusion (no directional alpha; edge = risk-mgmt + latency) is right,
  tell me what that IMPLIES for where I should spend the next 6 months. If it's wrong, show me
  the specific flaw.
- End with: the single highest-leverage adaptation, and the single biggest blind spot you see.
```
