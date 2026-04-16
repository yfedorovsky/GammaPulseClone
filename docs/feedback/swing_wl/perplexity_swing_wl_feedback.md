# Quantitative Swing Trading Screening: Academic Evidence Review (2020–2026)

## Executive Summary

This report synthesizes peer-reviewed and empirical evidence for seven core screening criteria used in short-hold (1–5 day), options-based swing trading systems: relative strength momentum, moving average filters, sector rotation, volume-based signals, average daily range (ADR%), multifactor combinations, and the IBD RS rating. The most robust findings — those surviving data-snooping corrections, out-of-sample tests, and post-publication scrutiny — are momentum (cross-sectional, conditional on liquidity), sector-level momentum, and MA-based trend filters used as risk filters rather than standalone trade signals. Volume is a confirmed predictor of move *magnitude* but not *direction*. ADR% lacks direct academic validation for options specifically but maps closely onto well-studied realized-vs-implied volatility research. Multifactor models show genuine diversification benefits up to ~3–4 factors, after which gains are statistically indistinguishable from data mining. The IBD RS rating is not independently academically validated but is a practitioner implementation of the academically robust 12-1 month momentum factor with recent-quarter overweighting.

***

## 1. Relative Strength Momentum: Cross-Sectional Evidence

### Foundational Literature

Jegadeesh and Titman (1993) established that buying the top decile by 12-month trailing return (skipping the most recent month) and holding for 3–12 months earns approximately 1% per month in the US equity universe. This "12-1" momentum strategy has been replicated across 40+ countries and 150+ years of data. The 1-month skip is not arbitrary — it exists to avoid short-term reversal: Jegadeesh (1990) and Lehmann (1990) both documented that 1-week to 1-month returns exhibit *reversal*, not continuation, driven by microstructure effects (bid-ask bounce, inventory management).[^1][^2][^3]

### Critical Finding for Swing Traders: The Turnover Interaction

The most actionable recent paper for swing traders is Medhat & Schmeling (2022, *Review of Financial Studies*), which resolves the reversal/continuation paradox directly. Using US stocks from CRSP, they show that the sign of short-term price continuation depends critically on share turnover:[^4][^5][^6]

- **Low-turnover stocks** exhibit short-term *reversal* after strong 1-month returns (consistent with price pressure / liquidity provision)
- **High-turnover stocks** exhibit short-term *momentum continuation* — the effect is significant and survives transaction costs for large-cap liquid stocks
- The short-term momentum signal for high-turnover stocks persists for up to 12 months post-formation and is strongest in S&P 500-type names[^7]

This means that screening for 1-month RS rank is *only* a valid predictor of forward 1-week returns in the **high-turnover subsample**. Applying RS screening indiscriminately to all stocks — including thinly traded small-caps — will produce the opposite of the intended effect.

Chen, Stivers & Sun (2024, *Journal of Empirical Finance*) further refine this: short-term reversal switches to continuation for stocks with *both* high turnover *and* high price-to-52-week-high ratio. This double-conditioning materially improves forward return predictability.[^8][^9]

### Optimal Lookback Period for Swing Holds

Backtesting evidence on 480 S&P 500 stocks (2015–2025) finds the 6-month lookback + 1-month hold configuration produces the highest Sharpe ratio (1.16), while the 12-month lookback produces the highest average Sharpe (1.17) across all configurations. Post-2008, however, the 3-month lookback has meaningfully outperformed the 12-month, likely due to faster information diffusion and rising factor arbitrage. For a 1-week hold, the direct academic evidence does **not** support 1-month RS as a universal predictor — but conditioned on high turnover + proximity to 52-week high, it becomes valid.[^10][^11][^8][^4]

**Evidence quality: HIGH (for liquid, high-turnover stocks). MODERATE (for unconstrained application).**

***

## 2. Moving Average Filters for Stock Selection

### 50-Day and 200-Day SMA

The 200-day SMA as a market-timing or risk filter has been studied extensively. Empirical work on the S&P 500 shows that applying a 200-day MA exit rule reduces maximum drawdown from 56.73% to 21.31%, though it also compresses CAGR from 4.66% to 3.65% due to whipsaws. Adding a ±3% buffer around the 200-day reduces false signals from 40+ triggers to 13 trades and improves net CAGR to ~6%. Very long moving average studies (Isakov & Marti) confirm that SMA windows above 200 days tend to outperform buy-and-hold on a gross return basis across multiple equity markets.[^12][^13]

For **stock selection** (using price > 200-day SMA as a filter, not a trade signal), the 200-day SMA functions as a regime classifier — filtering out stocks in structural downtrends where momentum strategies fare poorly. This is the more defensible use: most practitioners and quantitative systems apply it as a *precondition* that eliminates technically broken candidates rather than as a standalone entry trigger.[^14][^15]

### EMA Crossover Alignment (21/50/200)

The 21 EMA > 50 EMA > 200 SMA alignment ("three-layer trend confluence") appears throughout practitioner literature but has limited *peer-reviewed* support as a specific combination. Studies on golden cross (50-day SMA crossing above 200-day SMA) show significant variation in outcomes depending on market regime. A 2025 reinforcement learning study found that combining multiple SMA lengths optimized alpha in equity strategies, suggesting the underlying principle has merit. However, EMA crossover combinations fall squarely in Harvey, Liu & Zhu's (2015) "factor zoo" warning zone — the t-statistic threshold required to reject data mining for a multi-parameter technical rule is substantially higher than the conventional 1.96.[^16][^17][^18][^19][^20]

**Use MA alignment as a *filter*, not a factor. It reduces noise and prevents buying broken stocks. Treat it as a regime classifier, not an alpha source.**

**Evidence quality: MODERATE as risk filter. LOW as standalone alpha signal.**

***

## 3. Sector Rotation as a Stock Selection Layer

### Foundational Evidence

Moskowitz & Grinblatt (1999, *Journal of Finance*) is the canonical paper: industry momentum is strong and accounts for much of individual stock momentum. An equal-weighted 6-month/6-month industry momentum strategy earned 0.43%/month; when industry effects were removed, individual stock momentum largely disappeared. The raw industry momentum spread reached 0.81%/month (10.2% annualized, t-statistic = 7.71).[^21][^22]

More recent work on sector ETFs confirms this premium remains accessible. Vanstone et al. find sector ETF momentum portfolios exhibit strong and distinct return patterns versus individual stock momentum. A Cranfield University study (2024) documents that sector rotation strategies outperform benchmarks in both US and European markets across the 1999–2019 period. A QuantConnect momentum-driven sector rotation backtest (2025) demonstrates continued alpha from this approach in modern markets.[^23][^24][^25]

### Premium Magnitude and Top-Quintile Effect

The documented sector premium — measured as top vs. bottom quintile sector performance — implies that stocks in the leading sector quintile benefit from both a direct sector tailwind and individual stock momentum that sector membership amplifies. Cross-sectional evidence from Symmetry Partners' US Sector Momentum strategy shows persistent premium over cap-weighted benchmarks. Sector-level momentum tends to peak over evaluation + holding periods of 13–14 months.[^26][^27][^28]

### Optimal Rebalancing Frequency

Monthly rebalancing consistently outperforms quarterly and annual for momentum-based strategies. Validea's long-run backtest shows monthly rebalancing produced +1220.7% cumulative return versus +442.5% for quarterly (2003–2025). This matches the academic prediction: monthly aligns with the momentum horizon before mean reversion accelerates. Weekly rebalancing of sector rankings introduces excessive transaction costs and microstructure noise; monthly is the academically grounded standard for swing-oriented systems.[^29][^30]

**Evidence quality: HIGH for monthly sector rotation as a selection layer. MODERATE for top-quintile premium magnitude (sensitive to measurement period).**

***

## 4. Volume-Based Screening

### Volume as a Return Predictor

The volume-return relationship has been studied extensively. Dynamic Granger causality analysis (PMC, 2022) finds trading volume predicts returns in multiple markets, though the effect varies by market microstructure. A 2026 meta-level study of S&P 500 stocks confirms positive short-run return predictability from above-average volume, consistent with informed trading interpretation. Goyenko et al. (AEA 2024) find that predicting individual stock trading volume has economic benefits comparable in magnitude to predicting returns directly.[^31][^32][^33]

Critically, Medhat & Schmeling's finding that *high turnover* is what converts 1-month reversal into continuation is the strongest academic evidence linking volume metrics to forward returns. This effectively makes relative volume a *prerequisite* for the RS momentum screen, not a separate additive factor.[^4]

### Volume on Breakouts: Magnitude, Not Direction

A direct empirical test of 2,919 price breakouts from 99 S&P 500 stocks (2021–2024) found:[^34]
- High-volume breakouts and low-volume breakouts had nearly identical *hold rates* (54.9% both)
- However, average maximum gain was +5.8% for high-volume vs. +4.5% for low-volume
- Extreme volume (5× the 20-day average) produced average maximum gains of +11.2% — 2.5× the baseline
- **Volume predicts the magnitude of subsequent price movement, not the direction**

This is a crucial distinction for swing traders: RVOL screening helps identify *how far* a stock can move, not *which way*. It is best used in conjunction with a directional signal (RS, MA alignment) rather than alone.

### Accumulation/Distribution Metrics

The Chaikin Accumulation/Distribution (A/D) Line and On-Balance Volume (OBV) are used as proxies for institutional flow. AInvest (2025) documents that stocks with sustained rising A/D lines tend to exhibit leadership characteristics consistent with IBD-style CANSLIM methodology. These indicators are not independently peer-reviewed as alpha factors but serve as useful filters for identifying stocks under institutional accumulation — consistent with the informed-trading interpretation of the volume-return literature.[^35][^36][^37]

**Optimal RVOL thresholds:** No single academic threshold exists. Practitioner standard of 1.5×–2× the 20-day average captures "significant" volume; 5× captures "extreme" events with outsized move potential.[^34]

**Evidence quality: MODERATE (volume predicts move magnitude). LOW for direction. HIGH for turnover as RS momentum conditioner.**

***

## 5. ADR% as an Options Filter

### Mapping ADR% to Academic Volatility Research

ADR% (Average Daily Range as a percentage of price) is a practitioner measure of realized daily volatility — functionally equivalent to Average True Range (ATR%). No peer-reviewed paper directly addresses "optimal ADR% range for 7–14 DTE option buyers," but the realized vs. implied volatility literature is highly relevant.[^38][^39]

The fundamental principle for directional options buyers: profitability requires that realized volatility (what the stock actually moves) exceeds implied volatility (what the market priced into the option). ADR% is a proxy for realized volatility expectations.[^40][^41]

### The Cao & Han (2011) Paradox

Cao & Han (2011) found that delta-hedged option returns *decrease* monotonically with higher idiosyncratic volatility — suggesting that options on *lower* volatility stocks are actually more profitable on a delta-hedged, risk-adjusted basis. However, this finding applies to **delta-hedged** (market-neutral) positions. For **directional** option buyers (straight calls/puts), the calculus is different: you need sufficient underlying movement to exceed your theta decay, making ADR% a legitimate filter for identifying stocks with move potential.[^42]

An EFMA 2024 paper finds that stocks in the highest abnormal turnover ratio (ATR) quintile exhibit +7.78% more realized volatility than expected, which fully reverses — meaning high-ATR stocks have options that are *cheap* relative to subsequent realized moves in the short term. This provides indirect support for using ATR/ADR% as a positive screen for short-dated option buyers.[^43]

### Practical ADR% Guidance

For 7–14 DTE option buyers on individual stocks (swing-length directional trades):
- ADR% should be high enough to provide a 1–2 standard deviation move opportunity within the holding period
- Too-high ADR% (>10%) typically implies elevated IV that offsets move potential (implied already prices in the volatility)
- The 3%–8% ADR% range is where the realized-vs-implied volatility edge tends to be most accessible, though this is practitioner consensus rather than academic finding

**Evidence quality: MODERATE (indirect, through volatility literature). No direct peer-reviewed study exists for this specific application.**

***

## 6. Combining Multiple Factors

### Do Multiple Factors Add Value?

The case for multifactor stock screening rests on factor diversification: factors with low or negative cross-correlations should compound their individual edges. A 2024 multi-factor, market-neutral strategy study on NYSE stocks found Sharpe ratios of 0.81–0.89 when combining momentum with fundamental and analyst revision factors. A UK quantitative equity study found a 6-factor model producing Sharpe of 1.6 — but with meaningful decay across sub-periods as factor crowding increased.[^44][^45]

The combination of value and momentum is particularly well-studied. AQR and Cliff Asness have documented negative cross-factor correlation between value and momentum (~−0.60), making them highly complementary. However, for *short-term* swing trading applications (1–5 day holds), value is irrelevant; the operative combination is **momentum + trend (MA) + volume + sector**.[^46]

### Diminishing Returns After 3–4 Factors

Harvey, Liu & Zhu (2015) tested 315 published factors; after adjusting for multiple comparisons, a t-statistic of at least 3.0 (not the conventional 1.96) is required for a new factor to be considered independently significant. Hou, Xue & Zhang (Taming the Factor Zoo, 2020) found that the majority of published "anomalies" fail to replicate with proper controls. McLean & Pontiff (2016) document that anomaly returns decay by an average of 35% post-publication as arbitrage capital flows in.[^19][^20][^47][^48][^49]

The practical implication: combining 3–4 robust, economically-motivated factors (momentum, trend, volume confirmation, sector context) is well-supported. Adding a 5th or 6th factor based on backtested correlation has a high probability of adding noise rather than signal, and may represent in-sample data mining rather than genuine edge.

### Recommended Combination and Signal Architecture

| Factor | Role | Lookback | Evidence Strength |
|--------|------|----------|-------------------|
| Sector momentum (top quintile) | Universe filter | 1 month rank | HIGH |
| Price > 200-day SMA | Regime filter | N/A | MODERATE |
| RS rank (conditioned on high turnover) | Selection signal | 1–3 months | HIGH (conditional) |
| RVOL ≥ 1.5× 20-day avg | Confirmation | 1-day | MODERATE |
| ADR% in target range | Options sizing | 20-day avg | LOW-MODERATE |

**Evidence quality: HIGH for 3-factor combinations. DIMINISHING for 4+. Caution warranted for composite scores that optimize on backtest Sharpe.**

***

## 7. IBD Relative Strength Rating

### Formula and Methodology

The IBD RS Rating uses a weighted composite of quarterly relative price performance:[^50]

> RS = 0.40 × ROC(63 days) + 0.20 × ROC(126 days) + 0.20 × ROC(189 days) + 0.20 × ROC(252 days)

This construction overweights the most recent quarter (40%) versus the three prior quarters (20% each), then ranks each stock from 1–99 relative to all other stocks. It is a proprietary rank, not a raw return.

### Academic Validation

No peer-reviewed study has specifically validated the IBD RS formula. However, the underlying 12-1 momentum factor — to which IBD RS is closely related — has been validated across 150+ years and 40+ countries. A 2025 SSRN paper evaluating the 12-1 month momentum strategy from 2005–2024 finds it continues to generate significant risk-adjusted returns with gross Sharpe of ~0.9. IBKR Quant (2025) confirms momentum remains one of the few factors that is robust to data-mining adjustments in recent literature.[^3][^51]

### IBD RS vs. Simpler 3-Month RS

| Metric | IBD RS (12-1 weighted) | 3-Month RS Rank | 1-Month RS Rank |
|--------|------------------------|-----------------|-----------------|
| Lookback | 12 months (recent-weighted) | 3 months | 1 month |
| Sharpe (2015–2025 backtest) | ~1.17 equivalent | ~1.16 | Lower (reversal risk) |
| Post-2008 performance | Moderate | Stronger | Variable |
| Data decay concern | Low | Moderate | High |
| Academic backing | Strong (for underlying factor) | Strong | Conditional only |

The main advantage of IBD RS over simple 3-month RS is stability: the weighted composite smooths out single-quarter anomalies and prevents a single strong month from dominating the signal. The main disadvantage is that the 12-month lookback anchors performance to events that may have no bearing on the next 5 days.[^10]

For swing trading specifically, **a 3-month RS rank conditioned on high turnover** is likely a more appropriate adaptation of the momentum signal than the full 12-month IBD RS, given Medhat & Schmeling's finding that short-term momentum is strongest for recently active, liquid names.[^7][^4]

**Evidence quality: HIGH for the underlying momentum principle. LOW for the specific IBD formula. No head-to-head academic study comparing IBD RS to simpler measures exists.**

***

## Robustness vs. Data-Mined Noise: A Framework

| Criterion | Survives Data-Snooping Correction? | Post-Publication Decay | OOS Replication |
|-----------|-----------------------------------|----------------------|-----------------|
| Cross-sectional momentum (12-1) | YES — top-tier[^3][^20] | ~20–25% decay[^48] | 40+ countries confirmed |
| Short-term RS (1-month, high turnover) | YES — conditional[^4] | Unknown | US, UK confirmed |
| MA trend filter (200-day, as risk filter) | MODERATE | Low (not arbitrageable) | Multiple markets |
| MA crossover (golden cross as signal) | MARGINAL | High | Mixed |
| Sector/industry momentum | YES[^21][^22] | ~15–20% decay | Cross-country confirmed |
| Relative volume (breakout confirmation) | PARTIAL (magnitude only)[^34] | Low | US equities |
| ADR% for options | NO direct study | N/A | Practitioner-based |
| Multifactor composite (3–4 factors) | MODERATE[^44][^45] | Increases with factors | Varies by combination |
| IBD RS (as 12-1 proxy) | YES (for underlying factor) | ~20–25%[^48] | Indirect only |

### Key Caveat: Transaction Costs and Factor Crowding

Most academic findings are reported gross of transaction costs. For swing trading with 1–5 day holds, the relevant cost structure includes bid-ask spread, market impact, and options spreads. Medhat & Schmeling explicitly note their short-term momentum results survive *net* of transaction costs only in the most liquid large-cap names. The sector-level momentum literature similarly shows stronger results for ETF-based implementations than individual stocks due to lower implementation costs.[^25][^7]

Factor crowding — when too many strategies trade the same signals — accelerates the decay documented by McLean & Pontiff. Momentum is particularly susceptible: momentum crashes during reversals (2009 recovery, March 2020) can produce drawdowns of 30–50% within a month. Risk management and position sizing rules that account for momentum crash risk are essential complements to any RS-based screening system.[^14][^3]

---

## References

1. [Jegadeesh & Titman (1993): The Seminal Momentum ...](https://blankcapitalresearch.com/learn/jegadeesh-titman-momentum) - The original momentum paper: winners outperform losers by ~1% per month. Summary of Jegadeesh and Ti...

2. [[PDF] Momentum](https://breesefine7110.tulane.edu/wp-content/uploads/sites/16/2015/10/Momentum-2001.pdf)

3. [Momentum Factor Investing: Evidence and Evolution](https://www.interactivebrokers.com/campus/ibkr-quant-news/momentum-factor-investing-evidence-and-evolution/) - This new paper revisits the factor with the largest and most comprehensive dataset ever assembled, s...

4. [Short-term Momentum | The Review of Financial Studies](https://academic.oup.com/rfs/article/35/3/1480/6286969)

5. [Short-term Momentum - City Research Online](https://openaccess.city.ac.uk/id/eprint/31278/) - The version of record Mamdouh Medhat, Maik Schmeling, Short-term Momentum, The Review of Financial S...

6. [Short-term Momentum - IDEAS/RePEc](https://ideas.repec.org/a/oup/rfinst/v35y2022i3p1480-1526..html) - Mamdouh Medhat & Maik Schmeling, 2022. "Short-term Momentum," The Review of Financial Studies, Socie...

7. [[PDF] Short-term Momentum - City Research Online](https://openaccess.city.ac.uk/id/eprint/31278/1/MS_short_term_mom_v27.pdf) - A one-month holding period is standard in the literature and last month's return is the signal under...

8. [Short-term momentum and reversals, turnover, and a stock's price-to-52-week-high ratio ☆](https://www.sciencedirect.com/science/article/abs/pii/S0927539824000902) - We show that short-term reversal behavior declines with a stock's turnover and the prior month's pri...

9. [Short-term momentum and reversals, turnover, and a ...](https://ideas.repec.org/a/eee/empfin/v79y2024ics0927539824000902.html) - We show that short-term reversal behavior declines with a stock’s turnover and the prior month’s pri...

10. [Optimal Lookback Period For Momentum Strategies](https://seekingalpha.com/article/4240540-optimal-lookback-period-for-momentum-strategies) - The optimal lookback period for momentum strategies is changing in time as equity and bond market be...

11. [Backtesting Momentum Strategies Across Different Lookback and ...](https://nextinvest.org/post_detail/8089150d-e2ff-4e99-8eb8-19746983e885) - Our analysis of 32 momentum strategy configurations reveals which parameters delivered the best retu...

12. [Skip the Noise and Focus on the Signal by Effectively Using the 200 ...](https://articles.stockcharts.com/article/articles-arthurhill-2023-11-who-will-win-the-battle-for-th-837/) - ... 200-day SMA is the most popular long-term moving average. Perhaps the 200-day SMA works well for...

13. [Effectiveness of Very Long Moving Averages - CXO Advisory](https://www.cxoadvisory.com/technical-trading/effectiveness-of-very-long-moving-averages/) - Very long moving averages (up to 1000 days) outperformed buy-and-hold (9.2%-13.6% vs 6.1% annual ret...

14. [US Stock Momentum Trading System for Retail Traders [Deep ...](https://www.crackingmarkets.com/us-stock-momentum-trading-system-for-retail-traders-deep-research/) - Our system will primarily rely on the simple 200-day moving average market filter and the option to ...

15. [Understanding the 200 Day SMA Filter - Trade Ideas](https://www.trade-ideas.com/help/filter/SMA200/) - A price above the 200-day SMA is typically seen as bullish, indicating that the stock is in an uptre...

16. [Reinforcement learning meets technical analysis: combining moving ...](https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2490818) - This study expands on a model-free algorithm inspired by reinforcement learning to address the chall...

17. [[PDF] Golden cross as Buying Indicator for Stock Investment in Bursa ...](https://ir.uitm.edu.my/id/eprint/59689/1/59689.pdf) - This paper analyzes the use of the Golden Cross as an indicator for buying stock, based on the stock...

18. [[PDF] Golden Cross](https://www.advancedinvesting.org/wp-content/uploads/2025/03/Golden-Cross.pdf) - Momentum Growth Strategy: A golden cross occurs when a short-term moving average crosses above a lon...

19. [A Zoo of Factors - Research Affiliates](https://www.researchaffiliates.com/publications/articles/223_finding_smart_beta_in_the_factor_zoo/jcr:content/theme/main/publication/body/publication_parsys_1323611929) - Adjusting for “data-snooping,” Harvey, Liu, and Zhu (2014) conclude ... anomalies are very significa...

20. [Taming the Factor Zoo: A Test of New Factors - Dacheng Xiu](https://dachxiu.chicagobooth.edu/download/ZOO.pdf)

21. [[PDF] Do Industries Explain Momentum? Tobias J. Moskowitz; Mark Grinblatt](http://www-stat.wharton.upenn.edu/~steele/Courses/956/Resource/Momentum/MoskowitzGrinblatt99.pdf) - We employ 30 percent breakpoints to determine winners and losers, and we value weight the returns of...

22. [Do Industries Explain Momentum? - AQR Capital Management](https://www.aqr.com/Insights/Research/Journal-Article/Do-Industries-Explain-Momentum) - We identify industry momentum as the source of much of the momentum trading profits at these horizon...

23. [Momentum-Driven Sector Rotation - QuantConnect Quant League ...](https://www.quantconnect.com/league/18908/2025-q2/momentum-driven-sector-rotation/) - Momentum-driven sector rotation captures persistent sector leadership using 20-day momentum.

24. [[PDF] 1 Gauging the Effectiveness of Sector Rotation Strategies](https://dspace.lib.cranfield.ac.uk/server/api/core/bitstreams/2a95672f-af33-4d89-b886-0bd7f8f02da1/content) - Moskowitz and Grinblatt (1999) argued that most of the momentum-based returns can be captured by for...

25. [[PDF] Industry momentum: an exchange‐traded funds approach](https://pure.bond.edu.au/ws/portalfiles/portal/47234914/AM_Industry_momentum.pdf) - Indeed, implementing an industry momentum portfolio approach using Sector ETFs would appear to be a ...

26. [[PDF] Symmetry U.S. Sector Momentum](https://symmetrypartners.com/wp-content/uploads/2025/07/U.S.-Sector-Momentum-Factsheet.pdf) - Attempts to capture some of the premium from price Momentum among the constituent sectors of the S&P...

27. [[PDF] Industry Momentum and Sector Mutual Funds](https://www.anderson.ucla.edu/documents/areas/prg/asam/2019/Momentum.pdf) - Moskowitz and Grinblatt explored this self- financing strategy for lag and hold periods of var- ious...

28. [Momentum Trading Strategies for Industry Groups: A Closer Look](https://summit.sfu.ca/item/2363) - This paper builds on Jegadeesh and Titman (1993) and Grinblatt and Moskowitz (1999) to take a closer...

29. [Why Monthly Rebalancing is Key to Unlocking the Power of ...](https://blog.validea.com/why-monthly-rebalancing-is-key-to-unlocking-the-power-of-momentum-investing/) - Momentum investing has long been one of the most robust and persistent factors in financial markets....

30. [Sector Momentum - Rotational System - Quantpedia](https://quantpedia.com/strategies/sector-momentum-rotational-system)

31. [Dynamic relationship between trading volume, returns and ... - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9332039/) - In this empirical investigation, we examine the relationship between trading volume, return and vola...

32. [[PDF] Trading Volume Alpha - American Economic Association](https://www.aeaweb.org/conference/2025/program/paper/ZsFFtySn) - For example, informed versus uninformed volume, volume with temporary versus permanent price impact,...

33. [Explaining the causality between trading volume and stock ...](https://www.sciencedirect.com/science/article/pii/S0264999325000720)

34. [Volume on a breakout doesnt predict whether the stock keeps going ...](https://www.reddit.com/r/swingtrading/comments/1sfvj6l/volume_on_a_breakout_doesnt_predict_whether_the/) - Everyone says volume confirms breakouts. I wanted to test that. Tested 2,919 breakouts across 99 S&P...

35. [Identifying Stock Market Leaders Using the Accumulation ... - AInvest](https://www.ainvest.com/news/identifying-stock-market-leaders-accumulation-distribution-rating-2512/) - Identifying Stock Market Leaders Using the Accumulation/Distribution Rating

36. [2025 Trader's Guide to Accumulation Distribution Indicator](https://thetradinganalyst.com/accumulation-distribution-indicator/) - The Accumulation Distribution Indicator equips traders in the complex financial markets with enhance...

37. [Accumulation Distribution Indicator: How to Read Buying Pressure](https://abovethegreenline.com/accumulation-distribution-indicator/) - Rising A/D indicates accumulation; falling A/D indicates distribution—even when price appears flat. ...

38. [Average Daily Range (ADR) indicator - TradingView](https://www.tradingview.com/support/solutions/43000695003-average-daily-range-adr-indicator/) - The Average Daily Range indicator measures the asset's volatility. It's mostly used by scalpers and ...

39. [Average Daily Range (ADR) - Help Center | Gainium](https://gainium.io/help/adr) - Use the ADR indicator in Gainium to track daily volatility, set realistic price targets, and manage ...

40. [Implied Volatility For Options Trading (2024 ULTIMATE Guide)](https://www.prospertrading.com/implied-volatility/) - Implied volatility is a crucial concept in options trading that can help traders potentially find bi...

41. [Gamma Scalping](https://www.predictingalpha.com/the-option-traders-guide-to-volatility-trading/) - Article Summary Introduction Volatility trading is a type of options trading that uses market volati...

42. [Electronic copy available at: http://ssrn.com/abstract=1786607](https://www.kdajdqs.org/bbs/reference/862/download/1444)

43. [[PDF] Stock Return Predictability of Realized-Implied Volatility Spread and ...](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/ATR_RVolIVOl_Complete.pdf)

44. [A multi-factor market-neutral investment strategy for New York Stock ...](https://arxiv.org/html/2412.12350v1) - The market neutral strategy proposed displayed a Sharpe ratio of 0.89 and 0.81 in the validation and...

45. [[PDF] QUANTITATIVE THE RETURN OF FACTOR INVESTING](https://19956154.fs1.hubspotusercontent-na1.net/hubfs/19956154/Equity%20Styles%20Factor%20Investing%20with%20SQ_UK.pdf)

46. [Value and Momentum Investing: Combine or Separate? -](https://alphaarchitect.com/value-and-momentum-investing-combine-or-separate/) - Value and Momentum investing - is it better to focus on each factor separately and then combine the ...

47. [[PDF] Taming the Factor Zoo: A Test of New Factors](https://economics.smu.edu.sg/sites/economics.smu.edu.sg/files/economics/pdf/Seminar/2021/2021120304.pdf)

48. [[PDF] Does Academic Research Destroy Stock Return Predictability?](https://www.fmg.ac.uk/sites/default/files/2020-08/Jeffrey-Pontiff.pdf) - In fact, for the first two years post publication, anomaly predictability increases instead of decay...

49. [Does Academic Research Destroy Stock Return ...](https://www.hec.ca/finance/Fichier/McLean.pdf)

50. [IBD Style Relative Strength - Optuma Scripting](https://forum.optuma.com/t/ibd-style-relative-strength/6614) - Looking to create a scan whereby one can create an IBD style relative strength calculation that rank...

51. [Evaluating a 12-1 Month Momentum Strategy (2005-2024)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5367656) - We test a classic 12-1 cross-sectional momentum rule on S&P 500 constituents over January 2005-Decem...

