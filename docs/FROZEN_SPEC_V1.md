# GammaPulse Production Strategy — Frozen Spec v1.0

**Frozen:** April 14, 2026
**Status:** PAPER TRADING CANDIDATE
**Rule:** NO core-rule changes until 50 paper trades completed

---

## Strategy Summary

Mir's bullish momentum rules select the ticker and direction.
Point-in-time quarterly basket rotation selects the sectors.
GEX levels provide entry/target/stop context.
Enter during PM window on 7-14 DTE calls.

---

## Universe Selection (Point-in-Time Quarterly)

### Basket Selection (quarterly, frozen for 3 months)
- Composite score: 0.4 * percentile(3mo_sector_ETF_return) + 0.3 * percentile(breadth) + 0.3 * percentile(median_RS)
- Select top 3 SPDR sectors
- Freeze for the quarter
- No mid-quarter changes (no emergency refresh in v1)

### Stock Selection (daily, within frozen baskets)
- Price > $5, Market Cap > $2B, Avg Volume > 500K
- Price above SMA 20, SMA 50, SMA 200 (strict)
- EMA 21 > EMA 50
- Top-quartile relative strength within sector

### Regime Filter
- Skip ALL entries when SPY 20-day return < 0

### Day Filter
- Skip Mondays

---

## Contract Selection

- **DTE:** 7-14 days (target 10 DTE)
- **Strike:** 1st OTM call
- **Direction:** BULL only

---

## Entry Timing

- **Daily signal:** generated from EOD chain data
- **Preferred entry:** PM window (2:00-4:00 PM ET)
- **Power Hour (3:00-4:00)** is strongest but not required
- **T+1 execution:** signal day T, enter day T+1

---

## Exit Rules (FROZEN)

| Trigger | Action |
|---------|--------|
| +25% on contract | Sell half, move stop to breakeven |
| +100% on contract | Sell remaining or trail |
| -50% on contract | Hard stop, exit all |

---

## Position Sizing

- **1.5% of account per trade** (fixed, Kelly suspended)
- **Max 5 open positions**
- **Max 1 position per ticker**

---

## Circuit Breaker

| Trigger | Action |
|---------|--------|
| 3 consecutive losses | Reduce to 1% sizing |
| 5 consecutive losses | Paper trade only |
| WR < 45% over 30 trades | Full stop, reassess |
| Max drawdown 8% | Full stop |

---

## Validation Results (Walk-Forward)

```
PIT Quarterly: 239 trades, 52.7% WR, +138.5% avg P&L
Captures 99% of curated edge
Beats scanner-only by +27% avg
Survives 5x spread friction stress test
Edge survives time split (60% first half, 54% second half)
Options beat stock 5.3x on same signals
```

---

## Paper Trading Protocol

1. **Start date:** April 15, 2026
2. **Current quarterly basket:** Select top 3 sectors using data through April 1, 2026
3. **Log every signal** with entry price, fill price, slippage
4. **No parameter changes** for 50 trades
5. **Track:** WR, avg P&L, slippage vs model, fill quality, missed trades
6. **Decision at 50 trades:**
   - WR > 45% + positive EV: go tiny live
   - WR 35-45%: continue paper trading
   - WR < 35%: reassess strategy

---

## What Is NOT Allowed (Until 50 Paper Trades)

- No new indicators
- No DTE changes
- No exit ladder changes
- No regime filter changes
- No ticker additions outside quarterly basket
- No architecture redesign
- No "just one more improvement"

The biggest danger is now over-tinkering.
The strategy is good enough to validate forward.
