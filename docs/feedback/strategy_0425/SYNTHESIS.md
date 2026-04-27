# Cross-LLM Synthesis — Winner Scoring Workflow Critique

*Sat Apr 25 2026. Synthesis of feedback from ChatGPT, Grok, and Perplexity (with citations) on `WINNER_SCORING_WORKFLOW_PROMPT.md`.*

## Bottom line

All three LLMs agree on the **same two structural flaws** as the highest-priority fixes — that's the strongest possible signal. They also converge on the **same Bayesian shrinkage technique** as the fix for #1 and the **same breadth-gate mechanism** as the fix for #2.

When ChatGPT, Grok, and Perplexity independently arrive at the same critique with the same proposed solution, that is not a coincidence — it is the textbook fix. Implement those first. Everything else is judgment.

## Consensus changes (ship these first)

### #1 — Per-ticker edge is selection-bias contaminated → apply Bayesian shrinkage
**All 3 agree.** This is the single most dangerous flaw because it feeds Kelly sizing.

Replace raw per-ticker hit rate with shrinkage toward the pooled mean:

```
adjusted_p = (n × ticker_p + k × pooled_p) / (n + k)
```

Where:
- `n` = number of historical triggers for this ticker
- `ticker_p` = ticker's raw hit rate
- `pooled_p` = pooled hit rate across all cohort names (currently 72% at 21d)
- `k` = prior strength parameter

| LLM | Suggested k |
|---|---|
| Grok | 15 |
| ChatGPT | 20-40 |
| Perplexity | 20 |

**Decision: k = 20.** If `n < 10`, use 100% pooled. Implementable in 5 lines of pandas, no new data.

Also (ChatGPT-specific): cap raw inputs to Kelly at win-rate ∈ [45%, 65%] and payoff ratio b ∈ [0.8, 2.5] to prevent extreme inputs from blowing up the fraction.

### #2 — Macro at 5% is dangerously underweighted → promote to hard gate
**All 3 agree.** Regime is binary, not marginal — scoring it misses the point.

Move Macro/Regime out of Layer 3 entirely. Add to Layer 2 (screen) as a hard pre-filter:

```
breadth = % of universe (or S&P 500) above 200d MA

if SPY < SPY.SMA200 AND breadth < 40%:
    candidate_pool = []   # no new longs
elif breadth < 60%:
    eligible_grades = ["A+", "A"]  # B+ suspended
    cohort_cap = 5%               # tighter
else:
    normal operation
```

Threshold consensus: **40% breadth = no-trade gate, 60%+ = full bull, in-between = transitional.** Perplexity adds an early-warning signal: McClellan Oscillator persistently negative for 10+ days typically precedes the breadth break by 1-3 weeks.

### #3 — Replace -9.1% fixed stop with ATR-based stop
**All 3 agree.** Fixed % is instrument-agnostic; the cohort has 4-6% ATR which makes 9.1% just 1.5-2× ATR — within normal noise.

```
hard_stop = max(entry - 2.5 × ATR(20), entry × 0.88)  # capped at -12%
```

Keep the -50% premium stop on the options leg (all 3 agree this one is correct because of gamma/theta non-linearity). Drives stop calculation off underlying volatility, then maps to options PnL.

### #4 — Time-stop logic asymmetrically caps winners → conditional time stop
**All 3 agree.** The 21-day cap exits everything, including runners. Qullamaggie / Minervini both let winners run 35-90+ days using EMA trails.

```
if trade_below_breakeven_at_day_15:
    exit_by_day_21          # current behavior, correct for losers
elif trade_above_+1R_at_day_15:
    switch_to_EMA21_trail   # let runner go, exit on close < EMA21
                            # consistent with how the gurus actually trade
```

Grok adds: only extend if SPY > 200d AND breadth > 50% (don't let runners run in a regime that just shifted).

### #5 — Layer 3 has collinearity → collapse Trend + RS + Setup Pattern
**All 3 agree** components are redundant. Concrete cuts vary slightly:

| LLM | Cut #1 | Cut #2 | Cut #3 |
|---|---|---|---|
| ChatGPT | Setup Pattern (in momentum) | ATR-RS (in vol exits) | Sector/Theme (replace with breadth) |
| Grok | Volatility Posture (collinear ATR) | one RS window | Macro (→ gate) |
| Perplexity | Setup Pattern (→ qualifier) | Macro (→ gate) | Merge Trend into RS |

**Synthesis decision:** Setup Pattern → demote to Layer 5 entry qualifier (don't score, but use to break ties on Zone A vs B). Trend Quality + Relative Strength → merge into single "Momentum Composite" (25%). Macro → hard gate (already #2 above). Volatility Posture → keep for now (drives sizing reduction at high IV); revisit in 60 days.

## Divergences — judgment calls

### B+ sizing: ⅔ vs ½?
- **ChatGPT:** ½ (more conservative)
- **Grok:** ½ (matches half-Kelly logic better)
- **Perplexity:** notes the cap dominates anyway; difference is "1 contract." Calls it psychological scaffolding.

**Decision: ½.** Two-of-three vote, plus the Kelly math agrees, plus reduces variance ~15-20% with tiny expectancy hit per Grok.

### Cohort cap: hard 8% vs sector-bucket 2-3 names?
- **ChatGPT:** sector buckets (max 2-3 per sector, reduce size if >2)
- **Grok:** keep 8% but make it per-cluster, not total
- **Perplexity:** make it conditional — 8% if sector ETF extended (within 5% of 52w high), 12% if sector ETF breaking out fresh

**Decision: keep 8% per theme/sector cluster (not total) — Grok's tweak.** Perplexity's conditional is elegant but adds runtime complexity for marginal benefit. Sector buckets is clean and easy to code.

### Breadth as scored component or only as gate?
- **ChatGPT:** ±10 score adjustment OR position-size adjuster
- **Grok:** hard gate only
- **Perplexity:** BOTH — 8% scored weight AND a hard gate

**Decision: hard gate first, score later.** Start simple. If 60d of live operation shows the gate is binary-rigid and missing nuance, then layer in scoring. Don't pre-optimize.

### Per-ticker edge weight after debiasing?
- **ChatGPT:** "tie-breaker only," not sizing driver
- **Grok:** raise to 20-25% only after debiasing
- **Perplexity:** 17% (specifically calibrated)

**Decision: 15% post-shrinkage.** Splits the difference, defensible, leaves room to raise after live validation.

## Unique high-value insights (only one LLM caught these)

### Perplexity-only: IV regime mismatch with entry zones
**This is genuinely novel.** Zone A (pullback to EMA10) = consolidation = compressed IV = good for options buyers. Zone B (breakout on volume) = IV spike = expensive options. Your current sizing puts MORE size at Zone B — exactly backwards for options.

**Proposed fix:** For options specifically, take ½ at Zone A (low IV) and only add at Zone B if IV-rank < 50 that day. If IV-rank > 50 at Zone B, skip Zone B and wait for next pullback.

**Action:** Worth a separate small backtest — pull historical IV-rank at Zone A vs Zone B trigger days for the cohort, see if the inversion is empirically supported. If yes, ship as Layer-5 modification.

### Perplexity-only: McClellan Oscillator as breadth early-warning
NYSE McClellan turning persistently negative (10+ days) historically precedes breadth break by 1-3 weeks. Free data on StockCharts. Functions as a "throttle" before the full gate trips.

**Action:** Add to dashboard as an info widget, not yet a gate. Watch behavior for 60d before promoting to logic.

### Perplexity-only: Theta-rate based options time stop
For options, the relevant clock is theta burn rate per day, not calendar days. Exit when daily theta exceeds 0.5% of premium AND no 1R reached. ThetaData has this.

**Action:** Defer to Phase 2. Layer-6 logic complexity should not increase before debiasing + breadth gate ship.

### Grok-only: Cap edge inputs to prevent Kelly explosion
Cap win rate input ∈ [45%, 65%] and payoff b ∈ [0.8, 2.5] before passing to Kelly. Prevents a single noisy +90% trade from inflating the win-loss ratio enough to break sizing.

**Action: Ship with shrinkage in Phase 1.**

### ChatGPT-only: 10-day rolling win-rate as second early-warning
If breadth < 40% AND 10-day rolling system win rate < 45% → halve all sizing globally + disable Zone B/C. Acts as a "live performance circuit breaker" complementing the breadth gate.

**Action:** Trivial to add to discipline layer. Ship in Phase 1.

## Phased implementation plan

> **Update from Perplexity follow-up (Apr 25 evening):**
> - 10-day rolling win-rate circuit breaker is **YELLOW, not green**. Win rate alone is a noisy control metric — a momentum system can have a bad 10-day win rate while still positive expectancy if losses are small and winners large. Pure win-rate breakers can sideline you right before the real move starts. **Fix:** redefine as composite breaker requiring BOTH low rolling win rate AND low rolling profit factor (or avg R). Defer to last in Phase 1.
> - Recommended ship order (refined): Breadth gate → Shrinkage → Kelly clipping → ATR stop → B+ to ½ → THEN test composite breaker.
> - Caveat on cross-LLM consensus: convergence is useful for prioritization but **is not validation**. The right next step is "ship the high-confidence items, then measure pre/post live-paper behavior over 30-50 trades" — not "believe the consensus harder."

### Phase 1 — Ship this week (refined order per Perplexity follow-up)
1. **Breadth gate** at Layer 2: %above-200d < 40% → no new longs; 40-60% → A/A+ only
2. **Bayesian shrinkage** on per-ticker hit rates (k=20, n<10 → pooled-only)
3. **Cap Kelly inputs** [win-rate 45-65%, payoff 0.8-2.5]
4. **ATR-based hard stop** (-2.5×ATR, capped at -12%)
5. **B+ sizing** to ½ (from ⅔)
6. **Composite circuit breaker** (NOT win-rate alone): pause new entries when (10d rolling win-rate < 45% AND rolling profit factor < 1.0) — the AND condition prevents being sidelined during a momentum cluster of small losses before a runner. Last item in Phase 1, ship only after items 1-5 are live for ≥10 trading days.
7. ~~**IV-zone inversion** for options sizing~~ **KILLED Apr 26 (full 19-name validation).** Definitively rejected on 3,726 daily bars with real ATM-30DTE IV: Zone A IV-rank median 0.56 vs Zone B 0.52, Welch t=0.47, p=0.64 (no robust difference). The realized-vol proxy that drove the Apr 25 finding correlates only +0.18 with real IV (essentially noise). **However**, the Zone A *hit-rate* edge survived and strengthened: 77.6% vs 64.5% at 5d, 80.2% vs 67.7% at 10d, 77.3% vs 70.0% at 21d (n=136 Zone A, n=32 Zone B). New Phase-2 candidate: Zone A as a hit-rate priority signal (NOT an IV-pricing rule). New Phase-3 candidate: IV-rank itself as an independent factor — LOW-IV days show +11pp hit-rate edge at 21d. See [docs/research/iv_zone_validation_FINAL.md](../../research/iv_zone_validation_FINAL.md).

### Phase 2 — Ship within 2 weeks (consensus but more involved)
7. **Conditional time stop** — winners on EMA21 trail beyond day 21
8. **Collapse Trend + RS** into Momentum Composite (25%)
9. **Demote Setup Pattern** from scored component to Zone qualifier
10. **Sector-bucket cap** (max 2-3 per sector cluster, replaces flat 8%)

### Phase 3 — Validate first, then add (Perplexity-uniques)
11. **McClellan early-warning** — add as dashboard signal, watch 60d, then promote
12. **Real-IV validation** of zone inversion — spot-check ThetaData ATM IV history on 30-50 sample of Zone A vs Zone B days, confirm proxy was directionally correct

### Phase 4 — Defer indefinitely (low ROI per all 3)
- Sentiment / options-flow as scored component (qualifier only)
- Short interest / float rotation
- Per-trade theta-rate exit on options (revisit if Phase 1-3 work)

## Updated Layer 3 weights (target state after Phase 2)

| Component | Old | New | Notes |
|---|---:|---:|---|
| Momentum Composite (Trend + RS merged) | 35 | 25 | Was 20+15, collinear |
| Volume Confirmation | 10 | 10 | Unchanged |
| Volatility Posture | 10 | 10 | Keep for sizing reduction at high IV |
| Setup Pattern Match | 10 | 0 | Demoted to Zone qualifier |
| Earnings Distance | 10 | 15 | Bumped — clean discontinuity, options-relevant |
| Sector/Theme Confirmation | 10 | 10 | Unchanged |
| Backtested Per-Ticker Edge (debiased) | 10 | 15 | Raised after shrinkage applied |
| Macro/Regime Filter | 5 | 0 | Promoted to Layer 2 hard gate |
| **Breadth (new)** | — | 15 | New — and also a hard gate at <40% |
| **Total** | 100 | 100 | |

## What to NOT change (all 3 LLMs validated these)

- Half-Kelly + 3% cap + 0.25% floor structure (perfectly coherent for retail book)
- -50% premium stop on options leg (correct given gamma/theta non-linearity)
- Mandatory pre-earnings exit
- Daily/weekly circuit breakers (-2.5%/day, -5%/week)
- Position-count cap of 8 open
- Post-trade journal structure
- Tier-based universe refresh cadence

## The honest read

All three LLMs separately concluded the system is "one of the cleanest solo retail workflows" they've seen. They also separately concluded that **two flaws are doing the heavy lifting on downside risk**: per-ticker selection bias and regime blindness. Fix those and the variance of outcomes drops materially. Everything else is polish.

The 2022-scenario consensus is sobering: in the current state this system would generate 5-15 false A+ candidates per week during a bear-rally regime, fire Kelly-sized positions on them, and bleed through 2-3 circuit breakers before the macro factor accumulated enough scoring weight to matter. The breadth gate is the single change that prevents that scenario.

Phase 1 is implementable in a single coding session. The expected impact is materially lower drawdown variance with ~95% of current upside expectancy preserved.
