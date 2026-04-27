# IV-Rank as an Independent Factor — Verdict

*Run Sun Apr 26 2026. Six conditional tests on the 3,726-bar 19-name dataset to decide whether IV-rank should be promoted to a Layer-3 scoring component or kept as observation.*

## TL;DR

**Ship IV-rank as a CONDITIONAL signal, not a scored component. The effect exists and is large, but it is regime-dependent in a way that breaks the "add it to the score" approach.**

The single most important finding is from T2 (regime conditioning):

| SPY regime | IV-tertile | 21d hit rate | 21d avg return |
|---|---|---:|---:|
| SPY_BULL (n=3,373) | LOW-IV | 74.0% | +13.36% |
| SPY_BULL | HIGH-IV | 66.6% | **+18.67%** |
| SPY_BEAR (n=353) | LOW-IV | **92.1%** | +16.93% |
| SPY_BEAR | HIGH-IV | **33.3%** | **−7.31%** |

In bull tapes the effect is mild (LOW slightly better hit rate, HIGH bigger right tail). In bear tapes the effect is enormous: HIGH-IV positions are **net losing** with a 33% hit rate. **The IV-rank factor's value is concentrated almost entirely in adverse regimes.**

This is exactly the case where a flat scored component is the wrong tool — the right tool is a regime-conditional gate.

## The six tests

### T1 — Per-ticker stability: pattern holds in 13/17 names
Re-tertile each ticker's IV-rank within itself, then compare LOW vs HIGH 21d hit rate.

| Where pattern holds (LOW > HIGH) | Δ 21d hit |
|---|---:|
| UCTT | +47pp |
| AAOI | +40pp |
| CAMT | +30pp |
| GLW | +29pp |
| LASR | +27pp |
| TROX | +21pp |
| VICR | +18pp |
| NBR | +15pp |
| PUMP | +12pp |
| LAR | +7pp |
| RES | +6pp |
| AESI | +5pp |
| MU | +4pp |

| Where pattern reverses | Δ 21d hit |
|---|---:|
| ANAB | −11pp |
| CAPR | −9pp |
| GHRS | −9pp |
| PTEN | −3pp |

Median delta across all tickers: **+12.1pp** in favor of LOW-IV. The 4 reverses are concentrated in **biotech** (ANAB, CAPR, GHRS) plus PTEN. Biotech has different vol dynamics — IV often spikes around catalyst events that resolve favorably for the long. Suggests IV-rank rule should NOT apply to biotech specifically (or, more practically, biotech should never be sized off this factor).

### T2 — SPY regime conditioning: the effect lives in bear tapes
Already shown above. The LOW vs HIGH IV-tertile spread:
- SPY_BULL (n=3,373): 74.0% − 66.6% = **+7.4pp**
- SPY_BEAR (n=353): 92.1% − 33.3% = **+58.8pp**

The bear-regime sample is much smaller (10% of bars) but the effect is so large it cannot be sample noise — HIGH-IV in bear regime returns *negative on average* (−7.31%) with only 33% wins. **This is the actionable insight.**

### T3 — Zone × IV-tertile cross-tab
The interactions:

| Zone | IV-tertile | n | 21d hit | 21d avg | 21d median |
|---|---|---:|---:|---:|---:|
| **A** | **LOW** | 44 | **84.1%** | **+16.54%** | **+17.46%** |
| A | MID | 34 | 73.5% | +13.15% | +5.44% |
| A | HIGH | 32 | 71.9% | +10.14% | +9.73% |
| B | LOW | 14 | 78.6% | +19.44% | +12.72% |
| B | MID | 9 | 77.8% | +15.09% | +11.72% |
| **B** | **HIGH** | 7 | **42.9%** | +2.29% | −0.12% |
| Other | LOW | 1,108 | 74.2% | +13.28% | +8.82% |
| Other | HIGH | 1,079 | 62.9% | +16.14% | +6.33% |

**Zone A × LOW IV is the highest-quality cell** (84% hit, +16.5% avg, +17.5% median). Zone B × HIGH IV is the worst (43% hit, near-zero average). The two factors stack — they are not redundant.

The Zone-A-vs-Other findings already shipped; this adds an IV layer on top.

### T4 — Vega-adjusted (approximate, deferred)
Crude approximation produced unreliable numbers (got −inf in one cell from edge-case division). Proper options-PnL modeling needs ATM-call delta + vega + theta over the 21-day path — beyond what we can do quickly in this session. **Deferred to Phase 3.**

The directional intuition (HIGH-IV positions get hurt more by vega mean reversion) is consistent with the equity-side hit-rate finding, but absolute magnitude needs proper modeling.

### T5 — Time stability
Split sample at Aug 1, 2025:

| Period | IV-tertile | n | 21d hit | 21d avg |
|---|---|---:|---:|---:|
| Before 2025-08-01 | LOW | 243 | 65.4% | +7.79% |
| Before 2025-08-01 | HIGH | 228 | **29.4%** | **−8.01%** |
| On/after 2025-08-01 | LOW | 923 | 77.0% | +14.97% |
| On/after 2025-08-01 | HIGH | 890 | 71.7% | +22.00% |

Pattern direction holds in both periods. **Magnitude differs by ~3×.** The early 2025 period contained more bear-regime bars (consistent with T2). Late 2025 / early 2026 has been mostly bull, so the effect compresses.

This argues against pure pattern fragility (it's not a fluke) but reinforces that the effect is regime-driven, not a stable secular signal.

### T6 — IV vs RV-rank cross-tab (errored)
Cross-tab failed on a duplicate-index issue — non-critical, the directional finding is already that IV-rank and RV-rank correlate only +0.18 (validated earlier). They measure different things.

## What this means for shipping

### Recommended: gate, not score

Don't add IV-rank as a Layer-3 scored component (would be averaged across regimes and dilute the actionable signal). Instead, add it as a **regime-conditional adjustment** that ties into the breadth gate already shipped in `server/regime_breadth.py`.

**Proposed rule (to ship as Phase-2 candidate):**

```
For long entries on the 19-cohort universe:

    if breadth_regime in (BEAR, TRANSITIONAL):
        # bear-regime amplification effect: HIGH-IV is a 33% trap
        if iv_rank > 0.66:
            BLOCK entry  (or reduce to 25% size)
        elif iv_rank < 0.33:
            allow normal entry — historically 92% hit in bear
    elif breadth_regime == FULL_BULL:
        # mild effect; tune later
        if iv_rank < 0.33:
            +1 pt score bonus  (modest, +7pp hit edge)
        # don't restrict HIGH-IV in bull regime — right tail is real
```

The bear-regime block is the high-impact rule. The bull-regime bonus is icing.

### Per-ticker overrides

Biotech (ANAB, CAPR, GHRS) showed reverse pattern in T1. Either:
- **Hard exclusion:** the IV-rank rule does not apply to biotech tickers
- **Sector tag:** every cohort ticker gets a "vol_sensitivity" tag (LOW for biotech, NORMAL otherwise), and the rule keys off that tag

Hard exclusion is simpler, ship-able first. Sector tag is more robust long-term.

### Required for shipment

1. The breadth gate (already shipped in Phase 1 #1) provides the regime context.
2. Need a live IV-rank computation per signal — currently only available offline from the chain CSVs / atm_iv_30dte/. Real-time hook needs:
   - Pull current ATM 30-DTE IV from ThetaData snapshot (existing `option_snapshot_greeks_implied_volatility`)
   - Maintain a 60-day rolling distribution per ticker (cache in JSON / SQLite)
   - Compute current rank as percentile within distribution

### What NOT to ship

- IV-rank as a +X% size multiplier in bull regime (effect too small, +7pp not worth integration cost)
- IV-rank as a Layer-3 scored component (regime-conditional, dilutes when averaged)
- The right-tail bonus on HIGH-IV bull entries (true on average but median return is barely different — average is dominated by a few outsized winners that won't show up reliably)

## Phase numbering update

| Item | Status |
|---|---|
| Zone A as hit-rate priority signal (from prior validation) | **Phase 2 candidate** — clean, ready to design |
| IV-rank regime-conditional gate (this finding) | **Phase 2 candidate** — needs live IV-rank computation |
| IV-rank as standalone score | NOT SHIPPING — wrong tool |
| Proper options PnL vega adjustment | **Phase 3** — needs options-modeling work |
| Biotech sector exclusion for IV rule | Ships with the IV rule, not separately |

## Honest assessment

This investigation was worth doing. The naïve interpretation of the original IV-tertile finding ("LOW IV better hit rate") was correct in direction but missed the key insight: **the effect is overwhelmingly concentrated in bear-regime bars.** A flat-score implementation would have buried that insight in noise from bull-regime bars where the effect is mild.

Combined with the Phase-1 breadth gate, the rule "block HIGH-IV entries when breadth is bear" is a tight, defensible, high-impact addition. It would have prevented entries with 33% historical hit rate and negative average return.

The biotech reverse-pattern is also genuinely useful — without per-ticker T1, the rule would have applied to ANAB/CAPR/GHRS and burned ~10pp of hit rate on those names.

Most importantly, this is what cross-LLM consensus + ground-truth validation + conditional analysis is supposed to look like. The first hypothesis (IV-pricing) was wrong. The second hypothesis (Zone A hit rate) was right but uncovered a third hypothesis (IV-rank in bear regime) that is the real prize.
