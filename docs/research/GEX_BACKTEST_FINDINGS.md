# Direction A — GEX-Structure Tradeability: Findings

**Companion to** `docs/research/GEX_BACKTEST_PREREG.md` (the binding pre-registration). Hypotheses,
bands, horizons, and pass bars were fixed there *before* running and are not moved here. This document
reports the full result matrix and the verdict, in the same skeptical spirit that killed the whale-flow edge.

---

## VERDICT

**GEX structure is CONTEXT, not a TRIGGER.** Across all five hypotheses — 78 pre-registered
(hypothesis × band × horizon) cells — **0 cells pass the full pre-committed bar.** The king/floor/
ceiling/gamma-flip geometry we trade off is **descriptive-not-tradeable**: it describes where price
*is* relative to dealer structure, but a mechanical entry on that geometry does not produce a
positive net-of-slippage edge that survives out-of-sample (CPCV), multiplicity deflation (DSR),
overfit detection (PBO < 0.5), a regime split, and the per-ticker base-rate null — simultaneously,
in even one cell. This is the *same* verdict the flow work reached: the heatmap is **awareness**, not
a switch.

---

## How to read the matrix

Each cell is graded against all five pre-committed pass legs. A cell **passes only if ALL hold**:

1. `net_R>0` **and** `cpcv_lower>0` (out-of-sample lower band positive),
2. `dsr_positive` (Deflated Sharpe positive, deflated for the full trial count),
3. `pbo<0.5` (CSCV — not an overfit),
4. `regime_robust` (survives the RISK-ON / RISK-OFF / crash split),
5. `beats_base_rate` (beats the per-ticker unconditional forward-move null).

`net_R` = mean R after a 2bps/side spot-slippage haircut. R = oriented forward move / band width.
Cells are reported in full — best and worst — per the PBO discipline (no slicing-until-it-passes).

**Data windows (verified against `gex_backtest/work.db`):**
- **Track I (intraday):** `gex_events_intraday`, 73,525 events, **2026-05-28 .. 2026-06-15, 13 trading
  days**, stable king-selection-v3 window, ~444 roots in the pin universe (457 across all setups).
  Regimes: 64,221 POS / 9,304 NEG. `is_stale=1` excluded at build time.
- **Track S (swing/EOD):** `gex_struct_eod`, 12,213 EOD rows, **116 roots, 2026-01-02 .. 2026-06-09**
  (109 distinct dates), recomputed with FIXED king/floor/ceiling/net-gamma logic (BSM gamma from IV
  via `server/gex.py _bsm_gamma`; `net_gex = gamma·OI·100·spot²·0.01`, calls +, puts −).

---

## H1 — Positive-gamma PIN → king mean-reversion (fade deviation toward king)

**Claim.** In POS gamma, when spot sits within band b of the king, the forward move is suppressed and
drifts *toward* the king; the fade-toward-king trade should be positive.

**Result: clean, well-powered NULL (0/9).** Pinned spot in POS gamma does **not** revert toward the
king — the fraction reverting is **< 0.50 in every cell** and the residual drift is faintly *away*
from the king. The fade trade bleeds net of slippage in all 9 cells (−0.07R to −0.64R). No cell clears
any single pass leg.

| band | horizon | n | mean R | net R (slip) | base-rate Δ | cpcv_lo | DSR+ | PBO | regime_robust | beats_base | PASS |
|---|---|---:|---:|---:|---:|---:|:--:|---:|:--:|:--:|:--:|
| 0.15% | 15m | 3853 | −0.202 | **−0.469** | −0.176 | −0.562 | no | 0.073 | no | no | ❌ |
| 0.15% | 30m | 2340 | −0.377 | **−0.644** | −0.209 | −0.945 | no | 0.073 | no | no | ❌ |
| 0.15% | 60m | 2808 | −0.094 | **−0.361** | −0.082 | −0.508 | no | 0.073 | no | no | ❌ |
| 0.30% | 15m | 7940 | −0.047 | **−0.180** | −0.060 | −0.229 | no | 0.073 | no | no | ❌ |
| 0.30% | 30m | 4763 | −0.118 | **−0.251** | −0.145 | −0.369 | no | 0.073 | no | no | ❌ |
| 0.30% | 60m | 5865 | −0.024 | **−0.157** | −0.102 | −0.239 | no | 0.073 | no | no | ❌ |
| 0.50% | 15m | 13341 | −0.009 | **−0.089** | −0.004 | −0.113 | no | 0.073 | no | no | ❌ |
| 0.50% | 30m | 8135 | −0.036 | **−0.116** | −0.009 | −0.137 | no | 0.073 | no | no | ❌ |
| 0.50% | 60m | 9844 | +0.005 | **−0.075** | +0.038 | −0.146 | no | 0.073 | no | no | ❌ |

The only gross-positive cell (0.50%/60m, +0.005R) is a rounding artifact that inverts to −0.075R after
slippage. Note the low family PBO (0.073) is **not** evidence of an edge here — it just says "the loser
is consistently a loser," which is the opposite of tradeable. **H1: descriptive-not-tradeable.**

---

## H2 — Positive-gamma FLOOR bounce (long the floor test)

**Claim.** In POS gamma, a spot test within band b of the GEX floor produces a positive forward return
(bounce) beating the per-ticker base rate.

**Result: 0/9.** The "bounce" is a **49.6–51.1% coin flip** with a ~±1bp mean move that goes negative
after slippage in every cell. CPCV lower band < 0 everywhere; no DSR-positive cell; family **PBO 0.65**
(high — the apparent signal is overfit-prone); no regime robustness — the only positive gross means come
*purely* from risk-on days and invert hard on risk-off; base-rate deltas are indistinguishable from zero
(O(1e-4)).

| band | horizon | n | mean R | net R (slip) | base-rate Δ | cpcv_lo | DSR+ | PBO | regime_robust | beats_base | PASS |
|---|---|---:|---:|---:|---:|---:|:--:|---:|:--:|:--:|:--:|
| 0.15% | 15m | 3238 | +0.072 | **−0.195** | +0.0001 | −0.430 | no | 0.649 | no | no | ❌ |
| 0.15% | 30m | 2335 | −0.023 | **−0.290** | +0.0001 | −0.515 | no | 0.649 | no | no | ❌ |
| 0.15% | 60m | 2537 | −0.305 | **−0.572** | −0.0002 | −0.865 | no | 0.649 | no | no | ❌ |
| 0.30% | 15m | 6544 | +0.031 | **−0.102** | +0.0001 | −0.139 | no | 0.649 | no | no | ❌ |
| 0.30% | 30m | 4644 | +0.003 | **−0.131** | +0.0001 | −0.227 | no | 0.649 | no | no | ❌ |
| 0.30% | 60m | 5083 | −0.098 | **−0.231** | −0.0001 | −0.358 | no | 0.649 | no | no | ❌ |
| 0.50% | 15m | 10688 | +0.017 | **−0.063** | +0.0001 | −0.091 | no | 0.649 | no | no | ❌ |
| 0.50% | 30m | 7561 | +0.014 | **−0.066** | +0.0001 | −0.097 | no | 0.649 | no | **yes** | ❌ |
| 0.50% | 60m | 8300 | −0.049 | **−0.129** | −0.00001 | −0.214 | no | 0.649 | no | no | ❌ |

One cell (0.50%/30m) nominally "beats base rate" by 1.4e-4 — economically zero, and it fails every other
leg. **H2: descriptive-not-tradeable.**

---

## H3 — Positive-gamma CEILING reject (short the ceiling test)

**Claim.** Symmetric to H2: at the ceiling, forward return is negative (reject).

**Result: 0/9, the weakest hypothesis of all.** Ceiling-touch events are rare in this universe (n =
136–853/cell). Net-of-slippage R is **negative in every cell** (−0.16R to −1.34R), CPCV lower bands are
deeply negative (down to −3.7R), DSR negative everywhere, and family PBO is **0.86** with several cells
at **0.96** — i.e. almost certainly overfit. The "short the reject" trade not only fails to print; it
loses badly and unstably.

| band | horizon | n | net R (slip) | cpcv_lo | DSR+ | PBO | PASS |
|---|---|---:|---:|---:|:--:|---:|:--:|
| 0.15% | 15m | 227 | −0.41 | −0.87 | no | 0.86 | ❌ |
| 0.15% | 30m | 136 | −0.90 | −1.59 | no | 0.63 | ❌ |
| 0.15% | 60m | 179 | −1.34 | −3.70 | no | 0.96 | ❌ |
| 0.30% | 15m | 453 | −0.20 | −0.31 | no | 0.86 | ❌ |
| 0.30% | 30m | 296 | −0.29 | −0.55 | no | 0.83 | ❌ |
| 0.30% | 60m | 364 | −0.73 | −1.65 | no | 0.96 | ❌ |
| 0.50% | 15m | 853 | −0.16 | −0.30 | no | 0.86 | ❌ |
| 0.50% | 30m | 569 | −0.24 | −0.43 | no | 0.71 | ❌ |
| 0.50% | 60m | 653 | −0.38 | −0.63 | no | 0.96 | ❌ |

**H3: descriptive-not-tradeable** (and the most overfit-prone of the family — small-n, high PBO).

---

## H4 — Negative-gamma instability (does the regime tag INVERT H1–H3?)

**Claim.** In NEG gamma the proximity setups should flip: realized vol higher, breakouts beat fades.
Graded over `regime='NEG'` events, **27 cells** = setup(pin/floor/ceiling) × band(0.15/0.30/0.50%) ×
horizon(15/30/60m). R is **H4-oriented**: floor = short/breakdown (−fwd), ceiling = long/breakout
(+fwd), pin = sign(displacement-from-king)·fwd. DSR deflated for n_trials = 27.

**Result: 0/27.** The NEG-gamma tag carries only a *faint gross* pin-instability signal — oriented pin
breakout +0.03–0.08%/move with t ≈ 2.6–2.9 — that **dies on slippage**, never clears the CPCV
out-of-sample lower band (negative in all 27 cells), never survives 27-trial DSR deflation, and never
significantly beats the unconditional oriented null. The inversion claim is also only *partially* true
descriptively: pin |move| **is** higher in NEG (consistent with instability), but floor/ceiling |move|
is actually **lower**, and the ceiling still *rejects* rather than breaks out (NEG ceiling cells are
all negative-R, n = 12–62).

PBO by setup: **pin 0.681, floor 0.263, ceiling undefined** (n too small / degenerate split, shown as
`−1` sentinel in the grade JSON). Selected cells (full 27 in `gex_backtest/h4_result.json`):

| setup@band | horizon | n | mean R | net R (slip) | cpcv_lo | DSR+ | regime_robust | beats_base | PASS |
|---|---|---:|---:|---:|---:|:--:|:--:|:--:|:--:|
| pin@0.30% | 30m | 407 | +0.438 | +0.304 | −0.153 | no | **yes** | no | ❌ |
| pin@0.50% | 30m | 812 | +0.152 | +0.072 | −0.170 | no | **yes** | no | ❌ |
| pin@0.50% | 60m | 938 | +0.165 | +0.085 | −0.246 | no | no | no | ❌ |
| pin@0.30% | 15m | 747 | +0.158 | +0.025 | −0.141 | no | no | no | ❌ |
| floor@0.15% | 60m | 643 | +0.554 | +0.287 | −0.268 | no | **yes** | no | ❌ |
| floor@0.50% | 60m | 1858 | +0.093 | +0.013 | −0.130 | no | no | no | ❌ |
| ceiling@0.15% | 30m | 12 | −0.813 | −1.079 | −2.394 | no | no | no | ❌ |
| ceiling@0.50% | 60m | 30 | −0.010 | −0.090 | −0.553 | no | no | no | ❌ |

The handful of `regime_robust=yes` pin/floor cells still fail because **cpcv_lower < 0** and **DSR is
negative after 27-trial deflation** — i.e. they don't survive out-of-sample or multiplicity. The NEG tag
is real *information about realized dispersion* (pins are wider) but it is **not a tradeable inversion**.
**H4: descriptive-not-tradeable** (inversion claim partially true descriptively, false economically).

---

## H5 — Overnight structure drift (Track S, EOD swing)

**Claim.** Signed EOD distance to the gamma king [king-above-spot → long toward king; king-below →
short] predicts `fwd_ret_1d` / `fwd_ret_3d` via mean-reversion toward the king, beyond the per-ticker
base rate. Buckets = |dist_king_pct| ≤ {0.15%, 0.30%, 0.50%}; R = signed_fwd / band; 2bps/side haircut;
DSR deflated for the **full 42-trial matrix** (H1–H4's 36 + H5's 6).

**Result: 0/6.** The tightest bucket (≤0.15%) is *negative* — pinned-overnight names drift the wrong way
(−0.67R to −1.47R net). The wider buckets show positive gross/net R that grows with horizon, and **one
cell (0.50% / 3d) clears CPCV, DSR-positive, and base-rate**:

| band | horizon | n | mean R | net R (slip) | base-rate Δ | cpcv_lo | DSR+ | PBO | regime_robust | beats_base | PASS |
|---|---|---:|---:|---:|---:|---:|:--:|---:|:--:|:--:|:--:|
| king≤0.15% | 1d | 405 | −0.401 | −0.668 | −0.651 | −3.242 | no | 0.907 | no | no | ❌ |
| king≤0.15% | 3d | 401 | −1.208 | −1.475 | −1.288 | −4.167 | no | 0.907 | no | no | ❌ |
| king≤0.30% | 1d | 750 | +0.323 | +0.190 | +0.234 | −0.528 | no | 0.907 | no | no | ❌ |
| king≤0.30% | 3d | 743 | +1.091 | +0.958 | +1.131 | −1.051 | no | 0.907 | no | no | ❌ |
| king≤0.50% | 1d | 1173 | +0.405 | +0.325 | +0.299 | −0.010 | no | 0.907 | no | no | ❌ |
| **king≤0.50%** | **3d** | **1157** | **+1.024** | **+0.944** | **+0.881** | **+0.197** | **yes** | **0.907** | **no** | **yes** | ❌ |

That one cell is **killed by the remaining two legs**, decisively:
- **PBO = 0.907** (family-wide CSCV) — there is a >90% probability this configuration is the in-sample
  best by luck; it is an overfit selection, not a stable rule.
- **Regime-fragile.** The day-level payoff dispersion is enormous: the king≤0.50%/3d bucket runs from
  **−0.095 mean fwd_ret_3d on the worst days (6/3, 6/4, 3/25)** to **+0.10–0.11 on the best
  (3/2, 3/3, 4/28)**. Net +0.94R pooled is **risk-on beta** (≈ +1.9R on risk-on, ≈ −0.06R on risk-off,
  ≈ −0.33R through the crash window) — the 2026 universe's broad-beta drift, *not* a king-pin reversion
  edge. The tightest, "most pinned" bucket actually drifts the wrong way, which is the tell: this is not
  a king-distance signal, it's a low-volatility-name-in-an-up-tape signal.

**H5: descriptive-not-tradeable.**

---

## What survived adversarial refutation — and what did not

**Survived: nothing.** No cell in any hypothesis cleared all five pass legs. The two cells that looked
alive after the first three legs each fell to a specific, decisive refutation:

| Apparent edge | Why it died |
|---|---|
| H5 king≤0.50% / 3d (net +0.94R, CPCV+, DSR+, beats base) | **PBO 0.91** (overfit selection) **+ regime-fragile** — pure risk-on beta; tightest bucket drifts *against* the thesis; inverts on risk-off and in the crash. Not a king-pin edge. |
| H4 NEG pin@0.30%/30m & floor@0.15%/60m (regime_robust, gross +0.3–0.55R) | **cpcv_lower < 0** (no OOS positive lower band) **+ DSR negative** after 27-trial deflation. The NEG dispersion is real but not capturable net of slippage. |

The honest read: the moment a cell looked promising on raw R, exactly one of {slippage, OOS lower band,
multiplicity deflation, PBO, regime split} took it out. That is the pre-registered machinery working as
designed — the same way it killed the whale/flow edge.

---

## Confounds checked (all five pre-named, all controlled)

1. **Single-regime / period risk** — controlled via the RISK-ON/OFF/crash split. It was *decisive*: the
   only net-positive Track-S cell is a pure risk-on artifact (H5 above). `regime_robust` is `false` in
   every passing-candidate cell.
2. **Slippage / economic null** — a flat 2bps/side spot haircut flips the sign of essentially every
   marginal cell (H1 0.50%/60m, all of H2's positives, the H4 pin cells). Gross R was never the verdict;
   net R is negative or sub-null everywhere that matters.
3. **Signal-definition drift (Track I)** — mitigated by restricting to the stable king-selection-v3
   window (2026-05-28..2026-06-15, 13 days), as pre-registered. No king-logic change inside the window.
4. **Base-rate illusion** — every cell is differenced against the per-ticker *unconditional* oriented
   forward-move null (`base_rates` table). Track-I base-rate deltas are O(1e-4) (economically zero);
   Track-S deltas that look large (H5) are the same risk-on beta the base rate also contains once you
   condition on regime.
5. **Multiplicity** — DSR deflated for the full trial count (27 for H4's NEG family; 42 across the
   H1–H5 matrix for H5). PBO via CSCV per family. Reported ALL cells, never the best one in isolation.

---

## Honest limitations

- **Track S is EOD-only, single-year (2026 YTD).** 116 roots, 109 dates. It includes the Feb/Mar
  regime-diverse window and a crash, which is *why* the regime split is informative — but it is still one
  calendar year and one universe. A multi-year swing replay could change magnitudes (not, on this
  evidence, the verdict).
- **Track I is stable-window-only — 13 trading days.** This is the price of avoiding king-selection
  drift: deep per-event n (73,525 events) but shallow *calendar* coverage (~3 weeks, late-May/mid-June).
  Cells are well-powered on count, under-powered on *distinct regimes*. The NEG-gamma sample (9,304
  events) spans few genuinely NEG-regime days.
- **As-implemented king.** Both tracks use *our* king/floor/ceiling definition, including the #73 scope
  quirk (no-floor serialized null; king<spot fallback-guard dropped). This is deliberate — we test the
  structure we actually trade, not an idealized one — but it means the null is about *this* signal, not
  GEX-in-the-abstract. A differently-defined king is a different (un-pre-registered) experiment.
- **Spot-only fills.** Track I grades on next-snapshot spot ± haircut, not on option fills. The economic
  null is therefore generous to the hypothesis (real option slippage/theta would be worse), which only
  *strengthens* the null verdict.
- **Ceiling samples are thin** (H3 n = 136–853; H4 NEG ceiling n = 12–62). Those cells are reported for
  completeness but their PBO/DSR are barely defined; treat the ceiling conclusions as "no evidence of an
  edge," not a precise effect estimate.

---

## Product implication

**The GEX heatmap is CONTEXT (awareness), not a TRIGGER.** This is the *same* conclusion the flow work
reached for whales: dealer structure tells you *where you are* (pinned vs. at a floor vs. unstable in
short-gamma), and that framing has real descriptive value for sizing, expectations, and the
short-gamma-tape guardrail (#54). But a mechanical "fade to king / buy the floor / short the ceiling /
fade the gamma flip" entry is **not** a positive-expectancy trade net of slippage, and nothing here
licenses promoting any king/floor/ceiling proximity event to an auto-fire or a sizing-up trigger.

- **Keep:** the heatmap and regime tag as *context* — POS = pin/suppressed expectations, NEG = wider
  realized dispersion (the H4 pin |move| result is genuinely informative for *risk*, not *direction*).
- **Do not:** wire any of these 78 cells into an alert/auto-trade as a standalone edge.
- **If anything is ever revisited:** the *only* candidate worth a pre-registered live FORWARD test (not a
  switch-flip) is the Track-S king≤0.50%/3d drift — and *only* after explicitly de-betaing it
  (regress out universe/risk-on beta) and re-running on out-of-sample 2026-H2 data, since on this sample
  it is indistinguishable from risk-on beta with PBO 0.91. Absent that, it stays in the CONTEXT bucket.

**Bottom line:** 0/78 cells tradeable. The GEX structure is the spine of the *view*, not a *signal*.
This is a clean, well-powered null — a finding, not a failure.

---

*Artifacts (gitignored): `gex_backtest/work.db` (`gex_events_intraday` 73,525 rows; `gex_struct_eod`
12,213 rows; `base_rates`), `gex_backtest/h4_result.json`. Reusable graders:
`scripts/gex_bt/{build_swing,build_intraday,build_base_rates,grade_h1..h5,stats}.py`. Pre-registration:
`docs/research/GEX_BACKTEST_PREREG.md`.*
