# Week Cohort Analysis — 2026-04-13 to 2026-04-17

**Roundtrips:** 91 | **Net:** $+11,568.87 | **WR:** 72.5%

Broker CSVs give date-only timestamps, so entry time-of-day uses the
matched SOE signal timestamp when confidence >= MEDIUM. Day-of-week
uses the broker trade date directly.

## By DTE at entry

| DTE at entry | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| 0DTE | 12 | $-378 | 67% | $-32 | 3 | 4 |
| 1-2DTE | 12 | $-276 | 58% | $-23 | 3 | 4 |
| 3-7DTE | 38 | $+2,207 | 66% | $+58 | 6 | 5 |
| 8-14DTE | 18 | $+5,730 | 89% | $+318 | 8 | 0 |
| 15-30DTE | 4 | $+284 | 75% | $+71 | 0 | 0 |
| 30+DTE | 7 | $+4,001 | 100% | $+572 | 5 | 0 |

## By Hold duration

| Hold duration | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| same-day | 46 | $+2,588 | 74% | $+56 | 9 | 6 |
| overnight | 41 | $+9,517 | 73% | $+232 | 16 | 6 |
| 2-3 days | 4 | $-537 | 50% | $-134 | 0 | 1 |

## By Direction

| Direction | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| CALL | 81 | $+12,945 | 78% | $+160 | 24 | 6 |
| PUT | 10 | $-1,376 | 30% | $-138 | 1 | 7 |

## By Day of week

| Day of week | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| Mon | 18 | $+4,537 | 89% | $+252 | 6 | 2 |
| Tue | 12 | $+633 | 50% | $+53 | 1 | 2 |
| Wed | 18 | $+4,180 | 72% | $+232 | 8 | 2 |
| Thu | 8 | $+1,020 | 88% | $+128 | 2 | 1 |
| Fri | 35 | $+1,199 | 69% | $+34 | 8 | 6 |

## By Match confidence

| Match confidence | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| STRONG | 44 | $+6,564 | 82% | $+149 | 17 | 4 |
| MEDIUM | 24 | $+2,203 | 54% | $+92 | 3 | 6 |
| WEAK | 11 | $+2,112 | 91% | $+192 | 3 | 1 |
| NONE | 12 | $+689 | 58% | $+57 | 2 | 2 |

## By Broker

| Broker | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| fidelity | 63 | $+11,170 | 76% | $+177 | 18 | 7 |
| etrade | 28 | $+398 | 64% | $+14 | 7 | 6 |

## By Entry time-of-day (n=79 with signal match)

| Entry time-of-day (n=79 with signal match) | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |
|---|---:|---:|---:|---:|---:|---:|
| 09:30-10:00 open | 23 | $+1,942 | 65% | $+84 | 5 | 5 |
| 10:00-11:30 morning | 31 | $+4,349 | 87% | $+140 | 7 | 0 |
| 11:30-13:30 lunch | 19 | $+5,041 | 84% | $+265 | 10 | 1 |
| 13:30-15:00 PM | 1 | $-414 | 0% | $-414 | 0 | 1 |
| 15:00-16:00 power hour | 1 | $+776 | 100% | $+776 | 1 | 0 |
| post-close | 4 | $-814 | 0% | $-204 | 0 | 4 |

## DTE × Direction (does short-DTE put buying kill us?)

| Bucket | CALL N | CALL P&L | CALL WR | PUT N | PUT P&L | PUT WR |
|---|---:|---:|---:|---:|---:|---:|
| 0DTE | 11 | $-462 | 64% | 1 | $+84 | 100% |
| 1-2DTE | 7 | $+939 | 86% | 5 | $-1,215 | 20% |
| 3-7DTE | 34 | $+2,452 | 71% | 4 | $-245 | 25% |
| 8-14DTE | 18 | $+5,730 | 89% | 0 | $+0 | 0% |
| 15-30DTE | 4 | $+284 | 75% | 0 | $+0 | 0% |
| 30+DTE | 7 | $+4,001 | 100% | 0 | $+0 | 0% |

## Ticker Repeat Behavior

**Tickers traded 3+ times this week:** 14

| Ticker | N | Net P&L | WR% | Wins | Losses | Avg Hold |
|---|---:|---:|---:|---:|---:|---:|
| AXTI | 6 | $+2,755 | 100% | 6 | 0 | 0.8d |
| RDDT | 3 | $+1,788 | 100% | 3 | 0 | 0.7d |
| TSM | 8 | $+1,586 | 100% | 8 | 0 | 1.0d |
| TSLA | 5 | $+798 | 80% | 4 | 1 | 0.6d |
| DELL | 4 | $+765 | 100% | 4 | 0 | 0.5d |
| MSFT | 3 | $+451 | 67% | 2 | 1 | 0.3d |
| NFLX | 8 | $+450 | 75% | 6 | 2 | 0.0d |
| AAOI | 6 | $+336 | 50% | 3 | 3 | 0.2d |
| SPY | 5 | $+64 | 80% | 4 | 1 | 0.2d |
| SNDK | 4 | $+23 | 50% | 2 | 2 | 0.5d |
| MU | 4 | $+20 | 50% | 2 | 2 | 0.0d |
| QQQ | 3 | $-421 | 33% | 1 | 2 | 0.7d |
| LITE | 5 | $-529 | 20% | 1 | 4 | 1.2d |
| AMAT | 4 | $-814 | 0% | 0 | 4 | 0.0d |

## Scaled-In Positions (same contract ≥3 entries)

| Contract | N | Net P&L | WR% | Avg Entry | First→Last Entry |
|---|---:|---:|---:|---:|---:|
| AMAT $395C 2026-04-17 | 4 | $-814 | 0% | $2.75 | $2.50→$3.20 |
| AAOI $200C 2026-04-24 | 5 | $-46 | 40% | $1.51 | $1.38→$1.15 |
| TSM $400C 2026-04-17 | 4 | $+349 | 100% | $1.61 | $1.56→$1.66 |
| NFLX $100C 2026-04-24 | 4 | $+349 | 100% | $0.67 | $0.55→$0.89 |
| TSM $390C 2026-04-17 | 4 | $+1,238 | 100% | $2.89 | $2.85→$2.97 |
| RDDT $160C 2026-04-24 | 3 | $+1,788 | 100% | $2.44 | $2.40→$2.46 |
| AXTI $70C 2026-08-21 | 3 | $+2,302 | 100% | $22.82 | $22.82→$22.82 |

## Signal Lag — Winners vs Losers (attributed trades only)

*Lag = minutes between signal fire and broker entry. Negative = signal fired before entry.*

- **Winners:** N=59, median=663m, mean=666m
- **Losers:** N=20, median=663m, mean=714m

## Key Patterns

- **PUT vs CALL gap:** 10 puts, 30% WR, $-1,376 vs 81 calls, 78% WR, $+12,945.
- **Short-dated (0-2DTE):** 24 trades, 62% WR, $-654.
- **Scale-in positions (7 contracts, 27 fills):** total $+5,165.
- **Weekday spread:** best = Mon ($+4,537), worst = Tue ($+633).
- **Hold duration:** same-day 46 trades 74% WR $+2,588; held 45 trades 71% WR $+8,981.

## Caveats

- **Sample size**: 91 trades / 5 days. Cells with N<5 are noise.
- **Time-of-day is approximate**: uses matched SOE signal timestamp
  when available (MEDIUM+ confidence); broker timestamps are day-only.
- **Survivorship**: only trades taken. Signals skipped aren't here.
- **Scale-in contracts**: FIFO-paired at import, so partial-fill
  sequences may split across multiple roundtrips (each fill → one rt).
