# Full Strategy Audit and Win-Rate Optimization

## Executive diagnosis

I could not directly inspect the referenced repo files through the available tools, so this audit is based on the detailed operational summary you provided plus external market-microstructure and options literature. Even with that limitation, the main diagnosis is clear: the highest-value missing layer is **not** another micro-tweak to the current confluence score. It is a **day-state and trade-feasibility layer** that sits above the current 0DTE candidate generator and below any decision to treat an alert as actionable.

That conclusion is consistent with both your evidence and the broader literature. Same-day options are now large enough to matter to index microstructure: entity["organization","Cboe Global Markets","options exchange operator"] reported that SPX 0DTE options averaged 2.3 million contracts a day in 2025 and represented 59% of total SPX volume. But the literature does **not** point to one universal effect. One recent paper finds that 0DTE market-maker intermediation lowers index volatility on average, another finds that more 0DTE trading raises volatility, and a third finds that intraday jump risk in 0DTE pricing is frequent, concentrated around the open and close, and commands a large premium. The practical takeaway is not “0DTE is good” or “0DTE is bad.” It is that the effect is likely **state-dependent**, which matches your observed bimodality much better than the idea that the engine simply needs one more confluence point. citeturn6search0turn6search3turn1search0turn1search1turn0search1

Based on your summary, the hardest conclusions are these:

| Topic | Verdict | Why it matters |
|---|---|---|
| GEX level geometry | Retire it as a primary causal thesis | Your randomized distance-matched audit already did the important work |
| 0DTE engine grading | Collapsed, not discriminative | If historical alerts are effectively all the same grade and metadata, the grade is not ranking signal quality |
| ST hard confirmation | Excellent temporary safety brake, poor permanent architecture | It saved May 1, but a zero-fire week means it can functionally turn the strategy off |
| Missing variable | Day-state plus strike-feasibility | That is where the largest unexplained variance now appears to live |

My strongest pushback is this: **your stack is currently over-specified at the trigger layer and under-instrumented at the feasibility layer**. You are measuring confluence elegantly while measuring “could this strike plausibly get paid before theta and spread kill it?” too weakly.

## What the current evidence actually means

Your own audit has already falsified the strongest version of the GEX thesis: the levels, as spatial boundaries, are not behaving better than random ATM-rounded levels at the same distance from spot. Respect that result. Do not smuggle the dead thesis back in through side doors like “multi-day level memory,” “was the level tested yesterday,” or more elaborate geometry around king/floor/ceiling. If an edge remains, it is not “this level is intrinsically special.” It would have to live in **state variables** such as hedging pressure, order-flow persistence, jump regime, or execution context. That distinction matters because the literature does show strike clustering and hedging-related intraday effects around expiration, but those are not the same claim as “our computed structural levels are privileged price boundaries.” citeturn7search0turn1search4turn1search0turn1search1

The second hard read is that the current 0DTE engine is probably **not** a complete signal. It is a **candidate generator**. When winners and losers arrive with essentially identical alert metadata, the engine is not measuring the variable that matters most. That does **not** prove the candidate stream is useless. It does mean your present scoring framework is not doing the discrimination job you want it to do. Put differently: the system may be surfacing the right neighborhood of moments, but it is not separating tradeable from untradeable context inside that neighborhood.

The third hard read is that your current samples are not as large as the raw alert count suggests. Because alerts cluster heavily by day, and sometimes by repeated same-direction same-state episodes within the day, the effective sample size is much closer to **day clusters** or **signal episodes** than to raw alerts. This matters for both inference and future classifier work. If May 1 produces fifteen bullish alerts that are all the same state expressed repeatedly, that is closer to one bad regime with fifteen echoes than to fifteen independent observations.

## Bimodality and day-state discriminators

I did **not** find a clean peer-reviewed paper that literally partitions U.S. index sessions into “return-to-open” versus “directional” days for 0DTE trading. I **did** find three adjacent literatures that support the broad idea. First, large opening moves in stock-index futures often reverse later in the day. Second, market intraday momentum work shows early-session returns can predict late-session returns, especially on volatile, high-volume, and macro-news days. Third, options research shows intraday and overnight option-return components behave very differently. So your “return-to-open versus drift” hypothesis is intellectually defensible, but the exact thresholds you quoted are **not** literature-backed yet and should be treated as a forward hypothesis, not a fact. citeturn12search0turn12search1turn1search2turn1search4turn0search2

The right way to proceed with your 127 days of regular-hours tick data is to build **causal, scale-free, low-dimensional features** that can be measured at alert time without lookahead. The most promising ones are below.

| Feature | Causal definition at alert time | Why it is robust |
|---|---|---|
| Open reversion ratio | `abs(P_t - P_open) / (H_t - L_t)` using session-so-far range | Detects rotational sessions without needing full-day close |
| Path efficiency | `abs(P_t - P_open) / sum(abs(ΔP_i))` from open to `t` | Separates grind/trend from chop with one interpretable ratio |
| Open-cross count | Number of distinct crosses of the opening price by `t` | Rotational sessions re-cross open; directional sessions do not |
| Directional-change count | Count of alternating moves above a vol-scaled threshold | Event-based summary is more robust than raw bar-count heuristics |
| Jump share | `max(RV_t - BV_t, 0) / RV_t` where BV is bipower variation | Separates jump/event days from smooth continuous trend/rotation |
| Gap follow-through | `sign(gap_open) * return_open_to_t` | Distinguishes opening continuation from opening overreaction/reversal |
| Macro window tag | Binary flags for scheduled releases near `t` | Captures exogenous volatility regime shifts without news NLP |
| Cross-ticker alignment | Sign and z-scored magnitude agreement between SPY and QQQ path-so-far | Divergence often marks messy or incomplete tape confirmation |

The reason these features are attractive is that they can be estimated **without using the five winners to choose thresholds**. Jump-share features come from a long realized-volatility literature that explicitly decomposes continuous and jump variation. Directional-change features come from event-based regime literature that is more stable than ad hoc bar-pattern counting. Macro-window tagging is justified by a large literature showing scheduled announcements change intraday volatility structure, and the opening-gap/reversal idea has direct support in index-futures studies. citeturn3search0turn4search1turn4search2turn5search1turn5search3turn12search0turn12search1

What I would do with the 127-day dataset is **not** fit a winner/loser classifier. I would use it to estimate the **distribution of day states** and freeze a taxonomy before forward evaluation. Concretely: compute the features above every five minutes from, say, 10:00 to 14:00; normalize them by ticker and time-of-day quantiles; then build a small unsupervised taxonomy with three or four states such as rotational/balanced, directional/trend, jump/event, and noisy/dislocated. Only after that would I overlay your six historical alert days to see where the winners and losers landed. That avoids tuning the taxonomy to five winners. If you want a model class for this unsupervised step, a small HMM or a simple k-medoids/GMM on causal path features is reasonable; using alert outcomes at this stage is not. citeturn10search0turn10search5turn4search2

My answer to the “mis-tuned alert generator versus external regime” question is: **both, but in different senses**. As a **ranking mechanism**, the alert generator is mis-tuned because it is not producing useful entropy. As a **candidate enumerator**, it may still be detecting something real that only monetizes under specific day states. Operationally, that means you should stop asking it to do both jobs.

## Alert logic and gate architecture

The next features I would prioritize are not the fanciest ones. They are the ones that directly attack your current failure modes.

| Priority | Add or shadow metric | Why it matters | Ship before Monday? |
|---|---|---|---|
| Highest | Strike reachability ratio | Filters “good idea, impossible strike” failures | Annotation now; logic change only if bug proven |
| Highest | Minutes-to-expiry / entry-time bin | 0DTE convexity and theta are pathologically time-sensitive | Annotation now |
| High | ST rolling near-fire state | Preserves information from 6/8 or 7/8 asynchronous states | Annotation now |
| High | Flow persistence window | A five- to fifteen-minute persistence measure is more credible than a one-bar coincidence | Annotation now |
| Medium | Macro-event windows | Distinguishes event/jump sessions from ordinary tape | Annotation now |
| Medium | Cross-ticker confluence | Reduces false confidence from one-symbol microstate | Annotation now |
| Low for now | Vanna / dealer-positioning proxies from sparse snapshots | Too much false precision relative to your available data | No |
| Low for now | Multi-day GEX memory features | Too closely tied to a boundary thesis your audit rejected | No |

The core reason to de-prioritize dealer-positioning change, vanna pressure, or gamma-distance-from-flip is not that those concepts are unimportant. It is that **you do not have the right data to estimate them cleanly**. The more microstructure-driven the market is, the more dangerous it is to feed a fragile proxy into a score and act as if it were ground truth. Likewise, if you do eventually use VIX1D or VIX9D, only do so if you already have a clean series and you de-bias VIX1D’s known intraday drift first; otherwise you will be adding another contaminated input. citeturn6search4turn6search5turn0search1

On the “loose intersection” question: yes, there is a legitimate framing, but it is **not** “7/8 is good enough.” The legitimate framing is a **two-timescale latent-state detector**. Some gates are slow state variables. Some are fast triggers. You are currently forcing them to co-occur on a single minute, which is exactly why they miss each other. Regime, structural context, spread regime, and broader flow regime should persist with a TTL on the order of 15–30 minutes. Sweeps, absorption, and CVD divergence should persist with a TTL of 1–5 minutes. A post-forward redesign should fire only when a fast trigger lands into an already-qualified slow state. That is conceptually stronger than relaxing thresholds, because it respects the different half-lives of the underlying processes.

The deepest design problem in ST, as summarized, is that it is trying to certify a latent market state with a pointwise AND across noisy proxies that operate on different clocks. That is structurally brittle. It produces a system that looks rigorous but actually suffers from **temporal aliasing**. The May 1 SPY near-fire strongly suggests this. I would not read it as “lower one threshold.” I would read it as “separate state evidence from trigger evidence.”

On whether the failed boundary audit kills the magnet/directional idea too: **not automatically**. The two claims are distinct. A static boundary claim says a level is special relative to random alternatives at the same distance. A directional/flow claim says dealer hedging or expiration-related positioning can alter drift, pinning, or mean-reversion conditional on state. The literature supports the second more than the first. But it also means your future theory should be about **state-conditioned microstructure**, not level mysticism. citeturn7search0turn1search4turn1search0turn1search1

## Classifiers, validation, and EV math

The most useful classifier split for your stack is **three separate models**, not one monolith.

| Classifier | What it should predict | Best form now | Best form later |
|---|---|---|---|
| Regime classifier | What kind of day/session is unfolding | Unsupervised day-state taxonomy or tiny rule set | Small HMM or frozen rules |
| Risk / feasibility classifier | Can this trade plausibly get paid before time and spread kill it? | Deterministic or isotonic reachability screen | Calibrated probabilistic model |
| Signal-quality classifier | Does this specific trigger merit taking risk? | None live; only shadow features | Penalized logistic, later |

For **current** supervised fitting, the ceiling is extremely low. In generic prediction-model research, binary-outcome models are very sample-size hungry, simple “10 events per variable” heuristics are already loose, and small datasets should not be casually split into train/test because that wastes information and worsens instability. Your problem is harder still because the observations are clustered by day and currently one-sided in direction. That means the effective N is not the raw alert count. It is much closer to day clusters or distinct signal episodes. On that basis, tree models and gradient boosting are a non-starter now, and even a three-feature logistic is too ambitious until you have many more forward day clusters. citeturn9search0turn9search3turn9search8

That implies four concrete validation rules.

First, **do not train a live filter now**. Everything you build right now is decoration or annotation unless it is a verified bug fix.

Second, treat forward data as **forward data**, not as a stream for sequential model refits. The right answer to your Q4.2 is closest to **(c)**: hold the forward sample, pre-register specific hypotheses now, score everything in shadow, and only fit later if a specific classifier remains theoretically motivated. You can still compute shadow predictions during Stage 1 and Stage 2, but do not deploy them as live filters.

Third, any forward classifier should be **forward-only** and **chronological**. Do not backfill it on the 27 in-sample ST fires or the 21 historical 0DTE alerts. Those samples are too small, too homogeneous, and too exposed to hindsight.

Fourth, evaluate at the **episode** and **day-cluster** levels, not just the raw alert level. Before Monday, I would add an annotation-only `episode_id` methodological repair. Example: same ticker, same direction, same broad state, and no gap of more than 45–60 minutes counts as one episode. Later repeated alerts become echoes of the first state, not fresh independent evidence.

A reasonable complexity ladder is:

| Data state | What is responsible |
|---|---|
| Current historical sample | No live classifier; only frozen shadow scoring |
| ~50 forward alerts across at least ~20–25 day clusters | Univariate or bivariate shadow models only |
| ~100 forward alerts across at least ~40–50 day clusters | Penalized logistic with at most 2–3 predictors |
| Far beyond that | Only then consider trees or boosted models |

For the MIXED refinement idea, write the spec now, but trigger analysis only after there are enough **forward MIXED episodes**, not just enough alerts. I would explicitly require something like **at least 30 MIXED forward alerts across at least 15 MIXED day clusters**, use only pre-specified features, and evaluate at the day-cluster level with cluster bootstrap. That is the right discipline.

On your EV question, the math is simple and very clarifying. Acceptance rate by itself does not determine expectancy. **Conditional expectancy on the taken subset** does.

If `EV = p*W - (1-p)*L`, then:

| Hit rate on selected subset | EV with +50 / -30 | EV with +40 / -30 | EV with +50 / -20 |
|---|---:|---:|---:|
| 35% | -2% | -5.5% | +4.5% |
| 40% | +2% | -2% | +8% |
| 45% | +6% | +1.5% | +11.5% |
| 50% | +10% | +5% | +15% |
| 55% | +14% | +8.5% | +18.5% |

So a filter that cuts participation to 50% is only valuable if the **selected subset** crosses the relevant break-even line. With a pure +50 / -30 profile, break-even is 37.5%. With effective average wins closer to +40, break-even rises to about 42.9%. That is why “filter half the alerts” is not the right target. The right target is “create a subset whose conditional hit rate and average win/loss profile cross break-even with room for slippage.”

## Strike selection, workflow rules, and strategic reframing

On strike selection, I would push back hard on fixed percent OTM or fixed point offsets as your default invariant. For 0DTE, that is the wrong axis. As entity["organization","The Options Industry Council","options education organization"] explains, delta is a rough probability/moneyness metric that already shifts with time-to-expiry and implied volatility, and gamma is highest around near-ATM, near-expiry strikes. That is exactly why a fixed 0.2% or 0.5% distance is unstable across tickers and volatility states. A delta-normalized strike target is more coherent than a human eyeballed distance target. citeturn8search0turn8search3

My recommendation is therefore not “always buy 0.30 delta” as a hard rule, but “**normalize by delta first, then add a reachability constraint**.” In practice, that means your baseline research target for long-premium intraday trades should be near-ATM or only slightly OTM, with farther OTM strikes reserved for the subset of sessions that pass a directional/event regime test **and** have a reachability ratio that says the strike is inside a high-quantile expected move. Your own summary already points the same way: the strikes that actually went ITM were very close to spot.

On SPX specifically, I do **not** think the current issue is just the $5 strike grid. The grid matters; Cboe’s product specs indicate that SPX strike intervals are generally no less than 5 points, with granularity improving as expiration approaches. But a systematic gap of roughly 0.5% OTM in SPX versus roughly 0.2% in SPY is too large to blame on strike granularity alone. That looks more like either a ticker-scaling bug or a deeper design miscalibration in how the system maps “reasonable distance” across underlyings. If code audit proves a genuine scaling bug, that is the **one** logic change I would bless before Monday under your freeze rule. If it is not provably a bug, do not change it now; just annotate and keep SPX separate in the forward analysis. citeturn13search7turn13search2

The Apr 29 workflow rule — require ST confirmation before acting on a 0DTE alert — is a very good **temporary falsification rule**. On your own evidence it prevented catastrophe. But I would not want that rule to become the permanent architecture unless ST’s fire rate materially improves, because otherwise it is not a filter so much as a kill switch. Long term, the more defensible architecture is likely: **0DTE candidate → day/risk qualifier → ST rolling-state assist**, not **0DTE alert → wait for perfect ST coincidence**.

Among the alternative workflow rules you listed, the ones worth shadowing are `Tape Regime != NOISY` and `recent ST near-fire`. The one I would de-prioritize is “positive overnight macro tape,” because the literature on opening overreaction and intraday reversal says that a simple positive-overnight sign can easily have the wrong interpretation on reversal days. Treat overnight context as a segmentation variable, not a directional gate. citeturn12search0turn12search1

The broader strategic reframing I think you are missing is this: the real object may not be “a universal 0DTE long-premium directional strategy keyed off GEX levels.” It may be a **regime-conditioned strategy selector**. The literature’s mixed findings on 0DTE — sometimes dampening volatility, sometimes amplifying it — are exactly what you would expect if the correct action changes by state. On trend-amplifying event days, long premium can make sense. On balanced or pinning days, the right action may be “skip” or, later, a very different expression entirely. That is a much stronger framing than trying to rescue a universal long-premium engine by adding more confluence points. citeturn1search0turn1search1turn7search0turn0search1

If I had to kill one thing from the current stack after the forward window, it would be **B+ as a production-grade class**. A grade that did not separate winners from losers is not a ranking system. It is a label.

## Before Monday and after the forward window

Under your freeze constraint, the action plan separates cleanly into bug fixes, annotation-only work, methodological repairs, and true post-forward redesign.

| Timing | Recommendation | Classification under freeze | Why |
|---|---|---|---|
| Before Monday | Audit the strike picker for a provable SPX scaling bug | **Bug fix only if verified** | Unreachable strikes can invalidate the forward read |
| Before Monday | Add `alert_strike_delta`, `distance_to_strike_bps`, `minutes_to_expiry`, `reachability_ratio` | **Annotation only** | Highest-value missing feasibility telemetry |
| Before Monday | Add `open_reversion_ratio`, `path_efficiency`, `open_cross_count`, `directional_change_count`, `jump_share`, `macro_window_tag`, `cross_ticker_alignment` | **Annotation only** | Captures the unmodeled day-state layer |
| Before Monday | Add `st_near_fire_score_15m`, `missing_gate_name`, `missing_gate_margin`, and slow/fast gate shadow states | **Annotation only** | Directly tests the temporal-aliasing hypothesis |
| Before Monday | Add `episode_id` for repeated same-direction same-state alerts | **Methodological repair** | Prevents pseudo-replication in forward analysis |
| Before Monday | Write `MIXED_REFINEMENT_SPEC.md`, `STRIKE_FEASIBILITY_SPEC.md`, and `ST_TEMPORAL_AUDIT_SPEC.md` | **Methodological repair** | Preserves pre-registration discipline |
| During Stage 1 and Stage 2 | Run all new features and shadow classifiers, but do not gate on them | **Allowed** | Learn without contaminating the falsification window |
| After Stage 3 and only with enough day clusters | Redesign the architecture into candidate / regime / risk / trigger layers | **Post-forward redesign** | That is the first moment where the sample supports it |
| After Stage 3 | Use the existing paired-trade infrastructure to A/B current strike picker vs delta-normalized reachability picker in shadow | **Post-forward redesign** | Cleanest way to test expression versus signal |

If I had to name **one thing to do this weekend**, it would be this: **prove or disprove a strike-selection bug in SPX, and regardless of the answer, start logging a frozen reachability ledger for every alert**. That directly addresses the most avoidable failure mode in your current evidence and gives the forward window a chance to answer the right question.

If I had to summarize the whole audit in one sentence, it would be: **stop treating the current 0DTE engine as a finished directional signal and start treating it as a candidate stream that still needs a day-state filter and a feasibility filter before it deserves capital.**