# Perplexity Deep Research — GEX Math & Data Validation

Paste this into Perplexity Pro (Deep Research mode) for source-backed answers.

---

## Prompt

I'm building a self-hosted Gamma Exposure (GEX) dashboard that computes dealer hedging pressure from option chain data. I need authoritative, source-cited answers to validate my math and architecture against what's publicly known about how the industry leaders do it.

### Question Set 1: ZGL / Gamma Flip Calculation

I compute the Zero Gamma Line (ZGL) by:
1. Taking all option contracts with their strike, OI, IV, and time-to-expiry
2. Building a grid of 80 hypothetical spot prices (current spot +/- 8%)
3. At each grid point, recomputing BSM gamma for every contract: `gamma = N'(d1) / (S * sigma * sqrt(T))`
4. Computing total GEX at each grid point: `sum(gamma * OI * 100 * S^2 * 0.01 * sign)` where sign = +1 calls, -1 puts
5. Finding where total GEX crosses zero via linear interpolation

**Research these specific questions:**
- How does SpotGamma compute their "Gamma Flip" / "Vol Trigger" level? Is it a spot-grid recomputation or something else? Cite any public whitepapers, blog posts, or videos where they explain their methodology.
- How does Menthor Q compute their zero gamma level? Any public documentation?
- In the academic literature, what is the standard method for computing a "gamma exposure profile" as a function of spot? Is BSM gamma recomputation the standard approach, or do practitioners use a different model?
- Does ignoring the risk-free rate in d1 (using `d1 = (ln(S/K) + 0.5*sigma^2*T) / (sigma*sqrt(T))` instead of `d1 = (ln(S/K) + (r + 0.5*sigma^2)*T) / (sigma*sqrt(T))`) matter for SPY/QQQ options with DTE < 30 days?

### Question Set 2: Dealer Positioning Sign Convention

I use the standard retail convention: calls get sign=+1, puts get sign=-1, assuming dealers are net short calls and net long puts.

**Research:**
- What does SpotGamma say publicly about their sign/directionality model? Do they distinguish dealer vs customer positioning? If so, how?
- Has any research paper or public source quantified how often the standard sign convention is wrong for SPY/SPX options?
- Does the CBOE or OCC publish any data on dealer vs customer open interest that could validate or invalidate this assumption?
- What does Squeezemetrics (the DIX/GEX originator) say about the sign convention in their public methodology?

### Question Set 3: Tradier vs Massive (Polygon) Greeks Quality

I'm migrating from Tradier to Massive (formerly Polygon.io) for real-time Greeks.

**Research:**
- Tradier's Greeks come from ORATS. How frequently are ORATS Greeks updated? Is "hourly" accurate, or is it more/less frequent?
- Massive/Polygon's $29 Starter plan says "Real-time Greeks and IV." What does "real-time" mean for their options snapshots? Is it tick-level, minute-level, or something else? Any forums, GitHub issues, or community posts that clarify the actual update frequency?
- Are there any known quality differences between ORATS Greeks (used by Tradier) and Massive/Polygon's Greeks? Different models, different IV methodologies?
- For a tool that needs intraday gamma exposure profiles: is Massive Starter sufficient, or do I need the Developer ($79) or Advanced ($199) tier?

### Question Set 4: 0DTE Signal Reliability

I'm considering enabling 0DTE trade signals gated by Greeks freshness:
```
greeks_age <= 10 seconds: fully tradeable
10-60 seconds: experimental mode (reduced size)
> 60 seconds: blocked
```

**Research:**
- What is the typical gamma sensitivity of 0DTE SPY options within 1 hour of expiry? How fast does gamma change for near-ATM strikes?
- Is there any public research on the reliability of GEX-based signals for 0DTE vs 7+ DTE options?
- What do SpotGamma and other GEX providers say about 0DTE reliability in their products?
- For intraday GEX dashboards, what update frequency do professional implementations typically target?

### Question Set 5: IV Normalization for Multi-Ticker Scoring

My signal engine scores 300+ tickers. For the IV factor, I now use percentile rank vs the scanned universe instead of absolute thresholds.

**Research:**
- Is percentile rank across a mixed universe (ETFs + mega caps + meme stocks + biotech) a valid normalization for IV?
- What do quant practitioners use to normalize IV across sectors? IV percentile vs own history? IV rank? IV-RV spread?
- Does OptionMetrics, IVolatility, or any major provider publish a standard methodology for cross-sectional IV comparison?

For each question, cite your sources with URLs. I need verifiable references, not generalized knowledge.
