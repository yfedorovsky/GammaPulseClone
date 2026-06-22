---
title: "Cap backtest — does the concurrent-exposure cap actually cut drawdown?"
date: "2026-06-21"
status: "DONE. Validates the cap (ruin avoidance) + regime scaling; REJECTS the drawdown breaker."
harness: "research/sizing_cap_backtest.py  (tape cached: research/results/sizing_trade_tape.json)"
grounding: "1,523 reconstructed king-up lotto-call trades, Jan-Jun 2026, real daily option paths (ThetaData EOD, ask-in/bid-out). Exit held constant (scale 1/3 @ +100%, run rest). Only the SIZING rule varies."
---

# Cap backtest: drawdown WITH vs WITHOUT the concurrent-exposure cap

## TL;DR
- **The no-discipline book goes BANKRUPT in Q1 2026** (mark-to-market drawdown −137.8% → through −100%). Its
  headline "+164% return" is a **survivorship mirage** — you're wiped out in March before the April/May rally.
- **Any deleveraging prevents ruin.** The cap's first-order benefit ("deploy < 100%") is also achievable by
  simply trading smaller — the scale-invariance control confirms it (uniformly shrinking the no-discipline book
  to the cap's size → ~16% maxDD, survives, same Calmar).
- **The REGIME overlay is the marginal structural value.** `S2_regime` is the **only** scenario whose Calmar
  (1.41) beats the no-discipline baseline (1.19) AND the blind fixed cap (0.20). Regime-scaling the cap earns
  its keep; the cap alone is (here, unlucky) pure deleverage.
- **The drawdown circuit breaker is NET-HARMFUL as specced** — it cut exposure into the March/June lows and
  missed the V-recovery (`S3` return −5.6%, Calmar −0.28). **Do not ship it** as a "halve cap after −X% DD" rule.

## Results (all values = % of TOTAL capital; exit identical across scenarios)

| Scenario | Rule | Ret% | maxDD% | Ruin | Calmar | taken | avgEx% | DD cut vs S0 | Ret give-up vs S0 |
|---|---|---:|---:|:--:|---:|---:|---:|---:|---:|
| **S0_nodisc** | pile in until cash-capped (100%) | 163.9 | **137.8** | **YES** | 1.19 | 331 | 92.9 | — | — |
| **S1_cap12** | hard 12% concurrent cap | 6.5 | 33.1 | no | 0.20 | 38 | 11.3 | 76% | 96% |
| **S2_regime** | 12% × regime (1.0/0.5/0.2) | 36.9 | 26.1 | no | **1.41** | 36 | 10.5 | 81% | 78% |
| **S3_regime_brk** | S2 + DD breaker (−6% → halve) | −5.6 | **19.6** | no | −0.28 | 24 | 7.5 | 86% | 103% |

Per-month P&L (% capital) — the regime gate's honesty check:

| | Jan | Feb | Mar | Apr | May | Jun |
|---|---:|---:|---:|---:|---:|---:|
| S0_nodisc | −12.4 | −2.1 | **−88.6** | +141.5 | +168.3 | −42.9 |
| S2_regime | −0.3 | −9.7 | −11.1 | +33.4 | +34.6 | −9.9 |

## What this means (honest reading)

1. **The real result is ruin, not return.** A 100%-deployed lotto book (≈58 concurrent OTM calls at 1.7% each —
   the proxy for the 52-position blow-up) hit a **−137.8% mark-to-market drawdown** and crossed −100% in March.
   The +164% terminal is unreachable: you can't hold a −100% account. **This is the single most important number
   in the study** — the cap converts a Q1 bankruptcy into a survivable book (maxDD 26–33%).

2. **Ruin-avoidance is first-order "deploy less," not magic.** Scale-invariance control: Calmar is unchanged by
   uniform sizing, so shrinking the no-discipline book ÷8.8 (to the cap's avg exposure) gives ~16% maxDD, survives,
   Calmar still 1.19. **You get most of the survivability just by trading smaller** — the cap's job is to *enforce*
   that with a hard, monitorable number, not to conjure alpha.

3. **The regime overlay is where structure beats deleverage.** Calmar ranking: **S2_regime 1.41 > S0 1.19 > S1 0.20.**
   Scaling the cap down in chop/downtrend (cutting March's −88.6% to −11.1% and softening June) lifted risk-adjusted
   return ~19% above the no-discipline baseline and 7× above the blind fixed cap. The blind 12% cap (S1) was pure —
   and in this draw, unlucky — deleverage (it took whatever filled first, regardless of tape).

4. **Kill the drawdown breaker (as specced).** Halving the cap after a −6% book drawdown de-risked into the March
   and June lows and **missed the April/May V-recovery** → return went NEGATIVE (−5.6%), Calmar −0.28. It bought the
   lowest maxDD (19.6%) at the cost of turning a winning book into a loser. Classic "sell the bottom." A drawdown
   trigger on a mean-reverting, V-shaped fat-tailed book is counterproductive.

## Recommendation
- **SHIP** the concurrent-exposure cap **with regime scaling** (`S2`) as the sizing discipline. It is the
  survivability win and the only rule that improved risk-adjusted return over doing nothing.
- **SHIP the Phase-1 MONITOR** (display lotto exposure % vs regime-scaled cap) — supported: the binding number is
  "total concurrent premium-at-risk," and making it visible is the zero-risk first step.
- **DROP / rework** the drawdown circuit breaker. If revisited, it must not simply de-risk on drawdown (that sells
  the recovery); a regime-conditioned or time-decayed re-entry would be required, and is not yet justified.

## Caveats (do not over-read)
- **Single 6-month, bull-dominated sample** (Apr/May +141/+168%). Calmar rewards leverage and one-bad-month-
  avoidance in such a sample. The **ruin/DD finding is robust**; the **return-give-up and the regime Calmar gain
  are sample-specific** — out of sample the regime timing may not be as clean.
- **King-up entries are a PROXY** for the user's single-name momentum lotto book (a representative fat-tailed,
  correlated, long-call population). The cash constraint throttled concurrency to a realistic ~58 max.
- **Exit held constant** (scale ⅓ @ +100%, run the rest) across all scenarios — isolates the sizing rule.
- Marks are daily **bid** (conservative, liquidation-honest); no-data days forward-fill the last mark.
