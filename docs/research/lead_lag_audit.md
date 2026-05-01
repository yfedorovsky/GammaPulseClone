# Test #7 — SPY/QQQ minute-OFI lead-lag

Sample: 124 cached days where both SPY and QQQ have data.
Per minute: summed quote-event OFI for each ticker, then Pearson correlation of SPY(t) vs QQQ(t + lag).


## Pooled correlation by lag

| Lag (min) | Mean corr | Std | n days |
|---|---|---|---|
| -5 | +0.0096 | 0.0725 | 124 |
| -3 | +0.0065 | 0.0729 | 124 |
| -2 | +0.0068 | 0.0768 | 124 |
| -1 | +0.0053 | 0.0952 | 124 |
| +0 | +0.3560 | 0.1520 | 124 |
| +1 | -0.0022 | 0.0974 | 124 |
| +2 | -0.0019 | 0.0753 | 124 |
| +3 | -0.0023 | 0.0748 | 124 |
| +5 | -0.0001 | 0.0724 | 124 |

## Verdict

Peak at lag=0 (+0.356). SPY and QQQ OFI move simultaneously at minute resolution. The current same-second cross-confirmation logic is appropriate; no v2 lag adjustment needed.