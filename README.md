# GammaPulse

A real-time options analytics platform with **OPRA-level flow detection**, **gamma exposure mapping**, and **institutional insider-pattern signals**. Originally reverse-engineered from [GammaPulse Pro](https://gammapulse.rstechnology.org/), now substantially beyond it in signal coverage.

**Current capability comparison:**

| | GammaPulse (this) | UW Whales API | UW GUI |
|---|---|---|---|
| OPRA tape + condition codes | ✅ via ThetaData | ✅ | ✅ |
| Real-time ISO sweep detection | ✅ | ✅ | ✅ |
| Live Golden Flow composite alerts | ✅ | ✅ | ✅ |
| Live Tail Flow (cheap far-OTM) alerts | ✅ | ✅ | ✅ |
| A+/A/B/C/D grading on every alert | ✅ | ❌ | ❌ |
| Forward-return hit rate per cohort | ✅ | ❌ | Partial |
| GEX gamma exposure heatmaps | ✅ (SPY/QQQ/SPX) | ❌ | ❌ |
| Mir momentum swing signals | ✅ | ❌ | ❌ |
| Paper trading with slippage + MFE/MAE | ✅ | ❌ | ❌ |
| Telegram push with confidence grade | ✅ | API only | ❌ |
| **Monthly cost** | **$80/mo** (ThetaData Options Standard) | $250+/mo | $50-100/mo |

---

## Stack

- **Backend**: Python 3.11+, FastAPI, httpx, SSE, asyncio, SQLite (WAL mode)
- **Frontend**: React 18, Vite, Zustand, lightweight-charts
- **Data sources**:
  - **ThetaData** (Options Standard $80/mo) — real-time OPRA trades/quotes, Greeks via BSM synthesis, 8yr history. Local Terminal on ports 25503 (REST) + 25520 (WebSocket).
  - **Tradier** — underlying spot + candles + historical stock bars
  - **Finnhub** (optional) — earnings calendar, news sentiment
  - **FRED** (free) — macro data (HY spreads, VIX, yield curve)
- **Integration**:
  - **Telegram** bot push for alerts (rate-limited, grade-tiered)
  - **Discord** listener for MirBot signal capture (Claude Haiku parsing)

---

## Features

### Flow detection (newest)

Two composite insider-pattern detectors running against the live OPRA tape:

- **⚡ GOLDEN FLOW** — urgent ATM conviction (1-2 DTE): `≥$500K`, `≥65% directional`, `V/OI ≥3x`, `≤2.5% OTM`, `≤2 DTE`. Matches UW's "golden sweep" pattern. Example reference: SPY 647P 3/24 (fired 15 min before market-moving headlines).
- **🎯 TAIL FLOW** — cheap far-OTM longer-dated lotto (3-45 DTE): `≥$500K`, `≥65% directional`, `≤$2 avg fill`, `4-25% OTM`, `3-45 DTE`. Portfolio hedgers + event-driven funds positioning for monthly-window catalysts.
- **Cluster detection** — 2+ matches on same underlying same session = the real tell.
- **A+/A/B/C/D grading** on every alert (5-factor composite, 0-20 score).
- Backed by `option_flow_daily` table + `/api/flow/golden` + `/api/flow/tail` endpoints.

Full architecture: [docs/research/SESSION_APR18_UW_PARITY.md](docs/research/SESSION_APR18_UW_PARITY.md).

### Gamma Exposure (GEX) analytics

- **HEATMAPS** tab — multi/focus layouts, BARS vs PROFILE view, king/floor/ceiling/gatekeeper classification, ZGL zero-gamma line, VEX arrows, magnetic strength bars
- **OVERLAY** tab — TradingView-style candles with GEX price lines, forward projection cone, volume profile, signal markers
- **HISTORY** tab — snapshot timeline for intraday GEX drift tracking
- **MTF** tab — king/floor/ceiling across all expirations

### Signal pathways

- **SOE engine** — 5-factor signal generator (Structure, King distance, S/R, IV environment, Macro) with A/A+/B+ grading, discipline layer (Kelly sizing, circuit breaker), contract quality gates
- **Mir momentum** — Discord listener + native scorer, sector-leader selection, 7-14 DTE swings
- **Scalp alerts** — 0DTE/1DTE SPY/QQQ structure patterns with VIX regime filtering
- **Runner tracker** — multi-day explosive breakout state machine
- **Swing scanner** — RS/trend/sector/options-quality watchlist

### UI tabs

`HEATMAPS · OVERLAY · SCANNER · SWINGS · FLOW · SWEEPS · BIGFLOW · SIGNALS · PORTFOLIO · SECTORS · HISTORY · MTF · EARNINGS · NEWS · GUIDE`

### Paper trading

- $20K simulated account with entry-at-ask/exit-at-bid slippage (no mid-price fantasy fills)
- Auto-open on SOE A/A+ signals + Mir Discord entries + scalp alerts
- MFE/MAE tracking, +25% partial exit to breakeven stop
- Notional-based position sizing (skip trade if 1 contract exceeds 1.5x target — prevents SPX blow-up)

---

## Project layout

```
GammaPulse/
├── docs/
│   ├── research/              # Session analyses, backtests, rule simulations
│   │   ├── SESSION_APR18_INDEX.md        # Weekly rules shipping
│   │   ├── SESSION_APR18_UW_PARITY.md    # Flow detectors build
│   │   ├── week_cohort_analysis.md
│   │   ├── theta_replay_summary.md
│   │   └── ...
│   ├── thetadata-options-api-docs.md
│   └── GROK_EVAL_PROMPT.md, GEMINI_..., PERPLEXITY_...
├── server/                    # FastAPI backend
│   ├── main.py                # all REST + SSE + WebSocket routes
│   ├── config.py              # .env settings
│   │
│   ├── thetadata.py           # ThetaData adapter (REST + WebSocket + NBBO cache)
│   ├── tradier.py             # Tradier (underlying quotes, candles, history)
│   ├── root_config.py         # per-root overrides (SPX div/strike-step, SPXW routing)
│   │
│   ├── gex.py                 # GEX/VEX math, ZGL solve, BSM gamma
│   ├── signals.py             # SOE 5-factor signal engine
│   ├── discipline.py          # Kelly, circuit breaker, base-rate tiers
│   ├── flow_alerts.py         # V/OI-inference flow scanner + sweep DB writes
│   ├── sweep_detector.py      # live ISO sweep stream consumer
│   ├── live_flow_aggregator.py  # live Golden/Tail transition detection + Telegram
│   ├── option_flow_daily.py   # per-contract-day aggregates + Golden/Tail classifiers
│   ├── signal_outcomes.py     # forward-return tracking + hit-rate aggregation
│   │
│   ├── paper_trading.py       # $20K simulated account + position lifecycle
│   ├── runner_tracker.py      # multi-day breakout state machine
│   ├── swing_scanner.py       # 5-source consensus watchlist
│   ├── scalp_alerts.py        # 0DTE/1DTE structure alerts
│   ├── discord_listener.py    # MirBot Discord → native cache
│   ├── telegram.py            # rate-limited push
│   │
│   ├── worker.py              # 300+ ticker scanner loop (tiered)
│   ├── snapshots.py           # SQLite snapshot store + daily closes
│   ├── cache.py               # in-memory ticker state cache
│   ├── db.py                  # single-writer SQLite queue (Actor pattern)
│   ├── stream.py              # SSE/WebSocket price streamer
│   ├── breadth.py             # NYMO/NAMO, VIX term structure, oil regime
│   ├── rts.py                 # Relative Trend Strength engine
│   ├── basket.py              # PIT quarterly sector selection
│   └── requirements.txt
├── scripts/                   # one-off runners + backfills
│   ├── backfill_sweeps.py     # ISO sweeps via /v3/option/history/trade_quote
│   ├── backfill_option_flow.py  # full aggressive flow daily aggregates
│   ├── backfill_outcomes.py   # forward returns per alert/signal
│   ├── thetadata_stream_smoke.py  # WebSocket transport smoke test
│   └── ...
└── web/                       # Vite + React frontend
    └── src/
        ├── App.jsx            # top-level, tab routing, lazy-loaded
        ├── api.js             # backend client
        ├── store.js           # zustand store
        ├── components/        # shared (Header, HitRateStrip, etc.)
        └── tabs/              # one file per tab
```

---

## Setup

### 1. ThetaData Terminal (primary data source)

1. Sign up at [thetadata.net](https://www.thetadata.net/) — **Options Standard tier ($80/mo)**
2. Download Theta Terminal JAR, place at `C:\Dev\ThetaData\ThetaTerminalv3.jar`
3. Create `C:\Dev\ThetaData\creds.txt` with your email + password
4. Launch:
   ```bash
   cd C:\Dev\ThetaData
   java -jar ThetaTerminalv3.jar
   ```
5. Confirm startup log shows `Subscriptions: Options: STANDARD`
6. Terminal must run whenever GammaPulse server is running (or set Task Scheduler auto-start on boot)

### 2. Tradier (secondary — underlying data)

Sign up at [developer.tradier.com](https://developer.tradier.com/). Sandbox is free and sufficient.

```bash
cp .env.example .env
# edit .env:
#   TRADIER_TOKEN=...
#   TRADIER_BASE_URL=https://api.tradier.com/v1
#   TELEGRAM_BOT_TOKEN=...         (optional — alerts to phone)
#   TELEGRAM_CHAT_ID=...
#   FINNHUB_API_KEY=...            (optional — earnings + news)
#   FRED_API_KEY=...               (free — macro regime data)
```

### 3. Backend

```bash
cd server
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
cd ..
uvicorn server.main:app --reload --port 8000
```

Startup logs to watch for:
```
[worker] Theta Greeks enabled — real-time delta/theta/vega/IV via OPRA
[STARTUP] Theta sweep detector enabled
[THETA_STREAM] connected, resubscribing N contracts
[SWEEP] subscribing to ~13000 contracts via Theta stream
```

### 4. Frontend

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api/*` to `http://localhost:8000`.

### 5. Historical backfill (optional but recommended)

For rich UI from day 1, seed the DB with a week of sweep + flow data:

```bash
# ISO sweep history (5 days, MVP watchlist, ~3 min)
python scripts/backfill_sweeps.py --days-back 5 --clean-first

# All aggressive flow for SPY/QQQ/SPX with wide strike coverage (~10 min)
python scripts/backfill_option_flow.py --days-back 5 --tickers SPY,QQQ,SPXW --strikes 100 --expirations 10

# Forward returns on existing alerts (rebuilds hit-rate cohorts)
python scripts/backfill_outcomes.py --days-back 60
```

---

## How it works

### Data pipeline

```
ThetaData WebSocket (port 25520)            Tradier REST
  │                                           │
  ├─ TRADE stream (per-contract)              ├─ underlying spot quotes
  │    + NBBO cache from QUOTE msgs           ├─ candle bars (5m/1d)
  │                                           └─ historical closes → snapshots.py
  ↓
ThetaStream.trades() async iterator
  │
  ├─ sweep_detector (ISO-only)
  │     → 30s time-bucketed rollups
  │     → flow_alerts.SWEEP rows
  │     → Telegram push @ $500K+ ISO
  │
  └─ live_flow_aggregator (ALL flow)
        → per-contract-day accumulator
        → Golden/Tail transition check every 30s
        → option_flow_daily upsert
        → Telegram push with A+/A/B/C/D grade on transition
```

### Worker cycle (300+ ticker scanner)

1. Pull spot quotes for tiered universe (tier 1 every cycle, tier 2 every 2, tier 3 every 4)
2. For each ticker, fetch full options chain from Tradier
3. Enrich with real-time Greeks from Theta (bulk `snapshot/greeks/first_order` + BSM-synthesized gamma)
4. Compute `compute_exp_data`:
   - `net_gex` per strike = `gamma × OI × 100 × spot² × 0.01` (signed by dealer side)
   - `net_vex` per strike = `vanna × OI × 100 × spot`
   - Node classification: king, floor/ceiling, gatekeepers, air pockets
   - ZGL (zero-gamma line), regime (POS/NEG), signal
5. Store in in-memory cache + SQLite snapshot (HISTORY tab + forward-return baseline)
6. Discipline layer checks (Kelly sizing, circuit breaker, base-rate tier)
7. Signal engine evaluates SOE 5-factor, Mir momentum, runner state

### API endpoints (highlights)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | worker status + market state |
| GET | `/api/confluence` | SPY/QQQ/IWM macro read |
| POST | `/api/chains` | full heatmap data per ticker list |
| GET | `/api/scanner` | 300+ ticker signal/regime grid |
| GET | `/api/alerts` | flow alerts (V/OI scanner) |
| GET | `/api/sweeps` | ISO-tagged sweep rollups |
| GET | `/api/flow/daily` | per-contract-day aggregates |
| GET | `/api/flow/golden` | GOLDEN FLOW matches |
| GET | `/api/flow/tail` | TAIL FLOW matches |
| GET | `/api/signals` | SOE signal history |
| GET | `/api/ab/results` | Book A vs Book B outcomes |
| GET | `/api/stats/hit-rate` | cohort-filtered forward returns |
| GET | `/api/portfolio` | paper account + positions |
| GET | `/api/swing-scanner` | watchlist with 5-source consensus |
| GET | `/api/breadth` | NYMO/NAMO + VIX/oil regimes |

---

## Session documentation

Every major work session documented in `docs/research/`. Recent:

- **[SESSION_APR18_INDEX.md](docs/research/SESSION_APR18_INDEX.md)** — Weekly cohort analysis + 4 discipline rules shipped + 3-week OOS Theta replay validation
- **[SESSION_APR18_UW_PARITY.md](docs/research/SESSION_APR18_UW_PARITY.md)** — Golden/Tail flow detectors + A+/A/B/C/D grading + SPX coverage
- **[theta_replay_summary.md](docs/research/theta_replay_summary.md)** — Out-of-sample engine edge validation
- **[week_cohort_analysis.md](docs/research/week_cohort_analysis.md)** — 91-trade post-mortem

---

## Philosophy

- **Signal quality > signal volume**. Better to see 1 A-graded alert/day than 50 noisy ones.
- **Data quality over inferred metrics**. ThetaData gives us raw OPRA; we compute our own analytics rather than trusting a black-box vendor.
- **Paper trade everything first**. THE ONE RULE: no live auto-execution on a new signal pathway until 30+ paper outcomes prove the hit rate.
- **Confluence beats standalone signals**. Mir + GEX + Golden Flow aligned > any one alone.

---

## Known limitations

- Live TAIL on mega-cap equities covers only ~5.6% OTM (subscription budget trade-off). SPX/SPXW covers full 14%.
- Hit-rate cohorts need 4-6 weeks of live alerts to be statistically meaningful. Currently using backfilled sweep outcomes as proxy.
- SOE signal direction normalization has gaps — some cohort queries return n=0. Documented for future debug.
- Holiday skips not implemented in trading-day calc (acceptable — ~0-2 days slop/year).

---

## License

Personal / educational clone. Don't use for live trading without validating math against your own data source first.
