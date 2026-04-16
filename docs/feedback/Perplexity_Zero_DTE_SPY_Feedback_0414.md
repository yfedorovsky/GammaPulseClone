# SPY/QQQ 0DTE Scalp Strategy — Brutal Honest Review

**Prepared for:** GammaPulse / Solo Retail Trader, $20K account  
**Date:** April 14, 2026  
**Scope:** Academic evidence review, engineering stress test, and practical implementation critique of the GammaPulse 0DTE directional scalp system

***

## Executive Summary

The GammaPulse strategy has legitimate structural foundations — the academic literature does confirm that dealer gamma hedging creates measurable intraday momentum and predictable support/resistance at high-GEX strikes. However, the strategy faces three compounding threats that narrow the edge significantly before the first trade: (1) execution costs on 0DTE ATM SPY options that run 3–6% of premium on entry and exit, (2) retail traders as a class losing an average of $350,000/day on 0DTE S&P 500 options since 2022, and (3) an unquantified per-alert-type win rate that means the backtested time-window win rates (58–62%) are likely overstating what the system will actually deliver. The strategy is **not** a coin flip — but getting to positive expectancy after all-in costs requires performance materially above the backtested base rates, disciplined execution, and a small set of targeted fixes.[^1][^2][^3]

***

## 1. Is the GEX Foundation Empirically Sound?

The core thesis — that dealer gamma hedging creates predictable intraday support and resistance — is supported by peer-reviewed finance literature, not just retail trader lore.

**Key academic evidence:**

- **Baltussen, Da, Lammers & Martens (2021)** in the *Journal of Financial Economics* provide the most rigorous confirmation: hedging short gamma exposure requires trading in the direction of price movements, thereby creating intraday momentum. Using intraday returns across 60+ futures markets from 1974–2020, they document strong "market intraday momentum everywhere," with the return during the last 30 minutes before close positively predicted by the day's prior return — and explicitly linking this to gamma hedging demand.[^4][^5][^6][^7]

- **Buis et al.** (published in the *Journal of Economic Dynamics and Control*) find via simulation that higher net gamma positioning of dynamic hedgers reduces volatility and increases market stability, while negative gamma positioning increases volatility — directly supporting the positive/negative gamma regime logic used in this strategy.[^8]

- A 2024 paper presented at the American Finance Association (*"Where does gamma hedge drive the intraday market move?"*) extends Baltussen et al. by identifying "gamma-theta breakeven ranges" (GTBRs) as inflection points: when these breakeven thresholds are hit, inelastic hedge demand is created, and intraday momentum surges. High long-gamma MM positioning also predicts significant mean reversion (-1.25 coefficient), directly corroborating the BUY_DIP and SELL_POP logic.[^9]

- Market practitioners (SpotGamma, menthorq, InsiderFinance) document the same dynamics in live data: on Oct 27, 2023, SPY hit extreme negative GEX of nearly -$3 billion coinciding with a market low, followed by a 15% rally — a textbook negative-gamma amplification event.[^10][^11]

**Bottom line on the foundation:** The GEX premise is real. Dealer hedging *does* create predictable intraday behavior around gamma-heavy strikes. The academic evidence for the regime distinction (positive gamma = mean reversion, negative gamma = momentum) is particularly robust and directly maps to the King/Floor/Ceiling/ZGL architecture.

***

## 2. The Realistic Sharpe After Costs

This is where the strategy faces its most serious challenge. The backtested win rates (58–62%) are measured on *SPY spot moves* during time windows — not on option premium P&L including bid-ask spread costs.

### Transaction Cost Reality

| Cost Component | Estimate | Source |
|---|---|---|
| ATM SPY 0DTE bid-ask spread (intraday) | $0.02–$0.05 per contract | [^12] |
| Spread as % of $1–4 premium | 1.25–5% per side | [^2] |
| Entry + exit round-trip cost | ~3–6% of premium | [^1][^2] |
| Annual drag (25% slippage rate, NDX study) | 300–350 bps/year | [^13] |

The 0DTE SPY spread is actually one of the tightest available — $0.02–$0.05 vs $0.10–$0.30 on SPX — which is an important point in the strategy's favor. But on a $2.00 ATM premium, even a $0.05 spread is 2.5% per side, meaning 5% round-trip before any directional edge. A 2023 Schaeffer's analysis found the 0DTE spread was 5.8% for near-$1 options vs ~1% for longer expirations.[^12][^2]

### The Math on Expectancy

The document's Gemini simulation prompt — 55% win rate, +40% avg winner, -80% avg loser, 2% commission drag — can be modeled explicitly:

\[ \text{EV per trade} = (0.55 \times 0.40) - (0.45 \times 0.80) - 0.02 \]
\[ \text{EV} = 0.22 - 0.36 - 0.02 = -0.16 \]

At these parameters, the strategy is **deeply negative** at -16% per trade on option premium. To get to breakeven requires roughly a 65% win rate at those payoff ratios, or improving the avg winner to ~65–70% while keeping the avg loser at 80%. These aren't impossible numbers for a high-quality filtered setup, but they're meaningfully above the unadjusted backtest rates.

A broader academic study (Beckmeyer, Branger & Gayda, 2023, SSRN) found retail traders as a class experiencing "substantial losses" in 0DTE S&P 500 options despite benefiting from some price improvement mechanisms. Retail traders collectively lost $125M in aggregate and $350K/day since the introduction of daily expirations in 2022.[^14][^15][^3]

**The key caveat:** The strategy's selectivity filters (max 2 alerts/day, state-transition-only, macro skip, GEX magnitude threshold) are specifically designed to avoid the behavior that causes those aggregate retail losses — chasing moves, overtrading, holding through events. Whether the filters are sufficient to offset the structural disadvantage is the critical unknown.

***

## 3. The 15-Minute Volume Lag: Fatal, Fixable, or Acceptable?

**Verdict: Acceptable as currently implemented (informational, not veto), but 5-min bars would be a meaningful improvement.**

The fundamental problem with 15-min volume confirmation is that by the time the bar closes, the move is often 12–14 minutes old. For a scalp targeting 5–30 minute holds on 0DTE, confirming volume on a completed 15-min bar means you're often confirming a move you missed, not one you can still enter.

However, the current implementation correctly makes volume *informational rather than a hard gate* — the alert fires on the GEX state transition (which is near-real-time), and volume is displayed as context for the decision. This is the right engineering choice.

**On switching to 5-min bars:** The 2026 options.cafe opening range breakout study explicitly tested multiple bar intervals and found the 5-minute range "nearly doubled the returns compared to the commonly used 15-minute range while simultaneously reducing max drawdown". This is directionally consistent with the concern about 15-min lag. Switching the EMA_PULLBACK detection to 5-min bars would reduce lag by ~10 minutes at the cost of more noise. For the EMA and volume confirmation specifically (not the GEX state-transition alerts), a 5-min bar would improve responsiveness without compromising the core GEX signal.[^16]

**For the GEX alerts themselves:** The 2-minute GEX refresh is not the binding constraint. The binding constraint is the state-transition detection running on 30-second cycles reading the 2-minute-cached GEX state. This is architecturally sound — the scanner doesn't wait for a bar close to fire.

***

## 4. VIX Filter: Should It Be Added?

**Verdict: Yes — add VIX1D > 35 as a hard skip, VIX > 25 as a soft warning.**

The strategy currently skips high-impact macro *events* (FOMC, CPI, NFP via Finnhub) but not high-VIX *regimes*. These are different problems:

- **Event skips** (current implementation): Correct. Whipsaw risk on binary news events eliminates GEX reliability because dealers reprice the entire chain during the announcement.
- **High-VIX regime skips** (missing): High VIX means wider bid-ask spreads, faster realized moves that overshoot GEX levels, and degraded fill quality on manual execution.[^17][^18]

Research on VIX regimes in 0DTE trading suggests:
- VIX < 20: Low volatility, GEX levels sticky, positive-gamma pinning dominant — favorable for this strategy's BUY_DIP/SELL_POP setups.[^18][^19]
- VIX 20–30: GEX still functional but moves overshoot levels more frequently; 1DTE preferred.[^20]
- VIX > 30: Spreads widen dramatically, fills degrade, GEX levels can shift 3–5 strikes intraday during fast markets — skip.[^18]

The CBOE's VIX1D (intraday expected volatility for same session) is now available and specifically designed for 0DTE context. Using VIX1D as the primary filter is more precise than end-of-day VIX for same-day options decisions.[^19]

**Recommended filter addition:**
- VIX1D > 2% intraday move implied → soft warning tag on alerts
- VIX (standard) > 30 → hard skip, same as macro event day

***

## 5. 0DTE vs. 1DTE: The Theta/Gamma Tradeoff

**Verdict: Mir is correct. Switch to 1DTE for the PM entry window (1:30–4:00 PM).**

This is the single highest-impact improvement available with minimal code change.

### Theta Decay Timeline for 0DTE ATM Options

The academic and practitioner evidence on 0DTE theta decay is consistent:[^21][^22][^23]

- **9:30–12:00 PM:** Gradual decay, ATM option losing ~$0.40–0.60/hour on $5.00 premium
- **12:00–1:00 PM:** Inflection point — option has often lost ~50% of opening value
- **1:00–2:30 PM:** Aggressive theta ($0.80–$1.20/hour); the "tug of war" between theta drain and gamma amplification
- **2:30–3:30 PM:** Decay is "relentless" — an ATM option that opened at $5.00 may be worth $0.50–$1.00
- **3:30–4:00 PM:** ~60–70% of remaining extrinsic value vaporized[^22]

The strategy's primary entry window is 1:30–4:15 PM — precisely the window of maximum theta destruction. Entering a 0DTE call at 2:00 PM means buying an option that will lose 60–70% of its remaining extrinsic value in the next two hours regardless of direction.

**With 1DTE contracts at the same PM entry time:**
- The option has ~22–23 hours of time value remaining instead of ~2 hours
- Theta per hour is ~15–20x lower at equivalent strikes
- A 30-minute stall in the trade doesn't convert a winner to a loser purely from time decay
- The cost is slightly lower gamma leverage per dollar of underlying move — but for a 5–30 minute hold, this is minor

**The implementation gap:** The system already flags "1DTE preferred for buffer" in every alert but only suggests 0DTE contracts. Updating the contract suggestion logic to surface the 1DTE ATM strike as the primary suggestion is a one-line change with significant risk-reduction benefit.

***

## 6. Review of the 7 Alert Types

| Alert | Assessment | Issue | Fix |
|---|---|---|---|
| BUY_DIP | **Valid** | None — bounce off positive-gamma floor is the most academically supported setup[^9] | None |
| BREAKOUT | **Valid with caution** | In high-positive-GEX regimes, breakouts above King often fail — dealers sell into the move | Add GEX regime check: only fire BREAKOUT in negative or near-zero GEX |
| RETEST | **Valid** | Classic breakout-retest is sound; state-transition firing avoids chasing | None |
| SELL_POP | **Valid** | Ceiling rejection is the put-side mirror of BUY_DIP | None |
| FLOOR_BREAK | **Valid** | Strongest momentum signal in negative-gamma regime; dealers amplify[^11] | Confirm ZGL is below spot (negative gamma required for this to have momentum, not mean-reversion) |
| ZGL_CROSS_UP/DOWN | **Redundant risk** | The ZGL level is imprecise (2-min GEX data) and near-ATM it fluctuates ±$1–2 intraday; false crosses are likely | Add confirmation: require ZGL cross sustained for >1 bar, or require 0.3%+ distance from ZGL |
| EMA_PULLBACK | **Valid** | This is Mir's highest-conviction setup — 8 EMA on 15-min is a proven institutional reference | Switch to 5-min bars to reduce lag |
| EMA_REJECTION | **Valid** | Mirror of pullback | Same 5-min bar improvement |
| TREND_CONTINUATION | **Use with VIX caution** | Gap-and-go days (>2%) often have elevated VIX; 10:00 AM entry without VIX filter adds risk | Require VIX < 25 for this alert type |

**Structural redundancy concern:** ZGL_CROSS_UP and BREAKOUT can fire in rapid sequence (price crosses ZGL, then continues to King, then breaks above King), consuming both of the day's 2-alert slots within minutes on a trending day. Consider making ZGL_CROSS and BREAKOUT mutually exclusive (only one can count toward the daily cap per directional move).

***

## 7. Exit Logic Review

The current exit structure (30–60% target, stop on level break, time stop at 3:00 PM) is reasonable but has one significant flaw.

**What's correct:**
- Hard stop on structural level break (e.g., floor breaks on a BUY_DIP) is the right discipline — the GEX thesis is invalidated when the level fails
- Time stop at 3:00 PM aligns with the theta acceleration inflection point[^21][^22]
- +30–60% target is achievable with ATM 0DTE contracts on a 0.3–0.5% underlying move

**What to reconsider:**
- **The 3:00 PM time stop is too aggressive for 1DTE contracts.** If the system transitions to 1DTE, a 3:00 PM scratch doesn't apply — you can hold through 4:15 PM without catastrophic theta drag. The time stop should be: 0DTE → 3:00 PM scratch if down, 1DTE → 4:10 PM scratch if down.
- **Partial take implementation:** The +25% partial take (sell half, move stop to break-even) is worth implementing for 0DTE. Tastylive's two-year 0DTE study found that taking smaller profit targets (10–25%) significantly increased win rates and consistency compared to holding for larger targets or expiration. The hold time for 0DTE is too short for this to add operational friction — a half-exit at +25% and a stop-to-break-even rule is a 2-minute decision, not a complex management task.[^24]

***

## 8. Position Sizing and Daily Alert Cap

**Position sizing (0.5–1% per trade = $100–200 on $20K):**  
This is appropriate given the binary risk profile of 0DTE options. The documented 100% total-loss rate on OTM 0DTE losers means each trade is genuinely a full-premium-at-risk event. At $150 average risk, a 10-trade losing streak costs $1,500 — painful but survivable. Sizing up on "high confidence" setups is a discipline killer — avoid it.

**2 alerts per ticker per day:**  
This is well-calibrated. The two-alert cap forces selectivity and prevents the overtrading that drives aggregate retail 0DTE losses. Reduce it to 1 during VIX > 25 regimes.[^3]

**Max 2 alerts total (vs. 2 per ticker):**  
The document says "max 2 alerts per ticker per day" but then states "Daily max: 2 alerts traded." These should be harmonized. Recommendation: 2 total per day across both SPY and QQQ, not 2 per ticker (which could allow 4 total trades on a given day).

***

## 9. Macro Day Skip: Too Broad or Too Narrow?

**Verdict: Currently appropriate, with one gap.**

The Finnhub "high impact" flag correctly skips FOMC, CPI, PPI, and NFP — the events most correlated with 0DTE whipsaw losses. The GEX framework fails on these days because dealers reprice the entire chain around the announcement, making pre-event structural levels meaningless.[^8]

**The gap:** The macro skip checks Finnhub on a 30-second cycle, but the check should be *time-windowed* for intraday events. An FOMC announcement at 2:00 PM means the entire PM session is compromised — but a 2:01 PM check that clears the 30-second cycle might incorrectly re-enable alerts if the Finnhub flag doesn't persist post-announcement. The fix: if an intraday high-impact event is scheduled, skip the entire session from 90 minutes before the scheduled time through close.

***

## 10. GEX Data Staleness: 2-Minute Refresh Risk

**Verdict: Acceptable for most conditions; material risk during negative-gamma fast markets.**

The 2-minute GEX refresh cycle from Tradier chains + Massive Greeks is meaningfully slower than institutional-grade data (SpotGamma OPRA-grade, sub-second). The staleness risk quantification:

- In a positive-gamma regime (SPY near King with $10B+ GEX like the April 13, 2026 reading of $10.88B): Levels are stable. SPY moves at ~$0.10–0.20/minute in normal conditions; a GEX level shift during a 2-minute window is unlikely to be more than $1–2. This is within acceptable tolerance for $5-increment rounding.[^25]

- In a negative-gamma regime during a fast market (VIX > 25): SPY can move $0.50–1.50 in 2 minutes. GEX levels can shift by 3–5 strikes. The Floor, Ceiling, and ZGL levels computed 2 minutes ago may no longer reflect current dealer positioning. **This is precisely the VIX > 25 regime that should be filtered out.** The VIX filter recommendation in Section 4 directly addresses this staleness risk.

A 2024 analysis of GEX for SPX 0DTE specifically warned that "relying solely on a Gamma Flip level calculated at the start of the day or based on previous day's data can be misleading for intraday 0DTE strategies. Effective use requires monitoring frequently updated or real-time calculations". The 2-minute refresh is far better than daily recalculation, but the engineering gap remains: during negative-gamma fast markets, the system is trading stale structure.[^26]

***

## 11. Crowd Factor and Edge Decay

**Verdict: Edge has decayed but the full-profile GEX implementation preserves meaningful differentiation.**

By mid-2023, 0DTE options accounted for over 40% of all SPX options volume; by February 2025, this reached a record 56% share. This democratization has compressed the GEX edge in documented ways:[^27][^26]

1. Premium sellers flooding ATM strikes push implied vol lower, reducing gamma scalping profitability
2. Dealer gamma positioning is more dynamic intraday as retail flow surges during lunch hours
3. Pin points are less predictable due to fragmented activity across SPX, SPY, and multiple expirations

However, the GammaPulse implementation uses the *full gamma profile* across an 80-point spot grid, not simple put/call walls or max pain. Academic evidence supports this distinction: the crowding that has reduced edge is concentrated in the most obvious levels (round numbers, max pain) used by retail-grade tools. The GTBR-based inflection points identified in the 2024 AFA paper — which more closely resemble what GammaPulse's King/Floor/ZGL architecture approximates — remain less crowded because they require computing the dealer book's breakeven range, not just reading open interest.[^9]

***

## 12. Single Highest-Impact Improvement

**Implement 1DTE contract suggestions as the primary output for all PM session alerts (1:30–4:15 PM).**

Rationale: The PM entry window that provides 58–62% backtested win rates on the underlying move is precisely the window where 0DTE theta decay is most destructive. The GEX structural levels don't care about contract expiry — a bounce off the Floor at 2:00 PM is the same trade whether in 0DTE or 1DTE. But in 1DTE, the theta drag is ~20x lower per hour, spreads are slightly wider (~$0.04–0.07 vs $0.02–0.05) but manageable, and a 15-minute stall in the trade doesn't convert a winner to a breakeven or loss. This single change converts the strategy's worst structural weakness (theta destruction in the exact window it trades) into a manageable cost.[^22][^21]

Secondary improvements ranked by impact:
1. Add VIX1D > 35 hard skip
2. Switch EMA_PULLBACK/REJECTION detection to 5-min bars
3. Implement partial exit (+25% half-out, stop to break-even) for all directional scalps
4. Add confirmation requirement for ZGL_CROSS (1 bar sustained + 0.3% distance)
5. Fix the macro skip to be time-windowed for intraday events

***

## 13. On the Honest Question

> "Is this a real edge with disciplined execution on a small account, or is it sophisticated infrastructure around what's fundamentally a coin flip with leverage?"

It is not a coin flip. The academic literature confirms the GEX mechanism is real, the dealer hedging behavior creates predictable intraday dynamics, and the PM session win rate asymmetry (62% Power Hour vs 48% AM) is consistent with what the gamma-hedging-momentum research would predict — demand for delta hedging into the close creates the afternoon momentum documented by Baltussen et al..[^5][^4]

However, the strategy has a gap between "real edge on the underlying move" and "positive expectancy after option premium P&L." The aggregate retail 0DTE loss data is not evidence that the GEX thesis is wrong — it's evidence that most retail traders use 0DTE incorrectly (no structural filters, overtrading, no time stops, wrong expirations). The GammaPulse filters directly address most of those failure modes.[^3]

The realistic assessment: with the proposed fixes (1DTE primary, VIX filter, partial exits), the strategy has a plausible path to a positive-expectancy outcome, but the first 50–100 live trades should be treated as calibration data, not evidence of success. The per-alert-type win rate, live slippage, and fill quality on manual execution are unknowns that no amount of backtesting resolves. Start with the minimum position size ($100 risk per alert) and treat the first 3 months as live paper trading with real money at stake.

---

## References

1. [I analyzed 1.5M quotes to quantify the real bid-ask spread cost for 0DTE SPX Iron Condors.](https://www.reddit.com/r/options/comments/1n461td/i_analyzed_15m_quotes_to_quantify_the_real_bidask/) - I analyzed 1.5M quotes to quantify the real bid-ask spread cost for 0DTE SPX Iron Condors.

2. [0DTE Options: Are Higher Spreads Imminent? - Schaeffer's Investment Research](https://www.schaeffersresearch.com/content/bgs/2023/09/22/0dte-options-are-higher-spreads-imminent) - Taking a look at 0DTE options on the SPDR S&P 500 ETF Trust (SPY) and Invesco QQQ Trust Series 1 (QQ...

3. [Zero-day-to-expiry options: A losing bet for retail traders - Neudata](https://www.neudata.co/literature-reviews/zero-day-to-expiry-options-a-losing-bet-for-retail-traders) - Retail traders have been losing a total of $350k a day from betting on zero-day-to-expiry (0DTE) opt...

4. [Hedging Demand and Market Intraday Momentum](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3760365) - We provide novel evidence that links marketintraday momentum to the gamma hedging demand from market...

5. [Baltussen, G., Da, Z., Lammers, S. and Martens, M. (2021). Hedging ...](https://tinbergen.nl/index.php/publication/168044/hedging-demand-and-market-intraday-momentum)

6. [Hedging demand and market intraday momentum - ScienceDirect.com](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21001598) - We provide novel evidence that links market intraday momentum to the gamma hedging demand from marke...

7. [Hedging Demand and Market Intraday Momentum - PURE.EUR.NL.](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/) - Baltussen G, Da Z, Lammers S, Martens MPE. Hedging Demand and Market Intraday Momentum. Journal of F...

8. [Workflow](https://www.insiderfinance.io/resources/the-ultimate-guide-to-gamma-exposure-gex) - Learn what gamma exposure (GEX) is, how positive vs. negative gamma affects price action, what the g...

9. [[PDF] Where does gamma hedge drive the intraday market move?](https://afajof.org/management/viewp.php?n=129472) - Abstract. This study examines how option market makers' inelastic demand for delta-neutral hedges im...

10. [Conclusion: Using...](https://www.luxalgo.com/blog/spotgamma-levels-reveal-dealer-positioning/) - Explore how SpotGamma levels reveal dealer positioning to enhance trading strategies through market ...

11. [Introducing GEX: Dealer...](https://menthorq.com/guide/understanding-gamma-exposure-mechanics/) - This article explains how gamma exposure affects dealer hedging, moving markets mechanically through...

12. [0DTE SPY: The Complete Intraday Playbook for Same-Day Options](https://flashalpha.com/articles/0dte-spy-complete-intraday-playbook-same-day-options) - A data-driven playbook for trading SPY 0DTE options. Covers SPY's unique gamma profile, the Mon/Wed/...

13. [Improving 0-DTE Trading Returns By Avoiding Expensive Exits](https://www.volossoftware.com/insights/improving-0dte-trading-returns) - For our newest research paper, Volos analyzed historical intraday options pricing using Nasdaq-100® ...

14. [Retail Traders Love 0DTE Options... But Should They?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4404704) - Our study investigates trading in options that expire on the same day-so-called "0DTE" options-throu...

15. [Retail 0DTE Option Trader Performance](https://www.cxoadvisory.com/individual-investing/retail-0dte-option-trader-performance/) - Should individuals who trade zero-days-to-expiration (0DTE) S&P 500 Index options expect to make mon...

16. [0DTE Opening Range Breakout: Strategy Rules and Backtest Results](https://options.cafe/blog/0dte-opening-range-breakout-strategy-spy-backtested-results/) - For 0DTE SPY options, the spread is typically $0.02-0.05 per contract, but it can widen significantl...

17. [Gamma Exposure (GEX) and Option Expiry (OpEx) strategies ...](https://www.reddit.com/r/options/comments/1rwspuu/gamma_exposure_gex_and_option_expiry_opex/) - How does Gamma Exposure inform your trades this close to OpEx dates. Does anyone who trades the majo...

18. [Opening Range Breakout Strategy for 0DTE Options - GreeksLab](https://greekslab.com/blog/opening-range-breakout-strategy-for-0dte-options) - The extreme gamma of 0DTE options means a genuine breakout can cause an option to double or more in ...

19. [VIX1D Explained: 0DTE Intraday Volatility - Option Alpha](https://optionalpha.com/learn/vix1d-explained-0dte-intraday-volatility) - The VIX1D measures the expected volatility of the S&P 500 Index over the current trading day, and ha...

20. [0DTE or 1DTE? Choosing the Right Option for SPY Scalps](https://thetradingpub.com/roger-scott/0dte-or-1dte-choosing-the-right-option-for-spy-scalps/) - the decision between 0DTE and 1DTE — meaning zero days till expiration or one day till expiration — ...

21. [The Truth About 0DTE Options Time Decay](https://optionalpha.com/blog/0dte-options-time-decay) - Significant theta decay in 0DTE options occurs primarily after 3:30 PM ET. OTM options decay faster ...

22. [0DTE Theta Decay: How Same-Day Expiration Accelerates Time ...](https://marketxls.com/blog/0dte-theta-decay-what-every-trader-should-know) - The key takeaway from this hour-by-hour breakdown: roughly 60–70% of an ATM 0DTE option's time value...

23. [0DTE Options Time Decay Research + How to Take Advantage of It](https://optionalpha.com/videos/0dte-options-time-decay-research-how-to-take-advantage-of-it) - We observed the most significant price drop typically occurs around 15:30 (3:30 ET), where the sprea...

24. [0DTE Options Trading Strategy: Profit Targets, Win Rate & Risk](https://www.youtube.com/watch?v=VGjjNll86-4) - We break down two data-driven studies focused on 0 DTE options trading and how different trade manag...

25. [SPY Gamma Exposure (GEX) - InsiderFinance](https://www.insiderfinance.io/gamma-exposure/SPY) - Analyze SPY gamma exposure and market maker positioning to identify potential support, resistance, a...

26. [Gamma Exposure (GEX) and its Application to SPX 0DTE Options ...](https://technicalindicatorsthatsortofwork.com/blog/indications/gamma-exposure-gex-and-its-application-to-spx-0dte-options-trading) - Sign: A positive GEX value indicates net long gamma exposure for market makers, while a negative GEX...

27. [How Institutional Traders Exploit Gamma Explosion at Options ...](https://navnoorbawa.substack.com/p/how-institutional-traders-exploit) - This is a detailed research piece.

