# Grok Feedback — Skylit Reverse-Engineering

**Received:** 2026-04-16
**Model:** Grok (xAI)

## TL;DR

Skylit's GEX is a proprietary, flow-inferred dealer-microstructure model —
not any standard OI- or volume-based formula. **Their own documentation
confirms this directly.**

Grok quotes Skylit: HeatSeeker uses *"custom inference models and proprietary
intelligence built from years of research into dealer microstructure."* The
numbers *"aren't just aggregated from a data vendor"* but are derived from
models that capture *"the nuances of how dealers actually position and
hedge."*

## Hypothesis Ranking (Grok's Confidence Levels)

| # | Hypothesis | Likelihood |
|---|---|---|
| H4+H8 | Dealer-inferred sign from order flow + proprietary net-notional | **~90%** |
| H2 | Composite metric, flow-accelerated | Plausible secondary |
| H1 | Different OI source | Unlikely (Skylit's own docs say it's NOT raw exchange data) |
| H3/H6/H7 | Volume proxy / scaling / units | Ruled out by our fits |
| H5 | Multi-day OI | Minor smoothing at most |

## What Skylit Is Actually Doing

Per Grok's analysis:

1. Classify trades via OPRA tick data (aggressive buyer/seller)
2. Infer customer net flow per strike/expiration
3. Treat dealers as mirror-image counterparty
4. Maintain a **running net dealer position** (not gross OI)
5. `GEX = γ × (inferred net dealer contracts) × 100 × S² × 0.01 × dealer_sign`

This simultaneously explains **both** the sign flips and the wild magnitude
differences — when today's flow dwarfs stale OI, both change.

**Crypto analog:** Glassnode's "Taker-Flow-Based Gamma Exposure." Similar
methodology for crypto derivatives, publicly documented.

## The Specific Math on AAOI 4/24 $210

Grok solved for the implied input:

```
Our formula:   GEX = γ × N × 100 × S² × 0.01
Given Skylit's $2,656,700 and our known γ=0.00525, S=153.74:

Effective net dealer contracts ≈ 2,656,700 / (0.00525 × 153.74²) = 21,410
```

**Our Tradier sees 25 OI / 5,567 volume. Skylit's model inferred ~21,410 net
dealer contracts** at that strike — roughly 856x our OI figure. Grok's read:
"5,567 volume contracts were net customer buys of calls → dealers sold ~21k
net (after closes, spreads, etc.)."

**This confirms our formula is correct. The disagreement is entirely on the
INPUT (effective dealer contracts), not the formula structure.**

## Peer Comparison (Who Uses What)

| Provider | Methodology |
|---|---|
| **Skylit** | Proprietary flow-inferred dealer inventory (this analysis) |
| **SpotGamma** | Standard OI × gamma (same structure as ours) |
| **Unusual Whales** | Dual: OI-based (purple) + volume-based (yellow) — still linear |
| **MenthorQ** | Mostly standard OI + simple flow overlays |
| **Glassnode (crypto)** | Taker-flow-based GEX — publicly documented |

Grok's note: *"No public methodology matches your observed outputs except
Skylit's own black-box description."*

## Why AAOI 4/17 $155 Flipped Sign

Our +$1.27M assumes full call OI=1,677 is dealer-short-gamma.
Skylit shows -$319,900.

Grok's explanation:
> Their model inferred only a fraction of the OI is "live" dealer short gamma,
> and the net flow direction was opposite (e.g., customers net selling calls
> or buying puts at that strike today). Effective net dealer contracts ≈ 1/4
> of your OI and flipped sign. This is exactly what net-notional inference
> does — it ignores stale gross OI and only cares about the dealer's actual
> current book.

## What Data You Need to Match Them

**Critical (can't reproduce without):**
- OPRA tick-level data with trade initiator (aggressive buyer/seller)
- Real-time intraday OI changes (not yesterday's settlement)
- Dealer-inventory reconstruction engine

**Helpful but insufficient:**
- Bid-ask sizes / quote updates
- Your current live Greeks + cumulative volume (already have)

**Realistic paths for GammaPulse:**

1. **Retail-tier**: blend OI + today's volume (α≈0.7 median fit was 1x)
   + simple sweep direction from unusual-whales-style data. Directionally
   useful but never matches Skylit cell-by-cell.
2. **Serious upgrade**: Full OPRA feed + build taker-flow GEX (mirror
   customer flow). Still not Skylit's proprietary version, but far better
   than pure OI.

## Is Skylit "Wrong" or Overstating?

Grok's take: **Not wrong — deliberately different.**

> They are selling a forward-looking dealer-position model, not a rear-view
> mirror of yesterday's OI. The dramatic magnitudes and King Nodes are
> intentional: they highlight where the actual hedging pressure is today
> based on live flow. Marketing amplification? Yes, but the methodology is
> internally consistent with their "microstructure" claim. Your retail data
> simply cannot see what they see.

## Bottom-Line Recommendation

1. **Document clearly:** "Our GEX uses standard OCC OI + Tradier greeks
   (simple-dealer sign). Skylit uses proprietary flow-inferred net dealer
   positioning from OPRA tick data — magnitudes and signs will differ,
   sometimes dramatically on high-flow strikes."
2. **Add a toggle:** "Flow-Adjusted GEX (OI + 0.7×vol)" as middle ground.
3. **To compete on accuracy:** budget for better data (OPRA feed).

> This is the structural reason none of the standard heuristics worked.
> Skylit isn't using a fancier linear formula — they rebuilt the entire
> dealer book from flow.
