# Grok System Review — GammaPulse Full Architecture (April 2026)

I built GammaPulse, a real-time options analytics platform that combines dealer gamma exposure (GEX) analysis with momentum-based trading rules. It's been reviewed twice by ChatGPT (quant teardown + post-fix follow-up) and once by Perplexity (academic lit review). I want your fresh, unbiased take.

I'm about to put real money behind this. Be brutal.

---

## System Overview

GammaPulse is a full-stack options intelligence platform: Python/FastAPI backend, React frontend, SQLite persistence, Telegram alerts. It scans 300+ tickers every 2 minutes, computes gamma exposure profiles, generates trade signals, and enforces a rules-based discipline layer calibrated from 569 real trades.

---

## Backend Architecture (Python / FastAPI)

### Core Engine: GEX Computation (`gex.py`)

**What it computes per ticker, per expiration:**
- Net GEX per strike: `gamma * OI * 100 * spot^2 * 0.01` (dealer-side convention)
- Node classification: **King** (highest |GEX|), **Floor** (structural support below spot), **Ceiling** (structural resistance above spot), **Gatekeepers** (top-6 by intensity), **Air** (near-zero GEX = fragile zones)
- **ZGL (Zero Gamma Line):** True gamma profile solve via BSM (r=4.5%, q=1.3% in d1) on 80-point spot grid with linear interpolation at zero crossings. All crossings stored (highest below spot, lowest above spot, nearest). Centroid fallback only when IV missing (tagged).
- **Regime:** POS (positive total GEX = mean-reverting, dealer hedging stabilizes) vs NEG (negative total GEX = trend-amplifying, dealer hedging destabilizes)
- **Signal:** MAGNET_UP, SUPPORT, PINNING, AIR_POCKET, RESISTANCE, DANGER (based on king polarity, king position relative to spot, regime)
- VEX (vanna exposure) approximated from greeks but used for UI display only, not decisions
- **MACRO aggregation:** "MACRO (ALL 200D)" key aggregates across all expirations within 200 DTE for structural view

**Greeks data sources (dual-tracked):**
- Tradier API: free with brokerage, but **CONFIRMED FROZEN** for 0DTE (identical values across 10-minute samples)
- Massive API ($29/mo): **CONFIRMED REAL-TIME** (delta updates every 30-second sample)
- Both stored separately (`_greeks_tradier` + `_greeks_massive`) for auditability
- **0DTE hard gate:** only tradeable if Massive Greeks age <= 60s AND spot age <= 180s. No silent fallback to Tradier.

### Signal Engine: SOE 5-Factor Scoring (`signals.py`)

**5 independent factors (max 6 points), reduced from 8 to address collinearity:**

| # | Factor | Max | What It Measures |
|---|--------|-----|------------------|
| 1 | GEX Structure | 2 | King polarity + regime alignment + ZGL position + wall structure, bounded to ONE factor to avoid inflating correlated GEX views |
| 2 | King Distance | 1 | Sweet spot 0.5-3% from spot (too close = noise, too far = no pull) |
| 3 | Support/Resistance | 1 | Floor/ceiling structural confirmation |
| 4 | IV Environment | 1 | Per-ticker IVP vs 52-week history + IV/HV ratio (Vega Risk Premium) |
| 5 | Macro Confluence | 1 | SPY/QQQ/IWM directional alignment (0.5) + NYMO/NAMO breadth (0.5) + VIX term structure |

**Grade mapping:** A+ (7.2+/8), A (6.5-7.1), B+ (5.5-6.4), B (4.5-5.4), C (<4.5)

**Contract quality gates at signal generation:**
- Bid-ask spread < 10% of mid
- Open interest > 500
- Delta 0.25-0.60
- R:R >= 1.0
- Earnings blackout (Finnhub 7-day lookahead)

**Signal lifecycle:** PENDING -> WIN / LOSS / EXPIRED (with PnL tracking)

### Discipline Layer: Kelly + Circuit Breaker (`discipline.py`)

**Calibrated from 569 real MirBot trades (not placeholder assumptions):**

| Tier | Criteria | Kelly Multiplier | Win Rate Floor |
|------|----------|-----------------|----------------|
| PROVEN | 10+ trades | 10.75 | 22.8% |
| DEVELOPING | 3-9 trades | 17.13 | 22.8% |
| UNPROVEN | <3 trades | 29.67 | 22.8% |

**Known issue:** UNPROVEN multiplier is highest — likely survivorship bias from outlier tickers (e.g., AAPL 35x on 18 trades inflating the category).

**Rolling circuit breaker (replaces "reset on any single win"):**
- L1: rolling 10-trade WR < 20% -> reduce size
- L2: WR < 10% OR weekly drawdown > 5R -> half size
- L3: WR = 0% on 10 trades OR weekly DD > 8R -> full stop

**0DTE time gates (backtest-validated):**
- AM momentum (9:30-12:00): 48% WR, 0% EV -> **DISABLED for live**
- PM momentum (1:30-3:00): 58% WR, +0.24% avg -> enabled
- Power Hour (3:00-4:00): 62% WR, +0.37% avg -> enabled (best edge)

**Exit ladder:** +50% / +100% / +150% / +200% scaling

### Mir's Codified Rules (`mir_rules.py`)

Extracted from 23,866 RAG chunks of MirBot's Discord/Twitter history (April 2026). MirBot is a paid options signal service I subscribe to.

**7 rules codified into `score_mir_pattern()` (returns match %):**

1. **DTE:** 0DTE = lottos only. 1-7 DTE preferred minimum. 14-21 DTE for catalyst. 30+ for macro.
2. **Time of day:** Avoid first hour. Best windows: AM settled (10:30-11:30), Mid-day (1:30-2:00), Power Hour (3:00-4:00).
3. **Stop loss:** Weeklies = 50% stop. Move to breakeven quickly. Trail outside last flag.
4. **Position sizing:** 5-10% baseline, scale in 3 parts, HIGH conviction up to 10%.
5. **Ticker selection:** EMA 21/50 filter, ADR% > 2%, volume > 500K, price > $3. Group by leading sector.
6. **Profit taking:** Scale 50% at 100% gain. Primary target 1.618 fib.
7. **Macro regime:** VIX > 22 = defensive. VIX > 35 = cash. Oversold NYMO = aggressive rotation.

**Critical architecture decision: Mir HIGH conviction OVERRIDES the GEX discipline gate.** Rationale: backtest proved GEX alone = negative EV on single stocks. Mir momentum alone = 54.9% WR, +27.5% avg. GEX becomes advisory (provides levels), not blocking, when Mir is HIGH conviction.

### MirBot Bridge (real-time integration)
- Mac Mini Discord listener -> POST to GammaPulse webhook
- Mir conviction (HIGH/MEDIUM/LOW) stored in cache with 1-hour TTL
- Factor 1 in discipline gate uses REAL Mir conviction

### Scalp Alert System (`scalp_alerts.py`)
Separate from SOE. Runs every 30 seconds on SPY/QQQ.

**Fires on STATE TRANSITIONS only (not proximity):**
- BUY THE DIP: floor held, price bouncing up
- BREAKOUT: price crossed above king
- RETEST: pullback to king from above
- SELL THE POP: ceiling rejection
- FLOOR BREAK: breakdown below support
- REGIME CHANGE: ZGL cross

Skips first hour + midday chop. 15-minute cooldown per alert type per ticker.

### Flow Alert System (`flow_alerts.py`)
Scans 300+ tickers every 30 seconds for unusual options volume.

**Conviction scoring:** volume-weighted notional, vol/OI ratio (2x+ = unusual), GEX alignment, smart money direction inference (call ASK = bullish, put ASK = hedging).

### RTS Engine (`rts.py`) — Vehicle Selection Layer
Relative Trend Strength ranks tickers by momentum + quality:
- **RS block (50%):** 20D/60D return vs SPY, percentile rank
- **Trend block (50%):** Price above 20/50/100 MA, MA alignment, 20MA slope
- **Extension flag:** NORMAL / EXTENDED / OVEREXTENDED (based on ATR distance from 20MA)

### Industry Leadership (`industry.py`)
13 groups (Mag 7, Semis, Photonics, AI/DC Infra, Crypto, etc.). Per-group scoring -> LEADING / EMERGING / NEUTRAL / WEAKENING / BROKEN.

### Breadth Module (`breadth.py`)
NYMO/NAMO McClellan Oscillator from advance/decline data:
- Classified by exchange (XNYS vs XNAS, 5,025 common stocks)
- 39+ days backfilled, persisted in SQLite
- Wired into SOE Factor 5

### Background Workers
| Worker | Cadence | Purpose |
|--------|---------|---------|
| GEX Scanner | 120s | Batch chains + GEX computation |
| Flow Scanner | 30s | Unusual volume detection |
| Position Monitor | 30s | Trade tracking + exit ladder |
| SOE Engine | 5min | Signal generation |
| Scalp Scanner | 30s | SPY/QQQ 0DTE structure alerts |

Tier-based scanning: Tier 1 (mega caps) every cycle, Tier 2 every 2 cycles, Tier 3 every 4 cycles.

### Telegram Alerts
Centralized rate limiter: 3 messages/10min global, 1hr/ticker cooldown. A/A+ SOE signals bypass global limit.

---

## Frontend Architecture (React 18 / Zustand / Vite)

### Tabs
| Tab | Purpose |
|-----|---------|
| HEATMAPS | Multi-panel GEX heatmaps (bars + profile views) |
| OVERLAY | Candlestick chart + GEX levels + EMAs + RSI/ADX + Volume Profile (ISeriesPrimitive plugin) + AVWAP click-to-anchor + signal markers + earnings markers |
| SCANNER | 300+ ticker sortable table with RTS, signals, regimes, theme-based watchlists |
| FLOW | Unusual volume alerts with conviction scoring + 7-day win rate stats |
| SIGNALS | SOE signal history with grade/outcome filters + per-grade WR breakdown |
| SECTORS | Industry leadership dashboard (group scores + member rankings) |
| HISTORY | Timeline scrubber over GEX snapshots |
| MTF | Multi-timeframe king/floor/ceiling per expiration |
| EARNINGS | Finnhub calendar with ticker badges |
| NEWS | Per-ticker Finnhub news feed |

### Chart Overlay (the main trading view)
- Lightweight-charts v4.2.3 with ISeriesPrimitive plugins
- Volume Profile: custom plugin primitive, gray bars with POC highlight, auto-syncs with zoom/pan
- EMA cloud: 8/21/50/200 with last-value labels
- AVWAP: click-to-anchor on any candle (uses refs to avoid stale closures)
- Earnings "E" markers on daily timeframe
- GEX levels: King (gold/purple), Floor (green), Ceiling (red), ZGL (dotted red)
- VISION mode: aura bands, confidence cone (+/-1 sigma from IV), VEX arrows
- Signal markers: buy/sell arrows with WIN/LOSS status
- Session filter (RTH only for intraday)

### Streaming Architecture
WebSocket -> SSE -> polling fallback chain with automatic failover (4s WS timeout, 6s SSE timeout).

### Bundle
Lazy-loaded tabs: 180KB main + chunks. Lightweight-charts 162KB.

---

## Backtest Results

### SPY Intraday Scalps (5-min bars, Apr 2025 - Apr 2026)
```
258 trades, 51.9% WR, +0.09% avg
  Power Hour: 62% WR, +0.37% avg (16 trades)
  PM Momentum: 58% WR, +0.24% avg (74 trades)
  AM Momentum: 48% WR, -0.00% avg (168 trades) <- DISABLED
```

### Mir Swing (semi/photonics, daily bars)
```
162 trades, 54.9% WR, +27.5% avg
  MU: 71% WR, +83.2% avg (41 trades)
  SMH: 72% WR, +23.9% avg (25 trades)
  LRCX: 64% WR, +53.5% avg (36 trades)
```

### Surviving Strategies (from v3.0 review)
Only BREAKDOWN_ACCELERATOR (AIR POCKET + NEG gamma, buy puts) and RESISTANCE_FADE survived ChatGPT's quant teardown. PINNING, SUPPORT_BOUNCE, MAGNET_BREAKOUT, POST_BOTTOM_LAUNCH all killed for low WR or conceptual issues.

---

## Academic Foundation

The Perplexity academic review (12 papers) confirmed:
1. **Negative gamma amplification is robustly established** (Baltussen et al. 2021, Buis et al. 2024, Anderegg et al. 2022)
2. **The effect is primarily INTRADAY and reverts within 1-3 days** -- does not compound multi-day without new catalyst
3. **No peer-reviewed backtest of a GEX-based options strategy with published WR/Sharpe exists**
4. **Bid-ask spreads consume ~20% of option value on average** (friction is real)
5. **GEX signal quality degrades: SPX > SPY > QQQ > individual equities** (driven by OI concentration + dealer participation)

---

## Known Gaps & Limitations

1. **IV smile/skew modeling:** Single ATM IV per expiration. No smile interpolation.
2. **Single-leg only:** No spread recommendations. Directional puts/calls only.
3. **SPY-only GEX:** No SPX aggregation (SPX + SPY dealer positions differ).
4. **Vanna approximation:** UI display only, not used in signal decisions.
5. **No time-weighted gamma:** Treats all expirations equally within MACRO view.
6. **Sample sizes:** Power Hour edge based on 16 trades. Mir swing backtested on one sector cluster.
7. **Kelly UNPROVEN tier:** Counterintuitively highest multiplier (29.67) -- likely survivorship bias.
8. **GEX alone = negative EV on single stocks.** The edge comes from Mir momentum + GEX levels, not GEX alone.

---

## Data Sources & Costs

| Source | Data | Cost |
|--------|------|------|
| Tradier | Quotes, streaming, candles, OI, volume | Free (with brokerage) |
| Massive | Real-time Greeks (30s refresh) | $29/mo |
| Finnhub | Earnings calendar, news | Free tier |
| MirBot | Discord signals (relayed via webhook) | Paid subscription |
| Telegram | Push alerts (outbound only) | Free |

---

## Live Trading Parameters (ChatGPT-calibrated)

- Expected WR: 52-54% (not 65%)
- Expected per-trade EV: +1-3%
- Kill switch: 30 trades negative EV, 5% DD, or WR < 45%
- Starting size: $250-500/trade on $100K account
- 1.5% fixed sizing for validation phase (not Kelly)

---

## Questions for Grok

### 1. Edge Assessment
GammaPulse combines GEX structural analysis (WHERE dealer hedging creates mechanical support/resistance) with Mir momentum signals (WHEN to enter based on price action + sector rotation) and a Kelly-calibrated discipline layer (HOW MUCH to size).

- **Is the combination of these three layers (where + when + how much) a genuine edge, or am I just adding complexity to a coin flip?**
- **The academic lit says GEX degrades from SPX -> individual equities. My backtest confirms GEX alone = negative EV on single stocks. Is the Mir override the right fix, or am I masking a fundamental flaw?**
- **What's the actual mechanism that would produce alpha here vs. a simple momentum strategy with stop losses?**

### 2. Architecture Critique
- **What's over-engineered?** 5 background workers, 300+ tickers, 11 tabs, dual Greek sources, 5-factor scoring... Is this engineering discipline or complexity theater?
- **What's under-engineered?** Where are the gaps that will bite me in live trading?
- **The SQLite single-writer + in-memory cache architecture: good enough, or will it break under load?**

### 3. Statistical Validity
- **16 power-hour trades showing 62% WR: is this anything, or pure noise?**
- **162 Mir swing trades at 54.9% WR, +27.5% avg: survivorship bias from backtesting on winning tickers?**
- **The Kelly calibration from 569 trades: is this a valid sample, or are we fitting noise?**

### 4. What Would You Change?
If you had this codebase and were going to put real money behind it:
- **What would you add/remove/change in the first week?**
- **What's the minimum viable version (strip everything that doesn't contribute to edge)?**
- **What monitoring would you set up for live trading?**

### 5. Competitive Landscape
- **How does this compare to retail tools like SpotGamma, Menthor Q, OptionSonar, GEX Dashboard Pro?**
- **Is building custom infrastructure a competitive advantage, or would subscribing to a commercial GEX service + following Mir be simpler and equally effective?**
- **What are professional market makers doing differently that makes this approach naive?**

### 6. The Brutal Question
I've spent months building this. The academic review says GEX is real but intraday-only. My own backtest says GEX alone is negative EV. The edge, if any, comes from Mir momentum + GEX levels + disciplined sizing.

**Am I building a sophisticated interface for following someone else's trade signals with extra steps? If I removed GEX entirely and just followed Mir alerts with the discipline layer, would my results be materially worse?**

---

## The Bottom Line

Rate this system honestly:

| Dimension | Score (1-10) | Notes |
|-----------|-------------|-------|
| Engineering quality | ? | |
| GEX math correctness | ? | |
| Signal generation | ? | |
| Risk management | ? | |
| Data fidelity | ? | |
| Statistical rigor | ? | |
| Real-money readiness | ? | |
| Edge probability | ? | |

Be blunt. I'd rather know now than after losing money.
