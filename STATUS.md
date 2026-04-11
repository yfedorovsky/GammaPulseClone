# GammaPulse Clone — Build Status

**Last updated:** April 11, 2026  
**Commits:** 5 on `master`  
**Stack:** FastAPI + Vite/React + zustand + lightweight-charts + SQLite

---

## What's Built (Production-Ready)

### Core Engine
- **GEX/VEX Math Engine** (`server/gex.py`) — gamma × OI × 100 × spot² × 0.01, verified within 2-17% of original (data provider gap, not algo)
- **300+ Ticker Scanner** (`server/worker.py`) — tiered scanning with aggressive chain caching (expirations 1hr, chains 2min)
- **Real-time Streaming** — WebSocket primary → SSE fallback → 5s polling. Price updates tick-by-tick during market hours
- **Tradier Adapter** (`server/tradier.py`) — quotes, expirations, chains with greeks, history, intraday bars

### 11 Tabs

| Tab | Status | Description |
|-----|--------|-------------|
| HEATMAPS | ✅ Complete | MULTI/FOCUS modes, BARS/PROFILE views, 0DTE toggle, Expected Move badge, per-expiration signals, hover tooltips, watchlist tabs |
| OVERLAY | ✅ Complete | Real Tradier candles, GEX levels on chart, VISION mode (aura bands + confidence cone + VEX arrows), mini sidebar, volume, sessions filter, trade ideas |
| SCANNER | ✅ Complete | 300+ tickers, signal filter pills with counts, MTF side panel, custom ticker input, King%/GEX MAG/AGE columns |
| FLOW | ✅ Complete | 3 modes: ALERTS (conviction scoring + lifecycle), SCAN (300+ tickers), DETAIL (per-ticker flow analysis with P/C ratio, sentiment, side detection) |
| SIGNALS | ✅ Complete | SOE engine — 8-factor GEX scoring (A+/A/B+/B/C), specific contract selection, Entry/Target/Stop with R:R, reasoning checklist, win rate tracking |
| SECTORS | ✅ Complete | Treemap of 11 SPDR ETFs, RRG rotation graph, top-10 holdings with GEX data, weighted aggregate GEX walls |
| HISTORY | ✅ Complete | Timeline scrubber, GEX snapshots every 5 min during market hours |
| MTF | ✅ Complete | Multi-ticker king/floor/ceiling across all expirations, green gradient separators |
| EARNINGS | ✅ Complete | Weekly calendar with real Finnhub earnings (beat/miss), economic events (FOMC/CPI/PPI/NFP/OPEX), Prev/Next navigation |
| NEWS | ✅ Complete | Finnhub company news with bullish/bearish/neutral sentiment tagging, left sidebar watchlist, category filters |
| GUIDE | ✅ Complete | Full documentation of all features |

### Alert System
- **Flow Alerts** — scans all 300+ cached tickers every 30s for unusual volume (V/OI ≥ 3×, notional ≥ $500K)
- **Conviction Scoring** — HIGH/MEDIUM/LOW based on volume, notional, GEX alignment
- **Trade Tracker** — entry + 8 exit signal types (KING_HIT, FLOOR_BREAK, REGIME_FLIP, IV_CRUSH, THETA_WARNING, etc.)
- **Telegram Push** — instant notifications for flow alerts + exit signals
- **Zero API Cost** — flow scanner piggybacks on GEX worker cache, no extra Tradier calls

### SOE Signals Engine (`server/signals.py`)
AI trade recommendation pipeline scoring 8 factors:
1. Regime alignment (POS/NEG gamma)
2. King polarity (matches direction)
3. King distance (0.5-3% sweet spot)
4. Floor/ceiling confirmation
5. ZGL position
6. IV level
7. Confluence (SPY/QQQ/IWM)
8. Call/put wall alignment

Generates specific contracts with grade (A+ through C), entry/target/stop, R:R ratio, and reasoning.

### Discipline Layer (`server/discipline.py`)
MirBot strategy integration — additive, never overrides GEX scoring:
- **Base Rate Tiering** — PROVEN (≥50% WR, ≥10 trades) / DEVELOPING / UNPROVEN / BELOW_FLOOR per ticker
- **Quarter-Kelly Sizing** — f* × 0.25 with hard caps (15% single, 5% 0DTE, 30% sector)
- **Exit Ladder** — +50/+100/+150/+200% systematic profit taking, 0DTE -50% hard stop
- **Circuit Breaker** — 3 losses → min score, 5 → half size, 7 → full stop until next week
- **0DTE Time Gates** — morning momentum (9:45-11:30), chop zone warning (11:30-1:30), afternoon (1:30-3:00), power hour allowed (3:00-4:15)

---

## What's Remaining / Nice-to-Have

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Display discipline fields in Signals tab UI | High | Easy | Kelly size, tier badge, exit ladder visualization |
| Exit ladder Telegram alerts | High | Easy | Push at +50/+100/+150% levels |
| GEX Time Machine on History tab | Medium | Medium | Spot vs king mini chart with playback |
| Drag-to-reorder panels | Medium | Medium | Edit mode works, just no drag |
| Signal accuracy tracker (real runtime data) | Medium | Needs data | Requires several days of snapshots |
| Earnings badge on heatmap tickers | Low | Easy | Orange badge for earnings this week |
| Session hour shading on overlay | Low | Easy | Green bars for RTH |
| Discord webhook (morning report) | Low | Easy | Already have Telegram |
| Forward projection curve in VISION | Low | Hard | Custom lightweight-charts plugin |
| Pulsing king animation | Low | Easy | CSS keyframe on king price line |

---

## Environment Setup

```bash
# Backend
cd C:/Dev/GammaPulse
python -m venv .venv
.venv\Scripts\activate
pip install -r server/requirements.txt
uvicorn server.main:app --reload --port 8000

# Frontend (separate terminal)
cd C:/Dev/GammaPulse/web
npm install
npm run dev
```

### .env Required Keys
```
TRADIER_TOKEN=xxx              # Required — production API
TRADIER_BASE_URL=https://api.tradier.com/v1
TELEGRAM_BOT_TOKEN=xxx         # Optional — push alerts
TELEGRAM_CHAT_ID=xxx
FINNHUB_API_KEY=xxx            # Optional — news + earnings
```

---

## Key Architecture Decisions

1. **SPY-only GEX** — no SPX aggregation. Industry standard (SpotGamma, Barchart). SPX/NDX/RUT mapping available as future toggle.
2. **Vanna approximated** as vega/spot — Tradier doesn't provide vanna directly.
3. **Rate limiting** handled via tiered scanning + aggressive caching. First cycle expensive (~750 calls), subsequent cycles near-free from cache.
4. **Discipline layer is additive** — never overrides or reduces SOE GEX scoring. It wraps around with sizing + risk management.
5. **0DTE stays open until 4:15** — power hour gamma squeezes are tradeable on E-Trade.
