# ChatGPT Round 3 — Post-Backtest, Post-Live Day 1 (April 14, 2026)

You reviewed GammaPulse twice before. Last time you scored real-money readiness at 6/10. Since then we did a massive backtest validation, went live for the first trading day, and built infrastructure you recommended. Here's everything that changed.

---

## What Changed Since Round 2

### Backtest Validation (the game changer)
- **34 tickers, 15 months of data** (Jan 2025 - Apr 2026)
- **256 trades on sector leaders: 59% WR, +142.5% avg per trade**
- DTE grid search: 7-14 DTE >> 14-21 >> 21-35 >> 3-7
- Average hold: 2.7 days (80% resolve within 5 days)
- Top performers: LITE 78% WR, AXTI 55% WR +1653% avg (tail winners), MU 59% WR, VRT 64% WR
- **Strategy pivoted from bearish BREAKDOWN to bullish Mir momentum on sector leaders**
- GEX confirmed as quality gate (validates entry levels), not signal generator
- Monday skip (34% WR vs 46-51% other days)
- Bear regime filter: skip when SPY 20d return < 0
- Exit ladder: +25% sell half / +100% target / -50% hard stop

### A/B Test Infrastructure (your #1 recommendation)
- `ab_decisions` table logging every signal opportunity with BOTH decisions:
  - Book A (Mir+GEX): full SOE scoring + GEX structure + king/floor targets
  - Book B (Mir-only): fixed +2%/-1% targets, no GEX, 3-factor gate
- GEX contribution flags: entry_blocked, regime_blocked, improved_target, improved_stop
- Outcomes tracked independently per book (WIN/LOSS/EXPIRED + PnL)
- 8,582 decisions logged on day 1
- `/api/ab/results` endpoint with summary, GEX contribution breakdown, by-conviction
- Frontend ABTestPanel in Signals tab

### Paper Trading Portfolio ($20K)
- Full position lifecycle: open from signal → auto-monitor → auto-close on target/stop/expiry
- Kelly-computed contract sizing
- Equity curve with daily snapshots
- Trade journal with event audit trail (OPENED, TARGET_HIT, STOP_HIT, LADDER, etc.)
- By-ticker PnL breakdown, profit factor, max drawdown
- "Paper Trade" button on every signal card

### Spot-Consistency Check (0DTE safety)
- Massive Greeks built on 15-min delayed underlying (confirmed by Perplexity + Gemini)
- Now: compare Massive spot vs Tradier real-time spot every cycle
- >0.3% divergence → `[GEX_STALE_SPOT]` log + hard-block 0DTE signals
- Multi-day swings unaffected

### Setup-Forming Scanner (proactive trade ideas)
- Scans full universe every signal cycle for Mir-style setups forming
- Criteria: POS regime + king magnet + high RTS + Mir sector + low IVP + PM window bonus
- Monday penalty, bear regime filter
- Telegram push with king/floor targets and 7-14 DTE suggestion
- Based on PRODUCTION_STRATEGY.md backtest validation

### Scoring Fixes (from Day 1 live lessons)
- NYMO overbought threshold raised 40→80 (was blocking all signals on green days)
- "Don't fight the tape": when GEX 3/3 bullish, breadth penalty capped
- B+ Telegram push now works (field name bug fixed)
- Flow alerts require 1% OTM (no more ITM chase alerts)
- Contract selection sweet spot shifted to 10 DTE (was 14), range 7-21

### Reliability
- First cycle scans ALL 328 tickers (was only Tier 1 on restart)
- Mir signals persist to SQLite (survive restarts)
- UNPROVEN Kelly tier capped at DEVELOPING (was 29.67, now 17.13)
- Windows auto-start script for market hours

### Overlay Chart
- Volume Profile via ISeriesPrimitive plugin (official LWC API)
- AVWAP click-to-anchor (stale closure fix)
- Earnings "E" markers on daily chart
- Extended hours coloring (after-hours blue, premarket gray)
- Custom ticker input

### External Reviews
- **Grok**: Engineering 9/10, GEX math 10/10, Edge probability 4/10. "Sophisticated interface for following Mir signals with extra steps." Recommended A/B test (done).
- **Perplexity (77 citations)**: NYMO formula correct, Kelly needs 50+ trades per tier, POC has 90% reaction rate, Massive $29 is 15-min delayed.
- **Gemini**: Temporal mismatch is real for 0DTE (fixed), Bayesian scoring is future upgrade, ZGL migration is pro differentiator.

---

## Current System Architecture

### Signal Pipeline (in order of execution)
1. **Worker** scans 328 tickers every 2 min (GEX + Greeks + RTS + industry)
2. **SOE Engine** generates 5-factor scored signals every 5 min
3. **Setup Scanner** identifies Mir-style setups forming (proactive ideas)
4. **Discipline Layer** gates signals through Kelly + circuit breaker + Mir conviction
5. **AB Logger** records both Mir+GEX and Mir-only decisions
6. **Telegram** pushes A/A+ signals + quality B+ + setup forming alerts
7. **Paper Trading** tracks positions with auto-close on target/stop/expiry
8. **Outcome Checker** updates signal status + AB outcomes every minute

### Production Strategy (from backtest)
- **Ticker selection**: Mir's rules (EMA 21>50, SMA 20/50/200, RS top quartile, approved sectors)
- **Sectors**: Photonics, Semi Equipment, Memory, Space, AI/Compute
- **DTE**: 7-14 (sweet spot 10)
- **Entry**: PM window (2:00-4:00), GEX king/floor levels
- **Exit**: +25% sell half, +100% target, -50% hard stop
- **Regime**: skip when SPY 20d < 0
- **Day**: skip Mondays
- **Sizing**: 1.5% validation phase, quarter-Kelly after 50 trades

### Live Trading Parameters
- Paper portfolio: $20,000
- Max 3 open positions
- 1DTE minimum (no 0DTE for swings)
- Kill switches: 3 consecutive losses → 1% size, 5 → paper only, WR < 45% over 30 → stop

---

## Questions for Round 3

### 1. Strategy Validation
The backtest shows 59% WR, +142.5% avg on 256 trades (sector leaders, 7-14 DTE, bullish momentum). The previous rounds flagged "no backtest validation" as the critical gap.
- **Does this backtest address your concerns?**
- **What are the risks of this specific strategy in live trading?**
- **The +142.5% avg is driven by tail winners (AXTI +1653%). How should I think about the distribution?**

### 2. A/B Test Design
The A/B test logs both Mir+GEX and Mir-only decisions for every signal opportunity.
- **Is this a valid experimental design to answer "does GEX add value"?**
- **What sample size do I need before the results are meaningful?**
- **Should I be tracking anything else in the AB decisions?**

### 3. The SOE Engine Switch
Currently SOE still generates bearish BREAKDOWN signals alongside everything else. The backtest says only bullish momentum on sector leaders works.
- **Should I kill all bearish signal types? Or keep them for SPY/QQQ scalps?**
- **The setup-forming scanner is separate from SOE — is that the right architecture? Or should it replace SOE for sector leaders?**

### 4. Day 1 Lessons
- Server was down during key Mir signals (missed MSFT $400C, up 90%)
- NYMO 164 was blocking all A-grade signals on a massive green day
- Mac Mini bridge dropped a QQQ signal
- Flow alerts for ITM contracts were useless
- **What operational risks should I prioritize fixing?**

### 5. Updated Scorecard
Given everything above — backtest validation, A/B infrastructure, paper portfolio, spot-consistency check, setup scanner, scoring fixes:

| Dimension | Last Score | Updated? |
|-----------|-----------|----------|
| Engineering | 8.5/10 | ? |
| GEX math | 8/10 | ? |
| Signal engine | 7/10 | ? |
| Risk layer | 8/10 | ? |
| Data fidelity | 9/10 | ? |
| Statistical rigor | ?/10 | (new: backtest data) |
| Real-money readiness | 6/10 | ? |
| Edge probability | ?/10 | (new: 59% WR backtest) |

Be blunt. I'm paper trading now and planning to go live within weeks.
