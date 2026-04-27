# AION/TradableAstro Pivot — Perplexity Synthesis

*Sun Apr 26 2026. Synthesis of Perplexity research on whether to build the proposed Phase 4 macro layer or subscribe to AION.*

## TL;DR

**Build 3 of 4 with revisions. Skip AION ($500/mo). Trial SentimenTrader instead. New surprise candidate: VEX layer.**

The TradableAstro Jan→Mar→Apr call was directionally real but they're an AION affiliate marketer (promo code "ASTRO") with admitted misses (Apr 15 2026 quote: *"Made the mistake of going against the models earlier this year"*). Signal-not-noise but evidence is curated. AION itself is opaque: $500/mo, no published calibration, crash detection LAGS the market (spiked from 1% to 19.4% AFTER SPY had already dropped — circular, not predictive).

The good news: my Phase 4 proposal was directionally right but two items need scope changes, one needs to be downgraded from "signal" to "context", and there's a new high-value item I missed.

## Verified facts that matter

1. **SPY chart confirms TradableAstro narrative** but with a key timing error:
   - Feb top: real ($695 area)
   - "Buy March 19" call: SPY was $659.80 that day, but actual low was **March 30 at $629.28**
   - 11 trading days off + 5% lower than predicted entry. If you'd actually bought March 19, you'd have eaten -5% before the rally
   - Recovery to $714 ATH today: real

2. **AION economics are disqualifying:** $500/mo = 5-10× my ceiling, zero published backtest, crash detector confirmed to be lagging not leading

3. **Influencer affiliation:** TradableAstro bio links AION with promo code, has run "free trial expires in 60 minutes" promotional posts. This is sponsorship, not independent track record

## Component-by-component verdict

### #1 — Multi-model consensus counter
**Verdict: BUILD** (~30 min)
- Backed by ensemble ML literature (Gu/Kelly/Xiu 2020)
- BUT the marginal lift is modest because my signals (NYMO, breadth, VIX, GEX) are not independent — they all respond to the same macro regime
- **Reframe:** call it a "regime alignment counter" not "consensus forecaster"
- 4-out-of-6 alignment = coherent regime → size up; 3/3 split = incoherent → reduce size

### #2 — Stress composite (0-100)
**Verdict: BUILD AS CONTEXT ONLY, NOT TRADING SIGNAL** (~30 min)
- This is where Perplexity pushed back hardest with citations
- OFR FSI study (CXO Advisory): "Level of OFR FSI does NOT predict daily SPY returns"
- Cleveland CFSI was discontinued in 2016 due to construction errors
- MENA study: stress indices have predictive value only in **bearish quantile**, not at 3-10d horizons in normal regimes
- The math: VIX and drawdown are inputs to market price → stress composite is largely coincident, not leading
- **Action:** build it, display it on dashboard, but only use the extreme ranges (>80) as a trade-suspension gate. Do NOT use as forward signal.

### #3 — Conditional base rate forecasts
**Verdict: BUILD with sample-size warnings** (~3-4 hr) — **THE HIGHEST-VALUE ITEM**
- Strong academic backing: Timmermann (UCSD/NBER 2011), Ang-Bekaert (NBER 2003) regime-switching models
- Ang-Bekaert: regime-conditional asset allocation improves Sharpe 0.619 → 0.871
- Critical implementation requirements Perplexity flagged:
  1. **Display N alongside probability.** "74% up (N=47)" ≠ "74% up (N=287)". Below 100 obs the probability has ±10-15% standard error.
  2. **Apply Bayesian shrinkage** when N<100 (pull extreme regime probabilities toward unconditional mean — same technique we already use for per-ticker shrinkage)
  3. **20-day horizon more reliable than 3-day** (regime persistence)
- Reuses the shrinkage helper from Phase 1. Clean integration.

### #4 — SPY macro-pivot detector
**Verdict: BUILD LAST with HARD constraints** (~4-6 hr)
- Edge exists but narrow; **June 2022 false positive proves single-gate triggers fail**
- Historical 30-45% false-positive rate on 60-90 DTE OTM SPY calls at "extreme oversold + initial reversal"
- **Required gates (all 3):**
  1. Extreme oversold (NYMO < -60, breadth < 30%, VIX > 25)
  2. Stress de-escalation (5-day rolling improvement in breadth + VIX < 10d MA + NYMO higher low — NOT just one green day)
  3. VIX beginning to contract (term structure flipping back to contango)
- **Position size cap: 3-4% (NOT my proposed 5-8%)** — at $150K notional, 3% = $4,500 premium budget
- **Cohort correlation warning Perplexity flagged that I missed:** when this fires, my 19-name cohort is in maximum drawdown simultaneously. So the *effective* macro-pivot exposure is 6-8%, not 3-4%, when stacked with cohort drawdown. Account for this.

## Two surprises from the Perplexity research

### Surprise #1 — VEX (Vanna Exposure) is the real signal AION has that I don't
- Distinct from GEX (gamma): vanna = ∂²V/∂S∂σ
- **VEX dominates the 7-30 DTE window** — exactly where my trades live
- Computable from my existing ThetaData chains: VEX = Σ Δᵢ × Vannaᵢ × OIᵢ
- Build cost: 6-8 hours
- Phase 5 candidate — defer until after Phase 4 ships, but real

### Surprise #2 — SentimenTrader is a legit alternative to AION at 1/6 the price
- $79-99/mo
- 20+ years of public track record
- 20,000+ proprietary indicators
- Includes a backtest engine (which AION doesn't appear to have)
- Has Market Environment Composite + Sentiment Cycle Composite — operationally similar to what AION's "9 models" claim
- **Worth a 30-day trial** before committing to a full Phase 4 build, because if SentimenTrader's composites work well, items #1 and #2 from my Phase 4 list are redundant

## Three risks Perplexity surfaced that I missed

1. **Regime transition latency:** my breadth gate fires on daily closes. The Mar 30 low → Apr 24 ATH was 13% in 17 trading days. By the time my classifier confirms regime change, SPY is already $30+ off the low. The macro-pivot detector specifically needs to handle this — possibly fire on intraday breadth + VIX rather than waiting for daily close confirmation.

2. **Cohort correlation at the pivot moment:** when my macro-pivot trade fires, my 19-name momentum cohort is in maximum drawdown simultaneously. Effective exposure when stacked = 2× the SPY position alone. **Implication:** sizing the macro-pivot at 3% on top of an already-down 6-8% cohort = real portfolio swing of 12-15% on a wrong call. Calibrate sizing accordingly.

3. **Calibration sample-size problem:** 16 months of cohort data = 1-2 market cycles. Conditional probability estimates will be noisier than the system suggests. Bayesian shrinkage (already in Phase 1 stack for per-ticker) should be applied to regime-conditional probabilities as well.

## Revised plan

### Immediate (this week)
1. **30-day SentimenTrader trial** — see if it makes Phase 4 #1 and #2 redundant
2. **Skip AION** — economics + opacity disqualify it
3. **Read TradableAstro Twitter critically** — useful as a market commentary source, but discount the calibration claims; they're an affiliate

### Phase 4 build, in this order
1. **#1 Regime alignment counter** (30 min) — ship first, lowest risk
2. **#2 Stress composite as context** (30 min) — ship second, trade-suspension only
3. **#3 Conditional base rate forecasts** (3-4 hr) — biggest value, with shrinkage + N-display
4. **#4 Macro-pivot detector** (4-6 hr) — last, 3% size cap, all 3 gates required, cohort correlation aware

### Phase 5 candidate
- **VEX layer** — if my GEX work continues to deliver, this is the natural next addition. 6-8 hours, real marginal value

### What NOT to build
- AION subscription
- Stress composite as a forward-trading signal (only as suspension gate)
- 5-8% size on macro-pivot trade (Perplexity hard cap: 3-4%)
- Single-gate macro-pivot trigger (must require all 3 gates + de-escalation as multi-day, not single bounce)

## Honest assessment

The Perplexity validation worked exactly like the previous IV-zone inversion case:
- The original idea was directionally correct
- One component (stress composite as forward signal) needs to be downgraded
- One component (macro-pivot trade) needs scope tightening
- One component I didn't ask about (VEX layer) emerged as a high-value Phase 5 candidate
- The "subscribe to AION" alternative is killed; SentimenTrader emerges as a cheaper, better-documented option

**The pattern is consistent: cross-LLM consensus identifies the right *direction*, ground-truth research provides the right *magnitudes*, and the implementation needs the integration of both.**

The TradableAstro track record being real but cherry-picked is also a useful pattern recognition: their March-30 call was off by 11 days and 5%, AND they're an affiliate marketer. Useful commentary source, but their public posts are a marketing funnel, not an audited record.
