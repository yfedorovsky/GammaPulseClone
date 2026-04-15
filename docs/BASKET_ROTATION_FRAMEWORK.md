# Point-in-Time Quarterly Basket Rotation Framework

**Purpose:** Eliminate survivorship/hindsight bias from the GammaPulse backtest by replacing the curated sector list with a rule-based, point-in-time universe selection methodology.

---

## 1. What Is Still Credible

- Options beat stock 5.3x on same signals (capital efficiency is real)
- Edge survives outlier removal, time splits, and 5x spread friction
- Fast resolution (2-3 day avg hold) matches momentum literature
- Power Hour timing effect is academically supported
- 57% of losers had +25% MFE before dying — exit ladder is additive
- The OPTIONS WRAPPER is the right monetization — this is settled

## 2. What Is Methodologically Broken

- **Universe was selected with hindsight**: photonics/memory/space/AI-infra are the sectors we KNOW won in 2025-2026
- **Backtest ran on forward-selected winners**: every ticker in the universe survived and outperformed
- **This inflates everything**: WR, avg P&L, total return, alpha vs B&H
- **The fix is NOT to remove themes** — it's to select themes using ONLY data available at each rebalance date

## 3. Recommended Point-in-Time Basket Framework

### Universe Construction Rules (applied at each rebalance date)

**Step 1: Start with a BROAD universe (no hindsight)**
- All US equities with options
- Price > $5
- Market cap > $2B
- Avg daily volume > 500K shares
- Options OI > 1,000 contracts (tradeable)
- This gives ~800-1,200 names at any point in time

**Step 2: Compute sector/theme relative strength**
- Use GICS sectors OR a simple industry grouping (Finviz, Yahoo)
- For each sector, compute:
  - 3-month sector ETF return (if sector ETF exists)
  - % of sector members above their 50-day MA ("breadth")
  - Median 20-day RS score of sector members vs SPY
- Rank sectors by composite score: `0.4 * 3mo_return + 0.3 * breadth + 0.3 * median_RS`

**Step 3: Select top N sectors**
- **Top 3 sectors** = the "hot baskets" for the quarter
- These are the ONLY sectors the strategy trades for the next 3 months
- Within each top sector, the daily scanner (SMA/EMA/RS) selects individual names

**Step 4: Within-sector stock selection (daily, NOT frozen)**
- Apply Mir's daily filters: SMA 20/50/200, EMA 21>50, top-quartile RS within sector
- This part is dynamic — stocks enter and exit the tradeable list daily
- But the SECTOR selection is frozen for the quarter

### Why This Works
- Sector selection uses ONLY backward-looking data (3-month returns, current breadth)
- No forward-looking information contaminates the basket
- The daily stock scanner handles individual name selection dynamically
- If a sector stops performing mid-quarter, trades simply stop triggering (SMA/EMA filters fail)

## 4. Recommended Rebalance Schedule

**Quarterly with monthly emergency refresh:**

| Event | Action |
|-------|--------|
| Quarter start (Jan 1, Apr 1, Jul 1, Oct 1) | Full sector ranking, select top 3, freeze |
| Monthly check (1st of each month) | If a frozen sector drops below median RS, replace with next-best sector |
| Emergency: SPY 20d < -5% | Pause ALL entries until regime recovers |

**Why quarterly, not monthly:**
- Monthly rebalancing = 4x more parameter sensitivity
- Quarterly gives sectors time to develop (momentum literature says 3-12 month horizons)
- Monthly emergency refresh catches regime breaks without over-trading

**Why top 3, not top 5:**
- 3 sectors = ~100-200 names (plenty for daily scanner)
- 5 sectors = too broad, dilutes the momentum concentration that IS the edge
- Man Group research: momentum IS a concentrated sector bet — embrace that, just do it ex ante

## 5. Correct Backtest Protocol

### Walk-Forward Design

```
Period 1: Q1 2025 (Jan-Mar)
  - Basket selection: Use data through Dec 31, 2024
  - Rank sectors by composite score
  - Freeze top 3 sectors
  - Run daily scanner within frozen baskets
  - Record all trades

Period 2: Q2 2025 (Apr-Jun)
  - Basket selection: Use data through Mar 31, 2025
  - Re-rank sectors
  - Freeze new top 3
  - Run scanner
  - Record trades

... continue quarterly through Apr 2026
```

### Anti-Bias Rules
1. **No parameter changes** during walk-forward (use v3.0 frozen config)
2. **Sector ranking uses ONLY trailing data** (3-month return, breadth as of rebalance date)
3. **Stock scanner uses ONLY current-day data** (SMA/EMA computed from price history up to that day)
4. **No ticker exclusions or additions** based on future knowledge
5. **Holdout period**: Q1 2026 (Jan-Mar) is NEVER used for parameter tuning — results are final

### Data Requirements
- Sector ETF prices for ranking (XLK, XLF, XLV, etc. — available from Yahoo free)
- Broad universe stock prices for breadth computation
- Options chains for the selected universe (EODHD)
- All data timestamped and never accessed ahead of its date

## 6. Required Comparison Tests

Run these 6 variants side-by-side on the SAME time period:

| Variant | Universe | Description |
|---------|----------|-------------|
| A | **Current curated** | Photonics/memory/space/AI-infra (the original backtest) |
| B | **Point-in-time quarterly** | Top 3 sectors by composite score, frozen quarterly |
| C | **Point-in-time monthly** | Top 3 sectors, refreshed monthly |
| D | **Scanner-only** | No sector filter, scanner selects from entire broad universe |
| E | **Random sectors** | Randomly select 3 sectors each quarter (null hypothesis) |
| F | **Bottom 3 sectors** | Worst-performing sectors (counter-test) |

**What each comparison tells us:**

- A vs B: How much of the edge was hindsight vs real momentum selection?
- B vs C: Does monthly refresh add value or just noise?
- B vs D: Does sector concentration help or hurt?
- B vs E: Is the sector selection adding alpha over random?
- B vs F: Does buying momentum in LOSING sectors work? (should fail)
- All variants: run with stock vs options to confirm monetization

## 7. Most Likely Outcome After Bias Removal

### Best Case
- Point-in-time quarterly baskets capture 60-80% of the curated backtest's edge
- The AI/semi/photonics sectors WOULD have been selected ex ante (they were clearly the strongest RS sectors throughout 2025)
- Avg P&L drops from +142% to ~+80-100% but remains strongly positive
- The framework IS the edge — selecting hot sectors and buying momentum calls within them

### Realistic Case
- Point-in-time baskets capture 40-60% of the curated edge
- Some quarters select wrong sectors (miss photonics, pick energy instead)
- Avg P&L drops to ~+40-60% after realistic spreads + bias removal
- Still positive expectancy but much more modest
- The strategy works in trending environments and underperforms in rotation/chop

### Failure Case
- Point-in-time baskets fail to consistently select the winning sectors
- The edge was 80%+ hindsight: we only traded photonics because we KNEW it would work
- After bias removal + realistic spreads, avg P&L drops to +10-15% or below
- Not enough edge to justify options over stock on risk-adjusted basis
- Strategy becomes "buy calls in whatever sector is hot" — a trivial momentum overlay

### My Honest Prior
I'd put it at:
- 30% chance best case (most of the edge survives)
- 50% chance realistic case (edge compressed but real)
- 20% chance failure case (edge was mostly hindsight)

Even the realistic case is still a tradeable strategy. The failure case means pivot to stock + simple sector ETF rotation instead of single-name options.

## 8. Concrete Implementation Checklist

### Phase 1: Data Setup (1-2 hours)
- [ ] Download SPDR sector ETF prices (XLK, XLF, XLV, XLE, XLI, XLY, XLC, XLP, XLRE, XLU, XLB) from Yahoo — free, 2 years
- [ ] Download broad universe stock prices for breadth computation (Russell 1000 or S&P 500 members — Yahoo free)
- [ ] Build sector membership mapping (ticker -> GICS sector)

### Phase 2: Basket Selector (2-3 hours)
- [ ] Write `backtest/basket_selector.py`:
  - Input: date, sector ETF prices, stock prices
  - Output: top 3 sectors for the quarter
  - Method: 0.4 * 3mo_return + 0.3 * breadth + 0.3 * median_RS
- [ ] Verify selector produces reasonable baskets for each quarter of 2025-2026
- [ ] Log which sectors were selected and which were rejected

### Phase 3: Walk-Forward Backtest (2-3 hours)
- [ ] Write `backtest/walk_forward.py`:
  - Quarterly rebalance loop
  - Point-in-time basket selection
  - Daily scanner within frozen baskets
  - Same Mir rules (SMA/EMA/RS, exit ladder, stops)
  - Same DTE (7-14), same contract selection
- [ ] Run all 6 comparison variants (A through F)

### Phase 4: Analysis (1 hour)
- [ ] Compare A (curated) vs B (point-in-time) — the key test
- [ ] Run slippage stress on variant B (5% to 25%)
- [ ] Report results with honest framing

### Phase 5: Decision (30 minutes)
- [ ] If B captures >50% of A's edge: proceed to paper trading with point-in-time baskets
- [ ] If B captures 25-50%: the edge is narrower but still worth pursuing at micro size
- [ ] If B captures <25%: the original result was mostly hindsight; pivot strategy

---

## Key Principle

> The strategy may still be real even if the original backtest was overstated. The goal now is not to defend the original result, but to discover the most realistic version of the edge.
