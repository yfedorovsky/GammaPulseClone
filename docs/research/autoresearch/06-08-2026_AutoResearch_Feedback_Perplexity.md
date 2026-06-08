# AutoResearch for GammaPulse: Closed-Loop Signal Discovery Architecture, Costs, and Validation

## Executive Summary

The proposed AutoResearch loop — scrape → hypothesize → auto-backtest → validate → ship → retire — is architecturally sound and represents a genuine frontier for solo quant operators in 2026. However, three honest constraints dominate the economics: (1) the validation gate must be the most expensive component, not the cheapest; (2) the 80% of value comes from mining *your existing alert_outcomes.db* rather than scraping the open web; and (3) "loop velocity" is a real edge but only if the loop cannot fool itself. All six questions are addressed below with current (2026) evidence.

***

## Question 1: Feasibility and Architecture

### Is the Closed-Loop Design Right for a Solo Operator?

The architecture is directionally correct, and it is now empirically validated by several 2026 research systems. NVIDIA's May 2026 NeMo Agent Toolkit demo implements exactly a three-agent loop (Signal Agent → Code Agent → Evaluation Agent) that proposes hypotheses, writes executable Python, backtests against market data, and feeds results back for next-iteration refinement, operating as a "continuous research loop" rather than a single-pass generator. Microsoft's open-source RD-Agent (Qlib), with 5,500+ GitHub stars as of 2025, automates the full quant R&D cycle: hypothesis generation, code synthesis via Co-STEER, real-market backtesting, and iterative feedback — achieving up to 2× higher annualized returns than classical factor libraries using 70% fewer factors in published benchmarks, with full experiment runs costing under $10. The KX/NVIDIA GTC 2026 collaboration launched production-ready "Trading Signal Agents" blueprints that validate and monitor signals against live time-series streams with governed, auditable outputs. The field has moved from academic prototypes to deployable toolkits within 18 months.[^1][^2][^3][^4][^5][^6]

### How Serious Quant Shops Structure This

Institutional quant factories differ from the proposed loop in one important way: they separate the **signal library** (a growing, version-controlled catalog of validated factors) from the **mining loop** (a disposable hypothesis generator). The mining loop is cheap and noisy; the library is expensive to get into and rigorously maintained. RD-Agent(Q) formalizes this as a "knowledge forest" where hypotheses pass through specification, synthesis, implementation, and validation stages before entering the live library. AlphaAgent (KDD 2025, accepted) enforces *three gates* before a factor can enter the library: originality check (AST-based structural similarity vs. existing alpha zoo), hypothesis-factor semantic alignment, and complexity control — factors failing any gate are rejected regardless of backtest performance. This is the key insight missing from many solo implementations: the factory discipline is not just "test more ideas faster," it is "reject more ideas rigorously."[^7][^8][^9][^5]

### Build vs. Buy: Component Map

| Component | Build | Buy/Use Existing | Notes |
|-----------|-------|-----------------|-------|
| Orchestration | ❌ | **Prefect** (free tier: 2 users, 5 workflows; Pro ~$100/mo) | Pure Python decorators, MLflow native integration[^10][^11] |
| Experiment tracking | ❌ | **MLflow** (100% open source, Apache 2.0, forever free)[^12] | Log every hypothesis, metrics, CI bounds |
| Backtesting engine | ✅ Already built | Your ThetaData replay + slippage engine | Advantage: you have real options tick data |
| Hypothesis store / queue | Lightweight | SQLite or Postgres; simple priority queue | No commercial product needed |
| Decay monitoring | ❌ | 10-line rolling IC / Wilson CI on alert_outcomes.db | Already have the data |
| LLM synthesis layer | ❌ | GPT-5.1 mini / Claude Haiku 4.5 for bulk; Sonnet for eval | See cost breakdown below |
| Paper scraping | ❌ | **arXiv API** (free, rate-limited but generous) | Semantic Scholar API also free |
| Signal similarity gate | Lightweight build | Port AlphaAgent's AST similarity checker (~200 lines Python) | Prevents re-discovering known signals |

### Failure Modes Specific to Trading AutoResearch (vs. ML Model Tuning)

The failure modes here are qualitatively different from standard ML evaluation because the evaluation set is not clean:

1. **The eval set contaminates itself over time.** Every signal you fire on live markets leaves footprints. If your universe is 471 tickers, running 200 auto-backtests against alert_outcomes.db means later tests partly reflect market impact of earlier signals. ML model evaluation does not have this property.
2. **Non-stationarity invalidates iid assumptions.** Walk-forward PBO requires distributional stationarity; options microstructure regimes (low-VIX, dealer-long/short, earnings clusters) violate this continuously.
3. **The LLM hallucination tax.** LLM-generated factors often contain lookahead bias, survivorship bias, or logically inconsistent operator chains. Without a mandatory code-quality agent and a unit-test for temporal leakage (as implemented in AlphaAgent's "Cognitive Alpha Mining" variant), the loop will reliably manufacture spurious results.[^2][^13]
4. **Selection illusion from social signal latency.** Options flow alpha is intraday or sub-hour. A hypothesis generated from a SSRN paper published in 2024 and tested on your 2022-2025 data may have already been crowded out. The paper was written *because* the signal was visible in that data.
5. **Research theater.** The loop will produce a steady stream of "validated" signals that cluster in adjacent parameter space. Without the AST-based novelty gate, you will rediscover the same signal 20 times in different notation.

***

## Question 2: Realistic Monthly Cost

### LLM Tokens

| Task | Model | Tokens/month (est.) | Monthly Cost |
|------|-------|---------------------|--------------|
| Paper scraping + summarization (50 papers × 5K tokens each) | GPT-5.1 mini ($0.15/M in, $0.60/M out) | ~750K in, 250K out | ~$0.26 |
| Hypothesis generation (200 hypotheses × 2K tokens) | Claude Haiku 4.5 ($0.25/M in, $1.25/M out) | ~400K total | ~$0.13 |
| Hypothesis-factor alignment scoring (gate pass) | Claude Sonnet 4.5 ($3/M in, $15/M out) | ~500K total | ~$9 |
| Backtest result synthesis + retirement decisions | GPT-5.1 mini | ~300K total | ~$0.07 |
| **Total LLM** | | | **~$10–$20/month** |

At the prices shown (Claude Sonnet 4.5: $3 input / $15 output per million tokens; GPT-5.1 mini: $0.15/$0.60; Claude Haiku 4.5: $0.25/$1.25), a continuous but modestly-scaled loop costs under $25/month for LLM tokens. Even at 10× usage scale, costs stay under $200/month. This is not the binding cost.[^14][^15]

### Data and Scraping

- **arXiv API**: Free; rate-limited to ~3 requests/second[^16]
- **SSRN**: Free public abstracts via RSS; full-text download requires manual or browser automation
- **NewsData.io Basic**: $199.99/month for 20,000 credits, real-time, 6 months historical; free tier gives 200 credits/day (12-hour delayed)[^17]
- **Benzinga Pro API**: ~$300/month for options news + event feeds[^18]
- **Reddit PRAW (official)**: $0.24/1,000 API calls; a daily scan of 10 subreddits at ~500 posts each costs roughly $1.20/day = **$36/month**[^19]
- **X (Twitter) API**: Basic $200/month (15,000 reads/month — barely enough for 500 tickers); Pro $5,000/month for 1M reads; Enterprise $42,000+/month. For a solo operator, the official X API is **economically inaccessible** for systematic options flow sentiment. Third-party wrappers (e.g., twitterapi.io) offer ~$0.15/1,000 tweets vs. $5.00/1,000 on the official Pro tier.[^20][^21]
- **StockTwits**: Free public API for ticker-specific streams; no volume pricing

### Compute (Backtests)

AWS Lambda charges $0.20/million requests and $0.0000166667 per GB-second. A single options backtest against ThetaData replay for 471 tickers over 2 years takes roughly 30–120 seconds depending on complexity. At 200 backtests/month × 60 seconds × 512MB = 6,144 GB-seconds = **~$0.10/month** in compute alone. Even at 10× scale: <$2/month. The real cost is ThetaData Pro (approximately $150–$500/month depending on your tier) — but you already have that. If running on a persistent t3.medium EC2 (~$30/month), total compute stays under $50/month.[^22][^23]

### Realistic Monthly Budget (Lean Stack)

| Component | Monthly Cost |
|-----------|-------------|
| LLM APIs | $15–$25 |
| NewsData.io Basic | $200 |
| Reddit API (PRAW at modest volume) | $10–$40 |
| X/Twitter (skip official; use StockTwits instead) | $0 |
| AWS compute (Lambda + small EC2) | $30–$50 |
| Prefect Cloud (free tier sufficient) | $0 |
| MLflow (self-hosted) | $0 |
| **Total** | **~$250–$315/month** |

**The cost-benefit threshold:** If the loop produces even one additional validated signal per quarter that fires 50+ times at your current ~14.9% win rate (SOE A), at a 3:1 R:R, the incremental PnL at minimum position sizes likely exceeds this cost within weeks. The 80/20 realization: **skip X entirely, use StockTwits + RSS feeds, and mine your own alert_outcomes.db first** — this brings the monthly cost below $100.

***

## Question 3: Effectiveness — Does Automated Idea-Gen Produce Tradeable Edge?

### What the Evidence Shows

The most rigorous published evidence comes from factor equity markets (CSI 300/500, S&P 500) rather than options flow, but the signal pipeline structure is directly analogous. AlphaAgent (KDD 2025) running a closed loop with GPT-3.5-turbo achieved IC of 0.0056 and 8.74% annualized excess return on S&P 500 from 2021–2024 with MDD below 10%. QuantaAlpha (arXiv Feb 2026) using an evolutionary trajectory framework achieved IC of 0.1501 with an annualized return of 27.75% and MDD of 7.98% on CSI 300 using GPT-5.2, with factors transferring to CSI 500 (160% cumulative excess return) and S&P 500 (137%) over four years. RD-Agent(Q) (Microsoft, May 2025) achieves IC of 0.0532 and 14.21% ARR on CSI 300 in joint factor-model optimization mode using GPT-4o mini.[^24][^9][^6][^7]

**Critical caveat:** All these results are for *systematic daily equity factor investing*, not intraday options flow detection. The options microstructure context (sub-hour expiration effects, pin risk, gamma exposure gradients) is far more non-stationary and regime-dependent than equity factor returns. The academic validation literature for *options flow* specifically is sparse. McLean and Pontiff (2016) established that roughly 50% of cross-sectional anomaly alpha disappears post-publication, and US equity signals lose approximately 5.6% of their alpha per year, European signals lose 9.9% annually.[^25][^26][^27]

### Social Media/News Signal Evidence

Cross-source sentiment combining X, StockTwits, and news — when *all three signal positively simultaneously* — has outperformed SPY by 29% cumulatively since August 2021 in published research from Context Analytics. Social media-based investor sentiment shows significant predictive power particularly during high-volatility periods. However: (1) this is daily-horizon signal, not sub-hour options flow; (2) the alpha is largely captured in *aggregated consensus* states, not individual tweet monitoring; and (3) since 2023, the social signal has been institutionalized — hedge funds and retail aggregators read the same feeds simultaneously.[^28][^29]

The honest characterization: **auto-generated hypothesis → validated edge hit rates are approximately 1–5% for novel, options-flow-specific signals.** Most of what the loop will discover will be variations on known factors. The value is in *systematically testing and retiring* them faster than the competition discovers and crowds them, not in discovering genuinely novel alpha from arXiv papers.

***

## Question 4: The Validation Gate — Preventing Self-Deception at Scale

This is the crux, and the literature is unusually specific. Running 200 auto-backtests guarantees false discoveries absent explicit multiple-testing corrections. The following hierarchy of protection should be implemented in order:

### Layer 1: Deflated Sharpe Ratio (DSR)

Bailey and López de Prado's Deflated Sharpe Ratio corrects for selection bias under multiple testing, non-normal returns (skewness, fat tails), and short sample lengths. It is the single most important gate to implement. The formula deflates the observed SR by the expected maximum SR under the null of pure luck given the number of trials conducted:[^30][^31][^32]

\[ \widehat{DSR} = \Phi\left( \frac{(SR - E[\max SR_N]) \cdot \sqrt{T-1}}{\sqrt{1 - \hat{\gamma}_3 \cdot SR + \frac{\hat{\gamma}_4 - 1}{4} \cdot SR^2}} \right) \]

where N is the number of strategies tried, T is the number of observations, and the skewness/kurtosis terms correct for non-normality. Open-source Python implementation: `pypbo` on GitHub, which also includes PBO, MinTRL, and probabilistic SR.[^33]

### Layer 2: Probability of Backtest Overfitting (PBO)

Bailey et al.'s combinatorial cross-validation approach divides the historical record into S subsets (typically 16), generates all possible training/test combinations, computes the performance rank of the "optimal" strategy in sample vs. out of sample, and estimates the probability that the optimal in-sample strategy underperforms the median OOS. A PBO above 50% means your backtesting procedure is generating noise, not edge. `pypbo` implements this directly.[^32][^33]

### Layer 3: Combinatorial Purged Cross-Validation (CPCV)

Standard walk-forward analysis has a well-documented failure mode: it produces high temporal variability and poor stationarity, particularly for options flow strategies with regime dependence. CPCV generates many chronology-respecting train-test partitions across the entire dataset, using every data point for both training and testing at different times. A 2024 empirical study found CPCV delivers significantly lower PBO and better deflated Sharpe statistics than walk-forward across synthetic market environments including Heston stochastic volatility and regime-switching models. For your alert_outcomes.db with ~200 minimum observations per signal cohort, CPCV is more data-efficient than walk-forward and is the correct choice. Implementation: `mlfinlab` library or `QuantBeckman`.[^34][^35][^36]

### Layer 4: Minimum Track Record Length (MinTRL)

Before any signal can exit shadow mode, compute the minimum number of out-of-sample observations needed to achieve statistical significance at your target confidence level. For options flow signals at ~14.9% base win rate, with a target of detecting a 5pp improvement at 90% confidence, MinTRL is roughly 250–400 clean observations depending on return distribution. This is your empirically grounded minimum-N rule.[^33]

### Fitness Function Design Principles

The auto-validation fitness function must be *adversarial to itself*. Concretely:
1. **Never optimize the fitness function itself.** If the loop can change what it is optimized against, it will find artifacts, not edge. The gate criteria are fixed at inception.
2. **Require economic rationale tagging.** Every hypothesis must include a mechanistic claim ("dealer gamma exposure creates directional drift because..."). Factors without mechanistic claims get rejected before backtesting. This is AlphaAgent's hypothesis-alignment gate.[^7]
3. **Track cumulative N-trials.** Every backtest increments a global counter. DSR is computed against that counter, not the per-signal count.
4. **Require OOS stability.** Performance in the most recent third of the test period must not be statistically worse than the first two-thirds. Decaying in-sample is a disqualifier.
5. **Apply regime-split validation.** Test separately in high-VIX vs. low-VIX, positive-GEX vs. negative-GEX, pre-earnings vs. post-earnings. A signal that only works in one regime is a regime bet, not a signal.

***

## Question 5: Highest-Leverage Additions for GammaPulse Specifically

### The Highest-Value Action: Mine alert_outcomes.db First

This is the 80% before building any scraping infrastructure. You have an asset no commercial system has: time-stamped fire-time context (regime, VIX, GEX, IVR, earnings proximity) with measured outcomes. The immediately valuable loop is:
1. **Rolling decay monitor**: Compute 60-day rolling win rate and Wilson CI for each signal cohort. If the lower CI bound falls below breakeven, the signal is flagged for retirement automatically.
2. **Context-conditional slicing**: Your alert_outcomes.db already has regime metadata. Automated queries like "what is the win rate of multi-strike cluster alerts that fire when VIX > 20 and GEX < 0 and earnings_proximity > 5 days?" are internal, cost-free hypothesis tests. The answer conditions exactly the "SELECTION + STRUCTURE" thesis validated in prior cross-LLM rounds.
3. **Opening vs. closing flow cohort feature**: You already built this split. The automated test is: "Does the next-morning settled-OI confirmation cohort have a statistically different forward return distribution at the 1-hour vs. EOD horizon?" — this is a Clopper-Pearson binomial test on your own data, zero external cost.

### What to Build, In Order

**Tier 1 (build now, ~2 weeks):**
- Rolling decay monitor with Wilson CI — outputs a "signal health" table daily
- Automated context-conditional win-rate slicer on alert_outcomes.db
- MLflow integration to log every shadow-mode alert as an "experiment run" with fire-time features as parameters

**Tier 2 (build next, ~4 weeks):**
- arXiv/SSRN scraper (free APIs) + Claude Haiku summarizer → hypothesis queue
- Basic LLM-synthesis step: given a paper abstract, output: (a) falsifiable claim, (b) mapping to your existing detector vocabulary, (c) auto-rejection if claim is already represented in your signal library
- Prefect orchestration to run the above weekly and append to hypothesis queue

**Tier 3 (build after Tier 1+2 validated, ~6 weeks):**
- Automated backtest trigger for top-N hypotheses above a plausibility score
- DSR + PBO gating at result collection
- Shadow-deploy auto-trigger for signals clearing all gates at n=50 observations, with auto-retire trigger at n=200 if performance < null

### What NOT to Build

- **Do NOT build real-time X (Twitter) scraping.** The API economics ($200/month for 15K reads at Basic; $5K/month for 1M reads at Pro) are prohibitive for a solo operator, and the alpha in public social sentiment is documented to be largely institutionalized. StockTwits public API + PRAW for Reddit r/options/r/wallstreetbets is 95% of the social signal value at 2% of the cost.[^21][^20]
- **Do NOT build a general-purpose idea-gen engine first.** The marginal hypothesis from arXiv has vastly lower alpha density than the marginal slice of your own alert_outcomes.db. The loop should mine internal data first, external literature second.
- **Do NOT implement multi-armed bandit hypothesis scheduling before Tier 1 is validated.** This is premature optimization. The RD-Agent(Q) paper found meaningful gains from bandit scheduling, but only on top of a validated base loop with clean evaluation metrics.[^9]
- **Do NOT confuse loop velocity with loop quality.** The risk of automating research is manufacturing false edge at industrial scale. Every additional automated backtest without DSR/PBO gating increases the probability that the "best" signal in the queue is a statistical artifact.

### Is "Loop Velocity" a Genuine Durable Edge?

With caveats, yes — but the mechanism is not what it sounds like. The edge is not in "discovering signals faster." All serious operators with comparable infrastructure discover similar patterns at similar speeds. The edge is in **retiring and replacing signals faster than competitors who have no automated decay detection**. US equity signals lose ~5.6% of alpha annually; options microstructure signals likely decay faster due to dealer adaptation. A solo operator with no decay monitoring runs a signal 6–12 months past its half-life; an automated decay monitor triggers retirement at the correct inflection point. That timing difference is the actual durable moat.[^26][^27]

***

## Question 6: External Sources — Ranked by Alpha Density vs. Noise

### Source Ranking for Options/Equity Flow

| Rank | Source | Alpha-Relevance | 2026 Access Reality | Cost |
|------|--------|-----------------|---------------------|------|
| 1 | **alert_outcomes.db (your own)** | Highest — proprietary, regime-tagged | Instant | $0 |
| 2 | **ThetaData OPRA tick history** | High — direct flow state | Already licensed | $150–500/mo |
| 3 | **arXiv q-fin / SSRN** | Medium — signal ideas from academia, but publication-lag decay[^25] | Free API | $0 |
| 4 | **SEC EDGAR (13F, form 4 insider)** | Medium-high for individual names | Free API (EDGAR) | $0 |
| 5 | **Fed/FOMC calendar + macro releases** | Medium — known to condition GEX regimes | Free (Federal Reserve, BLS) | $0 |
| 6 | **Benzinga Pro news API** | Medium — real-time catalyst triggers | ~$300/mo[^18] | $300/mo |
| 7 | **StockTwits public API** | Low-medium — retail sentiment, institutionalized | Free public endpoint | $0 |
| 8 | **Reddit (r/options, r/WSB via PRAW)** | Low-medium — useful for unusual flow confirmation; very noisy | $0.24/1K calls[^19] | $10–40/mo |
| 9 | **NewsData.io** | Low-medium — general news sentiment | $200/mo Basic[^17] | $200/mo |
| 10 | **X/Twitter official** | Low for options flow; high for meme/squeeze events | $200/mo (15K reads) to $5K/mo (1M reads)[^20][^21] | Prohibitive |

### X/Twitter 2026 Reality

X's enterprise API is priced at $42,000/month, the Pro tier at $5,000/month for 1 million reads, and Basic at $200/month for only 15,000 reads — insufficient for 471-ticker continuous monitoring. The academic research access program was dismantled in 2023. For a solo operator, the only compliant and economical path is third-party wrapper APIs (e.g., twitterapi.io at ~$0.15/1,000 tweets vs. $5.00 official), which carry ToS risk, or targeted monitoring of known high-signal accounts via personal API keys (free tier: 100 reads/month), which is too narrow for systematic coverage.[^37][^38][^20][^21]

### Reddit 2026 Reality

Reddit's official API charges $0.24/1,000 API calls for high-volume commercial use (since July 2023). Small-scale bots using PRAW targeting specific subreddits remain effectively free — "small private bots running for years without issues" are documented. The API is not built for high-volume use and Reddit's own documentation states this. For GammaPulse's use case (scan r/options daily for unusual flow confirmation), PRAW at <1,000 daily calls is free and compliant.[^39][^40][^19]

### News APIs 2026 Reality

NewsData.io Basic: $199.99/month for 20,000 credits, real-time, 6 months historical; free tier gives 200 credits/day with 12-hour delay. NewsAPI.ai covers 150,000 global sources with archive back to 2014. Benzinga is the highest-density financial news source for options-relevant catalysts (earnings date changes, clinical trial readouts, M&A rumors) at approximately $300/month for API access. Bloomberg terminal data (~$2,200/month) is cost-prohibitive for a solo operator.[^41][^18][^17]

***

## Three Highest-Confidence Build Recommendations

### Recommendation 1: Automated Decay Monitoring on alert_outcomes.db (Build in 1–2 weeks, cost: $0)

**Rationale:** This is the highest-certainty positive ROI action. You already have regime-tagged outcomes. The implementation is a weekly Prefect job that (a) computes 60-day and 90-day rolling Wilson CI win rates per signal cohort per regime bucket, (b) flags signals where the lower CI bound has dropped below breakeven (22.7% at 3.4× R:R per your measurement), and (c) auto-promotes to "shadow-retire" state pending human confirmation. This directly operationalizes the "retire decaying signals" half of the loop velocity thesis at zero incremental data cost and minimal development time. MLflow logs each weekly snapshot as an experiment, creating a compounding audit trail. The academic support is unambiguous: alpha monitoring is industry standard at serious quant shops, and the cost of running a decayed signal is 5–10% of edge per year.[^42][^27][^26]

**Risk:** Low. The worst case is that all signals are healthy and the monitor reports nothing interesting. Zero negative side effects.

### Recommendation 2: Internal Hypothesis Generator from alert_outcomes.db Slices (Build in 3–4 weeks, cost: ~$15/month LLM)

**Rationale:** Before scraping any external source, automate the generation of *testable hypotheses from your own data*. The implementation: a weekly script that (a) queries alert_outcomes.db for all 2×2×2 context combinations (high/low VIX × positive/negative GEX × opening/closing flow) that have n≥30 observations and have not been previously tested, (b) sends the win-rate differential to Claude Haiku with a prompt that produces a falsifiable hypothesis ("multi-strike cluster alerts in negative-GEX + high-VIX environments have a win rate above breakeven"), and (c) auto-backtests that hypothesis against ThetaData history using your existing engine. Every resulting test logs to MLflow. This is precisely the "SELECTION + STRUCTURE" thesis from your prior cross-LLM round, now automated. At roughly 100 unique context-combinations and 4 runs per combination per year, this is ~400 LLM calls at $0 each (Haiku pricing: $0.25/M input) = literally pennies.

**Risk:** Medium. The main risk is generating many statistically similar hypotheses (the "research theater" failure mode). Mitigation: implement a simple bloom-filter-based deduplication of hypothesis text embeddings before sending to backtest, rejecting semantically-similar hypotheses automatically.

### Recommendation 3: DSR + PBO Gating via pypbo on All Auto-Backtests (Build in 2 weeks, cost: $0)

**Rationale:** This is the validation infrastructure that prevents the loop from accelerating overfitting rather than alpha discovery. Install `pypbo` (MIT license, available on GitHub), and wrap every backtest result with DSR and PBO calculations before results are written to MLflow. The DSR gate should be set at 95% probability of genuine SR above the null; the PBO gate should reject any signal where the probability of backtest overfitting exceeds 50%. Critically: the DSR denominator (expected maximum SR given N trials) must increment globally across all auto-backtests ever run — not just per-signal trials. This single discipline change separates a research loop that compounds knowledge from one that manufactures artifacts.[^32][^34][^33]

**Risk:** Low-medium. The implementation risk is correctly computing the global N-trials counter across the history of all loop runs, which requires a persistent counter in MLflow or a dedicated log table. The failure mode (if not implemented correctly) is underestimating N, which inflates DSR scores. Mitigation: start the counter at 0 and be conservative; any uncertainty about historical N should round up, not down.

***

*Evidence quality note: The options-flow-specific evidence for LLM-driven auto-research is thin; the most relevant validated systems (AlphaAgent, QuantaAlpha, RD-Agent) are benchmarked on equity factor markets (CSI 300/500, S&P 500) at daily resolution. Extrapolation to intraday options microstructure involves meaningful uncertainty. The validation methodology recommendations (DSR, PBO, CPCV) are directly applicable regardless of asset class.*

---

## References

1. [NVIDIA shows how multi-agent systems can automate financial ...](https://vmts.com.hk/en/insights/nvidia-financial-signal-multi-agent-2026/) - NVIDIA's May 21, 2026 developer example uses NeMo Agent Toolkit, Nemotron models, and three speciali...

2. [NVIDIA's AI Agents Automate Signal Discovery in Quant Finance](https://www.mexc.com/news/1109357) - NVIDIA's NeMo Agent Toolkit enables AI-driven automation for financial signal discovery, reducing re...

3. [KX Launches Agentic AI Blueprints Powered by NVIDIA at GTC ...](https://kx.com/news-room/kx-launches-agentic-ai-blueprints-powered-by-nvidia-at-gtc-2026-featuring-a-capital-markets-research-assistant-and-trading-signal-agent/) - KX Launches Agentic AI Blueprints Powered by NVIDIA at GTC 2026, Featuring a Capital Markets Researc...

4. [Microsoft Qlib RD-Agent: Open-Source AI Automates Quant Finance ...](https://www.reddit.com/r/aicuriosity/comments/1o7eytl/microsoft_qlib_rdagent_opensource_ai_automates/) - Auto Research: RD-Agent uses smart language models to find useful factors, remove weak ones, and imp...

5. [R&D-Agent-Quant: A Multi-Agent Framework for Data-Centric ...](https://www.microsoft.com/en-us/research/publication/rd-agent-quant-a-multi-agent-framework-for-data-centric-factors-and-model-joint-optimization/) - In this paper, we propose R&D-Agent for Quantitative Finance, in short RD-Agent(Q), the first data-c...

6. [RD-Agent(Q): A framework for automated quant R&D - LinkedIn](https://www.linkedin.com/posts/armankhaledian_rd-agentq-data-centric-multi-agent-factormodel-activity-7336326541053767681-qJHN) - RD-Agent(Q), a multi-agent, data-centric framework that automates end-to-end quant R&D, mining facto...

7. [AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration ...](https://arxiv.org/abs/2502.16789) - We propose AlphaAgent, an autonomous framework that effectively integrates LLM agents with ad hoc re...

8. [AlphaAgent is an autonomous alpha mining framework. - GitHub](https://github.com/RndmVariableQ/AlphaAgent) - AlphaAgent is an autonomous framework that effectively integrates LLM agents for mining interpretabl...

9. [R&D-Agent-Quant: A Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization](https://arxiv.org/abs/2505.15155) - Financial markets pose fundamental challenges for asset return prediction due to their high dimensio...

10. [Prefect vs Airflow - Modern Workflow Orchestration](https://www.prefect.io/compare/airflow) - Your pipeline is your code. Prefect runs your Python as-is with simple decorators. Airflow requires ...

11. [Pricing - Prefect Cloud](https://www.prefect.io/pricing) - Simple, predictable pricing based on seats and workspaces—not usage. Start free with the Hobby tier ...

12. [MLflow - Open Source AI Platform for Agents, LLMs & Models](https://mlflow.org) - Open Source 100% open source under Apache 2.0 license. Forever free, no strings attached. any cloud,...

13. [Cognitive Alpha Mining via LLM-Driven Code-Based Evolution - arXiv](https://arxiv.org/html/2511.18850v3)

14. [LLM API Pricing Comparison 2026: Claude vs GPT vs Gemini Cost ...](https://claude5.ai/ja/news/llm-api-pricing-comparison-2025-complete-guide) - Comprehensive comparison of AI API pricing in 2026: detailed cost breakdown for Claude, GPT, Gemini,...

15. [Claude API Pricing 2026: Full Anthropic Cost Breakdown](https://www.metacto.com/blogs/anthropic-api-pricing-a-full-breakdown-of-costs-and-integration) - Claude API pricing for May 2026: Opus 4.7 ($5/$25), Sonnet 4.6 ($3/$15), Haiku 4.5 ($1/$5) per milli...

16. [wilsonfreitas/awesome-quant: A curated list of insanely ... - GitHub](https://github.com/wilsonfreitas/awesome-quant) - AutoHypothesis - Python - An agentic framework that mimics the real quant trading pipeline to find a...

17. [All About Pricing Plans: NewsData.io News API](https://newsdata.io/blog/pricing-plan-in-newsdata-io/) - Basic Plan charges you $199.99 per month and $1,919.99 per year, which allows 20,000 API credits per...

18. [News API Providers? : r/algotrading - Reddit](https://www.reddit.com/r/algotrading/comments/cet7xj/news_api_providers/) - Benzinga is saying around $300 a month for a few APIs.

19. [Addressing the community about changes to our API - Reddit](https://www.reddit.com/r/reddit/comments/145bram/addressing_the_community_about_changes_to_our_api/) - Effective July 1, 2023, the rate for apps that require higher usage limits is $0.24 per 1K API calls...

20. [Twitter API Pricing — Compare All Tiers & Hidden Costs](https://twitterapi.io/blog/twitter-api-pricing-2025)

21. [Use Cases, Tutorials, & Documentation | Twitter Developer ... - X](https://developer.x.com) - Publish & analyze posts, optimize ads, & create unique customer experiences with the X API, X Ads AP...

22. [AWS Lambda Pricing Calculator (2026): Requests + Duration](https://projecthelena.com/tools/lambda-pricing-calculator/) - Lambda costs $0.20/M requests + duration (GB-seconds). Calculate monthly cost with free-tier, x86 vs...

23. [AWS Lambda Pricing](https://aws.amazon.com/lambda/pricing/)

24. [An Evolutionary Framework for LLM-Driven Alpha Mining](https://liner.com/ko/review/quantaalpha-evolutionary-framework-for-llmdriven-alpha-mining) - 이 arXiv 2026 논문과 관련하여, 이 리뷰는 시장 노이즈와 비정상성을 다루는 LLM-driven 알파 마이닝을 위한 진화적 프레임워크를 요약합니다.

25. [Not All Factors Crowd Equally: Modeling, Measuring, and Trading ...](https://arxiv.org/html/2512.11913v1) - McLean and Pontiff (McLean and Pontiff, 2016) found that approximately 50% of anomaly alpha disappea...

26. [How to Measure Your Alpha's Decay and Half-Life - LinkedIn](https://www.linkedin.com/posts/kunal-kumar-a5105721b_quantfinance-systematictrading-algotrading-activity-7392443434088767489-8AmX) - 💡 Is Your Alpha Dying Faster Than You Think? Most quant signals don’t fail suddenly — they fade quie...

27. [Alpha Decay: what does it look like? And what does it mean for ...](https://www.mavensecurities.com/alpha-decay-what-does-it-look-like-and-what-does-it-mean-for-systematic-traders/) - Alpha decay presents a serious challenge for systematic traders as it leads to poorly-informed tradi...

28. [Cross-Source Sentiment: Building Alpha from News and Social Media](https://www.contextanalytics-ai.com/news-sentiment/cross-source-sentiment-building-alpha-from-news-and-social-media/) - In this follow-up, we extend our methodology to the monthly level, constructing longer-hold portfoli...

29. [The Predictive Power of Social Media Sentiment on Stock Market ...](https://www.ijfmr.com/research-paper.php?id=46689) - This study investigates the predictive power of social media sentiment on stock market returns. As s...

30. [The minimum backtest length and the deflated SR - GitHub Pages](https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/) - Lopez de Prado and Bailey (2014) also derive a deflated SR to compute the probability that the SR is...

31. [Correcting for Selection Bias, Backtest Overfitting and Non-Normality](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) - The Deflated Sharpe Ratio (DSR) corrects for two leading sources of performance inflation: Selection...

32. [[PDF] THE DEFLATED SHARPE RATIO: CORRECTING FOR SELECTION ...](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) - Bailey et al. [2013] introduce a new cross-validation technique to compute the Probability of. Backt...

33. [pypbo - Probability of Backtest Overfitting in Python - GitHub](https://github.com/esvhd/pypbo) - [4] Bailey, David H. and Lopez de Prado, Marcos, The Deflated Sharpe Ratio: Correcting for Selection...

34. [Backtest overfitting in the machine learning era: A comparison of out ...](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110) - Further advancing the field, Lopez de Prado's Combinatorial Purged Cross-Validation (CPCV) method of...

35. [[PDF] Backtest Overfitting in the Machine Learning Era](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4686376_code4361537.pdf?abstractid=4686376&mirid=1) - Further advancing the field, Lopez de Prado's Combinatorial Purged Cross-Validation (CPCV) method of...

36. [[WITH CODE] Combinatorial Purged Cross Validation for Optimization](https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross) - Combinatorial Purged Cross-Validation (CPCV) addresses this flaw by generating a multitude of chrono...

37. [RIP Twitter API: A eulogy to its vast research contributions](https://arxiv.org/abs/2404.07340) - Since 2006, Twitter's APIs have been rich sources of data for researchers studying social phenomena ...

38. [RIP Twitter API: A eulogy to its vast research contributions](http://arxiv.org/pdf/2404.07340.pdf) - ...spring of 2023, Twitter (now called X) began changing
$42,000/month for its Enterprise access lev...

39. [How to Get Reddit Posts, Comments, and Trends with an Unofficial API](https://scrapecreators.com/blog/reddit-api) - Need a Reddit free API alternative? Get fast JSON access to public posts, comments, subreddits, and ...

40. [What does reddit API cost? : r/redditdev](https://www.reddit.com/r/redditdev/comments/1dh5jq2/what_does_reddit_api_cost/) - I want to fetch posts from a particular subreddit using python. I know that I can use praw, reddit A...

41. [Best News API 2025: 8 Providers Compared & Ranked](https://newsapi.ai/blog/best-news-api-comparison-2025) - We compared 8 top news APIs for features, pricing, and performance. See who ranks #1 for real-time n...

42. [Alpha in Quantitative Finance: Definition and Decay - LinkedIn](https://www.linkedin.com/posts/michael-fernandes-7a3b6227a_alphaquant-activity-7408014379272527872-V1IR) - What Is Alpha in Quantitative Finance? (And Why It Always Decays) In quantitative finance, alpha is ...

