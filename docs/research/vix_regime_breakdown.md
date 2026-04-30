# VIX-based Regime Breakdown

Replaces the hand-tuned IV-term-structure classifier with the CBOE-published VIX1D / VIX9D spread, sampled at the close of the prior trading day (ex-ante).

- Threshold (theory, NOT tuned): VIX1D - VIX9D > 3.0 = HUMP
- Stressed regime cutoff: VIX9D > 22.0


## Per-day VIX classification

| Day | Prior day | VIX1D | VIX9D | Spread | Regime |
|---|---|---|---|---|---|
| 2026-04-14 | 2026-04-13 | 11.77 | 17.33 | -5.56 | CALM_FLAT |
| 2026-04-15 | 2026-04-14 | 12.50 | 16.70 | -4.20 | CALM_FLAT |
| 2026-04-16 | 2026-04-15 | 12.65 | 16.01 | -3.36 | CALM_FLAT |
| 2026-04-20 | 2026-04-17 | 14.24 | 14.81 | -0.57 | CALM_FLAT |
| 2026-04-21 | 2026-04-20 | 12.13 | 17.79 | -5.66 | CALM_FLAT |
| 2026-04-22 | 2026-04-21 | 16.20 | 18.68 | -2.48 | CALM_FLAT |
| 2026-04-23 | 2026-04-22 | 12.28 | 17.29 | -5.01 | CALM_FLAT |
| 2026-04-24 | 2026-04-23 | 14.82 | 18.04 | -3.22 | CALM_FLAT |

## P&L per VIX regime

| Regime | Fires | with_EOD | WR | Avg |
|---|---|---|---|---|
| CALM_FLAT | 27 | 20 | 45.0% | +18.7% |