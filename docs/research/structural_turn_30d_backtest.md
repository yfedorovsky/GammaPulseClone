# Structural Turn — 30-day Backtest (BULLISH + BEARISH)

- Scan window: last **22 trading days**
- Tickers: SPY, QQQ, IWM, SPX
- Total qualified 5/5 fires: **4** (bullish 4, bearish 0)

**Note**: BEARISH fire returns are negated so positive = winner across both directions. BULLISH option P&L = ATM 0DTE call. BEARISH option P&L = ATM 0DTE put.

## Hit rates — SPOT (% with positive return)

| Horizon | n | Hit% | Avg | Median | P25 | P75 | Min | Max |
|---|---|---|---|---|---|---|---|---|
| +15min | 4 | 50.0% | +0.00% | -0.00% | -0.04% | +0.04% | -0.09% | +0.10% |
| +30min | 4 | 75.0% | +0.07% | +0.11% | +0.03% | +0.14% | -0.11% | +0.16% |
| +60min | 4 | 75.0% | +0.12% | +0.16% | +0.04% | +0.24% | -0.07% | +0.25% |
| EOD | 4 | 100.0% | +0.29% | +0.29% | +0.26% | +0.32% | +0.21% | +0.39% |

## Hit rates — OPTION P&L (0DTE ATM call, ask→bid)

| Horizon | n | Hit% | Avg | Median | P25 | P75 | Min | Max |
|---|---|---|---|---|---|---|---|---|
| +30min | 1 | 0.0% | -33% | -33% | -33% | -33% | -33% | -33% |
| +60min | 1 | 0.0% | -26% | -26% | -26% | -26% | -26% | -26% |
| EOD | 1 | 100.0% | +56% | +56% | +56% | +56% | +56% | +56% |
| MFE (mid) | 1 | — | +80% | +80% | — | — | +80% | +80% |

**Reading the option P&L**: positive numbers = trade made money. Compare avg-EOD to MFE-mean — if MFE is >> avg-EOD, exit discipline is leaving money on the table (the trade existed but you didn't hold).

## By tier

| Tier | Fires | Avg Opt EOD | Hit% Opt EOD | Avg MFE |
|---|---|---|---|---|
| A | 2 | +nan% | 0% | +nan% |
| B | 2 | +56% | 100% | +80% |

## By direction

| Direction | Fires | Avg Opt EOD | Hit% Opt EOD | Avg MFE |
|---|---|---|---|---|
| BULLISH | 4 | +56% | 100% | +80% |

## By ticker

| Ticker | Fires | Avg +30m | Avg +60m | Avg EOD | Hit% +30m | Hit% EOD |
|---|---|---|---|---|---|---|
| QQQ | 1 | +0.14% | +0.25% | +0.39% | 100% | 100% |
| SPY | 3 | +0.04% | +0.08% | +0.26% | 67% | 100% |

## Time of day

| Hour ET | Fires | Avg +30m | Hit% +30m |
|---|---|---|---|
| 10:00 | 1 | -0.11% | 0% |
| 11:00 | 1 | +0.08% | 100% |
| 13:00 | 2 | +0.15% | 100% |

### Tail behavior (T+60min)
- Big winners (>+0.5% spot): **0**
- Big losers (<-0.5% spot): **0**
- Asymmetry ratio: **0.00**

## All fires (chronological, with option P&L)

| Day | Time | Tkr | Dir | Tier | Spot | Strike | Entry$ | Opt+30m | Opt+60m | **Opt EOD** | MFE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-04-27 | 10:58 | SPY | 🟢 | 👁 B | $713.48 | 713C | $1.41 | -33% | -26% | **+56%** | +80% |
| 2026-04-28 | 11:31 | SPY | 🟢 | ⚡ A | $709.90 | 710C | — | — | — | **—** | — |
| 2026-04-28 | 13:03 | QQQ | 🟢 | 👁 B | $655.55 | 656C | — | — | — | **—** | — |
| 2026-04-28 | 13:18 | SPY | 🟢 | ⚡ A | $709.94 | 710C | — | — | — | **—** | — |
