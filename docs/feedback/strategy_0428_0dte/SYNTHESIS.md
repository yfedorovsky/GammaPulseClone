# Cross-LLM Synthesis — Zero-Lag Filter Strategies (Apr 28 2026)

Four LLMs (Grok, Perplexity, OpenAI, Gemini) reviewed the 0DTE structural-turn
strategy + PML/PMH backtest results. This is the synthesis with my engineering take.

---

## Per-LLM verdict

### Grok — shallow but right
~80 lines, table format, one-liner answers. Missed depth on theory but **picked the
right answer** (CVD bullish divergence as the single filter) and was the only one
to surface **cross-asset CVD divergence between QQQ and SPY** as a non-obvious
operational insight.

### Perplexity — most actionable
Best balance of academic citations + operational specificity. Three things:
1. Tier-1 ranking explicitly demotes price-based MAs (JMA, KAMA behind CVD/microstructure)
2. Cites **Beckmeyer 2024** (intraday option reversals — directly testable from your IV stream)
3. Concrete code-level plan: 3 immediate / 2 medium / 1 stop opt

### OpenAI — most epistemically careful
The honest one:
1. Explicit about what's NOT proven: "no peer-reviewed paper tests SPY/QQQ PML +
   CVD + 0DTE under ask-in/bid-out fills"
2. Cites parent literature: Cont (OFI > volume), Gould (queue imbalance), Bonart
   (microprice), Kolm (deep OFI)
3. Reframes the answer: "structure first, absorption second, gamma regime third,
   options flow fourth"
4. Cites Cboe 2025 — gamma's typical impact is **-0.2pp on volatility** (max +6.4pp).
   Tempers Gemini's enthusiasm: gamma is a *conditional filter*, not always-on.

### Gemini — most mechanistically rigorous
Deepest physics:
1. **MFE-vs-realized gap mathematically inevitable in negative gamma** via charm
   decay. Initial reflex bounce gives +50-84% MFE; mandatory dealer hedging causes
   -50% stop-out.
2. **Asymmetric volatility profile explains the BULL/BEAR EMA filter asymmetry.**
   Bullish bottoms form via liquidity sweep → EMAs distorted → filter rejects
   genuine setups. The 21%→22% result was structurally inevitable.
3. THE ONE filter recommendation: **Gamma Regime Filter (Spot > Gamma Flip)** —
   different from the other three.

---

## Universal consensus (4/4)

1. **Drop EMA8/21 trend filter on bullish side.** Wrong tool category.
2. **Add CVD bullish divergence** at PML retest. Single highest-value addition.
3. **Add Gamma Regime gate** as a regime veto.
4. **ISO sweeps** (cond=95) — high-quality flow signal. Rate-of-change >> absolute.
5. **Stop -50% is data-tunable.** MAE analysis would set the right number.

---

## Key disagreement: which is THE one filter?

| LLM | Pick | Reasoning |
|---|---|---|
| Grok | CVD bullish divergence | Practical, easy to add |
| Perplexity | CVD bullish divergence | Same + literature backing |
| OpenAI | Absorption-Divergence Gate (CVD + OFI + gamma veto) | Combines |
| **Gemini** | **Gamma Regime Filter (Spot > Flip)** | NEG-gamma trades fail mathematically |

**My take:** Your data contradicts Gemini's strongest claim. All 4 winning
structural_turn fires were in **NEG regime + ratio<0.7** ("mechanical bid at floor").
Gemini's "Spot > Gamma Flip required" rule would have **filtered out all 4
winners**. Your existing Gate 7 already captures regime correctly with the dual
POS-magnet-up / NEG-mechanical-bid logic.

So: absorption (CVD) > Gemini's gamma flip filter for this system specifically.

---

## OFI flavors — what's retail-accessible

| Flavor | Source | Tier |
|---|---|---|
| Trade-based OFI = CVD | Trade prints + bid/ask context | **Tier 1 (have it)** |
| LOB-state OFI (multi-level) | Level 2 / full depth-of-book | Skip (no data) |
| Microprice | Level 2 | Skip |
| Queue imbalance | Level 2 | Skip |

**ISO sweep density** is the retail proxy for institutional book pressure (Clean
Sweep paper: ISOs have larger information share than non-ISO trades). Combined
with CVD = ~80% of full L2 OFI signal at $0 incremental data cost.

---

## Action plan

### Tier 1 (this week — high ROI, low complexity)
1. **Gate 8: CVD bullish divergence** — at PML touch, require price LL + CVD HL
   in 3-bar lookback. Approximate with yfinance 1-min tick-rule until L2 available.
2. **Gate 4 upgrade: ISO sweep RATE** — replace absolute $10M with 3× 20-min avg
   in 5 bars before PML.
3. **MAE-based stop recalibration** — analyze existing winners' MAE; set stop just
   beyond their max adverse excursion.

### Tier 2 (this month — data pipeline)
4. **Anchored VWAP from prior session low** — institutional cost-basis level.
5. **Put IV skew normalization** (Beckmeyer 2024 implication) — already in OPRA.

### Skip
- All zero-lag MAs (HMA, ZLEMA, JMA, T3, KAMA, FRAMA, Kalman) — wrong category
- Full L2 OBI — retail-inaccessible; ISO sweep rate is the proxy
- Gamma Flip absolute filter (Gemini's pick) — your data contradicts it

---

## Open questions for forward testing

- CVD divergence on 0DTE specifically has no peer-reviewed validation. Mechanism
  generalizes from microstructure literature; chart pattern doesn't.
- The 4-fire backtest is statistically insignificant. Need 100+ signals over
  months of forward data to validate any filter at 95% confidence.
- Bearish side of structural_turn is untested (0 fires). May behave differently
  in negative gamma regime where Gemini's analysis IS correct.

---

## References (cited across all four)

- Cont 2014 — Order-flow imbalance > volume for short-horizon prediction
- Beckmeyer et al 2024 — Intraday option reversals (zero-delta straddles)
- Da, Goyenko, Zhang 2024 — Cross-day intraday momentum seasonality
- Pearson, Poteshman, White — Dealer gamma negatively correlated with volatility
- Barbon, Buraschi — Negative gamma + illiquidity → intraday momentum
- Cboe 2025 — Typical gamma impact on vol is -0.2pp (max +6.4pp)
- "Clean Sweep" — ISO trades have larger information share than non-ISO
- Cont, Gould, Bonart — LOB microstructure parent literature for OFI/microprice
- Kolm, Westray — Multi-level OFI improves R² 55% → 80%
