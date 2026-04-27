# Cross-LLM Synthesis — 4-Review Adversarial Critique

*Sun Apr 26 2026 evening. Synthesis of adversarial reviews from Grok, ChatGPT, Perplexity, and Gemini on the GammaPulse system as of post-Phase-5 build. Each LLM was given the same SYSTEM_FULL_WRITEUP_FOR_LLMS.md prompt.*

## Executive verdict

The system is **architecturally strong but quantitatively self-deceiving** in ways the 4 LLMs converge on with high confidence. The "empirical wins" (72% pooled hit, IV-rank gate edge, macro pivot 0 false positives) are heavily inflated by survivorship bias, in-sample parameter selection, multi-signal scoring degrees of freedom, and unmodeled execution friction.

**The 4 LLMs converge so consistently that the next session has a clear mandate.** Three structural fixes (point-in-time cohort, dynamic shrinkage, slippage model) AND one missing dimension addition are the unambiguous priorities — with all 4 LLMs validating from independent angles.

The unique value each LLM added:
- **Grok:** Liquidity gate framing, Zweig Breadth Thrust raised
- **ChatGPT:** "3 factors disguised as 10" structural collinearity insight + cross-sectional dispersion as missing dimension
- **Perplexity:** Cite-heavy academic backing (Novy-Marx, Daniel-Moskowitz, Heston 2023, Harvey/Liu/Zhu) + momentum crash literature framework
- **Gemini:** **Strongest critique overall** — Whaley Breadth Thrust as smarter ZBT alternative, PFOF math, dynamic shrinkage formula (James-Stein), VEX as entry gate, PEAD as missing dimension, dual-threshold hysteresis specifics

---

## Part 1 — Locked items (4-of-4 convergence)

These ship with high confidence regardless of other considerations.

### L1. Cohort selection bias is the dominant overfit risk
**Fix:** Point-in-time reconstitution of the QM × Minervini screen on each historical day. Not a "20 random S&P names" test (Grok) — Gemini correctly upgraded this to dynamic universe rebuilding.

**Implementation:**
- For each historical date 2024-2026, apply the Qullamaggie + Minervini screen using only data available at that time
- Track entries AND drop-outs (cohort changes weekly)
- Backtest forward returns on the rolling cohort, not the static-19
- If hit rate drops from 72% to 55-60%, the gap is the survivorship-bias inflation

**Time:** 3-4 hours (refactor existing backtest engine)
**Validates:** Whether the system has structural momentum edge or just selection bias

### L2. Conditional base rate -2pp signal is statistical noise
**Math:** Z = -2pp / 1.5pp SE = -1.33, p ≈ 0.20. With 49 cells × 3 horizons = 147 tests, false discoveries are guaranteed at p<0.05. Required Z > 2.0 (Gemini) or t > 3.3 with Bonferroni (Perplexity).

**Fix:** Keep the 49-cell grid as DASHBOARD CONTEXT only. Never use as sizing modifier. Enforce Z > 2.0 minimum threshold before any cell deviation can influence sizing decisions.

**Time:** 10 minutes (remove the modifier output from `conditional_base_rates.lookup_today()`)

### L3. VEX stays out of sizing modifiers — but Gemini upgrades the use case
**Convergence:** All 4 say don't promote VEX to a sizing multiplier.

**Gemini extension (worth shipping):** Use VEX as **entry-zone gate** instead:
- **Positive VEX regime** (puts OTM, dealers buy dips): restrict entries to **Zone A pullbacks** (dealers fade breakouts)
- **Negative VEX regime** (puts ITM, dealers sell dips): allow **Zone B breakouts** (dealers chase momentum)

This is more decision-leveraging than "observation only" without entering the sizing cascade.

**Time:** 1 hour (modify entry zone selection in signals.py based on VEX state)

### L4. Multi-timeframe ladder is wrong — use hysteresis instead
**Convergence:** ChatGPT, Perplexity, Gemini all converge on hysteresis (3-cycle persistence or dual-threshold bands). Gemini upgrades to specific math: activate at +25, deactivate at -25 (concrete dead-band).

**Fix:** Implement dual-threshold hysteresis in cell_history.py state engine. State change requires either:
- 3 consecutive cycles in new state (simpler), OR
- Crossing the dual-threshold band (e.g., BULL activates at NYMO > +25, deactivates only at NYMO < -25)

**Time:** 30 min - 1 hour
**Replaces:** The multi-timeframe ladder build proposed for the day-trader feedback

### L5. Multicollinearity in sizing cascade is structural — use min(), not multiplication
**Convergence:** ChatGPT explicitly ("3 factors disguised as 10"), Perplexity formally (Novy-Marx multi-signal bias), Gemini quantitatively (table of correlated modules).

**Fix:** Replace stacked size_modifier multiplication with `min()` semantics across all macro constraints. If breadth says 50%, stress says 25%, alignment says 70% → take 25% (most restrictive). Ignore the rest.

**Time:** 30 min (refactor paper_trading.py sizing layer)
**Replaces:** The "wire macro_context modifiers into auto-trade" item that was on the queue

### L6. Composite circuit breaker — defer until live data
**Convergence:** All 4 agree: not enough live data to test the WR + PF composite. Wait ≥10 trading days post-Phase-2 live operation before designing.

**Fix:** No action needed. Stays on backlog with explicit "data wait" tag.

---

## Part 2 — High-confidence items (3-of-4 convergence)

### H1. Slippage model in vega-adjusted PnL — Gemini's PFOF math seals it
**Convergence:** Grok flagged it, Perplexity backed it with academic framework, Gemini quantified it ($0.02-0.08/leg via PFOF, $8/round-trip per contract eclipses $0.65 IBKR commission). ChatGPT alone missed it.

**Fix:** Update `backtest/vega_adjusted_pnl.py` to include $0.03-0.06/leg slippage debit on entry AND exit. Re-run threshold tuning. If IV-rank gate edge collapses to <+5pp under realistic slippage, the gate is harvesting phantom alpha.

**Time:** 1-2 hours
**Critical because:** This may invalidate previously "validated" edges. Must run BEFORE any new sizing logic ships.

### H2. Macro pivot is too strict — but solution is Whaley Breadth Thrust, NOT loosening current gates
**Convergence:** Grok, ChatGPT, Gemini agree current macro pivot misses too many bottoms (1/5 detection on real soft bottoms, with Oct 2022 + Aug 2024 + Apr 2026 missed). Perplexity says keep current AND add ZBT as complement.

**Resolved:** Gemini's Whaley Breadth Thrust (WBT) is the correct addition:
- **Trigger:** 10-day MA of A/D ratio > 1.97
- **Frequency:** Cyclical (vs ZBT's decadal)
- **History:** Fires on softer bottoms ZBT rejects
- **Computable from existing breadth_daily SQLite** (we already populated this)

**Implementation:** Add WBT as **OR gate** in parallel with current macro pivot detector. Either fires → consider macro pivot. Don't replace G1/G2/G3 — augment.

**Time:** 2 hours
**Note on user's "ZBT too lagging" instinct:** Your gut was right that pure ZBT is too rigid; Whaley is the smarter alternative.

### H3. Dynamic Bayesian shrinkage replaces hardcoded k=20
**Convergence:** Perplexity (formal LOO-CV recommendation), Gemini (James-Stein formula), ChatGPT (gestured at). Grok didn't catch.

**Gemini's formula:**
```
k_dynamic = σ²_noise / (σ²_noise + σ²_prior)

Where:
  σ²_noise  = standard error of THIS ticker's win rate (depends on sample size)
  σ²_prior  = cross-sectional variance of cohort hit rates
```

**Behavior:**
- High ticker volatility (large σ²_noise) → shrink heavily toward pooled
- Highly disparate cohort (large σ²_prior) → minimize shrinkage, trust ticker data
- Stable both → balanced shrinkage by sample count

**Time:** 1-2 hours (refactor `backtest/shrinkage.py` and integration in `compute_kelly_size`)

### H4. Slippage assumption invalidates VEX-as-sizing-modifier conclusion (already locked) AND probably invalidates Zone-A 1.2× bonus
**Implication:** After H1 ships, Zone-A 1.2× bonus needs re-validation. Perplexity flagged the n=32 Zone B sample as too small (SE ~8.4pp). Once slippage is added, the 13pp edge may shrink to <8pp = noise.

**Fix:** Hold Zone-A 1.2× bonus pending H1 + re-validation. May need to demote to "tie-breaker only" if slippage absorbs most of the edge.

**Time:** Re-run after H1 (~30 min)

---

## Part 3 — Split decisions with judgment calls (2-of-4 or unique)

### S1. Stress composite size_modifier output: REMOVE entirely
**Convergence partial:** Grok, ChatGPT, Perplexity say "context only, not sizing." Gemini says "remove from cascade entirely."

**Decision:** Remove the `size_modifier` output from `stress_composite.get_stress_composite()`. Keep the band classification + score for dashboard display only. The blocks_new_longs flag at >80 stays as Boolean override (per L5 min() logic).

**Time:** 10 min

### S2. Biotech IV-rank handling — Gemini's catalyst-API approach is best long-term, hierarchical shrinkage is short-term
**Split:** Grok said sector-specific shrinkage (k=40), ChatGPT said hierarchical Bayesian, Perplexity said quantify event-driven IV %, Gemini said clinicaltrials.gov catalyst API + long-straddle routing.

**Decision:**
- **Short-term (this week):** Replace hard exclusion with Perplexity's quantification — compute % of IV-spikes within 14d of FDA catalyst per ticker. If >50% for biotech, principled exclusion.
- **Long-term (Phase 7+):** Gemini's catalyst-API integration with long-straddle routing module.

**Time:** 1 hour short-term, 4-6 hours long-term

### S3. Universe expansion to 1500 NYSE — KEEP on queue, NOT critical
**Split:** Perplexity said priority #1, Grok said cut, ChatGPT said cut. Gemini didn't address.

**Decision:** Defer. The Oct 2022 NYMO +4 anomaly is annoying but doesn't change the macro pivot decisions. The point-in-time cohort reconstruction (L1) is more important and will reuse the same yfinance batch infrastructure.

---

## Part 4 — Missing dimensions (one per LLM, all non-redundant)

Each LLM identified a different orthogonal information source we lack. **All four are worth incorporating** but priority order:

| # | LLM | Dimension | Time | Priority |
|---|---|---|---|---|
| 1 | **Gemini** | **PEAD (Post-Earnings Announcement Drift)** | 3-4 hr | **HIGHEST** |
| 2 | Perplexity | Momentum crash indicator (Daniel-Moskowitz) | 1.5 hr | HIGH |
| 3 | Grok | Liquidity gate (pre-entry option volume + bid-ask) | 2 hr | HIGH |
| 4 | ChatGPT | Cross-sectional dispersion (regime character) | 2 hr | MEDIUM |

### M1. PEAD (Gemini-unique) — highest leverage
**Why it's #1:** Currently we BLACKLIST the post-earnings window as "earnings blackout." Gemini correctly identifies this as the highest-EV entry zone:
- IV is cheap (just crushed)
- Directional drift probability is high (well-documented academic anomaly)
- We hold 1-90 days — perfectly aligned with PEAD's drift timeline

**Implementation:**
- Add `Zone D: Post-Earnings Drift` as new entry catalyst
- Trigger: surprise EPS beat > 5% AND volume > 2× 20d avg ON earnings day
- Entry window: days +1 to +5 after earnings
- IV-rank gate: REVERSED — favor LOW IV-rank entries (cheap premium + high directional probability)

**Time:** 3-4 hours (new catalyst module + earnings data integration)

### M2. Momentum crash indicator (Perplexity-unique)
**Daniel-Moskowitz 2016 framework:** Rolling 21d realized variance of cohort × bear-state proxy.
- Compute: 21d realized vol of equal-weight cohort portfolio
- Threshold: ratio to long-run median > 2.0
- Combined with: SPY 126d return < 0
- Action: 0.5× sizing modifier when both conditions hit

**Time:** 1.5 hours
**Why critical:** Direct answer to your existential 2022 concern. Computable from yfinance.

### M3. Liquidity gate (Grok-unique)
**Implementation:**
- Pre-entry check: average daily option volume > $2M notional on the strikes considered
- Spread filter: ATM bid-ask < 8% of premium
- For cohort names with thin chains (LASR, AAOI, AESI in particular), this gate may block 30%+ of would-be entries — that's the point

**Time:** 2 hours
**Note:** Gemini's PFOF slippage critique (H1) is the BACKTEST-side version of this; M3 is the LIVE-side enforcement.

### M4. Cross-sectional dispersion (ChatGPT-unique)
**Implementation:**
- Daily compute: cross-sectional std dev of cohort returns vs trailing 60d median
- Plus: % of cohort outperforming SPY (top decile spread)
- Use as global throttle: HIGH dispersion = momentum regime → full size; LOW dispersion = mean-revert regime → 0.5× size

**Time:** 2 hours
**Lower priority:** Most useful when momentum/mean-rev regime is changing. We have other regime detectors that overlap somewhat.

---

## Part 5 — Where each LLM was wrong or weak

| LLM | Notable mistakes |
|---|---|
| Grok | Sparse citations; "0/7 false positives is overfitting" framing was half-right but missed that the design choice was Perplexity-informed, not arbitrary |
| ChatGPT | Missed slippage entirely (Grok+Perplexity+Gemini caught it); said "Telegram alerts wasted" — disagree, real-time alerts on macro pivots have value; rolling cohort recommendation good but bootstrapping issues at boundaries |
| Perplexity | Slight self-contradiction (said universe expansion #1 priority but also said held-out test "most asymmetrically valuable"); recommendations to add option momentum AND PEAD-adjacent signals risk frankenstein |
| Gemini | Brilliant overall — minor weakness: NET (Noise Elimination Technology) recommendation may be overengineered vs simple hysteresis; biotech catalyst API integration is heavy ($30+/mo data sub or scraping clinicaltrials.gov) |

---

## Part 6 — Refactored Phase 6 priority queue

Based on full 4-LLM synthesis. Cuts and adds explicit.

### Phase 6A — Foundational validation (do FIRST)
| # | Item | Hours | Why first |
|---|---|---|---|
| 6A.1 | **Slippage model in vega_adjusted_pnl** (H1) | 1-2 | Verify all prior edges survive realistic execution before building anything new |
| 6A.2 | **2022 historical replay** (your existential concern) | 3-4 | Empirical answer to "would this survive a sustained bear" — uses yfinance + populated NYMO + Phase 1+2 deterministic gates |
| 6A.3 | **Point-in-time cohort reconstruction** (L1) | 3-4 | Quantifies survivorship bias inflation in pooled hit rate |

After 6A, we know: (1) what the system's edge actually is net of execution, (2) how it would have performed in a real bear, (3) how much of the cohort edge is structural vs selection.

### Phase 6B — High-confidence ships (after 6A validates)
| # | Item | Hours | Source |
|---|---|---|---|
| 6B.1 | **Hysteresis dual-threshold bands** (L4) | 30 min - 1 hr | All 4 LLMs |
| 6B.2 | **min() semantics for sizing modifiers** (L5) | 30 min | All 4 LLMs |
| 6B.3 | **Kill -2pp base rate sizing modifier** (L2) | 10 min | All 4 LLMs |
| 6B.4 | **Stress composite size_modifier removal** (S1) | 10 min | 3-of-4 LLMs |
| 6B.5 | **VEX as entry-zone gate** (L3) | 1 hr | Gemini extension |
| 6B.6 | **Dynamic Bayesian shrinkage** (H3) | 1-2 hr | Perplexity + Gemini formal |
| 6B.7 | **Whaley Breadth Thrust as OR-gate complement** (H2) | 2 hr | Gemini |
| 6B.8 | **Re-validate Zone-A 1.2× bonus post-slippage** (H4) | 30 min | Implication of 6A.1 |

### Phase 6C — New dimensions (one new layer per session)
| # | Item | Hours | Source |
|---|---|---|---|
| 6C.1 | **PEAD entry zone** (M1) | 3-4 hr | Gemini (highest leverage) |
| 6C.2 | **Momentum crash indicator** (M2) | 1.5 hr | Perplexity |
| 6C.3 | **Liquidity gate** (M3) | 2 hr | Grok |
| 6C.4 | **Cross-sectional dispersion** (M4) | 2 hr | ChatGPT |

### Phase 6D — Operational (defer until 6A-C land)
- Daily refresh cron (~1 hr)
- Telegram alerts for macro pivot fires + regime shifts (~1 hr)
- Universe expansion to 1500 NYSE (~3 hr) — defer per S3

### CUT from queue (do not build)
- ❌ Multi-timeframe signal ladder — replaced by hysteresis (L4)
- ❌ Live integration of macro_context size_modifiers — replaced by min() override (L5)
- ❌ Composite circuit breaker — defer (L6)

---

## Part 7 — Total Phase 6 effort

| Phase | Hours |
|---|---|
| 6A (foundational validation) | 7-10 |
| 6B (high-confidence ships) | 6-8 |
| 6C (one new dimension at a time) | 8-12 spread over multiple sessions |
| 6D (operational) | 2-5 |
| **Total** | **~25-35 hours of focused work** |

That's 3-5 substantial sessions to fully execute Phase 6. Suggest spreading across 2-3 weeks with live observation periods between phases.

---

## Part 8 — The honest reality check

The 4 LLMs collectively delivered the harshest validation we could have asked for. They're saying:

1. **Most of your "validated edges" are partially or fully selection bias + in-sample tuning artifacts** (cohort overfit, k=20 hardcoded, 3-gate macro pivot fitted to 7 events)
2. **The ones that probably ARE real (breadth gate, IV-rank gate at extremes, multi-day exit discipline) survive after stripping out the noise**
3. **The 2022 replay is the existential test the system has avoided** — until that runs, defensive claims are theoretical
4. **The framework is sound** — modularity, fail-open, validation discipline, the Apr 26 IV-zone kill — those are real institutional-grade features
5. **The fix is not more rules, it's better rigor on existing rules** + 1-2 new orthogonal dimensions (PEAD especially)

Phase 6 is essentially: **Do the hard validation work we should have done before celebrating Phase 5 completion.** The good news: the LLM consensus is so strong that the priority queue is unambiguous. The bad news: 6A may invalidate things we thought were solved.

Either way, this is the correct next session. The system either survives the rigor or doesn't — both outcomes are useful.

---

---

## Part 9 — REFINEMENTS from follow-up bounces (Apr 26 evening, post-original-synthesis)

After the initial 4-LLM synthesis, follow-up research was sent to Gemini (point-in-time + dynamic shrinkage specifics) and Perplexity (PEAD academic deep-dive + Whaley calibration + PFOF slippage validation for thin chains). The findings materially change the priority queue.

### Refinement 1 — Slippage is far worse than Gemini's $0.03-0.06/leg estimate (CRITICAL)

Perplexity validated against academic + practitioner sources: Gemini's figure is calibrated to LIQUID options (SPY/QQQ/large-caps). For our cohort:

- **Thin names (AAOI/LASR/AESI/CAPR): 12-20% of premium round-trip**
- **OTM strikes specifically: 15-25% of premium**
- (ask-bid)/mid > 40% (common on our names) → 15-25% friction
- **"Any edge signal below ~15% theoretical gain is below friction cost"**

**Implication:** The IV-rank gate's measured +11pp edge at 21d in BEAR — under realistic 15-20% premium friction, the NET edge for thin cohort names could be near zero or negative. Several previously "validated" edges may not survive proper friction modeling.

**Refined fix for H1:** vega_adjusted_pnl model needs PERCENTAGE-of-premium friction, name-specific, NOT dollar/leg.

### Refinement 2 — PEAD specifics now production-ready

- **Surprise definition: analyst-consensus beat** (not raw % EPS — small-cap inflation problem)
- **Magnitude: top quintile rank** in universe, not flat threshold
- **Drift duration: front-loaded days 1-10** for liquid (MU/CIEN/GLW); **extends 21-45 days for thin small-caps** (perfect for our time-stop)
- **MU PEAD-arbitraged away** — exclude (large-cap institutional)
- **PEAD + momentum: ADDITIVE** (Chan-Jegadeesh-Lakonishok 1996)
- **52-week-high (Zone A) AMPLIFIES PEAD**
- **Execution: long debit call spread**, NOT outright calls or straddles
- **Diagonals for 45-90d small-cap drift**
- **DO NOT trade straddles** — IV market efficient on earnings

### Refinement 3 — Whaley is NOT 100% win rate (Gemini overstated)

- **ZBT** standalone: 18 fires since 1945, ~24.6% avg at 11 months, near-100% win rate at 6/12 months
- **WBT** standalone (non-ZBT-coincident): NOT 100%. Alpha concentrated in **first 1-3 months only**; 6-12m flat
- **WBT failed-thrust analogue: Oct 2020** (frothy sentiment + extreme GEX → degraded forward alpha)
- **Apr 24-25 2025 ZBT** is a confirmed real fire — should be visible in our backfilled NYMO data

### Refinement 4 — Dynamic shrinkage formula confirmed

Gemini: **k_dynamic = p(1-p) / σ²_prior** where σ²_prior is sample variance of all 19 ticker hit rates. n=0 edge case → λ=1, fall back to 100% pooled.

### Refinement 5 — Point-in-time cohort: monthly rebalance (not daily)

Critical spec: daily rebuild = signal flickering / excessive turnover. Monthly is academic standard.

### Refinement 6 — 200d MA bootstrap means first usable signal ~May 2025

If cohort data starts Sept 2024, 200 trading days warmup pushes first valid out-of-sample signal to ~May 2025. Plan validation window accordingly (May 2025 - Apr 2026 = ~12 months of usable signal).

---

## Part 10 — Updated priority queue

### NEW Phase 6A.0 (must do FIRST — before any rebuild)

| # | Item | Hours | Why first |
|---|---|---|---|
| 6A.0a | **Validate Apr 24-25 2025 ZBT against NYMO backfill** | 30 min | Confirms our backfill data quality before building anything on top |
| 6A.0b | **Per-name slippage measurement from ThetaData chains** | 2 hr | Computes the friction assumption needed for 6A.1 |
| 6A.1 | **Update vega_adjusted_pnl with PERCENTAGE-of-premium slippage** (per-name) | 1 hr | Many "validated" edges may need re-tuning under realistic friction |
| 6A.2 | **Re-tune IV-rank gate threshold under realistic slippage** | 1 hr | Direct test of whether the +11pp BEAR edge survives |
| 6A.3 | **2022 historical replay** (existential concern) | 3-4 hr | Empirical answer on 2022-style regime defense |
| 6A.4 | **Point-in-time cohort reconstruction (monthly rebalance)** | 3-4 hr | Quantifies survivorship bias gap |

If 6A.0a passes (ZBT detectable in our data) → we can validate other breadth signals on the same data.
If 6A.0a fails → we have a data quality issue that needs fixing before anything else.

---

## Part 11 — KILL-SHOT findings from Phase 6A.0 execution (Apr 26 night)

After running the slippage measurement on the 19-name cohort and applying ChatGPT's nonlinear adjustment + Grok's kill threshold (<+5pp net edge = demote/kill):

### Cohort liquidity reality

| Tier | Names | Round-trip friction |
|---|---|---|
| **LIQUID** | MU, SNDK | 6% |
| **MEDIUM** | AAOI, CAMT, CIEN, GLW, VICR | 8% |
| **THIN** | PTEN, UCTT | 14% |
| **VERY_THIN** | AESI, ANAB, CAPR, LAR, LASR, NBR, PUMP, RES, TROX | 22% |
| **UNKNOWN** | GHRS | 18% (default) |

Notably extreme spread-to-mid measurements: **CAPR 150.8%**, RES 133.3%, NBR 89.1%, ANAB 78.8%. For these names the OTM bid is roughly 40% of the ask — essentially un-fillable in size.

### Edge survival test results (with nonlinear slippage)

**IV-rank gate's claimed +11pp BEAR edge** (HIGH IV-rank × 5% OTM, where gate actually fires):
- SHIP: **0 names**
- DEMOTE: 2 (MU, SNDK)
- **KILL: 14 names**

**Zone-A 1.2× bonus's claimed +13pp 5d hit-rate edge** (ATM × neutral IV):
- SHIP: 0 names
- DEMOTE: 2 (MU, SNDK)
- **KILL: 17 names**

**Rescue scenario — IV-rank gate at ATM only:**
- SHIP: 0 / DEMOTE: 7 / KILL: 9
- Net edges +0.6 to +3.2pp on liquid/medium names — barely positive
- All VERY_THIN names still KILL

### What this means

The Apr 25-26 build assumed Phase 1-5 components had validated edges. **Under realistic friction modeling, the IV-rank gate AND Zone-A bonus are net-negative for the majority of the cohort.** The system has been saved from blowing up only by very conservative Quarter-Kelly sizing + concentration caps.

The ONE component that probably still has real edge is the breadth gate — because it BLOCKS trades rather than trying to capture options-pricing edge.

### Required production changes (now data-supported, not hypothetical)

1. **Restrict IV-rank gate to ATM strikes only AND LIQUID+MEDIUM cohort tier only**
   - Cohort universe drops from 16 → 7 names for this gate
   - Kept: MU, SNDK, AAOI, CIEN, GLW, VICR, CAMT
   - Removed: AESI, LAR, LASR, NBR, PUMP, PTEN, RES, TROX, UCTT (THIN/VERY_THIN)

2. **Demote Zone-A 1.2× size bonus to tie-breaker / observation only**
   - Remove from `paper_trading.py` sizing multiplier stack
   - Keep zone classifier output for dashboard display

3. **Restructure cohort tier list:**
   - **Primary (edge survives):** MU, SNDK
   - **Secondary (marginal edge):** AAOI, CIEN, GLW, VICR, CAMT
   - **Manual-only (phantom alpha):** AESI, ANAB, CAPR, GHRS, LAR, LASR, NBR, PUMP, RES, TROX, UCTT, PTEN
   - Auto-trade should ONLY fire on Primary + Secondary names

4. **Update vega_adjusted_pnl** to use `slippage_model.slippage_lookup()` going forward — any future "edge" claim needs to pass kill-threshold check before being shipped

### Reconciliation: the IV-rank gate is DEFENSIVE, not offensive

The vega-PnL re-run with slippage (Apr 26 night) reveals an important nuance:

| IV-rank gate position | BEFORE slippage | AFTER slippage |
|---|---|---|
| BEAR + HIGH-IV (blocked) | -62.7% median | **-80.3% median** (disaster prevention) |
| BEAR + LOW-IV (passed) | +23.3% median | +9.0% median (barely positive) |
| BULL + HIGH-IV | +10.5% median | **-12.1% median** (flipped negative) |
| BULL + LOW-IV | +93.9% median | +81.2% median (still strong) |

The "+11pp edge" framing was wrong. The gate's real function is **disaster avoidance** — it prevents the system from buying HIGH-IV calls during BEAR/TRANSITIONAL regimes where the median outcome is a -80% bleed. The "passed" trades are not strongly positive (+9-13% median in BEAR); they just avoid catastrophe.

**Implications:**
- Gate stays — it's genuinely valuable as a disaster filter
- Reframe: "IV gate prevents -80% bleeders" (not "captures +11pp edge")
- BULL + HIGH-IV findings: ship as Phase 6 candidate to ALSO block HIGH-IV in FULL_BULL? (Currently only blocks in BEAR/TRANS)
- The cohort-tier restriction (LIQUID+MEDIUM only) still applies — for thin names even the "passed" trades face 22% slippage that may negate the +9% median

### Updated Phase 6 priority queue

**Phase 6A.0 — COMPLETE today (Apr 26 night):**
- ✅ Apr 2025 ZBT validated against NYMO backfill (6/7 events)
- ✅ Per-name slippage measured (18/19 cohort)
- ✅ Slippage model with nonlinear adjustment (`slippage_model.py`)
- ✅ Edge survival test (`edge_survival_test.py`) — KILL findings documented

**Phase 6A.1 — NEXT priorities (post-tonight, before any new builds):**
1. Update `server/iv_rank_cache.py` gate logic — restrict to ATM + LIQUID/MEDIUM tier
2. Demote Zone-A 1.2× bonus in `server/paper_trading.py` — remove multiplier
3. Update cohort tier metadata + auto-trade eligibility list
4. Update `vega_adjusted_pnl.py` to use slippage_model

**Phase 6A.2 — Foundational (next session):**
5. Point-in-time cohort reconstitution
6. 2022 historical replay (with nonlinear slippage applied)
7. Dynamic James-Stein shrinkage

After 6A.1 ships: the live system will be much more conservative (auto-trade only fires on 7 names instead of 19, no Zone-A multiplier) — but every signal it fires SHOULD have positive expected value net of friction.

This is the right outcome. Better to fire less and win more than fire often and bleed.

---

## Files

**This synthesis:**
- `docs/feedback/strategy_0427_review/SYNTHESIS.md` (this file)

**Source critiques (for re-reference):**
- `docs/feedback/strategy_0427_review/grok_response.md` *(save Grok response here)*
- `docs/feedback/strategy_0427_review/chatgpt_response.md` *(save ChatGPT response here)*
- `docs/feedback/strategy_0427_review/perplexity_response.md` *(Perplexity response — already in Downloads)*
- `docs/feedback/strategy_0427_review/gemini_response.md` *(Gemini response — already in Downloads)*

**Original prompt:**
- `docs/research/SYSTEM_FULL_WRITEUP_FOR_LLMS.md`
