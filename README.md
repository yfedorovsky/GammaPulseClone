# GammaPulse

A real-time options analytics platform with **OPRA-level flow detection**, **gamma exposure mapping**, and **institutional insider-pattern signals** — wrapped in a **measurement-first validation discipline** that tags every signal with regime context, persists outcomes, and refuses to ship rules that aren't empirically defensible.

Originally reverse-engineered from [GammaPulse Pro](https://gammapulse.rstechnology.org/), now substantially beyond it in signal coverage AND in the rigor of the meta-system that decides which signals to trust.

> **What's new (May 20 2026 — Perplexity audit response):**
> Cross-LLM critique (Perplexity Sonar Reasoning Pro) flagged that filter
> decisions were being made on statistically-meaningless samples (n=16
> from one 62-min window, 95% CI 0-35%). Tonight's foundational ship:
> - **`server/alert_outcomes.py`** — performance database that logs every
>   fired alert with full regime context + backfills 1h/EOD/next-day
>   outcomes from intraday history. Without this, every filter threshold
>   is unfounded. Background loop runs every 30 min during RTH.
> - **`server/cluster_resolution.py`** — MIXED-bias clusters now muted
>   from Telegram but TRACKED for 15 min; if a same-ticker cluster
>   resolves to single-direction within the window, fires a high-EV
>   `⚡ CLUSTER RESOLUTION` alert.
> - **Earnings + IVR gates** — multi-day SOE alerts now check
>   `earnings_in_window` and block long-premium recommendations when an
>   ER falls inside DTE. IVR percentile rendered in alert body.
> - **0DTE runway gate** — replaces hard 14:30 cutoff with a runway-based
>   gate (≥45 min to close + VIX < 22 + non-PINNING regime).
> - **Per-ticker daily cap** — max 5 alerts/ticker/day (10 for SOE A+).
> - **CHAT_RELAY (Mir LOW) deprecated from Telegram** — only fires
>   with system convergence.
> - **Mir ENTRY requires system convergence** — addresses copy-trade
>   alpha decay by gating Mir alerts on SOE/flow agreement (HIGH-TRUST
>   channels bypass).
> - **GEX VIX conditioning** — when VIX ≥ 20 in NEG regime, GEX-derived
>   scores downgrade by 1 (per 8-yr SPY backtest: GEX directional edge
>   collapses at high VIX, p=0.44).
>
> See [docs/research/perplexity_alert_evaluation_prompt.md](docs/research/perplexity_alert_evaluation_prompt.md)
> for the full evaluation prompt and [Perplexity report](https://example.com/perplexity-report)
> for the brutal critique that drove these changes.

> **Earlier (May 19 2026 — first wave of Perplexity-driven filters):**
> SOE FADE WATCH muted, MIXED cluster muted, late-session 0DTE blocked,
> weak FLOW [MEDIUM] muted. 16/16 backtest alerts → 7/16 post-fix.

> **Earlier (May 13 2026):** Bug #10 (Discord listener extracted to
> standalone process), P1 close (universe cleanup 444→440), P2 hot-chain
> expansion (lower gates for hot tickers), GEX magnet entry alert, snapshot
> watchdog. [docs/research/alert_format_previews.md](docs/research/alert_format_previews.md)

> **Apr 27 2026:** Cross-LLM critique cycle (Gemini/Grok/OpenAI/Perplexity)
> independently converged on the system's biggest empirical finding:
> **score is inversely correlated with 1d outcome** (5.0+ score = 9% hit
> on n=33; 3.75-4.1 score = 67%). High-score fade rule shipped +
> convergence bonus demoted to flag-only + macro regime tagger added.
> See [docs/feedback/strategy_0427/](docs/feedback/strategy_0427/).

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

- **SOE engine** — 5-factor signal generator (Structure, King distance, S/R, IV environment, Macro) with A/A+/B+ grading, discipline layer (Kelly sizing, circuit breaker), contract quality gates. **Phase 6 finding: score is inversely correlated with 1d outcome at the high end** — auto-trade now blocked for score ≥ 4.8 with ⚠ FADE WATCH banner.
- **SETUP FORMING scanner** — Mir-style proactive scoring (0-10) for POS-regime + king-magnet + RTS leader + Mir sector basket + cheap IVP. Parallel rubric to SOE; persisted Apr 27 for outcome tracking.
- **NET FLOW alerts** — NCP/NPP rate-of-change regime (FLOW_LEADS_UP/DOWN, divergences, stalls). Persisted Apr 27 for outcome tracking.
- **0DTE confluence engine** — combines GEX + NetFlow + Sweep + Golden into 0-20 score, A+/A/B+/B/C grading. ⚠ MANAGE banner per Apr 27 audit (avg MFE +90% but avg end-of-90min -38% on n=5).
- **Mir momentum** — Discord listener + native scorer + Apr 27 cross-reference layer (looks back 30min, surfaces every system signal that agrees with Mir's direction inline on his Telegram alert)
- **Scalp alerts** — 0DTE/1DTE SPY/QQQ structure patterns with VIX regime filtering
- **Runner tracker** — multi-day explosive breakout state machine
- **Swing scanner** — RS/trend/sector/options-quality watchlist

### Macro regime layer (Apr 27 — shadow mode)

Tags every SOE alert with NONE / SOFT / HARD / A_ONLY based on:
- **Calendar pressure** — hours to next FOMC + weighted megacap earnings count (FAANG 1.0, sector leaders 0.7, others 0.2)
- **Participation tilt** — QQQ vs QQQE intraday return gap (>0.5pp = narrow leadership)
- **Concentration tilt** — SPY vs XMAG gap (>0.4pp = mag-7 carrying tape)
- **Vol state** — VIX/VIX3M ratio (>1.0 = backwardation = stress) + SPX SKEW (>145 = institutional put bid). Realtime via Tradier.
- **Modifiers** — healthy breadth clips HARD→SOFT (not NONE), post-event reset 2h after FOMC, vol stress upgrades NONE/SOFT→HARD

Telegram footer renders: `⚠ Regime: HARD — FOMC 45h | weighted megacap 7.4 (shadow)`. NO score/size modification yet — flips live IF Friday audit shows HARD WR ≥5pp below NONE on ~150-200 sample.

### Convergence detection (Apr 27 v2 — informational flag)

When a SOE fires AND a NET FLOW or large flow_alert (per-ticker tier floor) co-fires same direction within 30min, surface a 🔎 CONVERGENCE FLAG block. Per 4-LLM critique consensus, the score boost was REMOVED (correlated signals are not independent confirmation). Detection survives for postmortem analysis via the audit harness.

### Telegram alert types + suppression rules (post-5/20 audit)

The system fires ~30-80 alerts/day post-filtering. Every alert is also
logged to `alert_outcomes.db` for retroactive validation.

| Alert | Source module | Always fires? | Suppression rule |
|---|---|---|---|
| **🔥 SOE A+** | `signals.py` | Yes (force=True) | None — highest priority |
| **⚡ SOE A** | `signals.py` | Yes | Per-ticker daily cap (10) |
| **⚠ SOE FADE WATCH** | `signals.py` | **UI only** | Muted from Telegram (5/20) |
| **🧲 GEX MAGNET ENTRY** | `gex_magnet_entry.py` | Yes | 45 min cooldown per (ticker, magnet) |
| **⚡ CLUSTER RESOLUTION** | `cluster_resolution.py` | Yes | Only when MIXED→single-direction in 15 min |
| **🎯 0DTE Engine A+/A/B+** | `zero_dte_loop.py` | Yes | Cooldown 10 min per (ticker, dir) |
| **📈 0DTE EMA Pullback** | `scalp_alerts.py` | Conditional | Blocked if <45 min to close OR VIX≥22 OR regime PINNING/MIXED |
| **🟢/🔴 CLUSTER FLOW (single-direction)** | `flow_alert_filter.py` | Conditional | MIXED-* bias muted; <$10M muted |
| **🟢/🔴 FLOW [MEDIUM]** | `flow_alerts.py` | Conditional | V/OI<1.0 AND notional<$10M muted |
| **🎯 MIR ENTRY (system convergence)** | `discord_listener.py` | Conditional | Requires SOE/flow convergence unless from #challenge-account |
| **💬 MIR CHAT (low)** | `discord_listener.py` | **UI only** | Telegram only with convergence; otherwise DB-only |
| **👑 KING MIGRATION** | `king_migration.py` | Yes | Cooldown per ticker |
| **SETUP FORMING** | `signals.py` | Yes | Top 3 by score per cycle |
| **🚨 SNAPSHOT WATCHDOG** | `snapshot_watchdog.py` | On alarm | Snapshots silent >10 min during RTH |

**Universal gates** (apply to all):
- Per-ticker daily cap: 5/day normal, 10/day priority (SOE A+, MIR ENTRY)
- Earnings-in-window block: long-premium SOE alerts with DTE≥2 skip when
  an ER falls inside the contract window
- 30-min `ZERO_DTE_TELEGRAM_FORMAT=clean` (default) — clean alert
  formatter; set `=full` for legacy multi-banner format

### Performance database (`alert_outcomes.db`)

Every fire is logged with:
- Context at fire time: spot, king/floor/ceiling, GEX regime, VIX, IVR,
  earnings_in_window, dte
- Plan: target_spot, stop_spot, entry_price
- Outcomes (backfilled by `alert_outcomes.run_outcome_backfill_loop`
  every 30 min): 1h verdict, EOD verdict, next-day verdict, spot
  MFE/MAE, target_hit_ts, stop_hit_ts

Query helpers:
- `get_win_rate_by_type(days=30)` — WR per alert type
- `get_win_rate_by_type_and_regime(days=30)` — WR by VIX regime (LOW/MED/HIGH)

After 60-120 trading days of data, every filter threshold can be
recalibrated empirically vs the current "logic and intuition" basis.

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
│   ├── net_flow.py            # NCP/NPP per-ticker rolling aggregator
│   ├── net_flow_signals.py    # NET FLOW regime detector + Telegram + persistence
│   ├── net_flow_fast.py       # 10s sub-minute aggregator for 0DTE
│   ├── zero_dte_engine.py     # 0DTE confluence scoring (0-20)
│   ├── zero_dte_loop.py       # 0DTE async loop + DB persistence
│   ├── zero_dte_telegram.py   # 0DTE alert formatter + ⚠ MANAGE banner
│   ├── king_migration.py      # live king-flip detector (separate DB)
│   ├── macro_regime.py        # Apr 27 — calendar pressure + breadth + vol state
│   ├── macro_context.py       # regime alignment + stress composite + forecast cells
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
├── scripts/                   # operational + research scripts
│   ├── preflight_monday.py    # daily pre-market sanity check
│   ├── weekly_digest.py       # Friday EOD WR digest by source_type + regime tag
│   ├── trade_journal.py       # minimal manual trade journal (6 fields)
│   ├── glw_earnings_primer.py # earnings cascade scanner (auto-expires)
│   ├── track_tsm_outcomes.py  # ad-hoc TSM signal tracker
│   ├── backtest_alerts_today.py  # parse Telegram alerts, pull ThetaData, MFE/MAE
│   ├── earnings_week_implied.py  # ATM straddle implied move per ticker
│   ├── weekend_research.py    # Sunday research synthesis (Finnhub macro layer)
│   ├── qm_universe_refresh.py # weekly Qullamaggie momentum cohort refresh
│   ├── backfill_sweeps.py     # ISO sweeps via /v3/option/history/trade_quote
│   ├── backfill_option_flow.py  # full aggressive flow daily aggregates
│   ├── backfill_outcomes.py   # forward returns per alert/signal
│   ├── thetadata_stream_smoke.py  # WebSocket transport smoke test
│   └── ...                    # ~30 total — see docs/SCRIPTS_CHEAT_SHEET.md
├── backtest/                  # research + validation harnesses
│   ├── regime_convergence_audit.py  # KEYSTONE — WR by regime + score band
│   ├── slippage_model.py      # nonlinear per-name options slippage
│   ├── grade_audit.py         # SOE score-vs-outcome inversion analysis
│   ├── replay_2022.py         # 2022 bear-regime existential test (PASSED — flat)
│   ├── setup_forming_replay.py  # SETUP FORMING historical hit rate
│   └── ...                    # ~40 total research scripts
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

## Validation harness

The Friday EOD routine to evaluate the live shadow-mode rules:

```bash
python scripts/backfill_outcomes.py --days-back 7        # populate forward returns
python scripts/weekly_digest.py --utf8                   # WR by source_type + regime
python backtest/regime_convergence_audit.py --days 14    # keystone — fade-rule verdict
```

The audit emits 6 slices ending with a HEADLINE VERDICT block:
- **PROMOTED A's vs ORIGINAL A's by regime tag** (decides convergence keep/kill)
- **All SOE WR by regime tag** (decides macro filter keep/kill)
- **WR by signal_type × regime** (which setups degrade most)
- **Promoted A's by time-of-day** (late-day = hedging vs initiation)
- **Convergence flag × score band** (does flagging add info per band?)
- **HIGH-SCORE FADE WATCH thesis verdict** (n=33 sample currently shows 9% hit, -0.53% avg = 4-LLM thesis confirmed)
- **Self-rated felt_quality vs realized outcomes** (joins trade_journal entries)

Cross-LLM critique cycle docs (paste-ready prompts + 4 LLM responses):
- **[docs/feedback/strategy_0427/](docs/feedback/strategy_0427/)** — Apr 27 (high-score fade rule + convergence demotion + vol regime)
- **[docs/feedback/strategy_0426_pivot/](docs/feedback/strategy_0426_pivot/)** — Apr 26 (Phase 6 cohort tier + slippage)
- **[docs/feedback/strategy_0425/](docs/feedback/strategy_0425/)** — Apr 25 (IV-zone validation kill)

---

## Session documentation

Every major work session documented in `docs/research/`. Recent:

- **[memory/phase6_critical_findings.md](memory/phase6_critical_findings.md)** *(in user's Claude memory dir)* — Apr 26-27 weekend that stripped phantom alpha. Cohort tier restructure (16 → 7 auto-trade names), score-PnL inversion finding, 2022 replay PASS, structural risk-factor guard. Required reading.
- **[docs/SCRIPTS_CHEAT_SHEET.md](docs/SCRIPTS_CHEAT_SHEET.md)** — when to run each of the ~30 scripts (daily/weekly/monthly cadences + ad-hoc)
- **[SESSION_APR18_INDEX.md](docs/research/SESSION_APR18_INDEX.md)** — Weekly cohort analysis + 4 discipline rules shipped + 3-week OOS Theta replay validation
- **[SESSION_APR18_UW_PARITY.md](docs/research/SESSION_APR18_UW_PARITY.md)** — Golden/Tail flow detectors + A+/A/B/C/D grading + SPX coverage
- **[theta_replay_summary.md](docs/research/theta_replay_summary.md)** — Out-of-sample engine edge validation
- **[week_cohort_analysis.md](docs/research/week_cohort_analysis.md)** — 91-trade post-mortem

---

## Philosophy

- **Measurement before behavior**. Ship hypothesis → instrument → run under fire → decide off data. Macro regime tag and convergence detection both run shadow-mode this week, evaluated Friday by `backtest/regime_convergence_audit.py`.
- **Signal quality > signal volume**. Better to see 1 alert/day with proven edge than 50 noisy ones.
- **The system can be wrong about its own setups**. The Phase 6 inversion finding (5.0+ score = 9% hit; 3.75-4.1 score = 67%) is the empirical proof. Auto-trade rules now respect this — score ≥ 4.8 is BLOCKED, not promoted.
- **Data quality over inferred metrics**. ThetaData gives us raw OPRA; we compute our own analytics rather than trusting a black-box vendor.
- **Confluence is sometimes concentration, not confirmation**. Per 4-LLM critique consensus: when SOE + NET FLOW + sweeps + Mir all agree, you may be seeing one institutional event projected through 4 lenses, not 4 independent confirmations. Convergence is now a flag (informational), not a score boost.
- **Paper trade everything first**. No live auto-execution on a new signal pathway until 30+ paper outcomes prove the hit rate net of slippage.
- **Cross-LLM critique cycle for high-stakes changes**. Same self-contained prompt to Gemini/Grok/OpenAI/Perplexity; ship on convergence. Documented 3× now (Apr 25 IV-zone, Apr 26-27 cohort tier, Apr 27 fade-rule).

---

## Known limitations

- Live TAIL on mega-cap equities covers only ~5.6% OTM (subscription budget trade-off). SPX/SPXW covers full 14%.
- Macro regime tagger is in **shadow mode through end of Apr 28-29 FOMC week**. Tag and footer render but don't modify score/size yet. Activation requires ~150-200 HARD-tagged signals showing materially different WR than NONE-tagged (per Perplexity statistical critique, the original 5pp threshold may need tightening to ~300-500 samples for true significance under options return variance).
- Auto-trade cohort tier still LIQUID + MEDIUM only (7 names: MU, SNDK, AAOI, CAMT, CIEN, GLW, VICR) per Phase 6 slippage measurement. Other cohort names log signals but don't auto-execute.
- SOE signal direction normalization has gaps — some cohort queries return n=0. Documented for future debug.
- Holiday skips not implemented in trading-day calc (acceptable — ~0-2 days slop/year).
- Trade journal is voluntary entry — won't catch trades unless user explicitly logs. Audit Slice 6 (felt_quality vs outcome) only populates if user runs `python scripts/trade_journal.py add` after each take.

---

## License

Personal / educational clone. Don't use for live trading without validating math against your own data source first.
