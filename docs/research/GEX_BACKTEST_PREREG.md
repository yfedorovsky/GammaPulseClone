# Direction A — GEX-Structure Tradeability: Pre-Registration

**Purpose.** We rigorously falsified the *flow* edge (WHALE/INFORMED → thematic/dead).
We then asserted "GEX/dealer structure is the reliable spine." That is an **assumption, not a
measurement.** This pre-registers a test — using the same machinery that killed whales — of
whether the GEX structure we actually trade off (king-pin, floor-bounce, ceiling-reject,
gamma-flip) has a **tradeable** edge, or is merely **descriptive**.

Pre-registered BEFORE running. Hypotheses, signal definitions, horizons, and pass bars are fixed
here; results do not get to move them. No slicing-until-it-passes (the PBO discipline).

---

## Data (honest constraints)
- **Track S (swing/overnight):** `chains.db` (Fable) — daily EOD, 116 roots, YTD 2026, 25.3M rows.
  We **recompute** king/floor/ceiling/net-gamma with FIXED logic across all dates → a *consistent*
  signal over deep, regime-diverse history (incl. the Feb-28 Iran crash).
- **Track I (intraday pin):** `snapshots.db::snapshots` — ~1–2 min king/floor/ceiling/spot/
  pos_gex/neg_gex/regime, our universe. The on-target data (it IS the heatmap we trade), BUT the
  king-selection logic drifted over time, so Track I is **restricted to a stable-logic window**
  (post the last king-selection change; identify the exact commit/date and use only days after it;
  report the window length). `is_stale=1` rows excluded.

**Known confounds (pre-named, must be controlled):**
1. **Single-regime / period risk** — same trap as whales. Report a regime split (RISK-ON/OFF, the
   crash window) — an edge that lives in one regime is conditional, not general.
2. **Slippage / economic null** — Phase 6 killed phantom alpha on slippage alone. Every edge is
   re-graded with realistic ask/bid fills; gross R is not the verdict.
3. **Signal-definition drift (Track I)** — mitigated by the stable-logic window.
4. **Selection across hypotheses** — DSR/PBO deflate for the number of (hypothesis × parameter)
   trials. Report ALL cells, not the best one.

---

## Hypotheses (falsifiable, pre-stated)

**H1 — Positive-gamma pin.** In POS gamma, when spot is within band b of the king, forward realized
move is *suppressed* and drifts *toward* the king (mean-reversion). Tradeable: fade deviations toward king.

**H2 — Floor bounce.** In POS gamma, when spot tests within band b of the floor, forward return is
*positive* (bounce) at a rate beating the ticker's base rate.

**H3 — Ceiling reject.** Symmetric to H2: at the ceiling, forward return is *negative* (reject).

**H4 — Negative-gamma instability.** In NEG gamma, the same proximity setups do NOT hold — realized
vol is *higher* and breakouts beat fades (the inverse of H1–H3). Tests whether the regime tag itself
carries information.

**H5 — Overnight structure drift (Track S).** EOD signed distance to the gamma structure (spot vs
king, and net-gamma sign) predicts next-day / multi-day forward return, beyond the ticker's drift.

---

## Signal & outcome definitions (mechanical)
- **Bands b:** pre-fixed grid {0.15%, 0.30%, 0.50%} of spot. No post-hoc band tuning.
- **Regime:** the recorded `regime` (POS/NEG) for Track I; recomputed net-gamma sign for Track S.
- **Forward horizons:** Track I {15, 30, 60 min} intraday spot move; Track S {1, 3 days} close-to-close.
- **Outcome:** signed return in R units (move / a fixed per-setup risk = band width or ATR fraction),
  AND raw % move. Win = direction matches the hypothesis.
- **Entry/exit:** mechanical at signal time; exit at horizon end OR opposing structure touch.
- **Fills:** Track I uses next-snapshot spot (no look-ahead) ± a spread/slippage haircut; Track S uses
  next-open or close with a haircut. Slippage model = the `realistic_slippage` convention.

## Benchmarks / nulls
- Per-ticker base rate (unconditional forward-return distribution) — the edge must beat it.
- Random-entry bootstrap (same count, same ticker/time distribution).
- Economic null: net-of-slippage R lower-CI.

## Pass bar (pre-committed)
An hypothesis is **CONFIRMED tradeable** only if ALL hold:
1. Pooled net-of-slippage mean R > 0 with **CPCV lower band > 0**.
2. **DSR > 0** (deflated for the full hypothesis × band × horizon trial count).
3. **PBO < 0.5** (CSCV) — not an overfit.
4. Survives the **regime split** (not driven by a single regime/the crash window).
5. Beats the per-ticker base rate (not just > 0 in absolute terms).

Anything less is reported as **descriptive-not-tradeable** (the honest default), exactly as we would
for whales. A null result here is a finding, not a failure — it tells us the heatmap is *awareness*,
not a trigger.

---

## Execution plan (the ultra workflow)
- **Phase 1 — Build:** recompute consistent GEX from `chains.db` (Track S surface); extract Track I
  setup events from `snapshots.db` (stable window). Parallel by root.
- **Phase 2 — Grade:** per hypothesis × band × horizon, compute R distributions, base-rate deltas,
  slippage-net, CPCV/DSR/PBO. Parallel by hypothesis.
- **Phase 3 — Adversarial verify:** independent skeptics try to refute each apparent edge (regime
  artifact? look-ahead? base-rate illusion? slippage-fragile?). Majority-refute kills it.
- **Phase 4 — Synthesize:** the matrix + the honest verdict into `GEX_BACKTEST_FINDINGS.md`.

Read-only on both DBs. No live-system changes. Results decide nothing automatically — they inform
whether the GEX spine is a *trigger* or *context*.
