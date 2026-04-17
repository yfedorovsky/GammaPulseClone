# 4-LLM Synthesis — Skylit GEX Reverse-Engineering

**Date:** 2026-04-16
**Inputs:** ChatGPT, Grok, Perplexity, Gemini feedback in `docs/research/`

This document synthesizes the four external reviews into a single actionable
conclusion + decision framework. **Skip to "THE VERDICT" if you want the
bottom line.**

---

## Unanimous Consensus (4/4 agree)

Every LLM independently converged on the same core diagnosis:

1. **Our GEX formula is correct.** The standard industry equation
   `GEX = γ × OI × 100 × S² × 0.01` is mathematically right. Not a
   formula bug.

2. **The discrepancy is INPUT-driven, not math-driven.** Skylit uses a
   fundamentally different concept of "open interest" — their displayed
   value is built from **inferred net dealer inventory from tick-level
   flow classification**, not from OCC settlement OI.

3. **Retail-tier data (Tradier) cannot reproduce Skylit cell-by-cell.**
   Closing the full gap requires OPRA tick-level data + a trade
   classification engine + continuous historical inventory state.

4. **Skylit's sign convention is flow-inferred, not structural.** No
   static rule (simple dealer, spot-aware, OI-dominated, etc.) predicts
   their signs — they classify each OPRA print buy-initiated vs
   sell-initiated and reconstruct the dealer's book dynamically.

## 3-of-4 Consensus

5. **The gap is ~80-90% driven by OI-concept-replacement, not formula
   tuning** (ChatGPT + Grok + Perplexity; Gemini frames it even more
   strongly as H1-FALSE because it's not "different OI" but "no OI
   concept at all").

6. **The algorithmic architecture is Lee-Ready-style tick classification
   + continuous inventory state** (Grok + Perplexity + Gemini explicitly;
   ChatGPT implicitly).

7. **Multi-Greek integration (Vanna + Charm) contributes to magnitude
   inflation at OTM strikes with steep skew** (ChatGPT H2, Perplexity
   H2, Gemini confirmed; Grok mentions it as secondary).

## 2-of-4 Consensus

8. **DTE-scaling pattern proves internal consistency** (Perplexity
   discovered via quantitative analysis of King Node multipliers; Gemini
   confirms methodology supports this). This argues AGAINST the "pure
   marketing amplification" theory.

9. **Polygon.io Options Snapshot ($29-$200/mo) is a real middle-ground
   upgrade** (Perplexity explicitly, Gemini implicitly supports).

## Divergence Matrix

| Point | ChatGPT | Grok | Perplexity | Gemini |
|---|---|---|---|---|
| Is Skylit partially dramatized? | **Yes** | No | Partially | **No** |
| Can retail match Skylit's absolute numbers? | No | No | No (but can rank correctly) | No |
| Primary recommendation | Model A + Model B | Doc + toggle | 4 concrete improvements | Phase 1 + Phase 2 upgrade |
| Rank H1 (different OI source) | High | Unlikely | ★★★★★ primary | **False** (wrong framing) |
| Confidence in diagnosis | Implicit | 90% | Citations-backed | Formal theoretical |
| Weight on multi-Greek integration | Low | Minor | Secondary | **Primary contributor** |

**Key divergences:**
- **ChatGPT vs others on "dramatization":** ChatGPT leaves room for "Skylit exaggerates for marketing"; Grok and Gemini reject this firmly; Perplexity partial.
- **Gemini's H1-FALSE framing:** Gemini argues the others are too generous to "better OI" as an explanation — the concept of OI itself is replaced, not refreshed.
- **Weight on Vanna/Charm:** Gemini puts this as a primary contributor to magnitude distortion; others treat as secondary.

---

## THE VERDICT

### What Skylit Is Actually Doing (High Confidence)

```
1. Ingest OPRA tick stream in real time
2. Apply Lee-Ready (or modern variant) algorithm to each trade:
   - Quote Rule: execution vs NBBO midpoint → buyer/seller initiated
   - Tick Test fallback at midpoint
3. Maintain a rolling Net Dealer Inventory per (strike, expiration):
   N_netdealer[strike] = Σ(classified_signed_volume) over rolling window
   with decay based on expiration/exercise probabilities
4. Integrate multi-Greek composite:
   "GEX" displayed = γ × N_netdealer × S² × 0.01
                   + Vanna_contribution × N_netdealer
                   + Charm_contribution × N_netdealer
5. Output dollar-denominated "dealer hedging obligation" per strike
6. Mark absolute-max cell across matrix as King Node (sign-agnostic)
```

This is not formula magic. It's a **data infrastructure difference**.

### What We Cannot Replicate Without OPRA Data

- Real-time trade initiator classification (buy/sell aggressor)
- Buy-to-open vs buy-to-close attribution
- Continuous multi-day dealer inventory reconstruction
- Sub-second OI refresh

### What We CAN Do With Current Tradier Data

(Concrete improvements proposed by Perplexity + Gemini, compatible with
ChatGPT's Model A + Model B architecture)

**Priority 1 — Activity-Weighted OI (easy, ~2hr)**
```
OI_eff = OI × (1 + α × min(vol/OI, C))
with α = 0.3-0.5, cap C = 5-10
```
Better than our current α=0.7 blanket — adds a cap to prevent expiry-
day close-out inflation. Fixes the "ATM discount anomaly" Perplexity
identified.

**Priority 2 — Absolute-Magnitude King Node (trivial, <30 min)**
Our current King picks the largest |GEX| per expiration. Matrix King
already does this across expirations (shipped tonight). **This is
already correct — no change needed.** Verified against all 4 reviews.

**Priority 3 — OI Delta as Flow Proxy (medium, ~4hr)**
Start persisting daily OCC OI snapshots. Compare today vs yesterday:
- Rising OI + large volume → net opening → use sign of price-volume
  correlation for dealer direction
- Falling OI → net closing → reduce effective exposure
Requires a new table and 1-day burn-in. Directional improvement for
sign accuracy even without tick data.

**Priority 4 — Vanna/Charm Composite (optional, ~3hr)**
Add a soft multiplier to GEX at strikes with steep IV skew:
```
GEX_composite = GEX × (1 + vanna_factor × skew_steepness)
```
This is a heuristic proxy for the multi-Greek integration Skylit does
natively. Would produce larger magnitudes at deep OTM without needing
new data.

**Priority 5 — Model A + Model B architecture (medium, ~5hr)**
Per ChatGPT: ship TWO metrics side-by-side:
- **Base GEX** (our current, conservative, OCC-based)
- **Flow Pressure** (activity-weighted + composite, acknowledged as
  retail approximation of institutional exposure)

Label both clearly. Don't pretend they're the same object.

### What We Should Document Prominently

```
"GammaPulse GEX uses standard OCC settlement open interest and
 BSM greeks from Tradier. Professional dashboards (SpotGamma,
 Skylit Heatseeker) use OPRA tick-level data with trade
 classification + continuous dealer inventory state to produce
 flow-inferred exposure metrics. Magnitudes and signs may differ
 significantly, especially on high-intraday-flow strikes. Our
 methodology is reproducible and auditable; theirs is proprietary."
```

### Upgrade Path (When Ready)

- **$29-$200/mo**: Polygon.io Options Snapshot — fresher intraday OI,
  no tick classification. Closes ~30-50% of the gap.
- **$1,500-$5,000/mo**: Polygon OPRA Full Feed / Databento / direct
  OPRA subscription. Closes ~80-90% of the gap if paired with a
  Lee-Ready classification engine and inventory state database.
- **Build cost**: ~2-4 weeks to implement Lee-Ready + inventory state
  + backfill on top of OPRA data.

---

## Action Plan Recommendation

**Tonight:** Commit this synthesis doc. Do not ship code changes.

**Next session (when you're fresh):**
1. Ship Priority 2 — already done, just verify
2. Ship Priority 1 — tighten the volume-adjusted OI with a cap
3. Add methodology disclaimer tooltip on Heatmap header
4. Pin Priority 3-5 for deliberate scoping

**Medium-term:** Decide on data upgrade. My read of the 4 reviews:
- If you want to compete on accuracy → Polygon OPRA + build Lee-Ready
- If you want to be retail-honest → ship Priority 1-3, accept the gap
- **Don't go halfway**: Polygon Options Snapshot alone won't bridge
  the conceptual gap (no sign inference without tick data)

**Long-term research question:** Is there an "alpha gap" between our
conservative model and Skylit's aggressive model? i.e., does Skylit's
more dramatic King Node actually predict reversals better than our
quieter numbers? That's a 3-month backtest comparing trade outcomes
against both dashboards' signals. Worth doing only if/when you have
both data sets.

---

## Confidence Assessment

| Question | Confidence |
|---|---|
| Our formula is structurally correct | **95%** (4/4 agree) |
| Skylit uses OPRA tick classification | **90%** (Grok docs + Gemini theory + Perplexity evidence) |
| Skylit integrates Vanna/Charm in "GEX" | **80%** (Gemini confirms via Skylit docs) |
| Skylit uses continuous multi-day inventory state | **85%** (Perplexity DTE-scaling proof + Gemini architecture) |
| Can we match Skylit with Tradier | **5%** (unanimous no) |
| Polygon Options Snapshot would close the gap | **30%** (closes staleness but not sign inference) |
| Full OPRA + Lee-Ready would close most of the gap | **80%** |

---

## Closing

All four LLMs, working independently with access to different training
data and different reasoning strengths, converged on the same structural
diagnosis. That's strong signal. The residual disagreements are matters
of emphasis, not contradiction.

**This is the cleanest multi-LLM consensus we've gotten across any
research project in this codebase.** Trust the conclusion.

Next action: your call on data upgrade and Model A + Model B scoping.
The technical path is clear; the business question is budget.
