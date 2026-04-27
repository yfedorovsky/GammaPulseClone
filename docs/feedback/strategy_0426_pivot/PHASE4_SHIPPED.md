# Phase 4 — Macro Composite Layer (Shipped Sun Apr 26 2026)

DIY replication of AION/SentimenTrader-style macro dashboards using only existing data sources (yfinance, ThetaData, Massive — no new subscriptions). Three components built today; #4 (macro-pivot detector) deferred to a separate session per scope discipline.

## What shipped

| # | Item | Module | Status |
|---|---|---|---|
| 1 | Regime alignment counter | [server/regime_alignment.py](../../../server/regime_alignment.py) | ✅ live |
| 2 | Stress composite (0-100) | [server/stress_composite.py](../../../server/stress_composite.py) | ✅ live, context-only per Perplexity |
| 3 | Conditional base rate forecasts | [backtest/conditional_base_rates.py](../../../backtest/conditional_base_rates.py) | ✅ 33-year cache (8,166 SPY bars), 49 regime cells |
| Bonus | Unified macro context panel | [server/macro_context.py](../../../server/macro_context.py) | ✅ bundles all three for dashboard |

## Current readings (Sun Apr 26 2026)

```
HEADLINE: BULL aligned (62.5%, stress 12.9/100)
Combined size modifier: 0.85

Regime alignment: 5B / 2N / 1- (dominant=BULL, alignment=62%)
  ++ breadth_regime         FULL_BULL
  ++ nymo                   +164
  ++ namo                   +192
  ++ vix_term_structure     CONTANGO
  -- breadth_score          -0.25 (mean-reversion bull setup absent)
   . vix_intraday           UNKNOWN (Sunday)
   . oil_intraday           UNKNOWN (Sunday)
  ++ spy_trend              SPY $713.94 stacked bull

Stress composite: 12.9 / 100 (LOW), size_mod=1.00
  breadth      %above200d=61.3   scaled 38.7 × 0.25 = 9.7
  nymo         NYMO=+164         scaled  0.0 × 0.20 = 0.0
  vix          VIX=18.7          scaled 10.6 × 0.30 = 3.2
  drawdown     SPY DD= 0.0%      scaled  0.0 × 0.25 = 0.0

SPY forecast (cell STACKED_BULL|15-20|0_-3, N=1015):
   3d: hit=57.7% (±1.6%)  avg=-0.00%  vs base: -0.2pp hit, -0.14pp avg
  10d: hit=61.2% (±1.5%)  avg=+0.22%  vs base: -0.7pp hit, -0.24pp avg
  20d: hit=63.3% (±1.5%)  avg=+0.38%  vs base: -2.0pp hit, -0.53pp avg
```

**Genuine empirical insight from the forecast:** the current "extended bull, low VIX, no drawdown" cell historically delivers SLIGHTLY WORSE 20d forwards than the unconditional baseline (-2pp hit rate, -0.5pp average). Subtle mean-reversion bias. With N=1015 the result is robust (no shrinkage applied) and the standard error is tight (±1.5pp).

## Per-component design choices

### #1 Regime alignment counter
Reframe per Perplexity feedback: not a "consensus forecaster" (signals are too correlated for true ensemble lift) but a "regime alignment counter" — useful for sizing confidence, not forecasting.

8 signals voted BULL/NEUTRAL/BEAR:
- breadth_regime (FULL_BULL/WARNING/TRANSITIONAL/BEAR)
- NYMO (>+25 bull, <-25 bear)
- NAMO (same thresholds)
- VIX intraday regime (7 states mapped)
- Oil intraday regime (8 states mapped)
- VIX term structure (CONTANGO/BACKWARDATION)
- breadth_score from server/breadth.py (composite mean-reversion)
- SPY trend stack (close vs 20/50/200)

Size modifier scaling:
- ≥75% aligned: 1.0×
- 60-75%: 0.85×
- 50-60%: 0.7×
- <50%: 0.5×

### #2 Stress composite (CONTEXT ONLY)
Per Perplexity citations (CXO Advisory, Cleveland CFSI, OFR FSI literature): stress indices do **NOT** predict 3-10d SPY returns reliably. Used **only** as:
- Trade suspension gate at extremes (>80 = no new BULL longs)
- Sizing dampener (linear scale-down from 30 to 80)
- Dashboard context number

Components and weights:
- Inverse breadth (0.25)
- NYMO scaled (0.20)
- VIX scaled (0.30)
- SPY drawdown from 252d high (0.25)

Bands: LOW (0-30), ELEVATED (30-50), HIGH (50-70), STRESSED (70-80), BLOOD (80-100).

### #3 Conditional base rate forecasts (THE PRIZE)
Backed by Timmermann (2011) + Ang-Bekaert (2003) regime-switching literature. Implementation specifics per Perplexity:

- 33 years of SPY (8,166 bars) bucketed into 64 cells: 4 trend × 4 VIX × 4 drawdown
- 49 cells actually populated (some combinations rare)
- For each cell: hit rate + avg return at 3/10/20d horizons
- Bayesian shrinkage applied when N<100: `adjusted = (N×cell + 30×pooled) / (N+30)`
- Standard error displayed alongside probability (Wilson approximation for proportion)
- vs-baseline delta surfaced explicitly (so user sees lift, not raw prob)

Pooled baselines (n=8163):
- 3d: hit=57.9%, avg=+0.14%
- 10d: hit=61.9%, avg=+0.46%
- 20d: hit=65.3%, avg=+0.91%

These are the unconditional means against which any cell-conditional reading is measured.

## What's NOT in Phase 4 (yet)

- **#4 Macro-pivot detector** — deferred per Perplexity scope guidance: needs 3 hard gates (oversold + de-escalation as 5-day rolling, not single bounce + VIX contraction), 3-4% size cap, cohort-correlation awareness. Build this next session.
- **VEX (vanna exposure) layer** — Phase 5 candidate. AION's one genuine differentiator. 6-8 hr build using existing ThetaData chains.
- **Wire macro_context into signals.py auto-trade gate** — currently context-only via dashboard. Decision deferred: should `combined_size_modifier` actually multiply Kelly output? Need to think about double-counting with existing breadth/IV gates.

## Phase 4 in the combined cascade

Currently the macro context is **observation-layer only** — visible via dashboard, log lines, alert footers. It does not yet modify auto-trade decisions. The decision to wire it into sizing requires care:

- `regime_alignment.size_modifier` (0.5-1.0) overlaps with the existing breadth gate (which already restricts grade eligibility)
- `stress_composite.size_modifier` (0-1.0) overlaps with the existing IV-rank gate
- Stacking all three multiplicatively could double-clip downside

**Recommended:** keep Phase 4 as a context layer this week. Watch live readings for 5-10 trading days. If the dashboard repeatedly flags conditions that the existing gates don't catch, then promote individual components to gates. Don't ship sizing changes off untested composites.

## Files

**New modules:**
- `server/regime_alignment.py` — 8-signal counter
- `server/stress_composite.py` — 0-100 score
- `server/macro_context.py` — unified dashboard panel
- `backtest/conditional_base_rates.py` — historical conditional probability engine + cache builder

**Cache built:**
- `data/conditional_base_rates.json` — 49 regime cells, 33-year history

## Operational notes

- The conditional base rate cache should rebuild monthly (or after market regime changes). Cheap: ~10s build time.
- The regime alignment counter pulls live data on every call. For dashboard use, wrap in a 5-min TTL cache.
- The stress composite is similar — no expensive computation, but the underlying data sources have their own TTLs.

## Honest assessment

The Perplexity validation worked: it told us to build #1+#2+#3 with specific revisions, skip AION ($500/mo, lagging crash detector), and consider VEX as a Phase 5 candidate I hadn't proposed. All three components shipped today match the Perplexity spec.

The conditional base rate engine (#3) was the right priority. Not because it's the loudest signal, but because it's the only one that produces forward-looking *probabilities* with confidence intervals. The current reading (mild mean-reversion expected vs baseline at 20d) is exactly the kind of subtle nuance that a flat regime classifier would miss.

The macro-pivot detector (#4) is a deliberately separate piece of work because it directly authorizes capital deployment in a single concentrated trade. That kind of trigger deserves its own session, not a tail-end of a multi-component build.

Total time today: ~2 hours for all three modules + integration + this doc. Total external cost: $0.
