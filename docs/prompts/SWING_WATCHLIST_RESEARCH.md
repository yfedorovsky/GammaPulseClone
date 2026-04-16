# Swing Watchlist Research Prompts
# Goal: Figure out the best method for building a daily/weekly swing watchlist
# Context: Options trader, $20K account, 7-14 DTE calls/puts, sector rotation focus

---

## Grok Prompt (Professional Trader Methods)

I'm building a systematic swing trading watchlist scanner for options (7-14 DTE calls/puts on single stocks). $20K account, not day trading — holding 1-5 days typically.

I want to know how professional/institutional swing traders actually build their daily watchlist. Not retail YouTube stuff — real methodology.

Specifically:

1. **What screening criteria do pros actually use?** Walk me through the exact filters. I've heard variations of:
   - Relative strength vs benchmark (Mansfield RS, IBD RS Rating, etc.)
   - Price above key moving averages (50 SMA, 200 SMA, 21 EMA)
   - Volume patterns (accumulation/distribution, relative volume)
   - ADR% (Average Daily Range) for options sizing
   - Sector/industry group strength
   - But which combination actually has edge? What's proven vs marketing?

2. **IBD/CANSLIM vs Minervini SEPA vs O'Neil vs Stan Weinstein Stage Analysis** — which framework has the best empirical track record for swing selection? Are there studies or documented performance comparisons?

3. **How do institutional sector rotators build their weekly focus list?** I'm thinking about relative strength by sector (SPDR ETFs), then drilling into the top 2-3 sectors for individual stock leaders. Is this how it's actually done at the desk level?

4. **What's the minimum viable screen?** If I could only run 3-4 filters to get from 3000 stocks down to 10-20 actionable names per week, what would those filters be? Rank them by importance.

5. **For options specifically (not stock-only swings):** Does the watchlist criteria change when you're buying 7-14 DTE calls instead of holding shares? Things like IV rank, liquidity minimums, average spread, open interest — what filters matter for options overlay?

6. **What's the daily workflow?** Pre-market scan → sector check → individual chart review → entry list. Walk me through the actual 15-minute morning routine a systematic swing trader uses.

Be specific with numbers/thresholds. I want implementable criteria, not concepts.

---

## Perplexity Prompt (Academic/Research Evidence)

I'm building a quantitative stock screening system for swing trading (1-5 day holds, options-based). I need academic and empirical evidence for the most effective screening criteria. Search for recent research (2020-2026).

Questions:

1. **Relative Strength momentum screening**: What does the academic literature say about cross-sectional momentum (Jegadeesh & Titman style) applied to weekly/monthly holding periods? Is 1-month relative strength vs benchmark a proven predictor of forward 1-week returns? What's the optimal lookback period for swing-length holds?

2. **Moving average filters for stock selection**: Is there peer-reviewed evidence that screening for stocks above their 50-day or 200-day SMA produces better risk-adjusted returns? What about EMA crossovers (21 EMA > 50 EMA > 200 SMA alignment)?

3. **Sector rotation as a stock selection layer**: What's the evidence for top-down sector rotation (buy leaders in strongest sectors)? Is there a documented premium for stocks in the top-performing sector quintile vs the full market? How often should sector rankings be rebalanced for swing trading?

4. **Volume-based screening**: Does relative volume (today's volume vs 20-day average) or accumulation/distribution metrics predict short-term price continuation? What are the optimal thresholds?

5. **ADR% (Average Daily Range) as a filter**: Is there evidence that higher ADR% stocks produce better options returns on a risk-adjusted basis? What ADR% range is optimal for 7-14 DTE option buyers?

6. **Combining multiple factors**: What does the literature say about combining RS + MA alignment + volume + sector strength into a composite score? Is there diminishing returns after 3-4 factors? Which combination has the highest Sharpe for weekly holds?

7. **IBD Relative Strength Rating**: Is the IBD RS rating (which uses 12-month weighted price performance) academically validated? How does it compare to simpler RS measures like 3-month return rank?

Cite specific papers, datasets, and sample sizes. I want to distinguish between robust findings and data-mined noise.

---

## ChatGPT Prompt (Practical Implementation Review)

I'm adding a "Swing Watchlist Scanner" to my options trading platform (GammaPulse). Here's what I already have built:

**Existing infrastructure:**
- 328 tickers scanned every 2 minutes
- RTS score (0-100): Relative Trend Strength combining RS vs SPY (20d/60d) + MA alignment (20/50/100) + slope
- IVP (IV Percentile vs 52-week history) — unlocking in ~14 days
- IVHV ratio (IV / 20-day realized vol)
- Sector mapping: 11 SPDR sectors + 13 industry theme groups
- 1 year of daily close history (backfilled from Tradier)
- GEX structural levels (king/floor/ceiling) per ticker
- Mir momentum scorer (6-rule system from a proven swing trader)

**What I want to build:**
A separate scanner tab/view that shows a ranked watchlist optimized for swing trades (7-14 DTE options, 1-5 day holds). Not the GEX-focused scanner I already have — this is pure relative strength + trend + sector rotation.

**My proposed filters (review these):**
1. RTS score >= 50 (above average relative strength)
2. Price above 21 EMA and 50 SMA
3. MA alignment: 21 EMA > 50 SMA (or close)
4. ADR% >= 2% (enough movement for options)
5. Volume >= 500K daily average
6. Top 3 SPDR sectors by 1-month return
7. IVP < 50% (options not expensive)
8. Spread < 10% on ATM options

**Questions:**
1. Is this filter set reasonable or am I over/under-filtering?
2. What am I missing that professional screeners include?
3. How should I rank the final list — composite score, or just sort by RTS?
4. Should the sector filter be hard (only top 3 sectors) or soft (bonus points)?
5. For the "wifey swing" use case (longer holds, 14-30 DTE, simpler entries) — what would you change?
6. What's the optimal refresh frequency — daily at open, or intraday?

Be direct. Tell me what to add, remove, or change.

---

## Gemini Prompt (Quantitative Deep Dive)

I'm designing a quantitative swing stock screening system for options trading. I need a rigorous, mathematically grounded evaluation of screening factor efficacy. This is for a 328-ticker universe (US large/mid-cap equities), with 7-14 DTE option positions held 1-5 days.

**System parameters:**
- Universe: 328 tickers (47 Tier-1, 140 Tier-2, 141 Tier-3)
- Holding period: 1-5 trading days
- Instrument: ATM to slightly OTM calls/puts, 7-14 DTE
- Account: $20K, max 5 concurrent positions
- Rebalance: daily scan, weekly sector rotation

**Factors I'm considering (evaluate each independently and in combination):**

| Factor | Computation | Threshold |
|--------|-------------|-----------|
| Relative Strength (20d) | ticker 20d return - SPY 20d return | > 0% |
| Relative Strength (60d) | ticker 60d return - SPY 60d return | > 0% |
| RS Percentile | rank within universe by 20d return | >= 70th |
| MA Position | price > 21 EMA, > 50 SMA | all above |
| MA Alignment | 21 EMA > 50 SMA > 100 SMA | bullish order |
| MA Slope | 20 SMA 5-day rate of change | > +0.5% |
| ADR% | 14-day average (high-low)/close | 2-6% |
| Relative Volume | today volume / 20d avg volume | > 1.2x |
| Sector RS | sector ETF 1-month return rank | top 3 of 11 |
| IV Percentile | current IV vs 52-week IV range | < 50% |
| IV/HV Ratio | implied vol / 20-day realized vol | < 1.2 |

**Questions:**

1. **Factor independence**: Which of these factors are likely collinear? If I'm already using RS 20d, does RS 60d add marginal information, or are they ~0.8 correlated? Build a correlation matrix estimate.

2. **Optimal factor weights**: If I'm building a composite screening score from these factors, what weights would you recommend based on the momentum/trend-following literature? Should I equal-weight or overweight certain factors?

3. **Diminishing returns**: At what point does adding more factors stop improving selection quality? Is there a principled way to determine the optimal number of factors (information coefficient analysis, factor spanning tests)?

4. **Sector filter methodology**: Should sector rotation be a hard gate (only show stocks from top 3 sectors) or a soft score (bonus points for strong sector)? What's the academic evidence for top-down vs bottom-up selection?

5. **ADR% optimization**: For 7-14 DTE option buyers, what ADR% range maximizes the probability of reaching a +30% option gain within 3 days? Model this using the relationship between ADR%, option delta, and DTE.

6. **Turnover and transaction costs**: With daily scanning, how many stocks typically enter/exit the top 20 list per day? Is daily rebalancing worth the information gain vs weekly?

7. **Backtest framework**: If I wanted to validate this screening system, what's the minimum sample size (months of data) needed for statistical significance? What's the right benchmark — equal-weight universe, SPY, or sector-matched?

Provide formulas, correlation estimates, and specific numerical recommendations. I want to implement this directly, not revisit it conceptually.

---

## MirBot RAG Prompt (Mir's Actual Workflow)

Search Mir's Discord history for how he builds his daily watchlist and selects swing trade candidates. I want to understand his ACTUAL process, not theory.

Specific questions:

1. **How does Mir narrow down to his daily focus list?** Does he use a screener? Sector rotation? RS ranking? Or is it more intuition + familiar names? What does he look at pre-market?

2. **Does Mir mention relative strength or RS ratings?** Has he ever talked about screening by RS, momentum rankings, or comparing stocks to SPY/sector benchmarks?

3. **What moving averages does Mir actually reference?** I know he uses the 8 EMA on 15-min for entries. But for DAILY chart stock selection — does he use 21 EMA, 50 SMA, 200 SMA? Which ones matter for his watchlist vs entry timing?

4. **Does Mir use sector rotation?** Does he rotate into hot sectors, or does he stick with his core themes (semis, photonics, AI) regardless of sector performance?

5. **Volume — does Mir screen for it?** Does he mention volume thresholds, relative volume, or accumulation patterns when selecting swings?

6. **What's Mir's rejection criteria?** When does he PASS on a setup that looks good technically? Earnings proximity? Low volume? Extended from base? Chop zone?

7. **Wifey trades specifically:** When Mir posts in #wifey-swing-trades, what's different about those picks vs his main account? Longer holds? Simpler setups? Different stock selection?

8. **Has Mir ever described his morning routine?** Pre-market scan, what he checks first, how he decides what's in play for the day?

Search for keywords: watchlist, scanner, screener, relative strength, sector, pre-market, morning routine, wifey, swing selection, daily list, focus list, hot list.
