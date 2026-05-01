# Test #2 — OFI predictive power on raw tape (v2 streaming OLS)

Streaming closed-form OLS over per-minute observations across all cached days. Memory is O(1) per (ticker × horizon) — no DataFrame concat, no in-memory pooling. Kills the 6 GB blow-up that crashed the v1 script.

Literature R² (Cont 2014, liquid index ETFs): 0.05-0.15


## Per-ticker, per-horizon

| Ticker | Horizon (min) | n | β | R² | t-stat |
|---|---|---|---|---|---|
| SPY | 5 | 43,986 | +2.488e-10 | 0.0000 | +0.83 |
| SPY | 15 | 43,966 | -9.669e-10 | 0.0002 | -3.02 |
| SPY | 30 | 43,814 | -8.064e-10 | 0.0001 | -2.31 |
| QQQ | 5 | 43,986 | -3.176e-11 | 0.0000 | -0.44 |
| QQQ | 15 | 43,966 | -7.160e-11 | 0.0000 | -0.59 |
| QQQ | 30 | 43,814 | +2.922e-10 | 0.0001 | +1.73 |

## Verdict

Maximum R² across all (ticker × horizon) cells is 0.0002. OFI does not show meaningful predictive power on next-N-minute returns in this 6-month sample. The Cont 2014 result does not transfer to this regime. **Do not build OFI gates** — the academic foundation isn't there for SPY/QQQ in 2025-26.