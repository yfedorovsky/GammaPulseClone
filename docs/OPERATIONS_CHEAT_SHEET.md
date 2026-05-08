# Daily Operations Cheat Sheet

**Purpose**: One-page reference for what to run, when, and with what parameters.
Covers pre-market prep, market open, intraday monitoring, EOD/aftermarket, and
weekly routines. Includes special handling for macro-event days.

All commands assume `cd C:\Dev\GammaPulse` and Python venv active.

---

## ☀️ Pre-Market (5:30 AM – 9:25 AM ET)

### Monday-only (one-time per week)

Two healthcheck scripts available. Use **preflight_monday.py** for the full
comprehensive check (sends a test Telegram); use **monday_healthcheck.py** for
a lighter quick check (~30 sec).

```bash
# HEAVY: comprehensive ~60-check preflight that exercises every code path
# and sends ONE test Telegram at the end.
# Exit codes: 0 = all green, 1 = warnings, 2 = errors (fix before starting)
python scripts/preflight_monday.py

# LIGHT: ~10 checks in ~30 sec — env creds, Tradier/E-Trade auth,
# DB files writable, last live activity timestamps. No Telegram test.
python scripts/monday_healthcheck.py
```

What `preflight_monday.py` validates:
- Every server module imports cleanly
- DB schema migrations applied to all DBs
- Live worker recent activity (last write timestamps)
- Telegram bot connection (sends test message)
- ThetaData reachability
- Databento cache freshness
- All env vars present

If `preflight_monday.py` fails (exit 2): STOP and fix before live worker start.

### Daily (every market day)

```bash
# Verify live worker is running (it should already be, from Sunday startup)
tasklist | findstr python   # see all python processes
# Look for the worker process; if not present, start it (see below)

# Optional watchlist-side flow check
python scripts/check_watchlist_flow.py
```

There is NO daily telegram-only healthcheck. If you want to verify Telegram
is working on a non-Monday, run `preflight_monday.py` (it'll send a test
message; safe to re-run on any day).

### Macro-event days (this week: Tue 5/5 ISM, Wed 5/6 QRA, Fri 5/8 NFP)

Macro day = high-variance day. **Adjust expectations, not the system.**

- ✅ **DO**: ensure `MACRO_EVENTS` dict has the day's events (already loaded for May 5-8)
- ✅ **DO**: read TraderMir's pre-market notes
- ✅ **DO**: review Alphatica GEX update if posted
- ❌ **DON'T** modify any gates or thresholds
- ❌ **DON'T** widen position sizes
- ❌ **DON'T** start any new live trade just before the event (-30 / +90 min window)

### If live worker isn't running

```bash
# Start the live worker (writes to structural_turns.db, zero_dte_alerts.db, snapshots.db)
python -m server.main
```

Live worker runs continuously. It pulls option chains every cycle, computes
GEX state, fires structural-turn and 0DTE alerts to telegram, persists to DBs.

---

## 🔔 Market Open (9:30 AM ET)

**Nothing manual.** Live worker handles everything.

What it's doing:
- Continuous chain refresh
- ST detector evaluating every minute on SPY/QQQ/IWM
- 0DTE alert generator running on the 5+ tickers it monitors
- Tape regime classifier tagging RANGE/MIXED/NOISY/TREND_UP/TREND_DOWN
- Spread tracker logging shadow-mode

**Watch the Telegram channel** for fires. If a 0DTE alert fires:

1. **Check the manage text** at the bottom — the rule is:
   - `TP +50% partial / +100% full / Stop -30%` (canonical)
   - **NO time stop** (decisively rejected by 6-month backtest)
   - Underlying invalidation acceptable as alternative stop
2. **Check ST confirmation** in the alert annotations
3. **Check tape regime** at fire time (banner in the alert)
4. **Check Alphatica/your GEX dashboard** for context

---

## 📊 Intraday Monitoring (9:30 AM – 4:00 PM)

### Quick checks during the day

```bash
# Today's alerts so far (count + outcomes still NULL)
python -c "import sqlite3; \
  c = sqlite3.connect('zero_dte_alerts.db'); \
  print(c.execute(\"SELECT COUNT(*) FROM zero_dte_alerts WHERE date(fired_at,'unixepoch','-4 hours')=date('now','-4 hours')\").fetchone())"

# Live ST fires today
python -c "import sqlite3; \
  c = sqlite3.connect('structural_turns.db'); \
  print(c.execute(\"SELECT COUNT(*) FROM structural_turns WHERE qualified=1 AND date(ts,'unixepoch','-4 hours')=date('now','-4 hours')\").fetchone())"
```

### Watch for these patterns (from May 4 forensic + 6-month backtest)

| Pattern | Meaning | Action |
|---|---|---|
| 5+ same-direction 0DTE alerts in 90 min | Chase pattern (May 4 = 11 bullish wipeouts) | Caution — this signals over-fitting to current move |
| ST fires 3+ times within 5 min, same spot | 1 episode, not 3 trades | Treat as one trade idea (episode_id grouping) |
| Tape regime flips RANGE→MIXED mid-day | Regime change, often signals trend break | Don't chase the prevailing direction |
| GEX flip near spot (within 0.3% of close) | Negative-gamma acceleration risk | Reduce size or skip |
| Macro event window flag | within ±30/+90 min of FOMC/CPI/NFP/QRA | Caution, expect wider ranges |

### DO NOT during intraday

- ❌ Run ad-hoc backfill on TODAY's data (data not yet T+1; SPX outcomes will be wrong)
- ❌ Re-run gates / change thresholds based on intraday performance
- ❌ Take alerts where the option mid-spread is > 10% (skip wide spreads)

---

## 🌙 EOD / Aftermarket (4:05 PM – 6:00 PM)

### Standard daily routine

```bash
# 1. Compute paired-trades outcome (gated alerts vs random equidistant baseline)
python -m server.paired_trades --date YYYY-MM-DD

# 2. NBBO-based outcome backfill (TP/Stop/Time-stop simulation)
python scripts/backfill_alert_outcomes_nbbo.py

# 3. Daily diagnostic summary (chase patterns, ST diagnostic, regime tags)
python scripts/daily_alert_summary.py --date YYYY-MM-DD
```

Replace `YYYY-MM-DD` with the trading day. Today = Tue 5/5/2026 → use `2026-05-05`.

### Output files generated

| Script | Output | Purpose |
|---|---|---|
| `paired_trades.py` | `paired_trades.db` rows | Bootstrap-CI ready P&L data |
| `backfill_alert_outcomes_nbbo.py` | `zero_dte_alerts_nbbo_outcomes` table | Real NBBO MFE/EOD per alert |
| `daily_alert_summary.py` | `docs/research/daily_summaries/YYYY-MM-DD.md` | Human-readable narrative |

### Sanity check after EOD run

```bash
# How many alerts got NBBO outcomes vs NO_DATA?
python -c "import sqlite3, pandas as pd; \
  c = sqlite3.connect('zero_dte_alerts.db'); \
  df = pd.read_sql('SELECT source, COUNT(*) FROM zero_dte_alerts_nbbo_outcomes GROUP BY source', c); \
  print(df.to_string())"
```

NO_DATA count should be ≤ 5% of total. If higher, ThetaData was unreachable
for some contracts — not a strategy issue, just a data issue.

### Macro-day EOD additions

After macro events (especially big ones — QRA, NFP), also run:

```bash
# Tag the day as MACRO_HEAVY in the daily summary
python scripts/daily_alert_summary.py --date YYYY-MM-DD --tag MACRO_HEAVY

# Record macro context in memory
echo "YYYY-MM-DD: macro event {QRA|NFP|...}, SPX move +/-X.X%" \
  >> docs/research/macro_day_log.md
```

---

## 📅 Weekly Routines

### Friday EOD (after market close)

```bash
# Cluster bootstrap CI on the running paired-trades sample
python scripts/paired_bootstrap_analysis.py

# Refresh Databento cache with this week's bars
python scripts/databento_append_recent.py --start MON --end FRI
```

The bootstrap analysis reports the **CI on (gated mean − random mean)** P&L.
This is the headline metric for Stage 1/2/3 falsification gating.

**Important**: Do NOT act on intermediate weekly CIs during Stage 1.
Stage 1 is futility-only; only Stage 3 allows efficacy decisions.

### Weekend (Sat-Sun)

```bash
# Re-rank top setups using updated 6-month + this week's data
python scripts/unified_setup_analysis.py
python scripts/unified_phase0_analysis.py   # walk-forward, slippage, dedup

# Log the week's setups in the watchlist
python scripts/weekly_setup_review.py    # generates docs/research/setups_week_YYYYMMDD.md
```

If you're doing live forward-window observation:

```bash
# Compare forward-window MFE distributions to backtest distributions
python scripts/forward_vs_backtest_comparison.py   # (write this once Phase 1 starts)
```

---

## 🎯 Phase 1 — Shadow Alerts (NOT YET DEPLOYED)

When you're ready to start the 30-day shadow-alert validation, the additional
scripts are:

```bash
# Start parallel signal detectors that LOG but don't fire telegram trades
python -m server.shadow_alert_worker   # writes shadow_alerts.db
```

Outputs to:
- `shadow_alerts.db` — every signal fire from the 4 candidate setups
  (pmh_break, sweep_pmh, orb15_break, ema_cross_imm)
- These are the post-Phase-0 robust setups (skip pml_break, vwap_2sd_fade,
  vwap_lose pending more data)

EOD addition during Phase 1:

```bash
python scripts/shadow_alerts_eod.py --date YYYY-MM-DD
# Computes NBBO outcomes for shadow alerts
# Compares forward MFE distribution to 6-month backtest distribution
```

---

## 🚨 If something breaks

### Live worker crashed

```bash
tail -100 logs/worker.log   # check error
python -m server.main       # restart
```

### Telegram alerts stopped firing

```bash
# preflight_monday.py sends a test Telegram at the end — re-run it
python scripts/preflight_monday.py
# Check TELEGRAM_BOT_TOKEN and CHAT_ID in .env if test fails
```

### ThetaData unreachable (port 25503)

```bash
curl http://127.0.0.1:25503/v3/option/history/quote \
  --data "symbol=SPY&expiration=2026-05-05&strike=720.000&right=C&start_date=2026-05-05&end_date=2026-05-05&interval=1m" \
  | head -10
# If 200 OK with data → fine
# If timeout → restart ThetaTerminal
```

### Databento cache stale

```bash
python scripts/databento_append_recent.py --start 2026-05-05 --end 2026-05-09
```

---

## Master command summary (most-used, copy-paste)

```bash
# Pre-market Monday — run ONE of these (preflight is more thorough):
python scripts/preflight_monday.py    # comprehensive + test Telegram
python scripts/monday_healthcheck.py  # lighter, no Telegram

# Pre-market daily — verify worker running:
tasklist | findstr python  # confirm live worker process alive

# EOD daily (replace date)
DATE=2026-05-05
python -m server.paired_trades --date $DATE
python scripts/backfill_alert_outcomes_nbbo.py
python scripts/daily_alert_summary.py --date $DATE

# Friday weekly
python scripts/paired_bootstrap_analysis.py
python scripts/databento_append_recent.py

# Weekend research
python scripts/unified_setup_analysis.py
python scripts/unified_phase0_analysis.py

# Diagnostic queries
python -c "import sqlite3; c=sqlite3.connect('zero_dte_alerts.db'); \
  print(c.execute('SELECT COUNT(*) FROM zero_dte_alerts').fetchone())"
```

---

## What is currently AUTOMATED vs MANUAL

| Task | Status | Notes |
|---|---|---|
| Live alert generation | 🤖 AUTO | Live worker runs continuously |
| Telegram delivery | 🤖 AUTO | Bot fires on each qualified alert |
| Tape regime tagging | 🤖 AUTO | At fire time |
| Spread shadow gate | 🤖 AUTO | Shadow-mode, logs only |
| Outcome backfill | ✋ MANUAL | Run EOD manually |
| Daily summary | ✋ MANUAL | Run EOD manually |
| Bootstrap CI weekly | ✋ MANUAL | Friday EOD |
| Setup re-ranking | ✋ MANUAL | Weekend |
| Shadow alerts (Phase 1) | ⚠️ NOT BUILT | Pending Phase 1 implementation |
| Live execution | ⚠️ NOT DEPLOYED | Paper-only until Phase 1 validates |

To reduce manual: run all EOD scripts via Windows Task Scheduler at 4:30 PM.
The user has not configured this yet.

---

## Today (May 5 2026, Tuesday) — specific plan

**This is a macro-heavy week**: ISM Services + JOLTS at 7:00 AM (red),
AMD earnings AC, Wed QRA at 8:30 AM, Fri NFP at 5:30 AM.

| Time | Action |
|---|---|
| 7:00 AM | ISM Services + JOLTS land. Markets may pre-position pre-open. |
| 9:25 AM | Verify live worker running. Check Alphatica or your GEX dashboard. |
| 9:30 AM | Market open. Live worker fires alerts. **Paper-only.** |
| 11:00 AM | Mid-morning check — was there a regime flip? Compare to May 4 pattern. |
| 4:00 PM | Market close. AMD earnings at 4:05 PM. |
| 4:30 PM | Run EOD routine: `paired_trades.py`, `backfill_alert_outcomes_nbbo.py`, `daily_alert_summary.py` |
| 5:00 PM | Review the day's alerts. Tag any patterns for forward-window log. |
| 6:00 PM+ | Optional: compare today's setups vs backtest expectations (`shadow_eod.py` once built) |
