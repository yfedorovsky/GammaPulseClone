# Perplexity Brief — Zero-Lag Filter Strategies for Intraday Options

## Context (read this first)

Solo retail options trader on E*Trade. Built GammaPulse-style system that
tracks GEX (gamma exposure), king/floor/ceiling structural levels, NCP/NPP
flow, ISO sweeps, UW-style "Golden" pattern alerts, and a real-time worker
that snapshots all of this to SQLite every ~6 minutes during market hours.

Goal: catch intraday turns on SPY/QQQ/SPX/IWM with **0DTE or 1DTE options**
(ATM calls/puts at fire-time). Realistic option P&L computed paying ASK on
entry, hitting BID on exit (no mid-fills assumed).

Specifically: find **fast/zero-lag filters** that distinguish a real
structural turn (which pays 100-300% on 0DTE) from a wick that fades right
back (which dies at -50% stop).

---

## What we already have working

**Structural Turn detector — 7-gate confluence:**
1. Spot near floor (BULL) or king (BEAR), within 0.5% tolerance
2. Floor migration UP / floor-hold pattern (3+ touches in 90min)
3. Volume absorption: 1-min bar ≥2× 20-min avg AT session LOD/HOD
4. Aggregate same-side flow ≥$10M in 30min (sweeps + Golden + HIGH conviction)
5. NCP/NPP corroboration: same-direction flow on this ticker OR SPX parent
6. GEX magnitude floor: |min(pos_gex, neg_gex)| ≥ $20M
7. Regime + ratio compatibility (POS+ratio≥2.0 OR NEG+ratio≤0.7 for BULL)

**Tiered alerts:**
- TIER A = 7/7 → auto-trade candidate
- TIER B = 6/7 (regime fuzzy) → watchlist

**22-day backtest results (Apr 7 – Apr 28, 2026, SPY/QQQ/IWM/SPX):**
- 4 fires, 100% EOD hit, +80% avg option P&L, +166% avg MFE
- 0 bearish fires (uptrending tape; detector is symmetric, just no setups)
- All 4 fires were BULLISH on PML retest patterns

---

## What we tested as a faster alternative (and why it failed)

**Strategy:** PML/PMH ±0.05% touch → ATM 0DTE call (PML) or put (PMH)
**Stops:** -50% on cost basis
**Targets:** TP1 +100% (sell 50%), TP2 +200% (sell 25%), trail or EOD on rest

### Three variants tested

| Variant | Filters | Stop | Trades | Hit% | Avg P&L |
|---|---|---|---|---|---|
| Baseline | none | -50% | 49 | 12% | -33% |
| Confirm + trend filter | EMA8>EMA21 (BULL), EMA8<EMA21 (BEAR), close-back required | -50% | 25 | 24% | -21% |
| Same + wider stop | + -70% stop | -70% | 25 | 32% | -22% |

### Asymmetric finding

The 5-min EMA8/EMA21 trend filter is **asymmetric in usefulness**:
- BEARISH: 7% → **38%** hit rate (filter eliminates puts into uptrending tape)
- BULLISH: 21% → 22% (filter doesn't help — PML touch is *inherently
  counter-trend*, requiring EMA8>EMA21 at the touch *rejects* the genuine
  bottom-formation setups before the trend has reversed)

### MFE-vs-realized gap

Avg MFE across all losing trades was +42% to +68%. Many trades that stopped
at -50% had earlier touched +50% to +84% MFE before reversing. **The
directional move often exists; the stop fires before TP1.**

---

## What we're looking for from you

Specifically: **zero-lag filter strategies** that could replace or augment
the EMA8/EMA21 trend filter for the BULLISH side (counter-trend dip-buying),
where traditional MAs are by definition lagging.

### Candidates we want your take on

1. **Hull MA (HMA)** — claims zero lag via WMA chained transformation
2. **ZLEMA / Zero-Lag EMA** — Ehlers' price-extrapolation method
3. **JMA (Jurik)** — proprietary but well-documented
4. **T3 / FRAMA / KAMA** — adaptive smoothers
5. **Kalman filter on price** — engineering approach, common in HFT
6. **Cumulative volume delta (CVD) divergence** — order-flow read
7. **Footprint / volume profile** — POC migration, value-area shifts
8. **Anchored VWAP** from prior session high/low
9. **Market microstructure** — order-book imbalance, queue position
10. **Statistical mean-reversion bands** (Bollinger %B, RSI on 1-min, etc.)

### Specific questions

1. For **counter-trend long entries** on retests of pre-market low or prior
   day's low, which of the above gives the highest signal-to-noise without
   requiring the trend to have reversed?

2. Has anyone published quantitative work on **CVD divergence + LOD test**
   as a 0DTE long-entry trigger? Does it generalize across SPY/QQQ?

3. For institutional/retail bottom-fishing on index ETFs, what does the
   current **academic + practitioner consensus** say about the best
   <30-second-lag filter? Is anyone using market-microstructure features
   (queue size, hidden liquidity, sweep density) successfully?

4. We have access to ThetaData OPRA stream (option sweeps, condition=95
   ISO prints). Are there proven **option-flow-based zero-lag triggers**
   (e.g. specific premium thresholds, OTM-vs-ITM call spread accumulation,
   gamma-flip detection) that could replace the trend filter entirely?

5. If we had to pick **ONE filter to add** that would lift the BULLISH PML
   touch from 21% hit to 50%+ without killing trade count, what would it be?
