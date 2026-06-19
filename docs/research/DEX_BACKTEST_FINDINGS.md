# DEX (Delta Exposure) Predictive-Power Test — Findings & Verdict

**Date:** 2026-06-18 · **Pre-reg:** `docs/research/DEX_PREREG.md` · **Engine:** `scripts/gex_bt/dex_backtest.py`
**Claim tested (Discord member):** *"GEX for levels, DEX near those levels — DEX tells me if we
break or bounce, and how fast/much."*

## VERDICT: `redundant_with_gamma` — DEX is NOT useful as claimed

At single-name daily resolution (12,077 name-days, 116 names, Jan–Jun 2026), DEX shows **no
standalone directional prediction, no move-size prediction, and no economically meaningful
break/bounce edge.** The one nominally-significant result is a coin-flip with a rounding error,
and it **fails the pre-registered "adds value beyond gamma" floor.** Consistent with every prior
structure test: **structure DETECTS context, it does not PREDICT direction.**

## The numbers

| Hypothesis | Metric | Result | Pre-reg bar | Pass? |
|---|---|---|---|---|
| **H1** DEX → next-day direction | corr(DEX_z, fwd1_std) | −0.030 (boot p=0.51) | beat placebo | ❌ |
| **H1** DEX → 3-day direction | corr | −0.053 (p=0.47) | beat placebo | ❌ |
| **H2** DEX → break vs bounce @ level | AUC | **0.526** (placebo 0.521, p=0.006) | beat placebo | ✅* |
| **H3 (DECISIVE)** DEX *beyond* gamma+momentum | CV-AUC lift | **+0.0147** (abs 0.517) | **≥ +0.02** | ❌ |
| **H4** DEX magnitude → move size | corr(\|DEX_z\|, move) | 0.047 (p=0.50) | beat placebo | ❌ |

Holm-Bonferroni (family of 4): only H2 clears (p=0.006 < 0.0125). H1×2, H4 fail.

\* **H2 "passes" but is meaningless.** AUC 0.526 vs a fair within-date placebo of 0.521 = a **0.5%
AUC edge** — 52.6% break-classification where 50% is a coin flip. Statistically detectable at
n=4,838, economically nothing (untradeable after any cost/slippage).

## Why this kills the claim (the decisive logic)

The member's claim is specifically that **DEX adds break/bounce information**. The pre-registered
decisive test (H3) controls for the gamma regime + momentum and asks whether DEX lifts predictive
power. It lifts out-of-fold AUC by **+0.0147 — below the +0.02 floor committed in advance** — to an
absolute **0.517**, still a coin flip. And the base (gamma+momentum) model was itself useless
(**AUC 0.502**), so this is not even "DEX is redundant *because* gamma already works" — at daily
single-name resolution, **neither gamma sign nor DEX predicts which way a level resolves.** Levels
are real (we use them as context); *which way they break is not foretold by the exposure metrics.*

The directional (H1) and magnitude (H4) tests — the "DEX tells me direction / how fast/much" parts
— are flat nulls (corr ≈ −0.03 and +0.05, both p ≈ 0.5). DEX did not even correlate with next-day
direction, let alone predict break velocity.

## Honest scope limits (state these in any public writeup)

1. **Single names, daily, ~5.5 months.** The member's framing is **SPX-intraday** (SpotGamma/Quant
   Data quad-chart style). That exact regime is UNTESTED here — it needs ThetaData SPXW per-strike
   greeks + intraday SPX path (a separate build). A daily single-name null is strong general
   evidence but does not formally close the intraday-index case.
2. **DEX from delta×OI** (settled OI, day-t close) with the call-+/put-− convention; sign is
   irrelevant to predictive *power* (the logistic finds direction either way).
3. Break/bounce defined as forward close beyond level by >0.5×ATR (break) vs rejection back toward
   spot (bounce); ambiguous in-between outcomes dropped (n drops 7,124 near-level → 4,838 resolved).

## What this means for us

- **Keep DEX as CONTEXT, not a trigger** — exactly how we treat GEX. The quad-chart VISUAL
  (GEX/DEX/VEX/CEX) is still worth building as an *awareness* tool (read it discretionarily); it
  just shouldn't be sold as a break/bounce predictor.
- The break/bounce question, at the resolution we can test, is **not** answered by the exposure
  metrics. If anything would, it's order-flow AS the level is tested (live OPRA tape, #77), not the
  static end-of-day exposure profile.

## To overturn this verdict

A `useful_at_levels_only` upgrade would require, on the SPX-intraday data: H2 AND H3 clearing —
i.e., DEX lifting break/bounce CV-AUC by ≥ +0.02 over gamma+momentum, surviving a within-session
placebo and Holm. Given the daily result (+0.0147, and gamma itself at 0.502), the prior is low —
but the intraday-index regime is the member's actual claim and is the only fair place to test it.

---

## Robustness review (2026-06-19, 5 adversarial lenses, all re-ran code)

The null verdict was stress-tested by five independent red-team lenses, several of which RE-RAN the
analysis under alternate definitions/conventions/subgroups. **Verdict: `confirm_null` — DEX is not
useful as claimed. The null is reinforced, not overturned.** One genuine methodological caveat (H3
seed-fragility) was found; it does not change the conclusion and the bias-free test resolves it
against DEX.

### What was re-run and what it found

| Lens | Re-ran | Outcome | Decisive evidence |
|---|---|---|---|
| **break_definition_robustness** | 15 break/bounce defs (ATR×NEAR grid + no-drop) | confirms null | H2 stable-and-trivial [0.518, 0.541] across all defs. H3 lift is **definition-driven**: it rises *monotonically* with BREAK_ATR (0.012→0.041) precisely because larger ATR discards more ambiguous middle rows (break_rate 0.36→0.15) — a **selection artifact**. The honest **no-drop** test (keep ALL near-level rows, label by sign of move through level) **collapses the lift to {+0.007, −0.0039, −0.0007}** — sub-floor, two negative. |
| **dex_convention** | 7 DEX constructions (raw/dollar/short/no_itm/call_only/put_only/**SLOPE**) | supports null | Every variant's H1 block-bootstrap boot_p is pure null (0.47–0.71, \|corr\| 0.02–0.07). The 3 nominal H3 "passes" (dollar/short/no_itm ~0.02–0.025) are the SAME signal as raw under monotone rescaling, landing on the MEDIAN of CV noise (40-seed: mean 0.0211, sd 0.0051, crosses +0.02 in only **53% of seeds**). **DEX-SLOPE = the cleanest null of all** (boot_p 0.545/0.707, the only NEGATIVE H3 lift −0.0088) — and it has full power (4,798 rows, corr 0.32 with level-DEX, genuinely distinct). |
| **subgroup_search** | 8 pre-named (not mined) subgroups w/ own-placebo | supports null | Only `a_lowGEX` survives its own placebo + Bonferroni (H2 AUC 0.549, p=0.002) — but it's the **WRONG direction** (prereg said DEX should work in *high*-\|GEX\|, which is the worst subgroup at 0.512/p=0.42) and its H3 incremental lift over gamma is **+0.008 (zero)**. A signal appearing only where the mechanism is weakest = noise. |
| **methodology_audit** | Full audit of `dex_backtest.py` (look-ahead, drop bias, placebo, bootstrap, Holm) | finds caveat | **No verdict-flipping bug.** No look-ahead (fwd1/fwd3 strictly t+1/t+3; predictors day-t). The 7124→4838 drop is empirically orthogonal to DEX (r=−0.008, p=0.49) → cannot manufacture/hide an edge. **One real defect:** the decisive H3 lift is fold-seed-fragile (30 seeds: mean +0.0219, sd 0.0055, clears +0.02 in 57%); the stored +0.0147 "below floor" is **seed-luck**. Fix = average over fold seeds. Does not overturn: even the upper end (+0.038, abs AUC ~0.53) is an economically-zero coin flip over a useless base. |
| **effect_size_steelman** | Best-case framing of H2 + breakeven WR by payout | finds caveat | Steelman: H2 0.526 is **statistically real** — beats fair placebo (p=0.006), survives Holm, AUC 95% CI lower bound (~0.510) **excludes 0.50**. Don't call it "noise." Counter-steelman: at the natural ~1:1 R:R of a symmetric break/bounce bet, gross edge is only +0.052R, **erased by ~0.05 ATR round-trip cost**; the favorable-payout assumption is unsupported (H4 magnitude is a flat null). And it still **fails the decisive H3 incremental bar.** Honest framing: **statistically real but economically marginal-to-untradeable**, and does NOT vindicate the "DEX adds break/bounce info beyond the level" claim. |

### The two things that matter most

1. **The bias-free ground truth kills the lift.** Stripping the ambiguous-row drop (the no-drop
   labeling, which keeps every near-level row and labels by the sign of the forward move through the
   level) — the construction that actually answers "does DEX predict direction through the wall" —
   takes H3 lift to **−0.0039 / −0.0007 / +0.007** across NEAR bands. The "+0.02-ish" lift that
   appears in the DROP definitions is the drop knob selecting for it, not a DEX edge. The stored
   +0.0147 is the honest read; re-seeding shows it straddles the floor (53–57%), so neither "passes"
   nor "fails" the +0.02 bar is meaningful — and the no-drop test breaks the tie *against* DEX.

2. **The member's strongest framing — "DEX accelerated / changed" (day-over-day SLOPE) — is the
   weakest null in the entire battery.** Worst H1 boot_p (0.545 fwd1 / 0.707 fwd3), near-zero fwd3
   corr (−0.008), and the only NEGATIVE H3 lift (−0.0088), at full power. This is a decisive
   rejection of the specific "how fast/much, it's accelerating" claim, not an underpowering artifact.

### Scope caveat (unchanged, honest)

This is **daily single-name** (116 names, Jan–Jun 2026). The member's actual claim is
**SPX-intraday**. A first-pass intraday probe (`dex_spx_intraday.py`, 16 days, 431 events) gave
DEX-break AUC **0.448 < 0.50** (p=0.285) — directionally consistent with the null but **underpowered**
(effective n ≈ 16 days, flat-IV BSM, coarse snapshots), so it is NOT a decisive test of the intraday
case. The intraday-index regime remains formally open and is the only fair place a future test could
overturn this.

### Robustness artifacts (all re-runnable, gitignored data)

- `scripts/gex_bt/dex_bb_sensitivity.py` → `data/dex_bb_sensitivity.json` (15-def break/bounce grid + no-drop)
- `scripts/gex_bt/dex_alt_constructions.py` → `data/dex_alt_results.json` (7 DEX conventions incl. SLOPE)
- `scripts/gex_bt/dex_subgroup_hunt.py` → `data/dex_subgroup_results.json` (8 pre-named subgroups)
- `scripts/gex_bt/dex_spx_intraday.py` → `data/dex_spx_intraday_results.json` (SPX-intraday probe, underpowered)
- Audited engine: `scripts/gex_bt/dex_backtest.py` → `data/dex_bt_results.json`

### THREAD-SAFE claim (publishable, wrong in neither direction)

> At daily single-name resolution, DEX near GEX levels showed **no usable break/bounce, direction, or
> move-size edge beyond what gamma already encodes** — its one statistically-real signal (break-AUC
> 0.526) is economically a coin flip that fails the pre-registered "adds value over gamma" bar, and
> the day-over-day "DEX is accelerating" version is the weakest signal of all; DEX is **context, not a
> trigger**. (Tested daily single-name; SPX-intraday — the member's actual setup — remains untested
> and is the only place this could still change.)
