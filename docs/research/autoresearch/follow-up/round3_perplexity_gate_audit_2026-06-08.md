# Round 3 — Targeted Perplexity audit of the validation-gate math
**Date:** 2026-06-08 · ONE LLM (Perplexity), ONE adversarial+cited prompt. Follow-up
to the AutoResearch fork/gate rounds. Goal: verify or refute four specific
methodology claims from the C1–C6 code review with current citations + the
canonical fix. Not a 4-LLM round — surgical, to avoid ceremony.

---

## 📋 CONTEXT (paste first)

I built an offline validation gate for a trading-signal research loop. It uses the
Bailey & López de Prado stack: Deflated Sharpe Ratio (DSR), Probability of Backtest
Overfitting via CSCV (PBO), purged+embargoed CPCV, MinTRL/MinBTL, Hansen SPA, plus a
global trial ledger and an always-valid confidence sequence for decay monitoring.
Sample sizes are tiny (hundreds of alerts → tens of *economic-decision clusters* per
cohort). I seeded the global trial ledger with N≈300 (prior ad-hoc backtests +
research rounds) so DSR doesn't pretend the program started from zero trials.

A code review flagged four issues. **Be adversarial: for each, tell me if I'm right
or wrong, cite the primary source (Bailey-López de Prado / Bailey-Borwein-LdP-Zhu /
Howard-Ramdas), and give the canonical fix.** If a claim is wrong, say so plainly.

## 🔬 THE FOUR CLAIMS TO ADJUDICATE

**1. DSR seed → variance corruption.** My DSR implementation feeds the *entire* trial
Sharpe list into both (a) the trial count `N` and (b) the cross-trial variance
`Var(ŜR)` that the expected-maximum-Sharpe term `E[max ŜR | N] = √Var(ŜR)·[(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))]` depends on. But the 300 *seed* trials are
recorded with `Sharpe = 0.0`, so they crush `Var(ŜR)` → shrink `E[max ŜR|N]` (the
hurdle) → make DSR **too lenient** via the variance channel, even as they correctly
*raise* N. **Claim: seed trials should contribute to N but NOT to `Var(ŜR)`; the
variance should be estimated only from genuinely-scored trials. Correct? What is the
canonical treatment of N vs Var(ŜR) in the DSR — are they meant to come from the same
trial set, and how should prior/seeded trials enter?**

**2. PBO/CSCV degenerates at small T.** CSCV splits T observations into S blocks (I
default S=16). With T=21 and S=16, `block_size = T//S = 1`, so each block holds ONE
observation → per-block Sharpe = mean/std of a single value → undefined/zero → the
in-sample argmax and OOS rank are degenerate, so my reported "PBO=0.672" is noise.
**Claim: PBO is meaningless when block_size→1; there's a minimum observations-per-
block (and thus a max S given T) for CSCV to be valid. Correct? What is the canonical
guidance for choosing S relative to T, the minimum block size, and what should the
gate do at small T (shrink S, or return PBO = N/A)?**

**3. Effective-N must not collapse independent prior trials.** I compute an "effective
number of independent trials" two ways: (a) participation ratio `(Σλ)²/Σλ²` of a trial
return-correlation matrix's eigenvalues, and (b) a no-matrix fallback = count of
distinct trial *families* (label groups). Problem: all 300 seeds share one family
label, so fallback-N_eff ≈ 3 while the true count is 302 — collapsing 300 genuinely-
independent prior searches to ~1. **Claim: the participation ratio is the right N_eff
for correlated variants, but genuinely-independent prior/seed trials must NOT be
family-collapsed; N_eff should be `(independent seed floor) + (clustered formal
variants)`. Is the participation-ratio the standard estimator for the effective number
of independent trials here, and how should a seeded prior count combine with it?**

**4. Always-valid LCB calibration.** For continuous (daily) retirement monitoring of a
binary win-rate I use an empirical-Bernstein, law-of-iterated-logarithm lower bound
(Howard-Ramdas family): `radius = √(2·v·β/n) + 3β/n`, with
`β = ln(1/α) + 3·ln(ln(e·n))` and `v = μ̂(1−μ̂)`; retire when this time-uniform LCB
falls below breakeven, with two-check hysteresis. **Claim: this is a correct,
standard time-uniform/anytime-valid confidence sequence for a [0,1] mean, it is
deliberately wider than a fixed-n Wilson bound (so it errs toward NOT retiring), and
that conservatism is appropriate. Correct? Is this the right boundary form, is the
`β` constant standard, and is there a tighter standard anytime-valid bound for a
bounded/Bernoulli mean (e.g. betting/PRGW confidence sequences) I should prefer?**

## 🎯 OUTPUT
For each of the 4: **VERDICT (correct / partially / wrong)** → 1-line why → primary
citation → the canonical fix (1–2 lines). Then: which of the 4 is most important to
fix first, and any error in my framing. Keep it tight; cite primary sources, flag
thin evidence.

> Re-verify any cited formula/paper before acting (prior rounds surfaced fabricated
> citations). This is a methodology check, not a strategy round.
