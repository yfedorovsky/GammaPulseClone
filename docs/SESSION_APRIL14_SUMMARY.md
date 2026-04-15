# Session Summary — April 14, 2026 (Web App Session 2)

**Duration:** Full day (pre-market through after-hours)
**Commits:** 14 pushed to main
**Lines changed:** ~3,500 additions across 25+ files
**Theme:** First live trading day + critical infrastructure fixes

---

## Features Built

### A/B Test Infrastructure (Mir-only vs Mir+GEX)
- `ab_decisions` table: logs BOTH Book A (Mir+GEX) and Book B (Mir-only) decisions for every signal opportunity
- Book B uses fixed +2%/-1% targets, 3-factor gate, no GEX
- GEX contribution flags: entry_blocked, regime_blocked, improved_target, improved_stop
- `check_ab_outcomes()` tracks WIN/LOSS/EXPIRED + PnL per book independently
- `GET /api/ab/results` — summary stats, GEX contribution breakdown, by-conviction, daily time series
- Collapsible ABTestPanel in SignalsTab (Book A vs B comparison cards)
- **8,582 decisions logged on Day 1**

### Paper Trading Portfolio ($20K)
- `server/paper_trading.py` — full module: account state, position CRUD, auto-monitor
- Tables: paper_account, paper_positions, paper_trade_events, paper_equity_snapshots
- `open_position(signal_id)` — Kelly-computed contracts, deducts cash
- `close_position(position_id)` — PnL calc, logs to discipline trade_log
- `update_positions()` — runs every 30s, auto-closes on target/stop/expiry, tracks MAE/MFE
- Daily equity snapshots at 4:15 PM for curve charting
- API: GET /api/portfolio, GET /api/portfolio/history, POST /api/portfolio/open|close|reset
- **PortfolioTab.jsx** — MirBot-style layout: stats bar, open positions (monospace), equity curve (lightweight-charts), performance stats, closed trades with event journal
- "Paper Trade" button on every signal card in SignalsTab

### Setup-Forming Scanner (Proactive Mir-Style Ideas)
- `scan_setups()` — scans full universe every signal cycle
- Criteria: POS regime + king magnet + high RTS + Mir sector + low IVP + PM window bonus
- Monday penalty, bear regime filter (SPY 20d < 0 = skip all)
- 4-hour cooldown per ticker, max 3 alerts per scan
- Telegram push with king/floor targets, contract suggestion (strike/DTE/premium/bid-ask)
- Flow confirmation check (recent HIGH conviction flow in last 30 min)
- Relaxed contract quality gates for smaller tickers (OI 50 vs 500, spread 25% vs 10%)
- Based on PRODUCTION_STRATEGY.md: 256 trades, 59% WR, +142% avg

### Overlay Chart Improvements
- **Volume Profile** — ISeriesPrimitive plugin (`volumeProfilePrimitive.js`), replaces canvas overlay. Gray bars, POC highlight, auto-syncs zoom/pan. Later simplified to uniform gray (removed fake buy/sell coloring).
- **AVWAP click-to-anchor** — fixed stale closure bug (avwapModeRef synced via useEffect)
- **Earnings "E" markers** — new `/api/earnings/dates/{ticker}` endpoint (Finnhub), gold circle markers on daily chart
- **Extended Hours toggle** — renamed Sessions to "Ext Hrs" (Webull-style). After-hours: blue/purple tint. Overnight+premarket: faint gray. Volume also dimmed.
- **Custom ticker input** — text input at top of overlay sidebar, type any ticker + Enter
- **EMA labels** — already working (title + lastValueVisible on line series)

### Eval Prompts & Reviews
- `docs/GROK_EVAL_PROMPT.md` — comprehensive system review (8 dimensions, brutal questions)
- `docs/PERPLEXITY_RESEARCH_PROMPT.md` — updated 6 question sets (academic validation, 77 citations returned)
- `docs/GEMINI_RESEARCH_PROMPT.md` — updated 6 sections (engineering stress-test)
- `docs/CHATGPT_EVAL_ROUND3.md` — post-backtest review prompt
- Feedback archived: `docs/feedback/Perplexity_Feedback_0413.md`, `docs/feedback/Gemini_Feedback_0413.md`

---

## Critical Bugs Found & Fixed

### 0DTE Gate Structurally Impossible to Pass
- **Root cause:** `_greeks_age_seconds` was a snapshot from scan time, not computed live. Worker scans every 120s, SOE checks every 300s. By check time, cached age was always >60s threshold.
- **Fix:** Compute age from `_greeks_ts` at check time. Relaxed threshold 60s → 300s (matches scan/SOE cadence). Quote age also relaxed 180s → 300s.
- **Impact:** Zero SPY 0DTE alerts fired despite perfect PINNING setup at King $695 during power hour.

### NYMO Overbought Blocking All A-Grade Signals
- **Root cause:** Overbought threshold was 40 (basically any green day). NYMO at 164 penalized every bullish signal, capping at B+.
- **Fix:** Threshold raised 40 → 80. Added "don't fight the tape" rule: when GEX 3/3 bullish, breadth penalty capped at 0.1-0.15 instead of 0.25-0.5.
- **Impact:** Every signal today was B+ instead of A/A+. No Telegram alerts for signals.

### Massive Greeks Source = None on SPY
- **Root cause:** First-cycle catch-up of 328 tickers may have hit Massive rate limits. Some Tier 1 tickers didn't get enriched.
- **Fix:** First cycle now scans ALL tickers with Massive (no tier filtering on cycle 1).

### B+ Telegram Filter Broken
- **Root cause:** Checked `contract.get("oi")` but field name is `contract_oi`.
- **Fix:** Updated to `contract.get("contract_oi")`.

### Setup Alerts Missing Contract Details
- **Root cause:** `_select_contract()` quality gates (OI > 500, spread < 10%) too tight for mid-cap options (AAOI, COHR, KLAC).
- **Fix:** Added `relaxed=True` mode for setup alerts: OI > 50, spread < 25%, delta 0.15-0.75.

---

## Spot-Consistency Check (0DTE Safety)
- `massive.py` — extracts underlying spot from Massive snapshot, caches per ticker via `get_massive_spot()`
- `worker.py` — compares Massive spot vs Tradier spot every cycle. >0.3% divergence logs `[GEX_STALE_SPOT]` and flags `_greeks_spot_stale=True`
- `signals.py` — 0DTE gate hard-blocks signals when spot is stale
- Addresses Perplexity/Gemini finding: Massive $29 Starter uses 15-min delayed underlying

---

## Reliability Improvements
- **First-cycle catch-up:** ALL 328 tickers scanned on restart (was only Tier 1)
- **Mir signal persistence:** SQLite-backed cache, loaded on startup within 1-hour TTL
- **Windows auto-start:** `start_gammapulse.bat` for Task Scheduler
- **Flow OTM filter:** Strikes must be >= 1% OTM for Telegram (no ITM chase alerts)
- **DTE sweet spot:** Shifted 14 → 10, range 7-21 (backtest validated)
- **UNPROVEN Kelly:** Already capped at DEVELOPING level (17.13, was 29.67)
- **Default watchlist:** Expanded to 36 tickers (Mir core + mega caps + themes)
- **SNDK added to Tier 2** (Western Digital new name)

---

## External Reviews Summary

### Grok (Brutal)
- Engineering 9/10, GEX math 10/10, Edge probability 4/10
- "Sophisticated interface for following Mir signals with extra steps"
- Recommended A/B test → built it
- Spot-consistency check idea → built it

### Perplexity (77 Citations)
- NYMO formula correct, Kelly needs 50+ trades per tier
- POC has 90% reaction rate (Jozwicki & Trippner 2025)
- Massive $29 = 15-min delayed underlying (confirmed)
- ThetaData $40/mo is the upgrade path
- No academic paper studies GEX + RS combination

### Gemini (Engineering Focus)
- Temporal mismatch is real for 0DTE → fixed with spot-consistency check
- Bayesian scoring is future upgrade (needs 50+ AB decisions)
- ZGL migration tracking is the pro differentiator
- SVI/SABR smile interpolation is nice-to-have

### ChatGPT Round 3
- Engineering: 9.1/10 (was 8.5)
- Real-money readiness: 7.4/10 (was 6.0)
- Edge probability: 6.2/10 (new)
- "Round 3 is the first version I'd call legitimately close to live"
- "The next milestone is not more features — it is proving the narrow validated strategy survives"

---

## Day 1 Live Trading Lessons

1. **Server was down** during Mir signals (MSFT $400C, up 90%) — need auto-start
2. **NYMO 164 blocked all A-grade signals** on a massive green day — fixed
3. **0DTE gate was structurally broken** — never could have fired — fixed
4. **Mac Mini bridge dropped QQQ signal** — reliability issue on bridge side
5. **Flow alerts for ITM contracts useless** (premium already jacked) — OTM filter added
6. **Setup alerts lacked contracts** — quality gates too tight for mid-caps — relaxed mode added
7. **Massive Greeks enrichment spotty** after restart — first-cycle catch-up added

### Missed Trades (would have caught with fixes)
- SPY $692-694C 0DTE during 3:00 PM power hour (PINNING at King $695, POS regime, pullback to 15-min 8 EMA)
- MSFT $400C (Mir called it at $0.58, up 90% by 1 PM)
- MU (gap-and-go +9%, no pullback entry — need trend day detector)

---

## Mir RAG Findings (0DTE SPY Entry)
- **15-min chart** is Mir's primary timeframe (not 5-min)
- **8 EMA pullback** is the primary entry trigger
- **20 SMA** for secondary support/resistance
- **Daily 8 EMA** as trend filter (above = bullish)
- **1DTE preferred** over 0DTE
- **Internals confirmation** for trend days
- Need to integrate 15-min EMA tracking into scalp alert system

---

## Data Source Investigation
- Massive $29: "Real-time Greeks and IV" but on 15-min delayed underlying quotes
- ThetaData $40/mo Value: truly real-time OPRA + tick-by-tick Greeks + native vanna/charm
- Decision: stay on Massive until A/B test proves GEX adds value, then upgrade

---

## Session 3 — April 14 Evening

### Features Built (All Three Critical Priorities)

#### 1. Trend Day Detection (`server/worker.py`)
- `_detect_trend_day(ticker, spot)` — compares today's open to yesterday's close
- Three modes: `NORMAL` (<2% gap), `TREND_DAY` (2-4%), `EXTREME_TREND` (>4%)
- Cached per day per ticker (first worker cycle captures opening gap)
- Stored in state as `_trend_day` dict — consumed by signals.py and scalp_alerts.py
- Trend days skip PM window requirement for entries (gap-and-go)
- Extreme trend days reduce conviction (chasing risk)

#### 2. Mir Momentum Signal Engine (`server/worker.py` + `server/signals.py`)
- `_compute_mir_signal(ticker, spot, rts)` — native Mir scoring using `backtest/mir_scorer.py`
- Gates: approved sectors only, skip Mondays, SPY 20d regime filter, SMA 20/50/200, EMA 21>50, RTS >= 70
- Computes sector peer RS comparison from snapshot daily closes
- Score >= 4.0/6 → stores `MIR_MOMENTUM` signal in cache via `set_mir_signal()`
- Dual pathway in `generate_signals()`: Mir-originated signals use GEX as quality gate (not generator)
  - GEX quality gate: king above spot, positive gamma, king distance 0.5-3% (2+ issues = block)
  - PM window: 2:00-4:00 PM for normal days, 10:00 AM+ for trend days
  - Contract: `mir_mode=True` → 7-14 DTE, delta 0.35-0.50, skip 0DTE
- Existing GEX-only pathway completely untouched (additive, not replacement)

#### 3. 15-min 8 EMA Pullback Detection (`server/scalp_alerts.py`)
- `_refresh_bars(ticker)` — Tradier 15-min bars with 5-min TTL cache (2 API calls/5min max)
- `_compute_ema8(closes)` — standard 8-period EMA computation
- `_detect_ema_pullback(ticker, state)` — state transition detection:
  - `EMA_PULLBACK`: prev bar at/below EMA → current above = bullish bounce (Mir's #1 trigger)
  - `EMA_REJECTION`: prev bar at/above EMA → current below = bearish breakdown
  - `TREND_CONTINUATION`: gap-and-go day, price above EMA with momentum
- Time gate refactored per-ticker: normal days 1:30 PM+, trend days 10:00 AM+
- Integrated into existing alert loop alongside structure alerts

### Files Modified
- `server/worker.py` — `_detect_trend_day()`, `_compute_mir_signal()`, wired into `_compute_one()` and `_scan_cycle()`
- `server/signals.py` — Mir-originated dual pathway in `generate_signals()`, `mir_mode` param on `_select_contract()`
- `server/scalp_alerts.py` — 15-min bar cache, EMA8 computation, `_detect_ema_pullback()`, per-ticker time gate

---

## Next Session Priorities

### CRITICAL
1. **Mac Mini bridge reliability** investigation
2. **Prove the strategy with data** — let A/B test + paper portfolio run 30+ resolved decisions

### MEDIUM
3. Scanner: Mir Score column + green highlight for passing tickers
4. Overlay: "Mir Signal Active" badge + power hour countdown
5. Screenshot/export summary report
6. Heartbeat alerts (Telegram if server down > 5 min)

### LATER
7. ZGL migration tracking (intraday)
8. Bayesian scoring upgrade (needs 50+ AB decisions)
9. ThetaData migration ($40/mo)

---

## Files Created/Modified

### New Files
- `server/paper_trading.py` — paper trading portfolio module
- `web/src/tabs/PortfolioTab.jsx` — portfolio dashboard tab
- `web/src/lib/volumeProfilePrimitive.js` — VP ISeriesPrimitive plugin
- `docs/GROK_EVAL_PROMPT.md`
- `docs/CHATGPT_EVAL_ROUND3.md`
- `docs/feedback/Perplexity_Feedback_0413.md`
- `docs/feedback/Gemini_Feedback_0413.md`
- `start_gammapulse.bat`

### Modified Files
- `server/signals.py` — AB test logging, setup scanner, 0DTE gate fix, NYMO fix, DTE shift, B+ telegram, relaxed contracts
- `server/discipline.py` — compute_mir_only_decision()
- `server/main.py` — portfolio endpoints, AB results endpoint, init calls
- `server/massive.py` — spot extraction for consistency check
- `server/worker.py` — first-cycle catch-up, spot divergence tracking
- `server/cache.py` — Mir signal DB persistence
- `server/breadth.py` — NYMO threshold fix (40→80), turning-down threshold (0→60)
- `server/flow_alerts.py` — OTM filter, get_recent_flow()
- `server/trade_tracker.py` — paper trading monitor wired in
- `server/tickers.py` — +SNDK
- `web/src/tabs/OverlayTab.jsx` — VP plugin, AVWAP fix, earnings markers, ext hours, custom ticker
- `web/src/tabs/SignalsTab.jsx` — AB panel, paper trade button
- `web/src/components/Header.jsx` — +PORTFOLIO tab
- `web/src/App.jsx` — +PortfolioTab lazy import
- `web/src/api.js` — portfolio + AB + earnings dates endpoints
- `web/src/store.js` — expanded default watchlist

---

## Git Log (14 commits)
```
a0f434b Fix setup alerts: relaxed contract gates for smaller tickers
3acc11a Fix 0DTE gate: was structurally impossible to pass
3f3c098 Setup alerts now include contract, flow confirmation, cleaner format
dbb288d DTE sweet spot 7-14, auto-start script, ChatGPT Round 3 eval prompt
dd6a5f7 Setup-forming scanner + backtest-calibrated Mir momentum alerts
99be9d3 Fix scoring, bridge reliability, and first-cycle cold start
d8e4fde Paper trading portfolio — $20K account with MirBot-style dashboard
d4a73ae Ext Hours toggle + session coloring + expanded default watchlist
073b8d5 Add custom ticker input to overlay sidebar
36f06eb A/B test infrastructure + overlay chart fixes + 0DTE spot-consistency gate
(+ 4 earlier overlay fixes from session start)
```
