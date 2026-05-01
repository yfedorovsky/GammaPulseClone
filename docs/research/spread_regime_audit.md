# Test #6 — Spread regime audit

Sample: 17 fires (SPY+QQQ).
For each fire: compare 30-min-pre-fire mean spread to that day's session-wide minute-spread distribution.


## Aggregate

- Fires flagged HIGH_SPREAD (window mean > day p90): 11/17 (65%)
- Mean ratio of fire-window spread to day p50: 1.37
  (1.0 = at the day's median; >1.5 = significantly elevated)

## Outcome by spread regime

| Regime | n | mean PnL | win rate |
|---|---|---|---|
| Normal | 5 | +62.6% | 40.0% |
| HIGH spread | 10 | -14.0% | 30.0% |

## Verdict

Normal-spread fires outperform HIGH-spread fires by 77pp avg PnL. **Consider a 'do not fire when 30-min spread > day p90' gate** for v2 — this filters the worst-expectancy subset before they cost capital.