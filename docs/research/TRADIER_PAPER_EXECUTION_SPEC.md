# Tradier Paper Execution Layer — Pre-Registration

**Status: PRE-REGISTERED. May 4 2026. Branch:
`feature/tradier-paper-execution`. Replaces the abandoned E-Trade attempt.**

## Context — why we pivoted

E-Trade Developer Sandbox (the original Phase 1-2 work) turned out to
be a developer-test-mock environment, not a paper trading platform:
- Returned canned responses (every order_id was "511")
- No UI representation anywhere
- No realistic fill simulation
- Daily OAuth dance at midnight ET
- Quotes were stale/mocked

User identified this Monday May 4 morning when checking his actual
E-Trade paper trading UI and seeing no positions despite the daemon
having "placed" 10 orders. Investigation confirmed E-Trade's developer
sandbox is API-only with zero connection to any visible account.

**Pivot decision**: rebuild on Tradier paper sandbox, which has:
- Real UI at https://brokerage.tradier.com
- Real-market quotes (15-min delayed; fine for paper validation)
- Realistic simulated fills tied to actual bid/ask
- Bearer token auth (no daily friction)

## Purpose

Same as the original E-Trade spec — secondary validation layer that
captures real fill timing/slippage to compare against the intrinsic-
only sim from `paired_trades.py` on `main`. The forward-window verdict
on `main` is the primary metric; Tradier paper is a cross-check.

## Architectural separation

`feature/tradier-paper-execution` only. `main` is unchanged. The
forward window verdict on main proceeds via intrinsic-only
`paired_trades.py` regardless of Tradier paper outcomes.

```
ZeroDTEAlert / ST qualified event
        │
        ├──► paired_trades.py (intrinsic-only)  ◄── PRIMARY VERDICT
        │           │
        │           └──► paired_trades.db
        │
        └──► tradier_executor.py (live paper fill)  ◄── SECONDARY
                    │
                    └──► paper_executions.db
```

## Pre-committed execution rules

The auto-executor takes EVERY alert dispatched (no filters). This
preserves the falsification protocol baseline. Filter effects analyzed
post-hoc using annotation columns from Tier-2/3/4 ships.

For each alert:
1. Place LIMIT BUY at `est_entry_price + $0.02` buffer
2. If unfilled within 60 seconds, cancel; log NO_FILL
3. On fill: place TP (LIMIT SELL @ +50%) AND Stop (STOP SELL @ -30%)
4. At 30-min mark from entry: cancel both, market close (TIME_STOP)
5. At 15:55 ET: any open position → market close (EOD safety)

ST qualified fires also auto-executed:
- Strike: ATM rounded to ticker grid
- Expiration: today (0DTE)
- Right: CALL for BULLISH, PUT for BEARISH
- Limit: real Tradier quote ask (sanity-checked: rejects > $100 for
  SPY/QQQ/IWM as obvious garbage)

## Schema

Reuses `paper_executions` table from the abandoned E-Trade work:

```sql
CREATE TABLE paper_executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_source TEXT NOT NULL,    -- '0dte' or 'st'
  alert_id TEXT NOT NULL,
  fired_at INTEGER NOT NULL,
  ticker TEXT, direction TEXT,
  intent_strike REAL, intent_right TEXT,
  intent_expiration TEXT, intent_limit_price REAL, intent_quantity INTEGER,
  entry_order_id TEXT, entry_placed_at INTEGER,
  entry_filled_at INTEGER, entry_fill_price REAL,
  entry_fill_status TEXT,        -- PENDING/FILLED/NO_FILL/PARTIAL/REJECTED/CANCELLED
  tp_order_id TEXT, tp_filled_at INTEGER, tp_fill_price REAL,
  stop_order_id TEXT, stop_filled_at INTEGER, stop_fill_price REAL,
  time_stop_at INTEGER, eod_close_at INTEGER,
  exit_reason TEXT,              -- TP/STOP/TIME_STOP/EOD/NO_FILL/ERROR
  exit_price REAL, exit_at INTEGER, pnl_pct REAL,
  account_id_key TEXT, is_sandbox INTEGER NOT NULL,
  notes TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(alert_source, alert_id)
);
```

## Pre-committed analysis methodology (post-Stage-3)

Trigger: Stage 3 of `FALSIFICATION_PROTOCOL.md` met (≥75-100 fires AND
≥25 day clusters).

Comparison: per matched (alert_id), compute
  `divergence = tradier_pnl_pct - intrinsic_pnl_pct`

Cluster bootstrap by day on divergence. Report:
- Mean divergence + 95% CI
- Distribution shape (histogram)
- Per-time-of-day divergence

**Decision rule**: if mean |divergence| < 15pp, intrinsic-only sim is
sufficiently accurate for the falsification verdict. If ≥ 15pp,
Tradier paper P&L becomes the headline number.

## What NOT to do

- Trade real money (Tradier paper is hardcoded; no env toggle to prod)
- Modify gate logic / sizing / stopping rules
- Apply post-hoc filters to the alert stream (preserves baseline)
- Auto-renew / refresh tokens (Tradier doesn't need it; if 401 happens,
  manually rotate via developer portal)

## Comparison with the abandoned E-Trade work

The architecture (state machine, TP/Stop/Time-stop, reconcile_on_startup)
transferred fully. Only auth + endpoint URLs + response shape parsing
changed. The E-Trade branch (`feature/etrade-paper-execution`) is
preserved as a reference for the failed approach but no longer
maintained.

Lessons learned from the E-Trade attempt:
1. **Sandbox != paper trading**. Always verify the sandbox shows up in
   a real UI before investing in integration.
2. **Real-market quotes matter**. Mocked sandbox quotes broke our ST
   strike picker (corrupted limit prices to $579.73 for an ATM SPY
   call).
3. **Bearer-token auth is dramatically less operational friction**
   than OAuth 1.0a, especially for daily-restart daemons.

## Source

- User request May 4 2026 morning to fix the E-Trade gap
- E-Trade pivot evidence: 10 orders placed against E-Trade sandbox,
  all CANCELLED with no realistic fill simulation, no UI visibility
- Tradier already integrated for production quotes — minimal added
  attack surface to extend for paper trading
