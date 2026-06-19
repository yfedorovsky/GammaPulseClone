# DEX (Delta Exposure) Predictive-Power Test — Pre-Registration

**Date:** 2026-06-18 · **Author:** Opus (main lane) · **Status:** PRE-REGISTERED (not yet run)
**Origin:** A Discord member's claim — *"GEX for levels, DEX near those levels… DEX tells me if
we break or bounce, and how fast/much."* We test it like everything else (Direction-A), because it
is the SAME FAMILY as claims we've already falsified (GEX-spine #75, JPM-collar pin, charm).

## The decisive methodological trap (what kills naive versions of this)

DEX is **mechanically correlated with gamma sign and with where spot sits in the strike
distribution.** So any apparent "DEX predicts direction" can be an artifact of (a) the gamma
regime (which DETECTS but doesn't predict — our settled finding), (b) momentum/autocorrelation (a
trending name has both a delta lean and continuation), or (c) spot-in-the-chain position. **The
test must isolate DEX's INCREMENTAL signal beyond gamma + momentum.** A DEX effect that vanishes
when you control for gamma sign means DEX adds nothing the member doesn't already get from levels.

## Data & scope

- `data/chains_ytd_2026.db::option_eod` — 25.3M rows, **116 single-name roots, 12,398 name-days**,
  2026-01-02 → 2026-06-09. Per strike/day: delta, iv, spot, oi, strike, exp, right.
- DEX = Σ (delta × oi × 100 × spot) over near-term near-money strikes (raw option delta: call +,
  put −; sign convention is irrelevant to predictive POWER). GEX = Σ (BSM-gamma × oi × 100 × spot²
  × 0.01 × [+call/−put]); gamma computed vectorized from iv (no gamma column).
- Aggregation window (fixed in advance): strikes within ±15% of spot, expirations 0–45 DTE.
- **SCOPE LIMIT (state loudly in any writeup):** single names, daily, ~5.5 months. The member's
  framing is SPX-intraday — that's a separate, heavier follow-up (ThetaData SPXW greeks). A null
  here is strong general evidence; a positive here would justify the SPX build.

## Normalization (fixed in advance)

- `DEX_z` = per-NAME z-score of net DEX (each name is its own baseline — matches "DEX is unusually
  +/− for this name"). Same for `GEX_z`.
- `fwd_ret_std` = forward close-to-close return ÷ that name's own daily-return stdev (cross-name
  poolable). Forward windows: **t+1 and t+3** (pre-registered; no other windows fished).

## Pre-registered hypotheses

- **H1 (DEX → direction):** `DEX_z` predicts the sign/magnitude of `fwd_ret_std`.
- **H2 (member's level claim):** conditional on spot within ±3% of a GEX level (nearest call wall
  above / put wall below), `DEX_z` predicts **BREAK** (close beyond the level by >0.5×ATR) vs
  **BOUNCE** (rejects, closes back toward spot) — AUC > 0.5 and beats placebo.
- **H3 (DECISIVE — incremental over gamma):** logistic `break ~ gamma_regime + prior_5d_ret +
  DEX_z`. Does the `DEX_z` coefficient survive (p<0.05 post-correction) and lift out-of-fold AUC
  over the gamma-only model by ≥ **0.02**? If not, DEX is redundant with gamma → claim rejected.
- **H4 ("how fast/much"):** `|DEX_z|` predicts forward realized move size (`|fwd_ret| ÷ name ATR`).

## Controls, null, inference (commit BEFORE looking)

- **Placebo null:** permute `DEX_z` across names *within each date* (preserves the market-day
  cross-section, breaks the name↔outcome link). Real `DEX_z` must beat the placebo distribution.
- **Clustered inference:** two-way cluster (by date AND by name) OR block-bootstrap by date — name-
  days are NOT independent (cross-sectional + serial correlation; the pseudo-replication trap).
  Report the CONSERVATIVE SE.
- **Multiple testing:** Holm-Bonferroni across {H1,H2,H3,H4} × {t+1,t+3} = 8 tests.
- **Effect-size floor (pre-stated):** H3 incremental out-of-fold AUC ≥ +0.02 AND survives Holm;
  H1/H2 |corr| or AUC must beat the placebo 95th percentile. Anything less ⇒ **DEX NOT USEFUL as
  claimed** (the expected default, given the GEX/charm/collar track record).
- **Look-ahead:** all predictors use day-t close data only; outcomes are strictly t+1/t+3.

## Verdict mapping

- `useful_standalone` — H1 & H4 clear AND survive (DEX predicts even before the level conditioning).
- `useful_at_levels_only` — H2 & **H3** clear (the member's specific claim: DEX adds break/bounce
  info AT levels, beyond gamma). This is the bar that vindicates him.
- `redundant_with_gamma` — H2 may look positive but H3 fails (DEX rides gamma, adds nothing).
- `no_signal` — nothing clears placebo.

Default expectation per our research history: `redundant_with_gamma` or `no_signal`. We test to know.
