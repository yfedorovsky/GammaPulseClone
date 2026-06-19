# JHEQX Collar (JPM) Pin/Support Backtest — Red-Team Findings & Verdict

**Date:** 2026-06-18 · **Synthesizer:** Opus (red-team lane) · **Pre-reg:** `docs/research/JPM_COLLAR_PREREG.md`
**Engine:** `scripts/gex_bt/collar_backtest.py` (deterministic, look-ahead-audited clean)

## VERDICT: `display_only`

The short-call "cap" pin is a **context label with ZERO algo weight**. It clears the pre-reg's
narrow effect-size floor in isolation but **fails the pre-reg's own mandatory Holm-Bonferroni
multiple-testing gate**, fails to separate from a fair distance-matched null, and the mechanism
lens shows the signal is **proximity/low-drift, not collar identity**. This is the expected
default, consistent with every prior structure test: **structure DETECTS, it does not PREDICT.**

---

## Headline numbers

| Metric | Value |
|---|---|
| Analyzable events (H1) | **45** (49 quarter-ends, 4 dropped `no_oi`) |
| Cap pin rate (settle within 0.5% of short-call) | **8/45 = 17.8%** |
| Original placebo (nearest round-100 ≠ leg) | **2/45 = 4.4%** |
| H2 long-put support held | 6/45 = 13.3% |
| Fisher OR (pin vs placebo) | 4.65 |
| Pin-rate Wilson 95% CI | **[9.3%, 31.3%]** |
| Pin-rate Clopper-Pearson 95% CI | **[8.0%, 32.1%]** |

All figures reproduced independently from the per-event records (scipy 1.17.1).

## Multiple-testing-corrected significance (the decisive math)

- Fisher exact 2×2 `[[8,37],[2,43]]`: **two-sided p = 0.0897** (NOT significant before any correction).
- One-sided (pre-specified pin>placebo): p = 0.04483; two-prop z one-sided p = 0.02209.
- H2 support (6/45 vs 2/45), Fisher one-sided: p = 0.13315.
- **Holm-Bonferroni, m=2:** sorted [H1_pin 0.04483, H2 0.13315]. Rank-1 threshold = α/2 = **0.025**.
  H1_pin 0.04483 **> 0.025 → FAIL.** H2 → FAIL.
- The pre-reg §5 family is actually **≥9 tests** ({H1,H2,H3}×{5,10,20-day}); the realized run used a
  single 10-day window (`RUNIN_DAYS=10`). Even the most generous 2-test family already kills H1.
- Both CIs **comfortably contain the placebo rate 4.4%** → pin is not statistically distinguishable
  from baseline at 95%.

## Lens-by-lens

| Lens | Verdict | Bottom line |
|---|---|---|
| `lookahead_audit` | **supports_effect** | Engine is **clean**. Legs from T-1 settled SPXW OI only; settle never enters leg selection (ordering proven: legs at lines 162-165 *before* path/settle at 167-168). Cap & placebo share the same as-of spot. Certifies *backtest* is leak-free (not the live detector path). |
| `effect_size_prereg` | **supports_effect** | STRICTLY per §5 floor: n=45≥20, pin 17.8% ≥ baseline+2SE (10.59%), pin>placebo. All three AND-conditions met. **BUT explicitly scoped narrowly** — did not evaluate the §5 Holm gate, which it flags could flip the decision. |
| `placebo_adequacy` | **inconclusive** | Original placebo is a **weak null** (placed ABOVE cap, near-unreachable → 4.4% by construction). Cap beats FAIR deterministic nulls (below-cap round-100 4.4%, 2nd-OI-leg 2.2%) but does **NOT** beat an ATM/low-drift null (44.4% exact / 28.9% snapped). Only 4/8 pins are "cap-only" (price had to travel up to meet cap); too few to claim a cap-specific magnet. |
| `multiple_testing` | **inconclusive** | Borderline-to-insignificant. Significant only under most-favorable one-sided framing; two-sided p=0.0897; **fails Holm rank-1 (0.025)**; CIs include placebo. Notes paired structure → McNemar is the correct primary test and would not be more favorable. |
| `mechanism_skeptic` | **refutes_effect** | **The strongest refuting lens.** The +13.3pp gap is a **distance confound**: placebo sits farther from spot (5.06% vs 3.41%). Pin rate is monotonic in cap distance (44%/60%/10%/0% across 0-0.5/0.5-1/1-2/>2% buckets), **not** in collar identity. **Distance-matched (pool both strikes, bucket by distance): cap 44%/10% vs placebo 50%/20% — INDISTINGUISHABLE.** The closer strike pins 6/45 vs farther 4/45 regardless of which is the cap. Signature of generic nearest-salient-strike settling, not a collar magnet. |

### Strongest refuting quote (verbatim, mechanism_skeptic)

> "When you do the clean apples-to-apples test — pool both strikes and bucket by distance — the
> cap and the placebo pin at statistically indistinguishable rates within each distance bucket
> (44% vs 50% closest; 10% vs 20% mid). That is the signature of generic nearest-salient-strike
> settling, not a collar-specific magnet... every single pin required the cap to already be within
> 1.53% of spot."

## Why `display_only` and not `context_gated`

`context_gated` requires the pin to survive **fair placebo + multiple-testing + the mechanism lens**.
It survives none of the three cleanly:
1. **Fair placebo:** beats weak/below-cap nulls but loses to the ATM/low-drift null; placebo_adequacy = inconclusive, not pass.
2. **Multiple-testing:** fails Holm at rank-1 (0.025) on even a 2-test family; CIs include placebo.
3. **Mechanism:** distance-matched, the collar adds **nothing** beyond proximity — the lens explicitly *refutes*.

Two lenses say "supports," but both are **narrow procedural certifications** (the engine has no
leak; the isolated floor arithmetic passes) — neither asserts the *effect is real*, and
`effect_size_prereg` self-flags that the Holm gate it skipped "could change the overall ship/no-ship
decision." The pre-reg §5 rule is explicit: *"any hypothesis that fails ⇒ that level is DISPLAY-ONLY."*
H1 fails its corrected bar. Per our settled rule — **known ≈ priced-in → CONTEXT, not trigger** — the
collar overlay ships as awareness; the pin/support *effect* earns zero algo weight.

## EXACTLY what would change this verdict

To upgrade `display_only` → `context_gated` (flag only, still never a trigger), ALL must hold:

1. **Beat a distance-matched null, not just a round-number null.** Re-run with a placebo sampled at
   the *same* distance-from-spot as the cap on the opposite side (or multiple equidistant non-collar
   strikes). Required: cap pin rate exceeds the distance-matched placebo **within distance buckets**,
   not just in aggregate. Current data: 44% vs 50% and 10% vs 20% → fails.
2. **Condition on materially-OTM caps (>1.5% above as-of spot)** so "settle≈cap" cannot be explained
   by "price never moved." Need the cap-only subset (price had to travel up to meet the cap) to pin
   above its own distance-matched baseline. Today only **4 such events exist** — far too few.
3. **Clear Holm-Bonferroni across the full §5 family** (≥9 tests = {H1,H2,H3}×{5,10,20-day}). With
   n=45 and an 8/2 split this is not reachable; needs materially more events OR a much larger effect.
4. **Use the paired McNemar test** (pin & placebo share the same 45 events) as the primary statistic,
   and survive it post-correction.

**Sample that would settle it:** SPXW OI history bounds the set to ~46 quarters (since 2014-09).
Quarterly cadence makes powering this on quarter-ends alone near-impossible — to detect a true ~13pp
lift over a fair distance-matched null at 80% power / α=0.05 (two-sided, post-Holm) needs **roughly
120-150+ events**, i.e. **~30+ more years of quarter-ends** (not available) OR broadening to **all
monthly/weekly large-OI single-name call walls** (e.g. the MRVL 330 case) to build n into the
hundreds with a distance-matched null and per-event McNemar pairing. Absent that, the honest verdict
stays `display_only`.

**One thing that would FLIP it back toward refutation harder:** if the 4 cap-only OTM pins, on
inspection, coincide with quarter-end rebalance-flow days or index-reconstitution, the residual
signal collapses entirely into known calendar effects.
