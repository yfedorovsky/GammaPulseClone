# Production Strategy — For Web App Integration

**Version:** 4.0 (Mir Momentum + GEX Quality Gate)
**Last Updated:** April 14, 2026
**Status:** Backtest validated on 34 tickers. Ready for live integration.

---

## The Strategy in One Sentence

Mir's bullish momentum rules pick the ticker and direction. GEX levels provide entry/target/stop. Enter during PM window (2:00-4:00 PM). Hold 2-3 days on 7-14 DTE contracts.

---

## Backtest Results (Full 34-Ticker Universe)

```
Period: Jan 2025 - Apr 2026 (15 months)
Trades: 256 (sector leaders only, no SPY/QQQ)
Win Rate: 59.0%
Avg P&L: +142.5% per trade
Avg Hold: 2.7 days (median 2 days)

Top Tickers:
  LITE:  78% WR, +181.3% avg (18 trades)
  AXTI:  55% WR, +1653% avg (11 trades -- huge tail winners)
  MU:    59% WR, +77.5% avg (49 trades)
  VRT:   64% WR, +91.5% avg (39 trades)
  RKLB:  60% WR, +87.6% avg (47 trades)
  ANET:  54% WR, +64.8% avg (28 trades)
  COHR:  59% WR, +60.0% avg (39 trades)

DTE Grid Winner: 7-14 DTE >> 14-21 >> 21-35 >> 3-7
Hold Distribution: 46% resolve in 1-2 days, 80% within 5 days
```

---

## Signal Generation (Mir's Rules)

### Ticker Filter (must pass ALL)
- Price > $5
- Market Cap > $2B
- Avg Volume > 500K
- Price above SMA 20, SMA 50, SMA 200 (strict)
- EMA 21 > EMA 50 (trend confirmation)
- Ticker in approved sector list

### Approved Sectors
```
Photonics:      AAOI, LITE, COHR, GLW, CIEN, AXTI, TSEM
Semi Equipment: AMAT, LRCX, AEHR, TER
Memory:         MU, WDC
Space:          RKLB, ASTS, SATL, VOYG
AI/Compute:     ANET, VRT, NET, SNOW, PLTR
```

### Relative Strength Filter
Rank tickers by 20-day return within their sector. Only trade top-quartile RS names.

### Regime Filter
Skip ALL entries when SPY 20-day return < 0 (bearish macro).

### Day Filter
Skip Mondays (34% WR vs 46-51% other days).

---

## GEX Quality Gate

GEX does NOT generate the signal. It validates the Mir signal:

- **King above spot** = bullish structure confirmed (magnet pull up)
- **Floor below spot** = support confirmed (dealers buy dips)
- **Positive gamma regime** = dealers absorb volatility (stable)
- **King distance 0.5-3%** = target is reachable

If GEX contradicts Mir (e.g., negative king above = resistance), reduce size or skip.

---

## Contract Selection

- **DTE**: 7-14 days (sweet spot from grid search)
- **Strike**: 1st OTM call (ATM also works, slightly lower EV)
- **Target**: GEX king level or +100% on contract
- **Stop**: -50% on contract value (Mir's rule: "if contracts cut to 50%, let it go")

---

## Entry Timing

### Daily Signal
Generated at market close from EOD chain data. Fires next day.

### Intraday Entry
Best window: **2:00 PM - 4:00 PM ET**
- Power Hour (3:00-4:00): 45% WR, +0.52% avg
- PM Momentum (1:30-3:00): 40% WR, +0.28% avg  
- Morning (10:30-11:30): marginal, skip

### GEX Level Entry (intraday)
When price reaches king/floor during PM window = optimal entry point.
Mir from RAG: "SPY 582.5 should give a good entry to target 585"
These ARE the GEX levels.

---

## Exit Rules

### Exit Ladder
| Trigger | Action |
|---------|--------|
| +25% on contract | Sell half, move stop to breakeven |
| +100% on contract | Sell remaining (or trail) |
| -50% on contract | Hard stop, exit all |

### Mir's Profit Taking (from RAG)
- "Half out at least if it hits 100%"
- "On a rollup I'm never risking the whole bag — 1/3 of original"
- In strong trends: let runners ride
- In chop: take base hits (+30-50%), tight stops

---

## Position Sizing

### Validation Phase (first 50 live trades)
- 1.5% of account per trade ($1,500 on $100K)
- Max 3 open positions
- No 0DTE (1DTE minimum)

### After Validation
- Quarter-Kelly with real payoff ratios from live trades
- Max 10% single position (HIGH conviction)
- Max 5% per trade default
- Max 30% correlated sector exposure

---

## Kill Switches

| Trigger | Action |
|---------|--------|
| SPY 20d return < 0 | Pause all entries (regime filter) |
| 3 consecutive losses | Reduce to 1% sizing |
| 5 consecutive losses | Paper trade only |
| WR < 45% over 30 trades | Full stop, reassess |
| Max drawdown 8% | Full stop |

---

## What the Live App Should Do

### Signal Engine Changes
1. Switch SOE from bearish-only BREAKDOWN to **bullish Mir momentum**
2. Add Mir's filters: SMA 20/50/200, EMA 21>50, RS ranking
3. Generate signals on approved sector tickers (not SPY/QQQ for swings)
4. Contract: 7-14 DTE, 1st OTM call
5. Fire during PM window (2:00-4:00 PM)

### Telegram Alerts
Format:
```
BUY MU $95 CALL 7DTE
Entry: $3.50 | Target: $7.00 (+100%) | Stop: $1.75 (-50%)
GEX: King $97 (magnet) | Floor $93 | Regime POS
Mir Score: 4.5/6 | RS: Top quartile | EMA aligned
Window: POWER HOUR
```

### Overlay Integration
- Show GEX king/floor/ceiling as entry/target/stop levels
- Add "Mir Signal Active" badge when daily swing passes
- Power hour countdown timer

### Scanner Enhancement
- Add "Mir Score" column (the 6-rule score from mir_scorer.py)
- Highlight tickers passing all filters in green
- Sort by RS ranking within each sector group

---

## SPY/QQQ 0DTE (Separate Strategy)

SPY/QQQ don't work for daily swings but DO work for intraday scalps:
- **Power Hour only** (3:00-4:00 PM)
- **5-min 20 SMA pullback** entry
- **61% WR** on SPY power hour
- **1DTE preferred** over 0DTE (Mir: "forget 0DTE crap, at least 1DTE")
- Entry at GEX level when price reaches king/floor
- Size for zero (1-2% max)

This is a SEPARATE strategy from the sector swing trades.

---

## Files for Integration

### Backtest (reference implementation)
- `backtest/mir_scorer.py` — Mir's 6-rule scoring (RS, SMA, EMA, DTE, macro, sector)
- `backtest/mir_backtest.py` — daily swing backtest
- `backtest/mir_intraday.py` — intraday 15-min backtest

### Server (needs updating)
- `server/signals.py` — SOE engine (currently bearish-only, needs Mir integration)
- `server/rts.py` — Already has RS scoring (wire into Mir filter)
- `server/gex.py` — GEX levels (already provides king/floor/ceiling)
- `server/discipline.py` — sizing + circuit breaker (keep as-is)

### Data
- `data/intraday/` — 15-min bars for intraday timing
- ChromaDB at `C:\Dev\mirbot_project\.openclaw\workspace-mirbot\data\chromadb` — Mir's RAG for conviction
