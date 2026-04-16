# SPY/QQQ 0DTE + 1DTE Scalp Strategy — External Review Prompt

**System:** GammaPulse — personal options trading platform
**Author:** Solo retail trader, $20K account, "degen fraction" allocation (max 10-15% = $2-3K)
**Status:** Built but not yet live-tested. Seeking brutal honest review before first real trades.
**Date:** April 14, 2026

---

## What This Is

A systematic 0DTE/1DTE directional scalp strategy for SPY and QQQ using dealer gamma exposure (GEX) levels as dynamic support/resistance, with volume confirmation and multiple safety filters. This is SEPARATE from our main Mir momentum swing strategy (7-14 DTE sector leaders).

This is the "fun money" / high-risk portion of the account. Not the core strategy.

---

## Strategy Overview

### Signal Generation

We compute dealer gamma exposure profiles from live options chains (BSM gamma across 80-point spot grid). This produces structural levels:

- **King** — highest net gamma strike (dealer magnet / equilibrium)
- **Floor** — strongest positive gamma below spot (dealer support)
- **Ceiling** — strongest positive gamma above spot (dealer resistance)
- **ZGL** — zero gamma line (regime boundary between positive/negative gamma)

Alerts fire ONLY on state transitions — the moment price crosses or bounces off a structural level, not while it sits near one.

### Alert Types (7 total)

| Alert | Trigger | Direction | Description |
|-------|---------|-----------|-------------|
| BUY_DIP | Price bounced off floor | CALLS | Was at/below floor, now moving away up |
| BREAKOUT | Price crossed above king | CALLS | Dealers chasing, momentum accelerating |
| RETEST | Price pulled back to king from above | CALLS | Classic breakout-retest entry |
| SELL_POP | Price hit ceiling and rejecting | PUTS | GEX resistance confirmed |
| FLOOR_BREAK | Price broke below floor | PUTS | Air pocket, dealers amplifying |
| ZGL_CROSS_UP | Price crossed above ZGL | CALLS | Regime improving |
| ZGL_CROSS_DOWN | Price crossed below ZGL | PUTS | Regime deteriorating |
| EMA_PULLBACK | 15-min price bounced off 8 EMA | CALLS | Mir's #1 intraday entry trigger |
| EMA_REJECTION | 15-min price broke below 8 EMA | PUTS | Trend support lost |
| TREND_CONTINUATION | Gap-and-go day, above 8 EMA | CALLS | No pullback wait on trend days |

### Filters (all must pass)

1. **GEX Magnitude > $1M** — total absolute gamma exposure must exceed $1M. Skips dead tape where levels are meaningless.

2. **15-min Volume >= 80% of 20-bar average** — current bar must have real participation. Does NOT veto the alert (gamma squeezes can start on normal volume), but tags it as confirmed or not. You see it in the Telegram alert and decide.

3. **Time Window:**
   - Normal days: PM session only (1:30 PM - 4:15 PM ET). Backtest-validated: PM momentum 58% WR +0.24%, Power Hour 62% WR +0.37%.
   - Trend days (>2% gap): allowed from 10:00 AM after first-hour settle.
   - AM session disabled (backtest: 48% WR, 0% EV).
   - Midday disabled (Mir: "chop zone, avoid").

4. **High-Impact Macro Day Skip** — checks Finnhub for FOMC, CPI, PPI, NFP. If any high-impact event today, zero scalp alerts. Whipsaws kill 0DTE.

5. **State Transition Only** — alerts fire on the CROSS or BOUNCE, not on proximity. Price sitting 0.2% from floor for 30 minutes does NOT fire an alert. Price dipping to floor and then bouncing 0.3% away DOES.

6. **15-minute cooldown per alert type per ticker** — prevents the same alert from firing every 30 seconds on oscillation.

7. **Max 2 alerts per ticker per day** — forces selectivity, prevents overtrading.

### Contract Selection

Currently: 0DTE only (today's expiration). ATM or slightly OTM strike rounded to $5 increments for SPY.

Mir's preference from years of Discord data: "forget 0DTE crap, at least 1DTE for buffer." The system notes this in every alert ("1DTE preferred for buffer") but currently only suggests 0DTE contracts.

### Entry/Exit (manual, not auto-traded)

- **Entry:** You receive Telegram alert, decide within seconds, buy at the ask.
- **Target:** +30-60% on the contract, or the next GEX level (whichever comes first).
- **Stop:** Hard stop if the structural level breaks against you (e.g., floor breaks on a BUY_DIP).
- **Time stop:** If not up 20%+ by 3:00 PM, scratch it (theta acceleration).
- **Hold time:** 5-30 minutes typical. Never overnight on 0DTE.

### Position Sizing

- **Max risk per alert:** 0.5-1% of total account ($100-200 on $20K)
- **Contracts:** 1-2 per trade (premium typically $1-4 for ATM SPY 0DTE)
- **Daily max:** 2 alerts traded, pick the cleanest setups

---

## What We Know From Backtesting

### Power Hour SPY Scalp (5-min bars, 15 months)
- 61% win rate
- +0.37% avg per trade (on SPY spot, not option premium)
- Best intraday window by far

### PM Momentum (1:30-3:00 PM)
- 58% win rate
- +0.24% avg per trade

### AM Momentum (9:30-11:30)
- 48% win rate
- 0% EV — disabled

### What We DON'T Know
- Live fill slippage on 0DTE contracts (bid-ask spread walk)
- Actual win rate on the alert types (no per-alert-type backtest, only time-window backtest)
- Performance during VIX > 25 or high-vol regimes
- How often the volume filter would have blocked good setups
- Whether 15-min EMA pullback detection lags the move (Grok's concern)

---

## Data Sources

- **GEX levels:** Computed from Tradier options chains (refreshed every 2 minutes) + Massive/Polygon for real-time Greeks on SPY/QQQ
- **15-min bars:** Tradier timesales API, cached 5 minutes
- **Spot price:** Tradier streaming/polling (sub-second on SPY)
- **Volume:** From 15-min bars (lagging by definition — this is a known weakness)
- **Economic calendar:** Finnhub (for macro day skip)

---

## Known Weaknesses (be honest about these)

1. **15-min volume confirmation lags.** By the time the bar closes, the explosive move may be over. We mitigated by making volume informational (not a hard veto), but it's still lagging.

2. **GEX data is refreshed every 2 minutes.** Levels can shift during fast moves. We're not using real-time OPRA-grade data (SpotGamma level). We're using Tradier chains + Massive Greeks.

3. **No cumulative delta / order flow.** We don't have Level 2 / tape reading. The volume bar is our only participation proxy.

4. **No VIX filter.** High VIX = wider spreads, faster moves, worse fills. We don't explicitly skip high-VIX days (only high-impact news days via Finnhub).

5. **Execution is manual.** Telegram alert -> you see it -> you click buy. Even 3-5 seconds of delay + spread costs money on 0DTE.

6. **Theta decay is brutal.** After 2:30 PM, 0DTE options lose value fast even if spot is flat. A winning position can turn into a loser just from time passing.

7. **Crowd factor.** GEX walls are widely known since 2023-2024. The edge has decayed as more participants watch the same levels. However, our implementation uses the full gamma profile (not just max pain or simple put/call walls), which is more sophisticated than most retail tools.

8. **1DTE not implemented.** Mir says 1DTE is better for buffer against theta and pin risk. We only suggest 0DTE contracts currently.

---

## What We Want From This Review

### For Grok (brutal honesty, no sugarcoating)
1. Is this strategy fundamentally viable for a $20K retail account, or am I fooling myself with sophisticated infrastructure around a losing game?
2. What's the realistic expected Sharpe after slippage + commissions on 1-2 contracts?
3. The 15-min volume lag — is it fatal, fixable, or acceptable? Would switching to 5-min bars help, or just add noise?
4. Should I add a VIX filter? If so, what threshold? VIX > 20? > 25? > 30?
5. Am I better off with 1DTE instead of 0DTE for the extra theta buffer? What's the tradeoff?
6. The GEX levels update every 2 minutes — is that fast enough for 0DTE, or am I always trading stale structure?
7. What's the single highest-impact improvement I could make to this exact setup?

### For ChatGPT (practical implementation review)
1. Review the 7 alert types. Are any of them structurally flawed or redundant?
2. The exit logic (30-60% target, stop on level break, time stop at 3 PM) — is this optimal for 0DTE gamma characteristics?
3. Max 2 alerts per day — is this too conservative? Too aggressive? Should it be 1?
4. The macro day skip uses Finnhub "high impact" — is this filter too broad or too narrow?
5. Position sizing at 0.5-1% per trade — given the 0DTE risk profile, should this be lower?
6. Should I implement the +25% partial take (sell half, move stop to breakeven) for 0DTE scalps, or is the hold time too short for that to matter?

### For Perplexity (academic/empirical research)
1. What does the academic literature say about intraday gamma exposure as a predictor of SPY price dynamics? Cite specific papers (2023-2026).
2. Is there empirical evidence that dealer hedging creates predictable support/resistance at high-gamma strikes? What's the effect size?
3. What's the documented bid-ask spread cost on SPY 0DTE ATM options as a function of time to expiry? How does it compare to 1DTE?
4. Has anyone published on the decay of the GEX edge as it became more widely known (2023 vs 2024 vs 2025)?
5. What does the research say about optimal holding periods for 0DTE directional positions?
6. Volume confirmation for intraday reversals — what bar interval shows the best predictive power (1-min? 5-min? 15-min?)?
7. What's the empirical win rate for "support bounce" strategies on SPY during the PM session vs AM?

### For Gemini (engineering stress test)
1. The 2-minute GEX refresh cycle — what's the risk that levels shift materially between refreshes during a 0DTE session? Can you quantify the staleness risk?
2. 15-min bar volume as a confirmation signal — what's the information loss vs 5-min or 1-min bars? Is 80% of 20-bar average a reasonable threshold, or should it be adaptive?
3. The alert cooldown (15 min per type) vs daily cap (2 per ticker) — are these interacting in unexpected ways? Could they create blind spots?
4. Theta decay profile: at what point in the session does holding a 0DTE ATM call become negative EV even with a directional edge? Model this explicitly.
5. If I switch to 1DTE, how does the gamma/theta tradeoff change for my specific entry windows (1:30-4:00 PM)?
6. The macro day skip checks Finnhub once per 30-second cycle — what if the event is mid-day (e.g., FOMC at 2 PM)? Should the skip be time-windowed?
7. Simulate: with 55% win rate, +40% avg winner, -80% avg loser, 2% commission drag — what's the breakeven threshold after 200 trades?

---

## System Architecture (for context)

```
Worker (every 2 min)
  -> Fetch SPY/QQQ chains from Tradier + Massive Greeks
  -> Compute GEX profile (BSM gamma across 80-pt spot grid)
  -> Identify king/floor/ceiling/ZGL
  -> Cache state

Scalp Scanner (every 30 sec)
  -> Read cached GEX state for SPY/QQQ
  -> Check all 7 state transition conditions
  -> Refresh 15-min bars (5-min cache TTL) for EMA + volume
  -> Apply filters (GEX magnitude, volume, time window, macro skip, daily cap)
  -> Fire Telegram alert with contract suggestion

You (human)
  -> Receive Telegram
  -> Decide in seconds
  -> Execute on broker (E-Trade / Tradier)
```

---

## Future Exploration (pinned, not for v1)

- **Basket-informed scalp selection:** When the PIT quarterly basket favors Technology/Communication sectors → lean QQQ for 0DTE scalps (60%+ tech-weighted). When Financials/Industrials dominate → lean SPY. The same basket that drives Mir swing trades could inform which index to scalp on a given day. Track in the 50-trade log: did the scalp align with active basket sector strength?

---

## The Honest Question

Is this a real edge with disciplined execution on a small account, or is it sophisticated infrastructure around what's fundamentally a coin flip with leverage?

I'm not asking for encouragement. I'm asking for the truth, with math.
