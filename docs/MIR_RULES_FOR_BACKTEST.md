# Mir's Trading Rules — For Backtest Integration

Extracted from 23,866 RAG chunks of @OptionsMir's Discord + Twitter history.
Codified in `server/mir_rules.py` on April 13, 2026.

---

## Entry Rules

### DTE Selection
- **0DTE**: Lotto only, size for zero (1-2% max), quick scalps
- **1-7 DTE**: Day trades / short swings, 1DTE minimum preferred over 0DTE for buffer
- **7-21 DTE**: Sweet spot for earnings/catalyst plays (2-3 weeks out)
- **21-45 DTE**: Thematic swings, monthly timeframe
- **45+ DTE**: LEAPS/macro thesis only

### Time of Day
- **AVOID first hour** after open (9:30-10:30) — "wait an hour after the opening bell"
- **10:30-11:30**: Post-open settled, watch for pullback to 15min 20 SMA
- **11:30-1:30**: Midday chop, low probability
- **1:30-2:00**: Mid-day volatility window (2nd key period)
- **3:00-4:00**: POWER HOUR — "our biggest plays are ones taken in those final minutes when whales enter positions"

### Ticker Selection Filters
**Breakout/UnR scanner:**
- Price > $3
- Market Cap > $300M
- Avg Volume > 500K
- ADR% > 2%
- EMA 21 below price AND EMA 50 below price

**Swing/RS scanner:**
- Price > $5
- Market Cap > $2B
- Avg Volume > 500K, Current Volume > 1M
- Price above SMA 20, 50, AND 200 (strict)
- Relative Volume > 1

### Sector/Theme Filter
Only trade names in leading sector groups:
- **Photonics**: AAOI, LITE, COHR, GLW, CIEN, AXTI
- **Semi Equipment**: AEHR, TER, AMAT, LRCX, KLAC
- **Space**: RKLB, ASTS
- **AI/Compute**: NBIS, OKLO, IREN, VRT, ANET
- **Memory**: MU, WDC

Stock must be a "liquid leader with highest relative strength" within a leading group.

---

## Position Sizing

### By Conviction
- **HIGH**: Up to 10% of account, scale in 3 parts
- **MEDIUM**: 5% of account, scale in 3 parts
- **LOW/WATCH**: 2% max, single entry

### By DTE
- **0DTE**: Max 2% — "size for zero"
- **1-7 DTE**: Standard sizing
- **7+ DTE**: Full sizing allowed

### Rollup Rule
After taking profits on heavy position, re-enter with **1/3 of original size** for continuation. "On a rollup I'm never risking the whole bag."

### Critical Warning
"Never full port 80% of account unless it's tiny." Always keep backup cash.

---

## Exit Rules

### Stop Loss
- **0DTE lottos**: No stop, sized for zero, let ride
- **Weeklies (1-7 DTE)**: 50% stop — "if contracts cut to 50% of value, let it go"
- **Longer dated**: 50% stop unless thesis still valid and chart intact
- **Regime rule**: In strong trends, "be generous at first to let the trade work"

### Stop Management
1. Enter with hard stop at max acceptable loss
2. Move to breakeven "once there is wiggle room"
3. Trail stops "just outside of last flagging action"
4. If it doubles: raise stop again to protect profits

### Profit Taking
- **Phase 1**: Scale out 50% at +100% gain (doubling)
- **Phase 2**: Target 1.618 Fibonacci extension (set alert slightly below)
- **Phase 3**: Trail stop on remainder, let runner work if trend is strong

### Regime-Based Exit
- **Bull trend**: Grand slams — hold runners, let contracts grow, rollup with 1/3
- **Choppy/weak**: Base hits — take 50% gain, tight stops, small runners only

---

## Macro Rules

### Defensive Triggers (reduce beta, hold cash)
- VIX > 22 sustained — "institutional risk management forces deleveraging"
- VIX > 35 — go to cash
- VIX backwardation — fear elevated
- Binary events (FOMC) at highs — "risk/reward not great"
- Dollar strength + market weakness
- Multiple risks clustering (earnings, tariffs, Fed)

### Aggressive Triggers (size up)
- Post-event clarity + key levels holding
- Stocks bucking bad news (bullish signal)
- NYMO < -40 (oversold) — "rotate into individual names that can move bigly"
- Technical breakouts above resistance

### What He Ignores
- Fed commentary for execution — "by the time you react the move is usually over"
- Consensus headlines — market reaction > data itself

---

## Backtest Implementation Notes

### Scoring Function: `score_mir_pattern()`
Checks 5 rules, returns match percentage (0-100%):
1. DTE alignment with trade type
2. Time of day (penalize first hour, reward power hour)
3. Ticker quality (EMA filter, volume, sector membership)
4. Macro alignment (VIX, NYMO, term structure)
5. (During live: Mir conviction from Discord — skip in backtest)

### Suggested Backtest Configs
```
Config 1: "Mir Swing" (his bread and butter)
  DTE: 14-21
  Entry: 10:30 AM - 2:00 PM
  Tickers: Photonics + Semi Equip only
  Filter: EMA 21 > EMA 50, price above both
  Stop: -50%
  Target: +100% (scale out half)
  
Config 2: "Mir Power Hour Scalp"
  DTE: 1-3
  Entry: 3:00 PM - 3:45 PM only
  Tickers: SPY, QQQ only
  Filter: Price above intraday VWAP
  Stop: -50%
  Target: +30% (take 2/3 off)

Config 3: "Mir Lotto"
  DTE: 0
  Entry: 3:30 PM - 3:55 PM
  Tickers: SPY, QQQ
  Size: 1-2% max
  Stop: none (expire worthless or hit)
  Target: +200%+

Config 4: "Mir Oversold Bounce"
  DTE: 7-14
  Entry: Only when NYMO < -40
  Tickers: Highest RS in leading sectors
  Filter: EMA 21 > EMA 50
  Stop: -50%
  Target: +100%, let runner ride
```

### Key Metrics to Track
- Win rate by DTE bucket
- Win rate by time of day
- Win rate by sector/theme
- Avg winner vs avg loser by config
- Payoff ratio by conviction level
- Performance in VIX > 22 vs VIX < 22
- Power hour entries vs morning entries
