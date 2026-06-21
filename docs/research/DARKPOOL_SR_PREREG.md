---
title: "Dark-pool levels as support/resistance — pre-registration (Direction-A)"
date: "2026-06-21"
status: "PRE-REGISTERED before testing. Skeptical lens. NIA. Pilot data = 1 OPEX-week, 21 semis names."
---

# Do dark-pool (TRF off-exchange) volume levels act as support/resistance guardrails?

Written **before** running the test so the read can't become hindsight. Prior from this
project: GEX/DEX structure DETECTS context but does not PREDICT; the option "bubble-magnet"
was FALSIFIED; the only DP level inspected so far (MRVL $310.50, ~37% of week volume) was a
**mechanical OPEX pin**, not revealed institutional S/R. So the skeptical prior is strong.

## The claim under test
A price level where a large share of recent **dark-pool** (FINRA/Nasdaq TRF off-exchange)
volume printed acts as a **guardrail**: when price later approaches that level, it is more
likely to **reverse (hold)** than to break through — more so than at a comparable level with
no dark-pool concentration.

## The two traps this design must defeat
1. **Tautology / lookahead.** DP volume concentrates where price already spent time. A level
   built from *today's* tape will trivially sit where today's price chopped. → **DP levels are
   built ONLY from PRIOR trading day(s); the hold test is on a SUBSEQUENT day's path.**
2. **"Volume node," not "dark-pool node."** Any high-volume price (lit POC, VWAP) tends to act
   as S/R. The claim is specifically that *dark-pool* concentration adds information. → primary
   control is distance-matched; the **lit-POC control is the decisive one but needs lit data
   (deferred, see Data).** Until then the verdict is explicitly "DP levels vs random," NOT
   "DP beats lit."

## Definitions (locked)
- **Price buckets:** width = 0.1% of the name's median price (matches `darkpool_levels.py`).
- **DP levels (causal):** for test day *t*, take the TRF volume-by-bucket profile over the
  trailing window (all prior cached RTH+ETH prints up to *t-1*); the **top K=5** buckets by
  share volume are the DP levels for day *t*. Cleaning: drop `size==0`; drop prints outside
  ±15% of the day's median price.
- **Test path:** day-*t* RTH (09:30–16:00 ET) price, reconstructed as 1-minute bars from the
  cleaned TRF prints (≥ thousands of prints/day → reliable).
- **Touch:** a 1-min bar's range enters [level−ε, level+ε], ε = one bucket, having approached
  from one side (the prior in-RTH bar was strictly on one side of the band).
- **Hold (guardrail):** within H = 30 minutes after a touch, price moves **R = 0.3% AWAY** from
  the level (reversal) before it moves **R through** the level (break). Barrier test; first
  barrier hit wins. Touches with neither barrier hit in H are "unresolved" (dropped).

## Controls
- **C1 distance-matched random (primary, available now):** for each test day, draw K random
  levels at the SAME distances-from-open as the DP levels but at random prices in the day's
  range that are NOT within ε of any DP level. Hold rate at these = base rate.
- **C2 lit-POC (decisive, DEFERRED — needs lit prints):** same construction on LIT volume.
  Tests whether DP adds beyond lit. Not run in the pilot; flagged as the powered-test gate.

## Null + inference (the canonical project method)
- **Within-name permutation null:** permute which buckets are labeled "DP levels" (shuffle the
  volume→bucket assignment within the name), recompute the hold rate, 5000×. Real DP levels must
  beat the permuted hold-rate distribution (one-sided p).
- **Effect + CI:** `lift = hold_rate(DP) − hold_rate(C1)`. Significance via **name/day-clustered
  bootstrap** 95% CI on the lift (resample name-days). Edge requires the CI to EXCLUDE 0.

## Decision rule (pre-registered)
**GUARDRAIL CONFIRMED** iff ALL hold:
- `lift > 0` and its name/day-clustered 95% CI excludes 0, AND
- within-name permutation one-sided p < 0.05, AND
- robust to leave-one-name-out (no single name drives it), AND
- not an OPEX-pin artifact (effect survives excluding the OPEX day / the pinned level).
Else **NULL/REJECTED**, with the failure recorded. Pilot is **underpowered by design** — a
non-significant pilot does NOT kill the idea; it sizes the powered pull (C2 + more weeks).

## Data reality / honest limits
- Pilot: `data/darkpool_cache/<NAME>_2026-06-13_2026-06-20.parquet` = 21 semis names, ~4
  trading days (6/15–6/18), TRF-only, ~OPEX week. Thin → wide CIs expected.
- Powered test needs: (a) **lit prints** for C2 (the decisive control), (b) **more weeks**
  across non-OPEX periods (~$7/week/basket via Databento), (c) ideally a non-semis basket to
  rule out sector-specificity.
- NOT investment advice. Structure DETECTS context; it does not PREDICT until proven here.
