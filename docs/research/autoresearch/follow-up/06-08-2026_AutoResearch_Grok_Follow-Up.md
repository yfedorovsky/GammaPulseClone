**Solid plan. You are building this the right way.**

Your Round 1 conclusion (research OS \+ rigorous validation engine over *your own* proprietary data first; retirement/adaptation timing as the durable edge; skip X; external sources later) is exactly correct for a solo operator in options flow. The hard rules (offline-only, human gate, no live LLM scoring, no X scraping) protect your real moat (sub-30s latency \+ proprietary detectors \+ labeled outcomes).

Phase 0 (decay/retirement monitor) and Phase 1 (validation/deflation engine) are the highest-leverage pieces you can ship right now. Everything else is secondary until these are production-grade and battle-tested on your historical alert\_outcomes.db.

### **Phase 0 – Decay/Retirement Monitor (Read-Only, High Priority)**

Your design is clean:

* Rolling 60d / 90d win rate per cohort (signal-type × regime × opening/closing flow, etc.).  
* Wilson \+ Clopper-Pearson 95% CIs.  
* HEALTHY / WATCH / RETIRE\_CANDIDATE states.  
* Trigger: CI lower bound \< breakeven (22.7% for 3.4× R:R).

**Recommended enhancements (implement these early):**

**Handle small n in regime splits intelligently**

1. With hundreds overall but often \<50–100 once split by regime, raw per-cohort CIs will be wide and noisy. Add:  
   * **Empirical Bayes / shrinkage** toward the pooled cohort mean (mirrors the Quarter-Kelly \+ empirical Bayes shrinkage you already use in GammaPulse sizing). This stabilizes estimates without over-penalizing real regime differences.  
   * Minimum n gate (e.g., require n ≥ 40–50 for a regime-specific verdict; otherwise fall back to pooled \+ flag “low data”).  
   * Track **expectancy \+ MFE/MAE distribution** (not just binary WR). A cohort can have “acceptable” WR but terrible tail risk or calibration drift.  
   * Version the monitor logic itself (store config \+ code hash so you can audit “why did this flip to RETIRE on date X?”).

**Output & actionability**

2. Produce a lightweight “Signal Health Card” per cohort (or per signal) that includes:  
   * Current rolling metrics \+ CIs \+ state.  
   * Trend (improving / stable / deteriorating).  
   * Linked experiments from Phase 1 that touched this cohort.  
   * Suggested action (nothing / investigate / prepare retirement plan).  
3. Persist this in a small metadata DB (SQLite or DuckDB alongside alert\_outcomes.db). Make it queryable for dashboards or Prefect tasks.

**Auto-retire trigger**

4. Your rule (CI lower bound \< breakeven) is conservative and good. Add a second, softer signal: “deterioration detected” (e.g., recent 30d point estimate meaningfully below historical \+ statistical support). This gives you lead time before hard retirement.

Phase 0 should run on a schedule (daily or after each new batch of outcomes) and be completely independent of live scoring.

### **Phase 1 – Validation / Deflation Engine**

Your stack and rules are excellent:

* DSR \+ PBO \+ CPCV (purged \+ embargoed) \+ MinTRL/MinBTL \+ Hansen SPA vs SOE-A baseline.  
* Global N-trials counter (critical).  
* Economic null (realistic slippage).  
* n ≥ 200 clean outcomes \+ shadow → human → ship.  
* Auto-retire when rolling CI lower bound \< breakeven.

**Implementation notes with your chosen libs:**

* **pypbo** (esvhd/pypbo): Use it directly for PSR, MinTRL, MinBTL, DSR, and PBO. It has a convenient pbo.pbo() function. Feed it the return series (or outcome series mapped to P\&L) from your backtester. Make sure you pass the *global* N-trials count (persistent across all experiments ever run on this system).  
* **mlfinlab CPCV**: The combinatorial purged CV implementation is solid for financial time-series. Adapt it to your discrete alert-level data:  
  * Treat each alert as an observation with its outcome window (1h / EOD / next-day).  
  * Purge/embargo based on **fire time overlap** and **outcome period overlap** (e.g., embargo 1–2 trading days around major events or overlapping alerts on the same name).  
  * Because your data is already “labeled outcomes” rather than raw price bars, you may need a thin wrapper that constructs the combinatorial paths at the *alert cohort* level rather than tick level.  
* **arch.bootstrap.SPA** (Hansen’s Superior Predictive Ability test): Perfect for testing a new candidate against the SOE-A baseline while accounting for data snooping. Run it on the distribution of path returns from CPCV.  
* **MLflow \+ Prefect**: Ideal pairing.  
  * MLflow: Track every experiment (hypothesis ID, config, metrics, artifacts, model/code version, N-trials at time of run).  
  * Prefect: Orchestrate the full flow — “prepare cohort data → compute baseline stats → run CPCV/DSR/PBO/SPA → apply economic null → log to MLflow → update retirement monitor → notify human if passes thresholds”.

**Global N-trials counter**

Persist this in the metadata DB and increment atomically on every backtest/evaluation that contributes to the multiple-testing universe. DSR and PBO are only as good as this number being accurate and comprehensive.

**Economic null**

Apply your realistic slippage model to the MFE/MAE or mapped P\&L before computing metrics. Be conservative — use the worse of historical realized slippage or a stressed scenario. Document the exact slippage assumptions in every experiment record.

**Small n & regime splits in validation**

Same problem as Phase 0\. For new candidates:

* Require minimum effective sample size after purging/embargoing.  
* Report both pooled and regime-stratified results (with shrinkage where n is small).  
* Use CPCV paths to get an *empirical distribution* of performance rather than relying on a single point estimate.

### **Overall Research OS Architecture (Thin from Scratch)**

Build a lightweight, auditable layer with these core entities (use SQLAlchemy models or Pydantic \+ DuckDB/SQLite):

* **Hypothesis** — id, natural language description \+ structured target (which detector/cohort/feature interaction), economic rationale, proposed change (diff or new code snippet), status, created\_by (human or internal miner), linked experiments.  
* **Experiment** — hypothesis\_id, config (full reproducibility), data slice (cohort \+ date range), metrics (DSR, PBO, SPA p-value, WR, expectancy, CI bounds, etc.), verdict, artifacts (MLflow run ID, backtest logs), N-trials consumed, human review notes.  
* **SignalHealth** (from Phase 0\) — linked to experiments that affected it.  
* **AuditLog** — immutable record of every decision, state change, and rationale (KX-style governance).

**Borrowed ideas, applied cleanly (no wholesale fork):**

* **RD-Agent style split**: Even in a thin system, separate concerns — “Research” module (internal pattern mining on alert\_outcomes.db \+ hypothesis proposal), “Dev” module (generate shadow implementation of the proposed change), “Feedback/Eval” module (run Phase 1 validation \+ explain why it passed/failed).  
* **AlphaAgent gates** (lightweight versions):  
  1. Novelty / non-duplication (simple AST or structural diff against existing detectors \+ prior experiments).  
  2. Alignment to your core thesis (informed flow criteria, dealer-gamma regime conditioning, selection logic).  
  3. Complexity parsimony (prefer small, interpretable mutations over giant new classifiers).  
* **KX-style governance**: Every output (hypothesis, experiment result, retirement recommendation) must be **governed and auditable**. Produce a one-page “Signal Card” or “Experiment Card” that a human can review in \<5 minutes. Include lineage, risks, and explicit retirement criteria.

**LLM role (strictly offline, local preferred)**

Use your Mac Mini M4 \+ Ollama (or equivalent local setup) for:

* Pattern mining on db subsets (“find regime × flow-type slices where SOE A win rate is materially above breakeven with statistical support”).  
* Drafting falsifiable hypotheses from those patterns.  
* Summarizing experiment results for human review.  
* Never for generating production code that bypasses the human gate.

Ground every prompt heavily in your schema, known detector logic, and trading thesis. Ask it to output structured JSON with explicit assumptions and falsifiable claims only.

### **Recommended Immediate Next Steps**

1. Finish Phase 0 with the shrinkage \+ minimum-n \+ expectancy enhancements. Test it on historical data and produce a few real Signal Health Cards.  
2. Implement the core Phase 1 stats wrappers (pypbo \+ adapted mlfinlab CPCV \+ SPA) inside a Prefect task \+ MLflow tracking. Validate the whole pipeline on a known historical cohort (e.g., re-evaluate SOE A itself).  
3. Add the global N-trials counter and economic null application.  
4. Wire Phase 0 and Phase 1 together so retirement monitor can trigger re-validation of borderline cohorts.  
5. Once stable, add the first “Internal Pattern Miner” task that runs weekly on the db and proposes 3–5 high-signal, falsifiable hypotheses for Phase 1 validation. This is where the real compounding begins.

This architecture stays thin, stays over *your* substrate, stays offline \+ human-gated, and directly attacks the two things that actually destroy solo systematic edges: **unnoticed decay** and **manufactured false edge from multiple testing**.

You are already ahead of most people building “AI quant research loops” because you started with the hard constraints and the right data. Execute Phase 0/1 cleanly and the rest becomes much easier (and safer).

If you want, share:

* Current alert\_outcomes.db schema (or a sample row)  
* Existing Prefect flow structure (if any)  
* How you currently compute outcomes/MFE/MAE

…and I can give concrete schema extensions, task skeletons, or prompt templates for the internal miner. Happy to iterate on the exact fitness function or CPCV adaptation for alert-level data as well.

**1\. Fork-vs-build — confirm or refute**

**Build thin over your own substrate and borrow ideas is the correct call.** Forking RD-Agent wholesale would be a mistake here.

RD-Agent (Microsoft/MIT research) is designed for equity-factor alpha mining on Qlib-style data with LLM-driven research/dev/feedback agents and a knowledge forest. Its validation is relatively weak (mostly IC \+ deduplication). Your substrate is completely different: proprietary labeled alert outcomes (discrete, context-rich, non-stationary intraday options flow with 1h/EOD/next-day verdicts, MFE/MAE, regime splits, and a rich alert\_outcomes.db). The domain mismatch is large enough that a full fork creates more friction than value.

**What is worth vendoring or adapting verbatim (minimal surface):**

* **mlfinlab CPCV** (combinatorial purged cross-validation implementation in mlfinlab/cross\_validation/combinatorial.py): Solid, well-tested for financial time-series with purging/embargoing. Adapt the path construction to your alert-level data (purge on overlapping fire times or outcome windows) rather than raw price bars. This is low-risk to pull in.  
* **pypbo** primitives (DSR, PSR, MinTRL, MinBTL, PBO calculation): Clean implementations of Bailey/López de Prado methods. Use the functions directly.  
* **AlphaAgent-style gates** (lightweight versions only): The AST-novelty / structural similarity check and complexity control ideas are useful if you ever generate code mutations. You can implement a thin diff-based or AST-similarity check yourself in \<100 lines; no need to vendor the full LLM factor-generation machinery.  
* **KX-style governance/audit patterns** (from their GTC 2026 Trading Signal Agents blueprint): The emphasis on governed, auditable, event-time-aligned outputs with clear lineage and retirement criteria. Translate this into your “Experiment Card” / “Signal Health Card” artifacts.

**Do not vendor:**

* RD-Agent’s full agent orchestration or knowledge forest (wrong data model, weak validation for your use case).  
* Full LLM hypothesis generation pipelines from RD-Agent or AlphaAgent (you are correctly deferring broad external generation and focusing on internal mining first).

Real quant/options desks in 2026 almost never fork entire research agent frameworks like RD-Agent into production. They build thin custom layers over their proprietary data \+ borrow statistical primitives (CPCV, DSR/PBO from LdP ecosystem, mlfinlab or pypbo) and governance patterns. Agentic components are still mostly internal prototypes or research. Your “thin \+ borrow targeted modules \+ strong governance” approach is the professional pattern.

**2\. Lock the exact thresholds for your situation (n in the hundreds, non-stationary intraday options, daily-resolution outcomes)**

Be conservative. Your data has fat tails, negative skew in many options P\&L distributions, regime non-stationarity, and overlapping outcome windows. Per-cohort frequentist tests are under-powered for small edges.

* **DSR**: Use a **0.95 confidence level** (standard). For the expected-max Sharpe term E\[max⁡SR∣N\] E\[\\max SR \\mid N\] E\[maxSR∣N\] in a continuously running loop, use the closed-form approximation from Bailey & López de Prado (the one with Euler-Mascheroni constant γ≈0.57721 \\gamma \\approx 0.57721 γ≈0.57721):

E\[max⁡Z\]≈(1−γ)Φ−1(1−1N)+γΦ−1(1−1Ne)E\[\\max Z\] \\approx (1 \- \\gamma) \\Phi^{-1}\\left(1 \- \\frac{1}{N}\\right) \+ \\gamma \\Phi^{-1}\\left(1 \- \\frac{1}{N e}\\right)E\[maxZ\]≈(1−γ)Φ−1(1−N1​)+γΦ−1(1−Ne1​)

where Z  Z  Z is standard normal. Then E\[max⁡SR\]=μ+σ⋅E\[max⁡Z\]  E\[\\max SR\] \= \\mu \+ \\sigma \\cdot E\[\\max Z\]  E\[maxSR\]=μ+σ⋅E\[maxZ\] (adjusted for your return frequency). In a running loop, **do not** let N  N  N grow unbounded with every ad-hoc test. Seed a conservative starting N  N  N (see Q3) and only increment on *formal* experiments that enter the official record. Many desks cap effective N  N  N or use a large fixed conservative value (e.g., 1,000–5,000) once the system is live to keep the gate usable.

* **PBO**: Use a **higher bar than 0.05** for discovery/exploratory work — **0.50 or even 0.60–0.70** as a soft filter combined with other gates (DSR, economic null, human review). A strict 0.05 PBO cutoff is too aggressive for small-n options flow data and will kill almost everything. Round 1 sources varied because 0.05 is more appropriate for confirmatory testing; in ongoing research loops you tolerate more uncertainty and rely on the portfolio of gates \+ human judgment.  
* **CPCV config**: For \~hundreds of observations with overlapping hold horizons, use a **modest design**: N=4 N=4 N=4 to 6 6 6 groups, k=1 k=1 k=1 or 2 2 2 test groups per path. This keeps combinatorial explosion manageable while still giving multiple paths. Embargo: **at least the maximum outcome horizon \+ buffer** (e.g., 2–5 trading days or event-based around earnings/Fed). Because your data is discrete alerts rather than continuous bars, implement purging at the *alert fire-time \+ outcome window* level (no two alerts whose outcome periods overlap should be in train and test for the same path). Test sensitivity to these choices.  
* **MinTRL / MinBTL**: For detecting a **5pp WR improvement** over 22.7% breakeven (i.e., moving toward \~27–28% WR) in data with realistic options skew/kurtosis, **n-in-the-hundreds per cohort is marginal to insufficient** under frequentist per-cohort gates after deflation. MinTRL formulas (Bailey/LdP) will often demand several hundred to low thousands of observations for reliable power on a small edge in noisy, fat-tailed data. This is why you need the power fixes in Q4.  
* **Hansen SPA**: Use **economic PnL per trade (or per alert)** net of your realistic slippage model as the loss differential. Not raw MAE or binary win/loss. This aligns the test with what actually hits your P\&L.

**3\. Global N-trials counter — practical seeding**

Prior informal/ad-hoc backtests and cross-LLM rounds **do count** toward multiple testing. Real shops bound this by documenting a “effective number of tests” that includes all prior documented search (even if informal) plus a buffer for future exploration. They often start with a conservative seed (e.g., 100–300 reflecting prior work) rather than trying to count every prompt ever run.

**Recommended seeding for you**: Start with **N \= 200–400** (conservative estimate of documented prior ad-hoc \+ 4-LLM rounds \+ buffer). Then increment *only* on formal experiments that are logged in MLflow with full config and enter the official record. Do not let every LLM pattern-mining query increment it. This keeps DSR from being falsely deflated into uselessness while still applying a meaningful correction. Update the seed once, document the rationale in your audit log, and move forward. Real desks do something similar — they do not pretend prior human/LLM exploration never happened.

**4\. Power reality check**

**After honest deflation, a solo operator can realistically afford to test only a handful of serious, well-formed hypotheses per quarter** (realistically **5–15 max**, heavily pre-filtered) against an n\~hundreds DB before almost nothing clears the combined gates. Per-cohort frequentist gates at your sample sizes will clear very little once you apply DSR \+ PBO \+ CPCV \+ economic null \+ human review.

**Phase 2 internal-mining is under-powered if done per-cohort frequentist.** You must pool across similar cohorts (or use hierarchical / empirical Bayes / shrinkage methods) for discovery. Treat the broader alert\_outcomes.db as the population and use cohort-specific results only for final validation on higher-powered slices. This is the single biggest practical adjustment needed. Many desks in similar small-edge, noisy domains do exactly this: broad hierarchical modeling for idea generation \+ strict per-candidate validation on the best candidates only.

**5\. Phase 0 decay-monitor design — is the rule right?**

The overall structure (rolling windows \+ CI lower bound \< breakeven) is directionally correct and better than most retail systems, but it has two practical weaknesses for continuous monitoring of the same signals:

* **Fixed-n CIs on rolling windows suffer from optional stopping / multiple testing bias** when you re-check the same signal daily. A noise streak can push the lower bound below breakeven temporarily even if the signal is still good. Real desks rarely kill on a single rolling CI breach.  
* **Wilson vs Clopper-Pearson**: Wilson is often preferred for binomial proportions in moderate n; both are fine. Jeffreys is more Bayesian and can be smoother but is less common in strict production gates.

**Recommended adjustments**:

* Require **confirmation across multiple windows/metrics** (e.g., both 60d and 90d, plus recent expectancy deterioration or MFE/MAE degradation) before RETIRE\_CANDIDATE.  
* Add a **probation / confirmation period** (e.g., stays in WATCH for 2–4 weeks of additional data) before hard retirement. This prevents killing good signals on short noise streaks.  
* Consider **always-valid confidence sequences** (Howard et al. or betting-based methods) for truly continuous monitoring instead of classical fixed-n CIs. They are more robust to optional stopping.  
* Real desk retirement triggers (blunt): Almost never a single statistical rule. Typical combination: rolling performance deterioration (multiple metrics) \+ economic threshold (recent expectancy near zero or negative after costs) \+ drawdown or calibration drift \+ human review / qualitative context. They deliberately err on the side of keeping signals longer through noise because replacing a live edge is expensive. Your CI-lower-bound rule is stricter than most desks use in isolation.

**6\. What’s wrong or missing in the Phase 0/1 plan (mid-build corrections)**

**Mostly right directionally, but under-built on power and governance; slightly over-engineered on some statistical purity without adaptation to your discrete alert data.**

**Under-built (fix these):**

* **Power handling for small n**: No explicit plan for pooling, hierarchical modeling, or shrinkage across cohorts. Per-cohort frequentist gates will be too weak. Add this before Phase 2\.  
* **Internal pattern mining module**: You correctly deferred broad external sources, but you still need a lightweight, offline, local-LLM (or statistical) miner that queries alert\_outcomes.db for high-value slices and proposes a small number of falsifiable, targeted hypotheses per week. Without it, the research OS has nothing to validate.  
* **Experiment / Signal Card \+ full audit trail** (KX-style governance): Every hypothesis and experiment should produce a one-page auditable artifact with lineage, assumptions, metrics, risks, and retirement criteria. This is missing and is high-leverage for human gate \+ future debugging.  
* **Economic null calibration**: Make slippage assumptions explicit, conservative, and versioned. Test sensitivity.

**Over-engineered or at risk of being too strict:**

* Combined DSR \+ PBO \+ CPCV \+ SPA \+ MinTRL on every candidate at small n will reject almost everything unless you add pooling/hierarchical layers and slightly relax the PBO bar for discovery.  
* CPCV implementation must be adapted to alert-level discrete data with overlapping windows; naive application of equity-bar code will have leakage or low power.  
* Global N-trials if seeded too aggressively or incremented on every LLM query will make the gate impossible.

**Common mid-build mistakes that break these loops**:

* Under-estimating dependence and multiple testing (your data has regime-driven correlation across alerts).  
* Making the statistical bar so high that nothing ever ships (analysis paralysis).  
* Poor experiment tracking (MLflow helps, but you still need the governance artifact).  
* Ignoring that retirement is as important as discovery — Phase 0 is correctly prioritized.  
* Treating LLM internal mining as “free discovery” without grounding it in falsifiable claims and the same validation engine.

**Practitioner blunt summary**: Your Phase 0/1 skeleton is already more disciplined than most solo or small-team attempts. The core mistake to avoid is applying strict per-cohort frequentist gates at n\~hundreds without power fixes (pooling \+ hierarchical). Real desks in options/flow spaces build thin, borrow the statistical primitives you already chose, and use multi-metric \+ human-confirmed retirement rules rather than single CI triggers. They also spend real effort on the “what do we actually test?” filter upstream so they are not running hundreds of under-powered hypotheses.

Fix the power layer and add the lightweight internal miner \+ governance cards, and this becomes a production-grade research OS. The rest is execution and iteration on real data.

If you want concrete code sketches for the adapted CPCV wrapper, a sample Experiment Card schema, or a starter prompt \+ output format for the internal pattern miner, share the current db schema or Prefect task structure and I’ll give you copy-paste-ready pieces.

