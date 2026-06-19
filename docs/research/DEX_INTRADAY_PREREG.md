# DEX INTRADAY-FLOW Test — Pre-Registration (the friend's REAL claim)

**Date:** 2026-06-19 (Juneteenth, market closed) · **Status:** PRE-REGISTERED (not yet run)

## What this tests (and how it differs from DEX_PREREG.md)

The earlier DEX test (`DEX_PREREG.md`) falsified the static DEX **level** + day-over-day change.
The Discord friend clarified his ACTUAL method: he watches the **intraday short-window (3-min)
CHANGE in DEX** — "how the position is building in real time… premium builds in the direction we
would go." That is a FLOW claim (net signed buy-to-open delta accumulating intraday), NOT a static
level — and it was genuinely untested. This pre-registers it.

**Critical distinction:** OI is static intraday, so "DEX building" is NOT OI changing. It is intraday
signed-VOLUME (new positioning). The spot-driven component of DEX change is circular (delta shifts
because price moved) and is EXCLUDED — we test only the FLOW component (signed delta-volume).

## Data (heavy pull, ThetaData free on the holiday)

- SPXW **0DTE** (exp = trading day) intraday trade tape via bulk `/v3/option/history/trade_quote`
  (whole chain w/ NBBO). 0DTE is the dominant intraday SPX gamma/delta driver and matches his
  day-trade framing. ~60 trading days (recent window).
- Spot at tick resolution from **ATM put-call parity** (S ≈ K + C_mid − P_mid at the ATM strike) —
  cleaner than our staleness-prone snapshots, unlimited history.
- Delta via flat-IV (0.15) BSM at the bucket spot (delta is robust to flat IV; sign/weight is what
  matters).

## Metric construction (fixed in advance)

- **Aggressor sign:** trade price ≥ ask → +1 (buy-to-open proxy); ≤ bid → −1; else MID → excluded.
- **DEX-flow** per 3-min bucket = Σ (delta × size × aggressor_sign) over near-money strikes
  (within ±4% of parity-spot). Also **notional-flow** = Σ (price × size × 100 × sign) ("premium
  builds").
- **Per-DAY z-score** the flow (each day its own baseline — matches "DEX unusual for the day").

## Pre-registered hypotheses

- **HF1 (continuation):** 3-min `DEX_flow_z` predicts the SIGN of the next-15-min SPX return.
- **HF2 (magnitude):** `DEX_flow_z` correlates with the next-15-min return (vol-normalized).
- **HF3 (premium variant):** notional-flow_z does the same (his "premium builds" wording).
- Forward windows: **5, 15, 30 min** (15 primary). No other windows fished.

## Controls / null / inference (commit BEFORE looking)

- **Within-day placebo:** permute `DEX_flow_z` within each day (break the flow↔return link, keep
  the day's return path). Real flow must beat the placebo distribution.
- **Day-clustered inference:** block-bootstrap by DAY (buckets within a day are autocorrelated —
  the overlapping-window / pseudo-replication trap). Report the conservative boot_p.
- **Multiple testing:** Holm-Bonferroni across {delta-flow, notional-flow} × {5,15,30} = 6 tests.
- **Effect-size floor (pre-stated):** |corr| must exceed the within-day placebo 97.5th pct AND the
  day-cluster boot_p < (Holm threshold). Sign-accuracy must beat the base rate by ≥ 2 binomial SE
  (day-clustered).
- **Circularity guard:** flow is signed VOLUME only; the spot-driven delta-drift component is never
  used as a predictor; forward return is strictly AFTER the bucket close.

## Verdict mapping

- `flow_predicts` — HF1/HF2 (or HF3) clear placebo + Holm + the effect floor → the friend's
  intraday-flow read has a real short-horizon continuation edge (would be a genuine finding,
  contra the static-DEX null).
- `flow_coincident` — flow correlates with CONTEMPORANEOUS move but not the FORWARD one (it
  confirms, doesn't lead) — the expected "flow is reactive" result.
- `no_signal` — nothing clears placebo.

Prior (from our flow history: ~48% hit, only sweeps survive at 58%): most likely `flow_coincident`.
But this is his exact claim, on the true tape — we test to know.

---

## ADDENDUM — the MAGNET test (Quant Data's own stated claim)

Quant Data's Interval Map help doc states verbatim: *"Sudden large bubbles that appear during the
day can indicate fresh positioning. These often attract price and can create magnets for flow."* —
and (per their docs) **no validation is provided.** This is a SPATIAL attraction claim, distinct
from the directional-flow test above, and it is the most faithful test of the tool's actual thesis.

**HM1 (magnet):** When a sudden large fresh exposure/premium bubble appears at strike K (top-decile
gross premium flow in a 3-min bucket, with K away from spot by 0.2–2.0%), price subsequently
MIGRATES TOWARD K over the next 15 min MORE than a **distance-matched placebo strike** (a non-bubble
strike the same distance from spot, same side).

- **Migration metric:** `migr = (|spot_t − K| − |spot_{t+15} − K|) / spot` (positive = moved toward K).
- **The decisive control (from the collar lesson):** price drifts toward NEARBY strikes by chance, so
  the bubble strike must beat a DISTANCE-MATCHED placebo, not just have positive migration.
- **Bubble size** = gross premium flow at K (Σ price×size, all aggressor trades) — "premium piling in."
- Horizons 5/15/30 min. Day-clustered bootstrap. Within-day placebo (permute which strike is "the
  bubble"). Holm across horizons.
- **Disconfirm:** bubble-strike migration ≤ distance-matched-placebo migration ⇒ no magnet effect
  beyond proximity (the expected default, by analogy to the collar distance-confound).

Both tests run off ONE per-strike tape cache (`dex_tape_collect.py` → `data/dex_tape_cache.csv`).
