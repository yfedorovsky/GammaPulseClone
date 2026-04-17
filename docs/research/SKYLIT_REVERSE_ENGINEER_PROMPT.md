# Reverse-Engineer Skylit's GEX Formula — External LLM Review

**We need your help.** We're building a retail options-flow dashboard
("GammaPulse") and compare our per-strike dealer gamma exposure (GEX)
numbers against Skylit (app.skylit.ai), a polished professional
reference. Our numbers are **consistently and wildly different** from
theirs — sometimes off by 100-800x in magnitude, frequently with
opposite signs. We want to understand what formula/assumptions Skylit
is actually using.

We've tried the standard industry heuristics and **none of them
reproduce Skylit's observed outputs** when fitted to real data. This
document contains the ground-truth observations + our raw inputs + our
candidate formulas + our statistical fit results. Please help us figure
out what they're doing.

---

## Background

**The GEX formula (standard industry definition):**

```
GEX(strike) = gamma × OI × 100 × S² × 0.01 × sign
```

- `gamma`: BSM gamma of the option (calls and puts have identical gamma)
- `OI`: open interest at that strike
- `100`: shares per contract
- `S²`: spot squared
- `0.01`: scales to "dollars per 1% move"
- `sign`: convention. Commonly:
  - **"Simple dealer"**: `+1` for calls, `-1` for puts (what we use)
  - **"Flow-inferred"**: dealer is short OTM calls and long OTM puts → signs flip above/below spot
  - **"Customer-inverse"**: whatever customers are long, dealers are short

**Our methodology:**

- Data source: Tradier REST API (retail-tier). `open_interest` is
  yesterday's OCC settlement figure (stale intraday).
- Greeks: Tradier's BSM greeks (mostly refreshed during market hours).
- Sign convention: simple dealer (+calls, −puts).
- Formula: standard GEX per above.

**Skylit's methodology (what we can infer):**

- Professional-tier interface at app.skylit.ai
- Shows per-cell dollar GEX on a strike × expiration heatmap
- Has intraday % change badges ("+11%", "-3%")
- Marks "King Node" ⭐ on the single dominant cell
- Appears to have sign flips above/below spot that don't follow our
  simple dealer convention
- Per their heatmap at 3:16 PM on 2026-04-16: AAOI spot $153.74 (+7.85%)

---

## Ground Truth — AAOI 2026-04-16 15:16 ET, spot $153.74

The user captured a Skylit screenshot of AAOI's heatmap during the
trading day. Below are cells across three expirations (4/17, 4/24, 5/1)
with Skylit's displayed values and our raw Tradier inputs for each.
**gamma is identical for call and put at the same strike (BSM).**

### Per-cell raw data + observed Skylit values

| Exp | Strike | Skylit $GEX | call_OI | put_OI | call_vol | put_vol | gamma | spot |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 4/17 | 149.0 | $122,700 | ? | ? | ? | ? | (fetch) | 153.74 |
| 4/17 | 150.0 | $1,556,600 | 4076 | – | 5427 | – | 0.0234 | 153.74 |
| 4/17 | 155.0 | -$319,900 | 1677 | – | 2147 | – | 0.0210 | 153.74 |
| 4/17 | 160.0 | $1,883,200 | 1205 | – | 5418 | – | 0.0185 | 153.74 |
| 4/17 | 162.5 | $385,700 | ? | ? | ? | ? | ? | 153.74 |
| 4/17 | 165.0 | $1,011,600 | ? | ? | ? | ? | ? | 153.74 |
| 4/17 | 167.5 | $473,900 | 42 | – | 427 | – | ~0.008 | 153.74 |
| 4/17 | 170.0 | $640,600 | ? | ? | ? | ? | ? | 153.74 |
| 4/17 | 175.0 | $245,000 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 150.0 | -$300 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 155.0 | -$106,100 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 160.0 | $115,300 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 165.0 | $71,300 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 170.0 | -$276,900 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 175.0 | -$90,500 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 180.0 | **-$557,000** | 897 | ? | 620 | ? | 0.0089 | 153.74 |
| 4/24 | 190.0 | -$159,200 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 195.0 | -$16,200 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 200.0 | **-$376,000** | 733 | 7 | 5067 | 0 | 0.00684 | 153.74 |
| 4/24 | 207.5 | $14,800 | ? | ? | ? | ? | ? | 153.74 |
| 4/24 | 210.0 | **$2,656,700** ⭐ KING | 25 | 0 | 5567 | 0 | 0.00525 | 153.74 |
| 4/24 | 212.5 | $12,400 | 3 | 0 | 5 | 6 | 0.00492 | 153.74 |
| 4/24 | 215.0 | $9,600 | 36 | 0 | 3 | 5 | 0.00459 | 153.74 |
| 4/24 | 220.0 | -$37,900 | 21 | 0 | 173 | 67 | 0.004 | 153.74 |
| 4/24 | 225.0 | $3,600 | 33 | 1 | 31 | 0 | 0.00349 | 153.74 |
| 4/24 | 230.0 | $2,000 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 150.0 | -$56,600 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 155.0 | $22,500 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 160.0 | $17,500 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 165.0 | $17,700 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 170.0 | -$67,600 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 175.0 | $202,400 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 180.0 | $18,300 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 185.0 | $16,700 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 195.0 | $49,500 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 200.0 | **-$5,394,600** ⭐ KING | 83 | ? | 5107 | ? | ~0.007 | 153.74 |
| 5/1 | 205.0 | -$122,200 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 215.0 | $30,800 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 220.0 | $16,500 | ? | ? | ? | ? | ? | 153.74 |
| 5/1 | 225.0 | -$20,300 | ? | ? | ? | ? | ? | 153.74 |

(The full table is in `docs/research/skylit_samples.json` — this has
raw values for every cell. "?" here means user hasn't typed that cell
from the screenshot yet.)

### Key outliers that NO standard formula explains

1. **AAOI 5/1 $200 call/put**: Skylit shows **-$5,394,600** (huge
   negative). Our raw data: call_OI=83, call_vol=5107, gamma≈0.007. Our
   formula gives ≈$14K. **Magnitude ratio: 385x too small.**

2. **AAOI 4/24 $210 call**: Skylit shows **+$2,656,700** (king). Raw:
   call_OI=25, call_vol=5567, gamma=0.00525. Our formula: $3,102.
   **Magnitude ratio: 858x too small.**

3. **AAOI 4/17 $155**: Skylit shows **-$319,900** (negative). Our raw:
   call_OI=1677, call_vol=2147. Our formula: +$1,268,402 (positive).
   **Sign flipped AND magnitude 4x different.**

4. **AAOI 4/17 $150**: Skylit shows **+$1,556,600**. Our raw: OI=4076,
   vol=5427, gamma=0.0234. Our formula: **+$2,599,261** — we're
   _bigger_ than Skylit here.

---

## Our Statistical Analysis — None of the Standard Formulas Work

We fit several candidate formulas against all 42 observed cells.

### Sign classifier performance (higher = better prediction of Skylit's sign)

| Classifier | Correct |
|---|---|
| S1 — calls=+, puts=− (naive) | 57.5% |
| S2 — spot-aware (calls above spot = −) | 43.9% |
| S3 — sign of (call_OI − put_OI) | 57.5% |
| S4 — flow-based (signed volume × delta) | 53.7% |
| S5 — ITM-inversion rule | 42.5% |

**None beats random-ish. Whatever Skylit uses for sign is not one of
the standard industry conventions.**

### Magnitude formula fits (MAE, median ratio, R²)

| Formula | Mean Abs Error | Median obs/pred | R² |
|---|---:|---:|---:|
| F1 raw OI × gamma × 100 × S² × 0.01 | $331,181 | 2.45x | −0.05 |
| F2 OI + 0.7 × vol | $437,763 | 1.00x | −0.30 |
| F2 OI + 1.0 × vol | $524,113 | 0.83x | −0.71 |
| F3 max(OI, vol) | $365,972 | 1.27x | 0.05 |
| F_exaggerate OI + 3 × vol | $1,124,386 | 0.38x | −7.88 |
| F4 fit α=0.16 (`OI + α × vol`) | $316,214 | 1.52x | −0.03 |

**Key observations:**

- **F2 with α=0.7 gives median ratio 1.00x** — median cell is perfect.
  But R² is −0.30 — TERRIBLE correlation. Median fit but no actual
  predictive power. That's a heavy-tailed residual distribution.
- **F4 with best-fit α=0.16** gives R² ≈ 0 — practically no
  relationship. The variance isn't explained by any linear combo of
  OI + volume.
- **F_exaggerate (3× vol)** overshoots with R² −7.88 — worse than mean.
- Every formula has huge residuals on the extreme outliers above.

**Conclusion: Skylit is not using any simple linear combination of
gamma × (OI + k × volume). Something else is happening.**

---

## Specific Hypotheses to Evaluate

We have several theories. Please rank them / add your own / suggest
experiments.

### H1: Skylit uses a completely different OI figure

Their data source (Polygon OPRA? Direct OCC feed?) may give them much
larger OI numbers than Tradier. Tradier's $210 call OI=25 might be stale
or wrong. If their real OI at $210 is ~20,000, the formula works out.

**Problem:** We don't see this plausibly explaining $167.5 ($473K
Skylit, vol=427, OI=42 — no way there's 20× OI here either).

### H2: Skylit shows something that isn't pure dealer GEX

Maybe it's a composite metric:
- **Dealer-delta impact** — the dollar delta dealers must hedge per 1% move
- **"Pin strength"** — weighted by bid-ask spread, volume concentration
- **Gamma × notional** — uses strike × OI × 100 instead of gamma math
- **Flow-accelerated GEX** — includes a flow momentum term

### H3: Skylit uses volume × delta as a "dealer exposure" proxy

Where volume represents flow today and delta gives the hedging delta.
Then amplified by some multiplier.

Example: $210 call: vol=5567, delta=0.098 → 5567 × 0.098 × 100 × S =
8.6M × $153.74 ≈ **$8.6M**, not $2.66M — so this isn't it either
unless there's a discount.

### H4: Skylit uses a "dealer-inferred" sign based on order flow

They have tick data (OPRA direct) and can classify trades as buy-
initiated vs sell-initiated. When customers are net buyers of calls at a
strike, dealers are net short → negative GEX. This would explain sign
flips that our simple model gets wrong.

### H5: Skylit uses a multi-day accumulated OI

Instead of "today's effective OI", they use "rolling 5-day OI estimate"
or "peak OI since listed". This could inflate low-listing-age strikes.

### H6: Skylit just uses volume as OI (super aggressive)

We tested this (F3 max, F2 with α=1.0) — ratios are still 0.83x (we're
too big now on most cells but too small on the killer outliers).

### H7: Units / scaling

Maybe they scale differently — not per 1% move but per 1-point move, or
they multiply by some internal "liquidity factor". A constant multiplier
doesn't fit since the ratios vary so widely across cells.

---

## Questions For You to Answer

1. **Which hypothesis is most likely?** Rank H1-H7 or propose H8+.

2. **Do you know any published methodology for Skylit, SpotGamma,
   MenthorQ, UnusualWhales, or similar dashboards** that matches these
   observed patterns?

3. **For the specific cell AAOI 4/24 $210 call** (OI=25, vol=5567,
   gamma=0.00525, spot=$153.74), Skylit shows $2,656,700. **What
   formula could plausibly produce this number?** Is there a way
   involving publicly-known retail option flow data?

4. **For AAOI 4/17 $155 cell** (OI=1677, vol=2147, gamma=0.021, spot=$153.74):
   - Our formula: +$1,268,402 (positive)
   - Skylit shows: −$319,900 (negative, smaller magnitude)
   **What could flip the sign AND reduce magnitude by 4x simultaneously?**

5. **What additional data do we need?** Would per-trade timestamps,
   bid-ask size, or anything else help figure this out? We currently
   have: OI (stale EOD), volume (intraday cumulative), gamma, delta,
   vega, IV (all live-ish).

6. **Is it possible Skylit is simply wrong/overstating?** Marketing
   amplification? They might use an intentionally aggressive model to
   look more dramatic than underlying data supports.

---

## What We've Tried

- Volume-adjusted OI: `OI + α × vol` for α ∈ {0.3, 0.5, 0.7, 1.0, 3.0}
- Sign conventions: 5 candidate classifiers (see table)
- Max-aggregation: `max(OI, vol)`
- Linear regression of best-fit α: got α=0.16 with R²≈0
- Formula scaling constants: none produce consistent per-cell ratios

**None of these close the gap across all cells.** The problem seems
structural, not a parameter tuning issue.

---

## The Goal

We're NOT trying to reproduce Skylit exactly — they may have proprietary
data or questionable methodology. We want to:

1. **Understand the general direction** of their model — OI-dominant?
   Flow-dominant? Hybrid?
2. **Improve our own model** to be more meaningful, even if less
   dramatic.
3. **Know what's achievable without OPRA tick data** vs what requires
   upgrading our data provider.

If your answer is "they have proprietary OPRA-tick-level flow analysis
that you can't reproduce without an expensive data subscription" —
that's a valid and useful answer. Just tell us so we can stop trying to
match them with retail data.

Thanks for your help.
