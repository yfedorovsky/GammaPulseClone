# GammaPulse — Full System Write-up for External LLM Critique

*Sun Apr 26 2026. Updated post-session covering Phases 1-5 and ~25 modules shipped today. Paste this into Perplexity / ChatGPT / Gemini / Grok.*

**Critique prompt:**
> Critique this end-to-end retail-options trading system. I want adversarial review: where is it overfit, where is it under-validated, where am I deceiving myself with empirical "wins" that won't survive out-of-sample? Where is the next high-leverage improvement, and where is wasted complexity I should cut? Be specific with citations or empirical reasoning, not platitudes.

---

## Part 1 — Who I am and what I'm building

Solo retail options trader. Trade primarily defined-risk options (calls, puts, occasional spreads) on US equities. Account size $50-200K notional. Position sizing 1-5% per trade with concentration caps. Hold periods 1-90 days depending on setup. Execute via E-Trade and Tradier API.

GammaPulse is my home-built system covering signal generation, scoring, sizing, exits, and discipline. It is *running production code*, not a sketch — every module described below has shipped, been smoke-tested or backtested, and is wired into the live signal pipeline (or deliberately kept as a context-layer when wiring would risk double-counting).

The system focuses on a **19-name momentum cohort** (Qullamaggie × Minervini joint screener):
AAOI, AESI, ANAB, CAMT, CAPR, CIEN, GHRS, GLW, LAR, LASR, MU, NBR, PTEN, PUMP, RES, SNDK, TROX, UCTT, VICR

Plus a wider 400-ticker universe for breadth/regime calculations.

## Part 2 — Data stack (paid + free)

| Source | Cost | What we use it for |
|---|---|---|
| ThetaData Options Standard | $80/mo | Real-time options chains, IV per contract, OPRA flow, historical IV for cohort |
| EODHD options Marketplace | $29/mo | Historical chain CSVs (have 16 months for 4 cohort names) |
| Massive (Polygon) | already paid | NYSE/NASDAQ A/D, grouped daily — used for live NYMO/NAMO via existing breadth.py |
| yfinance | free | Daily OHLC for any ticker, full universe %above-200d MA, NYMO backfill |
| FRED | free | Macro data (we don't use much currently) |
| Tradier | broker | Live execution + chains |
| Discord (sentiment-only) | $20/mo | One trader's Discord with discretionary signal commentary |
| Claude Max | sub | Code/research assistance (this conversation) |

**Explicit cost discipline:** evaluated AION ($500/mo) and SentimenTrader ($79-99/mo) — declined both. Built the equivalent ourselves at $0 marginal cost.

## Part 3 — Architecture overview

The system is a **layered cascade** that takes a candidate signal and runs it through gates / modifiers / scoring / sizing / exits. Each layer is independently testable; each is fail-open (helper module errors → legacy logic runs, signals don't get silently dropped).

```
RAW SIGNAL
    │
    ▼
┌─ Layer 1: Universe ──────────────────────────────────────┐
│  TIER_1 (~50, every cycle), TIER_2 (~120, every 2 cycles)│
│  TIER_3 (~230, every 4 cycles)                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 2: Hard Gates (PRE-SCORING) ──────────────────────┐
│  • Earnings blackout (within 7 days)                      │
│  • Breadth regime gate (P1#1):                            │
│      BEAR (<40% above 200d) → block all BULL              │
│      TRANSITIONAL (40-60%) → block B/B+                   │
│      FULL_BULL_WARNING (60%+ AND McClellan persist neg)   │
│         → block B grade                                    │
│      FULL_BULL → all eligible                              │
│  • IV-rank regime gate (P2#2):                            │
│      In BEAR/TRANSITIONAL: block BULL when ATM 30D        │
│      IV-rank > 0.66 (cohort + non-biotech only)           │
│  • Direction filter (BEAR signals blocked when SPY 20d>0) │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 3: Scoring (SOE / GEX / Mir) ─────────────────────┐
│  Existing scoring engine produces letter grades:          │
│    A+ (≥90), A (80-89), B+ (70-79), B (60-69), C/D       │
│  Components: trend, RS, volume, IV posture, setup        │
│  pattern, earnings distance, sector confirmation, etc.    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 4: Sizing ─────────────────────────────────────────┐
│  Quarter-Kelly with empirical-Bayes shrinkage (P1#2):     │
│    p_adj = (n × p_ticker + 20 × p_pooled) / (n + 20)     │
│    Below n=10 → 100% pooled                              │
│  Kelly input clipping (P1#3):                            │
│    win_rate ∈ [45, 65]%, payoff b ∈ [0.8, 2.5]           │
│  Grade size multiplier (P1#5):                            │
│    A+/A → 1.0×, B+ → 0.5×, B → 0.33×, C/D → 0           │
│  Zone-A bonus (P2#3): cohort + Zone A + BULL → 1.2×       │
│  Hard caps: 3% per name, 5% on UNPROVEN, 8% bucket       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 5: Position Caps ─────────────────────────────────┐
│  Sector-bucket cohort cap (P2#4):                         │
│    PHOTONICS 3, MEMORY 2, OFS 2, MATERIALS 2, BIO 2       │
│  Max-pay discipline gate (won't pay above prior cap)      │
│  Min-DTE gate (DTE ≥ 3 unless scalp setup)                │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 6: Entry & Stop ──────────────────────────────────┐
│  Entry: zone A (pullback), B (breakout), C (chase)        │
│  Stop: ATR + DTE + IV scaled, 1.5%-8% of underlying       │
│         (already production; cross-LLM ATR=2.5×/-12% cap  │
│         is the helper but live system is more conservative)│
│  Premium stop: -50% on options leg                        │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 7: Exit Cascade ──────────────────────────────────┐
│  1. EXPIRED                                                │
│  2. TARGET_HIT (spot)                                      │
│  3. STOP_HIT / STOP_BE                                     │
│  4. TIME_STOP_21D (P2#5): close losers @ day 21;          │
│     extend winners on existing trail when                 │
│     FULL_BULL + breadth>50% + currently winning + MFE≥+1R │
│  5. 0DTE_EOD (3:55 PM cleanup)                            │
│  6. WORTHLESS / OPT_LOSS_CAP / OPT_FLOOR                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 8: Discipline ────────────────────────────────────┐
│  Circuit breaker: 2 consec losses L1, 3 L2, 5 L3 (week)   │
│  Daily/weekly book caps                                   │
│  Composite circuit breaker (deferred): wait ≥10 trading   │
│     days post-Phase 2 for live data, then test            │
│     (rolling_10d_WR < 45% AND rolling_PF < 1.0)           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
EXECUTE (paper auto-trade for A+/A; manual for B+/macro pivot)
```

In parallel to this cascade, a **macro context layer** runs as observation (NOT yet wired into auto-trade gates):

```
┌─ Macro Context (Phase 4 — observation only) ────────────┐
│  Regime alignment counter: 8 signals voted BULL/NEUT/BEAR│
│     → dominant + alignment_pct + size_modifier (0.5-1.0) │
│  Stress composite (0-100): inverse breadth + NYMO + VIX  │
│     + drawdown weighted blend; 5 bands; size_modifier;   │
│     blocks new longs at >80                               │
│  Conditional base rate forecasts: 33-yr SPY history,     │
│     49 regime cells (4 trend × 4 VIX × 4 drawdown),      │
│     hit rate + avg return at 3/10/20d horizons,          │
│     Bayesian shrinkage when N<100, SE displayed          │
│  Macro pivot detector: 3 hard gates required             │
│     G1 EXTREME_OVERSOLD: NYMO ≤-60, breadth ≤30%, VIX≥25 │
│     G2 DE_ESCALATION: 5d breadth↑ + NYMO higher-low      │
│         + VIX < 10d MA                                    │
│     G3 VIX_CONTANGO_FLIPPING: ratio ≤1.0 OR dropped≥5%   │
│         + Phase 5 VEX confirmation (ALIGNED/DIVERGENT)    │
│  VEX confluence layer (Phase 5):                          │
│     SPX/SPY only, vanna direction below/above spot,      │
│     GEX-VEX alignment classifier (ALIGNED/DIVERGENT)     │
└─────────────────────────────────────────────────────────────┘
```

Each Layer 1-7 component is shipped, tested, integrated. The Macro Context is shipped but observation-only pending double-clip analysis with the existing gates.

## Part 4 — Validation & empirical results

### Cohort backtest (foundational)
- 19 names × 2y daily history = 645 historical "trigger" days matching same screen as today
- Pooled forward returns: **72% hit / +10.6% avg @ 21d**
- Per-ticker dispersion huge: AAOI +37% vs AESI -15% at 21d
- Validated the cohort screen has real edge; per-ticker base rates need shrinkage

### IV-zone inversion (validated AGAINST a Perplexity hypothesis)
- Original Apr 25 proxy backtest: realized-vol-rank below at Zone A vs Zone B, p<0.0001
- **Apr 26 ground-truth IV validation killed the original claim:** real IV-rank Zone A median 0.56 vs Zone B 0.52, Welch p=0.64 (NOT significant)
- Realized vol proxy correlates only +0.18 with real IV — was measuring noise
- BUT: the **Zone A hit-rate edge survived** — 77.6% vs 64.5% at 5d (n=136 / 32). Shipped as 1.2× bonus per Phase 2.
- Crucial: the original recommendation would have been WRONG. Validation prevented a wrong sizing change.

### IV-rank regime conditioning (Phase 3 deep-dive)
- 13/17 cohort tickers show LOW > HIGH IV-rank at 21d hit rate (median +12pp)
- Effect is **regime-dependent**:
  - SPY_BULL: +7pp gap (mild)
  - SPY_BEAR: **+59pp gap** (HIGH-IV is 33% hit / -7.31% avg)
- Implementation: regime-conditional gate, NOT a flat scored component
- Biotech (ANAB/CAPR/GHRS) shows reverse pattern → excluded from rule

### Vega-adjusted options PnL (Phase 3 #3)
- Black-Scholes simulator: 21-day ATM-call PnL with 40% IV mean-reversion
- Threshold tuning: peak edge at IV-rank > 0.66 (current production value)
- BEAR + HIGH-IV options: **-62.7% MEDIAN call PnL, 29.7% win rate** — vega decay AMPLIFIES the equity-side weakness
- Confirms IV-rank gate is doing real work in options PnL terms (not just equity returns)

### Macro pivot detector backtest (Phase 4 #4 + Phase 4.5 backfill)
- 1,838 NYSE bars from 2019-01-02 to 2026-04-24 (yfinance backfill, 5× scaled to match real $NYMO std~60)
- Tested 7 historical events (COVID 2020, June 2022 trap, Oct 2022, SVB Mar 2023, Oct 2023, Yen Aug 2024, Apr 2026)
- Result: **1 true positive (COVID), 0 false positives** (June 2022 correctly avoided despite G1+G3 firing — G2 saved us)
- Avg 90d return on FIRE: +45.95%
- 4 misses are SOFTER bottoms that should be caught by cohort momentum signals, not the once-per-cycle macro bet
- **Calibration is intentional: 0 false positives traded for missed soft bottoms, per Perplexity's "single-gate fires fail" warning**

### Gate-replay attribution (Phase 3 #1)
- Replayed Phase 1+2 gates against 3,417 cohort bars
- IV-rank gate adds **+11pp avg / +19pp hit rate** in BEAR (passed bars 74.3% / +16.09% vs blocked 55.5% / +5.03%)
- Gate correctly REVERSES in FULL_BULL (-3pp delta) — design validated by data
- Confirmed the regime-conditional design is correct

## Part 5 — Phase-by-phase summary of what shipped today

### Phase 1 — Cross-LLM consensus changes (5 items)
1. Breadth gate at signal emission (`server/regime_breadth.py` + wire in `signals.py`)
2. Bayesian shrinkage on per-ticker Kelly (`backtest/shrinkage.py` + `server/discipline.py`)
3. Kelly input clipping [WR 45-65, b 0.8-2.5]
4. ATR-based stop (helper `backtest/discipline.atr_based_stop()` — production already had a more sophisticated DTE-scaled version with 8% cap)
5. Grade size multiplier (B+ → ½ from ⅔)

### Phase 2 — From the IV-zone validation pivot (5 items)
1. Daily IV-rank cache for cohort (`server/iv_rank_cache.py`)
2. IV-rank regime gate (in `signals.py`)
3. Zone-A live classifier + 1.2× bonus (`server/zone_classifier.py` + `paper_trading.py`)
4. Sector-bucket cohort cap (`server/sector_cap.py`)
5. Conditional 21-day time stop (in `paper_trading.py update_positions`)

### Phase 3 — Validation tooling (3 items)
1. Historical gate-replay attribution (`backtest/gate_replay_attribution.py`)
2. McClellan Oscillator early-warning state (`server/regime_breadth.py` `FULL_BULL_WARNING`)
3. Vega-adjusted options PnL framework (`backtest/vega_adjusted_pnl.py`)

### Phase 4 — Macro composite layer (4 items)
1. Regime alignment counter (`server/regime_alignment.py`)
2. Stress composite (`server/stress_composite.py` — context only per Perplexity)
3. Conditional base rate forecasts (`backtest/conditional_base_rates.py` — 33-yr SPY history, 49 cells)
4. Macro pivot detector with 3 hard gates + trade proposal helper (`server/macro_pivot_detector.py`)

### Phase 4.5 — NYMO historical backfill
- yfinance batch on 288-name NYSE universe, 1,838 trading days
- Calibrated 5× to match real $NYMO distribution (std=60, range -224 to +182)
- Replaces synthetic proxy in macro_pivot backtest
- Confirmed COVID 2020 (-133), June 2022 (-125, correctly avoided trap), etc.

### Phase 5 — VEX (Vanna Exposure) confluence layer
- `server/vex_engine.py`: VEX state analyzer + GEX-VEX alignment classifier
- Wired into macro_pivot G3 as 4th confirming signal (CONFIRMED vs DIVERGENT label)
- Surfaced in `macro_context.py` dashboard payload
- Build time: 30 min (per-strike net_vex was already computed in `server/gex.py`)
- Deliberately scoped to SPX/SPY only — NOT per-cohort-ticker

## Part 6 — Specific design choices / explicit non-goals

### What we DELIBERATELY did NOT build today (and why)
- **AION subscription** — $500/mo, no published calibration, crash detector confirmed lagging (not leading). 5-10× our cost ceiling.
- **SentimenTrader subscription** — $79-99/mo, OK but we built equivalent (composite indicators) ourselves at $0
- **ThetaData Stocks subscription** — $30-80/mo additional. Used yfinance for one-off NYMO backfill instead.
- **Per-cohort-ticker VEX** — vanna is dealer-flow signal, dealers don't have meaningful single-name forced positioning. SPX/SPY only.
- **VEX as standalone scored component** — already 8+ scoring inputs. Another generic score = noise, not signal.
- **5th sizing modifier** — Phase 1+2+4 already stack 4 modifiers. Risk of double-clipping.
- **Composite circuit breaker** — Perplexity follow-up flagged win-rate alone as noisy; defer until ≥10 trading days post-Phase 2 to test composite (WR AND profit-factor).
- **AION-style visual VEX heatmap** — pretty, low decision-leverage.
- **Daily refresh cron** — operational, deferred to next session.
- **Wiring macro_context into auto-trade gates** — careful work needed to avoid double-clipping with existing breadth/IV gates.

### Intentional calibration choices
- Kelly = quarter (not half) — house empirical default from 569 closed trades
- Macro-pivot 0 false positives traded for 4 missed soft bottoms — per Perplexity, asymmetry is correct
- Time stop conditional on FULL_BULL + breadth > 50 + winning + MFE≥+1R — mirrors Qullamaggie/Minervini practice
- Stop-loss premium leg at -50%, equity leg ATR+DTE+IV scaled 1.5-8% — production already more sophisticated than the LLM consensus 12% cap
- IV-rank threshold 0.66 — empirically peaked at this value in vega-adjusted PnL tuning
- Zone A bonus 1.2× — conservative (hit-rate edge is real but variance is also real)

### Known limitations
- Cohort is 19 names — narrow, may not generalize to non-momentum names
- yfinance NYMO backfill uses 288-name universe — Oct 2022 shows +4 NYMO when official $NYMO was ~-90 (small-cap divergence). Acceptable proxy, not perfect.
- Macro pivot detector only tested on 7 historical events (1 cycle of pivots). Calibration may not hold next regime.
- Live macro_context dashboard requires running worker (per_strike cache); Sunday testing returns "no data"
- Conditional base rate forecasts use SPY-only signals (trend/VIX/drawdown), not breadth — could be improved with breadth as 4th dimension
- Composite circuit breaker not yet shipped — currently rely on simpler consecutive-loss circuit breaker
- 6 known-delisted tickers in universe (JWN, WBA, X, WRK, K, WISH) — flagged for cleanup

## Part 7 — Specific questions for LLM critique

### Q1 — Is the macro_context observation layer underutilized by not wiring into gates?
We have 4 size_modifiers in the cascade (Phase 1 grade, Phase 2 zone-A, breadth via gate, IV-rank via gate). Adding regime_alignment.size_modifier (0.5-1.0) AND stress_composite.size_modifier (0-1.0) on top would be 6 layers. Risk of double-clipping is real. Right answer: ship anyway with explicit "min of all modifiers" semantics? Or wait for live data on whether dashboard catches setups gates miss?

### Q2 — Is the macro-pivot detector too strict?
1 true positive (COVID) and 0 false positives across 7 events. Misses Oct 2022, Aug 2024 Yen, Apr 2026. By design — but is "0 false positives" the right optimization or am I leaving expected-value on the table by being too rare-firing?

### Q3 — Is the cohort itself overfit?
The 19 names were *currently working* when added to the universe. Per-ticker base rates inherit selection bias. Bayesian shrinkage helps but doesn't eliminate. Should I test the system on a held-out non-cohort universe (e.g. 20 random S&P names)?

### Q4 — VEX as confluence layer or new sizing input?
Currently VEX surfaces as ALIGNED/DIVERGENT labels on existing signals. Could promote to a sizing modifier (1.1× when VEX-positive below spot during a new BULL entry). Or keep observation-only? Frankenstein risk vs marginal alpha?

### Q5 — Conditional base rate forecasts — sample size pessimism?
33-yr SPY history, 49 cells. Cells with N>500 are robust; cells with N<100 get Bayesian shrinkage. But the *current cell* (STACKED_BULL × VIX 15-20 × 0% drawdown) has N=1015 and shows -2pp 20d hit rate vs baseline. Subtle mean-reversion signal. Is this the kind of signal worth incorporating into sizing, or noise within the SE bars (±1.5pp)?

### Q6 — IV-rank regime gate biotech exclusion — ad hoc?
ANAB/CAPR/GHRS show reverse pattern (HIGH-IV better than LOW-IV at 21d hit rate). I excluded them by sector tag. But this could be sample-size accident (only 3 names). What's the principled way to handle reverse-pattern subsets — exclude, downweight, or build a sub-model?

### Q7 — The day-trader feedback (multi-timeframe ladder)
A user of the OG GammaPulse dashboard reported "danger sign kept switching with bullish reversal" because the per-cycle signal flickers around thresholds. Specifically asking for 5m/15m/30m/1hr/4hr aggregation of signal state. We have the per-cycle history in cell_history.py. The fix is straightforward (build a bucketed modal-state aggregator + dashboard component). Is there a smarter approach — e.g. only show transitions (vs current state), or use a confidence band (signal state held N cycles)?

### Q8 — Where am I deceiving myself?
This system has gone through extensive validation today. But every backtest is in-sample to some degree. The cohort is 19 names. The macro pivot has 1 true positive. The IV-rank pattern is regime-dependent. Where would a hostile reviewer say "this is empirical theater that won't survive the next 12 months"?

### Q9 — Highest-leverage next thing to ship
The queue for next session:
- Multi-timeframe signal ladder (P6, user feedback, ~3-4 hr)
- Daily refresh cron (operational, ~1 hr)
- Telegram alert wiring for macro_pivot fires (~1 hr)
- Live integration of macro_context modifiers into auto-trade (careful, ~2 hr)
- Universe expansion to 1500 NYSE for cleaner historical NYMO (~3 hr)
- Composite circuit breaker (deferred until ≥10 trading days live data)

What should I cut from this list, what should I add, and what's the right ordering?

### Q10 — What am I missing entirely?
What's a class of signal or system component that this stack does NOT have but should? (Not asking for "more rules" — asking for orthogonal information sources or decision frameworks that would meaningfully shift edge.)

## Part 8 — Constraints (respect these in your critique)

- **Time budget:** I am 1 person trading my own book. Solutions requiring a quant team or microsecond execution are not actionable.
- **Cost budget:** ThetaData ($80) + EODHD ($29) + Discord ($20) + Claude Max are paid. AION ($500), SentimenTrader ($80) declined. New $50+/mo subs need very high-conviction justification.
- **Data sources:** I will not subscribe to additional data feeds for marginal accuracy. Will use yfinance + Massive + ThetaData chains for everything else.
- **Cognitive budget:** every new gate or component must produce a concrete decision improvement. Pretty dashboards are not value. The frankenstein test ("would this change a specific trade decision?") is real.
- **Survivor bias:** the cohort is selected for currently working. Bayesian shrinkage applied. But the system has not been stress-tested in a true 2022-style 9-month bear regime. Critique with this in mind.
- **No options-pricing wizardry:** I trade defined-risk options. Recommendations need to survive options pricing (slippage, IV crush, weekend decay) — already validated for several but not all components.

## Part 9 — What good critique looks like

- Specific number with citation: "Your Kelly assumption of payoff 17.13 is too high — Mar 2022 paper [X] shows true tail-adjusted payoff is ~5-7 for retail momentum"
- Specific cut: "Cut [Phase 4 #2 stress composite] because it's collinear with [Phase 1 #1 breadth gate], the literature already says it doesn't predict 3-day returns"
- Specific add: "You're missing [breadth thrust signal X] — academically validated [paper Y], computable from your existing data, would catch the Oct 2022 / Apr 2026 bottoms your macro-pivot misses"
- Specific question reframe: "Q3 is asking the wrong thing — the right question is whether the per-ticker shrinkage parameter k=20 is calibrated to your actual sample size variance (it's not, here's why)"

## Part 10 — What weak critique looks like

- "It depends" / "consider both sides"
- "Backtest more"
- "Add stop-losses" (already have them)
- "Diversify" (already have sector caps)
- "Use machine learning"
- Generic recommendations without specific citations or empirical reasoning

---

## Appendix — File map (for reference)

**Live signal pipeline:**
- `server/signals.py` — main signal generation, 2,500+ lines, where Layer 1-3 lives
- `server/discipline.py` — Kelly + tier + circuit breaker (Layer 4-8)
- `server/paper_trading.py` — sizing, gates, exit cascade
- `server/breadth.py` — NYMO/NAMO from Massive A/D + VIX intraday + oil intraday regimes
- `server/regime_breadth.py` — % above 200d gate (P1#1 + P3 McClellan warning)
- `server/iv_rank_cache.py` — cohort IV-rank cache + gate function (P2#2)
- `server/zone_classifier.py` — Zone A/B/Other live classifier (P2#3)
- `server/sector_cap.py` — sector bucket cap (P2#4)
- `server/regime_alignment.py` — 8-signal regime counter (P4#1)
- `server/stress_composite.py` — 0-100 stress score (P4#2)
- `server/macro_pivot_detector.py` — 3-gate detector + trade proposal (P4#4)
- `server/macro_context.py` — unified dashboard panel (P4 wrapper + P5 VEX)
- `server/vex_engine.py` — VEX state analyzer + GEX alignment (P5)

**Backtest infrastructure:**
- `backtest/shrinkage.py` — Bayesian shrinkage helpers (P1#2)
- `backtest/discipline.py` — backtest version of Kelly + ATR stop helper
- `backtest/conditional_base_rates.py` — 33-yr SPY conditional probability cache (P4#3)
- `backtest/qm_minervini_cohort.py` — original cohort screen
- `backtest/zone_iv_inversion.py` — proxy backtest (proxy invalidated by validation)
- `backtest/zone_iv_validation.py` + `_full.py` — ground-truth IV validation (killed proxy claim)
- `backtest/iv_rank_factor_investigation.py` — regime-conditional IV-rank deep dive (P3)
- `backtest/gate_replay_attribution.py` — replay Phase 1+2 gates on history (P3#1)
- `backtest/vega_adjusted_pnl.py` — Black-Scholes 21d ATM-call PnL (P3#3)
- `backtest/macro_pivot_backtest.py` — 7 historical pivot event tests (P4#4)

**Data scripts:**
- `scripts/backfill_breadth_history.py` — Massive backfill (rate-limited, used minimally)
- `scripts/backfill_nymo_yfinance.py` — yfinance NYMO backfill (P4.5)
- `backtest/fetch_atm_iv_thetadata.py` — IV history puller for cohort

**Documentation:**
- `docs/feedback/strategy_0425/` — original WINNER_SCORING_WORKFLOW + Perplexity/ChatGPT/Grok responses + SYNTHESIS
- `docs/feedback/strategy_0425/PHASE1_SHIPPED.md`, `PHASE2_SHIPPED.md`
- `docs/feedback/strategy_0426_pivot/` — AION pivot critique + PHASE3/4/5_SHIPPED
- `docs/research/` — IV zone validation FINAL, IV-rank factor verdict, conditional base rates results
