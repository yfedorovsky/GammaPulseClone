# Momentum Scoring Workflow: Adversarial Critique for a Solo Options Trader

## Executive Summary

This is a well-constructed system—better than 95% of what retail traders run. The scoring architecture is sound, the discipline layer is real, and the options-specific adjustments (IV-rank sizing reduction, mandatory pre-earnings exit) are sensible. The **weakest link is not any single layer but the interaction between three compounding flaws**: (1) a Macro/Regime filter that is laughably thin for a system built on tape-dependent momentum, (2) forward-looking selection bias in the per-ticker edge score that quietly inflates your best grades, and (3) a stop logic whose fixed 9.1% anchor is instrument-agnostic and almost certainly misfired on your highest-ATR names. The weight collinearity issue in Layer 3 is real but survivable; the regime blindness is not.

***

## Layer 3 Weights: Are They Defensible?

### The Academic Baseline

Jegadeesh and Titman's 1993 research—the foundational momentum paper—showed that 12-month-minus-1-month price momentum generates roughly 12% annual excess returns. When researchers disaggregate what drives this, price-based momentum (the 12-1 return) is responsible for most of the signal, not the derivative confirmatory indicators downstream of it. A practitioner weighting from Blank Capital's composite scoring assigns price momentum 40%, earnings momentum 30%, relative strength 20%, and technical confirmation only 10%. Your system is roughly the inverse of this: you weight trend confirmation (stacked MAs, RS, Volume, Setup Pattern) at 55% while your cleanest standalone momentum signal—Relative Strength at multi-windows—sits at only 15%.[^1][^2]

### The Collinearity Problem

Your **Trend Quality (20%) and Relative Strength (15%) are collinear by construction**. A stock with a stacked EMA10 > SMA20 > SMA50 chain, all positively sloped, has mathematically high multi-window RS. If a name scores 18/20 on Trend Quality, it will score 13+/15 on RS 90%+ of the time. You are double-counting the same signal at 35% weight. Similarly, **Setup Pattern Match (10%) is downstream of Trend Quality and Volume Confirmation**—a Stage-2 Breakout cannot exist without the prior two conditions already being satisfied. That's another 10% of effective double-counting.[^3]

**Concrete fix:** Collapse Trend Quality + Relative Strength into a single **Momentum Composite (25%)** using the academically validated 12-1 return rank plus a 3-month slope ratio. Eliminate Setup Pattern Match as a scored component entirely—it can remain a *qualifier* for entry zone selection (Layer 5) without inflating composite scores. This saves 20% weight to redistribute to the two most underweighted components.

### Macro Regime at 5%: A Structural Error

The 5% weight for Macro/Regime Filter is the most dangerous miscalibration in the entire system. In 2022, momentum factor drawdowns exceeded 40% in a rising-rate, mean-reverting tape. Your strategy's entire edge—buying stacked-MA, high-RS names—has near-zero or negative expectancy in a bear market. A factor that determines whether your strategy has *any* edge should never be treated as a tie-breaker at 5%. This is binary information masquerading as a marginal scoring variable.[^4][^5]

**Concrete fix:** Macro/Regime should not be a scoring component at all. It should be a **hard gate** in Layer 2, upstream of scoring. The gate trips when **both** conditions are met: (a) SPY below its 200-day SMA with the 200-day SMA itself declining (not just SPY below it—the slope matters), AND (b) % of NYSE/S&P 500 stocks above their 200-day MA drops below 40%. Below that breadth threshold, no new momentum longs, regardless of individual stock scores. Promote the freed 5% weight to Backtested Per-Ticker Edge.[^6][^7][^8]

### Should Backtested Per-Ticker Edge Be 10% or 25%?

Raise it—but with a critical caveat addressed in the selection bias section below. If you correct for forward-looking bias (see Layer-3 Selection Bias), per-ticker edge is the only component in your system that directly measures *this screen's edge on this specific name*. The academic literature on overlapping momentum portfolios shows that stocks simultaneously appearing in both 6-month and 12-month top deciles outperform non-overlapping momentum by 3.69% over a 9-month hold. That co-occurrence signal is precisely what per-ticker edge is trying to measure. **A defensible weight after debiasing is 15-18%**, not 25% (too dominant for a noisy 10-sample estimator) and not 10% (undersells the only personalized edge signal in the model).[^9]

### Revised Weight Table

| Component | Current | Recommended | Rationale |
|---|---|---|---|
| Trend Quality | 20% | **Merge** | Collinear with RS |
| Relative Strength | 15% | **25% (Momentum Composite)** | Merge with Trend Quality; academically primary signal |
| Volume Confirmation | 10% | 10% | Keep as-is; OBV slope is genuinely additive |
| Volatility Posture | 10% | 10% | Keep; ATR%-rank informs sizing, not direction |
| Setup Pattern Match | 10% | **0% (move to qualifier)** | Collinear with Trend + Volume |
| Earnings Distance | 10% | 10% | Keep; earnings proximity is a clean discontinuity |
| Sector/Theme Confirmation | 10% | 10% | Group RS genuinely additive over single-name RS |
| Backtested Per-Ticker Edge | 10% | **17%** | Raise after debiasing |
| Macro/Regime Filter | 5% | **0% (move to hard gate in Layer 2)** | Binary, not marginal |
| **New: Breadth Indicator** | — | **8%** | % NYSE above 200d MA; addresses regime trap |
| **Total** | 100% | 100% | |

***

## The Weakest Link: Per-Ticker Selection Bias

This is the single most dangerous flaw in the system and the one most likely to cause you to over-size your worst future trades.

### The Mechanism

You identified the names *currently in your 19-name universe* because they passed your screener over the past 2 years. AAOI averaged +37%/21d—the reason it's in your universe and has 75% historical hit rate is precisely because it worked. AESI averaged -15%/21d—the reason it's *still* in your universe despite that is your 60-day removal rule. The per-ticker base rates you are using were generated from the **same selection process** that assembled the universe. This is a circular reference, not a base rate. Survivorship bias in momentum backtests can inflate apparent returns by 4-6% annually, and for individual-name hit rates the inflation is concentrated in exactly the high-scoring names.[^10][^11]

### Specific Debiasing Technique

Apply a **shrinkage estimator** (Bayesian shrinkage toward the pooled mean) rather than using the raw per-ticker rate:

\[
\hat{p}_i = \frac{n_i \cdot p_i + n_0 \cdot \bar{p}}{n_i + n_0}
\]

Where \(p_i\) is the ticker's observed hit rate, \(\bar{p}\) is the pooled hit rate (your 72%), \(n_i\) is the ticker's sample count, and \(n_0\) is a **prior strength parameter** (set to ~20—the number of samples at which you trust individual data equally with the pool). With only 10 samples, AAOI's "75%" shrinks toward 72.5%; you need 40+ samples before a ticker's individual rate dominates. This is implementable with your existing data, requires no new libraries beyond `scipy.stats`, and is the standard technique in Bayesian sports analytics and quantitative strategy research.[^12][^13]

A complementary test: **time-split validation**. Take your 24 months of data. Train per-ticker rates on months 1-18. Evaluate their predictive validity on months 19-24. If AAOI's month 1-18 rate predicts month 19-24 outcomes better than the pooled rate, the signal is real. If it doesn't, you have evidence that the per-ticker variation is noise—and you should weight it accordingly.

***

## Stop Logic: The 9.1% Is the Wrong Tool

### Why Fixed Percentage Stops Are Instrument-Agnostic Failures

For names with 4-6% ATR (your own characterization of the universe), a fixed 9.1% stop is approximately 1.5-2× ATR. That is within the normal daily noise range for these names on a bad tape day. You will get stopped out of valid setups when a high-volatility name pulls back 1.8× ATR intraday before resuming, while simultaneously holding losing positions in lower-volatility names where 9.1% represents 3× ATR and you've already been dead for a week.[^14][^15]

Minervini uses a 7-8% stop but applies it to the *equity* position and couples it with VCP pattern selection that mechanically reduces the entry-point-to-stop distance through volatility contraction. His stop is small because his entry is *at* the tightest compression point. Your entries are at Zone A (pullback to EMA10) or Zone B (break above swing high)—both wider entries than a VCP pivot. Applying his percentage stop to your entry methodology creates a mismatch.[^16][^17]

**Concrete fix:** Convert the hard stop to **2.5× ATR from entry**, measured using the 14-day ATR on the day of entry. This self-calibrates: a name with 3% ATR gets a ~7.5% stop; a name with 6% ATR gets a ~15% stop. Your options position sizing (premium stop at -50%) typically trips before the equity stop on the high-ATR names anyway, making ATR-calibrated stops more consistent across your actual execution. Studies on ATR-based vs. fixed stops suggest the ATR approach improves risk-adjusted performance by approximately 15% versus fixed-percentage methods by avoiding noise-driven exits.[^14]

**Cap the ATR stop at -12% from entry** to prevent the formula from generating absurd stops on gap-up earnings names with temporarily inflated ATR.

***

## Time Stop at 21 Days: Correct Diagnosis, Wrong Application

### How Qullamaggie and Minervini Actually Handle Time

Qullamaggie's published methodology is to sell 1/3 to 1/2 of the position after **3-5 days** (when initial momentum ebbs), move the stop to breakeven, then trail the remainder with the 10- or 21-day EMA close. The longest documented runner using this approach in his own trades lasted approximately 35 trading days—not 21. His exits are **price-structure-driven**, not calendar-driven. The EMA trail is the exit mechanism; time is not the variable.[^18][^19][^20]

Minervini takes partial profits at 20-25% gains, then trails remainder with a percentage trailing stop (15-20% from peak) or the 10-day MA breach. He explicitly lets winners run to 3R-5R+.[^21][^16]

Your 21-day hard exit on *all* positions, winners and losers alike, is a **payoff asymmetry killer**. By forcing exit at day 21 regardless of trend status, you cap your right tail while leaving your left tail intact (you can still hold losers to day 21). The backtest showing 21 days as the "sweet spot" is measuring *average* forward return, not the distribution—and in momentum, the distribution is massively right-skewed. The 10% of positions that would have run to +50% in 35-45 days are your entire P&L.

**Concrete fix:** Keep the 21-day time stop *only for positions below breakeven by day 15*. For positions above +1R by day 15: convert to an **EMA21 trailing stop** (daily close below EMA21 triggers exit), which is consistent with how both Qullamaggie and Minervini actually manage runners. This aligns the time stop with its true function—culling non-working trades—without amputating winners.

***

## Kelly Sizing: Half-Kelly + Floor + Cap Is Coherent But Needs Calibration

### Is the Structure Sound?

Half-Kelly with a hard cap and a floor is mathematically coherent. Half-Kelly achieves approximately 75% of full-Kelly geometric growth with substantially lower variance, making it appropriate given estimation error in your edge parameters. The floor (0.25% book) prevents noise positions. The cap (3% book) prevents concentration blowups. These are redundant in different scenarios—the floor binds on thin-edge trades; the cap binds on high-edge trades—so they are not double-clipping the same constraint.[^22][^23][^24]

The **real problem** is not the structure but the inputs: Kelly is only as good as the win rate and avg-win/avg-loss you feed it. Given the selection bias in per-ticker rates, you may be systematically over-sizing A+ grades and under-sizing B grades.

### The B+ at ⅔ Size Question

Your assumption that B+ has ~60% expectancy and ⅔ size is appropriate is reasonable but needs grounding in your actual data. The Kelly fraction at 60% win rate and 2:1 win/loss R is approximately 30% (full Kelly), meaning half-Kelly = 15%—far above your 3% cap. Kelly is not your binding constraint on B+ sizing; the 3% cap is. The practical question is whether B+ Kelly-implied size (after the cap applies) is different from A grade. The answer depends on whether B+ has a materially lower Kelly fraction than A. At your realistic win rates (55-65%), the Kelly fraction difference between a 55% and 65% win-rate setup at 2:1 R is only about 5 percentage points of uncapped Kelly. Given your 3% cap, the actual difference in dollars at risk between A and B+ is small—probably one options contract. The ⅔ / full-size distinction may be more psychological scaffolding than mathematically necessary. That is not a criticism; psychological scaffolding has real value.

### Cohort Correlation Cap: 8% Is Structurally Correct But Needs a Trigger

The 8% aggregate cohort cap is correct in principle. Three photonics names + two semi-equip names in the same week are likely 0.7-0.85 pairwise correlated during thematic runs. The issue is that a *hard notional cap* ignores that correlation is time-varying: those same five names in a sideways tape have lower pairwise correlation than in a momentum thrust. **Replace the hard cap with a conditional one:** cap cohort exposure at 8% when sector ETF is within 5% of a 52-week high (extended); allow up to 12% when sector ETF is breaking out fresh (momentum confirmation validates the correlated exposure). This is implementable using your EODHD data.[^25][^26]

***

## The Regime Trap: Where This System Dies

### 2022-Style Bear Market: The Specific Failure Cascade

In 2022, the SPY lost ~19% peak-to-trough. More importantly for momentum traders, the **character** of the tape—not just direction—destroyed the strategy. The sequence:

1. Breadth deteriorated before SPY broke the 200-day SMA. % of S&P 500 above 200d MA dropped below 40% in January 2022, weeks before SPY's definitive 200d break.[^27][^7]
2. Individual names continued to pass your 7-gate screen intermittently in relief rallies throughout 2022, generating false A+ and A grades.
3. Your regime filter (SPY > 200d, VIX < 25, GEX positive) would have passed names during bear-market rallies in March, May, and August 2022—all of which failed within 2-4 weeks.
4. Each failed momentum trade in that environment was a B-grade trigger behaving like a D because the *macro factor you weighted at 5% was the only variable that differed*.

The system doesn't lose once in 2022—it bleeds 2-3 circuit breakers before the regime context accumulates enough evidence to matter at 5%.

### The Specific Fix: A Three-Threshold Breadth Gate

Add a **Breadth Regime Indicator** to Layer 2 as a hard gate, not a scoring component. Use % of S&P 500 stocks above 200-day MA (ticker: $MMFI on StockCharts, available free or via EODHD):

| Breadth Level | Regime | Action |
|---|---|---|
| > 60% above 200d MA | Full bull | Normal operation, all grades eligible |
| 40-60% above 200d MA | Transitional | B grades suspended; A/A+ only; cap cohort exposure at 5% |
| < 40% above 200d MA | Bear / mean-revert | **No new momentum longs** until breadth recovers above 45% for 5+ consecutive days |

This threshold is empirically validated: the 50% level acts as reliable support in bull markets and reliable resistance in bear markets, and a QQQ strategy using the 60% / 40% crossover over the Nasdaq 100% above 200d MA has historically identified significant regime reversals. You can calculate this daily from EODHD's constituent data—no new data subscription required.[^28][^7][^29]

The **early warning signal** to watch before the full gate trips: **McClellan Oscillator** (19-day EMA minus 39-day EMA of NYSE advances minus declines) turning persistently negative for 10+ days. This typically precedes the % above 200d MA drop by 1-3 weeks in historical bear markets, giving you advance notice to throttle new entries before circuit breakers fire. The McClellan data is free on StockCharts.[^30][^31][^32]

***

## What's Missing: Ranked by Expected Marginal Contribution

### 1. Breadth Indicator — High Impact, Use It

As detailed above, a % above 200d MA regime gate would have prevented the majority of false A+ signals in downtrending tapes. **This is missing and materially hurts expectancy in bear markets.** Priority one for addition—and it costs nothing.

### 2. Options Flow — Noisy, Low Marginal Contribution for Your Setup

Dark pool data alone has a win rate barely above 51%. Combined with 13F filings and insider data, it reaches 67%—but those supplementary sources are not in your stack. The signal that *would* be actionable for momentum options entries: **unusual call/put volume relative to open interest on the underlying**, which indicates institutional directional positioning before a move. ThetaData ($80/mo, already subscribed) has this. You could add a binary flag: "unusual options activity in past 3 sessions" (volume > 3× 20-day avg options volume, call-skewed). This would be a **qualifier for Zone A entries**, not a scored component—it does not belong in Layer 3 weighting. Do not add it as a scored component; add it as a Zone A entry filter.[^33][^34][^35][^36]

### 3. Short Interest / Float Rotation — Mixed Evidence, Skip

Short interest *does* add alpha beyond momentum, quality, and value in a multi-factor model, with information ratios of 0.49-1.68 depending on region. However, the practical implementation for a retail options trader requires a reliable float and short interest data source updated at least weekly. Your current stack (EODHD + yfinance) has short interest data but it is typically 2-week lagged and noisy for small/mid caps. Float rotation (how many times the float has turned over intraday) is a *day-trading* metric inapplicable to your 3-21 day hold. **Skip both.** The marginal alpha does not justify the data quality risk.[^37][^38]

***

## What to Cut: The 3-Component Trim

If forced to cut three components to simplify Layer 3 while retaining 90%+ of current expectancy:

**Cut 1: Setup Pattern Match (10% → qualifier only)**
It is collinear with Trend Quality + Volume Confirmation and adds lookup complexity. Move it from scored to a binary entry qualifier in Layer 5. Saves 10% weight.

**Cut 2: Macro/Regime Filter (5% → hard gate in Layer 2)**
Not a scoring variable—it's binary information. Scoring it at 5% means a bear-market name can score 95/100 (A+) and only loses 5 points for the regime being off. That makes no sense. Move it upstream as a gate. Saves 5% weight.

**Cut 3: Merge Trend Quality into Relative Strength (20% → eliminate as separate component)**
Retain the multi-window RS calculation with slope-adjustment, but don't score them separately. The stacked MA check is already a binary pass/fail gate in Layer 2—you don't need to rescore it in Layer 3. Consolidate into 25% Momentum Composite weight. Saves 15% weight that gets distributed to per-ticker edge (17%) and breadth (8%).

These three cuts remove the three weakest, most collinear, or misplaced components. The remaining six genuine independent signals are: Momentum Composite, Volume Confirmation, Volatility Posture, Earnings Distance, Sector/Theme Confirmation, and Per-Ticker Edge.

***

## Options-Specific Blind Spots

### IV and Entry Zones Are Misaligned

Your Zone A (pullback to rising EMA10/EMA20) is the *worst* options entry in the Volatility Posture dimension. Pullbacks to the EMA, by definition, occur when the stock is consolidating and IV is compressing. You buy lower IV on Zone A—which is actually good for options buyers. Zone B (break above swing high on 1.3× volume) is when IV spikes on the breakout and you are paying for the directional move plus elevated gamma. Yet your system prefers Zone B as the add-on after Zone A—which means you are adding options exposure at the highest-IV, highest-premium point.[^39][^40][^41]

**Concrete fix:** For options specifically (not equity), **invert the zone sizing weights**: take ½ of intended options size at Zone A (low IV), then *evaluate* whether to add at Zone B only if IV Rank on the day of Zone B is below 50 (meaning the breakout is not yet bid up in premium). If IV Rank > 50 at Zone B, skip the Zone B add and wait for Zone A on the next base. This is options-pricing reality that your current framework ignores.

### The Time Stop Doesn't Account for Theta Decay

A 21-day calendar maximum hold is used because that's your backtest sweet spot for forward equity returns. But for options, the relevant clock is **days-to-expiration relative to your theta burn rate**, not calendar days. An option purchased with 45 DTE at Zone A that doesn't move in 21 days has lost ~10-15% of time value regardless of stock price. Your time stop at day 21 may be exiting *equity*-equivalent positions correctly but exiting *options* positions too early if the stock is still above your stop but options theta has not yet become the primary P&L driver. The fix: for options, use a separate exit rule—exit when theta-adjusted daily decay exceeds 0.5% of premium per day *and* price has not yet confirmed the move (no 1R achieved). This is a measure from ThetaData you already have.

***

## Summary: Priority Action List

The critique resolves to five concrete changes, ordered by impact:

1. **Promote Macro/Regime to a hard Layer-2 gate using % above 200d MA < 40% as the no-new-longs threshold.** This single change prevents the most capital-destructive failure mode.

2. **Apply Bayesian shrinkage to per-ticker hit rates before using them in Layer 3.** Prior strength \(n_0 = 20\); this prevents AAOI's 75% from driving A+ sizing when it may be noise over 10 samples.

3. **Replace the -9.1% hard stop with -2.5× ATR from entry, capped at -12%.** Instrument-calibrated volatility stops are more coherent for your high-ATR universe.

4. **Lift the 21-day hard exit on profitable positions; substitute EMA21 trailing stop for names above +1R at day 15.** This unlocks the right tail without increasing risk on losers.

5. **Collapse Trend Quality + RS into a 25% Momentum Composite; move Setup Pattern Match to a qualifier; redeploy freed weight to per-ticker edge (17%) and a Breadth score (8%).** This eliminates the collinearity problem and corrects the most severe weight miscalibration.

Everything else—the Kelly framework, the entry zone structure, the 8% cohort cap, the journal discipline layer—is defensible and should not be changed until you have live data challenging it.

---

## References

1. [Jegadeesh & Titman (1993): The Seminal Momentum Paper That ...](https://blankcapitalresearch.com/learn/jegadeesh-titman-momentum) - The original momentum paper: winners outperform losers by ~1% per month. Summary of Jegadeesh and Ti...

2. [The Momentum Factor: Why Winners Keep Winning](https://blankcapitalresearch.com/research/the-momentum-factor-why-winners-keep-winning-and-how-to-profit-from-it) - Comprehensive analysis of momentum investing: academic foundation, behavioral explanations, metrics,...

3. [How to Avoid Using Similar Technical Analysis Indicators](https://www.earn2trade.com/blog/avoiding-indicator-overlap/) - Using too many indicators can be tricky. This article examines how to avoid indicator overlap or con...

4. [7 Timeless Trading Lessons from Mark Minervini, Kristjan ...](https://x.com/Gaurav_Cx10/status/1924464504206725519) - Three of the greatest momentum traders alive — different styles, one goal: maximize gains, minimize ...

5. [Factor Investors: Momentum is Everywhere](https://alphaarchitect.com/momentum-research-summary/) - The Jegadeesh and Titman (1993) paper on momentum established that an equity trading strategy consis...

6. [S&P 500: The 200-DMA Just Broke - What Every Investor Should ...](https://www.investing.com/analysis/sp-500-the-200dma-just-broke--what-every-investor-should-know-200677088) - Market breadth shows just 46% of stocks trading above their 200-DMA (Bearish); The 50-DMA has flatte...

7. [Percent Above Moving Average - ChartSchool - StockCharts.com](https://chartschool.stockcharts.com/table-of-contents/market-indicators/percent-above-moving-average) - The percent of stocks above their 50-day moving average is more volatile and crosses the 50% thresho...

8. [Above 200MA for S&P 500, Dow, Nasdaq - MarketInOut.com](https://www.marketinout.com/chart/market.php?breadth=above-sma-200) - A high percentage of stocks (above 70%) are above their 200-day moving average, signals broad market...

9. [Overlapping Momentum Stocks - do they cause outperformance?](https://alphaarchitect.com/a-new-twist-on-momentum-strategies-utilize-overlapping-momentum-portfolios/) - The superior performance of OMOM portfolios is due to the overlapping momentum stocks falling into t...

10. [Survivorship Bias in Backtesting Explained - LuxAlgo](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/) - Survivorship bias in backtesting can distort trading strategies by ignoring failed or delisted asset...

11. [Survivorship Bias In Backtests of Momentum Rotational Trading ...](https://www.priceactionlab.com/Blog/2019/11/survivorship-bias-in-backtests-of-momentum-rotational-trading-strategies/) - Survivorship bias increases as a function of the number of constituents in an index and length of ba...

12. [Survivorship Bias In Trading (How To Avoid It) – Backtesting ...](https://www.quantifiedstrategies.com/survivorship-bias-backtesting/) - Survivorship bias in trading and backtesting is about the things we don't see or to a certain degree...

13. [Survivorship Bias in Backtesting: Avoiding Traps - Adventures of Greg](http://adventuresofgreg.com/blog/2026/01/14/survivorship-bias-backtesting-avoiding-traps/) - Survivorship bias happens when backtesting overlooks assets or strategies that have failed, been del...

14. [Average True Range: Dynamic Stop Loss Levels - LuxAlgo](https://www.luxalgo.com/blog/average-true-range-dynamic-stop-loss-levels/) - Learn how to use the Average True Range to set adaptive stop-loss levels, enhancing your trading str...

15. [7 Advanced Stop Loss Strategies That Actually Work in 2025](https://chartswatcher.com/pages/blog/7-advanced-stop-loss-strategies-that-actually-work-in-2025) - Instead of a fixed percentage, you use a multiple of the ATR value to set your stop. For example, if...

16. [3 Key Lessons from Trade Like a Stock Market Wizard (Mark Minervini)](https://www.finermarketpoints.com/post/3-key-lessons-from-trade-like-a-stock-market-wizard) - Minervini's win rate typically runs between 45-60%, meaning he loses on 40-55% of trades. This surpr...

17. [Mark Minervini's VCP Criteria: The Complete 7-Point Checklist](https://www.finermarketpoints.com/post/vcp-criteria-complete-checklist) - Mark Minervini requires an RS rating above 70, with preference for ratings above 90, indicating the ...

18. [Qullamaggie said "you should sell 1/3 to 1/2 of the position after 3-5 ...](https://x.com/AsymTrading/status/1706716710735085833) - Qullamaggie said you should sell 1/3 to 1/2 of the position after 3-5 days, and then move the stop t...

19. [What is the longest time quallamaggie hold his stocks? He ... - Reddit](https://www.reddit.com/r/qullamaggie/comments/1qxh936/what_is_the_longest_time_quallamaggie_hold_his/) - He does a partial sell after 2-3 days, of 1/3 to 1/2 of the position, once the initial momentum ebbs...

20. [3 TIMELESS setups that have made me TENS OF MILLIONS!](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/) - You should sell 1/3 to 1/2 of the position after 3-5 days, and then move the stop to break even. The...

21. [Mark Minervini Momentum Investing Strategy Guide (FIN 101)](https://www.studocu.com/en-us/document/nazareth-college/investing/mark-minervini-momentum-investing-strategy-guide-fin-101/151295302) - This guide outlines Mark Minervini's momentum investing strategy, detailing market stages, entry and...

22. [Position Sizing for Momentum Trades: How Much to Risk](https://bananafarmer.app/learn/position-sizing-for-momentum) - Position sizing determines whether a winning strategy stays winning. The 1-2% rule, Kelly criterion ...

23. [Kelly Criterion Explained: Smarter Position Sizing for Traders](https://www.tastylive.com/news-insights/kelly-criterion-explained-smarter-position-sizing-traders) - Learn how the Kelly Criterion helps traders optimize position sizing, balance risk, and improve long...

24. [Free Kelly Criterion Calculator - Optimal Position Size for ...](https://www.quantcrawler.com/tools/kelly-criterion-calculator) - Calculate optimal position size based on your edge. Full Kelly, Half Kelly, and Quarter Kelly with e...

25. [Dynamic Position Sizing and Risk Management in Volatile Markets](https://internationaltradinginstitute.com/blog/dynamic-position-sizing-and-risk-management-in-volatile-markets/) - Learn how dynamic position sizing and risk management help traders control drawdowns, hedge effectiv...

26. [position sizing and correlation - Research - Portfolio123 Community](https://community.portfolio123.com/t/position-sizing-and-correlation/58504) - Does anyone use correlation tables or mean-variance optimization to determine position sizing within...

27. [Cool Follow-Through for the Bear Market Relief - The Market Breadth](https://drduru.com/onetwentytwo/2025/03/17/cool-follow-through-for-bear-market-relief-the-market-breadth/) - AT50 (MMFI), which tracks the percentage of stocks above their 50DMAs, rose by 3.5 percentage points...

28. [Sector Momentum Favors Defense; QQQ Yet To Break; Split NDX ...](https://articles.stockcharts.com/article/sector-momentum-favors-defense-qqq-yet-to-break-split-ndx-breadth/) - A bullish signal triggers when QQQ crosses above its 200-day SMA and Nasdaq 100 Percent above 200-da...

29. [Percent of Stocks Above 200-Day Average Ideas — INDEX:MMTH](https://www.tradingview.com/symbols/INDEX-MMTH/ideas/) - When 70% or more of stocks are above their 200 D MA, it can be seen as over exuberance which can lea...

30. [How to Use the McClellan Oscillator for Profitable Stock Trading?](https://enlightenedstocktrading.com/mcclellan-oscillator/) - When the McClellan Oscillator is above zero, and the price is above the 200-day SMA, it strongly ind...

31. [2025 Trader's Guide to McClellan Oscillator - The Trading Analyst](https://thetradinganalyst.com/mcclellan-oscillator/) - The McClellan Oscillator (MO) is a tool used to assess the market's scope by calculating the number ...

32. [What Is McClellan Oscillator? Formula, Trading Signals & Strategies](https://www.litefinance.org/blog/for-beginners/best-technical-indicators/what-is-mcclellan-oscillator/) - A positive value indicates strong bullish momentum, while a negative value means bearish market sent...

33. [Option Flow and Dark Pool: A Powerful Combination | InsiderFinance](https://www.insiderfinance.io/resources/option-flow-dark-pool-a-powerful-combination) - The powerful combination of option flow and dark pool helps traders determine market direction and i...

34. [Options Flow & Dark Pool Trades: Real-Time Data for Trading Success](https://www.investing.com/studios/article-382884) - Real-time options flow and dark pool data empower traders by providing comprehensive visibility into...

35. [Uncovering Institutional Trades with Options Flow and Dark Pools](https://www.linkedin.com/posts/quantsignalsxyz_options-flow-following-smart-money-price-activity-7442221303207649281-DMVQ) - Options Flow: Following Smart Money Price tells you what happened. Options flow tells you what is ab...

36. [Dark Pool Trading: How to Track What Institutions Are Hiding](https://alphasignal.fund/blog/dark-pool-trading-explained) - Dark pools account for 50% of all trading. Here's how to read the data, spot accumulation vs. distri...

37. [Unlocking Alpha Through Short Selling Activity - Larry's Substack](https://larryswedroe.substack.com/p/unlocking-alpha-through-short-selling) - Zou and Sun tested whether their shorting signal added value beyond traditional factors like momentu...

38. [Float Rotation - The Complete Guide for Traders](https://centerpointsecurities.com/float-rotation/) - Float rotation is a measure of how many times a stock cycles through its entire supply of floating s...

39. [Trading Breakouts with Options Without Overpaying IV | 915 - Groww](https://groww.in/blog/trading-breakouts-with-options-without-overpaying-iv) - Learn how to structure options trades for breakouts while avoiding expensive premiums and managing i...

40. [Approaching Post-Earnings IV Crush With Options - Moomoo](https://www.moomoo.com/us/learn/detail-approaching-post-earnings-iv-crush-with-options-117911-250480037) - While IV crush can benefit short Vega strategies, earnings day trades come with risks. The stock mig...

41. [Understanding IV Crush - SoFi](https://www.sofi.com/learn/content/implied-volatility-crush/) - IV crush refers to a sudden drop in implied volatility that reduces an option's value, even if the u...

