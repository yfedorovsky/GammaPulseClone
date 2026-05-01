# Test #3 — Day regime audit (VIX1D quartile vs microstructure)

- Sample: 248 ticker-days with valid features and VIX1D
- VIX1D source: ThetaData index/history/eod, prior-day close
- Quartiles assigned per-ticker so cohort sizes are balanced


## Mean feature by VIX1D quartile (per ticker)

| Ticker | Quartile | n days | cum_ofi | abs_ofi | total_volume | mean_spread | std_spread | mean_mp_dev_abs | spread_spike_minutes | n_trades |
|---|---|---|---|---|---|---|---|---|---|---|
| SPY | Q1 | 31 | -3.713e+05 | 6.319e+05 | 1.685e+06 | 0.02353 | 0.0467 | 0.004368 | 18.84 | 2.821e+04 |
| SPY | Q2 | 31 | -2.377e+05 | 8.033e+05 | 1.924e+06 | 0.03006 | 0.04286 | 0.00565 | 18.45 | 3.204e+04 |
| SPY | Q3 | 31 | -3.203e+05 | 8.943e+05 | 2.077e+06 | 0.04287 | 0.4733 | 0.01076 | 21.48 | 3.401e+04 |
| SPY | Q4 | 31 | -3.454e+05 | 1.705e+06 | 2.504e+06 | 0.0398 | 0.04376 | 0.007456 | 21.45 | 4.053e+04 |
| QQQ | Q1 | 31 | -1.632e+05 | 1.195e+06 | 1.21e+06 | 0.02682 | 0.03176 | 0.004962 | 20.35 | 1.873e+04 |
| QQQ | Q2 | 31 | -1.079e+05 | 1.002e+06 | 1.136e+06 | 0.03869 | 0.05429 | 0.007002 | 21.55 | 1.779e+04 |
| QQQ | Q3 | 31 | 1.188e+05 | 1.169e+06 | 1.371e+06 | 0.03619 | 0.04434 | 0.006373 | 22.16 | 2.203e+04 |
| QQQ | Q4 | 31 | 1.863e+05 | 1.146e+06 | 1.655e+06 | 0.0414 | 0.04615 | 0.007032 | 24.9 | 2.626e+04 |

## Kruskal-Wallis significance (across the 4 VIX1D quartiles)

| Ticker | Feature | K-W stat | p |
|---|---|---|---|
| SPY | cum_ofi | 3.82 | 0.2814 |
| SPY | abs_ofi | 10.62 | 0.0140 ✓ |
| SPY | total_volume | 18.67 | 0.0003 ✓ |
| SPY | mean_spread | 33.72 | 0.0000 ✓ |
| SPY | std_spread | 11.10 | 0.0112 ✓ |
| SPY | mean_mp_dev_abs | 28.76 | 0.0000 ✓ |
| SPY | spread_spike_minutes | 7.54 | 0.0567 |
| SPY | n_trades | 10.74 | 0.0132 ✓ |
| QQQ | cum_ofi | 2.08 | 0.5562 |
| QQQ | abs_ofi | 0.46 | 0.9278 |
| QQQ | total_volume | 14.18 | 0.0027 ✓ |
| QQQ | mean_spread | 35.02 | 0.0000 ✓ |
| QQQ | std_spread | 19.35 | 0.0002 ✓ |
| QQQ | mean_mp_dev_abs | 28.00 | 0.0000 ✓ |
| QQQ | spread_spike_minutes | 13.54 | 0.0036 ✓ |
| QQQ | n_trades | 15.37 | 0.0015 ✓ |

## Verdict

12 out of 16 feature × ticker tests show significant differences across VIX1D quartiles. **Vol regime carries microstructure information** at the day level. An IV-regime gate using VIX1D quartiles with pre-committed thresholds may be defensible for v2 — unlike the original 0DTE-IV-term-structure classifier which failed externally.