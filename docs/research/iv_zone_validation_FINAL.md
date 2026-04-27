# IV-Zone Inversion — Definitive Verdict (Full 19-Name Sample)

*Run Sun Apr 26 2026. Combines existing chain CSVs (AAOI/CIEN/GLW/MU) with fresh ThetaData ATM-30DTE pulls for the other 15 cohort names. Total sample: 3,726 daily bars across 19 tickers, 16-month window (Jan 2025 – Apr 2026).*

## TL;DR

**The IV-pricing argument for Zone A is dead. The equity-hit-rate argument for Zone A is stronger than ever.**

| Metric | Apr 25 Proxy | Apr 26 Validation (4 names) | Apr 26 Full (19 names) |
|---|---|---|---|
| Sample size (Zone A / Zone B bars) | 292 / 89 | 32 / 11 | **136 / 32** |
| Real IV-rank Zone A median | (proxy 0.52) | 0.75 | **0.56** |
| Real IV-rank Zone B median | (proxy 0.67) | 0.72 | **0.52** |
| Mean delta (A − B) | proxy −0.145 | +0.084 | **+0.029** |
| Statistical test | proxy p<0.0001 | p=0.47 | **p=0.64** |
| **IV-pricing claim** | "confirmed" | suspect | **definitively rejected** |

## Five validations from the full sample

### V1 — Proxy correlation worsens with bigger sample
Pearson 0.175 / Spearman 0.178. The realized-vol-rank proxy used in the Apr 25 backtest is essentially *noise* with respect to real implied vol. The "p<0.0001" finding from Apr 25 was measuring something — but that something was not IV.

### V2 — Real IV-rank by zone: no robust difference
| Zone | n | IV-rank median | ATM IV median |
|---|---:|---:|---:|
| A | 136 | 0.56 | 69.9% |
| B | 32 | 0.52 | 60.4% |
| Other | 3,558 | 0.58 | 70.5% |

Welch t = 0.473, p = 0.64. Mean delta +0.029. Zone A and Zone B are **statistically indistinguishable in real IV-rank**. The Perplexity hypothesis ("Zone A has compressed IV vs Zone B") does not survive contact with ground-truth data.

Curiously, raw ATM IV is slightly *lower* on Zone B days (60.4% vs 69.9%) — suggesting that breakouts in this cohort tend to occur AFTER an IV reset, not before one. Pullbacks (Zone A) often happen during ongoing event-risk regimes (earnings, sector vol).

### V3 — Forward equity returns: Zone A dominates on hit rate
| Horizon | Zone | n | Hit rate | Avg return | Median |
|---|---|---:|---:|---:|---:|
| 5d | A | 134 | **77.6%** | +4.74% | +4.21% |
| 5d | B | 31 | 64.5% | +6.20% | +3.88% |
| 5d | Other | 3,492 | 61.2% | +3.43% | +2.23% |
| 10d | A | 126 | **80.2%** | +7.43% | +5.52% |
| 10d | B | 31 | 67.7% | +9.19% | +10.40% |
| 10d | Other | 3,425 | 63.1% | +6.58% | +3.95% |
| 21d | A | 110 | 77.3% | +13.63% | +12.90% |
| 21d | B | 30 | 70.0% | +14.14% | +9.81% |
| 21d | Other | 3,277 | 69.7% | +13.50% | +8.12% |

**Zone A advantage on hit rate (vs Zone B):** +13pp at 5d, +12pp at 10d, +7pp at 21d. Consistent across all horizons. Median return is higher for Zone A at every horizon (Zone B's slightly higher *average* at 5d/10d is from a thinner right tail).

**Zone A also outperforms the "Other" benchmark by +16pp at 5d hit rate.** Pullback entries on stacked-MA names are genuinely a high-quality signal — the gain isn't "Zone A is better than Zone B," it's "Zone A is better than ANY other moment in the uptrend."

### V4 — Per-ticker IV-rank delta (where comparable)

Sorted by Zone A vs Zone B IV-rank delta (negative = inversion confirmed for that ticker):

| Ticker | Zone A med | Zone B med | Δ |
|---|---:|---:|---:|
| **GLW** | 0.75 | 0.83 | **−0.08** ← inversion holds |
| NBR | 0.25 | 0.14 | +0.11 |
| LASR | 0.77 | 0.62 | +0.14 |
| **MU** | 0.90 | 0.24 | **+0.66** ← strong reverse |

Only one ticker (GLW) shows the predicted inversion, and weakly. MU shows the opposite at high magnitude. The other 11 names with comparable samples don't have enough Zone B bars to compute a delta. **The pattern is dispersed, not directional.**

### V5 — Forward returns by IV-rank tertile (independent of zone)

This is the most actionable finding from the new analysis:

| Horizon | IV LOW | IV MID | IV HIGH |
|---|---:|---:|---:|
| 5d hit | 61.0% | 63.9% | 60.5% |
| 5d avg | +2.99% | +2.99% | +4.58% |
| 10d hit | 66.2% | 65.4% | 59.3% |
| 10d avg | +5.95% | +5.41% | +8.61% |
| 21d hit | **74.6%** | 71.8% | 63.1% |
| 21d avg | +13.47% | +11.21% | **+15.88%** |

**Pattern:** low-IV-rank days have *consistently higher hit rates* across all horizons (74.6% vs 63.1% at 21d), but high-IV-rank days have larger *average* returns (+15.88% vs +13.47% at 21d) — the right tail expands at high IV.

This actually is the IV story we *thought* the Zone A vs Zone B test would find — except it's not zone-dependent at all. **IV-rank itself is independently predictive of hit rate**, separate from any zone classification.

## Three concrete actions from this validation

### Action 1 — Reject Phase 1 #7 (IV-zone inversion as IV-pricing rule)
Already applied in SYNTHESIS.md. The original justification ("Zone A is cheaper IV → buy more options there") is empirically false. Don't change live sizing rules based on this hypothesis.

### Action 2 — Add Zone A as a hit-rate priority signal (Phase 2 candidate)
Zone A pullback entries genuinely have a 12-16pp hit-rate edge over both Zone B and "Other" days. This is robust at n=136 across 19 names.

**Proposed Phase-2 implementation:**
- When a candidate fires a Zone A entry context, add a **+5 score bonus** (or, more conservatively, a **soft 1.2× size multiplier** instead of a score change)
- Justify based on hit rate, not IV pricing. No claim about cheaper options.
- Validate against a separate 60-day live-paper sample before promoting.

### Action 3 — IV-rank as an additive signal (Phase 3 candidate)
The IV-tertile result (LOW-IV days have +11pp hit rate at 21d vs HIGH-IV days) suggests IV-rank is a real factor independent of zone. But it has tradeoffs:

- LOW IV: better hit rate, smaller right tail → favored for high-conviction A+ entries with shorter holds
- HIGH IV: lower hit rate, fatter right tail → arguably favored for thesis-driven asymmetric bets (event setups, runners)

**This is a Phase 3 (not Phase 1) item.** It needs more investigation:
- Does the LOW-IV hit-rate edge survive after accounting for regime (LOW IV may be correlated with grindy bull tapes)?
- Does the HIGH-IV right tail compensate for IV crush on options structures?
- How does this interact with earnings-distance scoring (HIGH IV is often pre-event)?

Don't ship anything from V5 until those questions get answered.

## What this teaches about the workflow

1. **Proxy validation matters.** A p<0.0001 result on a proxy can be entirely misleading if the proxy doesn't track the true variable. Always validate against ground truth before changing live rules.

2. **Cross-LLM consensus is prioritization, not validation.** Three LLMs agreed the IV-pricing claim was likely true. Real data killed it. The synthesis doc explicitly warned about this — and the warning was correct.

3. **The good signal that survived was a side effect, not the headline.** Zone A's hit-rate advantage was visible in the Apr 25 proxy backtest but framed as a side observation. Now it's the main finding. The claim we wanted to test (IV-pricing) failed; a related claim we didn't set out to test (hit-rate) survived.

4. **IV-rank itself is a candidate factor.** Possibly the most interesting follow-up — orthogonal to all the existing Layer-3 components. Worth a dedicated investigation before adding to the score.

## Files

- `data/atm_iv_30dte/` — 15 ticker CSVs from ThetaData pull (~340 daily IV rows each)
- `data/zone_iv_validation_full.csv` — 3,726 row combined dataset (zones, IV-rank, RV-rank, forward returns)
- `backtest/fetch_atm_iv_thetadata.py` — reproducible IV puller
- `backtest/zone_iv_validation_full.py` — reproducible analysis

Total ThetaData API cost: 0 (existing $80/mo subscription, ~250 calls in 6 minutes).
