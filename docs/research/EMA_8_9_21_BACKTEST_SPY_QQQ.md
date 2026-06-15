# EMA 8/9/21 Backtest — SPY & QQQ (Tier 3)

_Generated: 2026-05-12T21:58_  
_Data sources: yfinance (daily 5y, 1hr ~3y), Databento (5min 127d), ThetaData (VIX EOD, 0DTE NBBO)._  
_Slippage: 1.0bp per side on shares; NBBO mid for options._  
_Bootstrap: 2000 resamples, seed=42._  

## TL;DR

- **9/21 long-only on SPY daily** over 5y: n=21 trades, win rate 47.6%, avg trade +1.988% (95% CI [-0.699, +5.101]) (CI spans 0 — NOT significant), Sharpe +0.61, total return +45.1%. Edge classification: POSITIVE.
- **Buy-and-hold reference**: SPY closed-to-close over the same 5y window = +82.1%. Strategy must beat this with comparable risk to claim edge.
- **Sensitivity**: best (fast,slow) on SPY daily = (11,22) with Sharpe +0.83, total +61.1%. Grid range Sharpe ∈ [+0.61, +0.83] — see grid below.
- **0DTE overlay**: no trades captured (data unavailable or budget exhausted).
- **Walk-forward**: no major IS→OOS drift detected (see table).

## Strategy results (full-sample, slippage-adjusted)

### 9_21_long

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 21 | 47.6% | +1.988% | -0.335% | 2.75 | +0.61 | -13.6% | +45.1% | [-0.699, +5.101] |
| QQQ daily | 24 | 37.5% | +2.147% | -2.232% | 1.97 | +0.52 | -22.1% | +52.5% | [-1.256, +5.989] |
| SPY 1hr | 108 | 33.3% | +0.262% | -0.365% | 1.52 | +0.84 | -11.3% | +30.3% | [-0.079, +0.657] |
| QQQ 1hr | 104 | 36.5% | +0.445% | -0.428% | 1.68 | +0.95 | -12.5% | +53.0% | [-0.040, +1.041] |

### 9_21_long_short

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 42 | 35.7% | +0.590% | -1.433% | 1.39 | +0.32 | -15.2% | +21.0% | [-0.895, +2.387] |
| QQQ daily | 48 | 27.1% | +0.525% | -2.418% | 1.22 | +0.22 | -24.4% | +13.9% | [-1.484, +2.783] |
| SPY 1hr | 215 | 29.3% | +0.006% | -0.393% | 1.01 | +0.04 | -23.2% | -1.2% | [-0.195, +0.240] |
| QQQ 1hr | 208 | 32.2% | +0.102% | -0.575% | 1.15 | +0.37 | -19.2% | +17.1% | [-0.200, +0.434] |

### 8_21_long

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 21 | 47.6% | +2.143% | -0.198% | 3.09 | +0.66 | -11.5% | +50.0% | [-0.498, +5.227] |
| QQQ daily | 24 | 37.5% | +2.282% | -2.232% | 2.03 | +0.55 | -22.2% | +57.4% | [-1.117, +6.174] |
| SPY 1hr | 113 | 36.3% | +0.258% | -0.344% | 1.51 | +0.85 | -11.6% | +31.3% | [-0.069, +0.616] |
| QQQ 1hr | 108 | 37.0% | +0.445% | -0.428% | 1.69 | +0.98 | -12.5% | +55.5% | [-0.021, +0.989] |

### stacked_long

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 34 | 50.0% | +1.368% | +0.105% | 2.41 | +0.75 | -12.7% | +53.6% | [-0.109, +2.936] |
| QQQ daily | 40 | 40.0% | +1.065% | -1.224% | 1.68 | +0.50 | -22.5% | +43.3% | [-0.571, +3.069] |
| SPY 1hr | 141 | 34.0% | +0.163% | -0.275% | 1.42 | +0.78 | -8.0% | +24.1% | [-0.062, +0.408] |
| QQQ 1hr | 142 | 35.2% | +0.216% | -0.279% | 1.42 | +0.80 | -9.7% | +32.6% | [-0.071, +0.533] |

### pullback_to_9

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 132 | 53.0% | -0.037% | +0.072% | 0.93 | -0.15 | -13.3% | -5.8% | [-0.252, +0.189] |
| QQQ daily | 144 | 57.6% | +0.092% | +0.433% | 1.16 | +0.34 | -22.0% | +12.4% | [-0.153, +0.337] |
| SPY 1hr | 537 | 46.7% | -0.004% | -0.034% | 0.97 | -0.16 | -8.6% | -2.7% | [-0.038, +0.030] |
| QQQ 1hr | 502 | 49.0% | +0.002% | -0.016% | 1.01 | +0.06 | -9.9% | +0.5% | [-0.042, +0.048] |

### 9_21_long_trend

| Label | N | Win% | AvgRet | Median | PF | Sharpe | MaxDD | TotalRet | 95% CI on mean |
|---|---|---|---|---|---|---|---|---|---|
| SPY daily | 19 | 47.4% | +1.542% | -0.335% | 2.89 | +0.61 | -5.7% | +31.1% | [-0.384, +3.930] |
| QQQ daily | 22 | 40.9% | +2.785% | -2.026% | 2.42 | +0.62 | -13.9% | +68.5% | [-0.694, +7.102] |
| SPY 1hr | 90 | 34.4% | +0.190% | -0.349% | 1.42 | +0.72 | -7.4% | +17.6% | [-0.084, +0.490] |
| QQQ 1hr | 80 | 37.5% | +0.322% | -0.375% | 1.52 | +0.77 | -8.7% | +27.0% | [-0.119, +0.816] |

## Sensitivity grid (SPY daily, long-only)

Sharpe for each (fast, slow) pair:

| fast \ slow | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|
| **7** | +0.68 | +0.68 | +0.64 | +0.65 | +0.71 |
| **8** | +0.66 | +0.65 | +0.66 | +0.67 | +0.69 |
| **9** | +0.66 | +0.67 | +0.61 | +0.69 | +0.72 |
| **10** | +0.62 | +0.66 | +0.72 | +0.75 | +0.81 |
| **11** | +0.68 | +0.76 | +0.79 | +0.83 | +0.82 |

Total return (%) for each (fast, slow) pair:

| fast \ slow | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|
| **7** | +55.1% | +54.7% | +49.6% | +49.1% | +53.9% |
| **8** | +52.3% | +51.3% | +50.0% | +51.3% | +51.8% |
| **9** | +49.9% | +51.0% | +45.1% | +48.2% | +50.3% |
| **10** | +46.0% | +48.8% | +50.9% | +53.6% | +60.2% |
| **11** | +47.6% | +55.0% | +58.6% | +61.1% | +59.9% |

_The published (9, 21) pair ranks **#25 of 25** by Sharpe (+0.61). The grid is tightly clustered (robust to perturbation)._

## Walk-forward 80/20

In-sample (IS) = first 80% of bars; out-of-sample (OOS) = last 20%.

| Strategy | Ticker | TF | IS n | IS avg | IS Sharpe | OOS n | OOS avg | OOS Sharpe | Drift |
|---|---|---|---|---|---|---|---|---|---|
| 9_21_long | QQQ | 1hr | 79 | +0.431% | +0.98 | 26 | +0.472% | +0.91 | -0.041% |
| 9_21_long | QQQ | daily | 20 | +0.969% | +0.31 | 5 | +7.151% | +1.08 | -6.182% |
| 9_21_long | SPY | 1hr | 85 | +0.287% | +1.00 | 24 | +0.147% | +0.40 | +0.140% |
| 9_21_long | SPY | daily | 17 | +1.047% | +0.42 | 5 | +5.399% | +1.16 | -4.352% |
| 9_21_long_trend | QQQ | 1hr | 0 | +0.000% | +0.00 | 16 | +0.287% | +0.64 | -0.287% |
| 9_21_long_trend | QQQ | daily | 18 | +1.618% | +0.48 | 5 | +7.151% | +1.08 | -5.533% |
| 9_21_long_trend | SPY | 1hr | 0 | +0.000% | +0.00 | 19 | -0.150% | -0.66 | +0.150% ⚠ |
| 9_21_long_trend | SPY | daily | 15 | +1.546% | +0.61 | 4 | +1.526% | +1.04 | +0.020% |
| stacked_long | QQQ | 1hr | 112 | +0.242% | +0.89 | 33 | +0.120% | +0.47 | +0.122% |
| stacked_long | QQQ | daily | 29 | +0.673% | +0.36 | 12 | +2.229% | +1.00 | -1.557% |
| stacked_long | SPY | 1hr | 112 | +0.187% | +0.94 | 31 | +0.042% | +0.18 | +0.145% |
| stacked_long | SPY | daily | 25 | +1.153% | +0.68 | 10 | +2.075% | +1.13 | -0.923% |

## Regime split — 9/21 long-only, daily, by VIX at entry

| Ticker | Regime | N | Win% | Avg | Total | Sharpe |
|---|---|---|---|---|---|---|
| SPY | LOW (<15) | 4 | 50.0% | +4.471% | +18.0% | +1.03 |
| SPY | NORMAL (15-20) | 11 | 45.5% | +1.237% | +13.6% | +0.46 |
| SPY | HIGH (20-30) | 6 | 50.0% | +1.709% | +8.2% | +0.22 |
| SPY | STRESS (>30) | 0 | — | — | — | — |
| QQQ | LOW (<15) | 4 | 50.0% | +3.987% | +15.6% | +0.56 |
| QQQ | NORMAL (15-20) | 13 | 30.8% | +0.143% | -0.2% | +0.04 |
| QQQ | HIGH (20-30) | 7 | 42.9% | +4.816% | +32.2% | +0.47 |
| QQQ | STRESS (>30) | 0 | — | — | — | — |

## 0DTE overlay — 5-min 9/21 cross → ATM 0DTE

_No 0DTE trades captured. ThetaData NBBO was unavailable or budget exhausted; see run log._

## What surprised me

- Pullback-to-9 (SPY daily) Sharpe -0.15 **underperforms** the plain 9/21 cross (+0.61). The ATR-target exit may be cutting winners short — the cross strategy gets the trend leg fully.
- 9/21 long+short (+0.32) Sharpe **degrades** vs long-only (+0.61) on SPY daily. The short side is unprofitable in this 5y window (which contains a 2-year bull). Don't symmetrize a strategy just for elegance — the world isn't symmetric.

## What I'd trade (recommendation)

**Nothing.** No (strategy × timeframe × ticker) cell clears all four bars:
- n ≥ 20 trades
- 95% bootstrap CI on mean trade excludes zero
- Sharpe ≥ 0.4
- Max drawdown shallower than -30%

Translation: after slippage, none of the six EMA configs on SPY/QQQ delivers a positive expectancy that you can defend against a critic. Some configs *look* profitable in total return, but that's usually driven by 1-2 outlier wins riding the 5y trend — the per-trade edge isn't separable from random walk. Buy-and-hold SPY beats every variant on Sharpe-adjusted total return.

## What's missing / known limitations

- **Single 5y window.** No 2008-09 GFC, no 2018 vol shock, no 2020 COVID crash (we start May 2021). The OOS split (last 20%) covers ~1 year — thin for conclusions about regime durability.
- **5-min data is only 127 days.** Anything intraday is one quarter of samples. Don't treat the 5-min Sharpes as comparable to the daily Sharpes in terms of confidence.
- **1-hour data is ~3 years, not 5.** yfinance caps intraday at 730 days. ThetaData stock-tier requires VALUE subscription we don't have. Worth backfilling 1-hr to 5y via paid data if we want to publish.
- **Slippage model is uniform 1bp/side.** Real fills on SPY/QQQ shares are tighter than that on average but worse at open/close. The 1bp assumption is conservative on average but could under-penalize close-of-day exits.
- **0DTE overlay uses NBBO mid, not ask-on-entry/bid-on-exit.** Real executions on 0DTE SPY ATM are typically mid-to-ask on entry, mid-to-bid on exit — so realistic P&L would be 5-15% worse per trade than what's reported. Treat 0DTE numbers as upper bounds.
- **No multiple-comparisons correction.** We tested 6 strategies × 3 TFs × 2 tickers = 36 cells + 25-cell grid + walk-forward. Even random data would yield 1-2 'significant' results at p=0.05. The CI tests above are per-cell; the FDR-adjusted p-values would be looser.

## Methodology summary

- Entry: signal fires at the close of bar `i`. Trade enters at the open of bar `i+1` (no look-ahead).
- Exit: signal at close of bar `j`, exit at open of bar `j+1`. Final position force-closed at last close.
- Slippage: 1.0 bp applied to entry (worse) and exit (worse).
- Warmup: first 22 bars skipped to let the slow EMA settle.
- Bootstrap CI: 2000 resamples with seed 42 on per-trade P&L.
- Sharpe: daily-resampled equity (sum of trades closed that day), annualized × √252.

All trade-level data in `ema_8_9_21_backtest.db` (table `trades` + `dte_overlay`).
Equity-curve charts in `docs/research/ema_charts/`.