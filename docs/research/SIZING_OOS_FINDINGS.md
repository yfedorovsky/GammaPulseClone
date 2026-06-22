---
title: "OOS robustness of the sizing cap+regime edge (2024-2026), adversarially verified"
date: "2026-06-21"
status: "DONE + verified. CAP robust (ship). Regime overlay = leans-helpful but UNPROVEN (not refuted). Breaker parked."
harness: "research/sizing_cap_backtest_oos.py + research/sizing_oos_ordering_check.py (tapes/results in research/results/oos_*.json, gitignored)"
grounding: "5 half-year periods 2024-01..2026-06, momentum-breakout entries (a single-name long-call PROXY; king-up source is 2026-only), REAL ThetaData EOD option fills ask-in/bid-out, exit held constant. 3-lens adversarial verification + own reproduction."
---

# Does the sizing cap+regime edge survive out of sample?

## TL;DR (verified)
- **CAP = ROBUST → SHIP.** A 100%-deployed (no-discipline) lotto book ran **94–155% max drawdown in
  EVERY one of 5 periods** (outright ruin in 2/5). The flat 12% concurrent cap collapsed that to
  **15–29% maxDD with 0/5 ruin** — a 77–84% drawdown reduction, **5/5 directionally consistent and
  ordering-invariant.** This is the demonstrated, regime-robust edge.
- **REGIME overlay (S2 vs flat-cap S1) = LEANS HELPFUL but UNPROVEN — *not* refuted.** My first read
  ("only 2/5 periods, doesn't generalize") was an **artifact of a non-predictive same-day admit-order
  tiebreaker** (`order="king_up"`). Under fair RANDOM admit-ordering, regime-scaling beats the flat
  cap in **76% of 100 runs (mean Calmar edge +0.98)**. But n=5 periods is **underpowered** (the
  per-period edge CI straddles 0), so the magnitude is unconfirmed. Honest label: *optional /
  conservative / plausibly-helpful*, **not** "shown not to help."
- **BREAKER (S3) = inconsistent → stays parked.** Best in trending periods, worst in the 2024H2
  whipsaw; cuts DD but sheds return unpredictably.

## Method
Same engine and methodology as the in-sample 2026 run (`sizing_cap_backtest.py`), re-pointed to
2024-01..2026-06 with a DIFFERENT entry generator → a **double robustness test** (entry signal AND
regime). Entries = 20-day-high breakout & 5d-return ≥ +3% across the 116-name universe (king-up needs
`gex_struct_eod`, 2026-only; ThetaData stock EOD only goes back to 2024). Option fills = real
ThetaData EOD paths, ask-in/bid-out. Exit held constant (scale ⅓ @ +100%, run rest). Per period an
independent mini-backtest: S0 (100% cash pile-in) / S1 (flat 12% cap) / S2 (12%×regime) / S3 (+breaker).

## Results — per period
| Period | S0 ret% | S0 maxDD% | S0 ruin | S1 Calmar | S2 Calmar | S3 Calmar | regime (riskon/chop/down) |
|---|---:|---:|:--:|---:|---:|---:|---|
| 2024H1 | 162.4 | 94.0 | no | 4.07 | 3.15 | 1.98 | 109/21/8 (strong bull) |
| 2024H2 | 7.6 | 121.2 | **RUIN** | −0.32 | −0.56 | −0.73 | 111/28/19 (Aug carry-unwind whipsaw) |
| 2025H1 | 129.6 | 128.8 | **RUIN** | 1.28 | 1.93 | 2.35 | 94/29/29 (choppy/down) |
| 2025H2 | 398.3 | 155.4 | no | 1.76 | 2.27 | 3.47 | 109/19/11 (bull) |
| 2026H1 | 206.2 | 95.2 | no | 3.74 | 3.05 | 3.17 | 68/29/18 (mixed) |

S0 maxDD mean **118.9%** (ruin 2/5) → S1 maxDD mean **23.7%** (ruin 0/5). The cap finding is unanimous.

## The ordering artifact (why the regime read flipped)
`simulate()` admits same-day candidate entries until the cap binds; when it binds (~9–15 days/period)
the ADMIT-ORDER decides which trades make the book. The shipped default `order="king_up"` sorts by
5-day-return-at-entry — a **near-zero-correlation** sort (Pearson r≈0.04; weak Spearman ρ≈0.13). It is
not look-ahead (S1 and S2 use the same order) but it is a low-power tiebreaker that **dominates a
fragile result**. The clean way to report S2-vs-S1 is to average over random admit-orderings:

| Period | (S2−S1) king_up | neutral | random mean | S2>S1 (20 random) |
|---|---:|---:|---:|---:|
| 2024H1 | −0.93 | +3.65 | +1.47 | 85% |
| 2024H2 | −0.25 | −0.18 | −0.13 | **15%** |
| 2025H1 | +0.65 | +0.36 | +0.60 | 85% |
| 2025H2 | +0.51 | +0.76 | +1.46 | 100% |
| 2026H1 | −0.68 | +1.86 | +1.49 | 95% |
| **Pooled** | **−0.14 (2/5)** | | **+0.98** | **76% of 100 runs** |

So the single `king_up` run understated S2; the fair estimate has regime-scaling **ahead in 76% of
orderings**. The lone consistently-negative period is the **2024H2 whipsaw** (15%) — cutting exposure
into the "downtrend" then missing the snap-back, the same failure mode that sinks the breaker.

## Statistical honesty (why "leans helpful", not "proven")
The unit of analysis is **n=5 period-level Calmars**, not the ~470 trades/period (those only damp
within-period fill noise). The (S2−S1) edge is sign-stable-positive under random ordering but the
**95% CI across 5 periods straddles 0** and a single period (2024H2) can flip the mean. Power ≈ low.
→ The action (treat regime-scaling as optional, lead with the flat cap) is right; the *evidence*
supports "unproven/inconclusive," **not** a confident claim in either direction.

## Adversarial verification (3 lenses + synthesis, all agreed after reconciliation)
- **Methodology lens** found the ordering artifact (the headline catch) and confirmed the engine is
  otherwise sound: regime classifier strictly causal (trailing MA20 min10 + trailing 5d-ret, 0/147
  mismatches), maxDD/ruin/Calmar reproduce exactly, S0 cash cap binds ≤100%, exposure accounting
  consistent (expo[0]==1.0 for all 2,343 trades).
- **Statistics lens** caught the inferential overreach: n=5 ~6% power; 2/5 is the modal coin-flip;
  leave-one-out flips the mean sign → "inconclusive," not "not robust."
- **Fairness lens** confirmed the SPY-MA20 regime label is a *weak proxy* for single-name breakout
  outcomes (2026H1 had the most cut-eligible entries yet still lost under king_up ordering) — i.e.
  the *signal* may be weak even if the *concept* is sound.

## Recommendation (verified)
1. **SHIP the flat concurrent cap** as the binding sizing rule — robust ruin/DD prevention in 5/5.
2. **KEEP regime-scaling as an OPTIONAL conservative overlay**, labelled *plausibly-helpful but
   unproven* (76% of fair orderings favor it; underpowered). Do **not** claim a confirmed Calmar edge,
   and do **not** claim it "doesn't work."
3. **Breaker stays parked.** Gating stays parked — if/when wired, the **flat cap as a hard gate** is
   the supportable step; the regime multiplier is optional.
4. **Tooling note:** report S2-vs-S1 via the random-ordering band (`sizing_oos_ordering_check.py`),
   not a single `king_up` run — single-ordering results are fragile when the cap binds.

## Caveats
- Momentum-breakout entries are a PROXY for the user's single-name long-call book; the SPY-trend
  regime label is a weak proxy for single-name outcomes.
- Stock EOD limited the window to 2024+ (no 2022 bear); 5 half-years is underpowered for the regime
  question. The cap finding is strong; the regime magnitude is not.
