# Weekly Trade Analysis — Session Handoff

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
Resuming GammaPulse for weekly trade analysis.

Read memory files + docs/research/WEEKLY_TRADE_ANALYSIS_HANDOFF.md
for full context.

I've exported:
- data/etrade_week_20260418.csv
- data/fidelity_week_20260418.csv

Build:
1. scripts/import_broker_csv.py — unified import
2. scripts/match_signals_to_trades.py — signal attribution
3. scripts/weekly_analysis.py — cohort report

Then produce docs/research/week_20260418_analysis.md with honest
verdict on "dozens of alerts, few winners" hypothesis.
```

That single prompt restores full context, identifies the files, and scopes
the work.

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
