# QQQ Pattern Backtest — Comprehensive Findings

**Date:** 2026-06-19
**Scope:** 16 candidate QQQ patterns (13 daily, 3 intraday) pre-registered and run through the shared backtest harness, then the survivors put through adversarial verification.

---

## 1. Data Sources & Method

**Data**
- **Daily:** yfinance QQQ OHLCV, 1999-03-10 → 2026-06-18 (6,862 bars, ~27 years). Spans dot-com top, 2008 GFC, 2020 COVID, 2022 bear, 2023-2026 AI bull.
- **Intraday:** Databento QQQ MBP-1 tick → 5-min RTH bars, 2025-10-30 → 2026-06-18 (159 RTH sessions). **Single-regime, recent-only** — no decade-scale era diversity is possible on this set.
- **Spot/quote cross-checks:** Tradier.

**Method**
- All tests run through the shared `scripts/gex_bt/bt_harness.py` (`H.event_study`, `H.barrier_test`, `H.dist_matched_control`, `H.block_bootstrap_diff`), seeded RNG, 5,000 permutations.
- **Direction-A rule:** a pattern is an EDGE iff the bootstrap **lift 95% CI excludes 0**. "Lift" is the event metric minus the base/control metric.
- **Base controls bull drift.** For every directional event_study the base = **ALL valid bars**, which already embeds QQQ's strong secular uptrend (+0.525% mean 10-day return, ~60-68% up-rate). A signal must beat that drift, not merely be positive. This is the central honesty bar — see §4.
- **Holm correction** applied across all 16 tests (`holm_p`) to control family-wise error from running 16 candidates.
- **Adversarial verification** on every harness-flagged EDGE: independent re-derivation, look-ahead audit (corrupt future bars, causal manual loop), era robustness (calendar thirds / leave-one-era-out / block bootstrap), transaction costs, buy-and-hold confound, and researcher-degrees-of-freedom (threshold/horizon sweeps, leave-one-day/event-out).

---

## 2. Scorecard (sorted by Holm-adjusted p)

| Pattern | Family | n | Primary: event vs base/ctrl | Lift | Raw p | Holm p | Verify | FINAL |
|---|---|---:|---|---:|---:|---:|---|---|
| three_down_bounce | daily | 584 | +0.447% vs +0.056% (fwd1d ret) | **+0.391%** | 0.000 | **0.000** | WEAKENED | **CONDITIONAL** |
| fifty_two_wk_high | daily | 773 | +2.01% vs +3.12% (fwd60d ret) | **−1.115%** | 0.006 | 0.090 | **REFUTED** | **NOISE** |
| intraday_vol_spike | intraday | 41 | +0.098% vs +0.001% (fwd30m ret) | +0.097% | 0.0156 | 0.218 | WEAKENED | **NOISE** |
| bull_flag | daily | 43 | +1.86% vs +0.53% (fwd10d ret) | +1.334% | 0.064 | 0.832 | WEAKENED | **NOISE** |
| rsi2_meanrev (filtered) | daily | 178 | +0.372% vs +0.163% (fwd3d ret) | +0.210% | 0.317 | 1 | — | NULL |
| volume_spike_up | daily | 41 | +0.828% vs +0.267% (fwd5d ret) | +0.561% | 0.284 | 1 | — | NULL |
| gap_continuation | daily | 585 | +0.071% vs +0.267% (fwd5d ret) | −0.196% | 0.147 | 1 | — | NULL |
| inside_day_breakout | daily | 455 | +0.029% vs +0.267% (fwd5d ret) | −0.238% | 0.130 | 1 | — | NULL |
| nr7_breakout | daily | 716 | +0.144% vs +0.267% (fwd5d ret) | −0.123% | 0.306 | 1 | — | NULL |
| falling_wedge | daily | 201 | +0.008% vs +0.525% (fwd10d ret) | −0.517% | 0.110 | 1 | — | NULL |
| bollinger_squeeze | daily | 73 | +0.204% vs +0.525% (fwd10d ret) | −0.321% | 0.556 | 1 | — | NULL |
| ema20_reclaim | daily | 235 | +0.136% vs +0.267% (fwd5d ret) | −0.131% | 0.571 | 1 | — | NULL |
| ema_9_21_cross | daily | 144 | +1.151% vs +1.051% (fwd20d ret) | +0.101% | 0.856 | 1 | — | NULL |
| donchian20_breakout | daily | 864 | 0.640 vs 0.629 (fwd20d win) | ~0.000 | 0.995 | 1 | — | NULL |
| orb_30 | intraday | 108 | 0.296 vs 0.438 (barrier win) | **−0.141** | 0.9997 | 0.9997 | — | NULL (anti-edge) |
| vwap_reclaim | intraday | 502 | +0.006% vs +0.001% (fwd30m ret) | ~0.000 | 0.634 | 1 | — | NULL |

*Negative lift on `fifty_two_wk_high` and `orb_30` means the event UNDERperforms its base/control. Direction-A flags a CI-excludes-0 negative lift as an "EDGE" on the raw run, but a negative-lift long signal is not tradable long; both collapsed under scrutiny (Holm and/or verification).*

---

## 3. What Survives BOTH Holm AND Verification

Be ruthless about this: **of the 16 patterns, exactly ZERO survive as a clean, standalone, tradable edge.**

Four patterns were flagged EDGE on the raw harness run. After Holm correction and adversarial verification:

1. **`three_down_bounce`** — the *only* survivor of Holm (holm_p = 0.000) and the *only* one verification did not REFUTE (verdict WEAKENED). But "WEAKENED" is doing real work: the edge is **era-fragile**. No single horizon is significant in all three calendar eras — the 3-5 day mean-reversion bounce has **decayed to noise in the post-2018 regime** (h3 post-2018 lift +0.00138, CI [−0.0028, +0.0056], p=0.52). Look-ahead clean, survives costs, genuine excess over buy-and-hold on the full sample. **Status: CONDITIONAL** — usable only at the shortest horizon (h1), regime-aware, never assuming the full-sample magnitude.

2. **`fifty_two_wk_high`** — survived neither. Holm p = 0.090 (fails the 0.05 bar) and verification **REFUTED** it. The headline significance was an **overlapping-window artifact**: 60-day forward windows give only ~57 truly independent events, not 773; overlap-honest block bootstrap CI includes 0. The residual sits in one era (2018+) and ~80% is momentum-state drift, not the event. **Status: NOISE.**

3. **`intraday_vol_spike`** — Holm p = 0.218 (fails), verification WEAKENED. The edge lives on a **threshold island** (only at exactly 3.0× volume; 2.0×/3.5× are NULL), an **isolated horizon** (on at k=6 bars, off at k=3/4/5/7), and a **handful of events in one 11-week slice** of a 159-day sample. Leave-one-day-out kills it. **Status: NOISE.**

4. **`bull_flag`** — Holm p = 0.832 (fails badly), verification WEAKENED. n=43 over 27 years; significance is **entirely carried by the pre-2010 dot-com window** (leave-pre-2010-out → lift collapses, p=0.198, NULL). Knob-fragile (retrace <0.50 and pole ≥0.08 are a narrow sweet spot) and horizon-dependent (k=5 NULL). **Status: NOISE.**

**Bottom line: NONE of the 16 is a validated standalone QQQ edge.** One (`three_down_bounce`) is a conditional, regime-gated, short-horizon mean-reversion tilt; the rest are noise once multiplicity, drift, overlap, and era-robustness are honored.

---

## 4. Era-Robustness & the Buy-and-Hold Confound

This is the load-bearing section, because QQQ's 27-year uptrend makes almost any long signal *look* good.

**The drift trap.** QQQ's unconditional base is strongly positive at every horizon (fwd10d +0.525%, fwd60d +3.12%, up-rates 58-68%). A signal that fires "+1.86% on average" sounds bullish until you note the base is already +0.53% — and many of our patterns came in **at or below base**:
- `falling_wedge` breakout (textbook bullish): event +0.008% vs base +0.525% — it *underperforms* the drift.
- `donchian20_breakout`, `ema_9_21_cross`, `fifty_two_wk_high`: forward returns are positive but **less** than just being long. Buying the breakout buys you slightly *less* drift, because breakouts/new highs cluster in extended, late-cycle bars with lower forward expectancy.
- `gap_continuation`, `inside_day_breakout`, `nr7_breakout`, `vwap_reclaim`: all negative-lift or zero — momentum-continuation framings add nothing over passive QQQ.

Using ALL-bar base (not a flat 0%) is what exposes this. Any future QQQ research must keep the drift-laden base; a "positive return" is not a result.

**Era fragility killed every survivor.** Each of the four raw-EDGE patterns failed the "present in all thirds" test:
- `three_down_bounce`: mean-reversion **decayed post-2018** (modern regime NULL at 3-5d).
- `fifty_two_wk_high`: signal only in 2018+; pre-2010 and 2010-2018 CIs include 0 under block bootstrap.
- `bull_flag`: concentrated in **pre-2010 only**; modern era NULL.
- `intraday_vol_spike`: cannot even be era-tested (data is 100% 2025-2026); within-window it lives in one 11-week slice.

**Overlap inflation.** `fifty_two_wk_high` is the cautionary tale: the harness `event_study` resamples i.i.d. *bars*, so 773 overlapping 60-day windows masqueraded as independent (p=0.006). Effective n ≈ 57. **For long-horizon (≥20d) patterns, trust block-bootstrap / non-overlapping CIs over the harness CI.**

---

## 5. Conclusion & Concrete QQQ Recommendation

**Honest verdict:** On 27 years of QQQ daily plus 159 days of 5-min data, **no chart pattern in this set is a standalone predictor that survives multiple-comparison correction, the bull-drift base, era robustness, and overlap-honest CIs simultaneously.** The classic bullish continuation patterns (falling wedge, Donchian/turtle breakout, NR7, inside-day, gap-up, 9/21 cross, 52wk-high, VWAP reclaim, ORB-30) are noise-to-negative once you net out drift — several literally lag passive QQQ. ORB-30 is mildly *anti*-edge (long breakout wins 29.6% vs 43.8% control), hinting a fade variant, but that wasn't pre-registered.

**This ties directly to the session theme:** a pattern is **context, not a standalone predictor** unless it clears this bar — and on QQQ, none did. These shapes should inform/weight a confluence stack (regime, flow, GEX), not fire a detector on their own.

**What deserves a detector vs. noise:**

| Decision | Pattern | Rationale |
|---|---|---|
| **Conditional detector — gated** | `three_down_bounce` | Only validated survivor. Build it as a *short-horizon (1-3 day) mean-reversion tilt*, **gated on regime** (down/correction volatility), **never** as a long-trend signal. Demote/disable in calm bull regimes where it has decayed. Treat as a confluence input (size-down oversold dip-buy), not an autonomous alert. |
| **No detector — noise** | bull_flag, intraday_vol_spike, fifty_two_wk_high, and all other 12 | Fail Holm and/or verification. Do not build, do not alert. If ever revisited, require: out-of-sample (post-2018) confirmation, non-overlapping CIs, and a threshold/horizon stability sweep before any go-live. |
| **Inverted candidate — not validated** | orb_30 (fade) | The −0.141 lift suggests the *fade* of a 30-min OR breakout may carry signal. Pre-register and test the short/fade explicitly before trusting it; current long-breakout rule is a confirmed anti-edge. |

**Operational guardrails for the next QQQ pass:**
1. Keep the ALL-bar (drift-laden) base. Positive ≠ edge.
2. Use block-bootstrap / non-overlapping CIs for any horizon ≥ 20 days.
3. Demand era robustness (all calendar thirds, or explicit regime gating) before promoting anything.
4. Get more intraday history — 159 days is one regime; the intraday "edges" are untestable for robustness.
5. Patterns weight a confluence model; they do not fire alone.
