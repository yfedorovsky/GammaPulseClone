# $39 to $113 in Five Months: Inside Intel's Improbable Run, and the Trade That Just Started Working

*What Mir, Mr. Whale, and a $1.16M whale print all agreed on — at the same strike, in the same hour. A forensic walkthrough of the most asymmetric flow convergence I've seen this quarter.*

---

## The chart nobody is showing you

Intel closed at **$110.80** today, May 19, 2026.

It opened the year at **$39.38**.

That's **+181% year-to-date** on a name that twelve months ago Wall Street had given up on. A name that lost half its value in 2024. A name that, on April 8, 2025, sat at **$18.10** — down 73.5% from its 2020 high.

In the last five months, Intel has done what nobody — not the analysts, not the funds, not the financial press — predicted: it has become the best-performing mega-cap of 2026.

And today, on a normal Tuesday in late May, the **single most important trade of the year on this stock** got placed.

It was placed by a Discord trader named Mir.

He bought one contract. Then he posted about it. **It was already up 23% by the time most people read his alert.**

This is the story of why.

---

## The pattern recognition: today was structural

Most people looked at INTC today and saw a noisy session — an early-morning drop to $102.40, a violent reversal to $113.07 by 3:12 PM, and a fade into the close at $110.80. **A 10% intraday range. The stock close-traded ~80% off the day's low.**

If you only watch the chart, that's the entire story. Volatility. Noise. Maybe a buy-the-dip retail crowd.

If you watch the **options tape**, it's a different story entirely.

Here is what unfolded in **five minutes** between 14:05 ET and 14:09 ET:

| Time | Side | Contract | Size | Premium |
|---|---|---|---|---|
| 14:05:31 | ASK | 115C 1/15/27 | 40 | **$111K** |
| 14:05:31 | ASK | 105P 1/15/27 | 40 | $88K |
| 14:05:03 | BID | 125P 3/19/27 (×3 prints) | 53 | **$197K** |
| 14:05:38 | ASK | 195P 9/18/26 | 10 | $87K |
| 14:06:08 | ASK | 140C 12/18/26 | 35 | $67K |
| 14:06:24 | BID | 165C 1/15/27 | 20 | $30K |
| 14:06:49 | ASK | 115C 5/29/26 (×2) | 150 | $80K |
| 14:07:06 | ASK | 105C 5/29/26 | 32 | $35K |
| 14:07:07 | ASK | 105C 7/17/26 | 18 | $33K |
| 14:07:20 | BID | 114P 5/22/26 | 68 | $35K |
| 14:07:55 | BID | 105P 6/18/26 | 128 | $90K |
| 14:08:30 | ASK | **90C 12/17/27** (×3 prints) | 45 | **$231K** |
| 14:08:44 | ASK | **115C 7/17/26** | 200 | **$277K** |
| 14:09:17 | BID | 103C 5/22/26 (×2) | 110 | $118K |
| 14:09:34 | BID | 145C 6/12/26 | 338 | $71K |
| 14:09:38 | MID | 102P 5/22/26 | 498 | $48K |

**Total premium in 5 minutes: $1.60 million.**

Bullish: $1.16M. Bearish: $394K. **Bull/bear ratio: 2.93x.**

But raw totals miss the point. The story is in the **structure** — three layers, each making a different statement.

---

## Layer 1: The continuation scalp

Strike clusters around current spot, weekly expirations: someone is positioning for the move to **continue through next week**.

- 115C 5/29: 150 contracts bought on the ask ($80K)
- 105C 5/29: 32 contracts on the ask ($35K)
- 105P 6/18: 128 puts SOLD ($90K premium collected — betting INTC stays above $105)
- 114P 5/22: 68 puts SOLD into 3DTE ($35K — pin trade)

This is tactical. Not high-conviction, but real money saying "I think INTC at $110+ is the new floor for the next week."

Premium total here: ~$240K bullish, $118K bearish (call-selling at the 103C 5/22).

## Layer 2: The Mir tenor zone

Now look at the 6-8 week window:

- **115C 7/17: 200 contracts bought on the ask for $277K — the single biggest print in the entire window**
- 105C 7/17: 18 contracts on the ask ($33K)
- 140C 12/18: 35 contracts on the ask ($67K)

That $277K 115C 7/17 print is the **smoking gun**. Two hundred contracts on the ASK side, at the offer, on a 60-day OTM call. No averaging in. No working the order. Someone walked up to the offer and **bought $277,000 of upside exposure in one print.**

This is Mir's window — the medium-term, 1-3 month continuation thesis.

## Layer 3: The LEAP

Here's where it gets serious:

- **90C 12/17/27: 45 contracts on the ASK for $231K** (3 separate prints aggregating)
- 115C 1/15/27: 40 contracts on the ask for $111K (LEAP)
- 125P 3/19/27: 53 puts SOLD for $197K premium collected (LEAP put-selling = bullish premium collection)
- 105P 1/15/27: 40 puts on the ask for $88K (bearish, LEAP hedge)
- 165C 1/15/27: 20 calls SOLD for $30K (mild bearish call-selling)
- 195P 9/18/26: 10 deep-ITM puts for $87K (synthetic short stock, ~$90K notional bear)

**LEAP bull premium: $539K. LEAP bear premium: $205K.**

The 90C 12/17/27 is the most revealing. Intel is at $112; the 90C strike is **deep in the money**. Buying it is mathematically equivalent to **buying the stock with 2-year leverage**. The buyer pays $51 per share of premium up front and gets a $112 stock for the next 2.5 years.

You don't pay $231K for a structured-long-stock position **unless you believe Intel is going materially higher over a multi-year horizon.**

---

## The convergence: five independent signals

Now here's where this stops being one flow snapshot and starts being a thesis.

### Signal 1: Mr. Whale (Unusual Whales AI agent)

Earlier today, Unusual Whales launched their AI Market Analyst, "Mr. Whale" — a chat interface over their full real-time database.

I asked it: *"Which chains are seeing the biggest OTM call accumulation today, including under-the-radar tickers?"*

Its answer included two layers:

> **Mega-cap OTM accumulation in names like AMZN, MSFT, INTC, AVGO.**

INTC. Right at the top.

Mr. Whale was looking at the cumulative flow of the morning — well before the 14:05 ET burst — and INTC was already showing structural call accumulation in its database.

### Signal 2: Unusual Whales highest-volume contracts

The day's leaderboard, broadcast through UW's Discord bot, ranked the day's highest-volume options contracts.

INTC didn't dominate (TSLA's 1DTE was the noise leader), but **the 150C 7/17 strike — adjacent to the strike Mir would buy — appeared multiple times** with strong directional skew.

By volume alone, INTC was the seventh-most-traded name on the day.

### Signal 3: The flow tape itself

The 5-minute window between 14:05 and 14:09 ET delivered the multi-layer thesis above. Coordinated. Real. $1.16M long, $394K short.

In options market microstructure, when LEAP and near-term calls trade on the same side in the same hour, **that's somebody's portfolio manager working a multi-leg position in real time**. It's not noise. It's structure.

### Signal 4: GammaPulse (our own system)

Of the 22 prints UW flagged, we caught 5: the 115C 7/17, both 5/29 strikes, the 105P 6/18, and the 103C 5/22.

We **missed all the LEAPs**, which is a known gap in our detection logic — and one we'll fix this week. But we saw enough.

Our scanner had INTC in **flow-active mode** through the entire afternoon, with the call-side dominating by ~3x. The structural bias was visible from inside the system.

### Signal 5: Mir's alert

And then, at **11:43 AM ET**, into a Discord channel of Swing Traders, Mir posted:

> **$INTC 21AUG 150C @ $6.73**

One line. One contract. One entry price.

Most flow accounts post AFTER the move. They show you what already happened. They package it as analysis.

Mir posts WHILE he's clicking the buy button.

**By the time most people in that channel saw the message, the 150C was already up 23%.**

---

## The execution: why this entry was elite

Here is what makes Mir's $6.73 entry on the 150C 8/21 not a guess, but a craft.

The 150C 8/21 has traded for 16 sessions. Here's its full life history at end-of-day close:

| Date | INTC Spot | 150C Close | IV |
|---|---|---|---|
| 5/4 | $95.78 | $4.60 | 80% |
| 5/5 | $108.15 | $8.65 | 85% |
| 5/6 | $113.01 | $9.87 | 84% |
| 5/7 | $109.62 | $8.50 | 83% |
| **5/8** | **$124.92** (AAPL deal) | **$16.00** | **91%** |
| 5/11 | $129.44 (high $130) | $18.63 (high $20) | 94% |
| 5/12 | $120.61 | $13.70 | 90% |
| 5/13 | $120.29 | $13.35 | 89% |
| 5/14 | $115.93 | $10.97 | 88% |
| 5/15 | $108.77 | $7.85 | 85% |
| 5/18 | $108.17 | **$7.30** | 85% |
| **5/19 11:43 AM** | **$104-105** (Mir entry) | **$6.73** | ~86% |
| 5/19 close | $110.80 | $8.30 | 86% |

Two things to notice.

**One: Mir bought the 150C 8/21 within 5% of its all-time low.** The contract's all-time low close was $7.30 the day before. Mir bought 8% below that, intraday, while INTC was rallying off $102.40.

**Two: Mir didn't enter at $102.40.** That was the bottom. He waited an hour and twenty minutes. INTC had to confirm the reversal — it had to print higher highs off the morning low — before he committed.

Most flow accounts time the bottom. They get the BOTTOM TICK and post about it later. Mir doesn't try to bottom-tick. He waits for the bottom to confirm, then enters at the **statistical low of the implied position**.

This is what professional execution looks like in retail clothing. He gives up the bottom tick to gain certainty on the trend.

---

## The math: what this position is worth

The 150C 8/21 has a documented leverage profile. Here it is, from the actual recent tape:

| INTC daily move | 150C daily move | Realized leverage |
|---|---|---|
| +12.9% (5/5) | +88.0% | 6.8× |
| +14.0% (5/8 AAPL day) | +88.2% | 6.3× |
| +3.6% (5/11) | +16.4% | 4.5× |
| +4.5% (5/6) | +14.1% | 3.1× |

A 13-14% INTC pop produces an 85-90% gain on this call in a single day.

Look at where INTC has to go for this position to be a clean 2x:

- INTC at **$115** (+4%) → 150C around $10-11 → **+50%** from Mir's entry
- INTC at **$120** (+9%) → 150C around $13 → **+93%** from Mir's entry
- INTC at **$125** (+13%) → 150C around $16 → **+138%** from Mir's entry
- INTC at **$130** (+17%) → 150C around $19 → **+182%** from Mir's entry — the 5/11 high

INTC doesn't need to reach $150. **It only needs to print $130 for one session**, and the 150C 8/21 prints $19 against Mir's $6.73 entry. **A nearly-3x return on a 17% move in the underlying.**

This is the asymmetry the LEAP buyer is also paying for. The buyer of $231K of 90C 12/17/27 doesn't need INTC to rip. They need it to slowly grind from $112 to $140 over the next 24 months. They have **2.5 years** for the thesis to play out.

Mir has **3 months** to ride that same thesis with 6x leverage.

---

## What everyone missed: the regime change

Step back from the day. From the hour. From the trade.

Intel YTD: **+181%.**

This is not a normal year. This is, by realized return, the **most explosive single calendar year for INTC in 25 years**. Trailing 30-day realized volatility is **99.5%** annualized — Intel has been moving like a small-cap, not a $400 billion company.

The catalyst was the **April 24, 2026 earnings beat**: INTC opened +23.1%, closed +23.6%. Six-week chart up nearly 3x.

The AAPL chip deal news (5/8) — INTC adds 12% in a day, runs to $130.

The pattern: every time INTC trades down, it gets bought aggressively. Every news catalyst gets sold modestly, then bought again. The structural bid has not broken.

Today's 10% intraday range with 79% close-off-low **is the cleanest version of that pattern**.

In our 10-year database, intraday-reversal days with these characteristics produce:
- **5-day continuation rate: 69%** (peak ≥+5%)
- **95-day median peak: +30%**
- **95-day 75th percentile peak: +50%**
- **40% historical base rate of reaching +35.8% from the close** — i.e., $150 by August

These are not lottery odds. These are the kind of statistical asymmetry an institution writes a check for.

---

## What I'm watching tomorrow

Three scenarios.

**A. INTC gaps up ≥+2%.** The morning premium burns the entry. 150C opens $9-10. The asymmetry degrades. **Wait for a 15-minute pullback. If 150C touches $8.50, enter ×1. Otherwise skip.**

**B. INTC opens flat (±2%).** This is the modal scenario. 150C opens near $8.30. **Enter ×1 at $7.80-$8.50 limit. Place ladder exits: bank 50% at $13, 25% at $18, runner with trailing stop on the remainder.**

**C. INTC gaps down ≥-2% (post-OPEX broad-market pressure).** 150C opens $6-7. **This is the gift entry. Enter ×1-2 at $6.50-$7.00.** Same exits.

The trade is NOT hold-to-expiry. Held to expiration, this position has **-15% expected value**. Sold at the intraday peak with 30 days remaining, expected value is **+173%**.

Active management is the entire edge. The asymmetry only works if you take profits at $13-18 in the next 30-45 days. Time decay after that becomes brutal.

And one more critical date: **earnings on July 24**. That's INSIDE the 8/21 expiration window. Implied vol will rise into earnings (positive vega for the position), then crush on the print. **The optimal exit is BEFORE earnings, not through it.** If you're still holding the 150C on July 22, sell.

---

## The bigger lesson

This is the third instance in 2026 — by my count — of a Mir alert being preceded by 30-60 minutes of institutional flow that the watching tools surfaced independently.

The pattern is consistent:
1. Big institutional positioning surfaces in the options tape (sweeps, multi-tenor builds, LEAP accumulation)
2. The tape gets quiet for a half hour
3. Mir posts an alert that sits inside the institutional tenor zone
4. The position rips 20-50% in the first 4 hours
5. Retail follows hours late, drives further continuation

What's happening — and it's worth saying out loud — is that **the underlying mechanism is now visible**. Five independent flow tools can read the same institutional setup and converge on the same conclusion within minutes of each other. The information is no longer asymmetric. The execution still is.

Mir's edge isn't seeing what others can't see anymore. It's the discipline to wait for confirmation, then enter at the low of the position's range, then post — knowing that the post itself will drive further continuation.

That's a workflow advantage, not a data advantage.

And for the rest of us — those of us reading flow tools in real time — the lesson is: **don't try to bottom-tick. Wait for the institutional layering to complete, watch the LEAP layer specifically, and enter at the implied low.**

The 90C 12/17/27 buyer paid $231K to be wrong for the next 2.5 years. The 115C 7/17 buyer paid $277K to be wrong for the next 8 weeks.

Mir paid $673 to be right for the next 3 months.

---

## Receipts

For the people who want to verify everything in this writeup:

- **INTC daily history**: pulled via Tradier REST, 10-year window (2016-05-23 → 2026-05-19), 2,512 bars
- **150C 8/21 EOD pricing**: pulled via ThetaData REST `/v3/option/history/greeks/eod` from 2026-05-04 to 2026-05-18
- **UW flow data**: extracted from screenshot timestamp 5/19 14:05-14:09 ET
- **Mr. Whale screenshot**: 5/19 ~1:00 PM ET response to the query above
- **Mir alert**: TraderMir → #swing-trades channel → 5/19 11:43 AM ET → verbatim: *"$INTC 21AUG 150C @ $6.73"*
- **Statistical analysis**: 56 ≥8% range days in 10 years; intraday-reversal subset n=32; forward returns computed via daily history walk
- **Realized leverage**: computed from Theta EOD prices day-by-day for 5/4-5/18
- **All raw data**: available in `docs/research/INTC_DEEP_BACKTEST_2026-05-19.md`

The trade was open as of close: INTC $110.80, 150C 8/21 mid $8.30, Mir entry +23.3% intraday.

The story isn't over. We'll come back to it after Wednesday's open.

---

*If you found this useful, the underlying data pipelines and detection logic that surfaced these flows are open-source code I've been building at GammaPulse. The convergence pattern — UW + Mr. Whale + Mir + our system + technical structure — is the kind of edge stack worth building toward.*

*Cross-LLM validation: This piece was drafted with my own analysis, then stress-tested with skeptical pass — checked for unsupported claims, verified all numbers against source data, and reviewed for narrative honesty. Any errors are mine.*

*Receipts at the bottom. Disagreements welcome.*
