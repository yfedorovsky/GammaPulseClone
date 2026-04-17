# Signal Outcome Backtest — 2026-04-14 to 2026-04-17

**Method:** Walk-forward through 5-min Tradier bars from signal timestamp. WIN = spot hit target price. LOSS = spot hit stop price. AMBIGUOUS = both hit in same bar.

Total signals analyzed: 745

## Raw Win Rate By Grade

| Grade | Fires | WIN | LOSS | PENDING | AMBIG | Win Rate (on resolved) |
|---|---:|---:|---:|---:|---:|---:|
| A | 56 | 5 | 7 | 37 | 0 | **41.7%** |
| B+ | 689 | 152 | 185 | 292 | 0 | **45.1%** |

## Top 20 Tickers

| Ticker | Fires | WIN | LOSS | PEND | WR% |
|---|---:|---:|---:|---:|---:|
| DIA | 19 | 0 | 11 | 8 | 0.0% |
| BABA | 17 | 10 | 2 | 5 | 83.3% |
| SPX | 17 | 2 | 3 | 12 | 40.0% |
| SPY | 16 | 6 | 4 | 6 | 60.0% |
| MSFT | 16 | 10 | 1 | 5 | 90.9% |
| PLTR | 15 | 2 | 8 | 5 | 20.0% |
| AAPL | 15 | 4 | 4 | 7 | 50.0% |
| GOOG | 14 | 6 | 3 | 5 | 66.7% |
| PFE | 14 | 0 | 4 | 10 | 0.0% |
| MSTR | 12 | 7 | 3 | 2 | 70.0% |
| IBIT | 12 | 2 | 5 | 5 | 28.6% |
| AMD | 12 | 7 | 2 | 3 | 77.8% |
| QQQ | 12 | 6 | 1 | 5 | 85.7% |
| DIS | 12 | 0 | 7 | 5 | 0.0% |
| GOOGL | 12 | 1 | 4 | 7 | 20.0% |
| JPM | 12 | 0 | 6 | 6 | 0.0% |
| F | 11 | 2 | 9 | 0 | 18.2% |
| TSM | 11 | 1 | 6 | 4 | 14.3% |
| META | 11 | 2 | 3 | 6 | 40.0% |
| RBLX | 11 | 2 | 7 | 2 | 22.2% |

## By Hour (ET)

| Hour | Fires | WIN | LOSS | WR% |
|---|---:|---:|---:|---:|
| 07:00 | 31 | 22 | 8 | 73.3% |
| 08:00 | 36 | 24 | 11 | 68.6% |
| 09:00 | 58 | 9 | 14 | 39.1% |
| 10:00 | 123 | 28 | 32 | 46.7% |
| 11:00 | 47 | 8 | 8 | 50.0% |
| 12:00 | 129 | 22 | 39 | 36.1% |
| 13:00 | 38 | 8 | 9 | 47.1% |
| 14:00 | 140 | 19 | 29 | 39.6% |
| 15:00 | 50 | 7 | 20 | 25.9% |
| 16:00 | 93 | 10 | 22 | 31.2% |

## Methodology Caveats

- **5-min bar resolution:** fast wick-through moves are detected; tick-level precision is not. For signals with tight target/stop bands this may miss inter-candle noise. Generally this favors WIN classification since rapid spikes register on 5-min bars.
- **No option price tracking:** spot hits target doesn't guarantee the option itself would have paid 1R+ return (depends on delta, IV crush, theta). This backtest measures SPOT-BASED signal quality only. Option-level P&L would be different.
- **Multiple signals per ticker:** a ticker firing 18 B+ signals in 4 days produces 18 rows here. Treated as independent observations even though they may be re-alerts of the same underlying setup.
- **No dedup by time:** signals fired within minutes of each other on the same ticker are counted separately.
- **Sample size by grade:** small A-grade cohort means confidence intervals are wide.
