This is an exceptionally disciplined architecture. By building a thin layer over your existing alert\_outcomes.db and enforcing the offline-only rule, you protect your sub-30s OPRA latency edge while executing a mathematically sound validation pipeline. Deferring external data and dropping X entirely avoids massive API costs, legal friction, and the multiple-testing trap of mining noisy public sentiment.

Your Phase 1 design directly aligns with the academic state-of-the-art for preventing false discoveries. Using Combinatorial Purged Cross-Validation (CPCV) paired with the Probability of Backtest Overfitting (PBO) and the Deflated Sharpe Ratio (DSR) forces the system to account for the non-normality of returns and your global $N$-trials counter. Furthermore, implementing Hansen's SPA via the arch.bootstrap.SPA module ensures any newly generated signal is rigorously benchmarked against your existing "SOE A" grade. Incorporating Bailey and López de Prado's Minimum Backtest Length (MinBTL) will also guarantee your historical sample size is strictly scaled to the number of hypotheses tested.

Since you are actively in a build session, where should we focus first?

1. **The Deflation Engine (DSR & MinBTL):** Translating the Expected Maximum Sharpe Ratio and DSR formulas into vectorized Python code.  
2. **The CPCV / PBO Pipeline:** Structuring the step-by-step combinatorial logic for chronological data splitting, embargoing, and purging to prevent evaluation leakage.  
3. **Hansen's SPA:** Configuring the arch.bootstrap.SPA parameters (such as the stationary block bootstrap) to accurately evaluate the loss differential against your baseline.

Let me know which module you are currently writing or if you need to hash out the specific math and Python structures for any of these gates.

Here are the quantitative, literature-backed answers to your architectural and statistical design questions for the offline AutoResearch loop.

**1\. Fork-vs-build: Confirming "Build Thin"** Your decision to build a thin layer over your existing substrate is correct. Frameworks like Microsoft's RD-Agent are designed for traditional equities/Qlib factor mining and index heavily on LLM code generation rather than stringent multiple-testing corrections. Do not fork heavy research OS codebases. Instead, vendor the specific mathematical implementations. For the Deflation Engine, use ml4t-diagnostic which natively implements the Deflated Sharpe Ratio (DSR). For Hansen's SPA, use arch.bootstrap.SPA. Reimplementing CPCV and PBO is safer than relying on bloated libraries, as you must strictly map your embargo boundaries to your intraday OPRA data and overlapping label horizons.

**2\. Exact Thresholds for Phase 1 Validation**

* **DSR Confidence Cutoff & Expected Maximum Sharpe:** The correct confidence cutoff is $0.95$. The Expected Maximum Sharpe Ratio ($SR\_0$) for $N$ trials under a continuous loop is mathematically derived as:  
   $$SR\_0 \= \\sqrt{\\text{Var}} \\left( (1 \- \\gamma) Z^{-1} \\left(1 \- \\frac{1}{N}\\right) \+ \\gamma Z^{-1} \\left(1 \- \\frac{1}{N \\cdot e^{-1}}\\right)^{-1} \\right)$$  
   where $\\gamma \\approx 0.5772$ (Euler-Mascheroni constant), $Z$ is the standard normal CDF, and $\\text{Var}$ is the variance of the tested strategies.  
* **PBO Reject Cutoff:** Reject any hypothesis where $PBO \> 0.05$. A strategy with a genuine edge should push PBO toward $0$. A PBO of $0.50$ means the strategy is statistically indistinguishable from a random coin flip out-of-sample.  
* **CPCV Configuration:** Given sample sizes in the hundreds and overlapping hold horizons, use $N \= 6$ partitions and $k \= 2$ test groups, which yields $\\phi(6,2) \= 15$ combinatorial paths. Your embargo period must be at least the maximum holding horizon (e.g., 1 to 5 days) removed from the training set immediately following any test set to prevent delayed option-gamma reaction leakage.  
* **MinTRL (Minimum Track Record Length):** A sample size in the hundreds per cohort is mathematically underpowered given options-return distributions. The required track record length scales severely with skewness and kurtosis:  
  $$\\text{MinTRL} \= 1 \+ \\left \\left( \\frac{Z\_\\alpha}{SR \- SR^\*} \\right)^2$$  
   Negative skewness ($\\gamma\_3$) and fat tails ($\\gamma\_4 \> 3$) drastically increase the required number of observations. Detecting a mere 5 percentage point improvement over a 22.7% breakeven typically requires thousands of observations to achieve a 95% confidence level.  
* **Hansen SPA Loss Differential:** Bootstrap the economic PnL (net of realistic slippage). Using categorical outcomes (Win/Loss) discards severity. Evaluating the differential of the mean squared error or direct negative log returns against the "SOE A" baseline is required to properly calculate the p-value.

**3\. The Global N-Trials Counter & Prior Search** Prior informal search and ad-hoc backtests *do* count. Failing to include them guarantees your DSR will be falsely inflated. However, incrementing $N$ by 1 for every highly correlated LLM variation makes the hurdle impossible. **The Solution:** Do not use raw trial counts. Calculate the *effective* number of independent trials. Cluster your historical hypothesis returns using the Optimal Number of Clusters (ONC) algorithm or spectral eigenvalue methods applied to the correlation matrix of past returns. Seed $N$ with this effective dimension, and recalculate effective $N$ as the continuous loop runs.

**4\. Power Reality Check** A solo operator relying on per-cohort frequentist gates with $n \\approx 300$ will suffer from a near 100% false negative rate after honest deflation. Harvey, Liu, and Zhu proved that under multiple testing, the t-statistic required to claim a discovery in finance must exceed $3.0$. With an $n$ of 300, a candidate improving your win rate from 14.9% to 20% will yield a t-statistic of approximately $2.1$, failing the deflated hurdle. **The Fix:** You cannot use strict per-cohort frequentist isolation. You must apply Bayesian shrinkage or hierarchical pooling across regimes to borrow statistical strength , aggregating the validation across multiple similar strategy buckets before evaluating the significance.

**5\. Phase 0 Decay-Monitor Design**

Your proposed rule (rolling 60/90d Wilson CIs) is structurally flawed. Re-checking a fixed-n confidence interval daily constitutes sequential testing. If you monitor a 95% CI continuously, the probability of it randomly breaching the lower bound eventually approaches 100%, causing you to retire healthy signals prematurely.

**The Fix:** You must use "Always-Valid Confidence Sequences" (CS). Howard and Ramdas (2021) proved that sequential monitoring requires boundaries that expand at the Law of the Iterated Logarithm (LIL) rate: $O \\left( \\sqrt{\\frac{\\log\\log t}{t}} \\right)$. For a binary Win/Loss outcome, implement the empirical Bernstein or sub-Bernoulli confidence sequence. This guarantees that your false positive rate across *infinite continuous checks* remains strictly bounded at $\\alpha \= 0.05$. Your retirement trigger becomes: Retire when the lower bound of the *Always-Valid CS* drops below 22.7%.

**6\. Corrections for the Mid-Build Plan**

1. **Drop Fixed CIs in Phase 0:** Immediately replace Wilson/Clopper-Pearson with Howard-Ramdas Always-Valid Confidence Sequences for continuous monitoring.  
2. **Cluster your $N$-Trials:** Do not use a naive global integer counter for Phase 1\. Implement correlation clustering to count only effective independent trials, preventing the LLM's highly-correlated noise generations from permanently locking the DSR gate.  
3. **Bayesian Pooling:** Acknowledge that an $n$ in the hundreds per regime cannot survive a multiple-testing penalty. Design Phase 1 to evaluate the Hansen SPA globally across pooled cohorts with hierarchical shrinkage, rather than gating signals in isolated sub-cohorts.

