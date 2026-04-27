# Phase 1 — Shipped Sun Apr 26 2026

Cross-LLM-consensus changes from `SYNTHESIS.md`. All five high-confidence items shipped as opt-in helpers; full backward compat preserved for existing callers. Live integration into `signals.py` / `mir_rules.py` is the follow-up.

## What shipped

| # | Item | File | Status |
|---|---|---|---|
| 1 | Breadth gate (% above 200d MA) | [server/regime_breadth.py](../../../server/regime_breadth.py) | ✅ live, current reading **61.31% → FULL_BULL** |
| 2 | Bayesian shrinkage on per-ticker rates | [backtest/shrinkage.py](../../../backtest/shrinkage.py) | ✅ helpers + wired into `kelly_size()` |
| 3 | Kelly input clipping [WR 45-65, payoff 0.8-2.5] | [backtest/shrinkage.py](../../../backtest/shrinkage.py) | ✅ same module as #2 |
| 4 | ATR-based hard stop (2.5×ATR, capped -12%) | [backtest/discipline.py](../../../backtest/discipline.py) | ✅ `atr_based_stop()` helper |
| 5 | B+ → ½ size (was ⅔) | [backtest/discipline.py](../../../backtest/discipline.py) | ✅ `grade_size_modifier()` helper |
| 6 | Composite circuit breaker | — | ⏸ deferred per Perplexity follow-up (wait ≥10 trading days post-#1-5 live) |
| 7 | IV-zone inversion for options Layer-5 | — | ⏸ deferred until ThetaData ATM-IV validates the realized-vol proxy |

## How to use the new helpers

### Breadth gate
```python
from server.regime_breadth import get_breadth_regime, regime_allows_grade

regime = get_breadth_regime()
# {'date': '2026-04-26', 'pct_above_200d': 61.31, 'regime': 'FULL_BULL',
#  'cohort_cap_pct': 8.0, 'allowed_grades': ['A', 'A+', 'B', 'B+'], ...}

if regime["regime"] == "BEAR":
    return  # no new longs
if not regime_allows_grade(regime, signal_grade):
    return  # B/B+ blocked in TRANSITIONAL regime
```

### Shrinkage + clipping (opt-in via `kelly_size`)
```python
from backtest.discipline import kelly_size

result = kelly_size(
    win_rate=80, tier="PROVEN", avg_win=46, avg_loss=78,
    n_trades=15,                # required for shrinkage
    pooled_win_rate=60,          # cohort baseline
    pooled_payoff=0.6,           # cohort baseline
    shrinkage=True,              # turn on Phase 1 #2
    clip_inputs=True,            # turn on Phase 1 #3
)
# result includes 'effective_win_rate', 'effective_payoff', 'debias_reason'
# Call without shrinkage/clip flags → identical behavior as before.
```

### ATR stop
```python
from backtest.discipline import atr_based_stop

stop = atr_based_stop(entry_price=9.31, atr=0.45, direction="BULL")
# {'stop_price': 8.19, 'stop_pct': -12.0, 'binding': 'CAP', ...}
```

### Grade size modifier
```python
from backtest.discipline import grade_size_modifier

base_size_pct = kelly_size(...)["size_pct"]
final_size_pct = base_size_pct * grade_size_modifier(signal_grade)
# A+ / A → 1.0, B+ → 0.5 (was 0.667), B → 0.33, C/D → 0
```

## What's deferred and why

### #6 Composite circuit breaker
Perplexity follow-up (Apr 25 evening) flagged win-rate-only as a noisy control metric — a momentum strategy can string together 4-of-7 small losses right before a runner. Pausing on win-rate alone would sideline you at the worst time.

**Defined design when ready:**
```
pause new entries if:
    rolling_10d_win_rate < 45%
    AND rolling_10d_profit_factor < 1.0
```

The `AND` between win-rate and profit factor avoids the false-positive mode. Will ship after items #1-5 have been live for ≥10 trading days so we have real per-grade outcome data feeding the rolling metrics.

### #7 IV-zone inversion
Apr 25 backtest ([docs/research/iv_zone_inversion_results.md](../../research/iv_zone_inversion_results.md)) confirmed Perplexity's directional claim with realized-vol-rank as proxy: Zone B has ~14.5pp higher vol-rank than Zone A (Welch t-test p<0.0001). For ≤14d options this means Zone A entries cost ~15-25% less in premium AND have higher 5d/10d hit rate.

But realized vol is a proxy. Need ThetaData ATM-IV history validation on a 30-50 sample of historical Zone A vs Zone B days before flipping the live sizing rules. **Action item:** schedule the IV-fetch script for next week, then re-validate, then ship the inversion.

## Integration status — LIVE Apr 26

| Item | Status | Wire-in location |
|---|---|---|
| 1. Breadth gate at signal emission | ✅ live | [server/signals.py](../../../server/signals.py) — gates `should_auto_trade` and `should_push` for BULL signals when regime is BEAR/TRANSITIONAL |
| 2. Bayesian shrinkage on Kelly | ✅ live | [server/discipline.py](../../../server/discipline.py) — `compute_kelly_size(shrinkage=True)` is now default. `get_pooled_stats()` cache added with 1h TTL. |
| 3. Kelly input clipping | ✅ live | Same module — `clip_inputs=True` is now default |
| 4. ATR stop | ✅ already shipped | [server/signals.py](../../../server/signals.py) `_dynamic_stop_distance_pct` was already ATR-based with DTE scaling and 8% cap — *more* conservative than the Phase 1 spec (12% cap). The new `atr_based_stop()` helper is for backtest contexts that don't share the live snapshot DB. |
| 5. Grade size multiplier (B+ → ½) | ✅ live | [server/paper_trading.py](../../../server/paper_trading.py) — `grade_size_modifier()` applied to Kelly target_dollars before contract count |

All integrations preserve fail-open behavior: if any helper module errors, the legacy logic runs (no signals are silently dropped).

### What ships vs what was already there

The `_dynamic_stop_distance_pct` discovery is the most important: the codebase had already implemented an *better* version of Phase 1 #4 than the cross-LLM consensus proposed. The "9.1% fixed stop" referenced in the original prompt to the LLMs was an aspirational/Stockbee number that wasn't actually live. The real production stops are ATR + DTE + IV scaled with an 8% cap. The Phase 1 helper is now redundant in production paths but still useful for backtest scripts.

## Validation status

| Helper | Smoke-tested | Backward compat | Live integration |
|---|---|---|---|
| `regime_breadth.compute_pct_above_200d()` | ✅ returns 61.31% / FULL_BULL | n/a (new module) | pending |
| `shrinkage.shrunk_win_rate()` | ✅ 5 sample sizes verified | n/a (new module) | pending |
| `shrinkage.clip_kelly_inputs()` | ✅ 4 cases verified | n/a (new module) | pending |
| `discipline.kelly_size()` w/ new args | ✅ 3 calls compared | ✅ existing call signature unchanged | pending |
| `discipline.atr_based_stop()` | ✅ 5 instrument types verified (low-ATR, mid-ATR, high-ATR, gap-ATR, bear) | n/a (new function) | pending |
| `discipline.grade_size_modifier()` | ✅ all 6 grades + edge cases | n/a (new function) | pending |

## Universe maintenance follow-up

While computing today's breadth, 6 tickers in the universe were flagged as delisted by yfinance: `JWN, WBA, X, WRK, K, WISH`. These should be removed from `server/tickers.py` in a separate cleanup PR (low priority — they're already excluded from breadth math automatically).
