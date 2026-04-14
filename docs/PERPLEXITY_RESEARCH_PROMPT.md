# Perplexity Deep Research — GammaPulse System Validation (April 2026)

Paste this into Perplexity Pro (Deep Research mode) for source-backed answers.

---

## Context

I've built GammaPulse, a self-hosted options gamma exposure (GEX) platform. It's been reviewed by ChatGPT (quant teardown + follow-up) and has an academic lit review (12 papers on dealer hedging mechanics). I'm now going live with real capital and need Perplexity to validate specific claims and fill knowledge gaps with cited sources.

**What's built:** FastAPI backend scanning 300+ tickers every 2 min, React frontend with 11 tabs, 5-factor signal engine, Kelly-calibrated discipline layer (569 real trades), real-time Greeks via Massive ($29/mo), Telegram alerts, MirBot Discord bridge, breadth (NYMO/NAMO), RTS vehicle selection, industry leadership scoring.

---

## Question Set 1: Dealer Hedging — Duration & Magnitude

My academic review established that negative-gamma amplification is "primarily intraday and reverts within 1-3 days" (Baltussen et al. 2021). My system uses GEX for both intraday scalps (0DTE SPY) and multi-day swings (1-21 DTE on single stocks).

**Research with sources:**
- Has any paper quantified the **half-life of GEX-driven price impact** on SPY/SPX specifically? Not just "reverts in days" but actual decay curves.
- The 0DTE explosion since 2022 has changed market microstructure. Has any post-2023 paper studied whether 0DTE volume has **strengthened or weakened** the GEX feedback loop? (Wouts & Vilkov 2023 said "inconsistent with fragility" but that was early.)
- For **multi-day swing trades (7-21 DTE)**: does the academic literature support using GEX levels as structural support/resistance that persists across sessions? Or is this purely an intraday phenomenon that I'm wrongly extending?
- My system found GEX alone = negative EV on individual equities, positive EV only on SPY. Is there any published work studying **GEX signal quality degradation by underlying** (SPX vs SPY vs QQQ vs single stocks)?

### Question Set 2: McClellan Oscillator as Macro Filter

I compute NYMO (NYSE McClellan) and NAMO (NASDAQ McClellan) from advance/decline data classified by exchange (5,025 common stocks). This feeds into my macro confluence scoring.

**Research with sources:**
- What is the **standard McClellan Oscillator computation**? I use `EMA(19) of net advances - EMA(39) of net advances`. Is this the canonical formula, or do McClellan Financial Publications use a different one?
- Has any backtest studied the **predictive power of NYMO for options trading** specifically (not just equities)? Any papers on breadth + options alpha?
- I halved the breadth penalty for index ETFs (SPY/QQQ) in my scoring because "intraday bounces shouldn't be penalized by daily NYMO." Is there academic support for **treating index vs single-stock signals differently** w.r.t. breadth?
- What is the **standard oversold/overbought threshold** for NYMO? I've seen -60/+60 cited but Mir's rules use different levels.

### Question Set 3: Kelly Criterion for Options Trading

My discipline layer uses Kelly sizing calibrated from 569 real trades. The calibration produced counterintuitive results: UNPROVEN tickers (< 3 trades) have the highest Kelly multiplier (29.67) vs PROVEN (10+ trades, 10.75).

**Research with sources:**
- Is **Kelly criterion even appropriate for options** (binary-ish payoffs with fat tails)? What does the literature say about Kelly for trades with capped downside (-100%) but variable upside (+50% to +1000%)?
- **Quarter-Kelly vs half-Kelly vs fixed fraction**: what does the empirical literature show for actual trader performance? Is there a paper comparing Kelly variants on options specifically?
- My UNPROVEN tier shows the highest expected payoff — classic **survivorship bias from small samples**. What sample size does the literature recommend before trusting Kelly parameter estimates? Is 10 trades (my PROVEN threshold) anywhere near sufficient?
- Has any paper studied **rolling circuit breakers** (drawdown-triggered position reduction) in combination with Kelly? My L1/L2/L3 system reduces position size at 20%/10%/0% rolling WR thresholds.

### Question Set 4: Relative Trend Strength as Vehicle Selection

My RTS engine ranks 300+ tickers by momentum + quality (RS vs SPY 20d/60d, MA alignment 20/50/100, slope, ATR extension). This determines WHICH ticker to trade.

**Research with sources:**
- **Relative strength as a stock selection filter for options trades**: has any paper studied whether RS momentum (vs index) predicts options trade outcomes, not just equity returns?
- My ATR extension flag marks stocks > 2 ATR above 20MA as "EXTENDED" (avoid) and > 3 ATR as "OVEREXTENDED" (contrarian pullback zone). Is **ATR-based mean reversion** a documented strategy filter? What thresholds do practitioners use?
- I group tickers into 13 industry clusters and score them (LEADING/EMERGING/WEAKENING/BROKEN). **Industry momentum** as a factor: does the literature support trading in the direction of industry leadership? Papers on sector rotation + options?
- Is there any research on **combining momentum ranking with GEX levels**? I.e., using momentum to pick the ticker and GEX to pick the entry level.

### Question Set 5: Volume Profile as Context Layer

I just implemented a Volume Profile (VP) as a lightweight-charts ISeriesPrimitive plugin — horizontal bars showing volume-at-price distribution.

**Research with sources:**
- **Point of Control (POC) as support/resistance**: is there any statistical evidence that POC levels have predictive power, or is this a self-fulfilling technical analysis artifact?
- **VP + GEX overlap**: has anyone studied the interaction between high-volume price levels and high-GEX strikes? If a GEX king coincides with the VP POC, does that strengthen or weaken the signal?
- For **intraday VP**: is session VP (current day only) or multi-day VP more useful for 0DTE trading? Any papers on optimal VP lookback window?
- **Value Area (VA) as a mean-reversion zone**: the 70% value area concept. Is there empirical support for VA boundaries acting as support/resistance?

### Question Set 6: Competition & Data Sources

**Research with sources:**
- **SpotGamma's methodology** (April 2026): have they published any updates to their Gamma Flip / Vol Trigger calculation since 2024? Any new products or features?
- **Massive/Polygon real-time Greeks**: any developer community reports (GitHub issues, forums, Discord) confirming actual update latency on the $29 Starter plan? My live test showed delta updating every 30 seconds.
- **CBOE dealer positioning data**: the SEC's MIDAS system and CBOE's published data. Has any new public data source emerged since 2024 that could validate the standard sign convention (calls +1, puts -1)?
- **Open-source GEX tools on GitHub** (2025-2026): any new projects that implement GEX differently than the standard BSM-gamma model? Anything using order flow or trade-level data instead of snapshots?

---

For each question, cite your sources with URLs. I need verifiable references, not generalized knowledge. Prioritize peer-reviewed papers and primary sources over blog posts.
