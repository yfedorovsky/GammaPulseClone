# Gemini Deep Research — GammaPulse Architecture & Edge Analysis (April 2026)

Paste this into Gemini 2.5 Pro (Deep Research) for an engineering-focused review.

---

## Context

GammaPulse is a self-hosted options analytics platform I built over several months. It combines dealer gamma exposure (GEX) analysis with momentum-based trade selection and a Kelly-calibrated risk layer. I've had it reviewed by ChatGPT (quant teardown), Perplexity (academic lit validation), and I'm sending it to Grok (edge assessment). I want Gemini to focus on **engineering rigor, architectural decisions, and whether the system design actually supports the trading thesis**.

---

## Full Architecture

### Backend (Python / FastAPI)

**5 background workers running concurrently:**
| Worker | Cadence | Function |
|--------|---------|----------|
| GEX Scanner | 120s | Batch option chains for 300+ tickers (tiered: mega caps every cycle, mid caps every 4th), compute GEX/VEX/ZGL/regime/signals per ticker per expiration |
| Flow Scanner | 30s | Detect unusual options volume (vol/OI ratio, notional, GEX alignment) |
| Position Monitor | 30s | Track open trades, trigger exit ladder (+50/100/150/200%) |
| SOE Signal Engine | 5min | Generate scored trade signals (5-factor, max 6 points) with contract selection |
| Scalp Scanner | 30s | SPY/QQQ 0DTE structure alerts on GEX level state transitions |

**GEX math (`gex.py`):**
- Per-strike: `net_gex = gamma * OI * 100 * spot^2 * 0.01 * sign` (calls +1, puts -1)
- ZGL: BSM gamma recomputed across 80-point spot grid (r=4.5%, q=1.3% in d1), zero crossings found via linear interpolation. All crossings stored.
- Node classification: King (highest |GEX|), Floor/Ceiling (structural S/R), Gatekeepers (top-6), Air (near-zero)
- Regime: POS (stabilizing) vs NEG (destabilizing) based on total net GEX
- Signal: MAGNET_UP / SUPPORT / PINNING / AIR_POCKET / RESISTANCE / DANGER

**Dual Greeks architecture:**
- Tradier (via ORATS): free with brokerage, **confirmed frozen intraday** (identical values across 10-min samples)
- Massive/Polygon ($29/mo): **confirmed real-time** (delta moves every 30s sample)
- Both stored separately for auditability (`_greeks_tradier` + `_greeks_massive`)
- 0DTE hard-gated: Massive Greeks age <= 60s AND spot age <= 180s required

**Signal engine (`signals.py`) — 5 independent factors:**
1. GEX Structure (0-2): regime + king polarity + ZGL + walls, bounded to one composite factor
2. King Distance (0-1): 0.5-3% sweet spot from spot
3. Support/Resistance (0-1): floor/ceiling confirmation
4. IV Environment (0-1): per-ticker IVP vs 52-week history + IV/HV ratio (Vega Risk Premium)
5. Macro Confluence (0-1): SPY/QQQ/IWM directional alignment (0.5) + NYMO/NAMO breadth (0.5) + VIX term structure

**Contract quality gates:** spread < 10% mid, OI > 500, delta 0.25-0.60, R:R >= 1.0, earnings blackout

**Discipline layer (`discipline.py`):**
- Kelly sizing calibrated from 569 real MirBot trades
- Tier-based: PROVEN (10+ trades, multiplier 10.75), DEVELOPING (3-9, 17.13), UNPROVEN (<3, 29.67)
- Rolling circuit breaker: L1 (10-trade WR < 20%), L2 (WR < 10% or 5R weekly DD), L3 (WR = 0% or 8R DD)
- 0DTE time gates: AM disabled (48% WR, 0% EV), PM enabled (58%), Power Hour best (62%)
- Exit ladder: +50/100/150/200% systematic scaling

**Mir rules engine (`mir_rules.py`):**
- 7 rules extracted from 23,866 RAG chunks of a professional options trader's signal history
- `score_mir_pattern()` returns match %: DTE preference, time of day, stop rules, sizing, ticker selection, profit taking, macro regime
- **Mir HIGH conviction overrides GEX discipline gate** — backtest proved GEX alone = negative EV on single stocks, Mir momentum = 54.9% WR, +27.5% avg

**Supporting modules:**
- `breadth.py`: NYMO/NAMO McClellan from Massive advance/decline data (5,025 common stocks, 39 days backfilled)
- `rts.py`: Relative Trend Strength — RS vs SPY (20d/60d), MA alignment (20/50/100), slope, ATR extension
- `industry.py`: 13 industry groups scored -> LEADING/EMERGING/NEUTRAL/WEAKENING/BROKEN
- `scalp_alerts.py`: 0DTE structure alerts on state transitions (floor bounce, king breakout, ZGL cross)
- `flow_alerts.py`: unusual volume detection with conviction scoring
- `telegram.py`: rate-limited push alerts (3/10min global, 1hr/ticker cooldown)
- `db.py`: SQLite single-writer queue (Actor pattern)

**Persistence:** SQLite with tables for snapshots, signals, flow alerts, trade log, circuit breaker state, daily breadth

### Frontend (React 18 / Zustand / Vite)

**11 lazy-loaded tabs:**
- HEATMAPS: multi-panel GEX heatmaps (bars + profile views)
- OVERLAY: lightweight-charts v4.2.3 candlestick chart with GEX levels, EMA cloud (8/21/50/200), Volume Profile (ISeriesPrimitive plugin), AVWAP click-to-anchor, earnings "E" markers, signal markers, VISION mode (confidence cone, VEX arrows)
- SCANNER: 300+ ticker sortable table, RTS scores, theme-based watchlists (11 industry groups)
- FLOW: unusual volume alerts with conviction scoring
- SIGNALS: SOE signal history with grade/outcome filters, per-grade WR stats
- SECTORS: industry leadership dashboard
- HISTORY: timeline scrubber over GEX snapshots
- MTF: multi-timeframe king/floor/ceiling
- EARNINGS: Finnhub calendar
- NEWS: per-ticker Finnhub feed
- GUIDE: embedded docs

**Streaming:** WebSocket -> SSE -> 5s polling fallback chain (4s WS timeout, 6s SSE timeout)
**Bundle:** 180KB main + lazy chunks. lightweight-charts 162KB.

### Backtest Results

```
SPY Intraday Scalps (5-min bars, Apr 2025 - Apr 2026):
  258 trades, 51.9% WR, +0.09% avg
  Power Hour: 62% WR, +0.37% avg (16 trades)
  PM Momentum: 58% WR, +0.24% avg (74 trades)
  AM Momentum: 48% WR, -0.00% avg (168 trades) <- DISABLED

Mir Swing (semi/photonics, daily):
  162 trades, 54.9% WR, +27.5% avg
  MU: 71% WR, +83.2% avg (41 trades)
```

### Known Limitations
- IV smile/skew: single ATM IV per expiration, no smile interpolation
- Single-leg only: no spread recommendations
- SPY-only GEX (no SPX aggregation)
- Vanna approximated (UI only, not in decisions)
- No time-weighted gamma
- Small sample sizes (Power Hour: 16 trades, Mir swing: 162 trades on one sector cluster)

---

## What I Want Gemini to Evaluate

### 1. Concurrency & Reliability

Five async workers share an in-memory cache + SQLite DB. The SQLite write queue uses an Actor pattern (single-writer coroutine with asyncio.Queue).

- **Is the Actor pattern sufficient for SQLite concurrency**, or should I use WAL mode + connection pooling? What's the failure mode if the queue backs up?
- **Memory pressure**: 300+ tickers with full option chains cached in memory + 30s Greeks cache + streaming price buffer. Rough estimate of memory footprint? When does this become a problem?
- **Temporal coherence**: a signal could use a 2-minute-old chain with 30-second-old Greeks and 1-second-old spot. Is this mismatch a real issue for GEX computation? How do professional systems handle this?
- **Worker failure isolation**: if the flow scanner crashes, does it take down the GEX scanner? I use try/except per worker but no process isolation.
- **What happens when Massive API goes down during market hours?** Silent fallback to frozen Tradier Greeks — for 0DTE this is gated, but for multi-day signals the stale Greeks just flow through undetected.

### 2. Signal Engine Design

- **5-factor additive scoring with uniform weights**: is this defensible, or should factors be weighted differently based on predictive power? How would I determine weights without overfitting to 258 trades?
- **The collinearity fix** (bounding all GEX views into one 0-2 factor): is this the right approach? Should Factor 1 be decomposed differently?
- **Earnings blackout** uses Finnhub 7-day lookahead to block signals. But Finnhub only covers the current week reliably. Should I build a historical earnings database instead?
- **Signal dedup**: I persist the last 2 hours of signals and skip duplicates. Is 2 hours the right window? For daily signals this means I'll never re-fire on the same ticker in the same session. Is that correct behavior?
- **The Mir override**: when a trusted external signal source says HIGH conviction, my system overrides its own quality gates. Is this architecturally sound, or am I building a dependency that undermines the system's independence?

### 3. Data Pipeline Integrity

- **The GEX formula uses OI (open interest), which only updates overnight for most brokers.** During the trading day, I'm computing intraday GEX levels using stale OI. How much does this matter? Do professional tools use intraday OI updates?
- **My sign convention (calls +1, puts -1) assumes dealers are net short.** For SPY this is probably > 90% accurate. For TSLA or AMC meme stocks it's probably wrong. Should I adjust the convention per ticker based on some heuristic?
- **Greeks enrichment from Massive happens per worker cycle (120s).** Between enrichments, the Greeks in cache are aging. For 0DTE, 120 seconds of gamma drift is significant. Should the Greeks refresh be decoupled from the main scanner cycle?
- **NYMO/NAMO computation**: I classify tickers into NYSE vs NASDAQ based on exchange data from Massive. If a ticker is dual-listed or misclassified, it corrupts both oscillators. How robust is this classification?

### 4. Frontend Performance

- **11 lazy-loaded tabs** with the main heatmap view eagerly loaded. The OVERLAY tab has the heaviest rendering (lightweight-charts + VP plugin + multiple line series + markers).
- **The Volume Profile plugin** creates a new ISeriesPrimitive on each data update (detach + re-create). Is this the right lifecycle, or should I reuse the primitive and call `setData()`?
- **300+ rows in the Scanner tab**: currently renders all rows. Should I virtualize? At what row count does this matter?
- **Zustand store** holds all spot prices, chains, and scanner data in memory. The chains object for 300 tickers is substantial. Should I move to a more granular subscription model?

### 5. The Edge Question (Engineering Perspective)

My backtests show:
- GEX alone: negative EV on single stocks, marginal (+0.09%) on SPY
- Mir momentum alone: 54.9% WR, +27.5% avg on sector leaders
- Combined: untested at scale

From an **engineering perspective**:
- Am I building **decision support** (shows information, human decides) or **automated trading** (system decides)? The architecture straddles both — is that a problem?
- The Mir override makes this effectively a **signal relay with GEX context**. Is there a simpler architecture that achieves the same outcome?
- If I stripped everything except: (a) GEX levels on a chart, (b) Mir alert relay, (c) position sizing — would I lose any actual edge?
- **What's the minimum viable system** that captures the core value proposition?

### 6. What Would You Build Differently?

If you were starting this today with the same thesis (GEX levels + momentum signals + disciplined sizing):

- **Data architecture**: SQLite vs Postgres vs TimescaleDB vs Redis for the cache layer?
- **Worker architecture**: AsyncIO tasks vs Celery vs separate processes?
- **State management**: in-memory dict vs Redis vs event-sourcing?
- **Frontend**: React + lightweight-charts vs a commercial charting library (TradingView widget)?
- **Deployment**: single-machine Python process vs containerized microservices?
- **Monitoring**: what telemetry would you add for a live trading system?

Be specific and technical. I'm not looking for validation — I'm looking for things that will break when real money is on the line.
