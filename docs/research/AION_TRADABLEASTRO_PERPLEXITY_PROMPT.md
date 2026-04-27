# Perplexity Prompt — Validate AION / TradableAstro Pivot Idea

*Paste this into Perplexity. Ask: "Research this and give me a critical assessment with citations. I want to know if the proposed additions are worth building, or if I'm chasing a presentation layer over commodity signals."*

---

## Context

I'm a solo retail options trader running a system called GammaPulse. It already has:
- Per-stock GEX (gamma exposure) by strike across the next 5 expirations
- NYMO / NAMO McClellan Oscillator from NYSE/NASDAQ A/D data
- % of universe (~400 tickers) above 200-day SMA, classified into FULL_BULL / TRANSITIONAL / BEAR regimes
- VIX intraday regime detector (7 states, win-rate-validated)
- Per-ticker scoring → letter grades (A+/A/B+/B) → Quarter-Kelly sizing with Bayesian shrinkage
- Cohort-validated rules (19-name QM × Minervini cohort with 16 months of options chain data)
- Earnings-distance gates, sector-bucket caps, IV-rank regime gate

I just saw a Twitter thread from @DeepInference and @TradableAstro showing two products:

1. **AION Dashboard** (https://aion.tradableastro.com presumably, exact URL unknown):
   - "AI Forecast" with 3-day / 10-day / 20-day probability of upward move (currently shows 71% / 81% / 95%)
   - "Crash Detection" — 20-day market downturn probability (currently 4.8%, with action thresholds)
   - "9 Statistical Models" — labeled Price Trend, Trend+Momentum, Market Breadth, Volatility Envelope, Momentum Strength, etc., each with expected return + probability up
   - Multi-model consensus counter ("9 BULLISH / 0 BEARISH" panel)
   - Per-strike GEX heatmap across the week
   - Per-strike VEX (vanna exposure) heatmap across the week — separate from gamma
   - "Stress index" (0-100) and "Oversold" indicator
   - Status labels like "BLOOD IN STREETS", "DETERIORATING", "STABLE", "AGGRESSIVE RISK-ON"

2. **TradableAstro track record** (Twitter screenshots from Jan-Feb 2026):
   - Jan 5 2026: "Slow down the uptrend, big chop in feb/sell off hard into mid March. Should have a definitive top by end of Jan/first week of Feb."
   - Jan 5: "Yeah $SPY is fucked in march"
   - Jan 7: "Window of opportunity for a drawdown is the following before a massive dip buy opportunity in mid March (3/19)"
   - Feb 7: "Keeping 25% long and going 75% cash here"
   - Feb 23: "August/Sept long calls, buy on March 19th heavy, maybe 2-3% otm and hold for 3 months"
   - Feb 24: "lower into mid march, bottoming within the next 3 weeks before the leg to $750 by june, maybe even late may"
   - **What actually happened (verified from chart):** SPY made a Feb top, sold off to ~$630 in early April, then rallied to ATH $714 by April 26 (today). Their March-low forecast appears to have landed within days.

## My current proposal

I was about to build a "Phase 4 Macro Composite Layer" with:
1. **Multi-model consensus counter** — unified bullish/bearish count panel from existing signals (~30 min build)
2. **Stress composite (0-100)** — weighted blend of (1-breadth%) + (-NYMO/100) + VIX + drawdown (~30 min build)
3. **Forward probability forecasts** — historical conditional base rates: "when current regime/breadth/VIX matches today, what % of historical bars went up over 3/10/20 days?" (~3-4 hr build)
4. **SPY macro-pivot detector** — fires when oversold + stress de-escalating + forecast flipping bullish → load 60-90 DTE SPY calls 5-8% size (~4-6 hr build)

I was NOT going to build:
- VEX (vanna) heatmap — high cost, low marginal value vs my existing GEX
- ML/AI crash prediction — no training data
- Replication of their UI

## What I want you to investigate

### Q1 — Is TradableAstro's track record real?

- Pull their actual public post history. Did the Jan 5 prediction ("definitive top end of Jan/first week of Feb") and the Feb 23 call ("buy March 19th heavy, hold 3 months") really happen on those dates, or were they posted after the fact?
- What's the actual SPY chart for that period? Did the March 19 low + recovery to ATH actually unfold as predicted?
- Are there public posts where they were wrong that they don't highlight in the thread?
- Track record for past calls (2024 / 2023)?

### Q2 — Is AION / DeepInference a legitimate edge or a presentation layer?

- Who runs AION? Is there a research paper, GitHub, or methodology doc, or is it a closed dashboard?
- Are the "9 statistical models" actually 9 distinct, validated signals, or are they 1 underlying signal sliced 9 ways?
- The "AI Forecast" probabilities — is there evidence these are well-calibrated (e.g. 71% predictions resolving 71% of the time over a long sample), or are they post-hoc calibrated to the visible bull tape?
- What's the cost of access? Is it $X/month or a community subscription? (Cost is a sign — closed-source $200+/mo dashboards are usually presentation layers over commodity signals)

### Q3 — Are the proposed Phase 4 additions documented edges?

For each of the 4 things I'm proposing to build, what does the academic / practitioner literature actually say about expected lift?

a. **Multi-model consensus counters:** does combining many regime signals into a unified bull/bear count add measurable predictive value beyond the individual signals? Or is it just visualization?

b. **Stress composite indices:** the Cleveland Fed Financial Stress Index, OFR Financial Stress Index, GS FCI, Citi MDI — do any of these published indices actually predict equity returns at the 3/10/20-day horizon I care about?

c. **Forward probability forecasts via historical conditional base rates:** is there literature on regime-conditional return forecasting that backs this approach? Or do all such forecasts collapse to "trend + mean reversion" once you regress out simple controls?

d. **Macro pivot detection (oversold reversal + de-escalating stress → 6-mo SPY calls):** Is the "buy 90-DTE SPY calls at extreme oversold reversals" trade actually documented as edge, or is it the kind of thing where survivorship bias is large (people remember the 2022 March 19 trade, forget the times they bought a falling knife)?

### Q4 — Is the macro-pivot trade survivable in real-time?

- Looking at the last 5 actual "extreme oversold + reversal" candidates (e.g. Mar 2020, Oct 2022, Oct 2023, Apr 2025-equivalent dates from real data), what's the win rate of buying 60-90 DTE SPY calls at first sign of reversal?
- What's the false-positive rate (you bought, it kept dropping, calls went to zero)?
- Position sizing: 5-8% of book on a single SPY call expression — is that defensible given a 6-month hold can absorb a continued -10% before vega/theta destroy it?

### Q5 — What am I missing?

- Are there other macro-composite tools that are open-source / cheaper / better-validated than AION? (Think: SentimenTrader, Norm Conley, Hedgeye, Fairlead, etc.)
- Is there a specific signal that TradableAstro/DeepInference uses that I haven't already replicated?
- Is the right move not to build any of this and instead just subscribe to AION if it's reasonably priced and the calibration is real?

## What good critique looks like

- Verified citations to actual TradableAstro posts with timestamps (not screenshots, original tweets)
- Specific numbers: "Cleveland FSI Z-score predicts 3-day SPY returns at correlation r=0.X"
- Concrete recommendation: "Build #1 and #3, skip #2 and #4 because…"
- "Subscribe to AION if cost < $Y" with reasoning
- Flag the survivorship bias / cherry-picking risk in the TradableAstro track record

## What weak critique looks like

- "It depends" / "consider both sides"
- Generic "always validate before deploying"
- No specific numbers or sources
- Assuming the dashboard is legit because it looks impressive

## Constraints

- I am one person trading my own book; ~$50-200K notional. Not a quant team.
- I already pay $80/mo for ThetaData, $29/mo for EODHD, free for yfinance. Adding $50-100/mo for a macro tool is feasible if calibration is real.
- I trade defined-risk options (calls, puts, spreads) with 7-90 DTE and 1-5% size per position. The macro-pivot trade would be the largest single bet I make.
- My existing system's edge is per-ticker momentum on a 19-name cohort (already validated). I'm asking whether to add a separate macro layer on top.
