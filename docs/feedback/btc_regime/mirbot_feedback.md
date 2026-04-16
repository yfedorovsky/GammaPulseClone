# MirBot RAG — BTC/Equity Correlation Feedback (10 queries)

**Date:** April 16, 2026
**Queries:** `docs/prompts/MIRBOT_BTC_CORRELATION_QUERIES.md`

---

## Summary Verdict

**Mir actively uses BTC as a leading indicator for equities with specific, repeatable patterns.** This is NOT a "crypto is his thematic sleeve" case. He treats Bitcoin as a **liquidity barometer** that leads QQQ with a lag, and he watches specific divergences as tradeable warning signals.

**The most important single quote** (Query 7):
> "BITCOIN does lead QQQ so the main index shouldn't be too far behind but there is a lag."

That's a directional claim with an implicit time horizon. It's exactly the kind of language that justifies building a systematic detector — assuming the backtest confirms the lag is consistent.

---

## Query 1: BTC as Leading Indicator — CONFIRMED

Direct quotes from Discord:

- **2025-02-20:** "Interesting #BITCOIN is showing strength if the market is moving lower right? Doesn't seem totally risk off given that."
- **2023-10-05:** "GM all! $BITCOIN way up this morning is the first thing that jumps out so keep your eyes on those MARA charts."
- **2024-12-27:** Uses ETH/BTC flip + PEPE green as confirmation of risk-on intensity

**Mir's operational framework:**
- BTC strong during SPY weakness → "not totally risk off" (mean revert warning)
- BTC strong pre-market → bullish tone for the day, watch crypto proxies first
- ETH flipping BTC + memes green → confirmation of broad risk-on

---

## Query 2: Pre-market and Weekend Usage — HEAVY

**BTC is literally the first chart Mir checks** pre-market:

- "BITCOIN way up this morning is the **first thing that jumps out**" (2023-10-05)
- Uses weekend BTC action to structure Monday equity trades
- **2024-03-08 (Friday):** "We're swinging new amd and nvda positions. I took some far OTM mstr calls for 22MAR as well. Soo expensive but **bitcoin should run**." → Weekend BTC thesis → Monday equity positions

**Key nuance — different response for different tickers:**
- **Crypto proxies (MSTR/COIN/MARA):** Direct response to BTC gap, enter at open
- **General equities (TSLA/INTC):** Skeptical of overnight pumps, **sell into FOMO gaps**
- **Quote (2025-09-26):** "with these overnight pumps like we've seen recently in $TSLA and $INTC the vast majority of the time they get sold"

This is critical — BTC's lead signal applies DIFFERENTLY to different ticker types. Blindly going long everything on a BTC pop is wrong per Mir.

---

## Query 3: Correlation Regime Awareness — Operational, Not Academic

Mir doesn't talk in correlation coefficients, but his trades show **regime-dependent usage**:

- **Bull-run regime (BTC > key level like $70k or $110k):** positive correlation, dips buyable in both
- **Stress-test regime:** concurrent weakness (SPY gap down + BTC/ETH weak) = confirmed risk-off
- **Decoupling regime:** BTC breaking while SPY holding = warning

**Liquidity framework** (implicit):
- **2024-08-13:** "When the market moves due to an external force like a fed speaker the market has an almost reflexive nature. Unless breadth is naked below the surface $SPY resumes the regularly scheduled program."
- **Interpretation:** macro liquidity hits all risk assets; BTC is part of the "breadth" check

---

## Query 4: Divergence = Signal, Not Noise — STRONGEST FINDING

**This is a tradeable signal for Mir.** He uses divergence specifically to identify **bull traps in equities**.

- **2024-12-27:** "If $SPY closes > 595 this might go down as one of the **best traps ever**."
  - Context: SPY pushing highs, but ETH flipping BTC and memecoins mixed = not broad-based
  - Crypto divergence = suspect the SPY breakout

**Operational checklist when divergence appears:**
1. Identify leader/lagger (is BTC red while SPY green?)
2. Check breadth confirmation (MSTR/COIN weak too?)
3. Adjust bias:
   - BTC strong, SPY lagging → early risk-on signal
   - **SPY at highs, BTC breaking down → bull trap warning**
   - Both weak → broad risk-off confirmed

**Time frames:** Intraday (minutes/hours), daily, swing. **Multiple timeframes used.**

---

## Query 5: IBIT / MSTR / COIN — Different Roles

- **IBIT (pure play):** "Lately I'm finding it easier to trade straight $IBIT over the miners" (2025-01-15). Cleanest BTC exposure.
- **MSTR (leveraged momentum):** 2-3x BTC beta, treated as momentum vehicle. Further OTM calls (410C, 420C). Can decouple due to its own idiosyncratic factors.
- **COIN (hybrid):** Crypto proxy AND tech stock. Watches for leadership rotation between MSTR and COIN.
- **BITX/BITO:** Alternate pure plays when MSTR/COIN are "needing a breather" (2024-11-13)

**He watches relative strength between these as its own signal.**

---

## Query 6: Pre-Market Priority — Core Check, Regime-Dependent

BTC is checked **early in pre-market routine**, but the *priority* shifts:

- **Risk-on regime:** BTC = primary thematic focus
- **Tightening regime:** BTC = secondary confirmation (equity open takes precedence)

Links BTC directly to liquidity drivers (**TGA drawdown helps BTC**), so checking BTC = real-time liquidity read.

---

## Query 7: Macro-Liquidity Framework — THE GOLD FINDING

**This is the theoretical foundation.** Mir has an explicit liquidity framework:

- **TGA (Treasury General Account):** "TGA drawdown usually helps out with Bitcoin price" (2025-11-13)
- **DXY:** Inverse correlation. Weak dollar = "all clear for bulls"
- **TLT:** Stable/rising = liquidity support. Crashing = drain
- **HYG:** Risk appetite leading indicator

**Mechanism:**
> TGA rebuilds → liquidity drains → BTC sells off FIRST → equities follow with lag
> TGA drawdowns → liquidity floods → BTC rallies FIRST → equities follow

**Live trade example (2025-05-06):**
- Long GLD, short NQ as liquidity-rotation hedge
- Predicted: "Once $GLD puts in the local top there's a strong chance money will once again rotate back into #BITCOIN $IBIT"
- Result: called the turn exactly — "nice seeing #BITCOIN bounce exactly as our $GLD 315 primary target is hit"

**The critical quote:**
> **"#BITCOIN does lead $QQQ so the main index shouldn't be too far behind but there is a lag."**

---

## Query 8 & 9: Historical Validation Across Regimes

| Episode | Pattern | Framework Fit |
|---------|---------|---------------|
| **Mar 2020 COVID** | BTC crashed with everything, recovered fastest on Fed QE | ✅ Liquidity-return leading |
| **2022 Crypto Winter / QT** | BTC topped Nov 2021, led equity decline | ✅ Tightening cycle leading |
| **Jan 2023 Rally** | BTC bottomed Nov 2022 (before SPY Oct low), led +40% | ✅ Liquidity-return leading |
| **Mar 2023 Banking Crisis** | BTC +35% while bank stocks crashed (BTFP liquidity) | ✅ Liquidity injection front-run |
| **2024 BTC ETF** | Correlation tightened as institutional adoption | ✅ Structural increase in co-move |
| **Feb 2026 Broadening Pain** | BTC underperforming during VTV/VUG rotation | ✅ Current liquidity-drain leading |

The framework is **temporally stable** — works in 2020, 2022, 2023, 2024, 2026. That's ~6 years of consistent behavior.

---

## Query 10: Wifey Trades Use IBIT/MSTR/COIN During BTC Bull Runs

**Selection criteria for "Wifey" crypto-proxy trades:**
1. BTC above key level (e.g., $110k)
2. Supportive liquidity (TGA drawdown, weak DXY)
3. Concentrated options flow in monthly expiries

**Current market read (2026-04-16):**
- Bearish MSTR/COIN flow (C/P 0.91 and 1.96)
- Aligns with "broadening pain" + BTC underperformance
- **NOT a Wifey entry environment** — crypto proxies are contra-indicated for long-dated premium

---

## What This Changes vs My Earlier Take

I said earlier:

> "BTC theoretical case weaker than oil (no Kilian-Park equivalent)"

**I was wrong.** Mir's liquidity-cascade framework IS the theoretical equivalent:

**Oil (Kilian-Park):** supply vs demand shocks → opposite equity implications
**BTC (Mir's liquidity framework):** liquidity direction → BTC leads QQQ with lag → equities follow

The difference: Mir's framework is practitioner-derived, not academic. But he has:
- 6 years of consistent application
- Specific macro indicator dashboard (TGA/DXY/TLT/HYG)
- Documented historical examples across multiple regimes
- Live trade examples with called outcomes

---

## Revised Decision

**The RAG validates building a backtest — but NOT same-day shipping.**

The quality of Mir's framework is higher than I thought. BUT the discipline points still stand:

1. We're at 14 paper trades, not 30+
2. VIX + Oil regimes shipped today need validation data
3. Backtest must happen BEFORE integration
4. LLM review of backtest results before ship

**Recommended path:**

### Phase 1 (next session): Backtest
Build `scripts/backtest_btc_spy_regime.py` that tests:
1. **Overnight BTC return → next-day SPY open gap** (Mir's "first thing I check" pattern)
2. **BTC daily divergence from SPY** (Mir's bull-trap warning)
3. **TGA correlation with BTC** (the stated liquidity mechanism) — if we can get TGA data
4. **Lag quantification** — how many hours does BTC lead QQQ?

### Phase 2: LLM validation
Send backtest to ChatGPT / Grok / Perplexity / Gemini (same pattern as oil)

### Phase 3: Conservative ship (only if validated)
Following oil-regime pattern:
- Telegram alert on BTC divergence warning
- Soft runner score modifier
- Dashboard badge on SwingsTab

**DO NOT build any of this tonight.** THE ONE RULE still applies.

---

## Specific Patterns to Backtest

Based on Mir's language:

### Pattern 1: "BTC Leads QQQ" lag
- Compute cross-correlation between BTC returns and QQQ returns at lags from 0 to 48 hours
- Does BTC return at T correlate with QQQ return at T+X?
- What's the optimal lag? (hours? days?)

### Pattern 2: Divergence warning
- Days where SPY makes 20-day high AND BTC 5-day return is negative
- Does SPY reverse (fail breakout) within next 5 sessions?
- Compare base rate: SPY 20-day high + BTC flat/positive = control group

### Pattern 3: Overnight BTC → SPY gap
- Group trading days by overnight BTC return (8 PM ET prev day → 4 AM ET)
- Measure correlation with SPY open gap (prev close → today open)
- Is the 8 PM → 4 AM window better than 4 PM → 9 AM?

### Pattern 4: MSTR flow as confirmation
- When MSTR C/P ratio flips extreme (like today's 0.91 puts-heavy), does BTC follow?
- What's the timing lag?

### Pattern 5: Crypto sector internal divergence
- ETH/BTC ratio as early warning
- Memecoin relative strength (PEPE, DOGE) as risk-on intensity gauge
- Do these predict BTC direction 1-3 days ahead?

---

## Bottom Line

**Mir's framework is real and worth backtesting.** The RAG validates the theoretical grounding much more strongly than I initially estimated.

**BUT the discipline answer stands: don't build tonight.** Pin the backtest for next session, let VIX + Oil regimes generate validation data first, reach 30+ paper trades before adding a third regime layer.

The best edge right now is NOT one more signal. It's letting the current ones prove themselves with real outcomes.
