# MAE-Based Stop Recalibration Analysis

- Total trades analyzed: **78** (PML: 74, ST: 4)
- Winners (realized > 0): **16**
- Losers (realized ≤ 0): **62**

**Methodology**: For each historical trade, compute the deepest drawdown (MAE = min option mid / entry ask − 1) between entry and final exit time. Compare MAE distribution for winners vs losers, then simulate alternative stop levels.

## Winner MAE distribution (the answer is here)

| Percentile | MAE |
|---|---|
| P5  (worst) | -45.9% |
| P10 | -43.9% |
| P25 | -38.8% |
| median | -21.9% |
| P75 | -7.4% |
| P95 (best) | -0.6% |
| **Mean** | **-23.2%** |

**Interpretation**: This shows how deep your WINNING trades went underwater before recovering. The optimal stop should be just BELOW the worst MAE the typical winner experiences (P5-P10), to avoid stopping out genuine winners while cutting losers earlier.

## Loser MAE distribution

| Percentile | MAE |
|---|---|
| P5 | -53.9% |
| P25 | -52.5% |
| median | -51.0% |
| P75 | -50.3% |
| P95 | -49.6% |
| **Mean** | **-50.8%** |

## Stop simulation — what each level would have produced

Each candidate stop applied to all trades in the dataset. If MAE ≤ stop, the trade exits at the stop; otherwise the original realized P&L stands.

| Stop | Trades | Hit% | Avg P&L | Winners killed | Losers saved |
|---|---|---|---|---|---|
| -25% | 78 | 11.5% | -11.1% | 7 | 61 |
| -30% | 78 | 12.8% | -12.9% | 6 | 61 |
| -35% | 78 | 14.1% | -15.5% | 5 | 61 |
| -40% | 78 | 15.4% | -18.8% | 4 | 61 |
| -50% | 78 | 20.5% | -21.6% | 0 | 56 |
| -60% | 78 | 20.5% | -23.1% | 0 | 0 |
| -70% | 78 | 20.5% | -23.1% | 0 | 0 |
| -80% | 78 | 20.5% | -23.1% | 0 | 0 |

## Optimal stop

**Best avg P&L: -11.1% at stop = -25%**

vs current -50% stop: -21.6% → **delta = +10.5%**

## All winners with their MAE (sorted by MAE)

| Source | Day | Tkr | Dir | Entry | MAE | MFE | Realized |
|---|---|---|---|---|---|---|---|
| PML | 2026-04-01 | SPY | 🔴 | 14:00 | -0.4% | +193% | **+98.5%** |
| PML | 2026-04-02 | QQQ | 🟢 | 09:40 | -0.7% | +499% | **+204.0%** |
| PML | 2026-04-23 | QQQ | 🔴 | 13:05 | -0.9% | +224% | **+138.0%** |
| PML | 2026-04-08 | QQQ | 🔴 | 09:30 | -2.3% | +159% | **+81.2%** |
| ST A | 2026-04-28 | SPY | 🟢 | 13:18 | -9.2% | +207% | **+126.8%** |
| PML | 2026-04-20 | QQQ | 🟢 | 12:55 | -18.5% | +59% | **+3.4%** |
| PML | 2026-04-01 | QQQ | 🔴 | 14:05 | -18.5% | +135% | **+64.4%** |
| PML | 2026-04-20 | SPY | 🔴 | 09:55 | -19.2% | +120% | **+61.3%** |
| PML | 2026-04-08 | QQQ | 🔴 | 09:40 | -24.6% | +112% | **+58.3%** |
| PML | 2026-04-09 | QQQ | 🟢 | 10:25 | -29.6% | +363% | **+173.3%** |
| ST B | 2026-04-28 | QQQ | 🟢 | 13:03 | -30.5% | +280% | **+93.5%** |
| PML | 2026-04-06 | QQQ | 🟢 | 13:10 | -37.9% | +63% | **+34.9%** |
| ST B | 2026-04-27 | SPY | 🟢 | 10:58 | -41.5% | +79% | **+56.0%** |
| ST A | 2026-04-28 | SPY | 🟢 | 11:31 | -42.9% | +93% | **+42.5%** |
| PML | 2026-04-16 | QQQ | 🟢 | 09:40 | -44.8% | +166% | **+78.4%** |
| PML | 2026-04-16 | QQQ | 🔴 | 13:10 | -49.2% | +118% | **+57.1%** |
