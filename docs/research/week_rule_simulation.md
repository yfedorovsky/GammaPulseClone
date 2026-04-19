# Rule Simulation — 2026-04-13 to 2026-04-17

**Baseline:** 91 trades, $+11,568.87, 72.5% WR

*Each row shows what the week would look like if the rule had been in effect.*
*"Kept" = trades that passed the rule. "Blocked" = trades the rule would have stopped.*

## Single-rule simulation

| Rule | Blocked N | Blocked P&L | Blocked WR | Kept N | Kept P&L | Kept WR | Δ vs baseline |
|---|---:|---:|---:|---:|---:|---:|---:|
| #1 Block puts (non-bear regime) | 10 | $-1,376 | 30% | 81 | $+12,945 | 78% | $+1,376 |
| #2 Block 0-2DTE auto-open | 24 | $-654 | 62% | 67 | $+12,222 | 76% | $+654 |
| #3 Require STRONG match (all sources) | 35 | $+4,316 | 66% | 56 | $+7,253 | 77% | $-4,316 |
| #3b Block only SOE_B+ MEDIUM | 10 | $-777 | 30% | 81 | $+12,346 | 78% | $+777 |
| #3c Require STRONG for SOE only | 22 | $+827 | 64% | 69 | $+10,742 | 75% | $-827 |
| #5 Delay auto-open to 10:00+ | 23 | $+1,942 | 65% | 68 | $+9,627 | 75% | $-1,942 |

## Combined-rule simulation

| Combination | Blocked N | Blocked P&L | Blocked WR | Kept N | Kept P&L | Kept WR | Δ vs baseline |
|---|---:|---:|---:|---:|---:|---:|---:|
| #1 + #2 (puts + short DTE) | 28 | $-899 | 57% | 63 | $+12,468 | 79% | $+899 |
| #1 + #2 + #3b (targeted SOE_B+ MEDIUM) | 34 | $-862 | 56% | 57 | $+12,431 | 82% | $+862 |
| #1 + #2 + #3c (STRONG for SOE only) | 43 | $+833 | 65% | 48 | $+10,736 | 79% | $-833 |
| #1 + #2 + #3 (blunt) | 53 | $+4,333 | 68% | 38 | $+7,236 | 79% | $-4,333 |

## What each rule blocked

### #1 Block puts (non-bear regime)

Blocks **10 trades**, $-1,376 total, 30% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| META | $665 | 2026-04-17 | P | 2 | $-518 | LOSS | BIG_FLOW |
| LITE | $820 | 2026-04-17 | P | 1 | $-414 | LOSS | SOE_B+ |
| QQQ | $620 | 2026-04-17 | P | 3 | $-297 | LOSS | FLOW_ALERT |
| QQQ | $630 | 2026-04-17 | P | 2 | $-207 | LOSS | BIG_FLOW |
| SPY | $687 | 2026-04-15 | P | 1 | $-156 | LOSS | BIG_FLOW |
| NFLX | $90 | 2026-04-24 | P | 7 | $-60 | LOSS | BIG_FLOW |
| NFLX | $90 | 2026-04-24 | P | 7 | $-49 | LOSS | BIG_FLOW |
| TSLA | $380 | 2026-04-17 | P | 2 | $+81 | WIN | BIG_FLOW |
| QQQ | $645 | 2026-04-17 | P | 0 | $+84 | WIN | BIG_FLOW |
| ADBE | $245 | 2026-04-24 | P | 7 | $+162 | WIN | SOE_B+ |

### #2 Block 0-2DTE auto-open

Blocks **24 trades**, $-654 total, 62% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| META | $665 | 2026-04-17 | P | 2 | $-518 | LOSS | BIG_FLOW |
| LITE | $820 | 2026-04-17 | P | 1 | $-414 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-248 | LOSS | SOE_B+ |
| QQQ | $630 | 2026-04-17 | P | 2 | $-207 | LOSS | BIG_FLOW |
| AMAT | $395 | 2026-04-17 | C | 0 | $-198 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-188 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-178 | LOSS | SOE_B+ |
| SPY | $687 | 2026-04-15 | P | 1 | $-156 | LOSS | BIG_FLOW |
| MSFT | $400 | 2026-04-15 | C | 1 | $-1 | LOSS | FLOW_ALERT |
| SPY | $712 | 2026-04-17 | C | 0 | $+16 | WIN | BIG_FLOW |
| VRT | $310 | 2026-04-17 | C | 0 | $+20 | WIN | MANUAL |
| SPY | $710 | 2026-04-17 | C | 0 | $+22 | WIN | BIG_FLOW |
| SPY | $710 | 2026-04-17 | C | 0 | $+38 | WIN | BIG_FLOW |
| IWM | $264 | 2026-04-14 | C | 1 | $+40 | WIN | BIG_FLOW |
| NFLX | $100 | 2026-04-17 | C | 0 | $+40 | WIN | BIG_FLOW |
| _…9 more_ | | | | | | | |

### #3 Require STRONG match (all sources)

Blocks **35 trades**, $+4,316 total, 66% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| LITE | $820 | 2026-04-17 | P | 1 | $-414 | LOSS | SOE_B+ |
| SNDK | $1050 | 2026-04-17 | C | 3 | $-262 | LOSS | FLOW_ALERT |
| AMAT | $395 | 2026-04-17 | C | 0 | $-248 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-198 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-188 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-178 | LOSS | SOE_B+ |
| NFLX | $90 | 2026-04-24 | P | 7 | $-60 | LOSS | BIG_FLOW |
| SNDK | $1000 | 2026-04-24 | C | 9 | $-54 | LOSS | FLOW_ALERT |
| AAOI | $200 | 2026-04-24 | C | 7 | $-52 | LOSS | SOE_B+ |
| NFLX | $90 | 2026-04-24 | P | 7 | $-49 | LOSS | BIG_FLOW |
| AAOI | $200 | 2026-04-24 | C | 7 | $-33 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-8 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+10 | WIN | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+37 | WIN | SOE_B+ |
| TSM | $400 | 2026-04-17 | C | 4 | $+41 | WIN | SOE_B+ |
| _…20 more_ | | | | | | | |

### #3b Block only SOE_B+ MEDIUM

Blocks **10 trades**, $-777 total, 30% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| AMAT | $395 | 2026-04-17 | C | 0 | $-248 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-198 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-188 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-178 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-52 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-33 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-8 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+10 | WIN | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+37 | WIN | SOE_B+ |
| DELL | $190 | 2026-04-17 | C | 4 | $+83 | WIN | SOE_B+ |

### #3c Require STRONG for SOE only

Blocks **22 trades**, $+827 total, 64% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| LITE | $820 | 2026-04-17 | P | 1 | $-414 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-248 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-198 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-188 | LOSS | SOE_B+ |
| AMAT | $395 | 2026-04-17 | C | 0 | $-178 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-52 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-33 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $-8 | LOSS | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+10 | WIN | SOE_B+ |
| AAOI | $200 | 2026-04-24 | C | 7 | $+37 | WIN | SOE_B+ |
| TSM | $400 | 2026-04-17 | C | 4 | $+41 | WIN | SOE_B+ |
| TSM | $400 | 2026-04-17 | C | 4 | $+49 | WIN | SOE_B+ |
| TSM | $400 | 2026-04-17 | C | 4 | $+56 | WIN | SOE_B+ |
| DELL | $190 | 2026-04-17 | C | 4 | $+83 | WIN | SOE_B+ |
| SNDK | $1000 | 2026-04-24 | C | 7 | $+109 | WIN | SOE_A |
| _…7 more_ | | | | | | | |

### #5 Delay auto-open to 10:00+

Blocks **23 trades**, $+1,942 total, 65% WR

| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |
|---|---:|---|---|---:|---:|---|---|
| META | $665 | 2026-04-17 | P | 2 | $-518 | LOSS | BIG_FLOW |
| MU | $480 | 2026-04-24 | C | 7 | $-334 | LOSS | SOE_B+ |
| QQQ | $630 | 2026-04-17 | P | 2 | $-207 | LOSS | BIG_FLOW |
| SPY | $687 | 2026-04-15 | P | 1 | $-156 | LOSS | BIG_FLOW |
| NFLX | $90 | 2026-04-24 | P | 7 | $-60 | LOSS | BIG_FLOW |
| NFLX | $90 | 2026-04-24 | P | 7 | $-49 | LOSS | BIG_FLOW |
| MU | $480 | 2026-04-24 | C | 7 | $-24 | LOSS | SOE_B+ |
| MSFT | $400 | 2026-04-15 | C | 1 | $-1 | LOSS | FLOW_ALERT |
| SPY | $712 | 2026-04-17 | C | 0 | $+16 | WIN | BIG_FLOW |
| SPY | $710 | 2026-04-17 | C | 0 | $+22 | WIN | BIG_FLOW |
| SPY | $710 | 2026-04-17 | C | 0 | $+38 | WIN | BIG_FLOW |
| COIN | $180 | 2026-04-24 | C | 11 | $+40 | WIN | SOE_B+ |
| IWM | $264 | 2026-04-14 | C | 1 | $+40 | WIN | BIG_FLOW |
| NFLX | $100 | 2026-04-17 | C | 0 | $+40 | WIN | BIG_FLOW |
| UNH | $327.5 | 2026-04-24 | C | 7 | $+64 | WIN | SOE_B+ |
| _…8 more_ | | | | | | | |

## Interpretation

- **Negative Δ means the rule cost money** (cut winners too).
- **Positive Δ means the rule improved net P&L** (cut losers more than winners).
- **Kept WR up + fewer trades** is the ideal — same signal, less noise.
- This is ONE WEEK. Treat deltas under $1000 as noise until multi-week validation.
