# Reverse-Engineering OG GammaPulse's GEX Formula — External LLM Review

**Context:** Our GammaPulse clone is being compared side-by-side against the
original commercial "GammaPulse" dashboard (hereafter "OG") using OKLO options
data captured 2026-04-17 mid-session. Unlike Skylit (which uses proprietary
OPRA tick classification per our prior synthesis), OG appears to use a
simpler OCC-OI-based formula — but its numbers systematically deviate from
ours at specific strike regions in ways we can't explain with standard
industry methodology.

This doc captures the comparison data and asks external LLMs to help
identify the methodology differences.

---

## Both Systems Agree On Structure

Same spot, same King/Floor/Ceiling levels, same signal:

| Metric | Ours | OG | Match? |
|---|---|---|---|
| Spot | $68.85 | $68.63 (intraday delta) | ✓ |
| King | $70 | $70 | ✓ |
| Floor | $67 | $67 | ✓ |
| Ceiling | $75 | $75 | ✓ |
| Signal | MAGNET UP, POS γ | MAGNET UP, POS γ | ✓ |
| Position note | "2% below king" | "2.0% below king $70 · magnet pull" | ✓ |

**The structural gravity map is identical.** Disagreement is purely on
per-cell dollar magnitudes and the CEIL sign.

---

## Systematic Magnitude Comparison

All values are MACRO (ALL 200D) aggregated across every expiration within
200 days. Spot $68.85.

**Both systems use public OCC Open Interest (stale EOD settlement).** Our
system also offers an optional "activity-weighted" variant using today's
volume; shown side by side below.

| Strike | Ours (raw OI) | Ours (activity-weighted) | OG | Raw/OG | Act/OG | Note |
|---|---:|---:|---:|---:|---:|---|
| $100 | $278K | $334K | $204K | 1.36x | 1.64x | OTM call |
| $95 | $114K | $141K | $124K | **0.92x** | 1.14x | OTM call |
| $90 | $230K | $262K | $219K | **1.05x** | 1.20x | OTM call |
| $85 | $194K | $233K | $216K | **0.90x** | 1.08x | OTM call |
| $80 | $892K | $1,461K | $832K | **1.07x** | 1.75x | Gatekeeper |
| **$75** | **+$1,312K** | **+$3,792K** | **−$896K** | **−1.46x** | **−4.23x** | **CEIL — sign flip** |
| $70 | $2,963K | $6,104K | $3,400K | **0.87x** | 1.80x | KING |
| $67 | $933K | $1,340K | $2,000K | **0.47x** | 0.67x | FLOOR — we're HALF |
| $65 | $1,217K | $1,322K | $2,000K | **0.61x** | 0.66x | Below spot — we're LOW |
| $60 | $137K | $151K | $239K | **0.57x** | 0.63x | Below spot — we're LOW |

### Key Observations

**Above-spot strikes ($80-$100):** Our RAW formula matches OG within
0.90-1.36x — essentially the same methodology. Our activity-weighted
variant inflates 1.1-1.75x.

**Below-spot strikes ($60-$67):** Our raw formula is consistently **0.47-0.61x**
OG's values. OG is **~2x higher** in this zone. Our activity weighting
doesn't help — still ~0.65x.

**CEIL strike ($75):** Both systems have ~$900K-1.3M magnitude, but **sign
is flipped**. Our system: +$1,312K. OG: −$896K.

---

## Our Formula (Baseline)

Per-contract:
```
GEX_c = gamma × OI × 100 × S² × 0.01 × sign
sign = +1 if call, −1 if put  ("assumed_dealer" convention)
```

Aggregated to per-strike by summing across all contracts at that strike
across all expirations within 200 DTE.

Python reference: `server/gex.py::compute_exp_data`.

**Known simplification:** The sign convention is naive — calls always
positive, puts always negative. We know from the Skylit reverse-engineering
exercise that professional dashboards use flow-inferred signs via Lee-Ready
classification of OPRA tick data. We don't have that.

---

## Raw Per-Expiration OI Distribution At Key Strikes

To help diagnose what could be driving the divergences:

| Strike | call_OI_sum | put_OI_sum | call_vol | put_vol | Top gamma contributors |
|---|---:|---:|---:|---:|---|
| $100 | 11,974 | 3,160 | 3,836 | 31 | 5/15 call OI 1860 γ 0.0119 / 6/18 call OI 1960 γ 0.0113 / 6/18 put OI 1358 γ 0.0113 |
| $95 | 4,737 | 1,112 | 1,308 | 19 | 6/18 call OI 828 γ 0.0120 / 7/17 call OI 712 γ 0.0109 |
| $90 | 10,615 | 3,764 | 1,739 | 12 | 5/15 call OI 2069 γ 0.0150 / 6/18 call OI 1865 γ 0.0126 |
| $85 | 8,052 | 2,198 | 1,801 | 192 | 7/17 call OI 1590 γ 0.0115 / 5/15 call OI 1101 γ 0.0165 |
| $80 | 15,524 | 4,688 | 16,466 | 134 | 5/15 call OI 5122 γ 0.0177 / 6/18 call OI 4514 γ 0.0132 / 4/17 call OI 2329 γ 0.0125 |
| $75 | 14,354 | 4,788 | 23,296 | 1,064 | 4/17 call OI 2398 γ **0.0729** / 6/18 call OI 4167 γ 0.0131 / 5/15 call OI 1536 γ 0.0184 |
| $70 | 21,781 | 9,380 | 25,084 | 3,483 | 4/17 call OI 7253 γ **0.0987** / 4/17 put OI 2544 γ **0.0987** / 5/15 call OI 4279 γ 0.0182 |
| $67 | 4,526 | 207 | 5,607 | 2,958 | 4/17 call OI 3724 γ **0.0496** |
| $65 | 20,319 | 9,022 | 4,725 | 2,267 | 4/17 call OI 5276 γ 0.0268 / 4/24 call OI 2924 γ 0.0277 |
| $60 | 13,670 | 13,175 | 2,042 | 2,009 | 5/15 call OI 2442 γ 0.0140 / 4/24 call OI 1489 γ 0.0174 / 6/18 put OI 2348 γ 0.0107 |

**Observations:**

1. At $67 (strong OG floor @ $2M), put OI is minimal (207). This strike's
   GEX is almost entirely from calls — yet OG's value is 2.14x our raw
   calc.
2. At $65, put OI is substantial (9,022). Ratio is 1.64x — less extreme
   than $67 but still ours is 0.61x OG.
3. At $60, call_OI and put_OI are nearly equal (13670 vs 13175). Ratio is
   0.57x. If OG summed |call_gex| + |put_gex| rather than netting, this
   would double at $60 approximately — but NOT at $67 where put OI is
   tiny.
4. The **$75 CEIL sign flip** occurs at a strike where call OI (14354) is
   3x put OI (4788). Our raw formula yields +$1,312K. OG shows −$896K.

---

## Candidate Hypotheses

### H1: OG uses a "dealer customer-inverse" sign at OTM call strikes

Above spot, OG treats dealer as net short calls (customer long) → negative
GEX. This would explain the $75 CEIL sign flip but wouldn't affect
magnitude of same-sign strikes. **Partially explains.**

### H2: OG uses an alternative gamma source

Does OG use IV-smile interpolated gamma rather than per-contract gamma?
Our Tradier gamma at $95 is 0.0120 (6/18 exp). If OG uses smoothed IV
surface, their gamma could differ at far OTM. **Doesn't match** the
observation — we match OG at $95 (0.92x), but diverge at $60-$67.

### H3: OG treats puts at below-spot strikes with different sign

At $65, $67, $60 — all below spot — puts are OTM (normal behavior).
If OG treats OTM puts as dealer-long-customer-short (positive GEX from
puts) rather than negative, the put contribution flips sign and adds
to calls. At $65: call GEX + |put GEX| ≈ 1.6x raw formula — matches
observed ratio. **Plausible explanation for below-spot 2x discrepancy.**

### H4: OG adds non-gamma components (Vanna, Charm) at specific strikes

Some dashboards bundle multi-Greek exposure into their "GEX" display.
At $67/$65, does OG add a vanna/charm contribution that we miss?
**Possible but hard to verify without OG documentation.**

### H5: OG uses different expiration weighting

Does OG weight near-term expirations more than we do? Our calc sums flat
across all DTE within 200D. **Doesn't explain** the below-spot / at-spot
/ above-spot pattern — all use the same expiration set.

### H6: OG uses SpotGamma-style Dealer Delta

SpotGamma's GEX formula uses dealer-delta-hedged exposure. If OG has
similar dealer inference at below-spot strikes (treating puts as dealer
protection), that could inflate below-spot magnitudes. **Plausible.**

### H7: OG double-counts calls AND puts at in-the-money calls

At $65/$67 below spot, calls are ITM. ITM call OI represents a different
dealer position than OTM call OI. If OG treats ITM call OI as equivalent
to OTM put OI (put-call parity), it'd add the put equivalent to the call
gamma. **Maybe** — this would roughly double the magnitude at ITM strikes
which matches observation.

---

## Questions For You

1. **Which hypothesis is most likely?** Rank H1-H7 or propose H8+.

2. **Is OG GammaPulse's methodology publicly documented?** Any blog posts,
   whitepapers, or videos describing their formula?

3. **For the specific $67 strike discrepancy** (OG $2.0M, ours $933K with
   raw OI):
   - Dominant contribution is from 4/17 call OI 3724 × gamma 0.0496
   - Single-exp contribution: 3724 × 0.0496 × 100 × 68.85² × 0.01 ≈ $875K
   - That alone is 0.44x OG's $2.0M
   - What formula would DOUBLE this to match OG?

4. **For the $75 CEIL sign flip** (OG −$896K, ours +$1,312K same magnitude):
   - Both systems agree this is a ceiling (marked CEIL in both UIs)
   - OG shows negative, we show positive
   - What sign rule produces this flip at a strike with call_OI 3x put_OI?

5. **Does "OG GammaPulse" specifically refer to a known commercial dashboard?**
   The screenshot shows:
   - Title: "GammaPulse"
   - Shows per-cell dollar GEX + VEX
   - Marks King (yellow), Floor (teal), Ceil (orange)
   - Shows "1% $7.5M" total exposure metric
   - Shows Δ (delta) 7.4M, V (vanna) 266.0K

6. **What additional data do we need** to nail this down?

---

## The Goal

Unlike the Skylit investigation (which required OPRA data we don't have),
OG's formula appears reproducible from OCC OI alone — we just don't know
exactly HOW they aggregate it. Understanding their methodology would let us:

1. Offer a "OG-compatible" mode as a toggle for users who cross-reference
2. Fix our below-spot systematic undershoot
3. Validate the sign convention at CEIL strikes

This is a different problem from Skylit — smaller data requirements, but
still requires knowing the exact formula.

---

## Reproducible Data

Raw per-contract data was pulled from Tradier REST API on 2026-04-17 at
approximately 10:00 AM ET. Activity-weighted OI uses formula:
`OI_eff = OI × (1 + 0.4 × min(vol/OI, 7))`. Standard BSM gamma from Tradier's
greeks endpoint, `S² × 0.01` scaling for per-1% move.

Everyone seeing this prompt: our formula is in
`server/gex.py::compute_exp_data`. Our data source is Tradier. Our IV is
Tradier's mid_iv (live-ish during market hours).

Your feedback goes to `docs/research/og_gammapulse_[yourname].md`.
