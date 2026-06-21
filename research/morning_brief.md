# Morning brief — overnight research session 2026-06-20/21

**Pure research. Not investment advice / not a licensed-advisor output. No signal here is
trade-ready: Layer-2 is not yet powered enough to certify any economic edge.**

## Headline
Built the full two-layer research loop from scratch, seeded it with the 9 prior edges, and
ran **26 hypotheses** across Categories A/B/C-proxy/D/E **plus 10 interaction signals**.
**Zero new validated edges** — the correct, expected outcome. The session's highest-value
output is **methodological**: a Layer-2 engine that is now **validated 4 ways** (rejects beta,
accepts true positives, fairly handles regime-specific edges, refuses underpowered calls), and
a pipeline that caught every would-be false positive (B1, B3, I2, I7) that raw significance
would have waved through.

## Coverage
Cycles: 26 (16 single-condition + 10 interaction) · Category coverage: **A=5, B=4, C=1, D=2,
E=4, +10 interactions**, F=0, G=0 (both deferred with cause).
Engine: `research/signal_bt.py` (Layer-1) + `research/option_translate.py` + `theta_options.py`
(Layer-2, **hardened**: bootstrap CIs · monthly-expiry · power guard · regime-conditioned controls).

## Layer-2 hardening + validation (the session's main deliverable)
Hardened across 8 axes and validated with synthetic oracle fixtures — see `methodology_notes.md`
§7–10. Verdicts are **CI-based** (PASS needs the signal-mean CI *and* the appropriate edge CI to
exclude 0). Monthly-expiry preference cut NBBO-skip 55-60% → ~13% (retention 0.40 → 0.87).
**Regime-conditioned controls** replaced the mono-regime hard block: a mono-regime signal is
tested vs random entries *from its own regime* → `PASS_REGIME_CONDITIONAL` for a genuine
within-regime edge, REJECT for regime beta. Guard validated: B1→REJECT (stable 6/6),
multi-regime oracle→PASS, regime-locked oracle→PASS_REGIME_CONDITIONAL, underpowered→INCONCLUSIVE.

## Wave-3 — interaction signals (vol×breadth, vol×RS, divergences)
10 interaction hypotheses, **0 genuine edges**. Combining two null/beta conditions does not
manufacture an edge — the interaction space is also null on QQQ. Lone Layer-1 survivor
**I2** (high-vol+low-breadth washout) → **Layer-2 REJECT** on the *first real-signal* run of the
regime-conditioned path: it's vol beta (works in V-bottoms 2020/2025, lost −15.5%×24 in the 2022
bear, doesn't beat random high-vol entries). **I9** double-RS-lag short is significantly
*wrong-direction* (perm_p 0.033 — double weakness → QQQ bounces; contrarian, not a short edge).
**I7** = B3 + vol filter = still trend beta (a vol condition doesn't de-beta a trend signal).

## Validated edges (new this session)
**None.** (Prior, pre-session: FibLV-UP and opening-drive-as-context remain the only survivors,
both still pending option translation.)

## Promising leads (needs refinement) — but flagged beta, NOT queued
- **B3 pullback-in-uptrend** (B): perm_p 0.011, +0.33pp/5d, OOS 0.78, breadth 0.64 — passes
  almost everything **except** year-consistency (0.59<0.60). **Structurally it is the same trade
  as B1**: both gate on `close>200SMA`, so both fire ~exclusively in `trend_up` and both inherit
  the identical mono-regime / year-concentration beta profile. Parking it is the same call as B1,
  for the same reason — they are one family, not two independent signals. Both the `years_pos`
  gate and the adversarial skeptic flagged it `LIKELY_BETA_OR_ARTIFACT`. **Not promoted.**

## Rejected (16 hypotheses — with the informative ones called out)
- **B1 12-1 momentum** → Layer-1 real-but-year-concentrated-beta; **Layer-2 INCONCLUSIVE**
  (verdict flipped −12.2/+31.6/+71.6pp vs random across 3 draws at n=14–24). Parked beta-only.
- **A6 extreme-vol washout** → **significant in the WRONG direction** (perm_p 0.007, −0.43pp/10d):
  extreme rv20 → *continued decline* (vol clustering), falsifying "buy the washout." Tradeable
  read (short) is a widow-maker; not promoted.
- **E1/E2/E3/E4 (entire cross-asset category)** → comprehensively **null**. Breadth, semis-RS,
  and QQQ/SPY-RS carry no forward edge on QQQ (well-known/priced factors). E3 semis-leadership
  was marginal (+0.15pp, perm_p 0.14) but failed year/OOS.
- **A3/A4/A5** vol-regime variants → null. A4 (low-vol melt-up) and E1 (breadth-high) are
  textbook beta: n=2291 / n=3405, lift ≈ 0.
- **B4 momentum-acceleration, B2 52wk-low, D1 turn-of-month, D2 OPEX-week, A1 panic-bounce,
  A2 vol-backwardation** → null (D1/D2 = decayed anomalies; clean replication of post-publication decay).

## Top 3 insights
1. **Dual controls are non-negotiable.** B1's opposite-direction control showed a fake +51.5pp
   "directional edge" that was pure bull beta; only the random-entry control (−12.2pp) exposed it.
2. **An underpowered Layer-2 manufactures false verdicts.** B1 flipped PASS↔REJECT across samples
   → added a hard power guard (n≥30, ≥3 yrs×≥3 trades, ≥2 regime cells×≥10, retention≥40%, mono-regime flag).
3. **The year-consistency gate is earning its keep.** It (with the skeptic) caught both B1 and B3 —
   the two signals whose raw permutation-significance looked tradeable but which are mono-regime beta.
4. **The system can falsify, not just reject noise.** A6 (buy-the-extreme-vol-washout) came back
   *significant in the wrong direction* (perm_p 0.007, −0.43pp/10d) — a clean, positive falsification
   of a plausible thesis (extreme vol → continuation-down, not bounce). A directional negative result
   like this is often worth more than another marginal positive.

## Portfolio implications
None — no validated, uncorrelated edges to allocate. The price/vol/breadth/RS signal space is now
well-covered on QQQ + the 40-name panel and is **mostly null after proper inference**.

## Next priorities
1. **Harden Layer-2** (bootstrap CI on edge-vs-control + monthly-expiry skip fix) — the gating
   bottleneck; until done, no economic verdict is trustworthy.
2. **F (intraday 0-3DTE)** and **G (combinations)** stay deferred with cause (F = thin single-regime
   intraday data → n-guard risk; G needs ≥5 validated bases, have 0).
3. If continuing Layer-1, move OFF price-derived signals (now well-covered/null) toward
   options-structure (C; needs IV history) or event-drift (D; needs FOMC/CPI calendars — a known-unknown).

## Known-unknowns added
VIX/term regime overlay · macro-event calendars · Layer-2 robustness (NBBO-skip ~55–60%, needs CI) ·
C-category IV history.
