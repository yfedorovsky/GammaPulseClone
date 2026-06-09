# AutoResearch — Explained From Scratch (plain English)

A from-the-ground-up explanation of what we built, why, and what every technical
term and abbreviation means. No stats background assumed. Read top to bottom.

---

## 0. The one-sentence version
AutoResearch is a system that **grades your own trading signals honestly** — it
figures out which "edges" actually make money after costs, which have quietly
**stopped working**, and it does this with the same statistical rigor quant funds
use so it **can't fool itself** with a lucky streak.

**Analogy:** think of it as a brutally honest coach for your signals. Every play
(alert) you ran gets reviewed on game film, scored on *points actually put on the
board* (real P/L after slippage, not "we moved the right direction"), and benched
the moment it stops performing — with the bench decision backed by statistics, not
vibes.

---

## 1. The three traps it's built to avoid

Everything in AutoResearch exists to dodge three ways traders fool themselves:

1. **Alpha decay.** *Alpha* = your edge / excess return. Edges fade: a setup that
   printed last quarter quietly dies as the market adapts. Most people keep trading
   a dead signal out of habit. → AutoResearch *watches for decay and retires* signals.

2. **Multiple testing (a.k.a. data mining / "fooling yourself").** If you try 100
   ideas, ~5 will look great by **pure luck** even if none has real edge. The more
   you search, the more lucky-but-fake winners you find. → AutoResearch *counts every
   test it ever runs* and raises the bar accordingly.

3. **Backtest overfitting.** A strategy tuned to fit the past perfectly often fails
   on new data (it memorized noise, not signal). → AutoResearch *measures how
   overfit* a result is before trusting it.

The deep insight from our research rounds: **the durable edge isn't any one signal —
it's the discipline of validating and retiring faster than everyone else.**

---

## 2. The data it runs on: `alert_outcomes.db`

Every alert the live system fires is logged here with its **fire-time context**
(the market state when it fired: VIX, dealer gamma, IV rank, earnings proximity)
and, later, its **outcome** (did the underlying move the called direction? did the
option make money?). This is the proprietary asset — no scraper or competitor has
your labeled outcomes. AutoResearch only ever **reads** this DB; it never writes to
it and never touches live trading.

- **VIX** = the market's "fear index" (expected volatility).
- **IV** = implied volatility (the option market's expected move). **IV rank / IVR**
  = where today's IV sits vs its own past year (0–100).
- **Dealer gamma / GEX** = whether option market-makers' hedging *stabilizes* or
  *amplifies* price moves (a regime signal).

---

## 3. PART A — The Signal Health Card (the daily-usable tool)

**File:** `scripts/signal_health_report.py` → reads the DB, prints one "card" per
signal type. It answers: *"which of my live signals are decaying, and are they
actually tradable?"* This operationalizes the "retire decayed signals" idea.

Each card shows:

### Win rate (WR) and "n"
- **Win rate** = fraction of that signal's trades that won.
- **n** = number of resolved trades (the sample size). Small n = don't trust it yet.
- **Breakeven** = the win rate you need just to not lose money given your reward:risk.
  Ours is **22.7%** at a **3.4× R:R** (you win 3.4× what you risk, so you can be
  "wrong" most of the time and still profit). A signal is in trouble if its win rate
  is near/below breakeven.

### The confidence bound — this is the subtle, important part
A raw win rate (say 40% on 50 trades) is noisy — the *true* rate could be 30% or
50%. A **confidence interval (CI)** gives a range. We care about the **lower bound**
(worst plausible case): if even the *optimistic-floor* of the win rate is below
breakeven, the signal has no demonstrated edge.

- **Wilson interval / Clopper-Pearson interval / Jeffreys interval** = three standard
  recipes for a win-rate confidence interval. Clopper-Pearson is the most
  conservative ("exact"); Wilson is a good general default; Jeffreys is Bayesian.
- **The problem with normal CIs here:** they're valid if you look **once**. But we
  re-check the same signal **every day**. Checking a 95% interval repeatedly is like
  re-rolling dice until you get the result you want — eventually it *randomly*
  dips below breakeven and you'd retire a perfectly good signal. This is called
  **optional stopping bias** / the **peeking problem**.
- **The fix — an "always-valid" (anytime-valid) confidence sequence (CS):** a
  special interval that stays valid **no matter how many times you peek**. We use a
  **betting confidence sequence** (the math: Waudby-Smith & Ramdas, 2021–2023).
  - **Why "betting"?** It frames testing as a fair-bet game: you bet against the
    hypothesis "the true mean is m." If your imaginary betting wealth grows huge,
    that hypothesis is implausible → you can rule out that m. The set of m's you
    *can't* rule out is the confidence sequence. It's mathematically airtight under
    repeated peeking.
  - We implemented this in **pure Python** (the standard library `confseq` is a C++
    package that won't build on Windows) and **validated it with a coverage
    simulation** (see §6). The card's lower bound (`AV-LCB` = Always-Valid Lower
    Confidence Bound) comes from this.

### Verdict + action
- **HEALTHY** (lower bound clears breakeven) · **WATCH** · **RETIRE_CANDIDATE** ·
  **UNTRUSTED** (too few trades). Plus a suggested action and a 60-day-vs-prior-60-day
  **trend**. Retirement also uses **hysteresis** (must stay bad for 2+ checks) so a
  one-day fluke can't trigger it.

### The `--economics` upgrade (the killer feature)
The win rate above is **directional** — "did the stock move >0.3% the right way."
That is **NOT the same as making money on the option**, because you pay the
bid-ask **spread (slippage)**. The economics mode re-computes each trade's *actual
option P/L*:
- **R-multiple** = profit measured in units of risk. +2R = made twice what you
  risked; −1R = full stop-loss. Lets you compare trades of different sizes fairly.
- **Slippage / ask-in, bid-out** = the realistic worst-case retail fill: you buy at
  the **ask** (high) and sell at the **bid** (low), paying the full spread both ways.
- **NBBO** = National Best Bid & Offer (the official best quotes); we replay it from
  ThetaData to simulate fills.
- **The finding it surfaced:** signals that read 🟢 HEALTHY on direction (SOE_A at
  38.7% WR, FLOW_MEDIUM at 47%) are actually **negative after slippage** — flagged
  with ⚠️. *Directional accuracy ≠ money.* This is the whole point.

---

## 4. PART B — The Validation Gate (for testing NEW hypotheses)

When you (or, eventually, an automated "miner") propose a new trading idea, it must
pass an ordered gauntlet before it's allowed anywhere near a real decision. Cheap
checks first, expensive last. **File:** `autoresearch/gate.py`.

### Stage 0 — Test card + dedup
- A **test card** = a pre-registered hypothesis: the falsifiable claim, expected
  direction, *why* it should work (mechanism), which signal/regime it applies to,
  and what would kill it. Forcing this up front stops vague "maybe X works" fishing.
- **Dedup (de-duplication)** = reject ideas that are just reworded versions of ones
  already tested (otherwise you "discover" the same thing 20 times and inflate your
  test count). Ours checks both **wording similarity** and **structural** sameness
  (same signal + same direction + similar rationale = the same experiment).

### Stage 0.5 — Label confidence (do the labels even mean anything?)
Flow alerts get a **side** tag — ASK (someone aggressively *bought*) or BID
(*sold*) — and that tag decides the alert's claimed direction. On big blocks the
tag is often a **guess** (the live tracker falls back to a single snapshot print),
and the real tape sometimes says the opposite: MSTR 125C was tagged ASK/bullish
while 99.4% of 51,847 contracts actually hit the bid (selling). A cohort built on
such labels can show a fake "edge" that no amount of data fixes — it's mislabeled,
not under-sampled. So the gate **replays the OPRA tape** (every print + the quote
it traded against) for a sample of each flow-derived cohort and computes the
**tape-confirmation fraction**: how often the tape agrees with the label. Mostly
guesses/contradictions → the cohort is **quarantined** on label quality (a
different axis than "not enough data"); and if the edge *disappears* in the
tape-confirmed subset, it's rejected as a **labeling artifact**. First live run:
FLOW_MEDIUM was only **12% tape-confirmed**. (Detail: SIDE_CONFIDENCE.md.)

### Stage 1 — MinTRL / MinBTL (do we even have enough data?)
- **MinTRL** = **Minimum Track Record Length** — the minimum number of trades needed
  to *statistically prove* a given edge. Small edges need *lots* of data.
- **MinBTL** = **Minimum Backtest Length** — similar idea, scaled by how many tests
  you've run.
- If the cohort has fewer trades than required → **quarantine** ("come back when you
  have more data"). Right now *everything* hits this — we honestly don't have enough
  history yet, which is the system correctly saying "no proven edge."

### Stage 2 — CPCV (test it without cheating)
- **Cross-validation (CV)** = train on part of the data, test on the held-out part,
  to see if it generalizes. Standard ML.
- **Purged + embargoed** = the finance fix. Trades overlap in time (a trade's
  outcome can leak into a nearby trade), so we **purge** (drop) training trades that
  overlap the test window and **embargo** (skip) a buffer right after it. Stops the
  future from leaking into the past.
- **CPCV** = **Combinatorial Purged Cross-Validation** — does this across *many*
  train/test splits to get a whole *distribution* of out-of-sample results, not a
  single lucky path. (Plain CV / "walk-forward" tests only one path and is fragile.)

### Stage 3 — PBO (is this just overfit?)
- **PBO** = **Probability of Backtest Overfitting** — the chance that the
  best-looking configuration in-sample actually performs **below average** out-of-
  sample. **PBO ≥ 0.50** = your "winner" is no better than a coin flip out-of-sample
  = overfit garbage. (Computed via **CSCV** = Combinatorially Symmetric CV.)
- *Important nuance we fixed:* PBO is **not** a p-value. The danger line is **0.50**,
  not 0.05. We treat PBO (and DSR) as **diagnostics**, not hard pass/fail gates.

### Stage 4 — DSR (deflate the Sharpe for luck)
- **Sharpe ratio** = return per unit of risk (higher = better risk-adjusted edge).
- **The problem:** if you test N ideas, the *best* Sharpe will look high **by luck**.
- **DSR** = **Deflated Sharpe Ratio** — discounts the observed Sharpe by how good a
  *pure-luck* result would look given **N total tests**, and corrects for non-normal
  (fat-tailed) returns. **DSR ≥ 0.95** = 95% confident the edge is real, not luck.
- **E[max Sharpe | N]** = "the expected best Sharpe you'd get from N random
  strategies" — the luck benchmark DSR must beat. Bigger N → higher bar.
- **PSR** = **Probabilistic Sharpe Ratio**, the simpler building block DSR extends.

### The trials ledger (the anti-self-deception spine)
- A persistent count of **every backtest ever run** (the "global N"). DSR's luck-bar
  uses this — you literally **cannot lower your own bar by running more tests**.
- We **seed** it with ~300 (prior ad-hoc backtests + research rounds) so it doesn't
  pretend the program started from zero.
- **N_eff** = **effective number of *independent* tests** — 50 tiny variations of one
  idea count as ~1, not 50 (via a math trick called the *participation ratio* on the
  correlation of their results).

### Stage 5 — Hansen SPA (does it beat what I already have?)
- **SPA** = **Superior Predictive Ability** (Hansen's test). It's not enough to beat
  *zero* — a new signal must **statistically beat your existing best signal** (the
  baseline). Uses a **bootstrap** (resampling the data many times to get a robust
  p-value). A subtle point we handle: something can "lose less than a losing
  baseline" and pass SPA — so we *also* require positive economics.

### Stage 6 — Economic null
- Must have **positive expectancy after realistic slippage**, hold up across market
  regimes, and not be redundant with an existing signal (**orthogonality** = low
  correlation to what you already trade). This is a **hard** gate.

### Then: shadow → human → ship
Even after passing, a signal runs in **shadow** (watched live, not traded) until it
has ≥200 clean live outcomes, then a **human approves** before it goes live. Nothing
auto-trades. And it auto-**retires** when its live lower bound breaches breakeven.

---

## 5. Cross-cutting concepts (used in several places)

### The unit of analysis: "economic decision cluster"
Raw alerts are spammy — 10 alerts on the same name, same day, same direction are
really **one decision**, not ten. Counting them as ten fakes a big sample. So we
group them into a **cluster** (ticker × trading-day × direction) = one real economic
decision, and validate on clusters. This keeps the statistics honest.

### Hierarchical / Bayesian "partial pooling"
- **The problem:** sliced finely (e.g., "this signal, in high-VIX, negative-gamma,
  pre-earnings"), each bucket has tiny n → hopeless statistics.
- **Partial pooling** = let small buckets **borrow strength** from the overall
  average. A thin bucket's estimate gets pulled ("shrunk") toward the global mean
  unless it has strong evidence to differ.
- **Empirical Bayes / Beta-Binomial** = the recipe for pooling *win rates*.
  **DerSimonian-Laird** = the recipe for pooling *averages* (like R-multiples).
- **Why:** at our sample sizes, strict per-bucket testing rejects everything (~100%
  false negatives). Pooling is the only honest way to learn from subgroups.

### Coverage simulation (how we *verified* our home-grown math)
A confidence bound is only trustworthy if it actually **covers** the truth at the
promised rate. So for our pure-Python betting CS, we ran a **Monte-Carlo
simulation**: generate thousands of fake win/loss streams with a *known* true rate,
and check the bound is wrong at most ~α (e.g., 5%) of the time. It passed (wrong
0–2% of the time = correctly conservative). This sim also **caught a real bug** — a
shortcut version was invalid — which is exactly why you simulate instead of assume.

---

## 6. Glossary (every abbreviation)

| Term | Means |
|---|---|
| **alpha** | trading edge / excess return |
| **AV-LCB** | Always-Valid Lower Confidence Bound (the retirement trigger) |
| **CI** | Confidence Interval (a plausible range for a true value) |
| **CS** | Confidence **Sequence** (a CI that stays valid under repeated peeking) |
| **CV** | Cross-Validation (train/test split to check generalization) |
| **CPCV** | Combinatorial **Purged** CV (leakage-safe CV over many splits) |
| **CSCV** | Combinatorially Symmetric CV (the engine behind PBO) |
| **DSR** | Deflated Sharpe Ratio (Sharpe corrected for luck + fat tails) |
| **PSR** | Probabilistic Sharpe Ratio (DSR's simpler building block) |
| **E[max Sharpe\|N]** | the best Sharpe luck alone would produce from N tests |
| **GEX** | Gamma Exposure (dealer hedging regime: stabilizing vs amplifying) |
| **IV / IVR** | Implied Volatility / IV Rank |
| **MinTRL** | Minimum Track Record Length (data needed to prove an edge) |
| **MinBTL** | Minimum Backtest Length |
| **N / N_eff** | total tests ever run / effective *independent* tests |
| **NBBO** | National Best Bid & Offer (official best quotes) |
| **PBO** | Probability of Backtest Overfitting (≥0.50 = overfit) |
| **R / R-multiple** | profit in units of risk (+2R = 2× risked; −1R = full stop) |
| **R:R** | Reward-to-Risk ratio (ours 3.4×) |
| **Sharpe** | return per unit of risk |
| **slippage** | money lost to the bid-ask spread on entry+exit |
| **SPA** | Superior Predictive Ability (Hansen — beat the baseline, not just zero) |
| **VIX** | market fear index (expected volatility) |
| **Wilson / Clopper-Pearson / Jeffreys** | three win-rate confidence-interval recipes |
| **side (ASK/BID/MID)** | where an option trade executed vs the quote: at the ask = aggressive buy, at the bid = sell, between = unclear |
| **tape / OPRA tape** | the full record of every option trade print (what ACTUALLY executed) |
| **tape-confirmation fraction** | share of a cohort's alerts whose side tag the tape confirms (the label-quality metric) |
| **labeling artifact** | an apparent edge that disappears in the tape-confirmed subset — it came from mislabeled trades |
| **shadow mode** | computed/tagged but NOT changing live decisions (awaiting validation) |
| **hysteresis** | require a condition to persist (≥2 checks) before acting |
| **purge / embargo** | drop overlapping / buffer-skip trades so the future can't leak |
| **orthogonality** | low correlation to existing signals (adds something new) |

---

## 7. Where it stands right now

**Built & runnable:** the Signal Health Card (+ economics), the full validation gate
(all stages above), and every building block (decay monitor, option-PnL re-sim,
pooling, trials ledger, dedup, betting CS). All tests green.

**Honest current state:** the gate **quarantines everything at MinTRL** — we simply
don't have enough independent history yet to prove any edge. That's the system being
honest, not broken.

**Not built yet:** Phase 2 (an automated "miner" that proposes hypotheses and runs
them through the gate) — **data-gated**, waiting on weeks more outcomes; and MLflow
experiment tracking (optional plumbing).

**Isolation:** all of this lives on the `feature/autoresearch-loop` branch (pushed,
**not merged** to `main`). The live trading backend has none of it. AutoResearch is
offline, read-only, and advisory — it proposes; you decide.

*See also: HOWTO.md (commands + when to run), PROJECT.md (charter), SYNTHESIS.md
(the research verdict that shaped the design), PHASE1.md (gate internals).*
