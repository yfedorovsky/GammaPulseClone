# Gemini Deep Research — Architecture & Competitive Analysis

Paste this into Gemini 2.5 Pro (Deep Research) for a different perspective from ChatGPT.

---

## Prompt

I'm building GammaPulse, a self-hosted options gamma exposure (GEX) dashboard. I've gone through one round of expert review and implemented major fixes. Now I need a fresh set of eyes to find blind spots the first reviewer might have missed.

Here's my current architecture and the specific areas I want you to stress-test:

## System Overview

**Stack:** FastAPI + React + SQLite. Solo project, self-hosted.

**Data sources:**
- Tradier Brokerage API: quotes, streaming, OHLCV bars, option chains (OI, volume, bid/ask)
- Massive/Polygon ($29/mo Starter): real-time Greeks (delta, gamma, theta, vega, IV)
- Fallback: Tradier Greeks (hourly from ORATS) when Massive unavailable

**GEX calculation:**
- Standard dealer-hedging model: sign = +1 calls, -1 puts (assumed, not inferred)
- Per-strike: `gamma * OI * 100 * spot^2 * 0.01 * sign`
- Vanna approximated as vega/spot
- ZGL: true gamma profile solve (BSM gamma recomputed across 80-point spot grid, zero crossing found via linear interpolation)

**Signal engine (5 factors, max 6 points):**
1. GEX Structure (0-2) — composite of regime, king polarity, ZGL position, call/put wall
2. King Distance (0-1) — 0.5-3% sweet spot
3. Support/Resistance (0-1) — floor/ceiling confirmation
4. IV Rank (0-1) — percentile vs scanned universe
5. Macro Confluence (0-1) — SPY/QQQ/IWM alignment

**Risk management:**
- Quarter-Kelly sizing with hard caps (15% max single, 5% 0DTE, 5% unproven)
- Base rate tiering: PROVEN (50%+ WR, 10+ trades), DEVELOPING, UNPROVEN, BELOW_FLOOR
- Circuit breaker: 3/5/7 consecutive losses, resets on any win
- Exit ladder: systematic profit-taking at +50/100/150/200% (multi-day), +50/100% (0DTE)
- 0DTE freshness gate: greeks_age <= 10s = tradeable, 10-60s = experimental, >60s = blocked

**Coverage:** 300+ tickers across 3 tiers, 11 frontend tabs.

## What I Want You to Evaluate

### 1. Architecture Blind Spots

The first reviewer focused on math and data quality. What about:

- **Concurrency risks:** AsyncIO + SQLite writes from multiple background tasks (scanner, flow alerts, signal engine, position monitor). Is SQLite safe here? What failure modes should I worry about?
- **Memory pressure:** Caching 300+ tickers' full option chains in memory + 30-second Massive Greeks cache. What's my approximate memory footprint? When does this become a problem?
- **Error cascading:** If Massive API goes down, I silently fall back to Tradier. But if Tradier is also having issues, the entire pipeline stalls. Should I add a health check / dead man's switch?
- **Cache coherence:** Tradier chains cached 2 minutes, Massive Greeks cached 30 seconds, quotes streaming real-time. A signal could use a 2-minute-old chain with 5-second-old Greeks and 1-second-old spot. Is this temporal mismatch a real problem?

### 2. Signal Engine — Alternative Approaches

My 5-factor scoring is deterministic and rule-based. The first reviewer said it's "not yet quantitatively calibrated."

- What would a Bayesian approach to GEX signal scoring look like? Is there a practical way to assign calibrated probabilities to these factors without ML training data?
- For the IV Rank factor: I rank each ticker's IV against the full 300-ticker universe. Should I instead use IV percentile vs the ticker's own history (requires storing historical IV)? Or IV-RV spread?
- The "Macro Confluence" factor checks if SPY/QQQ/IWM kings are positive. Is this the right proxy for macro alignment, or should I use something else (VIX regime, breadth, credit spreads)?

### 3. Data Quality Reality Check

- Massive/Polygon's Starter plan says "15-minute delayed data" in some places and "Real-time Greeks and IV" in others. What is actually real-time at $29/mo? Have you seen any developer community reports on actual update latency?
- Tradier's ORATS Greeks: the first reviewer said "hourly." Is there any public documentation confirming this update frequency? ORATS themselves might update more frequently but Tradier might cache.
- For the vanna approximation (vega/spot): the reviewer said error <= 5% for ATM. In your estimation, how bad does this get for SPY puts at 5% OTM with 7 DTE? 10% OTM?

### 4. Competitive Landscape

I want to understand where GammaPulse fits vs what's available:

- **SpotGamma** ($40-150/mo): What specific features do they offer that I don't have? Focus on their data pipeline, update frequency, and any proprietary analytics.
- **Menthor Q** ($30-80/mo): How does their GEX model differ? Do they publish methodology?
- **Orats** (institutional): They supply the Greeks to Tradier. What does their own dashboard offer that retail GEX tools don't?
- **GEX Dashboard / Unusual Whales / FlowAlgo**: Any other retail GEX tools I should benchmark against?
- **Open source**: Are there any open-source GEX implementations on GitHub that I should study for alternative approaches?

### 5. What Would You Build Differently?

If you were starting a self-hosted GEX dashboard from scratch today:
- Would you use BSM or a different model for gamma recomputation?
- Would you use option chain snapshots or tick-by-tick trade data for GEX?
- Would you build the signal engine as rule-based, Bayesian, or ML?
- What data source would you choose at the $30-100/mo budget?
- What's the single most impactful feature that differentiates a professional GEX tool from a retail one?

Be specific and cite sources where possible. I'm not looking for encouragement — I'm looking for things I'm getting wrong or haven't considered.
