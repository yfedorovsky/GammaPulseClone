# Oil Regime Backtest — External Validation Request

**Date:** April 16, 2026
**Requester:** GammaPulse options trading system (retail, $20K paper account)
**Reviewers requested:** Grok, ChatGPT, Perplexity, Gemini
**Goal:** Validate whether the proposed "USO intraday regime" signal has real predictive edge or is noise/overfit.

---

## Background and Motivation

GammaPulse is a systematic options trading platform that already uses a **VIX intraday regime** signal with the following backtest-validated thresholds (1yr, 251 trading days):

- `VIX_BULL_COMPRESS` (VIX open <20, closes -3%+ intraday): **80.3% SPY OC win rate**
- `VIX_ELEVATED_COMP` (VIX 20-25, declining): **87.5% WR**
- `VIX_LOW_RISING` (VIX open <20, rises +3%+): **13.2% WR**
- `VIX_SPIKE` (VIX >25 rising): **20% WR**
- Baseline (all days): 43.2% WR

That signal is wired into:
- Runner tracker Day 1 scoring (+/- 2 to /20 score)
- Scalp alerts (disables mean-reversion SELL_POP on bull compress days)
- Swings tab regime badge

**Now we're asking**: can we build an analogous **oil spike regime** to catch geopolitical risk-off events (Hormuz/Iran, Houthi attacks, tanker incidents)?

**Hypothesis**: Days where USO (WTI crude ETF) spikes +4%+ intraday signal geopolitical risk-off that drags SPY down same-day, giving us a 30-60 min head start on the equity sell-off cascade.

---

## Methodology

### Data
- **Source**: Tradier REST API, daily OHLC bars
- **Tickers**: USO (WTI crude ETF), SPY (S&P 500 ETF), XLE (Energy Select Sector SPDR), BNO (Brent crude ETF)
- **Why daily only**: Tradier's `/markets/timesales` endpoint returns empty for USO/VIX intraday (calculated/composite nature), so we use daily OHLC as a proxy for intraday classification (open → close direction)
- **Universe**: All US equity trading days in lookback window
- **Script**: `scripts/backtest_oil_regime.py` (attached at end)

### Regime Classification

Daily % change = (USO close − USO open) / USO open × 100

| Regime | Threshold | Interpretation |
|--------|-----------|----------------|
| `OIL_SPIKE` | +4% or more | Geopolitical risk-off event |
| `OIL_UP_MILD` | +2% to +4% | Elevated, early warning |
| `OIL_CALM` | -2% to +2% | Normal |
| `OIL_DOWN_MILD` | -2% to -4% | Bearish oil |
| `OIL_CRASH` | -4% or less | Demand destruction OR deflationary relief |

### Measurements per regime
- Same-day SPY open-to-close %
- Same-day SPY high-low range (volatility)
- Win rate on SPY longs (% of days with positive open-to-close)
- **Next-day SPY open-to-close** (does the market continue or mean-revert?)
- **Next-day SPY overnight gap** (gap from prior close to next open)
- XLE cross-check (did energy sector confirm the oil move?)
- BNO cross-check (did Brent align with WTI — global vs local signal?)

---

## Results — 1-Year Lookback (365 days, 251 trading days)

| Regime | Days | % of Sample | Avg USO% | SPY OC% | SPY Rng% | SPY WR | Next OC% | Next Gap% |
|--------|------|-------------|----------|---------|----------|--------|----------|-----------|
| OIL_SPIKE | 2 | 0.8% | +4.41% | **-0.55%** | 1.24% | **0.0%** | +0.42% | +0.37% |
| OIL_UP_MILD | 15 | 6.0% | +2.62% | **-0.53%** | 1.06% | **13.3%** | -0.07% | +0.09% |
| OIL_CALM | 217 | 86.5% | +0.05% | +0.06% | 0.97% | 53.5% | +0.05% | +0.05% |
| OIL_DOWN_MILD | 14 | 5.6% | -2.59% | +0.12% | 1.29% | 64.3% | -0.02% | +0.40% |
| OIL_CRASH | 3 | 1.2% | -8.33% | +1.14% | 2.00% | **100%** | +0.28% | +0.27% |

**OIL_SPIKE vs OIL_CALM**:
- Same-day SPY OC: **-0.55%** (vs +0.06% baseline, delta −0.61pp)
- Same-day WR: **0.0%** (vs 53.5%, delta −53.5pp)
- Next-day SPY OC: +0.42% (vs +0.05%, +0.38pp) — **spike days bounce next session**

### 1-Year Recent Extreme Days

**OIL_SPIKE days (USO +4%+)**:
| Date | USO | XLE | BNO | SPY OC | SPY Next |
|------|-----|-----|-----|--------|----------|
| 2026-04-08 | +4.64% | +2.42% | +5.21% | -0.06% | +0.75% |
| 2026-03-13 | +4.18% | +0.35% | +4.01% | -1.04% | +0.10% |

**OIL_CRASH days (USO -4%+)**:
| Date | USO | XLE | SPY OC | SPY Next |
|------|-----|-----|--------|----------|
| 2026-03-09 | -12.64% | -0.91% | +1.78% | -0.08% |
| 2026-03-03 | -4.14% | -1.51% | +0.78% | +0.51% |
| 2025-06-23 | -8.22% | -3.74% | +0.86% | +0.41% |

---

## Results — 2-Year Lookback (730 days, 502 trading days)

This matters because the 1-year sample only had **2 OIL_SPIKE days** and **3 OIL_CRASH days** — far too few for confidence. Extending to 2 years nearly doubles the sample and reveals a critical outlier.

| Regime | Days | % of Sample | Avg USO% | SPY OC% | SPY Rng% | SPY WR | Next OC% | Next Gap% |
|--------|------|-------------|----------|---------|----------|--------|----------|-----------|
| OIL_SPIKE | 3 | 0.6% | +6.10% | **+3.36%** | 4.58% | **33.3%** | -0.19% | -0.75% |
| OIL_UP_MILD | 26 | 5.2% | +2.57% | **-0.11%** | 1.16% | **42.3%** | +0.06% | +0.12% |
| OIL_CALM | 446 | 88.8% | -0.01% | +0.01% | 1.03% | 52.9% | -0.00% | +0.04% |
| OIL_DOWN_MILD | 23 | 4.6% | -2.55% | -0.05% | 1.30% | 56.5% | -0.06% | +0.26% |
| OIL_CRASH | 4 | 0.8% | -7.47% | -0.36% | 3.22% | **75.0%** | +3.01% | +0.05% |

### The Critical Outlier

The 2-year sample added **one OIL_SPIKE day that completely flips the signal**:

| Date | USO | XLE | BNO | SPY OC | SPY Next |
|------|-----|-----|-----|--------|----------|
| 2025-04-09 | +9.48% | +9.89% | +8.89% | **+11.18%** | -1.43% |

This is the day **Trump paused reciprocal tariffs for 90 days** ("Liberation Day"), triggering a massive relief rally — everything green, oil +9% AND SPY +11% AND XLE +10% AND BNO +9% together. It inverts the OIL_SPIKE thesis because the oil spike wasn't geopolitical risk-off — it was pure risk-on pricing out deflationary tariff fears. Demand expectations re-priced up, not a supply shock.

Remove that one day, and OIL_SPIKE reverts to the 1-year pattern:
- 2 days, 0% WR, avg SPY -0.55%

### Proposed fix: "Not-a-relief-rally" filter

The core insight from the outlier is that **oil spikes alone are ambiguous** — you need equity/energy co-movement to disambiguate:

| Pattern | Interpretation | What it actually is |
|---------|---------------|---------------------|
| Oil ↑ + SPY ↓ + XLE ↑ | ✅ Classic geopolitical risk-off | What we want to catch (Hormuz, tanker attacks) |
| Oil ↑ + SPY ↑ + XLE ↑ | ❌ Relief rally / demand re-pricing | Liberation Day, trade deal announcements, recession-off |
| Oil ↑ + SPY ↓ + XLE ↓ | ❌ Stagflation fear | Bad data day (oil cost-push) |
| Oil ↓ + SPY ↑ + XLE ↓ | Deflationary bullish | OIL_CRASH rally pattern |

**Refined classification**: `OIL_SPIKE_RISKOFF` requires **USO +4%+ AND SPY red AND XLE not leading the market up**. This would have cleanly excluded April 9, 2025.

The pure `OIL_SPIKE` by USO alone is not the signal — it's just the trigger condition. The risk-off classification requires confirmation from the equity side.

### The OIL_UP_MILD Signal

This is the most statistically meaningful bucket:
- **1-year**: 15 days, 13.3% WR, avg SPY -0.53%
- **2-year**: 26 days, 42.3% WR, avg SPY -0.11%

Baseline WR is 52.9%. The 2-year OIL_UP_MILD edge is **-10.6pp** (not as dramatic as 1-year) but survives on a larger sample.

---

## Proposed System Integration (if validated)

### 1. Live detector
```python
# server/breadth.py (similar to existing get_vix_intraday_regime)
async def get_oil_intraday_regime() -> dict:
    uso_open = daily_bar.open
    uso_current = live_quote
    change_pct = (uso_current - uso_open) / uso_open * 100
    # Return regime + bull/bear bias + backtest WR expectation
```

### 2. Runner tracker score modifier
```python
# Add to _compute_runner_score
if oil_regime == "OIL_SPIKE": score -= 2  # pause new entries
elif oil_regime == "OIL_UP_MILD": score -= 1  # caution
elif oil_regime == "OIL_CRASH": score += 1  # relief rally tailwind
```

### 3. Scalp alert gate
- `OIL_SPIKE` + `OIL_UP_MILD`: disable BUY_DIP and RETEST (long mean-reversion)
- Enable FLOOR_BREAK more aggressively (momentum-with-trend)

### 4. Telegram alert
- Real-time alert on state transition from CALM → ELEVATED → SPIKE
- Give the user 30-60 min head start on the equity sell-off

### 5. Double-confirmation with VIX
- `OIL_SPIKE` + `VIX_LOW_RISING` = high-confidence risk-off
- `OIL_CRASH` + `VIX_BULL_COMPRESS` = high-confidence relief rally

---

## Questions for Review

### Grok (direct/practical trader take)
1. Is the +4% OIL_SPIKE threshold reasonable, or should it be dynamic (e.g., % of 20-day avg range)?
2. Does the April 2025 outlier invalidate the signal, or is it a special case that should be excluded with a "not-a-relief-rally" filter (e.g., skip if XLE + SPY both green on the spike day)?
3. Have you seen real traders use USO as an advance indicator for SPY risk-off, or do they use oil futures (/CL) or sector correlations?
4. What's the practical alpha here — can a retail trader actually react to a 4% USO move fast enough to avoid the SPY sell-off?

### ChatGPT (implementation/engineering)
1. Is the "daily OHLC as intraday proxy" methodology sound? Open-close direction as classifier vs. actual intraday path (which we can't get from Tradier)?
2. Is 3-4 days of OIL_SPIKE over 2 years enough to make a decision? What's the minimum sample size for a regime classification we'd trust in production?
3. How should we handle the confounding XLE/SPY alignment (relief rallies vs. risk-off spikes both produce oil spikes)?
4. Does combining OIL regime with VIX regime multiplicatively (joint probability) or additively make more sense?

### Perplexity (academic / empirical finance)
1. Is there academic evidence on **oil-equity correlation regime-switching**? Specifically, does correlation flip sign based on whether the oil move is supply-driven vs demand-driven?
2. Have studies documented the ~30-60 min lag between oil moves and equity reaction for geopolitical events (i.e., the "head start" we're claiming)?
3. What's the published evidence on short-term equity reaction to Middle East oil shocks (2022 Ukraine invasion, 2023 Hamas attack, 2024 Iran-Israel exchange)?
4. Does the OIL_CRASH bullish result (deflationary relief) have theoretical grounding, or is it a small-sample artifact?

### Gemini (quantitative deep-dive)
1. Power analysis: given the rarity of OIL_SPIKE days (~1% of sample), what confidence interval can we have on the 0% WR finding? Should we require 10+ observations before acting?
2. Collinearity: is USO + XLE + BNO providing marginal information, or are they so correlated that any one is sufficient?
3. **Information Coefficient (IC)** of OIL_UP_MILD (26-day sample) vs VIX_BULL_COMPRESS (61-day sample) — which factor has higher predictive power on a per-observation basis?
4. Transaction cost / acting-on-signal analysis: if we pause runner entries on OIL_UP_MILD, we miss the 42.3% of those days that ARE profitable. Expected value calculation for the "skip vs. trade" decision?

---

## Known Limitations

1. **Small sample size for extreme regimes**: Only 2-4 OIL_SPIKE and OIL_CRASH days in 2 years. Any conclusions are directional, not statistically rigorous.
2. **Daily OHLC ≠ true intraday path**: A stock can have +1% open-to-close while spiking +5% midday then retracing. Our classifier would miss that.
3. **No true geopolitical crisis in window**: The 2024-2026 window did NOT include a major Hormuz closure, large-scale Iran-Israel exchange, or tanker war. The thesis is most useful precisely when such events occur, but we can't backtest what didn't happen.
4. **SPY is the target, not VXX or sector ETFs**: We haven't tested whether oil spikes are better signals for specific sectors (airlines, cruise lines) or vol products (VXX, UVXY) where the correlation might be stronger.
5. **Survivorship**: ETFs (USO especially) have management/rolling costs that distort from pure WTI futures behavior.
6. **2025 April 9 outlier**: One non-geopolitical oil spike day (tariff-pause relief rally) completely flips the 2-year OIL_SPIKE WR from 0% to 33%. Signal is extremely sensitive to regime classification accuracy.

---

## Script Source (scripts/backtest_oil_regime.py)

```python
# Classification logic
def classify_oil_day(uso_open: float, uso_close: float) -> str:
    pct = (uso_close - uso_open) / uso_open * 100
    if pct >= 4.0: return "OIL_SPIKE"
    elif pct >= 2.0: return "OIL_UP_MILD"
    elif pct <= -4.0: return "OIL_CRASH"
    elif pct <= -2.0: return "OIL_DOWN_MILD"
    else: return "OIL_CALM"

# For each trading day:
# - Classify by USO daily OHLC
# - Measure SPY same-day OC%, high-low range, win rate
# - Measure SPY next-day OC%, overnight gap
# - Cross-check with XLE (energy sector) and BNO (Brent)
# - Aggregate by regime → summary table
```

Full script available at `scripts/backtest_oil_regime.py`.

---

## What We're Asking

Help us decide:
1. **Should we ship this into the production system** (live detector, API endpoint, runner/scalp integration), OR is the signal too weak to act on given the small samples?
2. **If yes**, what refinements would make it more robust (thresholds, confirmation rules, regime sub-classification)?
3. **If no**, what would make this signal viable (more data, finer granularity, different target universe, different confirmation method)?

**The VIX regime signal (already in production) was validated with 61 BULL_COMPRESS days across 1 year with 80% WR.** The oil signal here has 26 OIL_UP_MILD days across 2 years with ~42% WR. Is the latter robust enough to deploy, or should we pin it for more data collection?
