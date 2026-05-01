# Follow-up — Post-Synthesis Questions for Gemini Pro / Perplexity

This goes to both Gemini Pro and Perplexity (with the prior round's
context). I synthesized your responses and converged on a path
forward, but landed on five specific questions where I want sharper
input. Where you diverged from each other previously, I'll flag it.

## Where we landed

- v2 dead in any meaningful sense (Test #1 FAIL + Test #2 FAIL +
  Gate 8 TIE = three independent paths killed)
- Spread gate worth adding (one-liner, both of you endorsed)
- Forward stopping rule tightened from 30/5 to **30 fires AND 15 day
  clusters** (this picks Gemini's stricter cluster floor over
  Perplexity's stricter fire floor — both of you converged on a
  minimum of 10-15 clusters)
- Sizing language strips "Kelly" (Perplexity's stricter framing)
- Forward paper-only until CI completes
- Honest expected outcome: small noisy edge at hobby scale, possibly
  retire as production

The eight audit results, with concrete numbers from
`background_distributions.md` (96,304 per-minute observations across
124 trading days × 2 tickers):

- Test #1 microstructure profile: FAIL, max Cohen's d = 0.49 (volume)
- Test #2 OFI predictive: FAIL, max R² = 0.0002 across 6 cells
- Test #3 VIX1D regime: PASS, 12/16 K-W tests p<0.05
- Test #5 trade-size cohorts: small +0.32, medium +0.23, large +0.07
- Test #6 spread regime: PASS, normal +63%/40%WR vs HIGH -14%/30%WR
- Test #7 lead-lag: FAIL, lag-0 corr +0.36 dominates
- Gate 8 (LR vs bar): TIE, LR +0.30 vs bar +0.33

Concrete spread thresholds from background distributions (pre-
committed, not tuned):
- SPY morning: p90 spread = 0.049 (~5 cents), p99 = 0.090
- SPY midday: p90 = 0.043, p99 = 0.068
- QQQ morning: p90 = 0.053, p99 = 0.100

## Five sharper questions

### Q1. Forward-window statistical power

Stopping rule = ≥30 fires AND ≥15 day clusters. Cluster-bootstrap
on (gated − random_minute_atm) where random_minute_atm averages K=5
random non-fire minutes per fire-day.

With this design, given the right-skewed P&L distribution we
observed in-sample (mean +28pp, but 4/21 contributed +235pp while
most days were ±0-30pp), what minimum *true* effect size could we
realistically detect at 80% power? Concretely:

- If true timing alpha is +5pp, will we see CI exclude 0?
- If true alpha is +10pp?
- If true alpha is +20pp?

Asked differently: is it possible we run this window for 6 weeks,
return CI [+1pp, +25pp], conclude "edge inconclusive," when the
true effect is actually +8pp but our power was insufficient to
detect it?

If yes → we should design for higher n upfront. If no → 30/15 is
fine. The user is at retail-strategy n-availability, so "double the
sample" might not be feasible without taking 3 months.

### Q2. Spread gate threshold — day-relative vs static historical

Test #6 used day-relative p90 (compare 30-min-pre-fire mean spread
to *that day's* session-wide minute-spread p90). PASS with 77pp
effect.

Now that I have static historical p90 from
`background_distributions.md` per (ticker × TOD), three options for
the production gate:

(a) **Day-relative p90**: as in Test #6. Adapts to vol regime
    automatically (Test #3 PASS confirmed spread varies by VIX1D).
    But requires running stats over the morning before the gate is
    usable; first-hour fires can't be filtered.
(b) **Static historical p90**: e.g., SPY morning p90 = 0.049. Fixed
    threshold, available from session open. Simpler, fully pre-
    committed against external 6-month data. Doesn't adapt to that
    day's regime.
(c) **Both required**: fire only if BOTH thresholds say "ok"
    (current spread ≤ day's running p90 AND ≤ historical p90).
    Strictest. Filters more.

Which of (a), (b), (c) is the most defensible v2 design? The Test
#3 PASS (vol regime carries microstructure info) seems to argue for
(a). The Perplexity-style "pre-commit thresholds against external
data" argument seems to argue for (b). What wins?

### Q3. Test #5 surprise — small > medium > large CVD correlation

Small-trade aligned CVD: +0.319 corr with opt_eod_pnl
Medium: +0.230
Large: +0.072

Counter to the "smart money = institutional = large trades" narrative
that's standard in microstructure. What's going on?

Three hypotheses:
- 0DTE-specific: retail dominates 0DTE flow more than other markets,
  and retail is informed (not noise) at the 30-min horizon
- Adverse-selection: large trades are dealer-hedging trades that are
  delta-neutral on the dealer side, hence less directional
- Sample artifact: n=17 fires is small, this could be noise

Is there published research that bears on this? If small-trade CVD
is genuinely the more informative signal, our v1 Gate 5 (which uses
aggregate notional) is throwing away information by treating all
trades equally.

### Q4. Should we run Gemini's logistic regression now?

Gemini suggested in Q4 of the previous round: build a logistic /
probit model of win_flag with predictors (spread_regime, VIX1D,
RV, volume, OFI). Test whether spread coefficient remains
significant when controlling for the others.

Two concerns:
- This is more in-sample analysis on the 27 fires, which Perplexity
  warned against
- BUT: the current spec (V2_DETECTOR_SPEC.md) doesn't explicitly
  forbid additional in-sample audits if the methodology is pre-
  committed

Is there a defensible way to run this regression that doesn't
violate the freeze? E.g., pre-commit the model spec and the
significance threshold (p<0.05 for spread coefficient), then run
once and abide by the result? Or is any further in-sample work
contaminating regardless?

### Q5. The strategic pivot — abandon directional 0DTE for credit spreads at GEX levels?

Gemini's Q7 reframe:

> "Have you considered shifting the framework to use GEX levels not
> as timing triggers, but strictly as spatial boundaries to fade
> structural liquidity?"

The user is heavily invested in the long-premium directional 0DTE
framework (most of the existing code). Pivoting to credit-spread
mean-reversion at GEX levels is essentially a different strategy.

Specific question: given that Test #1 said "gates fire at
non-distinctive moments" and Test #6 said "wide spread destroys
expected outcome on directional 0DTE," is the cleaner conclusion
"long premium 0DTE on these signals doesn't work, but credit spreads
SOLD at the same levels probably do" — and if so, what's the
minimum-viable test of that hypothesis without rebuilding everything?

For example: paper-trade an iron condor at fire time using the same
gates, observe whether the king/floor levels actually act as
boundaries, see if expected value is positive without the right-
tail dependency that's killing long premium.

### Q6 (bonus, only if you want to push back)

The whole night's discipline (audits, pre-commitment, RETIRE branch
honoring) is presumably "good practice" — but we've spent ~24
focused hours and the conclusion is "wait 4-6 weeks and you'll
probably retire it anyway." Is there a steelman version of "actually
this is taking the discipline too far, just trade it small and learn
from real P&L"? Or is rigor-vs-action the wrong tradeoff to be
considering at this stage?

## What I'd find most useful

If I had to rank: Q1 (power calc) > Q5 (strategic pivot) > Q2 (spread
gate design) > Q3 (small-trade puzzle) > Q4 (more analysis y/n)
> Q6 (sanity check on the whole approach).

Q1 is the one I genuinely don't know how to answer myself. The
others I could think through, but you'll catch things I won't.
