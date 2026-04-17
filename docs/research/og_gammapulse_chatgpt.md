# ChatGPT Feedback — OG GammaPulse Reverse-Engineering

**Received:** 2026-04-17
**Source:** ChatGPT

## TL;DR

ChatGPT converges with Perplexity on hypothesis ranking but adds a valuable
new framing: **OG may be showing "node strength" (support/resistance
display convention) rather than strict signed net GEX math.**

> "OG is not using a radically different gamma backbone. It is probably
> using the same OI-gamma skeleton you are, but with: a different
> strike-region sign/display convention, a more support/resistance-
> oriented treatment of below-spot protection nodes, and possibly a
> product-layer transformation that emphasizes node strength over
> strict signed net local GEX."

## Hypothesis Ranking (ChatGPT)

| Hypothesis | Rating | ChatGPT's Reasoning |
|---|---|---|
| H3 + H1 + H6 flavor | Most likely | Below-spot treated as "protection/support" (not netted); CEIL sign flipped by dealer-short-call convention |
| H7 | Plausible secondary | Parity-style ITM call treatment — especially for $67 |
| H8 (reframed) | "Favorite product explanation" | OG mixes signed net GEX with node-strength heuristics |
| H2, H5 | Unlikely | Wrong shape of error — doesn't match "match above spot, miss below spot, flip CEIL" pattern |

## ChatGPT's New Framing — "Node Strength" Display

Key insight: **The displayed cell value may not equal the raw math.**

> "At floor-like strikes they may be showing: *'how big is the support
> node?'* — not *'what is the pure signed local gamma sum?'*"

This reframes the entire question. The cell value isn't necessarily a
textbook gamma dollar amount — it's a **product-layer transformation**
designed to convey trading intuition:
- **Support nodes** (below spot floors): display as positive, magnitude = support strength
- **Resistance nodes** (above spot ceilings): display as negative, magnitude = resistance strength
- **King (ATM)**: display normally (both systems match)

This would explain why:
- King/Floor/Ceiling levels all match (same skeleton)
- Magnitudes are directionally similar
- But signs and below-spot values don't match strict netting

## The $67 Diagnostic

ChatGPT frames this the same way Perplexity did:

> "That makes one thing clear: OG is almost certainly not just 'call
> gamma minus put gamma' at that strike. Because with tiny put OI
> (207), there is nothing there to 'fix' the gap by sign convention
> alone."

The cleanest explanation is ABSOLUTE gamma aggregation or parity-style
support interpretation. Same conclusion as Perplexity but stated from
the semantic angle.

## The $75 CEIL Sign Flip

ChatGPT's framing: **display convention, not math convention**.

> "Same ceiling, same neighborhood of magnitude. That is exactly what
> I'd expect if OG says: ceiling/overhead call wall = negative hedging
> pressure. Floor/downside support = positive hedging pressure.
>
> That is not the same thing as raw 'dealer gamma sign.' It is closer
> to: price-impact sign, or hedging-flow sign, or simply a charting
> convention where resistance nodes are negative and support nodes are
> positive."

This is a cleaner mental model than "dealer-short-calls convention" —
OG is using a **directional hedging-flow sign** for the display, not a
dealer position sign.

## Is OG Publicly Documented?

> "I did not find a public formula page for this exact OG GammaPulse
> methodology. Public GEX references from other vendors vary a lot, and
> many products use the standard OI-gamma backbone but differ in:
> - whether they show 1% move vs 1-point move
> - whether they use OI vs volume
> - whether they display net signed exposure vs node strength /
>   support-resistance interpretation."

## Practical Recommendation — Two Modes

ChatGPT's implementation path matches Skylit synthesis conclusion:

### Mode A — textbook net GEX (current default)

```python
gex = gamma × OI × 100 × S² × 0.01
signed by call (+) / put (−)
```

### Mode B — OG-like structural node mode

```python
below_spot:   call_gex + abs(put_gex)    # or parity-style equivalent
above_spot:   standard netting            # as Mode A
ceiling_display: flip sign negative       # for overhead call-dominant nodes
floor_display: keep positive              # standard
```

## Experiments ChatGPT Suggests

> "I can turn this into a Claude-ready reverse-engineering note with
> the exact experiments I'd run next:
> - strict net
> - absolute gamma below spot
> - parity-adjusted floor mode
> - resistance-sign display mode
> - compare against OG on the OKLO sample."

(User hasn't asked for this yet — noted for potential future session if
we decide to ship OG-compat mode.)

## Convergence With Perplexity

Both LLMs independently agree on:

1. ✅ Above-spot parity rules out global gamma/expiration hypotheses
2. ✅ Below-spot undershoot is caused by differential call/put treatment
3. ✅ $67 sign flip is NOT pure netting — requires protection/parity logic
4. ✅ $75 CEIL is a level-specific sign rule, not blanket above-spot
5. ✅ OG is reproducible from OCC OI (unlike Skylit which needs OPRA)
6. ✅ Practical path: two-mode implementation

## Difference In Framing

- **Perplexity:** Mechanical — "what formula produces the observed numbers" (H8 with ITM parity + CEIL override)
- **ChatGPT:** Semantic — "what OG is trying to show the user" (node strength display layer)

These are **compatible views of the same phenomenon.** ChatGPT's framing
is easier to sell in UI copy; Perplexity's is easier to implement as code.

## Verdict

Strong 2-LLM consensus already. If Grok and Gemini agree, we have
near-definitive diagnosis. Both LLMs recommend the same implementation
path: **ship two modes (textbook + OG-compatible) instead of chasing a
single formula.**
