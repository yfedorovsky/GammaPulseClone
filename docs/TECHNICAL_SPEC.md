# GammaPulse — Technical Specification for Expert Review

**Version:** v3.1 (April 2026)
**Stack:** FastAPI (Python) + React/Vite + SQLite
**Data:** Tradier Brokerage API (production), Finnhub (news/earnings), Telegram (alerts)
**Scope:** SPY-only GEX (no SPX aggregation) — industry standard matching SpotGamma/Menthor Q

---

## Architecture Overview

```
Tradier API (production token)
    ↓
worker.py (tiered scan: 120s cycle, 300+ tickers, 3 tiers)
    ↓
[In-memory cache + SQLite snapshots.db]
    ↓
FastAPI (30+ endpoints) ──→ React SPA (11 tabs)
    ↓
Optional: Telegram push alerts, Finnhub news/earnings
```

**Background Tasks (asyncio, started at server boot):**
1. GEX scanner — every 120s, tiered by ticker importance
2. Flow scanner — every 30s, unusual volume detection
3. Position monitor — every 30s, trade exit signals
4. SOE signal engine — every 5min, 8-factor scoring

---

## GEX Calculation Engine (server/gex.py)

### Per-Strike Math

```
gamma_dollar = gamma × OI × 100 × spot² × 0.01 × sign
vanna_dollar = vanna × OI × 100 × spot × sign
net_delta    = delta × OI × 100 × sign

sign = +1 for calls, -1 for puts
Vanna approximated as vega/spot (Tradier doesn't provide raw vanna)
```

### Strike Classification

| Type | Criteria | Meaning |
|------|----------|---------|
| KING | Max |net_gex| | Primary structural pivot |
| FLOOR | Highest +GEX below spot (excl. king) | Bull support |
| CEILING | Highest significant +GEX above spot (>3% of king magnitude) | Bear resistance |
| GATEKEEPER | Top 6 by |net_gex| excl. king | Secondary structure |
| AIR POCKET | intensity < 2% of max | Gap risk zone |

### Zero Gamma Line (ZGL)

```
ZGL = Σ(strike × |net_gex|) / Σ(|net_gex|)   [negative-GEX below spot]
Snapped to nearest actual strike.
```

Structural dividing line: below ZGL = volatile (negative gamma), above = stable (positive gamma).

### Signal Derivation

```
if dist_to_king < 0.3%:
    king_positive → PINNING (dealers support price)
    king_negative → DANGER (unstable)

if king_positive:
    king > spot → MAGNET UP (upside attraction)
    king < spot → SUPPORT (support below)

if king_negative:
    king < spot → AIR POCKET (breakdown risk)
    king > spot → RESISTANCE (selling wall)
```

### IV Calculation

Average of 5 strikes closest to spot with IV data, converted to percentage.

### Known Approximations

1. **Vanna ≈ vega/spot** — First-order BSM approximation. Error ≤5% for ATM, degrades for deep OTM
2. **Single IV per expiration** — ATM average, no smile/skew modeling
3. **Linear gamma** — Assumes constant over 1% move (valid for <5% spot moves)
4. **No time decay weighting** — Raw gamma, not time-adjusted
5. **European-equiv Greeks** — Tradier provides European; American early exercise not modeled

---

## SOE Signal Engine (server/signals.py)

8-factor scoring system that generates trade recommendations from GEX structure. Runs every 5 minutes during market hours.

### 8-Factor Scoring (out of 8 points)

| # | Factor | +1 Point | +0.5 Point |
|---|--------|----------|------------|
| 1 | Regime Alignment | Direction matches gamma regime | Counter-trend |
| 2 | King Polarity | King on correct side for trade | King at spot |
| 3 | King Distance | 0.5-3% from spot (sweet spot) | <0.3% (pinning) |
| 4 | Floor/Ceiling | Structural confirmation present | Not found |
| 5 | ZGL Position | Correct side of zero gamma line | N/A |
| 6 | IV Level | <25% (cheap premium) | 25-35% |
| 7 | Confluence | 2+/3 of SPY/QQQ/IWM aligned | N/A |
| 8 | Call/Put Wall | Wall on correct side for direction | N/A |

### Grade Mapping

```
A+ : ≥7.2/8 (90%+)
A  : ≥6.0/8 (75%+)
B+ : ≥5.0/8 (62.5%+)
B  : ≥4.0/8 (50%+)
C  : <4.0/8
Minimum threshold: 3.5/8 (below = rejected)
```

### Contract Selection

- **Expiration:** 7-28 DTE target (sweet spot 14 DTE), fallback 3+ DTE
- **Strike:** 2nd or 3rd OTM (~0.30-0.40 delta equivalent)
- **Entry/Target/Stop:** King as target, floor/ceiling as stop, with 2% fallbacks

### Signal Types

```
PINNING PREMIUM SELL     — at king, positive gamma → sell premium
MAGNET BREAKOUT          — MAGNET UP, king >2% away → directional
POST BOTTOM LAUNCH       — MAGNET UP, king ≤2% → recovering
SUPPORT BOUNCE           — bouncing off floor support
BREAKDOWN ACCELERATOR    — AIR POCKET, breakdown risk → puts
RESISTANCE FADE          — RESISTANCE wall → fade the move
```

### Lifecycle Tracking

Signals tracked in SQLite: PENDING → WIN (target hit) / LOSS (stop hit) / EXPIRED.
Dedup: max 1 signal per ticker per direction per hour.

---

## Discipline Layer (server/discipline.py)

Risk management overlay — additive, never overrides GEX scoring.

### Base Rate Tiering

```
PROVEN      : ≥10 wins, ≥50% win rate
DEVELOPING  : ≥5 wins, ≥25% win rate
UNPROVEN    : default
BELOW_FLOOR : ≥5 losses, <12% win rate → skip entirely
```

### Quarter-Kelly Position Sizing

```
p = win_rate (floored at 23.9% account-wide base rate)
b = payoff_ratio (tier-dependent: PROVEN=12.0, DEVELOPING=4.4, UNPROVEN=2.2)

kelly_raw = (p × b - q) / b
quarter_kelly = kelly_raw × 0.25
size_pct = quarter_kelly × 100 × tier_modifier
```

**Hard Caps (non-negotiable):**
- MAX_SINGLE_POSITION = 15%
- MAX_0DTE_POSITION = 5%
- MAX_UNPROVEN_POSITION = 5%
- MAX_CORRELATED_EXPOSURE = 30% (same sector)

### Circuit Breaker

```
3 consecutive losses → Level 1 (reduced size)
5 consecutive losses → Level 2 (50% size cap)
7+ consecutive losses → Level 3 (FULL STOP until next Monday)
Reset on ANY win.
```

### Exit Ladder

**Multi-day:**
```
+50%  → Sell 25%, stop → breakeven
+100% → Sell 25% more (50% total), trail stop → +50%
+150% → Sell 25% more (75% total)
+200% → Trail final 25%, stop at +100%
```

**0DTE:**
```
+50%  → Sell 50%, stop → breakeven
+100% → Sell 75%, let 25% ride
-50%  → HARD STOP, full exit
```

### 0DTE Time-of-Day Gates (ET)

```
9:30-9:44    → No entries (opening noise)
9:45-11:30   → Full access (morning momentum)
11:30-1:30   → Score ≥7/8 only (chop zone)
1:30-3:00    → Full access (afternoon momentum)
3:00-4:15    → PROVEN + A grade + regime aligned only (power hour)
```

### Five-Factor Playbook Gate

| Factor | +1 Point |
|--------|----------|
| Mir Conviction | HIGH/MEDIUM (or SOE grade A+/A as proxy) |
| Technical Setup | SOE score ≥5/8 |
| Options Flow | Unusual volume confirms direction |
| Macro Context | No toxic earnings, day-of-week, OPEX proximity |
| Catalyst Timing | 7+ DTE or intraday momentum |

```
≥4/5 → VALID (full Quarter-Kelly)
≥3/5 → WEAK (half size, user override needed)
<3/5 → INVALID (log only)
```

---

## Flow Alert System (server/flow_alerts.py)

Scans all 300+ cached tickers every 30s for unusual options activity.

### Detection Criteria

```
volume ≥ 2 × open_interest (V/OI ratio)
notional ≥ $500K
```

### Conviction Scoring

```
Volume: ≥5K → +2, ≥2K → +1
Notional: ≥$5M → +2, ≥$1M → +1
V/OI: ≥10x → +1
GEX alignment: +2 if bullish flow matches MAGNET UP/SUPPORT, or bearish matches AIR POCKET/RESISTANCE

Total ≥5 → HIGH, ≥3 → MEDIUM, else LOW
```

### Side Detection

```
mid = (bid + ask) / 2
if |last - mid| / spread < 0.2 → MID
elif last ≥ mid → ASK (aggressive buyer)
else → BID (aggressive seller)
```

---

## Trade Tracker & Exit Signals (server/trade_tracker.py)

11 exit signal types monitored every 30s:

| Signal | Condition |
|--------|-----------|
| KING_HIT | Spot reached king (take profit) |
| KING_BREAK | Spot broke king by >0.5% (trend continuation) |
| KING_SHIFT | King moved to new strike (structure changed) |
| FLOOR_BREAK | Spot broke below floor (stop loss for longs) |
| CEIL_BREAK | Spot broke above ceiling (stop loss for shorts) |
| ZGL_CROSS | Spot crossed zero gamma line |
| REGIME_FLIP | POS ↔ NEG gamma |
| IV_CRUSH | IV dropped 25%+ from entry |
| THETA_WARNING | ≤3 DTE remaining |
| PROFIT_TARGET | Option price doubled |
| STOP_LOSS | Option price dropped 50% |

---

## Scanner Architecture (server/worker.py)

### Tiered Coverage (300+ tickers)

```
Tier 1 (SPY, QQQ, AAPL, NVDA, etc.)  → Every cycle (120s)
Tier 2 (Large caps)                    → Even cycles (~4min)
Tier 3 (Mid caps)                      → Odd cycles (~4min)
Full universe coverage in 2 cycles = ~4 minutes
```

### Caching Strategy

```
Expirations:  TTL = 3600s (1 hour)
Chains:       TTL = 120s (2 min, matches scan cycle)
Quotes:       Stream (5-30s, real-time)
Snapshots:    Write every 5min (SQLite)
```

### API Cost Model

```
First cycle:     ~750 API calls (cold start)
Subsequent:      ~10 API calls (cache hits)
Tradier limit:   10 req/sec burst, 120K/month
```

---

## Real-Time Streaming

Three-tier fallback:
1. **WebSocket** (`/ws/prices`) — tick-by-tick, bidirectional
2. **SSE** (`/api/stream/prices`) — unidirectional fallback
3. **HTTP Polling** (`/api/quotes`) — last resort, every 5s

---

## Frontend (React/Vite, 11 Tabs)

| Tab | Lines | Features |
|-----|-------|----------|
| HEATMAPS | ~105 | Multi/Focus modes, BARS/PROFILE, 0DTE toggle, Expected Move, earnings badge |
| OVERLAY | ~498 | Tradier candles, GEX levels, VISION mode (aura + cone + arrows), volume, sessions |
| SCANNER | ~369 | 300+ tickers, signal pills, MTF side panel, custom input, King%/GEX MAG columns |
| FLOW | ~435 | ALERTS/SCAN/DETAIL modes, conviction, lifecycle, side detection |
| SIGNALS | ~346 | SOE 8-factor grades, contract selection, Entry/Target/Stop, R:R, reasoning |
| SECTORS | ~692 | Treemap, RRG rotation, holdings with GEX, aggregate walls |
| HISTORY | ~99 | Timeline scrubber, 5-min GEX snapshots |
| MTF | ~155 | Multi-ticker, multi-exp king/floor/ceiling, green separators |
| EARNINGS | ~114 | Weekly calendar (Finnhub), economic events (FOMC/CPI/NFP/OPEX) |
| NEWS | ~262 | Finnhub sentiment, category filters, watchlist sidebar |
| GUIDE | ~117 | Full documentation |

**Total:** ~3,200 lines across 11 tabs + 7 components
**State:** Zustand with localStorage persistence
**Streaming:** WebSocket → SSE → polling fallback chain

---

## Data Sources

| Source | Type | Required |
|--------|------|----------|
| Tradier Brokerage API | Chains, Greeks, bars, quotes, streaming | Required |
| Finnhub | Earnings, news, sentiment | Optional |
| Telegram | Push alerts | Optional |
| SQLite | Snapshots, trades, signals, alerts | Local |

**Real data:** All GEX, prices, chains, flow alerts, signals
**Hardcoded:** Economic event calendar dates, sector ETF mappings, ticker universe

---

## What's NOT Implemented

- IV smile/skew modeling (single ATM IV per expiration)
- Spread recommendations (single-leg only)
- ML-based signal scoring (all rule-based, deterministic)
- SPX aggregation (SPY-only, industry standard)
- True vanna (approximated as vega/spot)
- Time-weighted gamma
- American early exercise modeling
- Forward projection curve in VISION overlay
- GEX Time Machine playback
- Drag-to-reorder panels
