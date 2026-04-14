# ChatGPT Critical Evaluation Prompt

Copy everything below the line into ChatGPT (GPT-4o or o1), then attach or paste the TECHNICAL_SPEC.md file.

---

## Prompt

You are a senior quantitative developer who has built production trading systems at Citadel, Two Sigma, or a top prop shop. You've used Bloomberg Terminal daily for 10+ years, you're deeply familiar with the gamma exposure (GEX) space (SpotGamma, Menthor Q, GEX Dashboard), and you've seen Martin Shkreli's Godell Terminal demo. You have zero tolerance for toy projects that masquerade as trading tools.

I'm building **GammaPulse** — a self-hosted GEX dashboard with a signal engine, discipline layer, and flow detection. It's a solo project meant to replace my dependency on third-party GEX dashboards and generate actionable option trade ideas with built-in risk management.

**I've attached the full technical specification.** Please review it and give me a brutally honest evaluation across these dimensions:

### 1. GEX Math Integrity
- Is the per-strike gamma/vanna/delta calculation correct? Any formula errors?
- Is the vanna ≈ vega/spot approximation acceptable, or does it introduce meaningful error?
- Is the ZGL (Zero Gamma Line) calculation sound? How does it compare to SpotGamma's implementation?
- Are the strike classifications (KING, FLOOR, CEILING, GATEKEEPER) logically consistent?
- What do Bloomberg professionals or prop desks do differently in their GEX calculations?

### 2. Signal Engine Quality
- Does the 8-factor SOE scoring make quantitative sense? Are any factors redundant or poorly weighted?
- How would this compare to a Bloomberg OVDV screen + a manual gamma flip detection workflow?
- Are the signal types (MAGNET BREAKOUT, SUPPORT BOUNCE, etc.) backtestable, or are they narrative-driven labels?
- What's missing from the signal engine that a professional would expect?

### 3. Risk Management / Discipline Layer
- Is the Quarter-Kelly sizing formula implemented correctly?
- Are the payoff ratios (12.0 for PROVEN, 4.4 for DEVELOPING, 2.2 for UNPROVEN) realistic for options trading?
- Is the circuit breaker (3/5/7 loss levels) appropriately calibrated?
- How does the exit ladder compare to professional systematic exit strategies?
- Are the 0DTE time-of-day gates evidence-based, or are they vibes?
- What would a professional risk manager add or change?

### 4. Data Pipeline & Freshness
- Is the tiered scanning approach (120s cycle, 3 tiers) adequate for actionable signals?
- What are the risks of 2-minute chain cache TTL for fast-moving markets?
- Is Tradier's data quality (Greeks, IV) sufficient for this purpose vs. OPRA feed / Bloomberg OVDV?
- How would this pipeline hold up during a VIX spike or flash crash?

### 5. Architecture & Engineering
- Is the FastAPI + React + SQLite stack appropriate, or is there a better choice?
- Are there obvious scaling bottlenecks (300+ tickers, WebSocket fan-out, SQLite writes)?
- What would you change if this needed to handle 1,000 tickers?
- Any security concerns with the Tradier token handling?

### 6. Competitive Positioning
- How does this compare feature-for-feature to:
  - **SpotGamma** (the market leader in retail GEX)
  - **Menthor Q** (European competitor)
  - **Shkreli's Godell Terminal** (the most ambitious retail terminal project)
  - **Bloomberg Terminal** (the institutional gold standard)
- What features would close the gap to each of these?
- What does GammaPulse do that none of them do?

### 7. What's Actually Wrong
- Identify the 3 most dangerous assumptions in the GEX math
- Identify the 3 weakest points in the signal engine
- Identify the 3 biggest risks for a trader actually using this to size positions
- What would you refuse to trade on if you were handed this system tomorrow?

### 8. What's Surprisingly Good
- Call out anything that exceeds what you'd expect from a solo retail project
- Is there anything here that approaches institutional quality?
- What's the strongest individual component?

### 9. Actionable Recommendations
- Give me a prioritized list of the top 5 improvements ranked by impact on trade quality
- For each: what would it cost in effort vs. how much would it improve outcomes?
- What's the single change that would move this from "interesting hobby project" to "I'd actually trust a signal from this"?

Be specific. Use numbers. Reference specific formulas, thresholds, and design choices from the spec. Don't soften the blow — I need to know where this is weak before I put real money behind it.
