---
title: "Correlation-aware sizing for fat-tailed lotto-call books"
date: "2026-06-21"
status: "Research design. Practical, skeptical. NIA — sizing discipline, not a signal."
grounding: "Empirical: 39-name momentum universe avg pairwise corr 0.25 -> N_eff=3.8; 82-92% red together on SPY down days."
---

# Sizing a book of correlated fat-tailed lotto calls

## TL;DR — the recommended framework

**Size the BOOK, not the trade.** Your 40 lotto positions are ~2-4 independent bets, not 40.
So the binding constraint is **total concurrent lotto exposure**, capped small and scaled by
regime — NOT per-trade Kelly. Concretely:

1. **Hard concurrent cap** on total premium-at-risk in lotto calls: **≤12% of capital** in a
   risk-on regime (this single rule fixes the overleverage).
2. **Per-trade = equal-weight within the cap** (~1.5-2% base; **3% single-name ceiling**). Don't
   Kelly-size per trade — it double-counts the shared factor.
3. **Regime scaling = near kill-switch**: risk-on full cap (12%); chop half (6%); **confirmed
   downtrend ~0-3%** (they lose together in down months: Feb -37%, Jun -18%).
4. **Guardrails**: a **¼-Kelly ceiling** (never exceed) + a **drawdown circuit breaker** (lotto
   book −20% from peak → halve the cap until a winner resets it).

## 1. Problem diagnosis (why this is hard)

- **The book is ~one bet.** Avg pairwise correlation of the momentum names is 0.25; with N=39
  that's **N_eff = 39/(1+38·0.25) = 3.8 independent bets**. The OTM-call P&L correlation is
  *higher* (convex, same long direction, same theme) → effectively **~2-3 independent bets**.
- **They lose together.** On SPY down>1% days, 82% of the names are red; down>2%, 92%. OTM calls
  on those names go toward **−100% simultaneously**. Max loss in a down month ≈ *total* lotto
  exposure, all at once.
- **Correlation spikes in stress.** The 0.25 is the *calm* average; in a crash it goes toward 1
  (exactly when it hurts). So N_eff in stress is even lower — size for ρ≈1, not ρ=0.25.
- **The payoff punishes over-betting.** Median P&L ≈ −100% (most expire worthless), WR ~40-48%,
  expectancy carried by a 25%-frequency fat tail (+300% to +1500%). You WILL have long losing
  streaks; only the survivors of those streaks collect the tail.
- **Observed failure mode:** running 40-50+ positions = a single, massively-levered long-beta
  bet sized as if it were 40 diversified ones. One down month is then catastrophic.

## 2. Why standard methods fail here

| Method | Why it fails on THIS payoff |
|---|---|
| **Fixed-fractional per-trade** ("risk 2%/trade") | 40 trades → 80% at risk; correlation makes it one 80% bet, not forty 2% bets. Feels safe, isn't. |
| **Per-trade Kelly** | Assumes independence. Summing Kelly over 40 correlated positions over-bets the single shared factor by ~10×. |
| **Full Kelly (any form)** | Kelly needs the TRUE distribution. Yours is estimated from small, regime-biased samples with a heavy tail → full Kelly wildly over-bets. Kelly is a *ceiling*, not a target. |
| **Vol-targeting alone** | Targets per-position vol but ignores that the positions share one factor → under-counts portfolio risk. |
| **Risk parity** | Over-engineered here; equal-weight within a book cap captures ~all the benefit because the lottos are homogeneous. |

## 3. Recommended hybrid (detailed)

**PRIMARY — concurrent-exposure cap (the guardrail that matters).**
`lotto_book_risk = Σ premium_paid(open lotto calls)` (premium = max loss for a long call).
Rule: `lotto_book_risk ≤ CAP × capital`, with `CAP` = 0.12 risk-on. Rationale: the whole book
can go to −100% together, so cap it at a loss you can fully absorb (12% = a survivable bad
month). **This alone prevents the 40-50-position blowup.**

**SECONDARY — per-trade size within the cap.**
`base_trade = CAP × capital / target_concurrent` (e.g., 12% / 7 ≈ 1.7%). Equal-weight; optional
conviction tilt to 2× base for the top 1-2 names, hard-capped at **3% single-name**. New entries
that would breach the cap are skipped or force a trim of the weakest open lotto.

**REGIME SCALING — the dynamic risk dial (biggest lever).**
`CAP_effective = CAP × regime_mult`, regime from the SPY trend signal already shipped:
risk-on (SPY ≥ flat / above short MA) → 1.0; chop (flat/mixed) → 0.5; **confirmed downtrend
(SPY ≤ −1.5%/wk or below 20-MA) → 0.0-0.25**. In a downtrend the right lotto book size is
≈ zero — they don't work and they all fail together.

**GUARDRAILS.**
- *Kelly ceiling*: per independent bet, f* = p − (1−p)/b. For p≈0.30, b≈5 (avg winner ~5×),
  f* ≈ 0.30 − 0.70/5 = 0.16; **¼-Kelly ≈ 4% per independent bet × ~3 bets ≈ 12% book** — which
  is why the 12% cap is Kelly-sane, not arbitrary. Never exceed ¼-Kelly even if the cap allows.
- *Drawdown circuit breaker*: lotto book down ≥20% from its peak → halve CAP until a winner
  resets. Trigger on **capital drawdown, not streak length** (a streak of total losses is
  *expected* at 40% WR; a 20% book drawdown means the regime may have turned).

## 4. Risk management & monitoring

Monitor in real time (these are the dials):
- **Current lotto exposure** = book_risk / capital (vs CAP_effective). The single most important number.
- **N concurrent lotto positions** (a soft proxy; >~8 is a yellow flag).
- **Regime** (risk-on/chop/downtrend) and the resulting CAP_effective.
- **Lotto-book drawdown from peak** (drives the circuit breaker).
- **Single-name concentration** (no name > 3%).

Robust rules that prevent catastrophe (in priority order): (1) the hard book cap, (2) the
regime kill-switch, (3) the single-name ceiling, (4) the drawdown breaker. Any one of these
alone would have blunted the 52-position episode; together they make it structurally impossible.

## 5. Implementation & phased rollout

**Data needed (mostly already available):**
- Open lotto exposure → trade tracker / broker positions; classify "lotto" = single-name call,
  moneyness ≥ ~+5% OTM, DTE ≤ ~45. (Build this classifier once.)
- SPY regime → the `_tape_caution` / SPY-trend signal already shipped in `mir_tp_window.py`.
- Capital base → user-set config.

**Integration:** this is the natural next block in the Mir TP-Window alert + a small UI tile.
It reuses the regime signal already in place; the only new piece is the exposure aggregator.

**Phased rollout (conservative → live):**
- **Phase 1 (MONITOR, zero-risk):** compute + display current lotto exposure vs cap + regime in
  Telegram/UI. Warn when over cap. No gating. (Mirrors how the exit-discipline block shipped.)
- **Phase 2 (SOFT GATE):** new alerts that would breach the cap say "at X% vs Y% cap — skip/trim."
- **Phase 3 (REGIME-SCALED + BREAKER):** CAP scaled by regime, drawdown breaker active — still
  guidance, never auto-trade.

## Key risks & limitations
- Correlation is regime-dependent and **spikes toward 1 in crashes** → the cap is set for stress
  ρ≈1; if anything err smaller.
- Expectancy (+40-57%) is from 2026 / king-migration-style entries — the *true* edge is uncertain;
  size as if the edge is smaller than measured.
- Kelly inputs (p, b) are small-sample/biased → the ¼-Kelly discount is doing real work; do not
  raise it.
- This controls *ruin*, not *edge*. It won't make a beta book profitable — it makes it
  *survivable* so the right tail can pay over many cycles.

## Next steps
1. Build the **lotto classifier + exposure aggregator** (the one new data piece).
2. Ship **Phase-1 monitor** in the Mir TP-Window alert (exposure % vs cap + regime), reversible flag.
3. Backtest the cap+regime rules on 2026 by reconstructing a daily lotto book from the entries we
   have, measuring max drawdown WITH vs WITHOUT the cap (expect a large DD reduction for a small
   expectancy give-up — the same expectancy/tail-vs-survivability trade we quantified for exits).
4. Only after the monitor + backtest, consider the soft gate.

## Update 2026-06-21 — post-backtest (docs/research/SIZING_CAP_BACKTEST_FINDINGS.md)
- **Backtest DONE** (step 3, ran first per the user's priority order). Reconstructed 1,523 king-up
  lotto trades Jan–Jun '26, real option paths. **An uncapped book BANKRUPTED in Q1 (−138% MTM DD,
  crossed −100% in March); the cap+regime book survived (max DD 26%, Calmar 1.41 > no-discipline
  1.19).** Honest nuance: ruin-avoidance is mostly "deploy less" (scale-invariant); the **regime
  overlay** is the only piece that beat deleveraging on a risk-adjusted basis.
- **DROPPED: the drawdown circuit breaker.** It de-risked into the March/June lows and missed the
  V-recovery → return −5.6%, Calmar −0.28. Do NOT ship a "halve cap after −X% DD" rule on this
  mean-reverting fat-tailed book. (Guardrail #4 in §3 above is hereby retracted pending rework.)
- **SHIPPED: Phase-1 monitor** (step 2) in `server/mir_tp_window.py` — a "💰 LOTTO EXPOSURE CAP"
  block showing today's regime-scaled cap (risk-on 12% / chop 6% / downtrend 3%), flag `MIR_LOTTO_
  MONITOR` (default on), optional $ via `MIR_LOTTO_CAPITAL`. **Display-only, never gates.** It shows
  the CAP, not the user's actual premium-at-risk — the latter needs a live broker position feed
  (the "lotto classifier + exposure aggregator", step 1, deferred until a real positions source exists).
- **Recommended ruleset going forward:** concurrent-exposure cap + regime scaling (S2). Equal-weight
  within the cap, 3% single-name ceiling. No breaker.
