# Momentum Options Strategy: Academic Literature Review & Backtest Validation

## Executive Summary

This report evaluates six specific concerns about a momentum options strategy (buying 7–14 DTE calls on sector-leading stocks filtered by EMA/SMA alignment and relative strength) against the published academic literature. The strategy's reported 59% win rate and +142% average P&L on 256 trades over 15 months (Jan 2025–Apr 2026) warrants scrutiny on at least five structural grounds: (1) buy-and-hold outperformance in the underlying, (2) DTE choice, (3) concentration in a momentum sector supercycle, (4) end-of-day entry effects, and (5) backtest integrity. Each concern maps to specific academic work.

The bottom line is that options momentum is a real, documented phenomenon — but it operates on monthly rebalancing horizons using relative option returns, not on the leveraged-directional "buy calls on RS leaders" framework you describe. The specific combination of ultra-short DTE, static-IV repricing, and hindsight-curated universe selection creates a multi-layered inflation of reported performance that likely accounts for the majority of the +142% average P&L figure.

***

## 1. Options Momentum vs. Buy-and-Hold on the Underlying

### Does Buying Calls on Trending Stocks Generate Alpha Over Buying the Stock?

The most relevant academic paper is **Heston, Jones, Khorram, Li, and Mo, "Option Momentum," *Journal of Finance*, December 2023**. This is the canonical paper on options momentum and the closest analog to your strategy. The authors analyze monthly returns on at-the-money straddles on individual U.S. equities from 1996 to 2019 (approximately 385,000 observations), finding that options with high historical returns continue to significantly outperform options with low historical returns over horizons of 6 to 36 months. The pre-cost Sharpe ratio of option momentum is at least three times higher than the standard cross-sectional stock momentum strategy.[^1][^2][^3][^4]

**The critical caveat for your purposes:** the Heston et al. strategy uses **delta-neutral straddles**, not directional calls, and specifically notes that the option return continuation is "essentially unrelated to any momentum in the underlying stocks." Their finding is about cross-sectional variation in option *volatility* premia across stocks — not about capturing directional equity momentum via long calls. Kaefer, Moerke, and Wiest (2023) from the University of St. Gallen confirm and extend this finding, showing that option *factor* momentum fully subsumes option return momentum. Neither paper examines "buy calls on relative strength leaders" as a stand-alone directional strategy.[^5][^6][^7]

### Why Long Calls on RS Leaders Face a Structural Headwind

**Coval and Shumway (2001), "Expected Option Returns," *Journal of Finance***, provide the theoretical framework. Under mild asset pricing assumptions, call options should have expected returns *exceeding* those of the underlying — because they are positively convex leveraged positions on a positive risk-premium asset. However, empirically, zero-beta at-the-money straddles on S&P indices produce average losses of approximately **three percent per week**. This finding means that options are systematically *overpriced* relative to what you would expect even from a levered buy-and-hold position, due to a variance risk premium paid by option buyers and collected by sellers.[^8][^9]

**The variance risk premium (VRP) is the core problem.** Option-implied volatility has overstated realized volatility approximately **85% of the time** across extensive datasets. This means that an option buyer is, on average, overpaying for volatility relative to what actually materializes — a structural drag that must be overcome by directional gains. The Chicago Fed (2025) provides an important update: over the past 15 years, the VRP for equity index options has declined, with option alphas now *indistinguishable from zero*. This is a market efficiency improvement that makes the option-buyer's edge harder to sustain.[^10][^11]

### The Direct Comparison You Are Looking For

There is no peer-reviewed paper that directly compares "buy calls on relative strength leaders" versus "buy shares of relative strength leaders" as a stand-alone study. However, the Econstor working paper **"Testing Momentum Effect for the US Market: From Equity to Option Strategies"** comes closest. The authors find that: (a) call positions strongly outperform put positions in momentum strategies, consistent with buying calls on winners; (b) the literature shows option buyers tend to earn *less* return than predicted by standard risk-return models; and (c) momentum works in options, but only with certain construction rules. The paper notes that "all strategies based on the top percentile got the lowest alphas" — i.e., buying the very strongest stocks by momentum (your approach) does not maximize option alpha.[^12]

The fundamental insight across the literature is that buying calls on RS leaders captures directional beta with leverage — but this leverage is *costly*. In a supercycle environment where underlying stocks rise 100–400%, the compounding cost of theta and the spread on short-dated options can easily consume an edge that would have been captured for free by simply holding shares. The fact that buy-and-hold beat your strategy on most underlying tickers is the expected academic outcome, not an anomaly.

***

## 2. Optimal DTE for Momentum Options Strategies

### What the Literature Says About 7–14 DTE

There is no academic paper that specifically studies "momentum call buying at 7–14 DTE" as a category. The relevant literature comes from empirical backtesting studies of debit strategies across DTE buckets.

**The most directly applicable study** is from iPRESAGE (2026), which analyzed approximately **187,000 simulated trade observations** across 7 DTE buckets on the 10 most liquid underlyings over 6 years, covering 5 strategies including long ATM calls. Their finding directly contradicts the claim that 7–14 DTE is optimal for long calls: **21–30 DTE dominated most strategies**, including long ATM calls. The 8–14 DTE bucket (your range) produced lower risk-adjusted returns than longer-dated calls for directional strategies.[^13]

TastyLive's duration study found that **45 DTE produced approximately 10% higher average daily returns** than longer-dated options when managed to the same exit point, and that weekly volatility actually *increases* as you approach expiration regardless of initial DTE. This is consistent with the structural mechanics: at 7–14 DTE, an option sits firmly in what one framework calls the "High Octane Zone," where daily theta cost runs 10–25% of premium and gamma risk is severe.[^14][^15]

### The Noise Amplification Problem

The theoretical reason short DTE amplifies noise rather than momentum is well-established. At 7–14 DTE, gamma is extremely elevated, meaning that small random price moves produce large P&L swings that dwarf any directional momentum signal. Option Alpha's analysis of 1.7 million trade observations found a significant performance split at the **20 DTE mark: short-dated trades under 20 DTE demonstrated reduced predictability and profitability**. The grid-search finding of 7–14 DTE as "best" is almost certainly a backtest artifact of the specific period studied — a strong trending market where directional moves were large enough to survive theta burn. In a range-bound or mean-reverting environment, short-DTE long calls would be expected to perform far worse.[^16][^14]

Your average hold period of 2.7 days with 7–14 DTE entry means you are essentially buying a 5–11 DTE option at entry and exiting it well before expiration. This is a gamma-play on short-term price moves, not a momentum strategy in the academic sense. The institutional literature on short-dated options (CME Group data: volumes in options 5 days and under now dominate) confirms that this space is increasingly populated by dealers and professional participants who have structural advantages in managing gamma exposure.[^17]

***

## 3. Sector Momentum and Concentration Risk

### Industry Momentum: The Foundational Literature

**Moskowitz and Grinblatt (1999), "Do Industries Explain Momentum?" *Journal of Finance*** is the canonical reference. This highly influential paper shows that **industry portfolios exhibit significant momentum even after controlling for size, book-to-market, individual stock momentum, and microstructure effects**. More strikingly, once returns are adjusted for industry effects, profits from individual stock momentum strategies are "significantly weaker and, for the most part, statistically insignificant." Individual stock momentum is largely an industry phenomenon.[^18][^19]

The Heston et al. "Option Momentum" paper extends this directly to options: "Options also display momentum at the industry level, similar to the findings of Moskowitz and Grinblatt (1999) for stocks." This validates the general framework of sector-based RS selection — buying the best options in the best sectors does have academic support.[^20]

Sarwar, Mateus, and Todorovic (2017) study sector rotation using Fama-French 5-factor alphas on U.S. equity sectors and document that **high-technology and healthcare sectors generate the highest average alphas (37% and 38% annualized gross, respectively)** in a long-only sector rotation strategy. Long-only sector rotation outperforms; long-short does not.[^21]

### The AI/Semi Concentration Risk

The critical problem for your strategy is precisely what Man Group (Feb 2026) identified in a detailed quant analysis: **"momentum has moved from being a diversified style bet to a concentrated industry bet."** Their analysis finds that price momentum's current 12-month industry contribution stands at 7.9 percentage points — **at the 100th percentile of their 11-year sample**, far outside any historical precedent. When they strip out within-sector tilts, nearly half of price momentum's recent return disappears. "Investors relying on price momentum may be taking a bigger industry bet than they realise."[^22]

This is a precise academic framing of your risk. Your top performers (AI/semi/photonics) are not generating alpha through a generalizable momentum mechanism — they are expressions of a single industry bet that happens to have worked during the sample period. The literature distinguishes between *exploitable alpha* (alpha that persists across regimes) and *concentration risk* (exposure to a single factor that pays off over a specific regime). The current AI/semi momentum is the latter. Prior episodes where this signal diverged from analyst sentiment "saw it revert toward zero within six months."[^22]

***

## 4. Power Hour Effects: End-of-Day Momentum

### Academic Evidence for End-of-Day Momentum

This is the area where the academic evidence most directly supports an observable effect — but the mechanism is more nuanced than simple "institutions buy at the close."

**Da, Goyenko, and Zhang (2025), "Intraday Option Return: A Tale of Two Momentum," Notre Dame/McGill/SJTU (October 2025)** is the key paper. Using CBOE/LiveVol intraday data on S&P 500 equity option straddles from 2010 to 2018, the authors document two distinct intraday momentum patterns. **Afternoon momentum (3:30–4:00 PM "power hour")** — the straddle return in the last 30 minutes of day *t* positively predicts the same-interval return on day *t+1*. This generates approximately **8 basis points per day** (approximately **20% annualized**) with a Sharpe ratio of 3.11 and a monthly Fama-French 6-factor alpha of 1.7% (t-stat = 5.16). The mechanism is **option market maker (OMM) delta hedging and inventory management**: large end-user option purchases toward the close create negative OMM inventory, which OMMs must delta-hedge by buying the underlying, creating price pressure that persists into the next day's close.[^23]

At the equity level, **Gao, Han, and Zhou (2018)** document that the first half-hour return on the market significantly predicts the last half-hour return in the U.S. (using SPY data from 1999–2012), and this is confirmed internationally in 12 out of 16 markets. The economic driving forces are identified as day-trader and informed-trader behavior, plus infrequent institutional rebalancing. Beckmeyer et al. (2021) show directly that OMM delta hedging and leveraged ETF rebalancing can create end-of-day momentum or reversal depending on the net gamma sign of market makers.[^24][^25][^26]

### Limitations for Your "Power Hour" Finding

The Da et al. afternoon momentum effect applies to **straddle returns** (delta-neutral volatility plays), not directional calls. The paper specifically uses straddles to eliminate directional exposure. The mechanism they identify (OMM inventory management) would affect implied volatility and thus both calls and puts — not pure directional P&L from long calls. Your finding of 45% WR for power-hour entries vs. 36% for morning entries on directional calls may partially reflect this real mechanism, but it is conflated with the directional trend being stronger late in the day (which itself is a well-known feature of the intraday momentum literature). With 256 trades over 15 months split across entry times, the sample for each subgroup is too small to reach statistical significance — the difference between 45% and 36% WR is within a ±15 percentage point confidence interval for n≈100.

***

## 5. Static-IV Assumption and Backtest P&L Overstatement

### How Much Does Static IV Inflate Reported Returns?

This is the most serious methodological concern, and the academic evidence is unambiguous: **static-IV backtest assumptions systematically overstate options returns**, and the magnitude is significant for short-dated strategies.

The key structural fact is the **implied volatility–realized volatility gap**. Broadie, Chernov, and Johannes, in their *Management Science* paper "Understanding Index Option Returns", show that the gap between implied volatility (historically ~17%) and realized volatility (historically ~15%) — a 2-percentage-point gap — largely explains the inflated returns in option backtests. When you reprice an option at exit using the *same* IV as at entry (static-IV assumption), you are implicitly assuming that the option's time value has held steady except for theta decay modeled by BSM. In reality, IV is dynamic and mean-reverting — it often *declines* as near-dated options approach expiration, compressing the option's value below what BSM at static IV would predict. This is particularly acute at 7–14 DTE, where the "High Octane Zone" of accelerating theta coincides with the most volatile intraday IV fluctuations.[^27][^28][^14]

Fleming (1998) and Christoffersen and Prabhala (1998) demonstrate that **implied volatility is a biased upward forecast of realized volatility**, meaning that at any given moment when you buy an option, you are paying for more volatility than will subsequently materialize approximately 85% of the time. When you reprice at exit using the same entry IV rather than the exit-date market IV, you are assuming that the bias *paid on entry* is simply refunded at exit — which is not what happens in practice.[^29][^10]

### Quantifying the Spread/Cost Overstatement

Your 5% bid-ask friction assumption deserves scrutiny against the academic literature:

| Source | Options Category | Observed Bid-Ask Spread |
|--------|-----------------|------------------------|
| Bryzgalova et al. (2022), Cambridge[^30] | Weekly options (<1 week) | **12.3%** quoted spread |
| Bryzgalova et al. (2022)[^30] | Slightly OTM options | **28%** quoted spread |
| Muravyev & Pearson (2020), per Bryzgalova[^30] | S&P 500 stocks options | **17.2%** average quoted |
| De Silva, So, Smith (MIT, 2024)[^31][^32] | Pre-announcement options | **9–10%** of investment |
| ORATS professional backtester[^33] | Single-leg options | **75% of bid-ask width** |
| LSU anatomy of retail options[^34] | Typical retail option trades | **5–10%** effective spread |

Your 5% friction assumption, applied to *one* side of the trade, likely understates the true round-trip cost of short-dated individual equity options by a factor of 2–4x. At 7–14 DTE, options are in the segment with the highest proportional spreads because liquidity thins dramatically below 14 DTE for single-name equities that are not mega-cap. For a typical small-to-mid-cap AI/semi name at 10 DTE, a 15–25% round-trip effective spread is realistic.

The combined effect of static-IV overpricing and spread understatement likely inflates your +142% average P&L figure substantially. A reasonable correction scenario: (a) replace static-IV repricing with realized P&L using actual exit bids (-15% to -30% from static BSM prices for short-dated options); (b) replace 5% with 15–20% round-trip friction; (c) adjust for the approximately -3% per week baseline drag on long option positions documented by Coval & Shumway. Applied to 256 trades averaging 2.7-day holds, these corrections could reduce headline P&L by 40–60%.

***

## 6. Survivorship Bias and Look-Ahead Universe Selection

### The Academic Severity Assessment

**Survivorship/look-ahead bias from post-hoc universe selection is the single most dangerous flaw in this backtest.** The academic literature is explicit and quantitative about the magnitude.

**Marshall, Cahan, and Cahan (Bond University, 2010), "Survivorship Bias and Alternative Explanations of Momentum Effect"** is the most directly relevant paper. The authors replicate standard momentum results in the Australian equity market when survivorship-biased sampling is used, but **find no significant momentum effect when all listed stocks are included**. Their conclusion: "Momentum effect could be a product of look-ahead bias incurring from the sampling techniques." The Australian result suggests that in smaller, less diversified markets, the entire documented momentum premium may be an artifact of look-ahead bias.[^35][^36]

Alves and Filipe (2022) confirm this finding in the Portuguese market: "the Portuguese stock market does not exhibit the 'momentum effect' when all listed stocks are considered... [but] this phenomenon was detected when only survivor stocks are used." For the U.S. market, Deutsche Bank's "Seven Sins of Quantitative Investing" demonstrates the problem concretely: using the point-in-time Russell 3000 versus the non-point-in-time version produces materially different strategy performance.[^37][^38]

The most quantitative illustration is the Nasdaq 100 example: **a momentum strategy backtested on the Nasdaq 100 from 1993 to 2020 using only current members showed a CAGR of 46% with 41% drawdown. When delisted dot-com bubble companies were included, CAGR dropped to 16.4% and drawdown soared to 83%.** This is a 29-percentage-point CAGR inflation from survivorship bias alone.[^39]

### The Specific Problem With Your Backtest

Your "approved sector list curated with hindsight" introduces a *stronger* form of look-ahead bias than typical index-membership survivorship. You have not merely excluded stocks that later got delisted — you have *affirmatively selected* the stocks that performed best during the backtest period. This is equivalent to running a backtest on a universe that was 100% forward-selected: every stock in your universe survived and outperformed. Under Lopez de Prado's framework, the *minimum* in-sample Sharpe ratio required to be statistically significant after this form of selection bias grows substantially — and after testing "multiple scanner configurations" (your grid search on DTE, EMA, SMA settings), the probability that any observed Sharpe ratio above your threshold reflects genuine out-of-sample skill approaches zero without an untouched holdout.[^40][^41][^42]

### The Correct Methodology

The standard academic methodology for avoiding this bias, as applied in the Heston et al. "Option Momentum" paper and in Deutsche Bank's framework, is:[^5][^1][^37]

1. **Point-in-time universe construction**: At each rebalancing date, the eligible universe consists only of stocks that passed your scanner *on that date*, using only data available as of that date. Stocks are not selected or excluded based on subsequent outcomes.
2. **Expanding window**: The scanner (SMA/EMA/RS filters) is applied at each period-start using a rolling historical window, never referencing future data.
3. **Holdout period**: The DTE grid search and scanner parameter optimization are conducted on a designated *training* sub-period (e.g., 2023); the final parameters are then deployed untouched on the *holdout* sub-period (e.g., 2024–2025). The holdout results are the only ones presented as evidence of strategy performance.
4. **Deflated Sharpe ratio**: Per Bailey and Lopez de Prado (2014), report the Deflated Sharpe Ratio (DSR) alongside the raw Sharpe ratio. The DSR accounts for the number of parameter configurations tested in the grid search and adjusts the significance threshold accordingly.[^41][^40]

The scanner-based dynamic universe (SMA/EMA/RS) is theoretically the right approach — it is precisely what Jegadeesh and Titman (1993) and Moskowitz and Grinblatt (1999) use. The problem is the overlay of a *curated sector list* applied post-hoc. Removing that overlay and letting the scanner alone determine the universe is the methodological fix.[^43][^44][^18]

***

## Synthesis: Realistic Performance Expectations

The table below summarizes, for each of the six concerns, the academic finding and its estimated impact on your reported +142% average P&L figure:

| Concern | Academic Finding | Estimated Impact on Reported P&L |
|---------|-----------------|-----------------------------------|
| Options vs. buy-and-hold | VRP means option buyers pay ~85% of time; options should exceed underlying in expectation only before this cost[^8][^10] | Structural drag; options are the wrong instrument when underlying rises 100–400% |
| DTE optimization | 21–30 DTE dominates for long ATM calls in controlled studies; 7–14 DTE amplifies noise via gamma[^13][^16] | Grid-search artifact; likely overfitted to trending environment |
| Sector concentration | AI/semi momentum at 100th percentile of 11-year history; not diversified alpha[^22] | Results are a regime-specific bet, not a generalizable factor |
| Power hour | Real OMM-driven afternoon effect (~20% annualized for straddles)[^23] but applies to volatility plays, not directional calls | Marginal contribution; effect size smaller for directional calls |
| Static-IV / spread | Static IV overstates exit prices; round-trip spreads on short-dated options typically 12–28%[^30][^33] | **-40% to -60% reduction** in average trade P&L after corrections |
| Survivorship bias | Post-hoc universe selection can inflate CAGR by 20–30 percentage points in comparable studies[^39][^35] | May account for the majority of alpha; entire sample is selection-contaminated |

The +142% average P&L reported under current assumptions is almost certainly not reproducible in forward deployment against a point-in-time universe under realistic execution assumptions. The academic literature supports that a well-designed momentum options strategy *can* generate alpha — the Heston et al. framework demonstrates pre-cost Sharpe ratios of 3x the equity momentum benchmark — but this requires monthly rebalancing horizons, delta-neutral construction, and proper universe selection, none of which characterizes the current strategy.[^4]

***

## Conclusion

The academic literature validates four of the six premises underlying your strategy at a conceptual level: options momentum exists, industry/sector momentum exists, end-of-day price pressure effects exist, and relative-strength-based selection is a sound universe filter. However, the literature simultaneously flags structural problems with every specific implementation choice: ultra-short DTE, static-IV repricing, post-hoc universe selection, and concentration in a single industry theme at record levels. The most urgent validation step is a walk-forward backtest using a point-in-time, scanner-driven universe (no sector list), with realized execution prices at the bid for buys and at the ask for exits, evaluated over a holdout period not used for parameter selection.[^1][^18][^23]

---

## References

1. [Option Momentum - IDEAS/RePEc](https://ideas.repec.org/a/bla/jfinan/v78y2023i6p3141-3192.html) - This paper investigates the performance of option investments across different stocks by computing m...

2. [Option Momentum](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13279) - ## ABSTRACT

This paper investigates the performance of option investments across different stocks b...

3. [Momentum Everywhere, Including Equity Options - Alpha Architect](https://alphaarchitect.com/equity-option-momen/) - Option returns display momentum; firms whose options performed well in the previous 6 to 36 months a...

4. [Does Momentum work in Option Markets?](https://alphaarchitect.com/option-momentum/) - This paper explores the question of option momentum by examining what the research says about the pe...

5. [[PDF] Option Momentum - University of Southern California](http://faculty.marshall.usc.edu/Christopher-Jones/pdf/opmom.pdf) - This paper investigates the performance of option investments across different stocks by computing m...

6. [KAEFER MOERKE WIEST 2023](https://www.alexandria.unisg.ch/server/api/core/bitstreams/77c18800-3626-42f1-b413-ee60db6902c1/content)

7. [[PDF] KAEFER MOERKE WIEST 2023](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/OFM.pdf)

8. [Expected Option Returns by Tyler Shumway, Joshua D. Coval :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=189840) - This paper examines expected option returns in the context of mainstream asset pricing theory. Under...

9. [Expected Option Returns](https://econpapers.repec.org/article/blajfinan/v_3a56_3ay_3a2001_3ai_3a3_3ap_3a983-1009.htm) - By Joshua D. Coval and Tyler Shumway; Abstract: This paper examines expected option returns in the c...

10. [Implied vs. Realized Volatility Guide - MenthorQ](https://menthorq.com/guide/implied-vs-realized-volatility/) - The article explains why implied volatility usually overstates realized volatility and how traders c...

11. [The Decline of the Variance Risk Premium: Evidence from Traded ...](https://www.chicagofed.org/publications/working-papers/2025/2025-17) - Equity index options historically displayed sharply negative returns and CAPM alphas. This could ref...

12. [Testing momentum effectfor the US market: From equity to option strategies](https://www.econstor.eu/bitstream/10419/176594/1/621.pdf)

13. [What's the Optimal DTE? A Data-Driven Analysis — Options ...](https://www.ipresage.com/research/optimal-dte-study) - Free market intelligence powered by data. Daily scanner signals, sector pulse analysis, and market r...

14. [Theta Decay in Options: DTE Curves, Strategies & Time Value ...](https://www.daystoexpiry.com/blog/theta-decay-dte-guide) - Theta picks up. P&L swings become visible. 7-14 DTE, High ($0.25-0.40/day), Volatile, High, Fast dec...

15. [Testing Duration Volatility: How to Manage your Trades | tastylive](https://www.tastylive.com/news-insights/test-different-duration-volatilities-get-some-surprising-results) - Understanding the volatility of an option strategy can guide traders when to enter or exit a positio...

16. [Trade Ideas Performance: Analyzing Option Probabilities & DTE](https://optionalpha.com/blog/trade-ideas-performance-days-to-expiration) - Option Alpha analyzed more than 1.7 million option positions with varied DTE in November's volatile ...

17. [Why Are Equity Traders Using Shorter-Dated Options?](https://www.institutionalinvestor.com/article/2cf92n6v7spjqrzy2z5ds/innovation/why-are-equity-traders-using-shorter-dated-options) - Short-dated options allow traders to narrow their focus to a specific risk in a specific time frame.

18. [[PDF] Do Industries Explain Momentum? Tobias J. Moskowitz; Mark Grinblatt](http://www-stat.wharton.upenn.edu/~steele/Courses/956/Resource/Momentum/MoskowitzGrinblatt99.pdf) - Positive momentum in returns implies that stocks which outperformed the average stock in the last pe...

19. [Do Industries Explain Momentum? - jstor](https://www.jstor.org/stable/798005) - Do Industries Explain Momentum? TOBIAS J. MOSKOWITZ and MARK GRINBLATT*. ABSTRACT. This paper docume...

20. [[PDF] Option Momentum](https://www.acem.sjtu.edu.cn/sffs/2021w/pdfs/3.pdf) - This paper investigates the performance of option investments across different stocks by computing m...

21. [Sector Alpha Momentum Strategy? - CXO Advisory](https://www.cxoadvisory.com/momentum-investing/sector-alpha-momentum-strategy/) - Across all 10 sectors, the average gross annualized alpha is 3.15%. Highest average alphas are for h...

22. [How AI Hijacked the Momentum Trade - Man Group](https://www.man.com/insights/views-from-the-floor-2026-24-Feb) - Quant signals are diverging as AI-driven price trends detach from company fundamentals, creating con...

23. [[PDF] Intraday Option Return: A Tale of Two Momentum - Academic Web](https://academicweb.nd.edu/~zda/IntraOption.pdf) - Specifically, straddle return in a given half-hour interval today positively predicts the return in ...

24. [Attention Prop Traders: The first half hour of trading predicts the last ...](https://alphaarchitect.com/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/) - We document an intraday momentum pattern that the first half-hour return on the market predicts the ...

25. [[PDF] Intraday Time Series Momentum: International Evidence - CentAUR](https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf) - Our results reveal significant predictability of the first half-hour return to the last half-hour re...

26. [[PDF] The Role of Leveraged ETFs and Option Market Imbalances on End ...](https://fmai.memberclicks.net/assets/docs/Derivatives2021/beckmeyer_etf_options.pdf) - We investigate the potential links between large portfolio rebalancing effects due to hedging strate...

27. [[PDF] Understanding Index Option Returns](http://www.fields.utoronto.ca/av/slides/08-09/finance_seminar/broadie/download.pdf) - “We find significantly positive abnormal returns when selling options across the range of exercise p...

28. [Understanding Index Option Returns](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1946412) - Previous research concludes that options are mispriced based on the high average returns, CAPM alpha...

29. [PII: S0927-5398(98)00002-4](https://www.ruf.rice.edu/~jfleming/pub/jef9810.pdf)

30. [[PDF] Retail Trading in Options and the Rise of the Big Three Wholesalers](https://www.jbs.cam.ac.uk/wp-content/uploads/2022/05/2022-ccaf-conference-paper-bryzgalova-pavlova-sikoskaya.pdf) - We find that retail traders prefer cheaper, weekly options, the average quoted bid-ask spread for wh...

31. [[PDF] retail option trading and expected announcement volatility](https://www.timdesilva.me/files/papers/losing_optional.pdf) - These translate to retail losses of 5–9 percent on average, and 10–14 percent for high expected vola...

32. [Retail Option Trading and Expected Announcement Volatility](https://ide.mit.edu/wp-content/uploads/2024/03/Retail_Options.pdf?x93667)

33. [Backtesting 180 Million Options Strategies – Insights from ORATS ...](https://www.interactivebrokers.com/campus/ibkr-quant-news/backtesting-180-million-options-strategies-insights-from-orats-latest-research/) - Slippage assumptions are key for a realistic backtest and ours are based on years of experience. We ...

34. [An Anatomy of Retail Option Trading](https://www.lsu.edu/business/files/event-files/2025-finance-mardi-gras/retail_option_trading_v2.pdf)

35. [[PDF] Survivorship bias and alternative explanations of momentum effect](https://research.bond.edu.au/files/27740886/Survivorship_Bias_and_Alternative_Explanations_of_Momentum_Effect.pdf) - This paper provides the first detailed examination of momentum effect in Australian equity market. I...

36. [Survivorship Bias and Alternative Explanations of Momentum Effect](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1663495) - This paper provides the first detailed examination of momentum effect in Australian equity market. I...

37. [Signal Processing](https://hudsonthames.org/wp-content/uploads/2022/01/DB-201409-Seven_Sins_of_Quantitative_Investing.pdf)

38. [Survivorship bias on the momentum effect: Evidence from the Portuguese market](https://journals.bohrpub.com/index.php/bijfmr/article/download/64/2367/2668)

39. [Survivorship Bias in Backtesting: Avoiding Traps - Adventures of Greg](http://adventuresofgreg.com/blog/2026/01/14/survivorship-bias-backtesting-avoiding-traps/) - Survivorship bias can ruin your backtesting results by creating a false sense of success. It happens...

40. [Marcos M. Lopez de Prado - QuantResearch.org](https://www.quantresearch.org/Publications.htm) - Quantitative Research

41. [[PDF] Quantifying Backtest Overfitting in Alternative Beta Strategies](https://community.portfolio123.com/uploads/short-url/eDD8GQ0ZmwCF8vCR4dORON040Sf.pdf) - 2. The identification, development, and implementation of alternative beta strategies are inherently...

42. [[PDF] Statistical Overfitting and Backtest Performance - David H Bailey](https://www.davidhbailey.com/dhbpapers/overfitting.pdf) - In an attempt to avoid backtest overfitting, researchers and analysts often use the “hold-out” metho...

43. [[PDF] Profitability of Momentum Strategies: An Evaluation of Alternative ...](http://www-stat.wharton.upenn.edu/~steele/Courses/434/434Context/Momentum/MomentumStrategiesJF2001.pdf) - Jegadeesh and Titman (1993) examine a variety of momentum strategies and document that strategies th...

44. [[PDF] NBER WORKING PAPER SERIES PROFITABILITY OF MOMENTUM ...](https://www.nber.org/system/files/working_papers/w7159/w7159.pdf) - As discussed in Jegadeesh and Titman (1993), the observed momentum profits can be consistent with ei...

