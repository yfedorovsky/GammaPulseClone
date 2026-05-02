# E-Trade Paper Execution Layer — Pre-Registration

**Status: PRE-REGISTERED. May 2 2026 evening. Branch:
`feature/etrade-paper-execution`.**

This spec governs the secondary validation layer added on top of the
primary forward-window paper trade infrastructure (`paired_trades.py`).

## Purpose

The primary forward window simulates trades using ThetaData/Databento
intrinsic-only proxies. This understates true exit price for early
exits (where time premium remains) and overstates for very-late exits
(where bid degrades faster than mid). For 0DTE in the final 30 min the
divergence is small but during morning hours it can be ±20%.

Adding live E-Trade paper-account execution captures:
- **Real spread crossing** at entry (pay ask, sell bid)
- **Real fill timing** (alert fires at T, order arrives at T+ms,
  fills at T+seconds)
- **Real slippage** when limit orders chase a moving market
- **Real time-decay** in the option's actual mid price during the window

If the forward window's intrinsic-only result and the E-Trade paper
result agree within reasonable bounds, both findings reinforce each
other. If they disagree, the divergence is itself information about
which simulation methodology is more trustworthy.

## Architectural separation

This entire layer lives on `feature/etrade-paper-execution`. The
`main` branch is unchanged. The forward window verdict on `main`
proceeds via intrinsic-only `paired_trades.py` regardless of what
the E-Trade layer reports. Per the production freeze:

- E-Trade execution does NOT modify any gate logic, sizing, or
  stopping rules
- E-Trade fills do NOT enter `paired_trades.db` (the falsification
  protocol's primary metric)
- E-Trade fills enter a SEPARATE `paper_executions.db` for parallel
  analysis

## Data flow

```
ZeroDTEAlert / qualified ST event
        │
        ├──► paired_trades.py (intrinsic-only sim)  ◄── PRIMARY VERDICT
        │           │
        │           └──► paired_trades.db
        │
        └──► etrade_executor.py (live paper fill)   ◄── SECONDARY
                    │
                    └──► paper_executions.db
```

Both run independently. Either can fail without affecting the other.

## Pre-committed execution rules

The auto-executor takes EVERY alert dispatched (no filters). This
preserves the falsification protocol design — we want to validate
the primary metric on the un-truncated alert stream, then analyze
filter effects post-hoc using annotation columns.

For each alert:
1. Place a LIMIT order at `est_entry_price + 0.02` (2-cent buffer
   above expected fill to ensure fill on momentum)
2. If unfilled within 60 seconds, cancel and log "no_fill"
3. Once filled, set TWO orders simultaneously:
   - GTC limit SELL at `entry_fill_price * 1.50` (TP at +50%)
   - GTC stop-market SELL at `entry_fill_price * 0.70` (Stop at -30%)
4. At 30-min mark from entry: cancel both, market-close (time stop)
5. At 15:55 ET: any open position → market-close (EOD safety)

This implements the play guidance we shipped in telegram banners
(TP+50/Stop-30/Time-30). Pre-committed; do not tune in the forward
window.

For ST qualified fires (which currently produce 0 fires per day
during forward window), the executor takes a position the same way
as 0DTE alerts: ATM call/put per direction, same TP/Stop/Time rules.

## Schema: `paper_executions` table

```sql
CREATE TABLE paper_executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  -- Source alert reference
  alert_source TEXT NOT NULL,    -- '0dte' or 'st'
  alert_id TEXT NOT NULL,
  fired_at INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,
  -- Order intent
  intent_strike REAL,
  intent_right TEXT,
  intent_expiration TEXT,
  intent_limit_price REAL,
  intent_quantity INTEGER,
  -- Order placement (entry)
  entry_order_id TEXT,
  entry_placed_at INTEGER,
  entry_filled_at INTEGER,
  entry_fill_price REAL,
  entry_fill_status TEXT,  -- 'FILLED' / 'NO_FILL' / 'PARTIAL' / 'REJECTED'
  -- TP/Stop sub-orders
  tp_order_id TEXT,
  tp_filled_at INTEGER,
  tp_fill_price REAL,
  stop_order_id TEXT,
  stop_filled_at INTEGER,
  stop_fill_price REAL,
  time_stop_at INTEGER,    -- target time-stop timestamp (entry+30min)
  eod_close_at INTEGER,    -- target EOD-close timestamp
  -- Final outcome
  exit_reason TEXT,        -- 'TP' / 'STOP' / 'TIME_STOP' / 'EOD' / 'ERROR'
  exit_price REAL,
  exit_at INTEGER,
  pnl_pct REAL,            -- (exit_price - entry_fill_price) / entry_fill_price * 100
  -- E-Trade context
  account_id_key TEXT,
  is_sandbox INTEGER,      -- 1 if sandbox, 0 if prod
  -- Audit
  notes TEXT,
  created_at INTEGER NOT NULL,
  UNIQUE(alert_source, alert_id)
);
CREATE INDEX idx_pe_fired_at ON paper_executions(fired_at);
CREATE INDEX idx_pe_ticker ON paper_executions(ticker, fired_at);
```

## Pre-committed analysis methodology (post-Stage-3)

Trigger: same as primary forward window (Stage 3 met). Run once.

Comparison: per matched (alert_id), compute
  `divergence = etrade_pnl_pct - intrinsic_pnl_pct`

Cluster bootstrap by day on divergence. Report:
- Mean divergence + 95% CI
- Distribution shape (histogram)
- Per-time-of-day divergence (early-day expected to be more negative
  for E-Trade due to wider morning spreads)

**Decision rule**: if mean |divergence| < 15pp, intrinsic-only sim is
deemed sufficiently accurate for the falsification verdict. If
≥ 15pp, intrinsic-only verdict gets a footnote / asterisk and
E-Trade paper P&L becomes the headline number.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| OAuth token expires daily mid-day | `renew_access_token()` called every 90 min by executor; daily setup script as backup |
| E-Trade sandbox quote quality differs from real markets | Document divergence; eventually augment with live Tradier quotes for cross-check |
| Sandbox fills are simulated and may not reflect real liquidity | This IS the validation we want — knowing how the simulator differs is itself useful data. Compare against intrinsic-only as ground truth |
| Production credentials accidentally used | `ETRADE_USE_SANDBOX=1` is the default; production requires explicit env override + interactive confirmation |
| Executor crash during open positions | On startup, query open orders + positions, reconcile against `paper_executions` table, force-close any orphaned positions |
| Rate limits | Executor places at most ~20 orders per day total; well under any plausible E-Trade rate limit |

## What this layer does NOT do

- Does NOT trade real money (sandbox-only by default; production
  requires explicit env override)
- Does NOT modify the main-branch forward window verdict (separate
  branch, separate DB)
- Does NOT apply post-hoc filters to the alert stream — takes EVERY
  alert to preserve the falsification protocol baseline
- Does NOT auto-renew if cached token is missing — requires a daily
  manual setup script run when full re-auth is needed
- Does NOT replace the manual-paper-trade workflow rule check (the
  Apr 29 ST-confirmation rule is a TRADING decision, not an
  EXECUTION decision; if the executor takes everything, the
  workflow rule effect is computed post-hoc by filtering the
  paper_executions table on `st_confirmation_within_90m`)

## Source

- User request May 2 2026 evening to add E-Trade paper account
  validation
- OpenAI deep research May 2: "the highest-value missing layer is a
  feasibility / execution layer" — this is part of that
- Cross-LLM round 5 framing of strategy validation as needing
  multiple independent measurements
