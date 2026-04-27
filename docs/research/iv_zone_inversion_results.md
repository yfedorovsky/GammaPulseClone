# IV-Zone Inversion Backtest — Results

*Run Sat Apr 25 2026. Tests Perplexity's claim that Zone A entries (pullback to rising EMA) have compressed IV vs Zone B entries (breakout above swing high), making Zone A the better options buyer's entry.*

## Method

For each ticker in the 19-name QM × Minervini cohort, pulled 2y of daily history. For each daily bar in the uptrend regime (Close > SMA50 > SMA200 + rising 50d), classified the bar as:

- **Zone A** (pullback): close within ±2.5% of EMA10, in lower 55% of 20d range, volume ≤ 1.3× 20d avg
- **Zone B** (breakout): close ≥ 99% of 20d high, volume ≥ 1.3× 20d avg
- **Other**: neither

Note: deliberately did NOT restrict to the 7-gate trigger universe — that filter pre-selects extended bars and would exclude most pullbacks by construction. Testing on all uptrend bars gives meaningful sample sizes (292 Zone A vs 89 Zone B).

**IV proxy:** 5-day realized vol annualized, ranked as percentile within trailing 60-day distribution. IV in practice tracks realized vol with elevation — the directional claim ("Zone A has compressed vol vs Zone B") can be validated with realized-vol-rank as a stand-in. A formal validation against ThetaData ATM IV is the next step before sizing changes go live.

## Hypothesis 1 — IV compression at Zone A: CONFIRMED

| Zone | n | rv_rank mean | median | p25 | p75 | rv_5d (annual median) |
|---|---:|---:|---:|---:|---:|---:|
| **Zone A** | 292 | 0.50 | 0.52 | 0.25 | 0.75 | 45.5% |
| **Zone B** | 89 | 0.64 | 0.67 | 0.47 | 0.88 | 55.1% |

**Welch t-test (A vs B vol-rank): t = -4.225, p < 0.0001**

Mean delta: Zone B is +14.5 percentile points higher in realized vol than Zone A. The effect is large and overwhelmingly statistically significant. The IV-compression claim is empirically supported by the proxy.

**Annualized RV translation:** Zone A median ~46% vs Zone B median ~55%. For a typical 30 DTE ATM call, that ~9-vol delta translates roughly to **15-25% higher option premium at Zone B** vs Zone A on the same underlying — a substantial cost penalty for the breakout entry.

## Hypothesis 2 — Forward equity returns by zone

| Horizon | Zone | n | Hit rate | Avg return | Median | p25 | p75 |
|---|---|---:|---:|---:|---:|---:|---:|
| **5d** | A | 290 | **69.7%** | **+4.01%** | +3.12% | -1.12% | +9.31% |
| 5d | B | 88 | 59.1% | +2.91% | +2.76% | -2.06% | +7.46% |
| **10d** | A | 284 | **69.7%** | +6.15% | +4.84% | -1.38% | +13.69% |
| 10d | B | 88 | 63.6% | +6.53% | +3.66% | -2.59% | +13.83% |
| 21d | A | 268 | 66.4% | +10.68% | +6.81% | -4.09% | +24.81% |
| **21d** | B | 88 | 65.9% | **+12.06%** | +10.04% | -2.68% | +20.30% |

**Read:**
- **5-day window:** Zone A wins clearly on both hit rate (70% vs 59%) and average return (+4.0% vs +2.9%). 11 percentage points of hit-rate edge for Zone A.
- **10-day window:** Zone A retains the hit-rate edge (70% vs 64%) but Zone B catches up on average return.
- **21-day window:** Hit rates converge (~66%); Zone B has higher average and median return at the long horizon.

This pattern — Zone A dominates short-horizon, Zone B catches up at long-horizon — is exactly what you'd expect if Zone B entries are "later in the move with more momentum but less time runway."

## Implication for options sizing — INVERSION VALIDATED

For an options buyer, the relevant comparison is not raw equity return but **return net of vol-rank-driven premium cost**.

Vol-rank delta: Zone B costs ~15 percentile points more in IV terms. Translated roughly:

- **5-day options trade:** Zone A wins on equity return (+1.1pp) AND IV cost (~15-20% cheaper premium). **Massive Zone A preference.**
- **10-day options trade:** Equity returns roughly tied; ~15-20% premium savings at Zone A still favors Zone A.
- **21-day options trade:** Zone B wins on equity (+1.4pp) but pays ~15-20% more in premium. Approximately a wash, possibly slight Zone B edge if the +1.4pp equity advantage exceeds the IV cost penalty (depends on strike, DTE, and IV decay path).

**Bottom line:**
- For options trades targeting <14d hold: **Zone A is materially better.** Bigger size at Zone A, smaller (or zero) at Zone B.
- For options trades targeting 21d+ hold: roughly equal expected value; Zone A still slight preference for the IV cushion.

This validates Perplexity's directional claim. The current workflow (more size at Zone B than Zone A) is wrong for options-buyer specifically. **For equity-only positions** the calculus is different — Zone B is fine because there's no premium cost, but for options it inverts.

## Proposed sizing change for options (revision to Layer 5)

| Hold horizon | Current allocation | New allocation |
|---|---|---|
| Options ≤ 14 DTE / short hold | Zone A: ⅓, Zone B: ⅓, Zone C: ⅓ | **Zone A: ½, Zone B: ¼ (only if IV-rank < 50), Zone C: ¼ (only if both above and sector ETF breaking out)** |
| Options 21+ DTE / long hold | Same split | Same split — equity return advantage at Zone B compensates for IV |
| Equity positions | Zone A: ⅓, Zone B: ⅓, Zone C: ⅓ | Unchanged |

The IV-rank gate at Zone B (only add if IV-rank < 50) is Perplexity's recommended safeguard — only chase the breakout if the market hasn't already bid up the premium.

## Caveats

1. **Realized vol is a proxy for implied vol.** They correlate but are not identical. IV embeds forward expectations, event risk, and supply/demand for protection. The directional claim (Zone B vol > Zone A vol) is robust at p<0.0001 in the proxy but the magnitude in IV terms could be smaller or larger than the realized-vol delta suggests. **Phase-1.5 validation:** spot-check 30-50 historical Zone A and Zone B trigger days against ThetaData ATM IV history before sizing changes go live in production.

2. **Sample bias toward bull regime.** The 2-year window covers a generally rising tape. In a 2022-style regime, both zones would underperform; the inversion may not hold the same way.

3. **No transaction-cost modeling.** Bid-ask on options at low-IV-rank (Zone A) days can actually be wider in absolute spread terms because of low daily option volume on the underlying. A live-paper test should track realized fill quality.

4. **Zone B at 21d wins on raw equity by +1.4pp.** Not nothing. Aggressive interpretation: keep Zone B for longer-DTE options (45+ DTE) where IV decay is slower and the equity catch-up matters. Conservative interpretation: cut Zone B for all options regardless of DTE. The empirical evidence supports the conservative call for ≤30 DTE options, the aggressive call for ≥45 DTE.

## Output

381 zone-classified bars: [data/zone_iv_inversion_triggers.csv](../../data/zone_iv_inversion_triggers.csv)

## Next steps

1. **Validate against ThetaData ATM IV history** on a 30-50 sample of Zone A and Zone B days before any sizing changes go live (turn proxy into ground truth).
2. Add the IV-zone inversion to Phase 1 implementation as item #7 (after the 6 consensus changes already queued).
3. Re-run this same backtest in 60 days with live-paper data to confirm the inversion holds out-of-sample.
