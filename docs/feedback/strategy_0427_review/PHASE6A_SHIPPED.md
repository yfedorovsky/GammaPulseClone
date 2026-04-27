# Phase 6A.0 + 6A.1 — Shipped Sun Apr 26 Night

The most important shipping session of the project so far. Not because new features were added — because **previously "validated" features were stripped down to what actually survives realistic execution friction**.

## What shipped

| # | Item | Where | Result |
|---|---|---|---|
| 1 | ZBT validation against NYMO backfill | [backtest/zbt_validation.py](../../../backtest/zbt_validation.py) | ✅ 6/7 historical events detected, Apr 2025 ZBT confirmed |
| 2 | Per-name slippage measurement | [backtest/measure_cohort_slippage.py](../../../backtest/measure_cohort_slippage.py) | ✅ 18/19 cohort measured, severe spread/mid distribution exposed |
| 3 | Nonlinear slippage model | [backtest/slippage_model.py](../../../backtest/slippage_model.py) | ✅ IV-rank × moneyness × velocity adjustments per ChatGPT spec |
| 4 | Edge survival kill-threshold test | [backtest/edge_survival_test.py](../../../backtest/edge_survival_test.py) | ✅ exposed phantom alpha across most cohort |
| 5 | IV-rank gate restricted to LIQUID/MEDIUM tier | [server/iv_rank_cache.py](../../../server/iv_rank_cache.py) | ✅ auto-gate now fires on 7 names instead of 16 |
| 6 | Zone-A 1.2× bonus DEMOTED to observation | [server/paper_trading.py](../../../server/paper_trading.py) | ✅ no more size multiplier; logs only |
| 7 | vega_adjusted_pnl reads slippage_lookup | [backtest/vega_adjusted_pnl.py](../../../backtest/vega_adjusted_pnl.py) | ✅ gross + net comparison built-in |

## The cohort tier reality (validated by measurement, not guessed)

| Tier | Names | RT slippage | Auto-gate eligible? |
|---|---|---:|---|
| **LIQUID** | MU, SNDK | 6% | ✅ YES |
| **MEDIUM** | AAOI, CAMT, CIEN, GLW, VICR | 8% | ✅ YES |
| **THIN** | PTEN, UCTT | 14% | ❌ Manual-only |
| **VERY_THIN** | AESI, ANAB, CAPR, LAR, LASR, NBR, PUMP, RES, TROX | 22% | ❌ Manual-only |
| **EXCLUDED (biotech reverse)** | ANAB, CAPR, GHRS | n/a | ❌ Excluded by design |

**CAPR's bid-ask spread is 150% of mid** — ask is 2.5× bid. RES is 133%. NBR 89%. ANAB 78%. These names cannot be auto-traded for short-DTE OTM options without bleeding 20-50% per round-trip.

## Edge survival findings

### IV-rank gate's claimed "+11pp BEAR edge"
- Tested against all 16 non-biotech cohort names at HIGH IV-rank × 5% OTM (where gate fires)
- **0 SHIP / 2 DEMOTE / 14 KILL**
- Even at ATM-only restriction: 0 SHIP / 7 DEMOTE / 9 KILL

### Zone-A 1.2× bonus's claimed "+13pp 5d hit-rate edge"
- Tested at ATM × neutral IV (best-case conditions)
- **0 SHIP / 2 DEMOTE / 17 KILL**
- The hit-rate edge translates to ~6.5% PnL edge on options, eaten by 8-22% slippage

### Reconciliation: gate is DEFENSIVE not OFFENSIVE

The vega-PnL re-run with slippage shows the gate's REAL value:

| Position | Median PnL (gross) | Median PnL (net of slippage) |
|---|---:|---:|
| BEAR + HIGH-IV (blocked) | -62.7% | **-80.3%** (disaster prevention) |
| BEAR + LOW-IV (passed) | +23.3% | +9.0% (barely positive) |
| BULL + HIGH-IV | +10.5% | **-12.1%** (flipped negative!) |
| BULL + LOW-IV | +93.9% | +81.2% |

The gate prevents -80% bleeders, NOT captures +11pp edge. Reframe is critical for honesty.

**New finding:** BULL + HIGH-IV trades flip from +10.5% to -12.1% under slippage. The gate currently does NOT block in FULL_BULL — that may need to change. Add to Phase 6 backlog as candidate.

## Production behavior changes (effective Monday market open)

1. **Auto-trade fires on 7 cohort names** (down from 16):
   - MU, SNDK (liquid, full conviction)
   - AAOI, CAMT, CIEN, GLW, VICR (medium, normal sizing)

2. **9 cohort names are now manual-entry only** for IV-rank-gated signals:
   - PTEN, UCTT (thin)
   - AESI, LAR, LASR, NBR, PUMP, RES, TROX (very thin)
   - System logs the signal but does not auto-execute

3. **Zone-A bonus is observational** — no size multiplier, just dashboard flag

4. **All future backtests use slippage_lookup** — no more "validated" claims without friction modeling

## Files added/modified

**New modules:**
- `backtest/slippage_model.py` — nonlinear lookup + kill-threshold check
- `backtest/zbt_validation.py` — ZBT/Whaley historical validation
- `backtest/edge_survival_test.py` — kill-threshold check on claimed edges
- `backtest/measure_cohort_slippage.py` — per-name spread measurement

**Modified:**
- `server/iv_rank_cache.py` — added COHORT_MANUAL_ONLY tier; gate restricted
- `server/paper_trading.py` — Zone-A demoted from size mult to observation
- `backtest/vega_adjusted_pnl.py` — applies slippage_lookup; reports gross + net

**Output data:**
- `data/cohort_slippage.json` — per-ticker measured slippage assumptions
- `data/zone_iv_validation_full.csv` — updated with gross + net PnL columns

## Phase 6 status

**6A.0 (foundational validation):** ✅ COMPLETE
**6A.1 (production restriction):** ✅ COMPLETE
**6A.2 (next session):**
- Point-in-time cohort reconstitution (L1)
- 2022 historical replay (with new slippage applied)
- Dynamic James-Stein shrinkage (H3)
- min() sizing semantics (L5)
- Hysteresis dual-threshold (L4)
- Momentum crash indicator (M2)

## Honest assessment

Tonight's work is the most important the project has had. Not because we ADDED capabilities but because we **stripped phantom alpha** from previously-validated components and forced the system into honesty about what survives execution.

The 4-LLM pressure tests (Grok, ChatGPT, Perplexity, Gemini) all warned about slippage. Two follow-up rounds (Gemini + Perplexity on PEAD/Whaley/PFOF specifics, then ChatGPT pressure-test on the synthesis itself) tightened the implementation. The kill-threshold test gave us the data.

**Result: the system is now honest about what it can actually trade profitably.** Half the cohort moved to manual-only, Zone-A bonus removed, IV-gate reframed from offensive edge to defensive disaster filter.

This is the rigor that prevents "looks great in backtest, bleeds in live" from becoming our story. Even though it means fewer auto-trades and tighter scope, it means the trades that DO fire have positive expected value net of friction.

Tomorrow's market open is the live test. We'll see this in action.
