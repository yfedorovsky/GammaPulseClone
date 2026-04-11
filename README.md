# GammaPulse Clone

A full-stack clone of GammaPulse Pro — a real-time options analytics dashboard
showing per-strike Gamma Exposure (GEX) and Vanna Exposure (VEX) across 300+
tickers, plus signals, scanner, flow, overlay charts, history, and multi-
timeframe views.

This clone was reverse-engineered from the live app at gammapulse.rstechnology.org
and rebuilt from scratch using **Tradier** as the options data provider.

## Stack

- **Backend**: Python 3.11+, FastAPI, httpx, SSE, SQLite
- **Frontend**: React 18, Vite, Zustand, lightweight-charts (from TradingView)
- **Data**: Tradier `/markets/options/chains` (with greeks)

## Features

- **HEATMAPS** — MULTI (3-5 tickers side by side) and FOCUS (one ticker, 1/3/5 expiration panels). BARS vs PROFILE view toggle. Strike window (20/30/40/60/80).
- **OVERLAY** — Candlestick chart with GEX price lines as orbs, king strike highlight, mini heatmap sidebar, trade idea generator.
- **SCANNER** — 300+ ticker sortable table with signal/regime filters, MTF side panel per selected row.
- **FLOW** — SCAN ALL mode for tier-1 tickers plus per-ticker detail with P/C ratio and unusual volume (vol/OI ≥ 2×).
- **HISTORY** — Timeline scrubber over snapshots persisted every worker cycle.
- **MTF** — Side-by-side king/floor/ceiling across all expirations for a ticker.
- **GUIDE** — Embedded cheat sheet documenting node types, signals, and controls.
- **Live streaming** — SSE price updates, auto-reconnect.
- **Confluence banner** — SPY/QQQ/IWM macro read updated every 2 minutes.
- **Persistent settings** — Watchlists, panel count, view mode, strike window, font zoom all saved to localStorage.

## Project layout

```
GammaPulse/
├── docs/
│   └── API_CONTRACT.md         # captured API shapes
├── server/                     # FastAPI backend
│   ├── main.py                 # routes
│   ├── config.py               # env settings
│   ├── tradier.py              # Tradier adapter
│   ├── gex.py                  # GEX/VEX math, node classification, signals
│   ├── tickers.py              # tiered universe (300+ symbols)
│   ├── cache.py                # in-memory ticker state cache
│   ├── worker.py               # background scanner loop
│   ├── snapshots.py            # SQLite snapshot store
│   ├── stream.py               # SSE price streamer
│   └── requirements.txt
└── web/                        # Vite + React frontend
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx             # top-level
        ├── api.js              # backend client
        ├── store.js            # zustand store
        ├── styles.css          # design tokens + layout
        ├── components/
        │   ├── Header.jsx
        │   ├── ConfluenceBanner.jsx
        │   ├── WatchlistTabs.jsx
        │   └── HeatmapPanel.jsx
        ├── tabs/
        │   ├── HeatmapsTab.jsx
        │   ├── OverlayTab.jsx
        │   ├── ScannerTab.jsx
        │   ├── FlowTab.jsx
        │   ├── HistoryTab.jsx
        │   ├── MtfTab.jsx
        │   └── GuideTab.jsx
        └── lib/
            ├── gex.js          # row coloring, signal explanation
            └── format.js       # number/price formatting
```

## Setup

### 1. Tradier API key

Sign up at https://developer.tradier.com — the sandbox is free and sufficient
for development. Grab your token from the dashboard.

```bash
cp .env.example .env
# edit .env and set TRADIER_TOKEN=...
```

For production/live data, change `TRADIER_BASE_URL` to `https://api.tradier.com/v1`
and use a brokerage-account token.

### 2. Backend

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cd ..
uvicorn server.main:app --reload --port 8000
```

The first worker cycle takes ~30-90 seconds for tier-1 tickers. Subsequent
cycles run every `SCAN_INTERVAL_SECONDS` (default 300s).

Health check: http://localhost:8000/api/health

### 3. Frontend

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api/*` to `http://localhost:8000`.

## How it works

### Worker cycle
1. Pull spot quotes for the tiered ticker universe (tier 1 every cycle, tier 2 every 2 cycles, tier 3 every 4 cycles).
2. For each ticker, fetch its full options chain from Tradier for up to 17 expirations with greeks.
3. Group contracts by expiration and compute `compute_exp_data` in `server/gex.py`:
   - `net_gex` per strike = `gamma × OI × 100 × spot² × 0.01`, signed by dealer side
   - `net_vex` per strike = `vanna × OI × 100 × spot`
   - Node classification: `king` (highest |net_gex|), `floor`/`ceiling` (strongest +GEX below/above spot), `gatekeeper` (top-6 intensity), `air` (near-zero intensity)
   - ZGL (zero-gamma line), regime (POS/NEG), signal (MAGNET UP / SUPPORT / PINNING / AIR POCKET / RESISTANCE / DANGER)
4. Store the resulting ticker state in an in-memory cache and a SQLite snapshot row for the HISTORY tab.
5. Between cycles, the SSE streamer polls Tradier `/markets/quotes` every second for subscribed tickers and pushes updates to all open EventSource connections.

### API endpoints
All shapes match the original app (see `docs/API_CONTRACT.md`).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/health` | worker status + market open state |
| GET | `/api/confluence` | SPY/QQQ/IWM (hardcoded) for the banner |
| POST | `/api/chains` | `{tickers, strikes}` → full heatmap data |
| POST | `/api/quotes` | batch spot prices |
| POST | `/api/stream/subscribe` | add tickers to SSE set |
| GET | `/api/stream/prices` | SSE, emits `data: {...}` every ~1s |
| GET | `/api/scanner` | all cached tickers with signal/regime |
| POST | `/api/signals/log` | no-op ack (for accuracy tracking) |
| GET | `/api/history?ticker=X` | clone-only: snapshot series |
| GET | `/api/mtf?ticker=X` | clone-only: MTF table |
| GET | `/api/flow/{ticker}` | clone-only: detail flow |
| GET | `/api/flow/scan` | clone-only: flow scan across cache |

## Notes on accuracy

- The live app uses Schwab for data by default; this clone uses Tradier. The shapes are identical but values will differ slightly because Tradier computes greeks server-side while Schwab does not.
- The OVERLAY chart uses synthetic candles as a placeholder for visual parity. Replace `synthCandles()` in `OverlayTab.jsx` with a real Tradier historical bars fetch (`/markets/history`) or Polygon adapter to get real price history.
- The guide and signal accuracy tracking are implemented; full per-signal win rate computation requires several days of worker runs to populate the snapshot table.

## License

This is a personal / educational clone. Don't use it for live trading without validating the math against your own data source.
