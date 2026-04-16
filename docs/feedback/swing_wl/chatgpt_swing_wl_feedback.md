# GammaPulse — Swing Watchlist Scanner Spec

## Purpose

Build a separate **Swing Watchlist Scanner** for **7–14 DTE options** and **1–5 day holds**.

This scanner is **not** the GEX scanner.  
It is a **pure relative-strength / trend / sector-rotation / options-tradability** scanner.

Goal:

> Surface names that are not just strong on chart, but also realistically tradeable with short-dated options.

---

## Core Opinion

The original filter set is **close**, but it is:

- **too light on options execution quality**
- **slightly too restrictive on sector filtering**
- **too dependent on “looks strong” rather than “is tradeable now”**

The scanner should answer one question:

> **Would I actually buy 7–14 DTE options on this ticker right now?**

---

## Recommended Structure

Use a **2-stage design**:

1. **Eligibility Filter**
   - Hard pass/fail gates
   - Removes junk, illiquid, weak, or hard-to-trade names

2. **Ranking Model**
   - Composite score
   - Sorts the survivors by quality

This is better than just sorting the whole universe by RTS.

---

# 1) Review of Original Proposed Filters

## Original
1. RTS score >= 50  
2. Price above 21 EMA and 50 SMA  
3. MA alignment: 21 EMA > 50 SMA (or close)  
4. ADR% >= 2%  
5. Volume >= 500K daily average  
6. Top 3 SPDR sectors by 1-month return  
7. IVP < 50%  
8. Spread < 10% on ATM options  

## Verdict

### Keep
- RTS as the backbone
- Price above key moving averages
- ADR / movement filter
- Stock volume filter
- IV-aware filter
- Bid/ask spread filter

### Change
- **RTS >= 50** is too average for a premium swing watchlist
- **Top 3 sectors only** is too restrictive as a hard rule
- **Spread < 10%** alone is not enough to define options liquidity

### Add
- **Option open interest**
- **Option daily volume**
- **Trend quality / persistence**
- **Entry quality / extension control**
- **Earnings proximity filter**
- **Market regime gate**

---

# 2) Recommended Eligibility Filter (Hard Gates)

These should be **pass/fail**.

## Trend / Relative Strength
- **RTS >= 60**
- **Close > 21 EMA**
- **Close > 50 SMA**
- **21 EMA >= 50 SMA**
- **50 SMA slope > 0**

### Why
This removes mediocre names and keeps the scanner focused on actual trend leadership.

---

## Movement / Underlying Liquidity
- **ADR% >= 2.5%** for standard names
- Allow **ADR% >= 2.0%** for mega-caps if needed
- **Average daily stock volume >= 1,000,000 shares**

### Why
For 7–14 DTE options, the stock needs to move enough to create payoff.
500K average stock volume is probably too low for a premium swing-options scanner.

---

## Options Tradability
- **ATM option spread <= 8% of mid** preferred
- Hard reject above **10%**
- **ATM or target-strike open interest >= 500**
- **Front-month option volume >= 100** preferred

### Why
Spread alone is not enough.
You need actual participation and depth.
A “great chart” with weak option OI/volume is not a real candidate.

---

## Event Risk
- **No earnings within 5 trading days** for standard swing mode

### Why
For 7–14 DTE trades, an earnings event can dominate P&L through gap risk and IV behavior.
If you want earnings trades later, make that a separate mode.

---

## Entry / Extension Control
Use at least one of these:
- **Price within 0–8% of 20-day high**
- or **first clean pullback to the 21 EMA**
- reject names that are **too extended from the 21 EMA**

### Why
A strong stock can still be a bad entry.
This scanner should not just find leaders — it should find leaders at usable locations.

---

## Market Regime Gate
For long candidates, require one of:
- **SPY > 21 EMA**
- or **SPY 21 EMA > 50 SMA**
- or **SPY RTS / trend regime = bullish**

### Why
Even a pure RS scanner benefits from a market context gate.
Do not aggressively surface long swings in objectively poor tape.

---

# 3) Recommended Ranking Model

## Do not sort by RTS alone

RTS should be the **largest input**, but not the only one.

If you sort only by RTS, you will over-rank:
- extended names
- illiquid option chains
- names with expensive vol
- names far from good entry points

Use a **composite score**.

---

## Suggested Composite Weights

```text
SwingScore =
0.35 * RTS_norm +
0.20 * TrendQuality_norm +
0.15 * SectorStrength_norm +
0.10 * EntryQuality_norm +
0.10 * OptionsLiquidity_norm +
0.10 * Value_norm
```

## Weight Rationale

### 35% RTS
Still the anchor.
This is the primary signal for leadership.

### 20% Trend Quality
Separates clean, persistent trends from sloppy names that merely sit above moving averages.

### 15% Sector Strength
Sector rotation matters, but should not dominate the model.

### 10% Entry Quality
Avoid ranking names too far above actionable entries.

### 10% Options Liquidity
Prevents garbage option chains from surfacing too high.

### 10% Value
Rewards lower IVP / more reasonable IVHV.

---

# 4) How to Define the Subscores

## RTS_norm
Use your existing 0–100 RTS and normalize to 0–1.

```text
RTS_norm = RTS / 100
```

---

## TrendQuality_norm
Possible components:
- percent of last 10 closes above 21 EMA
- 20-day slope
- 20-day linear regression fit / trend efficiency
- percent of up days in last 20 sessions
- max pullback depth during last 20 sessions

Simple version:

```text
TrendQuality =
0.4 * pct_closes_above_21_last10 +
0.3 * slope_20_norm +
0.3 * up_day_ratio_20
```

Goal:
Reward orderly, persistent trends instead of noisy ones.

---

## SectorStrength_norm
Use sector 1-month return rank.

Suggested scoring:
- Top 3 sectors: full bonus
- Rank 4–5: medium bonus
- Rank 6–8: neutral
- Bottom 3: penalty

Example normalized mapping:

```text
SectorStrength_norm =
1.00   if sector_rank <= 3
0.70   if sector_rank in [4,5]
0.50   if sector_rank in [6,7,8]
0.25   if sector_rank in [9,10,11]
```

Important:
This should be a **soft scoring layer**, not a hard inclusion filter.

---

## EntryQuality_norm
Reward names that are:
- near a breakout
- on first pullback
- not too extended

Example framework:

```text
distance_from_21 = (close - ema21) / ema21
distance_from_20d_high = (high20 - close) / high20
```

Heuristic scoring:
- Best if close is near 20-day high **or** on a clean 21 EMA pullback
- Penalize if > 8–10% above 21 EMA
- Penalize if already far past breakout extension

Example:

```text
EntryQuality_norm =
1.0 if first_pullback_to_21
0.9 if within_3pct_of_20d_high
0.7 if within_5pct_of_20d_high
0.3 if extended_gt_8pct_above_21
```

---

## OptionsLiquidity_norm
Blend:
- spread quality
- open interest
- option volume

Example:

```text
OptionsLiquidity_norm =
0.5 * SpreadScore +
0.3 * OIScore +
0.2 * OptionVolumeScore
```

### Example subscores

```text
SpreadScore = clamp(1 - (spread_pct / 0.10), 0, 1)
OIScore = clamp(OI / 2000, 0, 1)
OptionVolumeScore = clamp(option_volume / 500, 0, 1)
```

---

## Value_norm
Blend:
- IVP
- IVHV ratio

Suggested logic:
- reward low-to-moderate IVP
- reward reasonable IVHV
- avoid very high IVP for standard directional swings

Example:

```text
IVP_score =
1.0 if IVP < 30
0.8 if IVP < 40
0.6 if IVP < 50
0.3 if IVP < 60
0.0 if IVP >= 70
```

For IVHV:
- best if elevated but not extreme
- avoid obviously overpriced options unless momentum is exceptional

You can keep this simple initially.

---

# 5) Sector Filter: Hard or Soft?

## Recommendation: Soft

Do **not** hard-filter to only the top 3 sectors.

That is too restrictive and will throw away legitimate strong outlier names.

## Better approach
Use sector strength as a **bonus / penalty** layer:

- Top 3 sector: **+ strong bonus**
- Rank 4–5: **+ mild bonus**
- Middle sectors: **neutral**
- Bottom sectors: **penalty**

Example additive overlay:

```text
sector_bonus =
+10 if sector_rank <= 3
+5  if sector_rank in [4,5]
 0  if sector_rank in [6,7,8]
-10 if sector_rank >= 9
```

This is the right balance between:
- acknowledging rotation
- not suffocating individual stock leadership

---

# 6) What Professional Screeners Often Include

These are the most useful additions beyond your current proposal.

## A. Option Open Interest
Critical.
A spread filter without OI can still let low-participation junk through.

---

## B. Option Daily Volume
Needed with OI.
Use current daily volume or average recent volume if available.

---

## C. Earnings Filter
Must-have for short-dated swing options.

---

## D. Market Regime Filter
Especially if this becomes a trusted retail-facing scanner.
Do not encourage long swings against poor market tape.

---

## E. Trend Quality / Efficiency
Above-MA alone is not enough.
You want clean, persistent behavior.

---

## F. Entry Quality / Extension
Pro screeners often care not only about “strong” but also “timely.”

A scanner should know the difference between:
- leader in a valid buy zone
- leader that is already too extended

---

## G. Breakout / Pullback State Tagging
Even if not used in ranking, it is useful for display tags:
- Near breakout
- First pullback
- Extended
- Tight base
- At 21 EMA
- Near 20-day high

These tags make the scanner much more usable.

---

# 7) Recommended Output Columns

For the scanner tab, show:

- Ticker
- Price
- RTS
- SwingScore
- Sector
- Sector Rank
- ADR%
- Avg Volume
- Close vs 21 EMA (%)
- Close vs 50 SMA (%)
- 20-day High Distance (%)
- IVP
- IVHV
- ATM Spread %
- ATM OI
- Option Volume
- Earnings Days Away
- Entry Tag
- Sector Tag
- Notes / Flags

Suggested tags:
- **Leader**
- **Top Sector**
- **First Pullback**
- **Near Breakout**
- **Cheap IV**
- **Liquid Chain**
- **Extended**
- **Earnings Soon**
- **Weak Sector**

---

# 8) Recommended Default Filters for Initial Release

## Hard Filter
- RTS >= 60
- Close > 21 EMA
- Close > 50 SMA
- 21 EMA >= 50 SMA
- 50 SMA slope > 0
- ADR% >= 2.0%
- Avg volume >= 1M
- ATM spread <= 10%
- ATM OI >= 500
- No earnings within 5 trading days
- Long-only regime gate passes

## Ranking
Sort by **SwingScore**, descending.

---

# 9) “Wifey Swing” Variant (Simpler, Longer-Hold Mode)

Use case:
- **14–30 DTE**
- simpler entries
- longer holds
- less twitchy than the default scanner

## What to change

### Loosen
- ADR requirement: **1.5%–2.0%**
- sector urgency
- strict IVP pressure slightly

### Tighten
- trend stability
- earnings avoidance
- extension control

## Recommended Wifey Filters
- RTS >= 65
- Close > 21 EMA > 50 SMA
- 50 SMA rising
- Price within 5% of 20-day high **or** first pullback to 21 EMA
- ADR >= 1.5%
- Avg stock volume >= 1M
- ATM / target-month spread <= 10%
- OI >= 750
- No earnings within 10 calendar days
- Prefer sectors in top half, not top 3 only

## IVP handling for Wifey mode
Do **not** hard reject at IVP 50.
Instead:
- best score below 40
- neutral 40–60
- hard reject above 70

Reason:
Longer-hold directional trades can still work with moderate IVP if the trend is exceptionally clean.

---

# 10) Refresh Frequency

## Recommendation
Use **daily ranking as the source of truth**.

### Best setup
- **Full recompute after market close**
- **Light refresh after first 30–45 minutes of next session**
- Optional **intraday liquidity refresh every 15–30 minutes**
  - spread
  - option volume
  - maybe price-extension tag

## Do not
Do **not** fully rerank the swing scanner every 2 minutes.

Reason:
This scanner is based mostly on:
- daily trend
- sector rotation
- relative strength
- options tradability

Those do not need hyper-frequent recomputation.

Intraday updates should mostly refresh:
- spread quality
- option activity
- extension / entry state

---

# 11) Direct Answers to the Original Questions

## 1. Is the filter set reasonable?
Yes, but it is:
- **under-filtered on options execution quality**
- **slightly over-filtered on sector rotation**

## 2. What is missing?
Add:
- option open interest
- option volume
- earnings filter
- market regime gate
- trend quality
- entry quality / extension logic

## 3. How should the final list be ranked?
Use a **composite score**, not RTS alone.

## 4. Should sector be hard or soft?
**Soft.**
Use sector leadership as a bonus/penalty layer, not a strict inclusion rule.

## 5. What changes for the wifey swing use case?
- longer DTE
- looser ADR
- tighter trend cleanliness
- more conservative earnings avoidance
- softer IVP handling

## 6. What is the optimal refresh frequency?
- daily full ranking
- light intraday liquidity refresh
- do not fully rerank every 2 minutes

---

# 12) Recommended Final Version (Practical)

## Stage 1 — Eligibility
Pass only if:
- RTS >= 60
- Close > 21 EMA and 50 SMA
- 21 EMA >= 50 SMA
- 50 SMA slope positive
- ADR >= 2.0% to 2.5%
- Avg stock volume >= 1M
- ATM spread <= 8% preferred / <=10% hard max
- ATM OI >= 500
- No earnings within 5 trading days
- Market regime long gate passes

## Stage 2 — Ranking
Sort survivors by:

```text
SwingScore =
0.35 * RTS_norm +
0.20 * TrendQuality_norm +
0.15 * SectorStrength_norm +
0.10 * EntryQuality_norm +
0.10 * OptionsLiquidity_norm +
0.10 * Value_norm
```

---

# 13) Bottom-Line Recommendation

Do **not** let this become just a “good-looking stock list.”

Design it so that it explicitly answers:

> **Which names are strong, clean, timely, and actually tradeable with short-dated options?**

That means:
- keep RTS as the backbone
- add real options liquidity tests
- make sector rotation soft, not hard
- rank by composite score
- refresh daily, not every 2 minutes
- add a simpler “wifey swing” mode separately

---

# 14) Suggested Future Enhancements

Once the base version works, consider adding:

- long / short symmetry
- breakout vs pullback sub-modes
- earnings mode as separate toggle
- quality-of-trend score using regression efficiency
- relative strength vs sector and vs SPY separately
- auto-generated “why this ranked” explanations
- watchlist buckets:
  - Leadership
  - Pullbacks
  - Near Breakouts
  - Cheap Premium
  - Cleanest Trends

---

# 15) Implementation Hint

A good UI pattern:

## Tabs or toggles
- **Core Swing**
- **Wifey Swing**
- **Pullbacks**
- **Near Breakouts**
- **Top Sectors**
- **Cheap IV**

## Row badges
- Leader
- Top Sector
- First Pullback
- Near Breakout
- Cheap IV
- Liquid Chain
- Extended
- Earnings Soon

That will make the scanner feel much more actionable than a generic ranked table.

