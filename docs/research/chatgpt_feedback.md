# ChatGPT Feedback — Skylit Reverse-Engineering

**Received:** 2026-04-16
**Model:** ChatGPT (version not specified by user)

## TL;DR

**Stop trying to match Skylit exactly with Tradier-level data.** Most likely
explanation is NOT a missing scaling constant. Skylit is using a hybrid of
**dealer-inferred sign + intraday flow + minute-updated exposure map** that
cannot be reproduced from retail chain snapshots.

## Hypothesis Ranking

**Most likely: H4 + H2 combined**
- Skylit shows something closer to dealer-inferred, flow-adjusted exposure
- Not pure local OI gamma
- Public docs emphasize real-time minute updates, live options flow, dealer
  long/short gamma polarity — but never commit to a reproducible formula
- Sign classifier failures confirm: they're not using naive call+/put- or
  even simple above/below-spot heuristic

**Plausible but secondary: H1** — their OI may be different/better, but alone
can't explain the worst outliers (e.g., $167.5 with vol=427 still shows $473K)

**Some contribution: H3** — volume × delta flow notional can create big
numbers on hot OTM strikes, but doesn't naturally explain all signs + magnitudes

**Unlikely core explanation: H5/H6/H7** — rolling OI, volume-as-OI, or simple
units/scaling. Doesn't fit the failure pattern.

## What Skylit Probably Does

```
1. Base local gamma exposure map from chain data
2. Infer dealer sign / net customer positioning using intraday flow
3. Amplify or attenuate strikes based on:
   - same-day traded flow concentration
   - buy-initiated vs sell-initiated classification
   - price relative to spot / likely pin zones
   - smoothing / clustering around neighboring strikes
4. Recompute every minute as flow changes
```

## Analysis of Specific Outliers

### AAOI 4/24 $210 call (OI=25, vol=5567, Skylit $2.66M, ours $3K)

"That cell screams: **today's flow dominated the node, not OI**."

Without trade classification data you don't know:
- Was volume mostly bought or sold?
- Opening vs closing?
- Dealer side net short or reducing risk?

**Verdict: basically unidentifiable from our data.**

### AAOI 4/17 $155 (our +$1.27M, Skylit -$320K)

Classic pattern: old OI says one thing, today's flow says dealer is on
opposite side now, Skylit downweights stale exposure because price/flow
migrated. **Flow-inferred sign + smaller effective notional.**

## Is Skylit Just Wrong/Exaggerated?

"Yes, absolutely. And I think you should consider that seriously."

Their public content is polished, behavioral, education-heavy, and notably
non-formulaic. May be:
- **Designed as decision-support visualization**, not literal local-GEX map
- **Story-consistent** rather than formula-consistent
- Dramatic outliers may be intentional amplification

## What Data We'd Need to Close the Gap

Not "more regression." **Better market microstructure data:**
- Per-trade timestamps
- Trade price vs bid/ask at execution
- Aggressor-side inference (buy vs sell initiation)
- Opening vs closing trade classification
- Intraday OI proxies / OCC-quality updates
- Quote size / depth

Without that, you're stuck trying to infer a flow-based object from stale OI
+ cumulative volume + live-ish Greeks. **Not enough.**

## Practical Recommendation

**Stop trying to match Skylit's numbers** — dead end with current data.

**Build a better retail-honest model with TWO metrics:**

### Model A — conservative local GEX

```
GEX = gamma × OI × 100 × S² × 0.01 × sign
```
Base structure map. Clear methodology.

### Model B — flow-pressure overlay (separate metric)

Using:
- same-day volume
- delta / gamma
- spot-aware sign heuristic
- above spot / below spot context
- normalized by average volume / OI

Call it something like `flow_pressure` or `intraday_gamma_pressure`.
**Do NOT pretend it's the same object as GEX.**

### UI

Show BOTH:
- Base GEX (conservative, reproducible)
- Flow pressure today (dramatic, intraday-driven)

Labels make clear what's what. More honest AND more useful than trying to
force one hybrid metric to mimic Skylit.

## Bottom Line

- **Most likely:** Skylit uses proprietary, flow-adjusted dealer-positioning
  model that cannot be reproduced with retail chain data alone
- **Second most likely:** their display is partly dramatized / heuristic,
  not meant to correspond to textbook local GEX
- **Least likely:** we're one missing constant away from matching them
