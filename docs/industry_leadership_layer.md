# GammaPulse — Leading Stocks in Leading Industries as an RTS Layer
## Claude-Ready Integration Note

## Executive Summary

**Leading Stocks in Leading Industries** should be implemented in GammaPulse as an **industry-strength layer on top of RTS**, not as a separate standalone indicator.

This layer answers a specific question that RTS alone does not fully answer:

> **Is this stock strong in isolation, or is it also being supported by a strong industry/group?**

That distinction matters a lot for options.

Best framing:

- **GEX / structure** = where the trade might work
- **NYMO/NAMO** = whether market internals support reversal or follow-through
- **RTS** = whether the stock itself is high quality
- **Industry leadership layer** = whether the stock is in a strong group, with real cluster confirmation

This is how GammaPulse should think about single-stock opportunity quality.

---

## Why This Matters

RTS is already useful because it tells you:

- which stocks are strong
- which stocks have clean trends
- which names are extended
- which names deserve attention

But a stock can still look strong while:

- its industry is weak
- its move is isolated
- it has no real group sponsorship
- it is not part of a broader leadership cluster

The “leading stocks in leading industries” framework adds:

- **group confirmation**
- **sector/industry tailwind**
- **cluster leadership**
- **leadership breadth inside an industry**
- **better ranking of single-stock options candidates**

This is especially important for swing-style options.

---

## What This Layer Should Do

This layer should answer:

1. **Which industries are strongest right now?**
2. **Which stocks are leading within those industries?**
3. **Is a stock’s strength isolated or group-confirmed?**
4. **Are multiple strong names appearing in the same industry?**
5. **Is the industry leadership broad, narrow, emerging, or weakening?**

That is a powerful stock-selection advantage.

---

## Correct Role in GammaPulse

### This should be:
- an **RTS enhancement layer**
- a **sector/industry confirmation module**
- a **scanner-ranking boost**
- a **watchlist prioritization tool**
- a **single-stock options quality filter**

### This should NOT be:
- a replacement for RTS
- a replacement for GEX
- a replacement for breadth
- a macro timing engine
- a standalone “buy this now” system

---

## Best Mental Model

### RTS tells you:
**Is this stock strong?**

### Industry leadership layer tells you:
**Is this stock strong inside a strong group?**

That second question matters because:

- strong stocks in weak groups often fail faster
- strong stocks in strong groups tend to have better follow-through
- sector/group tailwinds improve options outcomes
- cluster leadership is often more durable than isolated leadership

---

## Recommended GammaPulse Architecture

## Layer Relationship

### Layer 1 — GEX / Structure
- support / resistance / regime / target zones

### Layer 2 — Breadth (NYMO/NAMO)
- market stretch
- reversal context
- macro confluence

### Layer 3 — RTS
- stock quality
- trend quality
- relative performance
- extension

### Layer 4 — Industry Leadership
- group strength
- stock-in-group ranking
- cluster validation
- sector tailwind / headwind

### Layer 5 — Liquidity / Volatility / Freshness
- spread quality
- options liquidity
- quote freshness
- event risk
- IV / RV / premium context

### Layer 6 — Discipline
- whether trade is allowed
- size
- risk reduction
- breaker / drawdown controls

---

## What This Layer Adds Beyond RTS

RTS alone can still miss:

- whether leadership is **broad or isolated**
- whether the stock’s move has **industry support**
- whether there are **multiple A-tier names in the same group**
- whether the strongest trade is not just a strong stock, but a **strong stock inside the strongest industry**

That is the whole point of this layer.

---

## Recommended Data Model

## 1. Industry Strength Score

Each industry should receive a score based on measurable components.

### Suggested components
- 1-week relative performance
- 1-month relative performance
- 3-month relative performance
- percent of stocks above 20MA
- percent of stocks above 50MA
- percent of stocks in top RTS buckets
- median RTS score within group
- number of A / A+ names
- market-cap-weighted relative performance (optional)

### Suggested output fields
- `industry_name`
- `industry_score`
- `industry_rank`
- `industry_rs_1w`
- `industry_rs_1m`
- `industry_rs_3m`
- `industry_pct_above_20ma`
- `industry_pct_above_50ma`
- `industry_top_tier_count`
- `industry_bullish_pct`
- `industry_state` = leading / improving / neutral / weakening / weak

---

## 2. Stock-in-Industry Score

Each stock should have fields that describe both its RTS quality and its position inside its industry.

### Suggested output fields
- `ticker`
- `industry_name`
- `rts_score`
- `rts_grade`
- `industry_rank_within_group`
- `industry_percentile_within_group`
- `industry_tailwind_score`
- `industry_cluster_flag`
- `extension_flag`
- `market_cap`
- `avg_dollar_volume`
- `atr_value`
- `options_liquidity_score` (optional later)

---

## 3. Industry Cluster Logic

This is one of the most useful parts.

A strong industry should not just have one lucky stock.

It should have:
- multiple strong names
- healthy internal breadth
- multiple A / A+ names
- consistent group-level strength

### Suggested cluster states
- **Leading Group**
- **Emerging Group**
- **Weakening Group**
- **Broken Group**

### Example logic
A group is **Leading** if:
- industry score is top decile or quartile
- at least N names are A / A+
- bullish percentage exceeds threshold
- short-term and intermediate-term RS agree

A group is **Emerging** if:
- group score is rising quickly
- top-tier count expanding
- trend breadth improving
- RS improving over the past 1–2 weeks

A group is **Weakening** if:
- still ranked high, but breadth is narrowing
- fewer A-tier names
- extension rising
- short-term RS fading

This is extremely useful for options.

---

## Recommended Formula Direction

Do NOT blindly clone the exact “week x month RS” approach from the screenshot source.

Instead, define your own explicit GammaPulse version.

## Suggested Industry Score Formula

A good first-pass model could be:

- **35%** = 1-month median relative performance
- **25%** = 1-week median relative performance
- **20%** = percent of stocks above 50MA
- **10%** = percent of stocks in A / A+ RTS buckets
- **10%** = median RTS score

This gives you:
- trend
- momentum
- breadth
- quality

That is enough for a strong v1.

---

## How This Should Affect GammaPulse Ranking

## For single-stock bullish setups
Boost score when:
- stock RTS is high
- industry score is high
- stock ranks near top of its group
- group has cluster confirmation
- stock is not overextended

Downgrade when:
- stock looks decent, but industry is weak
- group breadth is poor
- stock is isolated
- extension is extreme

## For single-stock bearish setups
Boost bearish interest when:
- stock RTS is weak
- industry is weak
- stock is among weakest in group
- weak group breadth confirms deterioration

---

## Suggested Ranking Influence

Do NOT let this fully dominate the signal.

Use it as a **ranking multiplier / boost**, not the whole system.

### Example
Single-stock score could later become:

`final_single_stock_score = structure_score + rts_score + industry_tailwind + breadth_context + liquidity_quality`

Where:
- `industry_tailwind` is a moderate contributor
- not the whole trade thesis

---

## Best Use Cases

This layer is strongest for:

- ranking call candidates after a bullish market signal
- ranking put candidates after market deterioration
- identifying sector clusters with multiple leaders
- finding better 14–30 DTE swing option names
- narrowing a long scanner list into a small number of high-quality targets

This layer is weaker for:

- pure SPY/QQQ intraday trades
- 0DTE index options
- exact entry timing
- standalone signal generation

---

## UI / Product Recommendations

## Recommended UI Elements

### 1. Industry Strength Board
Show:
- industries sorted strongest to weakest
- strength score
- bullish %
- count of A / A+ names
- top leaders in each group

### 2. Stock Matrix by Industry
Like the screenshot concept:
- rows = industries
- stocks displayed within groups
- sort left-to-right by market cap or RTS
- color by RTS bucket
- font / badge for extension
- optional badge for liquidity quality

### 3. Scanner Integration
In scanner results:
- show industry rank
- show industry state
- show stock rank within group
- show cluster flag

### 4. Watchlist Output
Create dynamic lists:
- leading stocks in leading industries
- strongest emerging groups
- weak stocks in weak industries
- extended leaders at risk of pullback

---

## Implementation Recommendation

## Best First Version
Build this in three stages.

### Stage 1 — Industry Strength Table
- compute industry scores
- compute industry ranks
- expose API endpoint
- display strongest / weakest industries

### Stage 2 — RTS + Industry Join
- link each stock to industry score
- compute stock rank within group
- add industry boost to scanner output

### Stage 3 — Cluster / Leadership States
- detect leading groups
- detect emerging groups
- add top-group watchlist logic
- add UI matrix view

This is the cleanest rollout.

---

## Suggested API Objects

### Industry summary endpoint
`/api/industry-strength`

Fields:
- industry
- score
- rank
- bullish_pct
- top_tier_count
- top_names
- state

### Stock ranking endpoint
`/api/rts-industry`

Fields:
- ticker
- rts_score
- rts_grade
- industry
- industry_score
- industry_rank
- rank_in_group
- industry_state
- extension_flag

### Scanner enrichment
Add:
- `industry_score`
- `industry_rank`
- `rank_in_group`
- `industry_state`
- `cluster_flag`

---

## Important Design Warnings

1. **Do not confuse sector strength with stock quality**
A strong industry does not automatically make every stock attractive.

2. **Do not ignore extension**
A top-ranked stock can still be too late for fresh calls.

3. **Do not let industry strength replace liquidity checks**
A strong industry with bad options spreads is still a bad trade vehicle.

4. **Do not use this for macro timing**
This is a stock-selection enhancement, not a market-timing engine.

5. **Do not copy another trader’s labels without formulas**
You need GammaPulse-native rules.

---

## My Recommendations

## Strong recommendations
- implement this as a layer on top of RTS
- compute explicit industry scores
- rank stocks within industry
- expose cluster leadership state
- use it to rank scanner results and watchlists
- keep extension separate from quality
- make it highly visible for single-stock option selection

## Do later, not first
- fancy market-cap visuals
- advanced clustering heuristics
- machine-learned group classification
- full historical rotation analytics

Start simple and explicit.

---

## Priority vs Other GammaPulse Work

### Higher priority than this
1. data freshness / timestamp integrity
2. bid-ask spread + liquidity filters
3. earnings / event handling
4. IVP / realized vol / VRP work
5. RTS core engine itself

### This layer’s priority
Very high for **single-stock expansion**  
Moderate for **platform differentiation**  
Low for **core SPY/QQQ intraday hardening**

---

## Best Final Summary

> **Leading Stocks in Leading Industries should be implemented in GammaPulse as an industry-strength and cluster-confirmation layer on top of RTS.**
>
> RTS tells you whether the stock is strong.  
> This new layer tells you whether the stock is strong inside a strong group.
>
> That makes GammaPulse better at:
> - selecting single-stock option candidates
> - ranking scanner output
> - identifying sector leadership
> - avoiding isolated false leaders
>
> It should be used as a stock-selection enhancement, not a replacement for GEX, breadth, liquidity, or volatility controls.

---

## Recommended Next Step for Claude

Ask Claude to help with one of these focused tasks:

1. define a full `industry_score` formula for GammaPulse
2. design the `industry_state` logic (leading / emerging / weakening / weak)
3. design the join between RTS and industry-strength in scanner ranking
4. propose API response schemas for industry and stock ranking endpoints
5. design a UI table / heatmap inspired by the screenshot, but translated into GammaPulse-native metrics

That will be much more useful than another generic review prompt.
