# Grok — Oil Regime Backtest Validation

**Date:** April 16, 2026
**Verdict:** **Don't ship pure form. Ship refined confirmation-gated version as SECONDARY overlay to VIX.**

---

## Executive Summary

> "Directionally interesting and aligns with real macro dynamics, but the edge is too fragile, too rare, and too ambiguous right now for a $20K retail options system that already has a proven VIX regime."

Grok independently verified the backtest via Polygon daily bars 2020-2026 (1,580 trading days) — confirmed our tables exactly. Larger sample shows **only 11 OIL_SPIKE days in 6 years (~0.7%)** — not enough for production confidence when one non-geopolitical outlier flips 2yr WR.

---

## Q1: Is +4% OIL_SPIKE threshold reasonable, or dynamic?

**Reasonable as starting point, but static is sub-optimal.**

- +4% USO captures true tail events (11 in 6 years — exactly the rarity you want)
- But oil volatility isn't constant — static threshold gets stale
- **Better**: dynamic, `USO % change > 2× 20-day ATR` or `>3 std dev of recent daily OC %`
- Adapts to low-vol vs high-vol regimes
- Would have still caught the spikes while reducing false positives in quiet periods

**Recommendation**: Fixed +4% fine for backtest simplicity. Live implementation should use adaptive threshold.

---

## Q2: Does April 2025 outlier invalidate the signal?

**The outlier proves the signal is INCOMPLETE, not invalid.**

2025-04-09 (+9.48% USO / +11.18% SPY / +9.89% XLE / +8.89% BNO) = pure demand re-pricing (tariff pause = risk-on relief).

> "Classic supply-shock risk-off (Hormuz-style) should show oil ↑ + equities ↓ (or at least XLE/SPY divergence)."

**The proposed filter (USO +4% AND SPY red AND XLE not strongly green) is EXACTLY RIGHT** — matches academic literature:
- Supply-driven oil shocks (geopolitical) = negative for equities
- Demand-driven oil moves = positive/neutral for equities

Without the filter: just noise. With it: context-aware risk-off classifier.

**Citation**: [Oil Price Shocks and Equity Returns](https://ideas.repec.org/) literature.

---

## Q3: Do real traders use USO as an advance indicator for SPY?

**Not really USO specifically** — they watch:
- `/CL` (crude futures) — real-time, no ETF roll costs
- Brent futures
- **Oil + VIX together**
- **Oil vs XLE/SPY ratio** (the divergence check)
- **Oil + DXY** (dollar)

Professional desks use /CL because USO has slight lag + roll costs. USO is a **retail-friendly proxy**, not institutional.

**Real alpha in geo events**: news flow + futures reaction giving 15-90 min before SPY fully prices it. The 30-60 min head start claim is defensible IF you have proper futures/news feed, not daily OHLC.

---

## Q4: Practical alpha — can a retail trader react fast enough?

**Yes, but only with live futures/news — not daily OHLC proxy.**

- Tradier limitation (no USO intraday timesales) is the real bottleneck
- 4% USO daily move is obvious by midday → 30-60 min head start on genuine geo shocks
- On 2026 spike days: SPY was already weak same-day → edge not mechanical, it's "oil spiking + equities not confirming = pause longs / favor shorts/vol"
- Retail can monitor /CL on Thinkorswim/TradingView/Twitter news wires
- Execution friction (options liquidity, slippage) on $20K account = need very high conviction

**Bottom line on alpha**: Marginal at best.
- OIL_UP_MILD (104 days in 6yr, SPY WR ~42-53% vs baseline ~53%) = mild negative tilt
- Not comparable to VIX_BULL_COMPRESS (80%+ WR on 61+ days)
- Survives larger samples but **diluted by demand-driven noise**

---

## Ship Recommendation

**NO on current pure form. YES on refined, confirmation-gated version — but as SECONDARY overlay to VIX, not primary driver.**

### Why not ship pure
1. Sample too small for extremes (11 spikes in 6 years)
2. Ambiguity without supply-vs-demand filter (April 9 outlier proves it)
3. VIX regime already covers the high-conviction risk-off bucket

### Refinements that make it viable

**Refined regime** (the proposed split is spot-on):
- `OIL_SPIKE_RISKOFF`: USO +4% AND SPY OC < 0 (or SPY underperforming XLE materially)
- `OIL_DEMAND_RELIEF`: USO +4% AND SPY OC > +1% AND XLE strongly green
- `OIL_UP_MILD`: lighter "caution" flag (-1 score)

**Live implementation** (pseudocode):
```python
uso_pct = (live_uso - open_uso) / open_uso * 100
spy_pct = (live_spy - open_spy) / open_spy * 100
xle_pct = (live_xle - open_xle) / open_xle * 100

if uso_pct >= 4.0:
    if spy_pct < 0:
        return "OIL_SPIKE_RISKOFF"  # pause longs, favor FLOOR_BREAK
    else:
        return "OIL_DEMAND_RELIEF"  # risk-on tailwind
```

**Integration rules (conservative)**:
- `OIL_SPIKE_RISKOFF + VIX_LOW_RISING` → high-confidence risk-off (double-confirm = excellent)
- `OIL_UP_MILD` → -1 runner score OR disable BUY_DIP only (not full gate)
- `OIL_CRASH` → +1 or +2 (deflationary relief; theoretically grounded, data shows +1.14% SPY OC)

### Minimum bar for production

- **10-15 OIL_SPIKE_RISKOFF days with filter applied** before full integration
- Right now have ~2-3 clean ones
- Collect 6-12 more months OR do **event study on known geo shocks** (2022 Ukraine, 2023 Hamas) using the same filter

**Academic support**: [Supply-vs-demand oil shocks on equities](https://mpra.ub.uni-muenchen.de) — supply shocks hurt equities MORE than demand-driven ones.

---

## Key Validations from Grok

- **OIL_CRASH bullish result is not artifact** — matches "demand destruction / deflationary relief" — consistent pattern
- **The proposed 4-pattern matrix is spot-on** — aligns with academic literature on oil-equity regime switching
- **The confirmation-gate approach is the fix** — turns ambiguous signal into actionable classifier

---

## Quotes

> "The outlier proves the signal is incomplete, not invalid."

> "Professional desks and macro traders use /CL (crude futures) or Brent for real-time moves because USO is an ETF with slight lag + roll costs."

> "Real alpha in geo events is often the news flow + futures reaction giving 15-90 minutes before SPY fully prices it."

> "The signal survives larger samples but gets diluted by demand-driven noise."

> "Good work putting the outlier front-and-center — most people would have ignored it."

---

## Agreement with ChatGPT

Grok's verdict converges with ChatGPT's:
- Don't ship as pure gate
- OIL_UP_MILD has marginal info value only
- Joint confirmation with VIX is the right architecture
- Threshold should be adaptive (Grok: 2×20d ATR; ChatGPT: 1.5-2× 20d avg abs OC)
- Need more geopolitical shock observations before committing

Grok adds: **refined OIL_SPIKE_RISKOFF with equity confirmation CAN ship** as secondary overlay. ChatGPT was slightly more conservative (informational only).
