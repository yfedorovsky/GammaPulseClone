# IV-Zone Inversion — Ground-Truth IV Validation

*Run Sun Apr 26 2026. Re-runs the IV-zone inversion test using real ATM-30DTE IV from existing chain CSVs (AAOI, CIEN, GLW, MU — 16 months of full chain history with non-null IV). Replaces the realized-vol proxy used in `iv_zone_inversion_results.md` (Apr 25).*

## TL;DR — DO NOT SHIP the IV-zone inversion as a sizing rule

The Apr 25 proxy backtest claimed Zone A entries have meaningfully lower IV than Zone B with p<0.0001. **The real IV data does not support that claim.**

| Metric | Proxy (Apr 25) | Real IV (Apr 26) |
|---|---|---|
| Vol-rank Zone A median | 0.52 | 0.75 |
| Vol-rank Zone B median | 0.67 | 0.72 |
| Mean delta (A − B) | **−0.145** (Zone A lower) | **+0.084** (Zone A HIGHER) |
| Statistical test | t = −4.225, p < 0.0001 | t = +0.739, **p = 0.47 (not significant)** |
| Direction | Inversion confirmed | Direction inverted, NOT significant |

The proxy was directionally WRONG, not just noisy.

## Why the proxy lied

Pearson correlation between 5-day realized-vol-rank (proxy) and real ATM-30DTE IV-rank (ground truth) across 816 daily bars: **+0.25**.

That's a weak correlation. The proxy captures something — volatility *of recent price action* — but that's a different beast from forward-looking implied vol on a 30-DTE option.

Specifically:
- **Zone B (breakout on volume)** does have elevated *trailing* realized vol mechanically (a 4% breakout day is itself an elevated-vol bar). But that doesn't mean the market raises forward IV by an equivalent amount — IV reflects expected future move, not just yesterday's move.
- **Zone A (pullback to EMA)** can occur during periods where IV is high due to embedded event risk (earnings approaching) or persistent realized-vol regimes (post-gap consolidation). Real IV doesn't compress just because price is pulling back to an MA.

In short: realized vol moves with price action; implied vol embeds market-priced expectations. Confusing the two is a textbook category error and we caught it in time.

## The actual data — small sample but clean

Across AAOI / CIEN / GLW / MU, 330 trading days each (Jan 2025 – Apr 2026):

| Zone | n bars | Real IV-rank median | Real ATM IV median |
|---|---:|---:|---:|
| A | 32 | 0.75 | 63.9% |
| B | 11 | 0.72 | 56.8% |
| Other | 773 | 0.60 | 67.6% |

The sample is small for Zone B (11 bars across 4 names × 16 months). That's because high-volume breakout-above-20d-high bars are genuinely rare in this cohort during this period — much rarer than pullbacks. The Zone A sample (32) is more reliable.

Per-ticker breakdown:
- **GLW:** A med 0.75 vs B med 0.83 — slight inversion (A lower) ← consistent with claim
- **MU:** A med 0.90 vs B med 0.24 — STRONG REVERSE (A much higher than B)
- **AAOI / CIEN:** insufficient Zone B bars to compare

MU specifically destroys the average. Memory cycle context: MU has had IV-rank spikes during pullbacks (earnings overhangs) and IV-rank compression during breakouts (post-print clarity). That's the opposite of the proxy assumption.

## Forward returns — the equity-side story still favors Zone A short-horizon

Same 4-name validation universe:

| Horizon | Zone | n | Hit rate | Avg return |
|---|---|---:|---:|---:|
| 5d | A | 32 | **71.9%** | +3.16% |
| 5d | B | 11 | 63.6% | +3.22% |
| 10d | A | 30 | 70.0% | +7.00% |
| 10d | B | 11 | 72.7% | +10.18% |
| 21d | A | 26 | **88.5%** | +19.28% |
| 21d | B | 10 | 80.0% | +15.66% |

Zone A retains a hit-rate edge at 5d (+8pp) and 21d (+8pp). Zone B is fine at 10d. **The case for preferring Zone A on equity terms still has empirical support — just not on IV-pricing terms.**

## What this means for the workflow

### Kill the IV-zone inversion (Phase 1 #7) — do not ship.
The original claim was: "buy more at Zone A because IV is cheaper there." Real IV doesn't support that. Don't change live sizing rules based on a proxy that fails its ground-truth check.

### The Zone A preference can still hold for hit-rate reasons.
Zone A pullback entries have ~8pp higher 5d hit rate than Zone B breakout chases in this small sample. But that's an *equity expectancy* argument, not an *options pricing* argument. If you want to lean into Zone A for options, the justification is "pullback entries have better short-horizon hit rate," not "IV is cheaper there."

### Bigger validation requires more cohort coverage
Only 4 of 19 cohort names have chain data. The 11-bar Zone B sample is too thin for a robust conclusion either way. Two paths to widen the test:

1. **ThetaData live pull** — fetch historical ATM IV via the local terminal for the other 15 cohort names for the same 16-month window. Proper sample size (~150-200 Zone B bars) and proper validation. Estimated work: ~30 minutes of API calls, simple script.
2. **Live observation** — instrument the live signal pipeline to capture Zone classification + real ATM IV-rank at every signal emission for the next 60 days. Real-time ground truth, no historical backfill needed.

Recommendation: do (1) before any sizing change, even an equity-side hit-rate-driven one. The 32-vs-11 sample on 4 names is too small.

## Updated SYNTHESIS.md disposition

Phase 1 #7 (IV-zone inversion) — status changed from "deferred pending validation" to **"validated as wrong; do not ship as IV-cost rule."**

Possible Phase 2 follow-up — the Zone A hit-rate edge for short-horizon entries — needs separate validation on the full 19-name cohort before any sizing change. Not in the same urgency tier as Phase 1 items #1-5.

## Output files

- `data/zone_iv_validation.csv` — 816 daily bars across 4 names with real ATM IV, real IV-rank, proxy RV-rank, zone classification, and forward returns. Ground truth for any further analysis.
- `backtest/zone_iv_validation.py` — reproducible script (re-run any time as chain CSVs grow).

## Honest assessment

The cross-LLM consensus from Apr 25 had this as one of Perplexity's high-confidence recommendations. Perplexity's reasoning was sound in principle (IV does compress in consolidation, expand in breakouts) but the magnitude in this specific cohort and timeframe doesn't match the recommendation.

That's exactly why we validate. The synthesis doc itself flagged this caveat: "convergence is useful for prioritization but is not validation." This is the validation step doing its job.
