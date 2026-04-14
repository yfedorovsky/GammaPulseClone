# GammaPulse System Validation — April 2026

**Purpose:** Source-backed validation of six question sets covering dealer hedging mechanics, McClellan Oscillator computation, Kelly Criterion for options, relative strength vehicle selection, volume profile context, and competitive data sources for the GammaPulse live trading platform.

***

## Question Set 1: Dealer Hedging — Duration & Magnitude

### Half-Life of GEX-Driven Price Impact

No peer-reviewed paper has published a precise, numeric half-life decay curve for GEX-driven price impact on SPY/SPX specifically. The closest empirical work is the 2025 Linköping University thesis *"Convexity in Motion"* (Nyberg & Jonsson), which used daily data from 2011–2025 and an Autoregressive Distributed Lag (ARDL) model to show that **changes in GEX are significantly and positively associated with S&P 500 returns across multiple time horizons**. Their rolling-window out-of-sample forecasts confirm that incorporating GEX meaningfully improves predictive accuracy versus a random-walk benchmark, but neither this work nor the SqueezeMetrics white paper provides the discrete decay curve you're looking for. The consensus from practitioner and academic sources is that GEX effects are primarily intraday, with the strongest impact in the direction of price reversal (positive gamma) or momentum (negative gamma) resolving within 1–3 days. **Bottom line:** An explicit half-life curve for SPX GEX impact does not yet exist in the published literature; your Baltussen et al. (2021) reference remains the closest canonical treatment.[^1][^2][^3][^4][^5]

### 0DTE Volume and the GEX Feedback Loop

The definitive post-2023 paper on this topic is Dim, Eraker, and Vilkov (2024), **"0DTEs: Trading, Gamma Risk and Volatility Propagation"** (SSRN 4692190, revised June 2025). Key finding: *"high aggregate gamma in 0DTEs does not propagate past index volatility and is instead inversely associated with intraday volatility."* In other words, high 0DTE gamma is on average **stabilizing**, not destabilizing — consistent with the earlier Wouts & Vilkov (2023) result you referenced. However, the paper also notes that positive (negative) Market Maker inventory gamma strengthens intraday price **reversal** (momentum), which is entirely consistent with GEX-based regime analysis. Critically for your system, the paper documents that *dealers' net gamma in 0DTE is on average positive* — retail net buyers of options generate net short-gamma dealer books less often than assumed. This means your 0DTE SPY scalps should weight the dealer position direction (HIRO-style flow confirmation) rather than assuming short-gamma by default. 0DTE volume now exceeds **50% of daily SPX volume** per SpotGamma's current methodology, confirming the structural importance.[^6][^7][^8][^9]

A separate 2024 paper, **"Zero DTE Options Gamma Hedging"** (SSRN, posted July 2025), makes the important nuance that high notional volume does not equal large hedging demand — *what matters is the net imbalance between buyer and seller sides*. If 50,000 contracts buy and 50,000 sell at a strike, dealer hedging is near zero despite $50B notional.[^10]

### Multi-Day Swing GEX (7–21 DTE): Structural or Intraday?

The academic literature is clear that **GEX effects are primarily an intraday phenomenon** at the index level. Strike-level gamma walls (call walls / put walls) have mechanical support/resistance properties that can persist across sessions — as long as open interest remains concentrated at those strikes — but the *dynamic hedging flow* that enforces them is intraday. MenthorQ's analysis confirms that "SPX gamma levels... define zones where dealer hedging activity can stabilize, pin, or accelerate price movement" for both intraday and multi-day behavior, but cautions that the effect wanes as DTE increases and open interest shifts. **Assessment for GammaPulse:** Using GEX *levels* (strike concentrations) as structural S/R for 7–21 DTE swing entries is defensible — large gamma walls tend to persist until expiry rolls. But expecting the *dynamic flow amplification* to persist overnight or across multiple sessions is not well-supported; that amplification is tied to same-session hedging mechanics. Your safest framing: GEX levels as static S/R zones, not dynamic momentum drivers, for multi-day swings.[^11][^2][^12][^1]

### GEX Signal Quality: SPX/SPY vs. Single Stocks

No published paper has directly studied GEX *signal quality degradation* by underlying (the specific question of why GEX is negative EV on individual equities but positive on SPY). However, the practitioner and ML literature offers a coherent explanation. A 2026 ML forecasting study noted that **post-2022, 0DTE options dominate SPX volume, and GEX without 0DTE separation is noisy for single-stock analysis**; best practice is computing GEX with and without 0DTE as separate features. The deeper structural reason: SPX/SPY options markets are orders of magnitude more liquid, with concentrated, institutionally-driven open interest at key strikes. Single-stock gamma walls are thinner, more fragmented across strikes and expiries, and subject to earnings/event disruption that breaks the dealer-hedging assumption. The SqueezeMetrics GEX white paper (2016/2017, updated) explicitly scoped its analysis to SPX-level dynamics and did not make claims about individual equity GEX predictiveness. **This aligns precisely with your empirical finding** — GEX as a standalone signal degrades significantly outside of broad index options where dealer dominance and open interest concentration are structurally robust.[^13][^14][^15]

***

## Question Set 2: McClellan Oscillator as Macro Filter

### Standard McClellan Oscillator Formula

Your formula — `EMA(19) of net advances − EMA(39) of net advances` — is correct and matches the **canonical McClellan Financial Publications definition**. The McClellan family uses the terminology "10% Trend" (= 19-day EMA, smoothing constant 0.10) and "5% Trend" (= 39-day EMA, smoothing constant 0.05). The exact formulas per the source:[^16][^17]

```
10% Trend (today) = 0.10 × (Advances − Declines) + 0.90 × 10% Trend (yesterday)
5% Trend (today)  = 0.05 × (Advances − Declines) + 0.95 × 5% Trend (yesterday)
McClellan Oscillator = 10% Trend − 5% Trend
```

There is, however, an important distinction: **raw net advances vs. ratio-adjusted net advances (RANA)**. McClellan Financial Publications historically uses raw net advances (advances minus declines). StockCharts.com and many modern platforms use the **ratio-adjusted** version: `(Advances − Declines) / (Advances + Declines) × 1000`. The RANA version normalizes for the changing total number of listed stocks — which matters for long-term historical comparisons — and produces different absolute values. **For GammaPulse:** If you compute raw A-D net advances across 5,025 common stocks, your oscillator values will be in a different numerical range than RANA-based NYMO from data vendors. Verify which format your reference thresholds assume.[^18][^19][^17]

### Predictive Power of NYMO for Options Trading

No peer-reviewed paper has specifically studied NYMO as a filter for *options* trading alpha (breadth + options alpha). The practitioner literature treats NYMO primarily as an equity momentum/mean-reversion filter. The Build Alpha platform documents market breadth indicators (NYSE Adv/Dec) as conditional filters for price-action strategy systems, and Option Alpha's backtested data shows that **adding a trend filter (200-day MA) to directional option selling strategies reduced drawdowns and improved consistency** even if gross returns were not substantially higher. This provides indirect support for the principle of breadth-conditioning options trades, but no published academic study specifically tests NYMO as an options trade filter.[^20][^21]

### Index ETF vs. Single-Stock Breadth Penalty

Your design choice to halve the breadth penalty for SPY/QQQ is practically well-motivated but not directly studied in academic literature. The foundational reason is well-understood: **index ETFs arbitrage against their constituents via authorized participants**, so their intraday price behavior is structurally coupled to the basket rather than to any aggregate breadth signal. A weak NYMO day reflecting broad internal weakness can coexist with SPY holding near all-time highs due to mega-cap concentration. This divergence (breadth vs. cap-weighted index) is widely documented by practitioners and is the subject of many internals-based strategy discussions, but there is no academic paper specifically validating a "halved breadth penalty" for index products vs. single stocks in an options context.[^20]

### Standard NYMO Overbought/Oversold Thresholds

The **±60** threshold you've seen is widely cited as the "extreme overbought/oversold" level by practitioners. Some sources use **±100** as a more conservative threshold for extreme readings:[^22][^23][^24]

| Reading | Interpretation |
|---------|---------------|
| Above +100 | Extreme overbought — potential pullback[^22] |
| +50 to +100 | Strong bullish breadth[^22] |
| −50 to +50 | Neutral zone[^22] |
| −100 to −50 | Strong bearish breadth[^22] |
| Below −100 | Extreme oversold — potential bounce[^22] |
| Below −60 / Above +60 | "Extremely oversold/overbought" (practitioner rule)[^23] |

**Critically**, McClellan Financial Publications themselves caution that numerical thresholds are an "overly simplistic way" to use the oscillator — *structure and pattern* (complex vs. simple structures above/below zero) matter more than absolute levels. Tom McClellan's preferred interpretation focuses on zero-line crossings and structural complexity, not on fixed overbought/oversold numbers.[^25]

***

## Question Set 3: Kelly Criterion for Options Trading

### Is Kelly Appropriate for Options?

Kelly criterion is theoretically applicable to options but requires careful adaptation. The core issue is that options returns exhibit **fat tails, strong positive skewness on long positions, and non-normal distributions** — violating the Gaussian assumptions underlying simple Kelly calculations. A 2009 *Wilmott Magazine* paper by Osorio derived a "prospect-Kelly" approach for fat-tail portfolios using Student's t-distribution, showing that traditional fractional-Kelly arises as a special case. The 2025 thesis *"High-Frequency Kelly Criterion and Fat-Tails"* (University of Texas) explicitly extends the Kelly framework to heavy-tailed distributions, deriving a high-frequency Kelly criterion that depends on the **Lévy triplet of returns** and demonstrates it on equity options straddle strategies. The key conclusion: **Kelly IS appropriate for options in principle, but the naive formula using observed win rate and average win/loss ratio systematically overestimates optimal bet size** when fat tails are present, because large outlier losses are underweighted in the historical average. The 2025 University of Warsaw paper *"Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put-Writing on Index Options"* (SPXW options, 0–5 DTE) finds that **a hybrid Kelly + VIX-regime sizing method** consistently outperforms pure Kelly, producing better risk-adjusted returns with robust drawdown control.[^26][^27][^28][^29]

### Quarter-Kelly vs. Half-Kelly vs. Fixed Fraction

The empirical evidence strongly favors fractional Kelly:[^30][^31][^32]

| Kelly Fraction | Ruin Probability (halve before double) | Return Capture |
|---------------|----------------------------------------|---------------|
| Full Kelly | ~33% | 100% theoretical max |
| Half Kelly | ~11% | ~75% of optimal |
| Quarter Kelly | <3% (industry standard) | ~56% of optimal |

Half-Kelly captures approximately **71% of optimal returns with only ~38% of the volatility** of full Kelly. A tastylive analysis confirms this tradeoff. **No published paper specifically compares Kelly variants on options strategies only** (the research tends to use broad equity or fixed-odds settings), but the Warsaw paper tests Kelly + VIX hybrid specifically on short-put SPXW options and finds the hybrid clearly superior to pure Kelly in drawdown management. For options with asymmetric payoffs (capped downside, variable upside), the literature recommendation is to use fractional Kelly (quarter to half) and to compute Kelly parameters separately for each payoff regime rather than a single blended estimate.[^31][^26]

### Sample Size for Kelly Parameter Estimates

The literature is damning about small-sample Kelly calibration. Key benchmarks:[^33][^34]

- **30 trades** — CLT floor; statistical assumptions become unreliable below this
- **100–300 trades** — Basic reliability per Kevin Davey
- **200–500 trades** — Institutional-grade confidence per López de Prado
- **500–1000+** — What institutional desks require, including out-of-sample data

Your 569-trade sample at the portfolio level is near the institutional minimum, but your **UNPROVEN tier (< 3 trades)** is far below any defensible threshold. The "highest Kelly multiplier for UNPROVEN tickers" finding is almost certainly a **small-sample bias artifact**, not a real signal. One practitioner source argues you should *ignore the Kelly formula entirely* until you have at least 300 real trades per category. The PROVEN tier at 10 trades is also far short — at 10 trades, you cannot distinguish a 70% win rate from a 55% win rate at 95% confidence. **Practical recommendation:** Cap UNPROVEN and early-tier Kelly multipliers at a conservative fixed fraction (e.g., quarter Kelly of your overall calibrated fraction) until each tier accumulates 50+ trades, then reassess.[^34][^33]

### Rolling Circuit Breakers + Kelly

No academic paper has studied the specific combination of rolling win-rate circuit breakers with Kelly sizing. The closest treatments are in practitioner quantitative trading literature. Ernie Chan's blog (quantitativetradingblog.blogspot.com) describes limiting drawdown under Kelly by reducing leverage proportionally to the drawdown from peak — similar in spirit to your L1/L2/L3 system. The Elite Trader thread on Kelly + drawdown reduction documents the practitioner approach of combining Kelly fraction with a drawdown-based contract-reduction rule. This is a well-accepted practice without formal academic study. **Your L1/L2/L3 system (20%/10%/0% rolling WR thresholds reducing position size) is methodologically sound** and consistent with practitioner risk management — it prevents Kelly overbet ruin during regime shifts that the static historical calibration didn't capture.[^35][^36]

***

## Question Set 4: Relative Trend Strength as Vehicle Selection

### Relative Strength as an Options Trade Filter

Heston, Jones, Khorram, Li, and Mo (2021), **"Option Momentum"** (*Journal of Finance*, December 2021), is the canonical academic reference. They use delta-neutral straddles on individual equities (1996–2019) and find that **option momentum (6–36 month formation periods) is far stronger than equity momentum**, with a pre-cost Sharpe ratio at least three times higher than cross-sectional stock momentum. This work focuses on *options* momentum, not RS vs. an index as a filter for directional options trades. Käfer, Mörke, and Wiest (2023), "Option Factor Momentum" (University of St. Gallen), extends this finding to option factors, documenting profitable cross-sectional and time-series momentum in 56 delta-hedged option factors. Option Alpha's backtest data shows that **trading with the trend (above/below 200-day MA) reduces drawdowns** in directional option selling strategies, though it doesn't dramatically increase profits. No paper directly studies **RS vs. SPX 20d/60d as a filter for directional options trade outcomes** (the specific GammaPulse RTS framing), but the collective evidence strongly supports using equity momentum to improve option trade entry quality.[^37][^38][^39][^21]

### ATR Extension as a Mean-Reversion Filter

ATR-based mean reversion is a documented quantitative strategy filter with practitioner consensus around 2–3 ATR thresholds. Your specific thresholds (2 ATR = EXTENDED, 3 ATR = OVEREXTENDED) are consistent with practitioner implementations, though published academic work on this topic is sparse. ATR mean-reversion strategies are widely implemented in algorithmic trading platforms; the Adaptive Trend-Following ATR strategy and the ATR Channel Mean Reversion strategy both use dynamic ATR thresholds to signal overextension. **No academic paper establishes a universally validated threshold**; the 2–3 ATR range appears to be practitioner-consensus rather than academically derived. Given that ATR measures volatility, not just distance, the correct interpretation is: a stock >2 ATR above its 20MA has moved an unusually large amount *relative to its own recent volatility*, making mean reversion increasingly probable — a statistically sound intuition even without a published paper explicitly proving your specific thresholds.[^40][^41]

### Industry Momentum (Sector Leadership)

Moskowitz and Grinblatt (1999), **"Do Industries Explain Momentum?"** (*Journal of Finance*), is the seminal reference. Key findings: industry portfolios exhibit significant momentum over 6–12 month horizons; **the profitability of individual stock momentum strategies is largely explained by industry momentum effects**; a strategy of buying winner industries and shorting loser industries generates statistically significant payoffs uncorrelated with size or book-to-market factors. This is strongly supportive of your LEADING/EMERGING/WEAKENING/BROKEN industry scoring. However, **Molchanov and Stangl (2023)** in *"The Myth of Business Cycle Sector Rotation"* (*International Journal of Finance and Economics*) find that conventional sector rotation strategies (rotating with the business cycle) generate only modest outperformance before transaction costs. The resolution: **short-to-intermediate horizon industry momentum (1–12 months) is well-documented**; long-horizon business-cycle-based rotation is not. GammaPulse's scoring of industry leadership over days-to-weeks is in the academically supported range. A 2024 arXiv paper on sector rotation by factor model confirms that **momentum and short-term reversion are the most significant factors in sectoral shifts**.[^42][^43][^44][^45][^46][^47]

On the options-specific dimension: the LLM + GEX study (IJFBS, 2025) found that **incorporating GEX improved caution (reduced false entries) but reduced raw return rates** in breakout strategies, suggesting GEX acts as a quality filter rather than a return enhancer in momentum-based setups — which aligns with your system design where GEX defines the entry level, not the trade direction.[^48]

### Combining Momentum Ranking with GEX Levels

No published academic paper directly studies the combination of **relative strength ranking + GEX entry levels**. This is a genuine gap in the literature. The practitioner community (evidenced by YouTube content, Discord communities, and platforms like MenthorQ) widely uses this combination intuitively, but the closest academic analogue is the broader literature on combining momentum signals with microstructure signals. The 2025 IJFBS paper testing LLMs with GEX confirmation is the closest approximation — and its finding that GEX improves *caution* (entry precision) aligns with using GEX as the entry refiner after RS selects the ticker.[^2][^49][^48]

***

## Question Set 5: Volume Profile as Context Layer

### Point of Control (POC) as Support/Resistance

There is peer-reviewed evidence supporting POC as a meaningful price level. Jóźwicki and Trippner (2025), **"Use of the Volume Profile in Making Investment Decisions on the Stock Market"** (*Journal of Finance and Financial Law*, University of Lodz), studied the WIG20 index January–June 2024 and found that **"a noticeable reaction of the WIG20 index value to the POC of the preceding session took place in approximately 90% of cases"**. While this is a short sample period and one market, it provides direct statistical support for the POC-as-next-day-magnet hypothesis. The self-fulfilling vs. structural debate is unresolved — a high-volume POC represents a price at which the most bilateral consensus trading occurred, which gives it both informational weight (it's fair value to many participants) and potential mean-reversion gravity (unfilled orders cluster near it). **POC is not purely self-fulfilling** in the way that a simple moving average might be; it reflects actual historical order flow concentration.[^50][^51][^52]

### VP + GEX Overlap: Does Co-location Strengthen the Signal?

No academic paper studies the interaction between POC and GEX strike levels. However, the practitioner logic is coherent: a GEX "king" strike with high open interest concentration generates large dealer hedging flows at that price level, and if the same level is the POC (where historical trading consensus clustered), **both mechanical (dealer hedging) and informational (prior trading consensus) forces point to the same level** — a classic confluence signal. Order flow analysis practitioners explicitly combine these signals in live trading (see the April 2026 "How To Use Orderflow And GEX Levels" video). The absence of academic literature here reflects that this is a practitioner methodology, not a lack of theoretical merit.[^49]

### Session VP vs. Multi-Day VP for 0DTE Trading

Practitioner consensus favors **multi-day or prior-session VP as the higher-weight reference frame**, with session VP as a real-time context layer for same-day execution. The YouTube analysis from 0DTE VP traders notes that "the longer data has overwhelming percentage greater effect than the session data; the session data is subservient to the long-term data". For 0DTE specifically:[^53][^54][^52]

- **Prior-day RTH session profile**: Best for identifying overnight positioning and gap fill targets
- **Multi-day or weekly composite**: Defines macro S/R zones that the 0DTE will trade around
- **Current session VP**: Useful for intraday balance/imbalance detection after the first 30–60 minutes of trading establish an early POC

No published academic paper defines an optimal VP lookback for 0DTE trading — this remains practitioner domain knowledge.

### Value Area (70%) as Mean-Reversion Zone

The 70% Value Area derives from market profile theory (Pete Steidlmayer, 1980s) and the observation that a normal distribution's one-standard-deviation range covers ~68.2% of observations — leading to the ~70% convention for the value area. Statistical support for VA boundaries as support/resistance exists at the practitioner level: Charles Schwab's educational materials confirm the standard 70% convention, and Alchemy Markets documents the VAH/VAL as key mean-reversion zones. The formal academic study of value area boundaries (as distinct from POC) is sparse; the Jóźwicki/Trippner paper focuses on POC specifically. The mean-reversion logic is sound: price breaking cleanly outside the value area signals **discovery mode** (potential for continuation), while price re-entering from outside signals **acceptance/reversion** back toward the POC. This is a well-accepted practitioner framework with partial academic backing via the POC research.[^55][^56][^50]

***

## Question Set 6: Competition & Data Sources

### SpotGamma Methodology — April 2026 Status

SpotGamma has continued active development through 2025–2026. Key updates confirmed:

- **HIRO ("Super HIRO") upgrade** (October 2025): SpotGamma launched a significantly upgraded HIRO indicator tracking real-time options hedging flows down to the second, with improved 0DTE impact modeling[^57]
- **TRACE product**: A real-time S&P 500 options heatmap showing live hedging flow by strike, available on the Alpha plan[^58][^57]
- **Synthetic OI Lens**: Exclusive to the Alpha plan, shows "true dealer positioning" (inferred dealer-side open interest) as opposed to total OI[^59]
- **SpotGamma Vol Trigger / Gamma Flip**: No published methodology update since 2024; the core logic (gamma-weighted zero-crossing across the options surface) remains the same. SpotGamma's Founder Brent Kochuba raised the SPX Risk Pivot to 6,900 in February 2026 and continues to publish daily Vol Trigger levels[^60][^61][^6]
- **Coverage**: SpotGamma calculates GEX across the four nearest expirations, including 0DTE, which they describe as critical given 0DTE now drives >50% of SPX daily volume[^6]

SpotGamma has **not published** a detailed methodology whitepaper update since their earlier disclosures. Their sign convention (customer long calls = dealer short calls = negative gamma from dealer perspective, normalized to the "GEX positive = dealers long gamma" convention) is standard and consistent with the SqueezeMetrics white paper.[^62]

### Massive/Polygon Real-Time Greeks — Latency Confirmation

Your live test showing **delta updating every ~30 seconds** is consistent with Massive's documented plan structure. The Starter plan ($29/month) is explicitly documented as providing **15-minute delayed WebSocket access**, not real-time. The Advanced plan ($199/month) is required for real-time access. Massive's blog post on aggregate bar delays confirms they intentionally wait 2 additional seconds for high-latency messages on second-level aggregates. **The 30-second delta refresh you observed is not a bug or latency issue — it reflects the Starter plan's delayed data tier**. For a live capital deployment requiring real-time Greeks, you either need the Advanced plan ($199/month) or should confirm whether your Greeks calculations via a separate real-time feed (e.g., the $29 options Greeks snapshot API documented on Massive's blog) provide on-demand real-time computation vs. cached quotes.[^63][^64][^65][^66]

### CBOE Dealer Positioning Sign Convention & New Data Sources

The **standard sign convention** (customer perspective: calls +1, puts -1; dealer perspective: opposite) remains unchanged and is consistent across SpotGamma, MenthorQ, SqueezeMetrics, and open-source implementations. No new SEC or CBOE public data source has emerged since 2024 that directly provides validated dealer positioning. CBOE did file a major regulatory proposal in March 2026 for near-24x5 equities trading on EDGX (December 2026 launch), but this does not affect options GEX data. CBOE's 2025 annual report confirms 2025 was the sixth consecutive record year for U.S. listed options, with total volume exceeding 15.2 billion contracts (26% above 2024). No new public data source for validating the sign convention has emerged; the CBOE's published open interest data (used by all GEX tools) remains the primary input.[^67][^68][^69][^70][^71]

### Open-Source GEX Tools — 2025–2026 GitHub Landscape

Several notable open-source GEX projects exist, though most continue to use the standard BSM-gamma snapshot model:

| Project | Approach | Data Source |
|---------|----------|------------|
| `alexjust-data/gex-options-realtime` (2025)[^72] | Full backend system: GEX + Vanna + Charm via FastAPI; inspired by GexBot/Hedgeye | SPX, NDX, ES, QQQ |
| `KaranChavan21/GEX_Dashboard` (2025)[^73] | Real-time option chain → BSM Greeks → GEX + DEX + flow | Sub-second, multi-expiry |
| `aakash-code/GammaGEX` (2025)[^74] | Greek-based momentum: GEX + Delta-Weighted Volume Flow + Gamma Squeeze + Vanna/Charm + IV Skew | OpenAlgo / Upstox (Indian markets) |
| `Gurrel/GEX-Levels` (2024)[^75] | Real-time yFinance GEX with Plotly dashboard | MarketData App API |
| `erma0x/gexxer`[^76] | Standard BSM GEX + Fibonacci/Elliott/VIX context | Yahoo Finance |

**None of these use order flow or trade-level data instead of open interest snapshots** — the open-source community has not yet implemented a robust order-flow-derived GEX (which would require expensive Level 1/2 data and complex directional inference). FlashAlpha is a newer commercial API offering real-time GEX, SVI volatility surfaces, and Greeks for 6,000+ underlyings with a free tier — worth evaluating as a complement to Massive for Greeks latency. The `alexjust-data` project is the most architecturally sophisticated open-source effort (FastAPI backend, similar in spirit to GammaPulse), though it remains a BSM snapshot model.[^72][^77]

***

## Key Gaps and Open Research Questions

The following questions from your prompt currently have **no peer-reviewed answer**:

1. **Explicit GEX half-life decay curve for SPX/SPY** — This is a genuine gap. The closest work (Nyberg & Jonsson, 2025) shows multi-day predictive power but no decay parameterization.
2. **NYMO specifically as an options trading filter** — No academic paper; practitioner backtests show directional filters reduce drawdowns.
3. **GEX signal quality degradation by underlying type** — No direct study; inference from SqueezeMetrics scope limitation and ML GEX contamination literature.
4. **VP + GEX confluence signals** — No academic study; practitioner consensus is directionally supportive.
5. **Kelly circuit breakers + drawdown triggers** — No academic paper; practitioner implementations align with your L1/L2/L3 design.
6. **Optimal VP lookback for 0DTE** — Practitioner consensus: prior-session RTH + multi-day composite; no academic study.
7. **Combining RS ranking with GEX entry levels** — No published paper; indirect support from option momentum literature.

***

## Summary Assessment for Live Deployment

| Component | Academic Support | Key Risk | Recommendation |
|-----------|-----------------|----------|----------------|
| GEX for 0DTE SPY intraday | Strong[^7][^8] | Flow direction, not just sign | Add HIRO-style flow confirmation |
| GEX for 7–21 DTE single stocks | Weak/absent | Negative EV confirmed by your data | Use GEX *levels* as S/R only; reduce position size vs. SPY trades |
| NYMO as macro filter | Moderate (practitioner) | Raw vs. RANA divergence | Verify your formula vs. data vendor format |
| NYMO thresholds (±60/±100) | Moderate[^23][^22] | McClellan prefers structure over levels | Add pattern analysis beyond numeric threshold |
| Kelly sizing (569 trades) | Moderate[^26][^27] | UNPROVEN tier (< 3 trades) is noise | Cap UNPROVEN at quarter-Kelly of portfolio fraction |
| Fractional Kelly (yours) | Strong[^30][^31] | Fat tail underestimation | Consider hybrid Kelly + VIX-regime sizing[^26] |
| RTS + industry momentum | Strong[^45][^46] | Business-cycle rotation ≠ momentum | Short-to-intermediate formation periods validated |
| ATR extension flags | Moderate (practitioner) | No canonical threshold | 2–3 ATR range is consistent with practitioner consensus |
| Volume Profile POC | Moderate[^50] | Short sample study | Use as confluence, not standalone trigger |
| Massive Starter Plan Greeks | Confirmed[^65] | **15-minute delay on $29 plan** | Upgrade to Advanced ($199) for real-time Greeks |

---

## References

1. [How Dealer Positioning and Gamma Exposure Impacts Markets](https://mottcapitalmanagement.com/gamma-exposure-gex-often-drives-short-term-market-moves/?amp) - When dealers hold net long gamma, their hedging tends to act as a shock absorber. In a positive gamm...

2. [SPX Net GEX: Market Makers & Gamma Guide - MenthorQ](https://menthorq.com/guide/spx-net-gex-market-makers-gamma/) - This article explains how market makers' gamma exposure and hedging flows from SPX options drive vol...

3. [[PDF] Convexity in Motion - Diva-portal.org](https://liu.diva-portal.org/smash/get/diva2:1972044/FULLTEXT01.pdf) - This thesis investigates whether aggregate gamma exposure (GEX) in the S&P 500 index options market ...

4. [Leveraging Gamma Exposure to Predict Equity Market ...](https://liu.diva-portal.org/smash/record.jsf?pid=diva2%3A1972044) - This thesis investigates whether aggregate gamma exposure (GEX) in the S&P 500 index options market ...

5. [Convexity in Motion](https://www.diva-portal.org/smash/get/diva2:1972044/FULLTEXT01.pdf)

6. [Gamma Exposure (GEX) | SpotGamma™](https://spotgamma.com/gamma-exposure-gex/) - Gamma Exposure (GEX) is the estimated net gamma position held by options market makers across all st...

7. [0DTEs: Trading, Gamma Risk and Volatility Propagation](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190) - We study the recent explosion in trading of same-day expiry (0DTE) options on the S&P500 index and e...

8. [0DTEs: Trading, Gamma Risk and Volatility Propagation](https://colab.ws/articles/10.2139%2Fssrn.4692190) - Short-term, especially same-day expiry (0DTE), options trading has recently surged, raising concerns...

9. [[PDF] 0DTEs: Trading, Gamma Risk and Volatility Propagation](https://papers.ssrn.com/sol3/Delivery.cfm/4692190.pdf?abstractid=4692190&mirid=1) - Wehrli, 2022, “On the Directional Destabilizing Feedback Effects of. Option Hedging,” Swiss Finance ...

10. [Zero DTE Options Gamma Hedging](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5329719) - This paper is devoted to the sensitivity analysis of Zero-Days-to-Expiration options (0DTE options) ...

11. [Gamma Exposure Explained: How to See the Hidden Price Points ...](https://www.barchart.com/story/news/35756961/gamma-exposure-explained-how-to-see-the-hidden-price-points-where-market-makers-move-stocks) - Gamma exposure, often shortened to GEX, measures how market makers and options dealers adjust their ...

12. [I tracked dealer gamma exposure on SPX for 6 months. Here's what ...](https://www.reddit.com/r/options_trading/comments/1s3vmf9/i_tracked_dealer_gamma_exposure_on_spx_for_6/) - When dealers are short gamma, they amplify moves instead of dampening them. Every tick in one direct...

13. [Gamma Exposure in SPX Options: Insights from SqueezeMetrics ...](https://www.studocu.com/en-us/document/yale-university/international-finance/gamma-exposure-in-spx-options-insights-from-squeezemetrics-research/147874545) - This document explores Gamma Exposure (GEX) in SPX options, presenting a model to quantify hedge reb...

14. [ML Approaches for Predicting SPX Intraday Direction Using Options ...](https://qorsync.online/blog/61-ml-spx-prediction) - This report synthesizes the current state of research and practice in using machine learning models ...

15. [Gamma Exposure Analysis: Understanding SPX Options Dynamics](https://www.studocu.com/en-us/document/purdue-university-northwest/international-finance-and-banking/gamma-exposure-analysis-understanding-spx-options-dynamics/153015181) - Discover how Gamma Exposure (GEX) enhances understanding of equity options' impact on stock prices, ...

16. [Exponential Moving Averages Calculation - Technical Analysis Learning - McClellan Financial](https://www.mcoscillator.com/learning_center/kb/market_data/exponential_moving_averages_calculation/)

17. [The McClellan Oscillator & Summation Index](https://www.mcoscillator.com/learning_center/kb/mcclellan_oscillator/the_mcclellan_oscillator_summation_index/) - Every day that stocks are traded, financial publications list the number of stocks that closed highe...

18. [McClellan Summation Index - ChartSchool - StockCharts.com](https://chartschool.stockcharts.com/table-of-contents/market-indicators/mcclellan-summation-index) - Ratio-adjusted Net Advances equals Net Advances divided by advances plus declines. This shows Net Ad...

19. [McClellan Oscillator - ChartSchool - StockCharts.com](https://chartschool.stockcharts.com/table-of-contents/market-indicators/mcclellan-oscillator) - The McClellan Oscillator is a breadth indicator derived from Net Advances, which is the number of ad...

20. [Market Breadth Indicators for Algo Trading | TRIN, TICK & More](https://www.buildalpha.com/market-breadth/) - In this article I will explain the main market breadth indicators, what they quantify, and how to ad...

21. [Trend Trading: Backtesting Options Strategies | Podcast - Option Alpha](https://optionalpha.com/podcast/trend-trading) - We backtested directional option selling strategies with a long-term trend filter to see if there wa...

22. [McClellan Oscillator Calculator - Free Market Breadth Tool | Pineify](https://pineify.app/mcclellan-oscillator-calculator) - Calculate McClellan Oscillator and Summation Index from market breadth data. Identify overbought/ove...

23. [This is Not the Time to Press Your Bets | Jeff Clark Trader](https://www.jeffclarktrader.com/market-minute/this-is-not-the-time-to-press-your-bets/) - If you needed just another reason or two to be cautious after the market’s big rally in April...

24. [2025 Trader's Guide to McClellan Oscillator - The Trading Analyst](https://thetradinganalyst.com/mcclellan-oscillator/) - The McClellan Oscillator becomes an essential tool. It helps light up the way for making smart trade...

25. [Overbought McClellan Oscillator - Free Weekly Technical Analysis Chart - McClellan Financial](https://www.mcoscillator.com/learning_center/weekly_chart/overbought_mcclellan_oscillator/)

26. [5 Results](https://arxiv.org/html/2508.16598v1)

27. [[PDF] HIGH-FREQUENCY KELLY CRITERION AND FAT-TAILS](https://austinpollok.github.io/files/HighFrequency_KellyCriterion_and_FatTails.pdf)

28. [A prospect‐theory approach to the Kelly criterion for fat‐tail portfolios: the case of Student's __t__‐distribution](https://onlinelibrary.wiley.com/doi/abs/10.1002/wilj.7) - ## Abstract

An analytic approximation is derived for leverage levels that result from optimization ...

29. [Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put- ...](https://arxiv.org/pdf/2508.16598.pdf)

30. [The Mathematical Execution Behind Prediction Market Alpha](https://navnoorbawa.substack.com/p/the-mathematical-execution-behind) - Empirical Performance: Full Kelly: 33% probability of halving bankroll before doubling. Half Kelly: ...

31. [The Smart Trader's Guide to Kelly's Criterion - tastylive](https://www.tastylive.com/news-insights/smart-trader-guide-kellys-criterion) - The half Kelly thus has a higher risk-adjusted return. Using a Kelly fraction provides a better bala...

32. [Options Position Sizing: Kelly Criterion Explained - Longbridge](https://longbridge.com/en/academy/options/blog/options-position-sizing-kelly-criterion-explained-100160) - Using fractional Kelly (half or quarter of the full formula output) is widely recommended to balance...

33. [Minimum Trades for a Valid Backtest? Calculator + Research](https://www.backtestbase.com/education/how-many-trades-for-backtest) - Minimum trades to validate a backtest? 200-500 trades across multiple market regimes. Free calculato...

34. [The Kelly Criterion: How to Size Positions - tradicted](https://www.tradicted.com/learn/kelly-criterion/) - The Kelly Criterion calculates your optimal position size from your win rate and Risk/Reward ratio. ...

35. [Kelly Criterion & Positions Sizing [Overview] | Page 2 - Elite Trader](https://www.elitetrader.com/et/threads/kelly-criterion-positions-sizing-overview.381330/page-2) - Drawdown Reduction: Reduce the number of contracts during drawdowns. This combination dynamically ad...

36. [How do you limit drawdown using Kelly formula? - Quantitative Trading](http://epchan.blogspot.com/2010/04/how-do-you-limit-drawdown-using-kelly.html) - There is an easy way, though, that you can use Kelly formula to limit your drawdown to be much less ...

37. [Does Momentum work in Option Markets?](https://alphaarchitect.com/2022/11/option-momentum/) - This paper explores the question of option momentum by examining what the research says about the pe...

38. [KAEFER MOERKE WIEST 2023](https://www.alexandria.unisg.ch/server/api/core/bitstreams/77c18800-3626-42f1-b413-ee60db6902c1/content)

39. [Option Momentum](http://faculty.marshall.usc.edu/Christopher-Jones/pdf/opmom.pdf)

40. [Adaptive Trend-Following Multi-Period ATR Dynamic ...](https://www.fmz.com/lang/en/strategy/482807) - Overview This strategy is a short-selling mean reversion trading system based on ATR (Average True R...

41. [ATR Channel Mean Reversion Quantitative Trading Strategy](https://www.fmz.com/lang/en/strategy/434995) - Overview This is a long-only strategy that identifies entry signals when prices break below the lowe...

42. [Sector Rotation by Factor Model and Fundamental Analysis - arXiv](https://arxiv.org/html/2401.00001v1) - This study presents an analytical approach to sector rotation, leveraging both factor models and fun...

43. [The myth of business cycle sector rotation - Wiley Online Library](https://onlinelibrary.wiley.com/doi/10.1002/ijfe.2882) - We find that relaxing sector rotation assumptions and letting any industry excess return predict fut...

44. [[PDF] The Myth of Sector Rotation - ACFR - AUT](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/294287/The-Myth-of-Sector-Rotation-non-blind.pdf) - Sector rotation refers to a common investment strategy that targets investments in particular econom...

45. [[PDF] On industry momentum strategies - Osuva](https://osuva.uwasa.fi/bitstreams/93bf698a-1bb0-4885-bf5a-76df70e6443d/download) - Following seminal work by Jegadeesh and Titman (1993) on momentum profits,. Moskowitz and Grinblatt ...

46. [[PDF] Do Industries Explain Momentum? Tobias J. Moskowitz; Mark Grinblatt](http://www-stat.wharton.upenn.edu/~steele/Courses/956/Resource/Momentum/MoskowitzGrinblatt99.pdf) - "Moskowitz is from the Graduate School of Business, University of Chicago (tobias. moskowitz@gsb.uch...

47. [Do Industries Explain Momentum? - AQR Capital Management](https://www.aqr.com/Insights/Research/Journal-Article/Do-Industries-Explain-Momentum) - This paper largely focuses on the positive persistence in stock returns (or momentum effect) over in...

48. [[PDF] Finance & Banking Studies - SSBFNET](https://www.ssbfnet.com/ojs/index.php/ijfbs/article/download/4219/2785/16298) - GEX added a market microstructure lens that may enhance signal precision (Buis et al., 2024). If set...

49. [How To Use Orderflow And GEX Levels In Your Trading - YouTube](https://www.youtube.com/watch?v=aV0NQCoeBsg) - This video is an educational trading video going over orderflow trading , Options flow also known as...

50. [[PDF] USE OF THE VOLUME PROFILE IN MAKING INVESTMENT ...](https://czasopisma.uni.lodz.pl/fipf/article/download/28410/27868/72359) - sis, indicate that the volume profile, by determining the POC (point of control), facilitates the pr...

51. [Volume Profile & POC: My #1 Trading Strategy Explained](https://www.trader-dale.com/my-best-trading-strategy-learn-how-to-trade-using-volume-profile-and-poc/) - That's the trade — you're not guessing support and resistance, you're reading the actual evidence of...

52. [Trading with Volume Profile | Market Acceptance & Rejection](https://internationaltradinginstitute.com/blog/reading-the-volume-profile-from-acceptance-to-rejection/) - Learn how to read the volume profile like a pro—spotting acceptance, rejection, and high-probability...

53. [Understanding Volume Profile: A Practical Guide for Day Traders](https://www.reddit.com/r/Daytrading/comments/1rrc6ug/understanding_volume_profile_a_practical_guide/) - Volume profile works best on 15min+ timeframes for intraday. Always combine with price action, not i...

54. [0-DTE - The Truth About Daily Volume Profile Analysis - YouTube](https://www.youtube.com/watch?v=ZS-pdDKJA-U) - Dive into the intricacies of using Volume Profile for day trading, specifically focusing on today's ...

55. [Using the Volume Profile Indicator - Charles Schwab](https://www.schwab.com/learn/story/using-volume-profile-indicator) - The price level with the the highest volume (widest horizontal row) is referred to as the point of c...

56. [Volume Profile Effective Trading Guide - Alchemy Markets](https://alchemymarkets.com/education/indicators/volume-profile/) - Learn how to trade with the Volume Profile indicator—spot value zones, volume nodes, and high-probab...

57. [Unveil Hidden Flows in Real Time: Super HIRO Deep Dive | SpotGamma](https://www.youtube.com/watch?v=9VLNmB5zJYI) - Go deeper into our upgraded HIRO to track real-time options hedging flows, discover the impact of 0D...

58. [SpotGamma Review, Pricing, and Features (2026) - Find My Moat](https://www.findmymoat.com/tools/spotgamma) - SpotGamma review: Options‑market microstructure & dealer‑positioning analytics. Core modules: Equity...

59. [SpotGamma Review 2026 • OptionsScanners.com](https://optionsscanners.com/review/spotgamma) - Our SpotGamma review helps you understand the features and functionalities of the options screener, ...

60. [volatility trigger Archives | SpotGamma™](https://spotgamma.com/tag/volatility-trigger/) - The concept of the volatility trigger is that when the market moves below the Trigger, options deale...

61. [The New Volatility Regime | SpotGamma Weekly](https://spotgamma.com/the-new-volatility-regime/) - As a result, we now see the market transitioning into a higher-volatility regime. This is not simply...

62. [Gamma Exposure](https://squeezemetrics.com/download/white_paper.pdf)

63. [Blog | Massive](https://massive.com/blog/) - In this tutorial, we will learn how to build a real-time stock market monitoring tool using Python a...

64. [Understanding Aggregate Bar Delays - Massive](https://massive.com/blog/aggregate-bar-delays/) - For second aggregates, we wait an additional 2 seconds for any high latency messages to come in. Onc...

65. [Top Data Sources for Building Trading Algorithms | For Traders](https://www.fortraders.com/blog/data-sources-building-trading-algorithms) - Polygon.io (Massive): Low-latency real-time data for high-frequency trading. Plans start at $29/mont...

66. [Pricing | Massive](https://massive.com/pricing) - Stocks Starter. Great for aggregates. $29/month. Sign up. All US Stocks Tickers; Unlimited API Calls...

67. [What is GEX? Guide - MenthorQ](https://menthorq.com/guide/what-is-gex/) - This article explains Gamma Exposure (GEX), how dealer hedging affects market stability or volatilit...

68. [Dealers' gamma exposure (GEX) tracker - GitHub](https://github.com/Matteo-Ferrara/gex-tracker) - Dealers' gamma exposure (GEX) tracker. Contribute to Matteo-Ferrara/gex-tracker development by creat...

69. [Cboe Files Proposal with the SEC to Launch Near 24x5 U.S. ...](https://www.prnewswire.com/apac/news-releases/cboe-files-proposal-with-the-sec-to-launch-near-24x5-us-equities-trading-302715070.html) - Cboe is preparing to launch in December 2026, pending regulatory approval of its filing, and conting...

70. [The State of the Options Industry: 2025 - Cboe Global Markets](https://www.cboe.com/insights/posts/the-state-of-the-options-industry-2025/) - Total options volume topped 15.2 billion contracts in 2025, 26% above 2024 — the previous record. An...

71. [GitHub - chiraagbalu/dealergammaexposure](https://github.com/chiraagbalu/dealergammaexposure) - Contribute to chiraagbalu/dealergammaexposure development by creating an account on GitHub.

72. [GitHub - alexjust-data/gex-options-realtime: Real-time extraction, transformation, and analysis of options market data for quantitative trading and research.](https://github.com/alexjust-data/gex-options-realtime) - Real-time extraction, transformation, and analysis of options market data for quantitative trading a...

73. [KaranChavan21/GEX_Dashboard - GitHub](https://github.com/KaranChavan21/GEX_Dashboard) - This system processes real-time option chains, calculates Greeks using Black-Scholes, and aggregates...

74. [aakash-code/GammaGEX - GitHub](https://github.com/aakash-code/GammaGEX) - GammaGEX is a sophisticated Python application that analyzes option chain data to identify stock mom...

75. [GitHub - Gurrel/GEX-Levels](https://github.com/Gurrel/GEX-Levels) - Contribute to Gurrel/GEX-Levels development by creating an account on GitHub.

76. [erma0x/gexxer: reveal the most important GEX option ... - GitHub](https://github.com/erma0x/gexxer) - Reveal the most important GEX levels on the Yahoo Option Chain data · Example of GEX levels · Exampl...

77. [FlashAlpha | Options Analytics API - Greeks, Exposure & Vol Surfaces](https://flashalpha.com) - Real-time options analytics API. Greeks, gamma exposure (GEX), SVI volatility surfaces, and market d...

