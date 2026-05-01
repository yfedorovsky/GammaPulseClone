# Test #1 — Microstructure profile of fires vs random moments

- Fires audited: 17 (SPY+QQQ only)
- Random baselines per fire: 10
- Window: [event − 30min, event]


## Effect size table

Cohen's d interpretation: |d| < 0.2 = trivial, 0.2-0.5 = small, 0.5-0.8 = medium, > 0.8 = large.

| Feature | d | Fire mean | Random mean | Fire median | Rand median |
|---|---|---|---|---|---|
| cumulative_ofi | +0.06 | -5.972e+04 | -7.012e+04 | -6.054e+04 | -4.548e+04 |
| ofi_per_min | +0.06 | -1,991 | -2,337 | -2,018 | -1,516 |
| mean_mp_minus_mid | +0.30 | -0.0001982 | -0.0004924 | -0.0002087 | -0.0004866 |
| std_mp_minus_mid | +0.17 | +0.02117 | +0.01723 | +0.01267 | +0.009805 |
| mean_spread | +0.32 | +0.04933 | +0.04453 | +0.04754 | +0.03921 |
| std_spread | +0.26 | +0.05456 | +0.03737 | +0.02867 | +0.01615 |
| aggressor_ratio | +0.29 | +0.5199 | +0.4965 | +0.5029 | +0.4957 |
| total_volume | +0.49 | +1.126e+05 | +8.739e+04 | +9.692e+04 | +7.703e+04 |
| mean_trade_size | +0.37 | +66.58 | +62.39 | +64.78 | +61.43 |
| n_trades | +0.41 | +1,650 | +1,378 | +1,567 | +1,230 |

## Verdict

**No feature shows medium-or-larger effect size.** Fire windows are statistically similar to random same-day windows. The gate framework may be firing on structural-level coincidences rather than real microstructure events. Strong evidence that the v1 detector lacks flow-side discrimination.