# Weekly Trade Analysis — Session Handoff [SUPERSEDED]

> **Status as of 2026-04-18: fully worked through.** See
> [SESSION_APR18_INDEX.md](SESSION_APR18_INDEX.md) for the completed research
> narrative and shipped rules. This doc is kept for historical context —
> the priorities listed below have all been addressed:
> - ✅ 4PM signal gate fix (+ 4:15 index extension, + price_watch AH gate)
> - ✅ Mir Discord chat-relay parser (CHAT_RELAY signal_type)
> - ✅ Multi-week WR stability (internal bootstrap + Theta 3-week OOS replay)
> - ✅ Per-ticker/per-time/per-regime filters (rules #1, #2, #3b, #4 shipped)

**Context:** User wants to analyze this week's trades (Apr 14-18, 2026) across
all sources to answer the core question: **"Are our dozens of daily alerts
producing real winners, or mostly noise?"**

## The Hypothesis To Test

Working hypothesis (user's intuition): **"Dozens of daily alerts with only a
few REAL winners."**

If true: most of our alert pathways are high-noise. We should find which
pathway(s) actually produce edge and tighten or kill the rest.

If false (we get real signal across multiple pathways): we can keep the
current alert volume but maybe add filtering by cohort.

## What To Export Before Next Session

### 1. E*Trade CSV
**Path:** Accounts → Activity → Transactions → Export → CSV
- Choose date range: **2026-04-14 to 2026-04-18**
- Include options transactions
- Save to: `C:/Dev/GammaPulse/data/etrade_week_20260418.csv`

**Expected columns** (E*Trade varies):
- Run Date / Transaction Date
- Action (Bought/Sold/Expired/Assigned)
- Symbol (OSI format like `NVDA Apr 24 2026 200 Call`)
- Quantity
- Price
- Commission / Fees
- Amount
- Order Type

### 2. Fidelity CSV
**Path:** Accounts → Activity & Orders → Export → CSV
- Same date range
- Save to: `C:/Dev/GammaPulse/data/fidelity_week_20260418.csv`

**Expected columns** (Fidelity format):
- Run Date, Action, Symbol, Description, Security Type, Quantity
- Price, Commission, Fees, Accrued Interest, Amount
- Settlement Date

### 3. Our internal data (already on disk)

Tables in `snapshots.db` covering this week:

| Table | What it has | How to pull |
|---|---|---|
| `soe_signals` | Every SOE signal we fired (grade A/A+/B/B+) | `SELECT * FROM soe_signals WHERE ts > strftime('%s','2026-04-14')` |
| `paper_positions` | Auto-paper-trade positions (if any taken) | Fresh post-reset — only today's positions |
| `paper_trade_events` | Per-position event log (OPEN, PARTIAL_EXIT, CLOSE) | Linked via position_id |
| `runner_tracker` | DAY1_BREAKOUT, DAY2_CONFIRM, etc. | Filter by entry_ts |
| `flow_alerts` | Unusual flow detections | Filter by ts |
| `mir_signal_cache` | Discord Mir relay cache | Filter by ts |
| `tracked_trades` | Telegram alert history | Filter by ts |

Paper history pre-reset backup: `data/backups/paper_positions_pre_reset_*.csv`
(from Apr 16 night session — has the 22-trade -$3,943 history if useful).

## Analysis Plan For Next Session

### Step 1 — Build the unified trade table

Join Fidelity + E*Trade + our signals into one dataframe with columns:

```
ticker, strike, expiration, option_type,
action (BUY_OPEN | SELL_CLOSE | BUY_CLOSE | SELL_OPEN),
entry_ts, exit_ts, qty, fill_price,
pnl_dollars, pnl_pct, hold_duration,
# Attribution:
signal_source (mir | soe | runner | scalp | price_watch | manual),
signal_id (FK if algo-sourced),
signal_grade (A+ | A | B+ | B | null),
signal_time_lag_seconds (gap between alert and execution),
# Context at entry:
spot_at_entry, iv_at_entry, delta_at_entry,
vix_regime, oil_regime, spy_regime,
# Outcome:
is_win, max_favorable_excursion, max_adverse_excursion
```

### Step 2 — Compute cohort stats

**By signal source:**
```
Pathway           | N trades | Win rate | Avg PnL$ | Avg PnL% | Sharpe-ish
Mir Discord       | ?        | ?        | ?        | ?        | ?
SOE A/A+          | ?        | ?        | ?        | ?        | ?
SOE B+            | ?        | ?        | ?        | ?        | ?
Runner tracker    | ?        | ?        | ?        | ?        | ?
Scalp alerts      | ?        | ?        | ?        | ?        | ?
Price watches     | ?        | ?        | ?        | ?        | ?
Manual (no alert) | ?        | ?        | ?        | ?        | ?
```

**By ticker:**
- Win rate per ticker
- Are "pet" tickers (MSFT, AMD, AAOI) doing better than random?

**By time:**
- Opening drive (9:30-10:30) vs lunch chop (12:00-2:00) vs power hour (3:00-4:00)
- Day of week (Monday vs Friday)

**By regime:**
- VIX_LOW_FLAT vs VIX_LOW_RISING vs VIX_BULL_COMPRESS
- Oil regime present?

**By DTE:**
- 0DTE vs 1-2DTE vs 7DTE vs 14DTE+ win rates

### Step 3 — Signal-to-win attribution

For each winning trade, walk back the signal history:
- Did an alert fire within 2 hours before entry? Which pathway?
- Did MULTIPLE alerts fire — was it cross-confirmation?
- Time between alert and execution — faster = better?

For each losing trade:
- Was there a STOP signal / trim signal that was ignored?
- Did we have conflicting signals (bullish + bearish same ticker)?
- Was the setup quality already degraded at entry?

### Step 4 — Honest verdict

Write a summary doc answering:

1. **Which signal pathway has real edge?** (Win rate > baseline + positive expectancy)
2. **Which pathway is noise?** (Win rate at or below 50%, negative EV)
3. **Is "take everything" better than "take selectively"?** Compare cohort-filtered vs take-all hypothetical P&L
4. **Are there ticker/time/regime filters that improve outcomes?**
5. **Where should we invest next — tighter filters, new pathways, or just position sizing discipline?**

## Scripts To Pre-Build (Optional Prep)

If you want a head start tonight, I could write:

### `scripts/import_broker_csv.py`
Parses Fidelity + E*Trade CSVs into a unified format, writes to a new
`broker_trades` SQLite table. Accepts both schemas, normalizes option
symbols to OSI format, computes P&L per round-trip.

**Size:** ~150 lines, ~30 min build. Run via:
```
python -m scripts.import_broker_csv --etrade data/etrade_week.csv --fidelity data/fidelity_week.csv
```

### `scripts/match_signals_to_trades.py`
For each broker trade, finds the closest (in time, ticker, strike, exp)
signal from our various alert tables. Writes attribution.

**Size:** ~200 lines, ~45 min build. Can't run without broker data, so
scaffold only.

### `scripts/weekly_analysis.py`
Computes cohort stats (win rate by pathway/ticker/time/regime/DTE).
Outputs Markdown report to `docs/research/week_20260418_analysis.md`.

**Size:** ~300 lines, ~1hr build. Best done after we have data.

## Time Budget For Next Session

Realistic estimate if you export CSVs before we start:

- Import + normalize brokers: 30 min
- Signal attribution: 45 min
- Cohort analysis: 1 hour
- Writeup + honest recommendations: 30 min
- **Total: ~2.5 hours** of focused session

## Files/Tables Referenced From This Session

- `server/signals.py` — SOE engine + auto-paper-trade rules
- `server/runner_tracker.py` — Runner state machine
- `server/scalp_alerts.py` — SPY/QQQ scalp alerts
- `server/price_watch.py` — AMAT/AAOI/MSFT/NFLX watches (live today)
- `server/swing_alerts.py` — Swing watchlist entry alerts
- `server/paper_trading.py` — Auto-trade spec + exit logic
- Memory: `memory/MEMORY.md`, `memory/session_webapp.md`

## Resume Prompt For New Session

Copy this into the new Claude Code session:

```
Resuming GammaPulse. Context: broker CSVs already imported, signal
attribution complete. Read:
  docs/research/WEEKLY_TRADE_ANALYSIS_HANDOFF.md (this doc)
  docs/research/week_trade_attribution.md (the scorecard)
  docs/research/week_signal_outcomes.md (raw signal win rates)
  memory files

Priorities for this session:
  1. Fix signal time gate: change mins > 975 to mins > 960 in
     server/signals.py (lines 840, 1453) — stops post-4PM stale fires
  2. Extend Mir Discord parser to capture chat-relay signals
     (currently only 2/91 trades matched to Mir because many came
     from chat, not Discord signal messages)
  3. Multi-week backtest — import more weekly CSVs, stability check
     on the 70-100% WR numbers
  4. Propose filter rules informed by per-ticker/per-time findings
```

## What Got Done In The Last Session (Apr 17)

All committed + pushed to origin/main. Key deliverables:

- **scripts/import_broker_csv.py** — parses E*Trade + Fidelity CSVs
  into `broker_trades` + `broker_roundtrips` SQLite tables. FIFO-pairs
  opens with closes. Handled both formats (E*Trade regex on description
  field, Fidelity OSI-style symbol parsing).

- **scripts/backtest_signals_week.py** — walk-forward 5-min bar
  resolution of every SOE signal's target/stop. Outputs raw signal
  quality independent of execution.

- **scripts/attribute_trades_to_signals.py** — cross-references
  broker_roundtrips with signal sources (SOE_A/SOE_B+/Mir_Discord/Runner).
  Same-day ticker+strike+type+expiry matching with STRONG/MEDIUM/WEAK
  confidence. Classifies outcomes into BIG_WIN/WIN/SCRATCH/LOSS/BIG_LOSS.

### Week's actual results (4/13-4/17, 91 roundtrips)

| Source | Trades | Net P&L | Win Rate |
|---|---:|---:|---:|
| SOE_A | 8 | +$1,279 | **100%** |
| SOE_B+ | 53 | **+$6,328** | **70%** |
| MANUAL | 28 | +$3,994 | 71% |
| MIR_DISCORD | 2 | −$31 | 50% |
| **Total** | **91** | **+$11,569** | **72.5%** |

Hypothesis "dozens of alerts, few winners" — **inverted**. User took
9% of 1,014 signals, had 72.5% WR. Filter skill is the alpha.

### Open questions for next session

1. **4PM gate fix** (2 lines, 60 seconds work):
   - `server/signals.py` lines 840 + 1453: change `975` → `960`
   - Eliminates post-close stale-cache signals (20 fired today after 4PM)
   - User explicitly flagged this issue

2. **Mir Discord coverage gap**: user's biggest Mir-sourced trades
   (AMAT 395C, AAOI 200C, MSFT 430C trim, NFLX bullish post-ER) came
   from CHAT messages. Our `mir_signal_cache` only captured 18 signal
   messages. Need to extend the Discord listener to capture chat
   relays, or accept this limitation and flag MANUAL trades as
   "likely Mir chat" via proximity to Mir timestamps.

3. **AXTI LEAPS mystery**: 3 wins totaling ~$2,300 at MANUAL
   attribution. AXTI not in our scan universe. Pure user pattern
   recognition on photonics theme. Consider adding LEAPS detection
   to runner_tracker or swing_scanner if this is a repeatable alpha.

4. **AMAT discipline violation**: -$814 scaled-in loss. User paid
   $3.20/$2.70/$2.60/$2.50 despite Mir's "max $2" rule. Consider
   adding `max_pay_override` rejection to `price_watch.py` that
   blocks auto-paper-trades exceeding user-set ceiling per watch.

5. **Multi-week stability**: one week is noisy. Import 2-3 more
   weekly CSVs to validate the 70-100% WR numbers aren't a
   one-week fluke.

### What still works (don't touch)

- SOE engine + grading — A grade is perfect, B+ is strong
- Runner tracker (TSLA/AVGO actively tracked across the week)
- Price watches (AMAT/AAOI/MSFT/NFLX — all fired correctly)
- OI delta tracking (Day 2 snapshot fires today at 4:15 PM)
- Proto_runner observation mode (no detections yet, but infrastructure solid)
- Heatmap UI (matrix king, -king, callouts, % change badges)

## Important Honest Caveats For The Analysis

1. **Small sample size** — one week of data is 5 days. Statistics will be
   noisy. Call out confidence intervals, don't overclaim.

2. **Survivorship bias** — user only took trades they liked. Signals that
   fired but weren't traded aren't in the broker data. We'd need to
   compare "signals fired but not traded" vs "signals fired and traded"
   to see if you had good vs bad selection.

3. **Multiple-alert confounds** — if SOE A fires AND Mir Discord fires
   AND runner tracker fires on the same ticker, which pathway gets credit
   for the win? Keep the attribution honest — credit goes to whichever
   fired FIRST, or we split across overlapping alerts.

4. **Paper-trade history is truncated** — we reset the paper book last
   night. Only today's paper trades will be in the current DB. Pre-reset
   data is in `data/backups/` but was flawed (monitor bugs, overnight
   cached stales).

5. **E*Trade fills vs signal prices** — our signal `entry_price` is a
   snapshot. User's actual fill could be seconds to minutes later at a
   different price. Check slippage distribution.
