# Winner-Scoring Workflow — External LLM Critique Prompt

*Paste this into Perplexity / ChatGPT / Grok. Ask each: "Critique this end-to-end scoring workflow for picking momentum winners. Find the weakest link, suggest concrete improvements, and flag any blind spots. Be specific — I want actionable critique, not platitudes."*

---

## Who I am and what I'm building

Solo retail options trader. I trade primarily defined-risk options (calls/puts, occasional spreads) on US equities, with size 1-3% of book per position. I run my own scanner and discipline layer on top of an E-Trade / Tradier execution stack. I'm building a system that grades long candidates A+/A/B/C/D, sizes them with Kelly, manages exits with an ATR-based ladder, and keeps me honest with a circuit breaker.

I just ran a backtest on 19 names from a Qullamaggie × Minervini joint screener over 2 years of daily history. Pooled result was 72% hit rate at 21 trading days, +10.6% average return per trigger. Per-ticker dispersion was huge — AAOI averaged +37% / 21d while AESI averaged -15% / 21d at the same trigger conditions. That dispersion is what this scoring workflow is trying to handle: not "which screen do I run" but "given a list of 19 names that all passed the screen, how do I rank, size, and execute them differently?"

## The end-to-end workflow

### Layer 1 — Universe maintenance (weekly)

A 400-ticker universe organized into 3 tiers:
- **TIER_1** (~50): mega-caps + most-active movers, refreshed every scan cycle
- **TIER_2** (~120): sector leaders, refreshed every 2 cycles
- **TIER_3** (~230): theme/specialty names, refreshed every 4 cycles

New names are added when they:
1. Pass an external screener I trust (IBD Sector Leaders, Qullamaggie+Minervini, Stockbee, Mir Monis top-20, IBD Group #N leaders)
2. Are referenced by 2+ independent sources (LLM ensemble or trader Discord)
3. Fill a known thematic gap in the universe

Removed when underperforming for 60+ days AND no longer in any screen.

### Layer 2 — Screen (daily, automated)

Each scanner cycle runs the universe through:
1. **Stacked-MA Minervini Trend Template:** Close > EMA10 > SMA20 > SMA50 > SMA100 > SMA200, all positively sloped
2. **Relative Strength:** 1-month return rank ≥ 70th percentile vs SPY trailing 252d
3. **ATR Relative Strength:** ATR%-rank ≥ 50th percentile (above-average volatility)
4. **20-day range position:** within top 50% of trailing 20d range
5. **Daily candle:** bullish (close > open)
6. **Distance from 52w high:** within 15% (extended-but-not-blow-off filter)
7. **Liquidity:** $1B+ market cap, 1M+ avg daily share volume

Names passing all 7 gates enter the candidate pool for that day.

### Layer 3 — Single-name scoring (the part I want critiqued most)

Each candidate gets a composite score 0-100. Components:

| Component | Weight | What it measures |
|---|---:|---|
| **Trend Quality** | 20 | Slope of EMA10/SMA20/SMA50, distance between them, days-since-stacked |
| **Relative Strength** | 15 | Multi-window RS rank (1W/1M/3M/6M) vs SPY and sector ETF |
| **Volume Confirmation** | 10 | Today's volume vs 20d avg, OBV slope, accumulation days last 25 |
| **Volatility Posture** | 10 | ATR%-rank, IV-rank if optionable, IV vs realized 8q for earnings names |
| **Setup Pattern Match** | 10 | Specific named pattern detected: Stage-2 Breakout, Continuation, EP, Power Earnings Gap |
| **Earnings Distance** | 10 | Days to next earnings (penalize <3, reward 10-25, neutral >40) |
| **Sector / Theme Confirmation** | 10 | Group RS rank, count of cohort peers also triggering today |
| **Backtested Per-Ticker Edge** | 10 | Historical 21d hit rate and avg return on this same trigger pattern (where I have ≥10 historical samples) |
| **Macro / Regime Filter** | 5 | SPY > 200d? VIX < 25? Risk-on regime? GEX positive? |

Composite scores map to letter grades:
- **A+** ≥ 90 — full size, conviction
- **A** 80-89 — full size
- **B+** 70-79 — ⅔ size
- **B** 60-69 — ⅓ size, runner mentality
- **C / D** < 60 — watch only, no entry

### Layer 4 — Position sizing (Kelly with floor/cap)

For each grade-eligible candidate:
1. Look up base-rate hit-rate and avg-win/avg-loss from per-ticker history (or pooled if <20 samples)
2. Compute fractional Kelly: f = (p×b − (1−p)) / b, then take **half-Kelly** as max
3. Floor at 0.25% of book (avoid noise positions); cap at 3% of book per name
4. Cap aggregate cohort exposure at 8% of book (correlation control)
5. Adjust for IV — if IV-rank > 70, reduce size by 25% (paying up for gamma)

### Layer 5 — Entry execution

Three entry zones per setup:
- **Zone A (preferred):** First mean-revert pullback to rising EMA10 or EMA20 with bullish reversal candle. Buy ⅓ to ½ of intended size.
- **Zone B (continuation):** Break and hold above prior swing high on volume ≥ 1.3× 20d avg. Add ⅓.
- **Zone C (chase, restricted):** Only if sector ETF is also breaking out same session. Final ⅓.

If price runs away without offering Zone A, default to scaling in at Zone B; never chase Zone C alone.

### Layer 6 — Stop and exit ladder

- **Hard stop:** -9.1% from entry on equity, or -50% on options premium (whichever closer in dollars)
- **ATR-based trailing stop after entry +1×ATR:** trail at recent swing low or 2×ATR below close, whichever tighter
- **First scale-out:** at +1R (1× initial risk) → take ½ off
- **Second scale-out:** at +2R → take ¼ off
- **Runner:** trail final ¼ at 3×ATR or break of 21d EMA, whichever first
- **Mandatory exit before earnings if held > 1 day pre-print** (no holding binaries unless thesis is the print itself)
- **Time stop:** 21 trading days maximum hold; if not yet at +1R by day 15, exit by day 21 regardless

### Layer 7 — Discipline overlay

- **Daily loss limit:** -2.5% book → stop trading for the day
- **Weekly circuit breaker:** -5% book → stop new entries until weekend review
- **Streak management:** after 3 consecutive losses on same setup type, halve sizing on that setup until next win
- **Position-count cap:** max 8 open positions across all setups (focus over breadth)
- **No revenge trading rule:** must wait 30 minutes after any stopped-out exit before opening new position in same name or sector

### Layer 8 — Post-trade journal (mandatory, immediate)

Each closed trade logs:
- Entry grade and component scores
- Actual entry zone hit (A/B/C)
- Realized R-multiple
- Slippage vs model
- Time-to-target or time-to-stop
- Mistake category if loss (chase / wrong setup / cut early / held too long / size error)

Aggregated weekly into setup-level expectancy: hit rate × avg-win + (1 − hit rate) × avg-loss, by grade and by setup type.

## What I want LLM critique on — specific questions

1. **Component weights:** Are my Layer-3 weights defensible? Should backtested per-ticker edge be 10% or 25%? Is "macro regime" really only 5%? What's the academically validated weighting for momentum-factor scoring?

2. **The "B+ at ⅔ size" decision:** I currently fire B+ at ⅔ size on the assumption B+ has ~60% expectancy and full size would over-bet. Is this the right cutoff or should B+ be ½ size? What's the marginal expected value vs marginal risk-of-ruin tradeoff?

3. **Half-Kelly with both floor and cap:** Quant-finance convention says fractional Kelly avoids ruin. Is half-Kelly + 3% cap + 0.25% floor coherent or am I double-clipping the upside?

4. **Stop at -9.1%:** This number came from a Mir/Stockbee convention. Is it actually optimal for momentum names that average 4-6% ATR? Should it be ATR-multiple instead (e.g., -2.5×ATR)?

5. **Time stop at 21 days:** Backtest shows 21d as the sweet spot for forward returns, but does forcing exit at 21d for losers match how Qullamaggie or Minervini actually trade? Or do they let winners run 60-90 days?

6. **Cohort correlation cap of 8%:** Is 8% the right ceiling for thematically correlated longs (e.g., 3 photonics names + 2 semi-equip names all triggering same week)? Or should correlation-adjusted sizing replace a hard cap?

7. **Per-ticker base rates:** I'm using the same screen's historical per-ticker triggers as the base rate (so AAOI gets credit for its 75% historical hit, AESI gets debit for its 0%). This is forward-looking-bias prone (these names are currently working *because* they have winning setups). How would you correct for selection bias in the per-ticker score?

8. **What's missing entirely?** I have no sentiment/options-flow input in Layer 3. I have no breadth indicator (% of universe also stacked). I have no short-interest or float-rotation factor. Which of these would meaningfully move my expectancy and which are noise?

9. **Where would you simplify?** If you had to cut 3 components from Layer 3 and keep the system performing within 90% of its current expectancy, which 3 would you cut?

10. **Where's the regime trap?** This system is built and backtested in a generally-uptrending tape. Where does it fall apart in a 2022-style 9-month bear market — and what specific layer/threshold should change for me to detect that regime shift before it eats 2 months of gains?

## Constraints to respect in your critique

- I am one person trading my own book. Solutions requiring a quant team, expensive data licenses (>$200/mo) or microsecond execution are not actionable.
- I already have ThetaData ($80/mo), EODHD ($29/mo), and free yfinance for spot. I am NOT looking to add data sources.
- I trade options, not equities. Recommendations need to survive options-pricing reality (slippage, IV crush, weekend decay).
- Be skeptical of anything that sounds like "add more rules." Marginal complexity is the enemy. If a recommendation makes the system better only on paper, say so.

## What good critique looks like

- "Layer 3 weight on X should be Y because Z paper / Z empirical reason"
- "Your stop logic conflates A and B; here's how Minervini/Weinstein/Qullamaggie actually handle it"
- "Selection bias in per-ticker base rate is real — here's a specific debiasing technique you can apply with your existing data"
- "You're missing breadth — specifically, the McClellan Oscillator or the % of NYSE above 50d MA. Without it, your regime filter is naive"
- "Cut components X, Y, Z because they're collinear with component W"

## What weak critique looks like

- "Consider adding more rules" / "what about machine learning"
- "You should have stop-losses" (already do)
- Generic "diversification" advice without specifics
- "Backtest more"
