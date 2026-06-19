# DEX Intraday-Flow + Magnet Test — Findings & Verdict

**Date:** 2026-06-19 (Juneteenth) · **Pre-reg:** `docs/research/DEX_INTRADAY_PREREG.md`
**Data:** SPXW **0DTE true tick tape** from ThetaData, 32 days (2026-05-05..06-18), spot from ATM
put-call parity, delta via flat-IV BSM, aggressor from trade-vs-NBBO. Per-strike cache:
`dex_tape_collect.py` → `data/dex_tape_cache.csv` (322,685 strike-buckets). Stats:
`dex_directional_stats.py`, `dex_magnet_stats.py`.

## VERDICTS

- **Intraday DEX-FLOW does NOT lead price → `flow_coincident`** (the friend's "see what is
  happening" framing — confirmed, not refuted).
- **Quant Data's "fresh bubbles are price magnets" → FALSIFIED.** Bubbles attract price no more
  than a distance-matched random strike — if anything, slightly less.

Both close the DEX arc the same way as the static-level test: **exposure/flow is CONTEXT, not a
forward predictor.** This is now tested at every resolution we can reach: static daily level,
day-over-day change, intraday 3-min flow, and the spatial magnet claim.

## 1. Directional flow (HF1/HF2/HF3) — does 3-min flow lead the next 5/15/30 min?

| Metric × horizon | corr | perm_p (within-day) | sign-acc | placebo 97.5 |
|---|---|---|---|---|
| delta-flow → +5m | −0.053 | **0.007** | 0.488 | 0.509 |
| delta-flow → +15m | −0.053 | **0.006** | 0.477 | 0.507 |
| delta-flow → +30m | −0.056 | **0.002** | 0.482 | 0.508 |
| notional-flow → +15m | −0.031 | 0.046 | 0.480 | 0.507 |

n ≈ 4,000 buckets / 32 days. (NOTE — `perm_p` is the corrected **within-day permutation** null; the
original `boot_corr` preserved the x-y pairing and so reported an inert p≈0.5 — a red-team audit caught
it; fixed 2026-06-19.)

**The corrected reading — significant, but NOT leadership.** The small *negative* forward correlation
is statistically real (perm_p 0.002–0.007 for delta-flow). But it is **SPX 0DTE mean-reversion, not
flow leading price.** The regime decomposition is decisive: flow is strongly correlated with the
*contemporaneous* 3-min bar (corr **+0.40**), that bar mean-reverts over the next 15 min (corr −0.14),
and the **partial corr(flow, forward | contemporaneous) = +0.004 — zero.** Controlling for the move the
flow is *part of*, flow has no forward information. Sign-accuracy stays below 0.50 (you can't even
trade the fade reliably). So: **flow is COINCIDENT** (it confirms the move it rides), the market fades
the push, and flow adds nothing predictive on top — exactly the friend's present-tense "see what is
happening." Verdict `flow_coincident` stands; the precise statement is "significant raw forward corr,
fully explained by 0DTE mean-reversion, zero flow-specific lead."

## 2. Magnet test (HM1) — do sudden large fresh bubbles attract price?

Quant Data's help doc, verbatim: *"Sudden large bubbles… often attract price and can create magnets
for flow"* — presented with no validation. Tested it: 2,248 bubble events (top-decile gross premium,
0.2–2.0% from spot, spike vs the strike's trailing baseline), each against a **distance-matched
placebo** (same-distance non-bubble strike — the decisive control, since price drifts toward nearby
strikes by mere proximity).

| Horizon | bubble migration | placebo migration | bubble − placebo | one-sided p | toward-rate (bubble / placebo) |
|---|---|---|---|---|---|
| +5m | −4.4e-5 | −3.7e-5 | −7e-6 | 0.85 | 48.6% / 48.7% |
| +15m | −9.3e-5 | −7.3e-5 | −2.0e-5 | 0.98 | 47.3% / 47.6% |
| +30m | −1.6e-4 | −1.1e-4 | −5.0e-5 | 0.996 | 48.5% / 49.0% |

**Migration is negative** (price drifts slightly *away* from fresh bubbles) and **≤ the distance-
matched placebo at every horizon** (one-sided p 0.85→0.996 — strong rejection of "bubble beats
placebo"). Toward-rate < 50% for both, and bubble ≈ placebo. **Fresh large exposure bubbles do NOT
act as price magnets** on the SPX 0DTE tape. Same shape as the collar pin: an apparent "magnet" that
is at best proximity — and here it does not even reach proximity.

## What this means (the honest, two-sided read)

- **The friend is vindicated in how he actually uses it.** He said he watches the difference view
  "to see what is happening easier" — present tense, a monitoring aid. The data agrees: it's a
  faithful *coincident* read of positioning. He never claimed it forecasts; we confirm it doesn't.
- **Quant Data's marketing claim is not supported.** "Bubbles attract price / are magnets" fails a
  distance-matched test on 2,248 events. The tool is a fine *visualization of what is happening*;
  the *predictive* "magnet" framing is unvalidated by them and falsified by us.
- **GEX/DEX exposure = context, not trigger** — now confirmed at every resolution. Levels are real
  and sticky (SPX holds walls ~92%); which way they break, and whether fresh flow attracts price,
  is not in the exposure data. If anything leads, it is order flow's *aggression* in the moment
  (live tape) — not a static or even a 3-min exposure number forecasting the next 15.

## Honest limits

- SPX **0DTE only**, 32 days. Flat-IV delta; aggressor = trade-vs-NBBO proxy (some misclassification).
- Bubble defined as top-decile gross + spike + 0.2–2% from spot; the distance-matched placebo is the
  robust core, but alternate bubble definitions weren't swept here (an adversarial review could).
- 0DTE is the most relevant intraday regime for both claims, so this is on-point — but longer-dated
  exposure / multi-day positioning (the 30-60 DTE regime) is a different question, untested here.

## Robustness review (5-lens adversarial red-team, 2026-06-19)

Five adversarial lenses re-ran code off the local cache to try to break the two nulls. **Verdict
stands: `confirm_null`.** Four lenses support the null; the fifth found a real reporting bug that does
**not** flip the conclusion. Summary:

| Lens | Attack | Result |
|---|---|---|
| **bubble_definition** | Swept 10 bubble defs (net \|nflow\|/\|dflow\| vs gross, TOP_PCT 80/90/95, DIST bands 0.1-1.0/0.2-2.0/0.5-3.0%, SPIKE_X 1.5/2.0/3.0, drop-spike) | **supports_null** — no def beats placebo; min one-sided p across all = 0.37 (wider 0.5-3.0% band, n=1328); best-case bubble−placebo diff = +3e-6 of spot (~0.0003%, nil). Net/delta metrics make it *worse* (p≈0.99); most defs show bubbles drifting slightly *away*. |
| **aggressor_classification** | Is the ≥ask/≤bid proxy mislabel driving the −0.05? Filter to cleanly-signed buckets | **supports_null** — only ~4% of bucket gross premium survives signing (~90-96% cancels), so the signal lives in a denominator 25× the residual — sign-flips barely move net flow. Cleanest-signed subsets never cross significance (boot_p 0.45-0.68, sign_acc ≤0.50). High-conviction one-sided 0DTE buckets essentially don't exist (<25 above \|net\|/gross 0.30). Caveat: cache bakes signs, so this is robustness-of-conclusion, not an unbiased re-estimate (true Lee-Ready/NBBO-depth reclass needs re-pulling OPRA tape). |
| **placebo_control** | Is the single distance-matched placebo hiding an effect? Avg-over-all-placebos, opposite-side, no-control raw | **supports_null** — every alternate control reproduces the null. Avg-over-placebos p≈0.87/0.97/0.996. Raw absolute toward-rate 0.486/0.473/0.504 (≈ coin flip, below 0.5 at short horizons), mean signed migration NEGATIVE at all horizons. Original control was conservative, not suppressive. |
| **regime_subgroup** | 63 cells (42 directional + 21 magnet); mine for a surviving subgroup | **supports_null** — magnet: 0 survivors in all cells (migration ≤0 everywhere). Directional: 11 "survivors" beat placebo but **all negative-corr, same sign** = a tell. Decomposition kills it: corr(flow_z, contemp 3-min ret)=+0.40; corr(contemp ret, fwd15)=−0.14 (SPX short-horizon mean-reversion); **partial corr(flow_z, fwd15 \| contemp ret)=+0.004** (zero, N=3970). The −0.05 fwd corr is the mechanical product of flow chasing the current bar × that bar mean-reverting — NOT flow leadership, and NOT a contrarian edge. |
| **methodology_audit** | Look-ahead, day-clustering, migration sign, n-inflation, Holm honesty + audit the bootstrap | **finds_caveat (does not flip)** — see below. |

### The one real bug (caveat, not overturn)

`dex_directional_stats.py::boot_corr` (lines 23-27) reports a **statistically inert p-value**. It
resamples whole days from the OBSERVED joint `(x,y)` and counts `P(|boot corr| ≥ |obs|)` — but every
bootstrap sample preserves the x-y pairing, so the bootstrap distribution centers on `obs`, **not on
zero**. It is a precision/stability measure, not a null test; for a true corr of 0.445 it returns
p≈1.000. So `boot_p` is **biased toward non-rejection** and the directional Holm family (built on these
p's) inherits that. **This does not change the verdict** because the directional null is carried by the
*separate, valid* `placebo_sign` permutation (line 30-43, correctly shuffles x within-day): observed
sign-acc 0.477-0.490 sits **below** the placebo 97.5 band (~0.509-0.510) at every horizon, and the raw
corrs are tiny/negative. A broken `boot_p` can only *fail to find* an effect — the valid permutation
test *also* finds none, and the regime decomposition explains the residual −0.05 mechanically. The
magnet's `boot_diff` is a **different, valid** construction (paired day-clustered bootstrap of
`mean(bubble−placebo)`, p = P(mean ≤ 0)) and is sound. Other four audit points (no look-ahead, correct
day-clustered resampling in both files, correct migration sign, no n-inflation, honest Holm) all
verified clean.

**Action item (reporting integrity, not result):** the directional script's `boot_p` column should be
replaced by — or the Holm family rebuilt on — the `placebo_sign` permutation p-values. Tracked; does
not alter any published number or verdict.

### Thread-safe claim

> Quant Data's own help text asserts that "sudden large bubbles often attract price and can create
> magnets for flow" **without publishing any validation**; we tested that exact framing on 2,248
> distinct fresh top-decile-premium SPX 0DTE bubble events against distance-matched placebos across 32
> days and found **no magnet effect** — bubble migration was less-than-or-equal-to the same-distance
> placebo at every horizon (one-sided p 0.85-0.996) and survived no reasonable redefinition, so the
> *predictive* magnet claim is unsupported on our tape even though the tool remains a faithful
> *coincident* visualization of positioning.

*(Fairness note: this names their framing as stated in their docs and tests it on a large pre-registered
sample — it is not a strawman. We falsify the predictive "magnet" assertion, not the tool's stated
purpose as a what-is-happening monitor, which the directional `flow_coincident` result actually
supports.)*

## Re-runnable

`dex_tape_collect.py` (cache) · `dex_directional_stats.py` · `dex_magnet_stats.py`
(`data/dex_tape_cache.csv`, `data/dex_directional_results.json`, `data/dex_magnet_results.json` —
gitignored; regenerate from scripts). **Red-team scripts:** `dex_aggressor_sensitivity.py`,
`dex_magnet_placebo_robust.py` (+ swept bubble-def / subgroup variants), results in
`data/dex_aggressor_sensitivity_results.json` and the magnet-robust JSON.
