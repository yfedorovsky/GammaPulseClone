# GammaPulse AutoResearch Validation Gate

## Bottom line

Your current strategic choice is mostly right: **build thin over your own substrate, borrow ideas aggressively, and avoid inheriting a full Qlib-centric agent stack.** RD-Agent and AlphaAgent are valuable as *reference architectures* for workflow decomposition, trace persistence, knowledge reuse, and exploration control, but they are not a good fit to fork wholesale into a live options-flow research OS built around `alert_outcomes.db`, ThetaData replay, and event-level options outcomes. RD-Agent(Q) is explicitly organized around a five-unit loop—Specification, Synthesis, Implementation, Validation, Analysis—with a task-specific knowledge forest, Co-STEER code-generation workflow, and a contextual bandit scheduler, but its quant scenario is aimed at factor/model co-optimization on Qlib-style equity research rather than small-sample, overlapping, intraday options alerts. AlphaAgent is a closer conceptual fit on the *research-control* side because it adds originality enforcement, hypothesis–factor alignment, and complexity control, but its concrete implementation is still tied to a Qlib factor-expression world rather than your alert-outcome substrate. citeturn31view0turn32view0turn32view1turn39view0turn39view1turn29view0

The adversarial read is this: if you copy enough of the “rigor stack” without changing the *unit of analysis*, *trial accounting*, and *power model*, you will create a system that looks sophisticated while remaining statistically fragile. CPCV does not manufacture power. DSR becomes punitive if you seed the search count honestly. PBO is often misused as though it were a p-value. Fixed-window Wilson/Clopper intervals are not valid under continuous re-checking. And an alert-level database with raw `n` in the hundreds becomes much smaller once you cluster dependent alerts and split by regime. That means your current Phase 0/1 plan is directionally strong, but it needs to be **simplified at the gate, stricter on independence accounting, and more Bayesian in subgroup estimation** if it is going to be honest rather than ceremonial. citeturn42view3turn42view4turn43view4turn35view0turn36search0turn36search3turn37search1turn37search3

## Fork versus build

The strongest evidence in favor of **not forking RD-Agent wholesale** is in the repos themselves. RD-Agent is MIT-licensed and substantial, with a large codebase and distinct modules for `app`, `components`, `core`, `oai`, `scenarios`, and `utils`; within `components` it includes `benchmark`, `coder`, `document_reader`, `knowledge_management`, `proposal`, `runner`, and `workflow`. RD-Agent(Q) also explicitly centers a Qlib-backed research/development loop, Co-STEER implementation logic, and a contextual bandit controller. That makes it a rich source of design patterns, but also a large dependency surface whose abstractions were built for a different research object than yours. citeturn39view0turn21view2turn22view0turn31view0turn32view1turn32view3

AlphaAgent confirms the same conclusion from the other direction. Its repo is MIT-licensed, explicitly states that it follows the RD-Agent implementation, and organizes itself around the same broad skeleton (`components`, `core`, `oai`, `scenarios/qlib`, `utils`). The *useful* parts for you are the **regulation ideas**, not the scenario code: the KDD paper’s three regularizers are exactly the three things most likely to stop an autonomous loop from degenerating into duplicated, overfit output—AST-based originality enforcement, hypothesis–factor alignment, and AST-based complexity control. But the files where those ideas live in code—`alphaagent/scenarios/qlib/regulator/factor_regulator.py`, `proposal/factor_proposal.py`, `proposal/model_proposal.py`, and the Qlib-specific prompt/config files—are embedded in a symbolic factor-mining and Qlib research flow that does not match options-flow event research. citeturn39view1turn29view0turn23view1turn25view0turn25view1turn25view2turn27view5

The practical module-level recommendation is:

- **Borrow ideas, not the stack**, from RD-Agent:
  - keep the **Research → Development → Feedback** split;
  - copy the idea of an immutable **trace object** for every hypothesis, implementation, validation result, and retirement decision;
  - borrow the **knowledge store pattern** from `rdagent/components/knowledge_management`, especially the generic `graph.py` / `vector_base.py` idea for storing experiment context and retrieval metadata;
  - borrow the *concept* of the contextual bandit scheduler, but reimplement it thinly around your own queue and economic objective. citeturn31view0turn32view0turn32view1turn33view0

- **Borrow specific regularization logic** from AlphaAgent:
  - read and adapt `factor_regulator.py` conceptually for a **novelty gate**;
  - read and adapt `factor_proposal.py` for **hypothesis schema and conversion discipline**;
  - adapt its three-gate logic into your world as:
    - **novelty** against prior candidate definitions and signal output vectors,
    - **hypothesis alignment** between natural-language claim and executable test definition,
    - **complexity control** on feature count, conditioning depth, and degrees of freedom. citeturn25view0turn25view1turn29view0

- **Do not vendor mlfinlab from the public repo.**
  The public `mlfinlab` GitHub repository explicitly says it exists “for the sole purpose of providing users with an easy way to raise bugs, feature requests, and other issues,” and the public code exposed there is skeletal. The raw `cross_validation/combinatorial.py` and `cross_validation/cross_validation.py` files expose the right class names—`CombinatorialPurgedKFold`, `PurgedKFold`, `ml_get_train_times`, `ml_cross_val_score`—but the public code shown there is placeholder/stub code with `pass` bodies. The repo is also marked as “all rights reserved,” not an open vendoring target. In other words: use the book and the API ideas, not this repo as source code. citeturn39view2turn23view2turn26view0turn26view1

- **Do not vendor pypbo as-is.**
  `pypbo` is useful as a reference implementation inventory—it includes PBO, PSR, MinTRL, MinBTL, and DSR—but the repo is AGPL-3.0, lists very old dependencies, leaves important items in TODO, and has no releases. For a proprietary trading research system, that makes it a poor transplant candidate. Reimplement the parts you need directly from the papers. citeturn34view0turn18view8

- **Use `arch.bootstrap.SPA` and, if needed, `arch.bootstrap.StepM` directly.**
  Unlike the public mlfinlab repo, `arch` gives you an actively documented implementation of SPA/Reality Check and StepM with block bootstrap controls, studentization, and explicit multiple-comparison framing. citeturn35view0turn35view1

The short version is: **your fork-vs-build call should stand.** Build the substrate-specific engine yourself. Read RD-Agent and AlphaAgent closely. Vendor only tiny, generic utilities after audit. Reimplement the statistical core in-house. citeturn31view0turn39view0turn39view1turn39view2

## The thresholds that are actually defensible for your data

The uncomfortable truth is that your current plan includes more inferential machinery than your sample sizes can support *if you insist on per-cohort frequentist validation*. That does not mean the plan is wrong. It means the thresholds must be set with the expectation that **most subgroup claims will remain unresolved**, not “validated.” citeturn37search1turn37search3turn37search9turn43view4

For **DSR**, a `0.95` cutoff is defensible only as a **secondary admission condition**, not as the main gate. DSR is just PSR with a search-adjusted threshold, and the DSR logic explicitly raises the rejection threshold as the number of independent trials increases. The expected-max-Sharpe adjustment is the crux: under the DSR framework, the threshold Sharpe under the null is approximated by the cross-trial Sharpe dispersion multiplied by an extreme-value term involving the Euler–Mascheroni constant and two inverse-normal quantiles, which grow with the effective number of independent trials `N`. In a continuously running loop, that `N` is **cumulative and monotone** over the search family; resetting it quarterly would be false accounting. citeturn43view1turn43view4turn44search0turn44search10

The exact term you should use is the standard DSR extreme-value approximation,

\[
\widehat{SR}_0
=
\mathbb{E}[\widehat{SR}]
+
\sqrt{\mathbb{V}[\widehat{SR}]}
\left[
(1-\gamma)\Phi^{-1}\!\left(1-\frac{1}{N_{\text{eff}}}\right)
+
\gamma \Phi^{-1}\!\left(1-\frac{1}{N_{\text{eff}}e}\right)
\right],
\]

with `N_eff` defined as the **effective number of independent scored trials**, not the raw hypothesis count. Then use the usual DSR transform with sample length and skew/kurtosis correction. Operationally, for GammaPulse, I would set:
- **DSR < 0.90**: reject;
- **0.90 ≤ DSR < 0.95**: shadow-only / insufficiently proven;
- **DSR ≥ 0.95**: eligible for human review, but only if SPA and economic-lift conditions also pass.  
This is stricter than using DSR as a ranking score and looser than pretending DSR alone can validate an options signal family at your sample sizes. citeturn43view4turn44search0turn44search10turn37search1

For **PBO**, the literature-based answer to your 0.05 vs 0.50 conflict is: **0.50 is the definitional danger boundary; 0.05 is not a canonical PBO threshold at all.** The PBO paper defines overfitting as the event that the in-sample winner ranks below the median out of sample, and PBO is the probability of that event. That makes 0.50 the point where your selected strategy is more likely than not to be below-median OOS. PBO is not a conventional p-value, so importing a `0.05` reject rule is category error. For live research gating, I would use:
- **PBO ≥ 0.50**: fail hard;
- **0.20 ≤ PBO < 0.50**: reject for deployment, maybe keep only as research artifact;
- **0.10 ≤ PBO < 0.20**: shadow-only;
- **PBO < 0.10**: acceptable diagnostic.  
The 0.10 and 0.20 lines are operational choices, not paper-imposed constants; the paper itself supports the interpretation of 0.50 as the “detrimental selection process” line. citeturn42view3turn42view4

For **CPCV**, use fewer, fatter blocks than a standard equity-factor workflow would. With event counts only in the hundreds and overlapping horizons, my default would be:
- **`N = 6` contiguous time groups, `k = 2` test groups** as the default;
- move to **`N = 8`, `k = 2`** only when a candidate family has both enough calendar span and roughly ≥480 independent cluster observations.  
The reason is simple: smaller groups create a prettier combinatorics count while starving each fold of information. Six groups with two test folds gives you meaningful temporal diversity without shredding already-thin data. The public mlfinlab API shape (`CombinatorialPurgedKFold`, `n_splits`, `n_test_splits`, purge/embargo mechanics) is aligned with this style of implementation even though the public repo is not usable as source. citeturn23view2turn26view0turn26view1

For **embargo**, do not think in percentages first. Think in **event end-times**. Purge every observation whose label interval overlaps the test interval, and then embargo at least the maximum economic hold horizon after each test block. In your case—1h, EOD, and next-day outcomes—the minimum honest embargo is **one full trading day** after a test block, and **two trading days** is safer if same-day ticker clustering is heavy. If your implementation forces a percentage, derive it from calendar span rather than hard-coding a magic number. A flat `1%` embargo is acceptable only as a software default, not as the conceptual definition. citeturn26view0turn26view1turn35view0

For **MinTRL / MinBTL / required N**, the power reality is harsh. On a simple one-sided binomial power approximation using your own numbers—testing whether a candidate really clears a **5 percentage point** improvement over the 22.7% breakeven win rate, i.e. `22.7%` vs `27.7%`—you need roughly **455 independent observations** for 80% power at a one-sided 5% error rate, **~574** for the two-sided equivalent, and roughly **638–778** for 90% power. That is *before* dependence inflation, overlapping labels, or heavy-tailed PnL enters the picture. In other words: **n in the low hundreds is not enough to prove a 5pp edge per cohort**. It is enough to rank candidates coarsely and to decide what deserves more observation, not to bless fine regime splits as “validated.” That conclusion is exactly in the spirit of the DSR/MinTRL literature and the broader multiple-testing critique in finance. citeturn37search1turn37search3turn38search17turn43view4

For **Hansen SPA**, the loss differential should be **economic and cluster-aligned**. The `arch` docs are explicit that benchmark and alternative inputs are arrays of losses. In your case that means the benchmark should be your SOE-A baseline, and the candidate should be compared on **per-decision-cluster net economic loss**, not raw alert labels, not MAE alone, and not an alert-level verdict percentage. The loss should be a pre-registered utility-compatible measure—e.g. negative net R-multiple or negative cost-adjusted PnL, optionally clipped/winsorized in a pre-specified way to control domination by single gap events. Use verdict-based Brier/log-loss only if the object being compared is a probabilistic classifier rather than a tradeable selection rule. citeturn35view0turn14search12

## The global trial counter and the multiple-testing body count

The part of your plan that most determines whether the loop is honest is not DSR, PBO, or CPCV by itself. It is whether you will keep a **painfully honest, monotonically increasing trial ledger**. The DSR literature is explicit that the relevant `N` is the number of **independent** trials, not the raw number of attempts, and López de Prado’s later multiple-testing work explicitly recommends estimating the number of effectively uncorrelated trial clusters rather than naively counting all variants. Harvey–Liu–Zhu and Harvey–Liu’s backtesting work make the broader point: once the search history is ignored, significance is routinely overstated and most “discoveries” become unreliable. citeturn43view4turn15search1turn15search14turn37search1turn37search3turn37search9

That means your historical ad hoc backtests *do* count—**but only if they reached numerical evaluation** on the same or substantially similar substrate. My recommendation is:

- Count as a historical trial every candidate that produced a **distinct scored backtest, replay, or outcome report** against `alert_outcomes.db` or ThetaData replay.
- Do **not** count raw LLM brainstorming, prompt variants, or discussion-only ideas that never reached numerical scoring.
- Collapse near-duplicates into one effective trial cluster when they are materially the same candidate—highly correlated signal outputs, minor threshold tweaks, or prompt paraphrases that map to the same executable logic.
- Estimate `N_eff` by clustering numerically scored candidates using their return vectors, alert-incidence vectors, or both. This is the operational analogue of the “effectively uncorrelated clusters of trials” idea in the multiple-testing literature. citeturn15search1turn15search14turn43view4

The adversarial point is that if you seed `N` honestly, your DSR hurdle may indeed become high enough that almost nothing clears. That is not a bug. That is your data telling you that a continuously searching solo operator with small-sample cohorts **cannot afford to fully score dozens of materially distinct hypotheses every quarter** and still pretend to know which ones are real. In practice, a system at your power level can brainstorm many hypotheses, but should probably allow only **a single-digit number of genuinely distinct candidates per horizon/family per quarter** into the full expensive gate, with the rest staying in a cheap descriptive triage layer. If you let 50 materially distinct candidates per quarter hit full CPCV+SPA on the same substrate, the gate will either go slack and admit noise, or stay honest and admit almost nothing. Both are failure modes; only one is statistically respectable. citeturn37search1turn37search3turn37search9turn43view4

## The power problem you cannot code your way around

This is the central attack on the whole gate: **purged CV cannot create information that is not present in the data.** CPCV helps control leakage and stabilizes model comparison. It does not rescue an underpowered problem. If your alert-outcome substrate has only a few hundred raw events per signal family, and those events are clustered by day, ticker, tenor, and common underlying flow episode, then the effective sample size for “distinct economic decisions” is materially smaller than the row count in the database. That means a large fraction of per-cohort results are estimation problems, not hypothesis-testing problems. citeturn26view0turn26view1turn35view0turn37search1

This is exactly where **hierarchical / Bayesian partial pooling** stops being a luxury and becomes the only honest way to learn from subgroup structure. The statistical case for partial pooling is that small groups should borrow strength from the global population rather than be treated as isolated worlds; both Stan and PyMC case studies on repeated binary trials make this explicit. For GammaPulse, that means regime splits, OI cohort splits, and signal-subtype splits should not all be forced through separate frequentist gates. Use a **hierarchical beta-binomial** or hierarchical logistic model for win rates, and a hierarchical Student-t or Gaussian model for R-multiples / net expectancy, with signal family, ticker bucket, regime, and horizon as partial-pooling dimensions. Frequentist deflation is still appropriate at the **top-level candidate-selection stage**; it is just the wrong hammer for small subgroup estimation. citeturn40search0turn40search4turn40search11

So the honest answer to “is Phase 2 internal mining even powered?” is: **only if you do not define the candidate too narrowly, and only if you pool across related cohorts when estimating effect size.** Per-cohort frequentist gates are underpowered. Hierarchical shrinkage plus a top-level search-aware validation gate is the defensible hybrid. citeturn40search0turn40search11turn37search1turn43view4

## The decay monitor you should actually run

Your existing Phase 0 rule—rolling 60d and 90d win rate with Wilson and Clopper–Pearson lower bounds, triggering retirement when the lower bound slips below breakeven—is directionally sensible but statistically brittle under continuous monitoring. The issue is not the idea of rolling health checks. It is the fact that **fixed-n confidence intervals do not retain their nominal error rate under optional stopping and repeated peeking**. That is exactly what confidence-sequence and always-valid inference work was designed to solve: intervals and p-values that remain valid under arbitrary stopping and continual re-checking. citeturn36search0turn36search3turn36search7turn36search14

If you want an honest retirement process, the minimum correction is:

- monitor at the **decision-cluster level**, not raw alert level;
- replace “single-window lower bound below breakeven” with **two-condition hysteresis**:
  - recent edge estimate is weak enough to matter, and
  - recent realized economics are actually deteriorating;
- require the condition to persist across **at least two consecutive checks** before moving from WATCH to RETIRE_CANDIDATE.  

This is because otherwise the system will whipsaw on ordinary variance and retire viable signals during normal drift. That failure mode is especially acute when the underlying edge is small and the recent sample is short. citeturn36search0turn36search14turn37search1

My recommendation is:

- Use **one always-valid confidence sequence** or an anytime-valid posterior/probability monitor for the recent win-rate or expectancy statistic.
- Keep your 60d and 90d windows as dashboards, not as the sole statistical trigger.
- Promote:
  - **HEALTHY** if both recent economic expectancy and the sequential lower bound remain above the breakeven line;
  - **WATCH** if either weakens;
  - **RETIRE_CANDIDATE** only if:
    - both the short and long recent windows weaken,
    - the sequential lower bound falls below breakeven,
    - recent net economic PnL is negative,
    - and the condition persists for two checks with a minimum recent effective sample (for example, at least ~50 cluster observations).  

That is much closer to how a desk would actually manage a delicate signal: **with hysteresis, economics, and repeated-look validity**, not one-shot interval crossing. citeturn36search0turn36search3turn36search14

If you must stay simpler in the current build, then keep Wilson for the dashboard, drop Clopper–Pearson from the operational trigger, and add the two-check hysteresis plus cluster-level recent-PnL confirmation. That will materially reduce false retirements without pretending you have solved sequential inference completely. citeturn36search14turn37search1

## The minimal gate that survives the adversarial attack

If I strip your Phase 0/1 plan down to the version that I believe is genuinely worth building at your current sample sizes, it looks like this.

First, change the **unit of analysis**. Do not validate at raw alert level. Validate at the level of the **economic decision cluster**: same underlying flow episode, same ticker-day or ticker-session, same fire-time information set, one realized outcome record. That is the only way your resampling, SPA losses, and rolling decay logic can approximate independence. This is the single most important mid-build correction. citeturn26view0turn26view1turn35view0

Second, simplify the **top-level validation gate** to four layers:

- **Novelty / complexity pre-gate** before any expensive backtest:
  - reject candidates that are functionally duplicates of prior tested ideas;
  - cap degrees of freedom and conditioning depth;
  - require a clean natural-language hypothesis matched to an executable definition.  
  This is the part worth borrowing from AlphaAgent. citeturn29view0turn25view0turn25view1

- **Economic relevance gate** on a cheap holdout triage:
  - candidate must improve a single pre-registered economic objective versus SOE-A on cluster-level returns, net of costs;
  - no subgroup mining allowed at this stage.  
  This is where most bad ideas should die quickly. citeturn35view0turn37search1

- **Full validation gate**:
  - purged / embargoed blocked walk-forward or CPCV on cluster-level outcomes;
  - SPA versus SOE-A using cluster-level economic loss differential;
  - DSR and PBO reported as **diagnostics**, not sole pass/fail arbiters;
  - honest cumulative `N_eff` search ledger. citeturn35view0turn42view3turn42view4turn43view4

- **Human ship gate**:
  - only candidates with coherent mechanism, stable fold behavior, acceptable PBO, strong-enough DSR, and practical implementation simplicity go live. citeturn41search2turn41search6turn41search11

Third, use **frequentist deflation only where it is strongest**: top-level candidate admission. Use **hierarchical/Bayesian methods** where your problem is mostly estimation under small samples: subgroup effects, regime conditioning, and decay monitoring. That split is the honest compromise between rigor and usable signal discovery. citeturn40search0turn40search4turn40search11turn36search0

Fourth, accept that **`n ≥ 200` is not a ship threshold**. At your economics, it is barely enough to start shadowing something serious. It is a staging threshold, not a validation threshold. For per-family shipping claims, look for something closer to **~450 effective independent cluster observations** if the edge you need to prove is only five win-rate points above breakeven. If you cannot get that per cohort, then ship only at a pooled family level or keep the candidate shadowed. That is not theatre; it is restraint. citeturn37search1turn38search17

Finally, the specific corrections I would make **mid-build** are:

- replace raw-alert validation with **cluster-level validation**;
- make the **global search ledger immutable and cumulative** now, before the history becomes unrecoverable;
- demote DSR and PBO from sole gatekeepers to **diagnostic companions** to SPA and economic lift;
- stop planning to rely on public `mlfinlab` source code—build those splitters yourself or use another legitimately open implementation;
- add **hierarchical partial pooling** for all subgroup estimates;
- add **sequential validity / hysteresis** to the decay monitor;
- cap full validation throughput to a **small number of materially distinct candidates per family per quarter**. citeturn39view2turn26view0turn26view1turn40search0turn36search0turn37search1

## Open questions and limitations

I did not inspect every implementation detail inside RD-Agent’s and AlphaAgent’s source files, so the module recommendations above are strongest at the architectural and file-boundary level, not as a line-by-line vendoring audit. The public `mlfinlab` repo is clearly unsuitable as a vendoring target, but if you have a licensed private copy, that changes the software recommendation, not the statistical one. citeturn39view0turn39view1turn39view2

I also did not derive a market-specific, closed-form MinTRL/MinBTL under your exact empirical skew, kurtosis, and dependence structure from first principles. The sample-size figures above are conservative power approximations anchored to your stated breakeven and target uplift; the true requirement is likely worse once dependence and heavy-tailed economic outcomes are handled correctly. That strengthens, rather than weakens, the main conclusion: **your current data can support disciplined ranking and retirement, but per-cohort “validation” needs either more observations or partial pooling.** citeturn38search17turn43view4turn37search1