# Session Index — June 2-4, 2026 (Pro Tier Upgrade + Full Detection Stack)

**Final HEAD: `849a6a2`**
**Branch: `main`** (pushed to `origin/main`)
**Duration: ~36 hours wall-clock across 3 trading sessions**
**Test coverage: 74 tests across 5 suites, all passing**

## TL;DR — what shipped

10 production commits, 7 new server modules, 6 test scripts, 4 operational
scripts, and a $80→$160/mo ThetaData tier upgrade. The system now has 5
independent institutional-signal detectors layered on top of full-OPRA
streaming. Tomorrow's first market open with this stack is **6/5 9:30 AM ET**.

```
849a6a2 fix: classify whale BEFORE noise filter (NBIS catch)
3f15abc feat: dollar-driven whale-strike detector (task #41)
e109e13 test: comprehensive unit test suite (52 tests across 4 modules)
d301605 fix: P0 side-detection redux — RKLB 121C class miss (task #43)
667f7d1 chore: operational scripts — GC, freshness verify, tracker growth
8f892ce feat: flow_alerts noise filter — 327K → 5K alerts/day (98.6%)
db3b952 feat: ThetaData Pro tier upgrade — 7.5K → 45K subscription budget
03dc4f1 feat: Conviction Booster override + Mir TP dispatch tracking
53dcf1d feat: Triple Confluence detector — INFORMED FLOW + king + SOE
9a40a34 Volatility Regime tag (Friday baseline, prior session)
```

## Detection stack now live

| Layer | Module | Catches | Volume/day estimate |
|---|---|---|---|
| **INFORMED FLOW** | `flow_alerts._classify_insider_signature` | Short-dated V/OI shock (META 0DTE, RKLB 7DTE) | ~80-200 alerts |
| **WHALE** | `flow_alerts._classify_whale_signature` | Long-dated big-dollar accumulation (CVS, NBIS) | ~350 Telegram fires |
| **INFORMED CLUSTER** | `informed_cluster.py` | 3+ INFORMED FLOW strikes same direction | ~5-15 fires |
| **TRIPLE CONFLUENCE** | `triple_confluence.py` | INFORMED FLOW + king mig + SOE A+ aligned | ~5/day |
| **CONVICTION BOOSTER** | `conviction_booster.py` | A-grade SOE w/ broken IV but multi-factor confirmation | 1-3 overrides/day |

## Module-by-module

### `server/triple_confluence.py` (new, 432 lines)

When INFORMED FLOW + king migration + SOE A+ all converge on the same ticker
in the same direction within 4 hours, fire one high-priority Telegram alert
instead of the user mentally composing 3 separate signals.

Motivated by MRVL 5/28 missed signal stack. Threshold tuned against backtest:
27 confluences in 5 days (~5/day), MRVL 5/28 BULL fires correctly.

**Gates:**
- INFORMED FLOW ≥2 unique (strike, exp) combos same direction
- SOE ≥1 A+ signal (no A-only fallback)
- King migration ≥1 QUALIFIED with delta ≥1.5% of spot
- Index ETFs excluded
- 4-hour rolling window, once-per-ticker-per-direction-per-day dedup

### `server/conviction_booster.py` (new, 349 lines)

Multi-factor 0-100 score that overrides the `is_broken_a_combo` IV gate when
≥60 confirming factors agree. Audit found 4 SOE A signals (CRDO/HOOD/HIMS/SHOP)
silently blocked from Telegram by the IV-too-elevated gate despite perfect
multi-factor conviction — estimated suppression cost ~$9.1K on 6/2 alone.

**5 factors:**
1. Daily EMA stack (30 pts max)
2. Sector ETF strength (15 pts max)
3. Multi-day SOE repeat pattern (25 pts max)
4. Pre-fire INFORMED FLOW (15 pts max)
5. Today's bullish call-buy notional (15 pts max)

**Threshold: ≥60** overrides for Telegram dispatch only (auto-trade still
respects is_broken_a_combo).

Also shipped: `telegram_sent` column on `soe_signals` + Mir TP query filter
so the 1 PM "open winners" message only shows signals that actually reached
Telegram.

### `server/sweep_detector.py` (Pro tier expansion)

Raised every subscription ceiling to match ThetaData Pro:
- SUBSCRIPTION_BUDGET 7,500 → 50,000
- SUBSCRIPTION_TARGET 7,400 → 45,000
- SUBSCRIPTION_MAX_PLANNED 7,400 → 45,000
- THETA_MAX_STREAMS 500 → 45,000 (env var)

Per-tier budgets scaled 6x. Strike radii expanded 2-3x:
- TIER2_OTM_COVERAGE_PCT 0.10 → 0.50 (±50% catches RKLB-class)
- FLOW_FULL_COVERAGE_PCT 0.10 → 0.25
- FLOW_REDUCED_COVERAGE_PCT 0.05 → 0.15
- FLOW_MIN_COVERAGE_PCT 0.025 → 0.08

worker.py warmup now primes Tier2 thematic names so Phase 1 subscription
planning has spot data for RKLB/COIN/MSTR/ARM/etc.

start_gammapulse.bat sets `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` to
prevent the em-dash charmap crashes in phase2 logs.

### `server/flow_noise_filter.py` (new, 271 lines)

98.6% reduction: 327K raw alerts → 5K kept. Five fixes in one module:

1. **Contract-snapshot dedup** — only insert if new contract OR V/OI crossed
   meaningful band (10, 25, 50, 100, 250) OR 30+ min since last fire
2. **Drop LOW conviction at insert** — 66.5% of alerts never trigger anything
3. **Drop side=MID under $1M notional** — 49.2% MID rate was P0 bug residue
4. **Per-ticker chop suppression** — TSLA 6/5 today: $9.2B bull / $9.2B bear =
   0.1% bias = textbook chop, INFORMED FLOW dispatch suppressed
5. **Cross-expiration directional bias** — `GET /api/flow/bias/{ticker}`
   returns per-expiration verdict (CHOP / MILD / BULL / STRONG_BULL / BEAR /
   STRONG_BEAR) — surfaces TSLA-class "weekly chop but monthly bull" patterns

### `server/flow_alerts.py` updates

**Index ETF carve-out** — SPY/QQQ/SPX/IWM excluded from `tracked_trades`
creation. Index ETFs were dominating HIGH conviction tracker rows because
their baseline volume + notional auto-cleared score≥5 without any genuine
informed-flow signal. Pre-fix tracker hit 989K active rows by 6/2 morning.

**Whale classifier `_classify_whale_signature`** — task #41 implementation.
Catches CVS/NBIS-class accumulation signature distinct from INFORMED FLOW.

**Order fix (`849a6a2`)** — whale classification now runs BEFORE noise filter
so LOW-conviction whale signatures aren't dropped before being detected.
Promote whale-tagged LOW → MEDIUM to survive the filter.

**P0 side-detection redux (`d301605`)** — task #43. V/OI ≥15× AND vol > oi
now returns ASK unconditionally, bypassing the buggy "bottom-quartile = seller"
deferral that mis-tagged HPE / META 620C / RKLB 121C as BID.

`tick_side_tracker.py` window extended 60s → 30 min so the rolling NBBO
classifier retains sweep history through chain-snapshot lifecycle.

### Operational scripts

- `scripts/gc_pre_restart.py` — conservative cleanup (closes ACTIVE >24h)
- `scripts/gc_aggressive.py` — nuclear cleanup (closes ALL ACTIVE)
- `scripts/verify_freshness.py` — multi-signal backend health check
- `scripts/tracker_growth_check.py` — runaway-risk monitor
- `scripts/backtest_triple_confluence.py` — TC regression test

### Test suites

```
scripts/test_side_detection_p0.py    — 9 cases (RKLB/HPE/META/ABNB/GLD/INTC/MU + 2 negative)
scripts/test_triple_confluence.py    — 19 tests (direction normalization, exclusions, thresholds)
scripts/test_noise_filter.py         — 16 tests (dedup, LOW/MID drops, chop detection)
scripts/test_conviction_booster.py   — 8 tests (sector mapping, threshold, integration)
scripts/test_whale_detector.py       — 22 tests (all 7 gates + canonical CVS)
scripts/run_all_tests.py             — master runner
```

74 tests, 0 failures.

## Validation case studies

### RKLB 121C 6/18 (`d301605` — side-detection fix)
- FL0WG0D screenshot 6/4 15:50 ET — 750-contract ASK sweep at $11.00 avg ($825K)
- Our system tagged BID BEARISH LOW at 16:04:59 (14 min late, wrong direction)
- Post-fix: V/OI 21× → unconditional ASK return

### NBIS 350C 9/18 (`849a6a2` — whale order fix)
- FL0WG0D 6/4 13:48 PM tweet — 729 ASK at $35.65 ($2.6M sweep at 13:40)
- Pre-fix: all 29 alerts dropped by noise filter LOW gate (vol 918 < 2000)
- Post-fix: WHALE 🐋 fires at 14:07:02 ET = **19 min after FL0WG0D tweet**

### CVS 100C 8/21 (test case documentation)
- FL0WG0D 6/4 ~14:40 ET — 3,000 ASK at $3.41 ($1.02M sweep)
- 78-DTE long-dated with V/OI only 2.3× — INFORMED FLOW correctly rejects
- WHALE detector catches because $1M+ ASK + vol/oi ≥0.30 + ASK side

### MRVL 5/28 (Triple Confluence motivation)
- 4× INFORMED FLOW 320C 7/17 BULLISH ASK + 4× A+ SOE + king migration UP
- We caught all 3 signals individually 3 minutes BEFORE PETROAI's Twitter tweet
- Triple Confluence detector would have fired one composite Telegram alert
- 5/28 first fire would have been the loudest signal of the week

## Today's portfolio snapshot (for restoration context)

User trades Fidelity (large account) + E-Trade (small). Across the 3-day
window:

- **Friday 5/29**: $200,327 NAV / $80K cash (40%) after DELL ladder banking
- **Monday 6/1**: $219,943 NAV (+9.79% on Computex) / $80K cash (36%)
- **Tuesday 6/2**: $222,167 (+1% midday)
- **Wednesday 6/3** (no session note)
- **Thursday 6/4** (this session): trading day spanning RKLB/CVS/NBIS audits

Key positions referenced:
- NVDA 240C 7/17 ×6 (+143% total)
- MSFT 500C 1/15/27 ×4 (+102%)
- DELL 470C 7/17 ×2 (the Computex catch)
- INTC stack ×24 contracts + 100 shares (9.6% port concentration)
- ALAB 350C 6/5 ×2 (Mir-recommended)
- META 640C 6/12 ×2 + 7/17 ×4 (recent adds)
- RKLB 7/17 150C ×4 (followed correct thesis at safer strike vs whale 210C)
- HPE 47C 6/5 ×2 (earnings homerun, +400%)

## Backtest impact at end of session

| Layer | Volume |
|---|---|
| Raw flow_alerts/day | 327,024 (pre-filter) |
| After noise filter | 5,018 (98.5% reduction) |
| WHALE DB-tagged ($1M+) | 1,286 |
| WHALE Telegram ($3M+) | 352 (~22/hr) |
| INFORMED FLOW alerts | ~22 today |
| SOE A/A+ Telegram-sent | 196 |
| Triple Confluence fires | 0 today (would have been ~5 historical) |
| Tracker ACTIVE | bounded by index-ETF carve-out + LOW gate |

## What's NOT yet live (next priorities)

### **Task #44 (PRIORITY)** — Beat FL0WG0D latency

Current NBIS catch: 19 min after FL0WG0D tweet, 27 min after sweep.

The sweep_detector already runs on real-time OPRA stream and has tick-level
NBBO classification. The 19-min latency comes from chain-snapshot scanner
cadence — not from data unavailability.

Plan: extend sweep_detector to fire WHALE Telegram alerts DIRECTLY from
the OPRA stream when a single contract accumulates ≥$3M ASK in a 30-60s
rollup window. Bypasses chain-snapshot entirely.

Target: sub-30-second latency from OPRA print to Telegram. FL0WG0D's
pipeline takes ~8 minutes from sweep to tweet — beating that means
catching the signal before the audience sees the tweet.

Implementation outline:
1. New function in `sweep_detector.py`: `_check_whale_dispatch(rollup)`
2. Called every 30s in heartbeat or per-rollup
3. Per-contract rolling notional bucket (60s window)
4. Fire WHALE Telegram when: $3M ASK accumulated + not chop + not excluded
5. Bypass noise filter (it's chain-scan dedup, doesn't apply to real-time)
6. Per-contract dispatch dedup (don't fire same contract 4×/hour)
7. New regression test in `test_whale_detector.py`

### Other pending tasks

- (none — task list cleaned, only #44 active)

## Pre-bell restart sequence (every market open)

```powershell
cd C:\Dev\GammaPulse
Get-Process python | Stop-Process -Force
python scripts/gc_aggressive.py           # nuke tracker carryover
.\start_gammapulse.bat                    # load all detectors
# Wait 90 sec
python scripts/verify_freshness.py        # confirm tiers refreshing
python scripts/run_all_tests.py           # confirm prod code matches tests
```

After restart, watch the log for:
- `[SWEEP] subscription plan: 45000 contracts (MVP=25001, Tier2=8000, ...)`
- `[CONVICTION] OVERRIDE` lines on broken-A signals
- `[TRACKER] ACTIVE` staying under 1,000

## Config tunables (env vars + module constants)

- `THETA_MAX_STREAMS=45000` (`.env`)
- `WHALE_MIN_NOTIONAL = 1_000_000` (`flow_alerts.py`)
- `WHALE_TELEGRAM_NOTIONAL = 3_000_000` (`flow_alerts.py`)
- `WHALE_MIN_VOL = 500`
- `WHALE_MIN_VOL_OI_RATIO = 0.30`
- `CONVICTION_OVERRIDE_THRESHOLD = 60` (`conviction_booster.py`)
- `CHOP_BALANCE_PCT = 0.10` (`flow_noise_filter.py`)
- `CHOP_MIN_NOTIONAL = 5_000_000`
