# Tradier Paper Account Integration

**Branch**: `feature/tradier-paper-execution`. Replaces the abandoned
`feature/etrade-paper-execution` branch (which used a dev-mock sandbox
with no UI). Tradier paper provides:
- **Real UI** at https://brokerage.tradier.com (visible positions + P&L)
- **Real-market quotes** (not canned mocks)
- **Realistic simulated fills** tied to actual bid/ask
- **Bearer token auth** (no OAuth dance, no daily expiry)
- **Same API as Tradier production** (we already integrate for quotes)

## One-time setup

### 1. Tradier developer account

1. Go to https://developer.tradier.com (sign in with existing Tradier
   creds OR create new account — ~3 min)
2. Navigate to **Sandbox API** → **Generate Access Token**
3. Copy the token (and account number shown alongside)

### 2. .env entries

Add to `.env`:
```
TRADIER_PAPER_TOKEN=<your_sandbox_bearer_token>
TRADIER_PAPER_ACCOUNT_ID=<your_sandbox_account_number>
```

(If you don't know the account number yet, the setup script in step 3
will print it.)

### 3. Validate

```
python scripts/tradier_paper_setup.py
```

This will:
- Check token works
- List your accounts (and tell you which to use as `TRADIER_PAPER_ACCOUNT_ID`)
- Pull balance + positions for sanity
- Pull a SPY quote to confirm market data flows

If everything passes, you're ready.

## Daily flow

Tradier tokens **don't expire daily** — unlike E-Trade, no morning
re-auth. Just start the daemon when you want to start trading.

```
python -m server.tradier_executor
```

You'll see the safety banner showing:
- sandbox URL (https://sandbox.tradier.com)
- account ID
- TP +50% / Stop -30% / Time-stop 30 min / EOD 15:55 ET

Daemon runs autonomously. Crashes are recoverable — restart and the
reconcile_on_startup pulls Tradier state into local DB.

## State machine

Same as the (abandoned) E-Trade design:

```
PENDING (entry order placed)
  ├── 60s timeout → CANCELLED, exit_reason=NO_FILL
  └── filled → FILLED
                ├── place TP (limit @ +50%)
                └── place Stop (stop @ -30%)
                     ├── TP filled → CLOSED (TP), cancel Stop
                     ├── Stop filled → CLOSED (STOP), cancel TP
                     ├── time_stop reached → market close → TIME_STOP
                     └── EOD reached → market close → EOD
```

## Tradier-specific differences

| Aspect | Tradier paper | E-Trade sandbox (abandoned) |
|---|---|---|
| Auth | Bearer token | OAuth 1.0a |
| Token expiry | Never (until rotated) | Daily at midnight ET |
| Quote data | Real market | Canned/mocked |
| Fill simulation | Bid/ask-aware | Often no fills |
| UI access | Yes (brokerage.tradier.com) | None |
| API shape | JSON, lowercase verbs | XML/JSON mix, uppercase verbs |
| Order ID uniqueness | Yes (real ids) | All "511" (canned) |

## ST auto-execution

Same logic as E-Trade attempt:
- Strike: ATM rounded to ticker grid (SPY/QQQ/IWM=$1, SPX=$5)
- Expiration: today (0DTE thesis)
- Right: CALL for BULLISH, PUT for BEARISH
- Limit price: queried from Tradier real quotes (with sanity check —
  rejects asks > $100 for SPY/QQQ/IWM as obvious garbage, unlike the
  E-Trade version that would have placed orders at $579.73 when
  sandbox returned bogus data)

## MCP tools (10 total)

Configure in Claude Desktop config:
```json
{
  "mcpServers": {
    "tradier-paper": {
      "command": "python",
      "args": ["-m", "mcp_servers.tradier_paper.server"],
      "env": {
        "TRADIER_REPO_ROOT": "C:\\Dev\\GammaPulse"
      }
    }
  }
}
```

| Tool | Purpose |
|---|---|
| `tr_user_profile` | List accounts |
| `tr_balance` | Cash + buying power |
| `tr_positions` | Open positions |
| `tr_quote` | Real-time quote |
| `tr_place_paper_order` | Submit option order (preview by default) |
| `tr_list_orders` | All orders, optional status filter |
| `tr_cancel_order` | Cancel by id |
| `tr_paper_executions_today` | Local DB view |
| `tr_executor_status` | Aggregated stats |
| `tr_open_positions_local` | Local DB open positions |

## Pre-registered analysis

See `docs/research/TRADIER_PAPER_EXECUTION_SPEC.md` for the methodology
that compares Tradier paper fills vs intrinsic-only sim from
`paired_trades.py`. Trigger: Stage 3 of `FALSIFICATION_PROTOCOL.md`.
Until then, this is data collection only.

## Troubleshooting

**`TRADIER_PAPER_TOKEN not set`** — add to `.env` per setup steps.

**`401 Unauthorized`** — token rotated or invalid. Generate a new one
at https://developer.tradier.com and update `.env`.

**`No accounts returned`** — your Tradier developer account may not
have a paper sub-account provisioned. Check developer portal under
Sandbox API → Accounts.

**Quote endpoint returns prior-day stale data** — Tradier sandbox
quotes are ~15 min delayed. Real-time data requires production tier.
For paper validation purposes the 15-min delay is acceptable.

**No fills happening** — Tradier sandbox sometimes throttles fill
simulation. Check brokerage.tradier.com paper account UI to see actual
state. If positions show there but executor doesn't see them, check
`paper_executions.db` and run `python -m server.tradier_executor
--reconcile-only`.
