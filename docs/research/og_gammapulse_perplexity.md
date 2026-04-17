# Perplexity Feedback — OG GammaPulse Reverse-Engineering

**Received:** 2026-04-17
**Source:** Perplexity

## TL;DR

Perplexity's sharpest insight: **"The fact that above-spot and below-spot
behave differently is the key constraint. Any hypothesis that applies
uniformly (different gamma source, different expiration weighting) is
immediately ruled out by the above-spot parity. The formula divergence
is spot-relative, not global."**

This eliminates H2 and H5 immediately and focuses the investigation on
moneyness-aware methodology differences.

## Hypothesis Rankings (Perplexity)

| # | Hypothesis | Rating | Applies To |
|---|---|---|---|
| H3 | OTM Put Sign Flip Below Spot (abs summation vs netting) | ★★★★★ | Below-spot undershoot |
| H7 | ITM Call Put-Call Parity Doubling | ★★★★☆ | Below-spot, especially $67 |
| H1 | Dealer-Customer-Inverse Sign at OTM Calls | ★★★★☆ | $75 CEIL sign flip only |
| H6 | SpotGamma-style Dealer Delta Inference | ★★★☆☆ | Overarching framework |
| H4 | Vanna/Charm Bundling | ★★☆☆☆ | Deprioritized (VEX shown separately) |
| H2 | Different gamma source | ★☆☆☆☆ | Ruled out by above-spot parity |
| H5 | Expiration weighting | ★☆☆☆☆ | Ruled out by above-spot parity |

## Key Analysis — The 3 Anomalies

### Anomaly 1 — Below-spot undershoot ($60–$67)

**At $60:** call_OI (13,670) ≈ put_OI (13,175). If OG sums |call_GEX| +
|put_GEX| instead of netting, this would double → matches observed 0.57x.

**At $65:** Put OI is substantial (9,022). Flipping put sign to positive
would take netting → summing, explaining ~1.64x OG/ours.

**At $67:** Put OI minimal (207). Summing/flipping doesn't explain 2.14x
alone — this needs H7 (ITM call parity doubling) to account for the gap.

### Anomaly 2 — Above-spot parity ($80-$100)

Raw formula matches within 0.90-1.36x. Our activity-weighting pushes
1.1-1.75x (explains most of what we see in live UI). **OG uses raw OCC
OI for above-spot strikes — identical methodology to our raw formula.**

### Anomaly 3 — CEIL sign flip ($75 only)

Critical test: **$80-$100 is POSITIVE in OG's data**, only $75 is
negative. So it's NOT a blanket "above spot = negative" rule.

> This strongly points to a CEIL-specific sign rule — OG marks the
> ceiling as a dealer gamma-flip point and forces the sign negative
> there.

This is a **structural level marker**, not a formula-level rule.

## Perplexity's Proposed Unified Hypothesis: H8

Combined asymmetric dealer model:

```
(a) ITM calls (below spot): treated as equivalent to short puts from
    dealer's perspective — gamma contribution effectively doubled
(b) CEIL strike: forced negative as structural level marker
(c) Above-spot OTM calls (non-CEIL): normal positive
```

This explains all 4 patterns simultaneously:
- Below-spot ~2x inflation ← ITM call treatment (a)
- $67 near-doubling ← mostly call-driven ITM strike (a)
- $75 sign flip ← CEIL structural rule (b)
- Above-spot parity ← no change for OTM calls (c)

## At $67 — What Formula Gets Us To $2.0M?

Our single-exp: 3724 × 0.0496 × 100 × 68.85² × 0.01 ≈ $875K

Three candidate mechanisms to double:

1. **ITM call doubling via put-call parity:** add gamma × call_OI
   contribution a second time → +$875K → **$1.75M** (still ~12% short)

2. **Synthetic put OI from call delta:** put_OI_synthetic = call_OI × delta
   ≈ 3724 × 0.65 = 2420. Add: 2420 × 0.0496 × ... ≈ $569K →
   **$1.44M** (below target)

3. **Total OI (calls + puts):** (4526 + 207) × gamma × ... ≈ $1.11M
   (too low because put OI is tiny)

**Cleanest path: Option 1 (H7 doubling) + minor gamma contributions
from other expirations our data truncated.**

## At $75 CEIL — What Rule Produces the Sign Flip?

Two candidates:
1. Apply negative sign to all GEX at the designated CEIL level
   (post-calculation level-type rule)
2. Different sign convention for OTM calls above spot (dealer modeled short)

**Test:** $80-$100 all POSITIVE in OG. **Eliminates (2).** It's a
CEIL-specific sign rule.

## Is OG GammaPulse Publicly Documented?

> "GammaPulse" matches the style of several commercial options dashboards
> (SpotGamma HIRO, SqueezeMetrics GEX, or boutique dashboards). No
> publicly known dashboard is formally called "OG GammaPulse" in open
> literature. The methodology is almost certainly not publicly documented
> — these dashboards guard their exact formulas as competitive IP.

Suggested search paths: YouTube (vendor demos), platform's own
"methodology" or "FAQ" page.

## Additional Data Needed To Confirm H8

1. **OG's value at a pure-put below-spot strike** (high put OI, near-zero
   call OI) — if OG is high there too, it's not about calls at all; if
   OG is low, it confirms the ITM call treatment is the mechanism.

2. **OG's value at a non-CEIL above-spot strike with dominant put OI** —
   tests whether sign convention is purely call/put-based or level-based.

3. **OG's GEX for a single expiration (not MACRO ALL 200D)** — isolates
   one expiry, removes multi-expiry aggregation variable.

4. **The OG value at $70 KING using only 4/17 expiry** — 4/17 has highest
   gammas (0.0987). If OG's $3.4M is driven heavily by 4/17, their
   per-expiry weighting may differ from our flat 200D sum.

## Verdict

Perplexity's H8 is the cleanest unified explanation. It's testable with
more data points from OG's UI. The methodology is NOT publicly documented
but is reproducible from OCC OI alone (unlike Skylit which needs OPRA
tick data).

If confirmed, H8 would let us offer an "OG-compatible mode" toggle that
matches their dashboard for cross-reference purposes. Our own
activity-weighted model remains useful for retail-honest reasons.
