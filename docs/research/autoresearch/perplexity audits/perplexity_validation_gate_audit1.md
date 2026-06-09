# GammaPulse Validation Gate — Methodology Audit
**Date:** 2026-06-08 · Round 3 Perplexity Adversarial Audit  
**Scope:** Four methodology claims from the C1–C6 code review of the Bailey & López de Prado validation-gate stack.  
**Format:** VERDICT → Why → Primary citation → Canonical fix (per claim). Priority ordering at end.

---

## Claim 1: DSR Seed → Variance Corruption

**VERDICT: PARTIALLY CORRECT — right diagnosis, wrong canonical fix.**

### Why

Bailey & López de Prado (2014) Eq. (1) and Appendix A.1 are unambiguous: the formula is

$$
\widehat{SR}^* = \sqrt{\widehat{V}[\{\widehat{SR}_n\}]} \cdot \left[(1-\gamma)\,\Phi^{-1}\!\left(1-\tfrac{1}{N}\right) + \gamma\,\Phi^{-1}\!\!\left(1-\tfrac{1}{Ne}\right)\right]
$$

where $\widehat{V}[\{\widehat{SR}_n\}]$ is **the variance of the Sharpe estimates across the N trials**, and N is **the number of independent trials**. The paper presents **N and Var as coming from the same trial set** — there is no two-register design in the original formulation. The DSR derivation assumes you observe actual Sharpe values for all N trials; N is not a separate counter that can be incremented without a corresponding SR observation.

The diagnosis is correct: seeding 300 zeros artificially crushes Var toward zero, collapsing $\widehat{SR}^*$ and making the hurdle leniently close to zero even at large N. The variance channel is corrupted exactly as described.

**What is NOT correct:** The claim that "seed trials should contribute to N but NOT to Var" is not the canonical Bailey–López de Prado fix. It is an ad hoc split that the paper does not contemplate — and it is internally inconsistent, because N was derived as the count of *independent* trials whose observed SR values define the distribution with mean and variance $\widehat{V}$. You cannot decouple them without abandoning the distributional assumption.

### Primary Citation

Bailey, D. H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality." *Journal of Portfolio Management*, Eq. (1) and Appendix A.1–A.3.  
URL: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

### Canonical Fix

The paper's own Appendix A.3 addresses correlated trials by estimating an "implied independent N" via average correlation among SR estimates. For the seeding problem, the right treatment is one of:

**(a) Trimmed variance with full N** — exclude seeded trials from Var estimation entirely; compute Var from *only* scored trials; use N = seeded_count + scored_count in the N-slot. Document the split explicitly as a modeling choice not in the original paper.

**(b) Imputed SR distribution** — assign seeded trials a prior SR draw from your empirically observed SR distribution (e.g., bootstrap from scored trials) rather than SR=0. This imputes plausible variation rather than setting all seeds to the same degenerate value.

The paper's own numerical example passes `sigma=1` explicitly as a *prior belief* about trial variance (not computed from the data), confirming that Var can be partially decoupled — but must be assigned a **plausible** non-zero value, never zero.

> **Implementation note:** Option (b) is more defensible statistically. Option (a) is simpler and more auditable. Never use SR=0 for seeded trials.

---

## Claim 2: PBO/CSCV Degenerates at Small T

**VERDICT: CORRECT.**

### Why

Bailey, Borwein, López de Prado & Zhu (2014/2016) explicitly state that each sub-matrix $M_s$ in CSCV is of order $(T/S \times N)$, and that "k must be sufficiently small, so that the Sharpe ratio estimate is reliable." The Sharpe ratio of a **single observation** (block_size = 1) is undefined: the standard deviation of a length-1 series is zero, making SR = mean/std = ∞ or NaN.

The paper's own worked examples use T=1,000 with S=16, giving block_size ≈ 62.5. There is no explicit minimum block_size stated in the CSCV paper, but the structure of the algorithm requires that the Sharpe ratio "can be estimated on subsamples of each column" — a condition that fails at block_size = 1.

S=16 with T=21 gives `floor(21/16) = 1`. A reported PBO=0.672 from this configuration is noise and must not be consumed as a valid gate output.

### Primary Citation

Bailey, D. H., Borwein, J. M., López de Prado, M. & Zhu, Q. J. (2016). "The Probability of Backtest Overfitting." *Journal of Computational Finance*, Vol. 20, No. 4.  
URL: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf  
See also: https://www.risk.net/journal-of-computational-finance/2471206/the-probability-of-backtest-overfitting

### Canonical Fix

```
S = min(16,  2 * floor(T / 10))
```

Practical block-size guide:

| T range   | Recommended S | Resulting block_size |
|-----------|---------------|----------------------|
| T < 20    | return N/A    | —                    |
| 20–40     | S = 4         | 5–10                 |
| 40–80     | S = 6         | 6–13                 |
| 80–160    | S = 8         | 10–20                |
| 160–500   | S = 12        | 13–40                |
| ≥ 500     | S = 16        | ≥ 31                 |

**Guard to add immediately** (one line):

```python
if T // S < 5:
    return {'pbo': None, 'verdict': 'INSUFFICIENT_DATA'}
```

Do not attempt PBO when T < 20. At small T, fall back to Wilson/Clopper-Pearson CI on win-rate as the gate instead.

---

## Claim 3: Effective-N Must Not Collapse Independent Prior Trials

**VERDICT: PARTIALLY CORRECT — the participation ratio is right for correlated variants; the family-collapse failure is real; but the fix requires precision.**

### Why

Bailey & López de Prado (2014) Appendix A.3 derives the standard estimator for independent-equivalent N from correlated trials via average pairwise SR correlation $\hat{\rho}$:

$$
\hat{N} \approx M \cdot \left(1 - \hat{\rho}\left(1 - \tfrac{1}{M}\right)\right)^{-1} \cdot \hat{\rho}
$$

The **participation ratio** $(\sum\lambda_i)^2 / \sum\lambda_i^2$ of the SR-correlation eigenspectrum is a standard information-theoretic alternative to the average-correlation approach and is more robust for high-dimensional trial sets — this is correct and consistent with the paper's spirit.

**The family-collapse failure is a real bug:** the no-matrix fallback that reduces 300 independent seeds to a single family label incorrectly implies that the seeds are perfectly correlated variants of one strategy, when in reality they are genuinely independent prior searches. This understates $N_\text{eff}$ and paradoxically makes the gate *more lenient* (lower $N_\text{eff}$ → lower E[max SR] hurdle) — the opposite of the variance-crushing effect in Claim 1.

### Primary Citation

Bailey & López de Prado (2014), Appendix A.3 "Effective Number of Independent Trials."  
URL: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

### Canonical Fix

The Appendix A.3 formula applies only *within* a correlated family (e.g., parameter variations of the same strategy). The correct architecture:

$$
N_\text{eff} = N_\text{eff}^{(\text{independent seeds})} + \sum_{j \in \text{families}} N_\text{eff}^{(j)}
$$

where $N_\text{eff}^{(\text{independent seeds})} = 300$ (counted at face value — one per seed, by definition of independence), and each family's contribution is computed via average within-family SR correlation.

**Rule of thumb for independence classification:** Trials testing different *mechanisms* (different hypotheses) are independent. Trials testing different *parameters* of the same hypothesis are correlated variants within one family. The family-label fallback must never collapse independent seeds — only structurally dependent parameter sweeps within a single strategy class.

```python
def compute_n_eff(independent_seed_count: int,
                  family_sr_matrices: list[np.ndarray]) -> float:
    """
    independent_seed_count: number of genuinely distinct prior searches (300)
    family_sr_matrices: list of (T x M_j) SR arrays, one per strategy family
    """
    n_eff_families = 0.0
    for sr_mat in family_sr_matrices:
        corr = np.corrcoef(sr_mat.T)
        eigenvalues = np.linalg.eigvalsh(corr)
        # Participation ratio
        pr = (eigenvalues.sum()**2) / (eigenvalues**2).sum()
        n_eff_families += pr
    return independent_seed_count + n_eff_families
```

---

## Claim 4: Always-Valid LCB Calibration

**VERDICT: PARTIALLY CORRECT — the form is a valid Howard-Ramdas-family bound, but the specific β constant cited does not match any published formula in the primary source, and a strictly tighter bound now exists.**

### Why

Howard, Ramdas, McAuliffe & Sekhon (2021, *Annals of Statistics*) Theorem 4 gives the empirical-Bernstein stitched confidence sequence for bounded observations. The radius form

$$
\text{radius} = \sqrt{\frac{2\, v\, \beta}{n}} + \frac{3\beta}{n}, \qquad v = \hat{\mu}(1-\hat{\mu})
$$

is structurally a Maurer-Pontil empirical-Bernstein inequality extended to the sequential setting — it is in the right family. **However**, the exact constants in the primary source are **not** $\beta = \ln(1/\alpha) + 3 \cdot \ln(\ln(e \cdot n))$.

The paper's Theorem 4 uses constants derived from specific tuning parameters $\eta, m, s$ that do not reduce to a closed-form $\beta$ with a single coefficient of 3. The `3·ln(ln(e·n))` term is consistent with the **asymptotic LIL growth rate** ($O(\sqrt{v \log\log n / n})$), but the coefficient 3 is **not a canonical constant from the paper**. Using an unverified constant risks systematic under-coverage (too lenient, retiring too readily) or over-coverage (too conservative, never retiring).

**The conservatism claim is correct:** The stitched empirical-Bernstein CS is deliberately wider than fixed-n Wilson bounds, and for a retirement decision (where false retirements are costly), erring toward not retiring is the right asymmetry.

### Primary Citation

Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). "Time-uniform, nonparametric, nonasymptotic confidence sequences." *Annals of Statistics*, 49(2).  
DOI: 10.1214/20-AOS1991  
URL: https://arxiv.org/abs/1810.08240  
Preprint: https://par.nsf.gov/servlets/purl/10251927

### Is There a Tighter Standard Bound?

**Yes.** Waudby-Smith & Ramdas (2023, *JRSS-B*) — the **betting/PRGW (Predictable Regret Growth Weighting) confidence sequence** — is now the demonstrated state-of-the-art for bounded means:

- Shown to have **smaller first-order asymptotic width** than empirical-Bernstein CSs (Theorem 1 of Waudby-Smith & Ramdas 2023).
- Empirically "vastly outperforms" EB bounds on bounded data.
- Proved near-optimal: matches the information-theoretic lower bound modulo a logarithmic term.
- Paper: Waudby-Smith, I. & Ramdas, A. (2023). "Estimating means of bounded random variables by betting." *JRSS-B*, 86(1).  
  DOI: 10.1093/jrsssb/qkad009
- Near-optimality proof: "On the near-optimality of betting confidence sets for bounded means." *arXiv:2310.01547* (2023).

### Canonical Fix

Replace the hand-rolled β formula with the `confseq` library's verified implementations:

```python
# pip install confseq
from confseq.betting import betting_cs          # PRGW — tightest
from confseq.emp_bernstein import empirical_bernstein_cs  # Theorem 4 constants

# For binary win-rate (Bernoulli, bounded in [0,1])
# Preferred: PRGW betting CS
observations = np.array([1.0]*wins + [0.0]*(n - wins))

# running_intersection=True ensures the bound shrinks monotonically
lcb, ucb = betting_cs(
    observations,
    alpha=0.05,
    running_intersection=True,
    theta_method='PRGW'
)
current_lcb = lcb[-1]  # time-uniform lower bound at current n

# Retire when current_lcb < breakeven for 2 consecutive checks (hysteresis)
```

**Repo:** https://github.com/gostevehoward/confseq (MIT license, actively maintained).

### Additional Framing Error

The claim that "conservatism is appropriate because it errs toward NOT retiring" is sound for **retirement** decisions. However, the same CS is used for **promotion** (shadow → human gate) if you monitor win rate from below. For promotion, a wide CS means the LCB rarely exceeds breakeven — the asymmetry is reversed. Use:

- **Retirement monitoring:** one-sided lower CS (wide/conservative → rarely fires false retirement) ✓  
- **Promotion monitoring:** one-sided upper CS (or Jeffreys posterior UCB) → correctly sensitive to genuine improvement

If your current implementation uses the same lower-bound CS for both decisions, separate them into two independent monitors.

---

## Priority Order

| Priority | Claim | Severity | Fix complexity |
|----------|-------|----------|----------------|
| **1 — Fix immediately** | Claim 2 (PBO degenerate at T=21, S=16) | **Active error** — gate consuming numerical noise as valid signal | One-line guard |
| **2 — Fix this week** | Claim 4 (β constant unverified) | Calibration drift; retirement trigger may fire at wrong times | Swap to `confseq.betting_cs` |
| **3 — Fix in ledger refactor** | Claims 1 & 3 (jointly) | Corrupt DSR variance; collapsed N_eff | Trial-ledger refactor: 3 separate counters |

### Summary of the Three-Counter Ledger Refactor (Claims 1 + 3)

Maintain three registers:

| Register | What goes in | Used for |
|----------|-------------|----------|
| `N_independent_seeds` | All genuinely distinct prior searches (300) | Adds directly to N in E[max SR\|N] |
| `scored_trial_srs` | Sharpe values from *actually evaluated* hypotheses | Source of Var(SR̂) — never SR=0 |
| `family_sr_matrices` | Per-family (T × M) matrices for correlated parameter sweeps | Participation-ratio N_eff per family |

Final N for DSR = `N_independent_seeds + sum(family N_eff_j) + len(scored_trial_srs)`  
Var(SR̂) = `np.var(scored_trial_srs)` — seeded trials never enter this register.

---

*Primary sources used in this audit:*  
- Bailey & López de Prado (2014), SSRN 2460551 / davidhbailey.com/dhbpapers/deflated-sharpe.pdf  
- Bailey, Borwein, López de Prado & Zhu (2016), J. Computational Finance / davidhbailey.com/dhbpapers/backtest-prob.pdf  
- Howard, Ramdas, McAuliffe & Sekhon (2021), Annals of Statistics 49(2), arXiv:1810.08240  
- Waudby-Smith & Ramdas (2023), JRSS-B 86(1)  
- "On the near-optimality of betting confidence sets for bounded means," arXiv:2310.01547 (2023)
