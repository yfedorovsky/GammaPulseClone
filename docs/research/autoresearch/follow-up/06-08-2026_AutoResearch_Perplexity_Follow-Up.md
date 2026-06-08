Good — I have the precise technical details needed. This is clearly a follow-up deep-dive rather than a greenfield request, so I'll give a dense, direct technical answer (no report artifact needed per the follow-up query rule — but this is substantive enough to warrant a full structured response).

This is a **Phase 0 \+ Phase 1 build-session deep-dive**, not a greenfield question. Here's the implementation-specific guidance covering exact library APIs, wiring decisions, schema design, and the non-obvious gotchas for each component.

---

## **Phase 0: Decay/Retirement Monitor**

## **CI Implementation**

Use statsmodels.stats.proportion.proportion\_confint — it handles Wilson, Clopper-Pearson, and Agresti-Coull via a single method= parameter:

python

`from statsmodels.stats.proportion import proportion_confint`

`def compute_ci(wins: int, n: int, method: str = "wilson") -> tuple[float, float]:`  
    `"""Returns (lower, upper) 95% CI. Use method='beta' for Clopper-Pearson."""`  
    `return proportion_confint(count=wins, nobs=n, alpha=0.05, method=method)`

For your regime-split cohorts where n is small (30–80), Wilson and Clopper-Pearson behave differently: Clopper-Pearson (method='beta') is conservative (guaranteed ≥95% coverage, wider intervals), Wilson is accurate for p near 0.15. **Recommendation: compute both; use Wilson for WATCH triggers (higher sensitivity), Clopper-Pearson for RETIRE\_CANDIDATE (conservative, protective against premature retirement).** SciPy's binomtest(...).proportion\_ci(method='exact') also delivers Clopper-Pearson if you already have scipy in the stack.

## **Rolling Window Design**

The non-obvious decision: rolling by *calendar days* vs. *alert-firing count*. Calendar-day rolling (60d/90d) measures temporal staleness; firing-count rolling (last 60 alerts) measures statistical stability. You want **both**: an alert that fired 60 times in the last 90 days has more statistical power than one that fired 5 times in 60 days. Implement:

python

*`# alert_outcomes.db schema addition`*  
`-- Add to query:`   
`SELECT signal_type, regime_bucket, COUNT(*) as n,`  
       `SUM(CASE WHEN verdict='WIN' THEN 1 ELSE 0 END) as wins,`  
       `MIN(fire_ts) as window_start, MAX(fire_ts) as window_end`  
`FROM alert_outcomes`  
`WHERE fire_ts >= datetime('now', '-90 days')`  
`GROUP BY signal_type, regime_bucket`  
`HAVING n >= 20  -- suppress noise below min sample`

The regime\_bucket column (VIX-tier × GEX-sign × earnings\_proximity\_flag × opening\_vs\_closing) is the key grouping. If you don't already have it materialized as a single categorical column, add it as a computed column now — it's the join key for every downstream query.

## **Verdict State Machine**

text

`HEALTHY      → lower_CI >= breakeven (0.227)`  
`WATCH        → lower_CI < breakeven AND n < 60`  
`RETIRE_CANDIDATE → lower_CI < breakeven AND n >= 60`  
`RETIRED      → human confirms (write flag, freeze in MLflow)`

The n \>= 60 guard on RETIRE\_CANDIDATE prevents premature retirement on thin cohorts. Never auto-retire without the human gate — this is already in your rules.

---

## **Phase 1: Validation/Deflation Engine**

## **pypbo: What It Actually Gives You**

pypbo (MIT, GitHub esvhd/pypbo) is a flat-API library, no class hierarchy. Key calls:

python

`import pypbo as pbo`  
`import pypbo.perf as perf`  
`import numpy as np`

*`# PBO via CSCV: pass a T×N DataFrame of strategy returns`*  
*`# (rows = time periods, columns = strategy variants)`*  
`S = 16  # partitions; Bailey et al. recommend S=16 for T≥500`  
`metric = lambda x: np.sqrt(252) * perf.sharpe_iid(x)`  
`result = pbo.pbo(returns_df, S=S, metric_func=metric,`  
                 `threshold=0, n_jobs=4, plot=False)`  
`print(result.pbo)  # scalar [0,1]: prob of overfitting`

*`# Deflated Sharpe Ratio`*  
*`# args: observed_SR, T (obs), skewness, kurtosis, N_trials`*  
`dsr_stat = perf.dsr(sr_hat=0.8, t_obs=252, skew=-0.5,`   
                    `ex_kurtosis=2.0, sr_benchmark=0.0,`  
                    `n_trials=global_n_trials)  # <-- global counter here`

*`# MinTRL: minimum observations for SR to be significant`*  
`min_trl = perf.min_track_record_length(`  
    `sr=sr_hat, sr_benchmark=0.0, alpha=0.05, t_obs=T`  
`)`

**Critical wiring note**: n\_trials in the DSR call is your **global counter** — the total number of strategies ever evaluated in the loop, not just the current strategy's variants. Store this in MLflow as a run\_tag on a dedicated global\_state experiment, and read it before every DSR computation.

## **mlfinlab CPCV: The Purging/Embargo Parameters**

The mlfinlab CombinatorialPurgedKFoldCV class requires t1 (a pandas Series where index \= observation start time, values \= observation end time) to implement purging correctly. For options flow alerts:

python

`from mlfinlab.cross_validation.combinatorial import CombinatorialPurgedKFoldCV`

*`# t1: index = alert fire_ts, value = label-formation end (e.g. fire_ts + 1 trading day)`*  
`t1 = pd.Series(`  
    `data=alert_df['fire_ts'] + pd.Timedelta('1D'),`  
    `index=alert_df['fire_ts']`  
`)`  
`cv = CombinatorialPurgedKFoldCV(`  
    `n_splits=6,          # N groups; 6 is practical for n~200`  
    `n_test_splits=2,     # k test groups per split`  
    `pct_embargo=0.01     # 1% embargo ≈ ~2 trading days for daily labels`  
`)`

**Purge gap sizing for your context**: your label window is 1h/EOD/next-day. For next-day labels, the purge gap should be at least 1 trading day; for 1h labels, purge by 1h (express as fractional trading day). The pct\_embargo is a fraction of total T, so for \~200 observations: 0.01 × 200 \= 2 observations embargo — appropriate. For high-VIX regimes where serial correlation in alerts is higher, consider 2% embargo.

A lightweight standalone CPCV alternative if mlfinlab has dependency issues:

python

*`# ~50-line pure numpy/pandas implementation from gist.github.com/quantra-go-algo`*  
*`# No mlfinlab dependency. Good for initial phases.`*  
`from itertools import combinations`  
*`# (see cpcv_generator in web:175 for full implementation)`*

## **arch.bootstrap.SPA: Wiring vs. SOE-A Baseline**

The SPA test asks: "Does any alternative strategy significantly outperform the benchmark?". The correct setup for your system:

python

`from arch.bootstrap import SPA`  
`import numpy as np`

*`# losses array convention: SMALLER IS BETTER`*  
*`# Use negative returns as losses (or squared error if doing regression)`*  
`benchmark_losses = -soe_a_returns  # SOE-A is the benchmark`  
`alt_losses = np.column_stack([`  
    `-strategy_a_returns,`  
    `-strategy_b_returns,`  
    `# ... all candidate strategies`  
`])`

`spa = SPA(`  
    `benchmark=benchmark_losses,`  
    `models=alt_losses,`  
    `block_size=10,   # ~sqrt(T); tune to autocorrelation in your returns`  
    `reps=1000,`  
    `bootstrap='stationary'  # correct for autocorrelated options flow returns`  
`)`  
`spa.seed(42)`  
`spa.compute()`

*`# Three p-values: use 'consistent' for balanced sensitivity`*  
`print(spa.pvalues)  # {'lower': ..., 'consistent': ..., 'upper': ...}`

**Key nuance**: SPA uses *loss arrays*, not returns. If your strategy returns are non-overlapping (each observation is a clean alert outcome), block\_size=1 is valid. If alerts can fire in close temporal succession (serial correlation), set block\_size to the autocorrelation lag of your outcome series — empirically test with statsmodels.graphics.tsaplots.plot\_acf on your alert\_outcomes.db outcome series first.

The three p-values from spa.pvalues have this semantic:

* **upper**: conservative; treats all models as potential alternatives (never recenters)  
* **consistent**: correct for your use case — recenters models only if they're close to the null  
* **lower**: anti-conservative; use only for diagnostics, never for gates

Gate criterion: reject a candidate signal if spa.pvalues\['consistent'\] \> 0.05 (fails to beat SOE-A at 95% confidence).

## **Global N-Trials Counter: Implementation**

This is where most solo implementations quietly fail. Use MLflow tags on a singleton run:

python

`import mlflow`

`GLOBAL_STATE_EXPERIMENT = "autoresearch_global_state"`  
`GLOBAL_STATE_RUN_NAME = "n_trials_counter"`

`def increment_n_trials(n: int = 1) -> int:`  
    `client = mlflow.tracking.MlflowClient()`  
    `exp = client.get_experiment_by_name(GLOBAL_STATE_EXPERIMENT)`  
    `runs = client.search_runs(exp.experiment_id,`   
                               `filter_string=f"run_name = '{GLOBAL_STATE_RUN_NAME}'")`  
    `current = int(runs[0].data.tags.get("n_trials", 0)) if runs else 0`  
    `new_val = current + n`  
    `if runs:`  
        `client.set_tag(runs[0].info.run_id, "n_trials", str(new_val))`  
    `return new_val`

MLflow tags are string key-value pairs on a run — they're mutable, persistent, and readable without downloading artifacts. This is the correct level of persistence (not a metrics log, which is append-only).

## **MinBTL vs. MinTRL: The Distinction**

pypbo.perf.min\_track\_record\_length computes **MinTRL** — the minimum OOS observations for a *given* SR to be statistically significant. **MinBTL** (minimum backtest length) is the dual: the minimum in-sample length before the backtest is meaningful at all, accounting for selection bias from N trials. Your system needs both:

* **MinTRL at shadow-deploy**: How many more live observations before a shadow-mode signal can be promoted? For SOE-A tier (target WR \~25%, breakeven 22.7%, at 3.4:1 R:R), MinTRL at α=0.05 is roughly 180–250 observations depending on return distribution skewness.  
* **MinBTL before backtest is valid**: At N=50 trials in the global counter, MinBTL ≈ 600–800 trading-day observations (Bailey et al. 2016 formula). Your ThetaData replay for 2020–2025 gives \~1,300 trading days — comfortably above MinBTL for moderate N. As N grows into the hundreds, MinBTL grows — track it.

---

## **Schema and MLflow Experiment Design**

The cleanest organization for your use case:

| MLflow Experiment | Purpose | Key logged params |
| :---- | :---- | :---- |
| phase0\_decay\_monitor | Weekly CI snapshots | signal\_type, regime\_bucket, n, win\_rate, ci\_lower\_wilson, ci\_lower\_cp, verdict |
| phase1\_validation | Per-hypothesis backtest results | hypothesis\_id, n\_trials\_at\_eval, dsr\_score, pbo, spa\_pvalue\_consistent, min\_trl, regime\_splits |
| signal\_library | Canonical validated signals | Stage: shadow → validated → retired; tag: retire\_reason |
| autoresearch\_global\_state | Global counters | tag: n\_trials |

The signal\_library experiment should use MLflow's **Model Registry staging** (the stage field: None → Staging → Production → Archived) as a proxy for your shadow→human→ship→retire pipeline. This gives you a UI-visible state machine at zero extra code.

---

## **Prefect Orchestration Wiring**

Prefect's @flow / @task decorator model maps cleanly to your pipeline stages:

python

`from prefect import flow, task`  
`from prefect.schedules import CronSchedule`

`@task(retries=2, retry_delay_seconds=60)`  
`def compute_decay_verdicts() -> pd.DataFrame:`  
    `# queries alert_outcomes.db, computes Wilson + CP CIs`  
    `...`

`@task`  
`def log_verdicts_to_mlflow(df: pd.DataFrame):`  
    `# logs to phase0_decay_monitor experiment`  
    `...`

`@task`  
`def emit_retire_candidates(df: pd.DataFrame) -> list[str]:`  
    `return df[df['verdict'] == 'RETIRE_CANDIDATE']['signal_type'].tolist()`

`@flow(name="phase0-decay-monitor")`  
`def decay_monitor_flow():`  
    `df = compute_decay_verdicts()`  
    `log_verdicts_to_mlflow(df)`  
    `candidates = emit_retire_candidates(df)`  
    `if candidates:`  
        `# write to a watch table / send notification`  
        `...`

Prefect Cloud's free tier (Hobby: 2 users, free usage tier, \~18,500 GitHub stars) is sufficient for Phase 0 \+ Phase 1\. Self-hosted is free under Apache 2.0. Cloud overhead is under $0.01/task invocation at modest volume. Workers execute in your infrastructure — Prefect never touches alert\_outcomes.db or ThetaData.

**Scheduling recommendation**: Phase 0 (decay monitor) runs weekly, Sunday pre-open. Phase 1 (validation engine) runs on-demand, triggered by a hypothesis being promoted from the queue, not on a schedule — this prevents the loop from running backtests just because the clock says so, which is a subtle form of data snooping.

---

## **Non-Obvious Gotchas for Your Specific System**

1. **Outcome label leakage with regime features.** Your fire-time context columns (VIX, GEX, IVR) are contemporaneous with the alert fire — they're valid features. But *post-fire* regime shifts (VIX spike after alert fires) must never appear as features for a signal tested on that alert's forward return. The purging in CPCV handles temporal leakage between train/test splits, but it does not handle feature-time leakage within a single observation. Verify your feature extraction uses only fire-time state, not anything from the outcome window.  
2. **The opening-vs-closing cohort split halves your effective n.** At n=134 for SOE A, splitting by opening/closing flow gives \~67 per cohort before further regime splits. CPCV with N=6 groups on 67 observations has low statistical power. For this cohort specifically, use the simpler Wilson CI gate (Phase 0\) before running full CPCV (Phase 1). Only run CPCV on the merged cohort or the larger sub-cohort until you accumulate more observations.  
3. **pypbo's pbo() function expects non-overlapping returns per column.** If your backtest generates overlapping returns (e.g., next-day verdict for alerts that fire intraday), you need to de-overlap (take every-other observation, or aggregate to non-overlapping windows) before feeding into PBO. Overlapping returns inflate apparent consistency and understate PBO.  
4. **SPA block\_size matters a lot for flow data.** Options flow alerts on the same ticker cluster in time (whale accumulation events fire multiple signals within hours). Test your outcome series autocorrelation explicitly; for a block\_size that's too small, SPA will reject the null too readily (false positives). arch defaults to sqrt(T) if you don't specify — for T=134, that's block\_size=11.6 ≈ 12, which is likely too large for daily outcomes. Start with block\_size=3–5 and check sensitivity.  
5. **MLflow's Model Registry "staging" doesn't fire webhooks on state changes by default.** If you want automated notifications when a signal reaches RETIRE\_CANDIDATE in the registry, implement a thin polling task in Prefect that checks for stage changes and emits to your notification channel. Don't rely on MLflow push semantics.

This is a dense engineering-plus-statistics answer. Covering all six questions in full implementation detail.

---

## **Q1: Fork-vs-Build — Confirmed with Module-Level Precision**

**The "build thin, borrow ideas" decision is correct.** The reasons are structural:

* **RD-Agent** (github.com/microsoft/RD-Agent, MIT) is tightly coupled to Qlib's data model (QlibFactorScenario, Alpha158, LGBModel). The scenario path rdagent/scenarios/qlib/experiment/factor\_experiment.py is where every backtest runner, factor evaluator, and feedback loop resolves — none of it can be extracted without carrying the entire Qlib dependency tree. The validation signal is IC/ICIR on daily cross-sectional returns; your validation signal is a binary WIN/LOSS on options alert outcomes. Incompatible at the ground floor.  
* **AlphaAgent** (github.com/RndmVariableQ/AlphaAgent, follows RD-Agent MIT) explicitly states it "follows the implementation of RD-Agent" and its issue tracker is alive as of April 2026\. This creates the same Qlib coupling: QlibFactorCoSTEER, QlibFactorRunner, QlibFactorExperiment2Feedback are all in the critical path.

## **What IS Worth Vendoring Verbatim (or Near-Verbatim)**

**Vendor these — they are self-contained, dependency-light, and directly applicable:**

| Module | Source path | What it does | Coupling risk |
| :---- | :---- | :---- | :---- |
| AST novelty gate | AlphaAgent paper §3.2.1, code at github.com/RndmVariableQ/AlphaAgent | Pairwise subtree isomorphism similarity metric; rejects factors if S(f) \= max\_φ s(f,φ) exceeds threshold | None — pure Python ast stdlib \+ \~80 lines |
| Complexity control | Same paper §3.2.2 | Counts AST node depth \+ free parameters; rejects over-complex expressions | None |
| Hypothesis-factor alignment scorer | AlphaAgent §3.2.2, Eq. 7 | LLM consistency scoring C(h,d,f) \= α·c₁(h,d) \+ (1-α)·c₂(d,f) | Requires one LLM call; no Qlib dependency |
| Knowledge-forest pattern | RD-Agent docs, rdagent/core/knowledge\_base.py | Dict-backed store of (hypothesis → outcome) pairs with retrieval; conceptually a key-value store with cosine-similarity lookup | Pure Python; extract the interface, not the Qlib-specific subclass |
| Research/Dev/Feedback loop split | RD-Agent architecture | Abstract separation of Propose → Implement → Evaluate → Feedback stages | Borrow the *pattern*; implement as 3 Prefect flows |

**Do NOT vendor:**

* rdagent/scenarios/qlib/\* — 100% Qlib-coupled  
* rdagent/components/coder/factor\_coder/ (Co-STEER) — assumes the evaluator returns IC/ICIR; your evaluator returns WIN/LOSS binary outcome \+ MFE/MAE  
* mlfinlab.cross\_validation.combinatorial — see Q2 below on maintenance

## **The AST Gate Adapted for Your Context**

Your "factor expressions" are detector parameterizations (regime filter settings, threshold values, window sizes), not symbolic math trees. The AST gate ports cleanly if you define your signals as Python expression strings (e.g., "vix \> 20 and gex \< 0 and sweep\_score \> threshold"), parse them with the stdlib ast module, and compute pairwise subtree isomorphism against your existing validated signal zoo. This is \~120 lines and zero external dependencies.

---

## **Q2: Exact Thresholds Locked for Your Situation**

## **DSR: Confidence Cutoff and E\[max SR | N\]**

**Cutoff**: Use 0.95 (p ≥ 0.95 required to accept). For a solo operator with no regulatory floor, 0.90 is permissible for WATCH promotion but never for shadow-deploy.

**E\[max SR | N\] formula**: Bailey & López de Prado (2014) derive it via the expected maximum of a half-normal distribution:

E ⁣\[max⁡nSR^n\]≈(1−γ)Φ−1 ⁣(1−1N)+γ Φ−1 ⁣ ⁣(1−1N⋅e)

*E*\[

*n*

max

​

*SR*

*n*

​

\]≈(1−*γ*)Φ

−1

(1−

*N*

1

​

)+*γ*Φ

−1

(1−

*N*⋅*e*

1

​

)

where 

γ≈0.5772

*γ*≈0.5772 is the Euler–Mascheroni constant and 

Φ−1

Φ

−1

 is the standard normal quantile function. The Python one-liner (no special library needed):

python

`import numpy as np`  
`from scipy.stats import norm`

`def expected_max_sr(N: int, annualized: bool = True) -> float:`  
    `gamma = 0.5772156649`  
    `sr = (1 - gamma) * norm.ppf(1 - 1/N) + gamma * norm.ppf(1 - 1/(N * np.e))`  
    `return sr * np.sqrt(252) if annualized else sr`

For a **continuously running loop**, N increments with every hypothesis evaluated — even rejected ones, even failed backtests. At N=10, E\[max SR\] ≈ 1.08 annualized; at N=50, ≈ 1.51; at N=100, ≈ 1.73; at N=200, ≈ 1.96. This means that once you've run 50 auto-backtests, a candidate needs an *annualized SR above 1.5* just to pass the DSR gate at 95% confidence — before any skewness/kurtosis correction. With fat-tailed options returns (negative skew, leptokurtosis), the denominator of the DSR grows further, making the gate even stricter. López de Prado has shown that as few as 3 trials on a 10-year daily-return backtest suffice to make most strategies "likely false" under DSR — with options microstructure data and n-in-hundreds, this constraint is binding by N=20.

## **PBO: The Correct Cutoff — 0.5, Not 0.05**

This is the source of the Round 1 confusion. The two numbers mean completely different things:

* **PBO is a probability, not a p-value.** It estimates the probability that the best in-sample strategy underperforms the median OOS strategy.  
* **The reject threshold is PBO \> 0.5**, meaning: "more likely than not, the observed optimum is overfitted." This is analogous to a coin flip — you reject if the loop is no better than chance at identifying the true best strategy.  
* The 0.05 threshold that appears in Round 1 sources refers to the **p-value from a DSR test** or a binomial significance test on win rate — completely different quantity.

Practical implication: with n\~200 and S=8 partitions (appropriate for this sample size), PBO \> 0.5 is a coarse but honest gate. PBO values between 0.3–0.5 are in a "borderline" zone where the signal may have weak edge but the backtest is not robustly identifying it.

**Recommended PBO config for your data:**

python

`import pypbo as pbo`

*`# For n~200 observations, S=8 is correct (not 16)`*  
*`# S=16 is appropriate for T≥500; S=8 for T~200`*  
`result = pbo.pbo(returns_df, S=8, metric_func=your_metric,`   
                 `threshold=0, n_jobs=1, plot=False)`  
*`# Reject if result.pbo > 0.5`*

## **CPCV: Concrete Config for Your Data**

For n\~200 observations with 1h/EOD/next-day overlapping label horizons:

python

*`# Recommended config`*  
`n_splits = 6        # N groups: use 6, not 8 or 10, for n~200`  
`n_test_splits = 2   # k: 2 test groups per partition is standard`  
`pct_embargo = 0.02  # 2% = ~4 observations; covers next-day label overlap`

*`# Effective train size per split: ~133 obs; test per split: ~67 obs`*  
*`# Total number of paths: C(6,2) = 15 — sufficient for PBO estimation`*

The 2024 empirical study confirms CPCV markedly outperforms walk-forward in reducing PBO and delivering more favorable deflated SR statistics across synthetic market environments including regime-switching models. However, the specific finding that matters for you: **Purged-Fold K-Fold performs similarly to CPCV in some configurations**, and the paper flags "caution when selecting Purged-Fold K-F" for production use. Stick with full CPCV.

**Critical**: for 1-hour labels, embargo must cover at least the autocorrelation horizon of your outcome series. Run statsmodels.graphics.tsaplots.plot\_acf on your verdict binary series; if autocorrelation is significant at lag 2–3 (common for options flow on the same ticker), increase pct\_embargo to 0.03.

**mlfinlab maintenance reality**: The public open-source mlfinlab on GitHub (hudson-and-thames/mlfinlab) targets Python 3.6–3.7 and does not support Python 3.12 (issue \#544, filed July 2024, no resolution). The current maintained version is now **behind a £100/month paywall** via Hudson & Thames. The free GitHub repo is at v0.12.3, pinned to pandas==1.0.4 and numpy==1.18.5 — dependency conflicts with any modern stack are near-certain.

**Recommendation**: Vendor the CPCV implementation directly from the standalone gist (gist.github.com/quantra-go-algo/4540a0eea81a8693998bfc007ad427e5) or the quantbeckman implementation — both are \~100 lines of pure pandas/numpy CPCV, no mlfinlab dependency, compatible with any Python 3.10+. This is explicitly what the community has converged on.

## **MinTRL / MinBTL: Is n-in-Hundreds Enough?**

Short answer: **barely, and only at the pooled cohort level. Per-cohort at n\~60 after regime splits, you cannot make frequentist power claims.**

For detecting a 5pp improvement (22.7% → 27.7%) over your 3.4:1 R:R breakeven, treating the outcome as Bernoulli with p₀=0.227, p₁=0.277:

Using the arcsine-transformed binomial sample size formula at 80% power, α=0.05 one-sided:

n≈(z0.05+z0.20)2(2arcsin⁡ ⁣p1−2arcsin⁡ ⁣p0)2≈(1.645+0.842)2(2arcsin⁡(0.527)−2arcsin⁡(0.476))2

*n*≈

(2arcsin

*p*

1

​

​

−2arcsin

*p*

0

​

​

)

2

(*z*

0.05

​

\+*z*

0.20

​

)

2

​

≈

(2arcsin(0.527)−2arcsin(0.476))

2

(1.645+0.842)

2

​

This works out to approximately **n ≈ 480–550 at 80% power, n ≈ 650–750 at 90% power** (arcsine Cohen h ≈ 0.11, a very small effect). Your current n=134 for SOE A has power of approximately **20–25%** for detecting a 5pp improvement — you will miss real improvements 75–80% of the time. This is the single most important quantitative fact for Phase 1\.

**Implications:**

* Per-cohort frequentist testing is statistically underpowered at n\<400 for detecting 5pp. The n≥200 shadow-deploy rule will promote or retire signals with correct probabilities barely above chance.  
* You must either pool across cohorts (hierarchical model) or use a Bayesian shrinkage prior — see Q4.

**MinBTL** at N=20 global trials requires \~600 trading days of backtest history to be meaningful (Bailey et al.'s MinBTL formula grows as \~ln(N) × T\_required). Your ThetaData historical data from 2020–2025 gives \~1,300 trading days — you are above MinBTL for N\<50. Once the loop has run 100+ backtests, MinBTL will require effectively your full data history, making incremental discovery nearly impossible at frequentist confidence levels.

## **Hansen SPA: The Right Loss Differential**

**Use per-trade economic PnL (in R-multiples or dollar terms), not raw returns or MAE.** The SPA is testing whether *any* model's loss differential against the benchmark is positive in expectation across bootstrap samples. For binary outcomes at known R:R:

python

*`# Per-trade economic PnL in R-multiples`*  
*`# WIN=+3.4R, LOSS=-1R (your 3.4:1 R:R), FLAT=0`*  
`def economic_pnl(verdict, r_multiple=3.4):`  
    `return np.where(verdict == 'WIN', r_multiple,`   
           `np.where(verdict == 'LOSS', -1.0, 0.0))`

*`# Loss differential for SPA (SPA convention: smaller loss = better)`*  
`benchmark_pnl = economic_pnl(soe_a_verdicts)`  
`candidate_pnl = economic_pnl(candidate_verdicts)`  
`benchmark_losses = -benchmark_pnl   # negate: SPA minimizes loss`  
`candidate_losses = -candidate_pnl`

**Do NOT use MAE** — maximum adverse excursion captures a different dimension (path risk during trade) and is not the natural loss for a binary-outcome signal system. Do NOT use raw spot return — it conflates the signal's conviction with position sizing.

**block\_size caveat**: For your options flow data where alerts cluster temporally (whale accumulation events fire multiple signals in sequence), test autocorrelation explicitly. Start with block\_size=5 and run sensitivity at 3, 5, 10\. SPA results are sensitive to this parameter when n\<200.

---

## **Q3: Global N-Trials Counter — Seeding**

**The honest answer from López de Prado's own framing**: N should count "any decision to evaluate a strategy in any form" — including LLM-assisted hypothesis generation rounds where you mentally or explicitly tested whether a pattern exists. The 2021 tweet showing DSR collapse at N=3 is not hyperbole: with a 10-year backtest, even 3 trials makes most SR=1.0 strategies "likely false" under DSR.

**Practical seeding recommendation:**

| Prior activity | Count as N? | Reasoning |
| :---- | :---- | :---- |
| Formal backtests with recorded metrics | Yes, always | Each is a trial |
| Ad-hoc regime queries on alert\_outcomes.db with outcome inspection | Yes, if you used the result to decide anything | Counts as testing |
| Cross-LLM synthesis rounds (your 4 rounds) | Yes — count as approximately 5–10 each | LLM rounds inspect data implicitly through your framing |
| Signal design choices made before alert\_outcomes.db existed | Judgment call: count 1 per signal type shipped | Conservative |
| Shadow-mode monitoring without any parameter change | No — no selection decision made | Pure observation |

**Recommended seed**: Start with N \= max(50, count of all backtests you can document \+ 10 per LLM synthesis round). If you cannot reconstruct this, N=100 is a conservative but defensible floor that acknowledges significant prior informal search. The cost of over-seeding N is that your DSR gate becomes stricter; the cost of under-seeding is manufacturing false discoveries. Under-seeding is the asymmetric failure.

**How real shops bound N**: Institutional quant desks cap N by *research budget* rather than true trial count. A standard approach is to assign each research project a "trials budget" (e.g., 50 trials per signal family), track exhaustion, and retire the family when the budget is consumed — forcing researchers to write new hypotheses rather than continuing to tweak parameters. For your system, the equivalent is: per cohort-type (e.g., "multi-strike cluster in high-VIX"), assign a budget of 30 trials. Once exhausted, the cohort's signal family is frozen until new data accumulates.

---

## **Q4: Power Reality Check — Can Phase 2 Internal Mining Actually Work?**

**The honest verdict: frequentist per-cohort testing at n\~60–134 is structurally underpowered for 5pp detection. Phase 2 internal mining requires a different statistical framework to produce valid decisions.**

With N=50 global trials, the DSR gate requires \~SR\>1.5 annualized, which at n\~200 observations corresponds to detecting win-rate improvements of \~8–10pp above breakeven at 95% confidence — far above what you're targeting (5pp). With n\~60 per cohort after regime splits, even the Wilson CI gate has ±10–12pp width, meaning you cannot distinguish 22.7% from 32.7% reliably.

**The correct solution is Bayesian partial pooling (hierarchical model).** This is not a theoretical nicety — it's the only approach that makes coherent decisions with your sample sizes:

python

`import pymc as pm`  
`import numpy as np`

*`# Hierarchical beta-binomial model for win rate across regime cohorts`*  
*`# Partial pooling: each cohort shrinks toward the global mean`*  
`with pm.Model() as hierarchical_model:`  
    `# Hyperprior on the global win rate`  
    `mu_logit = pm.Normal('mu_logit', mu=0, sigma=1)`  
    `sigma_cohort = pm.HalfNormal('sigma_cohort', sigma=0.5)`  
      
    `# Per-cohort win rates (partial pooling)`  
    `logit_p = pm.Normal('logit_p', mu=mu_logit, sigma=sigma_cohort,`   
                         `shape=n_cohorts)`  
    `p = pm.Deterministic('p', pm.math.invlogit(logit_p))`  
      
    `# Likelihood`  
    `wins = pm.Binomial('wins', n=n_obs_per_cohort, p=p,`   
                        `observed=observed_wins)`  
      
    `trace = pm.sample(2000, tune=1000, return_inferencedata=True)`

*`# Decision rule: retire if P(p_cohort < breakeven) > 0.90`*  
`retire_probability = (trace.posterior['p'] < breakeven).mean(dim=['chain','draw'])`

The Stan case study on partial pooling for repeated binary trials (baseball batting averages, structurally identical to your problem) shows that no-pooling estimates are wildly noisy for n\<50, while partial pooling gives stable, well-calibrated posterior estimates even at n=20. The full-pooling case (treat all alerts as one signal) is the opposite extreme and ignores regime conditioning.

**What this means for Phase 1**: Keep Wilson CI \+ Clopper-Pearson for Phase 0 decay monitoring (they're the right tool for "is this signal currently healthy relative to its own history"). For Phase 1 hypothesis validation, replace per-cohort frequentist testing with Bayesian posterior checks: promote to shadow if P(win\_rate \> breakeven | data) \> 0.90, retire if P(win\_rate \< breakeven | data) \> 0.90.

---

## **Q5: Phase 0 Decay Monitor — Is the Rule Right?**

**The rolling CI trigger is directionally correct but has two real problems:**

## **Problem 1: Continuous Monitoring Inflates Type I Error**

You are re-checking the same signal every week with a fresh CI. This is sequential testing without sequential correction: the probability of ever falsely triggering the retirement gate is *not* 5% — it is substantially higher (empirically, 20–40% for 52 checks per year with a fixed-n CI). Wilson and Clopper-Pearson are both fixed-n procedures. They are **not** valid for "peek whenever you want."

## **The Correct Tool: Anytime-Valid Confidence Sequences**

Howard, Ramdas, McAuliffe & Sekhon (2021, *Annals of Statistics*) derive confidence sequences that are uniformly valid at all sample sizes simultaneously — you can check at any time, stop at any time, and the type-I error guarantee holds. The Python library is confseq (github.com/gostevehoward/confseq):

python

*`# pip install confseq`*  
`import confseq.boundaries as boundaries`

*`# Bernoulli confidence sequence for win rate`*  
*`# Returns lower/upper bounds valid at EVERY n, simultaneously`*  
`def get_cs_bounds(wins: int, n: int, alpha: float = 0.05):`  
    `# Using the empirical Bernstein confidence sequence`  
    `# (tighter than Hoeffding for p near 0.15)`  
    `from confseq.cs_bound import betting_cs`  
    `lower, upper = betting_cs(`  
        `x=np.array([1.0]*wins + [0.0]*(n-wins)),`  
        `alpha=alpha,`  
        `running_intersection=True,  # shrinks monotonically`  
        `estimate_fn='mean',`  
        `boundary_type='stitching'`  
    `)`  
    `return lower[-1], upper[-1]`

The 2026 JRSS-B paper "Anytime validity is free" establishes that sequential anytime-valid tests can be constructed to exactly match fixed-n tests at their endpoint, with no power loss at the final N — making the sequential version strictly dominant for a monitoring system. A 2025 CRAN package avseqmc implements anytime-valid binomial bounds specifically.

**However**: implementing confseq correctly requires choosing a "target N" (the maximum expected observations), which is your shadow-mode ObsCount target (n=200). This is a design parameter, not a free parameter.

## **Wilson vs. Clopper-Pearson vs. Jeffreys for Retirement**

For the specific decision of retirement (where false positives \= prematurely retiring a healthy signal), **Jeffreys prior interval** (Beta(0.5, 0.5) prior) is the best-calibrated at small n for a balanced false-positive/false-negative tradeoff. Wilson is slightly anti-conservative (coverage \< 95% for n\<30 near p=0.15), Clopper-Pearson is conservative (guaranteed ≥95%, wider). The practical difference for your actual decision:

* **Phase 0 WATCH trigger**: Use Wilson (sensitive, accepts false WATCH at low n)  
* **Phase 0 RETIRE\_CANDIDATE trigger (pre-human gate)**: Use Jeffreys or Clopper-Pearson (conservative, protect against false retirement)  
* **Continuous monitoring loop**: Replace both with confseq (sequentially valid)

## **What Desks Actually Use**

The institutional practice, per the options desk context: most systematic desks use a rolling "signal dashboard" that triggers **human review** (not auto-retirement) when the rolling performance crosses a threshold — the final retirement decision is always human. The threshold is typically: "if the last 90-day Sharpe is negative at the 95% Clopper-Pearson lower bound, add to watchlist." Auto-retirement without a human gate is almost never done in production because of the non-stationarity risk (a signal can look dead for 60 days and recover in a regime change). Your current design — RETIRE\_CANDIDATE → human gate → RETIRED — is exactly the institutional pattern. Keep it.

---

## **Q6: What's Wrong or Missing in Phase 0/1**

## **Three Highest-Confidence Corrections to Apply Mid-Build**

**Correction 1: Replace fixed-n CIs in Phase 0 with confseq anytime-valid bounds (or at minimum, apply Bonferroni correction for K weekly checks)**

The current rolling Wilson CI with weekly re-check is statistically invalid for sequential monitoring. The cheapest fix that doesn't require confseq: multiply your α by K (Bonferroni) where K is the number of times you'll check per signal lifetime. If you check weekly for 6 months, K=26, so use α=0.05/26≈0.002 — meaning you need a 99.8% CI before triggering RETIRE\_CANDIDATE. This is conservative but valid. The better fix is confseq, which is maintained, MIT licensed, and has \~200 lines of Python with a full interface.

**Correction 2: Replace per-cohort n≥200 frequentist promotion gate with Bayesian partial pooling for hypothesis validation**

The n≥200 gate is statistically insufficient to detect a 5pp improvement (requires \~500+ observations at 80% power). Any signal that clears the gate at n=200 has cleared it with \~25% power — you're missing real improvements 75% of the time. Add a pymc hierarchical beta-binomial model that pools across regime cohorts with a shared hyperprior. This is not optional complexity — it is the correct statistical framework for your data structure (multiple sparse binary outcomes grouped by regime). Use PyMC (Apache 2.0, actively maintained, Python 3.10+ compatible).

**Correction 3: Seed N-trials counter at ≥50 and lock the DSR denominator formula before running any auto-backtests**

Without this, the first 20 auto-backtests will produce DSR scores computed against N\<20, making most signals look far more significant than they are. Once signals are shadow-deployed on incorrect DSR estimates, removing them requires acknowledging a statistical error — organizational friction. The fix: set n\_trials \= 50 in the MLflow global state record on day one of Phase 1, before running any backtests. Increment it with every hypothesis evaluated thereafter, even failed or rejected ones. Document the initial seed value and the reasoning in MLflow as a note artifact — this is your audit trail if you need to defend the gate calibration later.

## **Other Issues in the Plan**

* **The phase 1 "shadow → human → ship at n≥200" rule** ships at 25% power. Either raise to n≥500 (impractical — 18–24 months of accumulation) or accept the power limitation explicitly and document it as a design constraint, not a quality guarantee. Consider framing it as: "n≥200 is the minimum for a Bayesian posterior to stabilize, not a frequentist significance claim."  
* **Hansen SPA against the "SOE-A baseline"** is the right test, but only if SOE A has sufficient observations (n≥200) to provide a stable benchmark return distribution. Below that, the bootstrap distribution of the benchmark is itself unreliable, and SPA p-values are inflated.  
* **CPCV with mlfinlab**: Do not use. Vendor the standalone implementation directly. The library pins to numpy==1.18.5 — dependency conflicts with PyMC, arch, or any modern stack are near-certain.  
* **pypbo maintenance**: pypbo (github.com/esvhd/pypbo) tests on Python 3.7–3.10; no CI confirmation for 3.12. It runs correctly on Python 3.10 as of the last community checks. Use Python 3.10 for Phase 1 if you want pypbo without vendoring.

