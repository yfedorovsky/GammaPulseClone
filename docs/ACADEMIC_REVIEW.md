# GEX-Based Options Trading: Academic Literature Review for the BREAKDOWN_ACCELERATOR Strategy

**Prepared for:** GammaPulse SOE v3.0 — BREAKDOWN_ACCELERATOR signal  
**Date:** April 2026  
**Scope:** Five specific research questions on GEX, dealer hedging, IV/RV timing, microstructure, and signal decay

***

## Executive Summary

The academic literature firmly establishes that negative-dealer-gamma regimes create mechanical feedback loops that amplify price moves. However, critical nuances distinguish what the papers actually prove from what retail GEX-based strategies typically assume. The key findings are:

1. **The hedging amplification effect is primarily intraday and reverts within 1–3 days** — it does not compound multi-day without new catalyst.
2. **No peer-reviewed backtest of a GEX-based put-buying strategy with published WR/Sharpe exists.** The academic literature studies GEX as a volatility or return predictor, not as an options trade.
3. **The IV/RV < 0.8 filter identifies windows where realized vol has *already* exceeded IV** — a backward-looking condition. The variance risk premium literature suggests this is the wrong signal direction for timing premium cheapness.
4. **Bid-ask spreads consume ~20% of option value on average**, and dealer positioning in put skew partially pre-prices downside risk — though the channel is distinct from the GEX feedback mechanism.
5. **GEX signal quality degrades measurably from SPX → SPY → QQQ → individual equities**, primarily driven by open interest concentration, dealer participation, and 0DTE volume effects. No paper quantifies this as a clean degradation curve.

***

## 1. Persistence of the Negative-Gamma Hedging Effect

### The Core Mechanism Is Robustly Established

The fundamental mechanic underlying BREAKDOWN_ACCELERATOR has peer-reviewed support from multiple independent research groups. Baltussen, Da, Lammers, and Martens document in a landmark *Journal of Financial Economics* (2021) paper that "hedging short gamma exposure requires trading in the direction of price movements, thereby creating price momentum," using intraday returns across 60+ futures on equities, bonds, commodities, and currencies from 1974 to 2020. Buis, Pieterse-Bloem, Verschoor, and Zwinkels in *Journal of Economic Dynamics and Control* (2024) confirm through simulation that "negative gamma positioning increases volatility and makes the market more prone to failure" and specifically that "in negative gamma scenarios, both informative and uninformative signals are amplified, leading to overshoots" — the precise language cited in STRATEGY.md. Anderegg, Ulmann, and Sornette in the *Journal of International Money and Finance* (2022) provide direct empirical quantification on foreign exchange: a negative OMM gamma of approximately −1,000 billion USD leads to an absolute increase in spot volatility of 0.7% for EUR/USD and 0.9% for USD/JPY over the sample period.[^1][^2][^3][^4][^5][^6][^7]

A 2025 preprint by Dai (arXiv) formalizes the feedback as a nonlinear recursive model with beta-normalized shock perception, deriving that the stability denominator \(D_i = 1 - \lambda G \phi(x_i)\) approaches zero at the gamma-squeeze threshold — and critically, that **low-beta stocks exhibit disproportionately strong feedback** for the same absolute price movement, because the normalized surprise \(x_i = |\Delta S/S| / (\beta_i \sigma_m)\) is larger for low-beta names[^8].

### The Critical Caveat: The Effect Is Intraday, Not Multi-Day Compounding

This is the single most important finding for your multi-day 14-DTE put strategy. Baltussen et al. (2021) explicitly state that the predictive power "reverts over the next days". A 2022 replication on the Chinese SSE 50 ETF confirms that "intraday momentum caused by hedging will decay in the next three days". The 0DTE paper by Wouts and Vilkov (SSRN 2023, presented at Oxford 2024) further finds that "intraday 0DTE trading volume shocks do not amplify recent past index returns," inconsistent with multi-day fragility.[^2][^9][^10][^11]

The implication: **the mechanical feedback loop that makes dealers sell into weakness operates intraday, concentrated in the final 30 minutes of each session. A 14-DTE put benefits from this only if the underlying move is large enough to shift the fundamental GEX landscape — not from daily compounding of intraday hedging flows.** What does compound across days is a persistent negative-GEX *regime*, sustained by ongoing put buying keeping dealers short gamma. The Dai 2025 model formalizes the self-limiting nature: position decay \(N_t = N_0 / (1 + \eta \cdot (\text{cumulative moves})^\xi)\) means hedging pressure naturally erodes as realized moves accumulate.[^8]

### VIX Regime Interaction

No published paper cleanly isolates whether the amplification effect is stronger in high-VIX vs. low-VIX environments as a controlled study. However, Goldman Sachs research notes that while higher volatility reduces gamma as a percentage of open interest (OTM options have less gamma than ATM), the **market impact per unit of gamma is higher when liquidity is thin during stress periods**. SpotGamma observes in practice that during periods with VIX ~30 and 1-month RV ~13%, "the stabilizing force of positive gamma is absent" and negative gamma creates a "trapdoor" structure. The mechanism is self-reinforcing: higher VIX periods attract more put buying → dealers accumulate more short gamma → feedback is amplified → VIX rises further. Your strategy's IV Level factor (preferring IV < 25%) may paradoxically filter *out* the strongest-feedback regimes, since high put buying (generating negative gamma) typically accompanies elevated IV.[^12][^13]

### The Absence of a Published "GEX Half-Life" Paper

No academic paper specifically studies the half-life of GEX-derived signals as a standalone metric. The closest proxies are: (1) Baltussen et al.'s 3-day decay finding; (2) Nyberg's 2025 Linköping University thesis showing GEX changes are "significantly and positively associated with S&P 500 returns across multiple time horizons" using an ARDL model on 2011–2025 daily data; and (3) the practical observation from GEX practitioners that open interest resets each day and position concentration can shift materially intraday. The half-life question therefore has no clean answer in the literature: it likely depends on the size of the initial catalyst, the magnitude of open interest at the relevant strike, and how quickly the negative-GEX king strike is approached.[^14][^15]

***

## 2. Published Backtests of GEX-Based Put-Buying Strategies

### The Gap in the Literature: No Published WR/Sharpe for Put-Buying GEX Strategies

This is the most uncomfortable finding for the strategy's empirical grounding. A thorough review finds **no peer-reviewed or credibly published backtest of a GEX-based directional put-buying strategy with documented win rates and Sharpe ratios**. The academic literature uses GEX as a predictor of realized volatility or equity returns, not as an options trading signal. What exists:

| Source | What It Studies | What It Does NOT Study |
|--------|-----------------|------------------------|
| Nyberg (2025 thesis)[^14] | GEX as predictor of S&P 500 returns, ARDL model, 2011–2025 | Options P&L, specific strike/DTE mechanics, WR/Sharpe |
| SqueezeMetrics whitepaper[^16] | GEX vs. SPX 1-day variance (scatterplot), GEX+ model | No put-buying backtest, no WR/Sharpe |
| PyQuantNews (2025)[^17] | GEX support/resistance for SPY equity trades → 1.03 Sharpe | Equity strategy, not options; not put-buying |
| Buis et al. JEDC (2024)[^1] | Simulation of gamma positioning on market quality | No trading strategy backtest |
| Baltussen et al. JFE (2021)[^4] | "Returns of simple trading strategies" on futures momentum | Futures/ETF, not options put-buying |

The PyQuantNews 1.03 Sharpe result is worth noting as partial evidence: a strategy that goes short SPY when price is above GEX resistance achieves this Sharpe ratio — but this is an equity short, not an options put purchase, and therefore does not account for theta decay, bid-ask friction, or gamma/vega dynamics.[^17]

### Why This Gap Exists

Options backtesting requires historical options chain data with timestamps, bid/ask spreads, and implied volatility surface evolution — data that is expensive, proprietary, or not yet part of standard academic datasets. GEX specifically requires dealer-side assumption about open interest direction (all call OI creates long dealer gamma; all put OI creates short dealer gamma), an assumption acknowledged as approximate by SqueezeMetrics and critiqued by OptionMetrics. The absence of published backtests is not evidence the strategy fails — it is evidence the academic infrastructure for this type of backtest is nascent.[^18][^16]

### What the Evidence Supports Indirectly

The literature supports the *direction* of BREAKDOWN_ACCELERATOR: negative gamma regimes amplify downside moves, and price discovery worsens (overshoots). It does not support specific thresholds (7.2/8 score, 0.30–0.40 delta puts, 14 DTE) having been empirically validated. Your in-house v2.0 data showing A+ grade 66.7% WR vs. A grade 13.0% WR on 35 trades is the most direct evidence for the strategy mechanics — but 35 trades is insufficient for statistical confidence, and the v3.0 out-of-sample validation is the appropriate test.[^1]

***

## 3. IV/RV Ratio as a Timing Filter for Long Puts

### The Variance Risk Premium Literature: IV Structurally Overprices RV

The foundational finding of the variance risk premium (VRP) literature is precisely the opposite of the IV/RV < 0.8 condition: **implied volatility persistently and significantly *overestimates* realized volatility**. Carr and Wu (*Review of Financial Studies*, 2009) document using five major stock indexes and 35 individual stocks that "the slope estimates from our regressions are significantly lower than one for the S&P indexes, suggesting that the market variance risk premiums are time-varying and correlated with the variance swap rate". Fallon, Park, and Yu (*Financial Analysts Journal*, 2015) find that systematically shorting volatility (exploiting IV > RV) produces a Sharpe ratio of 0.6 for equities across 34 global asset markets over 20 years. Todorov (*Journal of Finance*, 2009) identifies that VRP variation is primarily driven by jump intensity extracted from deep out-of-the-money put options — the same puts your strategy buys.[^19][^20][^21]

The baseline state is IV/RV > 1, not < 1. This means:

- **When IV/RV < 0.8:** A rare condition where realized movement has already exceeded what IV priced in. This is a *backward-looking* signal — it identifies that past realized vol has been high relative to implied vol.
- **The filter's intended meaning:** You are buying puts when the options market *has not yet repriced* realized volatility higher. This is a plausible thesis — markets can be slow to reprice IV.
- **The empirical risk:** Research on vol timing (Yang 2024) shows VRP timing strategies require forward-looking VRP estimates, not backward-looking comparisons. The window where IV/RV < 0.8 may already be over by the time you enter at T+1.[^22]

### What the Research Does Support

The EFMA 2024 paper on "Stock Return Predictability of Realized-Implied Volatility Spread" directly examines the RV > IV condition and finds it predicts *positive stock returns* — not necessarily positive put returns, but consistent directional evidence. The study notes that "excluding stocks with abnormal turnover significantly improves returns to RVol-IVol strategies," suggesting the signal degrades in high-noise environments. Ni, Pan, and Poteshman (*Journal of Finance*, 2008) show that non-market-maker net demand for volatility is informative about *future* realized volatility — which provides a different but complementary filter angle: net put buying demand predicts higher realized vol.[^23][^24][^25][^26]

### Practical Concern for the Strategy

Your IV/RV filter uses a ratio of 0.8, meaning you require RV > 1.25x IV before entering. The VRP literature suggests this condition occurs most often in the early stages of a volatility regime shift — precisely when negative-GEX environments are forming (put buying increases → IV should be rising → but if it lags realized vol, IV/RV temporarily compresses). This creates a coherent narrative: the signal fires when realized vol is already elevated but market pricing (IV) hasn't caught up. However, the risk is that IV will rapidly reprice at T+1 entry, inflating premiums. Your static IV assumption in BSM repricing (noted in STRATEGY.md) is therefore a meaningful conservatism — IV expansion on entry would hurt real-world fills even if BSM shows a win.

***

## 4. Options Market Microstructure: Adverse Selection and Pre-Pricing

### Bid-Ask Costs Are Substantially Larger Than Typically Modeled

Quantpedia's analysis of the Bryzgalova, Huang, and Julliard paper documents that average bid-ask spreads in options amount to approximately 20% of the option price, with spreads increasing materially ahead of high-expected-volatility events where retail trading concentrates. This is not a fringe finding: it's consistent with Eraker and Osterrieder's (2022) work showing that asking prices are more sensitive to shocks than bids, creating systematically skewed spreads. Your 3% spread assumption (mid ± 1.5%) is materially lower than empirically observed spreads for OTM puts in stressed conditions, which is where BREAKDOWN_ACCELERATOR fires. For 0.30–0.40 delta puts on individual equities, spreads of 5–15% of mid are common.[^27][^28]

### Is the Negative-Gamma Acceleration Already Priced into Put Skew?

This is the most structurally important microstructure question. The short answer is: **the skew risk premium and the GEX feedback channel are partially overlapping but not identical, and the GEX effect may be more actionable than it appears.** OptionMetrics (2022) makes the critical distinction: GEX measures net gamma (a structural market-maker positioning metric), while put skew measures the *risk premium for downside tail protection* purchased by hedgers. Negative GEX and elevated put skew can co-exist for different reasons: a dealer can be net short puts (negative GEX from the mechanical hedging perspective) while put skew is elevated because of demand from portfolio hedgers. The skew prices the insurance premium; GEX measures the mechanical hedging pressure. These are distinct.[^18]

However, the adverse selection risk is real for EOD data users. Baltussen et al. establish that the gamma hedging flow is concentrated in the **last 30 minutes of the trading session**. If that flow moves the underlying materially, the T+1 open entry captures a price that has already been mechanically displaced. In liquid markets, the GEX levels you observe at EOD on day T may be stale by the time day T+1 opens, as 0DTE option positions have expired and overnight flows reset positioning. Your per-day GEX change tracking (day-over-day) addresses this to some degree but does not solve the fundamental overnight reset problem for the negative-GEX king level.[^4][^2]

### Retail Versus Institutional Information Asymmetry

Ni, Pan, and Poteshman (JF 2008) show that the "price impact of volatility demand increases by 40% as informational asymmetry about stock volatility intensifies in the days leading up to earnings announcements". This implies that when your strategy fires on individual equities near earnings (where GEX positions are large), you face a significantly less favorable fill environment. The market makers you're trading with have better information about whether the GEX signal is information-driven or noise-driven.[^25]

***

## 5. GEX Signal Decay from SPX/SPY to Individual Equities

### The Structural Reasons for Degradation

No published academic paper explicitly constructs a "GEX decay curve" from SPX to QQQ to individual equities. However, the literature converges on several structural explanations for why the signal degrades:

**1. Open Interest and Notional Gamma Concentration**  
The SPX options market has $80 billion in gross gamma — meaning a 1% move in SPX changes total option deltas by $80 billion. This is orders of magnitude larger than any individual equity. The mechanical impact of hedging is proportional to this notional: smaller OI at individual name strikes means smaller absolute hedging flows per dollar of price movement.[^13]

**2. Dealer Participation Fraction**  
In SPX/SPY, over 65% of daily options volume is now in 0DTE contracts, and dealer market-making represents a large fraction of that volume. For individual equities, end-user flow (retail, institutional) represents a higher fraction of volume — meaning the GEX sign assumption (all put OI → dealer short puts → short gamma) is less reliable. OptionMetrics explicitly notes this: their DOOD measure (Demand for Option Order Delta) shows that the composition of OI matters, not just its sign.[^29][^18]

**3. 0DTE Volume Effects**  
SPX and SPY have same-day expirations every trading day; QQQ has daily expirations; most individual equities have only weekly or monthly expirations. The concentration of gamma in 0DTE options creates the strongest mechanical hedging effect — an effect that is much smaller for names with no 0DTE market.[^30][^29]

**4. Liquidity Amplification Channel**  
The BSIC review of the academic literature explicitly states that the delta-hedging feedback effect "is stronger for the least liquid underlying securities" — but this is nuanced. Lower liquidity means each hedging trade has greater price impact (amplifying the move), but lower liquidity also means smaller absolute option open interest (reducing the total hedging demand). For individual names, the latter effect typically dominates: the GEX king strike's absolute gamma is small enough that hedging flows don't meaningfully move the stock.[^31]

**5. Buis et al. (JEDC 2024) Policy Implication**  
The paper notes that "steering the net gamma position of dynamic hedgers can be considered a policy instrument to improve market quality, *especially for instruments with low liquidity or low traded volume*" — implying the gamma effect is most material for low-liquidity instruments, precisely the opposite of where GEX data quality is best.[^5]

### The QQQ Underperformance Is Structurally Explained

QQQ's daily expiration options exist but at significantly lower volume than SPY/SPX. This means that QQQ's GEX profile is a mix of the high-gamma-density 0DTE environment (present but less liquid) and the individual-equity problem (less OI per strike). The Dai (2025) beta-dependent model provides a potential partial offset: QQQ has higher beta than SPY (tech concentration), and higher-beta stocks show *weaker* gamma feedback for the same absolute move. The combination of QQQ's lower 0DTE concentration and higher beta could theoretically double the signal degradation observed empirically.[^8]

### The Critical Sign Assumption for Individual Equities

For individual equities, the standard GEX calculation assumes dealers are long all call OI and short all put OI. This assumption holds reasonably well for index products where dealer market-making dominates. For individual equities with significant institutional covered-call selling (puts OI created by delta-hedgers, not end-user put buyers), the sign convention breaks down. Poteshman et al. (RFS 2021) document a "noninformational channel through which option market maker hedge rebalancing affects stock return volatility" for individual names — but the direction of impact is more complex than the binary GEX sign.[^32][^33]

***

## 6. Synthesis: What the Literature Supports and What It Doesn't

### What Is Well-Supported

| Claim | Support |
|-------|---------|
| Negative-gamma dealers amplify intraday downside moves | Strong: multiple peer-reviewed papers across markets[^2][^1][^6] |
| Negative-gamma regimes increase realized volatility | Strong: Anderegg et al. empirical; Buis et al. simulation[^6][^5] |
| In negative gamma, uninformative signals are amplified (overshoots) | Strong: Buis et al. JEDC 2024[^1] |
| GEX changes predict S&P 500 returns at daily horizon | Moderate: Nyberg 2025 thesis with ARDL model[^14] |
| Dealer hedging creates intraday momentum concentrated at day end | Strong: Baltussen et al. JFE 2021[^4] |
| Low-beta stocks have disproportionately strong gamma feedback | Theoretical: Dai 2025 arXiv preprint[^8] |

### What Is Not Well-Supported

| Claim | Status |
|-------|--------|
| Negative gamma amplification compounds across multiple days | Not supported: effect reverts in 1–3 days[^2][^9] |
| GEX-based put buying has published WR/Sharpe | Not found: literature gap, no peer-reviewed backtest |
| IV/RV < 0.8 is a validated long-put entry timing signal | Mixed: backward-looking; VRP literature suggests IV usually overstates RV[^20][^21] |
| Put skew fully pre-prices GEX-driven downside acceleration | Not confirmed: skew and GEX are distinct channels[^18] |
| GEX signal degrades in a documented, quantified curve for equities | Not published: structural explanations exist but no empirical decay curve[^31][^5] |

***

## 7. Practical Implications for BREAKDOWN_ACCELERATOR v3.0

### Signal Timing

The 14-DTE put strategy needs the negative-GEX amplification to persist beyond the intraday window. The academic evidence suggests this requires the negative-GEX *regime* to persist (the dealer book stays short gamma across multiple sessions), not just a single-day intraday effect. Tracking day-over-day GEX change (as noted in STRATEGY.md) is the right approach: what matters is whether the regime is deepening or recovering.

### IV/RV Filter Reconsideration

The IV/RV < 0.8 filter has a logical thesis but a timing risk: it identifies windows where the market has *already* been moving faster than priced. Consider supplementing it with a forward-looking component — for example, whether IV has started to tick up (indicating the market is beginning to price the regime change), which would support entering before the full IV catch-up.

### Bid-Ask Spread Calibration

The 3% spread assumption (mid ± 1.5%) is likely too optimistic for the conditions where BREAKDOWN_ACCELERATOR fires. In negative-GEX regimes with elevated realized vol, put spreads expand. A conservative validation should test with 5–8% spread friction for individual equities and 3–5% for SPY.

### GEX Sign Reliability

For SPY, the standard GEX sign convention (put OI → dealer short gamma) is empirically supported. For individual equities in the ticker universe (NVDA, TSLA, MU, etc.), the sign assumption deserves scrutiny. The presence of significant institutional covered-call writing on these names complicates the dealer gamma direction inference.

### The QQQ Auto-Block

The EV gate that would auto-block QQQ after negative expectancy is correctly calibrated. The structural reasons for SPY's edge not transferring to QQQ are well-grounded in the literature: lower 0DTE concentration, higher beta, and less dominant dealer participation in OI. The same auto-block mechanism would likely trigger on individual equities with small options OI (e.g., photonics names in the universe), which is a feature, not a bug.[^29][^8]

***

## Key Papers Reference Summary

| Paper | Journal | Year | Key Finding Relevant to Strategy |
|-------|---------|------|----------------------------------|
| Baltussen, Da, Lammers, Martens | *JFE* | 2021 | Gamma hedging → intraday momentum; reverts within days[^2] |
| Buis, Pieterse-Bloem, Verschoor, Zwinkels | *JEDC* | 2024 | Negative gamma → overshoots; "prone to market failure"[^1] |
| Anderegg, Ulmann, Sornette | *JIMF* | 2022 | Empirical: negative OMM gamma increases spot volatility[^6] |
| Carr & Wu | *RFS* | 2009 | VRP: IV persistently > RV; slope < 1 for indexes[^20] |
| Ni, Pan, Poteshman | *JF* | 2008 | Non-MM vol demand predicts future realized vol[^25] |
| Poteshman et al. | *RFS* | 2021 | Hedge rebalancing affects stock return volatility (non-info channel)[^32] |
| Nyberg | Linköping thesis | 2025 | GEX changes predict S&P 500 returns; ARDL 2011–2025[^14] |
| Dai | *arXiv preprint* | 2025 | Beta-dependent gamma feedback; low-beta stocks amplify most[^8] |
| Wouts & Vilkov | *SSRN/Oxford* | 2023/2024 | 0DTE gamma does not amplify past returns multi-day[^10] |
| Goldman Sachs | Market note | 2020 | SPX $80B gross gamma; impact higher in low-liquidity conditions[^13] |

---

## References

1. [Gamma positioning and market quality](https://www.sciencedirect.com/science/article/pii/S0165188924000721)

2. [Baltussen, G., Da, Z., Lammers, S. and Martens, M. (2021). Hedging ...](https://tinbergen.nl/publication/168044/hedging-demand-and-market-intraday-momentum) - We provide novel evidence that links market intraday momentum to the gamma hedging demand from marke...

3. [[PDF] Hedging demand and market intraday momentum - Academic Web](https://academicweb.nd.edu/~zda/intramom.pdf) - We provide novel evidence that links market intraday momentum to the gamma hedging demand from marke...

4. [Hedging demand and market intraday momentum - ScienceDirect.com](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21001598) - In this paper, we extensively study market intraday momentum, or time-series momentum at the market ...

5. [Gamma positioning and market quality](https://pure.eur.nl/en/publications/gamma-positioning-and-market-quality/) - In this paper, we study the effect of the gamma positioning of dynamic hedgers on market quality thr...

6. [The impact of option hedging on the spot market volatility](https://ideas.repec.org/a/eee/jimfin/v124y2022ics0261560622000304.html) - We theoretically model and empirically quantify the feedback effect of delta hedging for the spot ma...

7. [The impact of option hedging on the spot market volatility - EconPapers](https://econpapers.repec.org/article/eeejimfin/v_3a124_3ay_3a2022_3ai_3ac_3as0261560622000304.htm) - Abstract: We theoretically model and empirically quantify the feedback effect of delta hedging for t...

8. [Beta-Dependent Gamma Feedback and Endogenous Volatility ...](https://arxiv.org/html/2511.22766) - We develop a theoretical framework that aims to link micro-level option hedging and stock-specific f...

9. [[PDF] Delta-hedging demand and intraday momentum](https://papers.ssrn.com/sol3/Delivery.cfm/01e9a66f-bc96-444f-b673-3e9398ec8f03-MECA.pdf?abstractid=4025948&mirid=1&type=2) - According to Baltussen, Da, Lammers, and Martens (2021), intraday momentum is generated by the marke...

10. [0DTEs: Trading, Gamma Risk and Volatility Propagation](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190) - We study the recent explosion in trading of same-day expiry (0DTE) options on the S&P500 index and e...

11. [0DTEs: Trading, Gamma Risk and Volatility Propagation](https://www.maths.ox.ac.uk/node/67396) - Investors fear that surging volumes in short-term, especially same-day expiry (0DTE), options can de...

12. [The New Volatility Regime | SpotGamma Weekly](https://spotgamma.com/the-new-volatility-regime/) - Between negative gamma below SPX 6900 and heavy put skew, the options market has formed a trapdoor t...

13. [Goldman: All You Ever Wanted To Know About Gamma, Op-Ex, And ...](https://spotgamma.com/all-you-ever-wanted-to-know-about-gamma/) - Goldman Sachs explains everything you ever wanted to know about Gamma, Op-Ex, and option-driven equi...

14. [Leveraging Gamma Exposure to Predict Equity Market Returns and ...](https://liu.diva-portal.org/smash/record.jsf?pid=diva2%3A1972044) - This thesis investigates whether aggregate gamma exposure (GEX) in the S&P 500 index options market ...

15. [[PDF] Convexity in Motion - Diva-portal.org](https://liu.diva-portal.org/smash/get/diva2:1972044/FULLTEXT01.pdf) - This thesis investigates whether aggregate gamma exposure (GEX) in the S&P 500 index options market ...

16. [The Implied Order Book](https://squeezemetrics.com/download/The_Implied_Order_Book.pdf)

17. [Boost a strategy to 1.03 Sharpe ratio with new Gamma levels](https://www.pyquantnews.com/the-pyquant-newsletter/boost-strategy-1-03-sharpe-ratio-with-new-gamma-levels) - Similarly, high gamma in put options often triggers buying, establishing support zones. Traders use ...

18. [Gamma Gravity: Negative Gamma is Not a Volatility Black Hole](https://optionmetrics.com/blog/2022_gamma_gravity/) - Negative gamma generalizes an environment where dealers are net short options. However, the GEX meas...

19. [[PDF] Variance Risk Premium Dynamics: The Role of Jumps∗](https://www.kellogg.northwestern.edu/faculty/todorov/htm/papers/vrpd.pdf) - In the empirical part in Section 1.2 I find that for the data used in this paper there is no signifi...

20. [Variance Risk Premiums | The Review of Financial Studies](https://academic.oup.com/rfs/article/22/3/1311/1581057?login=true) - Abstract. We propose a direct and robust method for quantifying the variance risk premium on financi...

21. [The Variance Risk Premium is Pervasive - - Alpha Architect](https://alphaarchitect.com/the-variance-risk-premium-is-pervasive/) - A large body of evidence demonstrates that the VRP is persistent and pervasive as well as robust to ...

22. [[PDF] Volatility-Managed Volatility Trading](https://english.phbs.pku.edu.cn/uploadfile/2024/0530/20240530092144610.pdf) - We develop volatility risk premium (VRP) timing strategies that involve trading two assets: a volati...

23. [Stock Return Predictability of Realized-Implied Volatility ...](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/ATR_RVolIVOl_Complete.pdf)

24. [[PDF] Stock Return Predictability of Realized-Implied Volatility Spread and ...](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/ATR_RVolIVOl_Complete.pdf)

25. [Volatility Information Trading in the Option Market - NI - 2008](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01352.x) - This paper investigates informed trading on stock volatility in the option market. We construct non-...

26. [[PDF] Volatility Information Trading in the Option Market](https://en.saif.sjtu.edu.cn/junpan/npp.pdf) - This paper investigates informed trading on stock volatility in the option market. We construct non-...

27. [[PDF] Market Maker Inventory, Bid-Ask Spreads, and the Computation of ...](http://eraker.marginalq.com/OIRM.pdf)

28. [How Retail Loses Money in Option Trading - QuantPedia](https://quantpedia.com/how-retail-losses-money-in-option-trading/) - Retail losses from bidding up prices are compounded by enormous bid-ask spreads in options ahead of ...

29. [All About 0DTE Options Guide - MenthorQ](https://menthorq.com/guide/all-about-0dte-options/) - Net Gamma Exposure (GEX): Indicates whether the market is positioned for mean-reversion (positive ga...

30. [0DTE Options and GEX Levels - How Gamma Exposure Affects ...](https://optionsflow.com/learn/0dte/0dte-gex-levels/) - Learn how GEX levels impact 0DTE options trading. Understand gamma amplification on expiration day, ...

31. [How Dealers' Gamma impacts underlying stocks](https://bsic.it/how-dealers-gamma-impacts-underlying-stocks/)

32. [Does Option Trading Have a Pervasive Impact on Underlying Stock ...](https://experts.illinois.edu/en/publications/does-option-trading-have-a-pervasive-impact-on-underlying-stock-p/) - Recent research presents evidence of an informational channel through which option trading affects s...

33. [Does Option Trading Have a Pervasive Impact on Underlying Stock ...](https://academic.oup.com/rfs/article-abstract/34/4/1952/5873587) - This paper provides evidence of a noninformational channel through which option market maker hedge r...

