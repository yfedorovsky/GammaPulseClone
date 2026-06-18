# Design Sketch — Name-Level Opening-Intensity Context Tag

_2026-06-18. Design only — not a build. **REVISED 2026-06-18 (evening)** after the red-team downgraded the premise — see "Correction" below. Pending (1) your go-ahead, (2) a liquidity-control that the original design lacked, and (3) a forward-validation plan. Task #79._

## ⚠️ Correction (red-team 2026-06-18)

The premise this tag was built on was **downgraded**. The original framing below claimed opening-intensity measures *informed positioning / accumulation conviction* and cited `t=+3.41`, 5.5% spread. The adversarial red-team (REDTEAM_2026-06-18.md, independently re-verified by the main-lane consequence-audit) found:

- **The signal is mechanically confounded with liquidity.** `opening_intensity ≈ ΔOI / volume` has volume in the denominator, so high-volume (liquid) names *definitionally* score low-intensity → "churn." `corr(opi, log_liq) = −0.535`. "Churn underperforms" is therefore entangled with "liquid/high-price names underperform" — a generic, known effect, **not necessarily anything about options positioning.**
- **Under a liquidity/price control the effect is fragile**: look-ahead-free OOS `t` falls from `3.01` (uncontrolled) to a **method-dependent 1.4–2.5**. Momentum is *not* the confound (controlling it leaves `t≈3.6`); liquidity/price is.
- **Realized round-trip spread is ~14% median**, not 5.5% — "dead on options" is even more emphatic (REJECT, not SHADOW).

**Net:** this is **real but fragile and not separable from a liquidity/price tilt in a single regime** — *not* the clean informed-positioning signal the original draft claimed. The honest open question is whether a name-level tag would measure flow *quality* at all, or just re-discover "this name is liquid." That question must be answered (with a within-liquidity-bucket test) **before** any build.

---

## Where this comes from

Fable's Pan-Poteshman ΔOI study (AutoResearch, 2026-06-18, as corrected):

- Low opening-intensity (churn-heavy) names underperform their cross-section out-of-semis — **look-ahead-free OOS `t = 3.01` uncontrolled, fragile `1.4–2.5` once liquidity/price is controlled.**
- The component that survives is the **short/fade leg** (churn underperforms). Buying the high-intensity leg is beta. **Direction is noise.**
- **Dead on options** after the ~14% realized round-trip spread — real on the equity cross-section only, never harvestable as an options trade.

## What "opening intensity" means — and why the metric is suspect

Per name per day, roughly:

```
opening_intensity ≈ Δ(settled OI)  /  volume
```

The *intended* reading was: high → new OI created → accumulation; low → churn among existing holders → no conviction. **But because `volume` is in the denominator, the metric is mechanically tied to liquidity** — the most-traded names score lowest, regardless of any positioning story. So a low-intensity ("churn") tag may simply be a high-liquidity tag wearing a behavioral label. Any use of this metric must control for liquidity within-bucket or it is measuring the wrong thing.

## What we already have — and the SHIPPED trap

`server/oi_delta.py` snapshots daily settled OI and computes **contract-level** ΔOI-vs-volume; we use it for dealer-side direction inference. Leave it as-is — it's a neutral data-capture utility.

**The trap is not hypothetical — it is already shipped.** `server/alert_outcomes.py` #60 (next-morning settled-OI confirmation cohort) is the **contract-level version of this exact idea, running every backfill loop**, and it currently labels the mechanical liquidity tilt as "opening conviction." It is *not* wired into the conviction score today (`conviction_booster.py` doesn't read `oi_confirmed`) — the risk is a future session promoting the mislabeled cohort to a gate. Re-scoping #60 to descriptive-only is **task #80**, and it outranks building this tag.

## Does it still earn a build? (weakened)

The original rationale — "the fade leg is the avoid-context our long-biased system lacks (AION #53)" — still *points* somewhere real, but the foundation is now a fragile, liquidity-confounded effect rather than a clean signal. So the bar to build rises:

- **Before any build, run the within-liquidity-bucket double-sort** (the test that adjudicates tilt-vs-signal; it's computed in `poteshman_redteam_checks.py` but was never reported). If opening-intensity has no discrimination *within* a liquidity tercile, there is nothing here but a liquidity tag and the tag should **not** be built.
- If it survives within-bucket, it can be a **descriptive flow-quality annotation only** — never a conviction input — pending forward-validation.

## Hard constraints (tightened)

- **CONTEXT only, never a trigger.** Dead-on-options (~14% spread) means it can never be an alert source.
- **The conviction-discount step is BLOCKED**, not deferred. Letting `CHURN` discount the conviction score re-imports a falsified edge into a live decision. Do not wire it until both (a) the within-bucket test passes and (b) forward-validation confirms churn-tagged names underperform *our* alert outcomes live.
- **No shorting**, no "short this" alerts.
- **Single regime.** One 5.5-month AI-capex bull; the effect collapses under controls. Treat as unproven.

## Proposed shape (only if the within-bucket test passes)

1. **Within-bucket test FIRST** — does opening-intensity discriminate *inside* a liquidity tercile? If no → stop, don't build.
2. **Compute** — name-level `Σ ΔOI / Σ volume` (drop 0DTE/expiry contamination; respect MNAR OI-null on high-priced names like KLAC/BKNG).
3. **Rank** — daily cross-sectional percentile.
4. **Tag** — descriptive label only (`CHURN` / `OPENING` / neutral). Annotation, not alert, **not conviction input.**
5. **Shadow** — log alongside `alert_outcomes` for a forward window. ~~Then let CHURN apply a conviction discount~~ — **STRUCK.** The conviction-discount step does not happen without forward-validation evidence; it is the step that re-imports the falsified edge.

## The bigger picture

The correction makes the [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md) thesis **stronger, not weaker**: the spread doubling (5.5%→~14%) widens the "buyers lose net-of-spread" moat, and the liquidity confound is the *same* mechanism behind whale=liquidity (ρ=0.988) and Poteshman-real-on-equity/dead-on-options. Everything real keeps turning out to be descriptive or confounded; nothing is a tradeable trigger. This tag is now a cautionary instance of that thesis — a candidate awareness layer that must clear a liquidity control before it's even allowed to be *context*, let alone a trade.
