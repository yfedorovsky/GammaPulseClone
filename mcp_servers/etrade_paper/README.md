# E-Trade Paper Account Integration

**Branch**: `feature/etrade-paper-execution` only. Not on `main`.

Two layers wrapping the E-Trade Sandbox API:

1. **Auto-executor daemon** (`server/etrade_executor.py`) — listens for
   alerts from the live worker, places paper orders automatically,
   tracks fills, applies TP+50/Stop-30/Time-30min exit rules.
2. **MCP server** (`mcp_servers/etrade_paper/server.py`) — exposes
   E-Trade tools to Claude (Desktop or Code) for interactive trade
   management + querying.

Both read from the SAME SQLite DB (`paper_executions.db`, gitignored)
so you can manually intervene via Claude on positions the daemon
opened, and vice-versa.

## One-time setup

### 1. E-Trade developer account

1. Sign up at https://developer.etrade.com/
2. Get your **sandbox** consumer key + secret. (You probably already
   have a brokerage account; the developer account is a separate
   sign-up under the same login.)
3. Optional: get production credentials too if you intend to use real
   money later. **Strongly recommended to stay in sandbox initially.**

### 2. .env entries

Add to `.env` in repo root:

```
ETRADE_SANDBOX_KEY=your_sandbox_consumer_key
ETRADE_SANDBOX_SECRET=your_sandbox_consumer_secret

# Optional — only set if you'll use production
# ETRADE_KEY=your_prod_key
# ETRADE_SECRET=your_prod_secret

# Default to sandbox; flip explicitly for prod
ETRADE_USE_SANDBOX=1
```

### 3. First-time OAuth grant

```
python scripts/etrade_oauth_setup.py
```

This will:
- Print a URL to visit in your browser
- Wait for you to click "Accept" on E-Trade and copy the verification code
- Exchange the code for an access token
- Save it to `.etrade_tokens.json` (gitignored)
- Sanity check by listing your accounts

You'll see your accounts listed. Note the `id_key` for your **paper
account** (NOT real-money) — you'll need it for the executor.

### 4. Identify your paper account_id_key

```
python -m server.etrade_executor --list-accounts
```

Output looks like:
```
account: id=12345 id_key=ABC123XYZ== type=MARGIN status=ACTIVE description=PAPER ACCT
```

Save the `id_key` — you'll pass it as `--account-id` to the executor.

## Daily flow

### Each trading morning (~30 sec)

```
python scripts/etrade_oauth_setup.py
```

(OR `python scripts/etrade_oauth_setup.py --renew-only` if your
token from yesterday is still valid — it'll attempt renewal first
and only do full re-auth on failure. Tokens expire daily at midnight
US ET, so most days renewal will fail.)

### Start the auto-executor (background)

```
python -m server.etrade_executor --account-id YOUR_ID_KEY
```

It will:
- Poll `zero_dte_alerts.db` and `structural_turns.db` every 15s
- Place a LIMIT BUY order on each new alert (entry premium + $0.02)
- Track fill, log to `paper_executions.db`
- Auto-renew OAuth token every 90 min
- Apply TP+50/Stop-30/Time-30min exit (Phase 2.5 — partially
  implemented; see code TODOs)

For dry-run (log intents but don't actually place orders):

```
python -m server.etrade_executor --account-id YOUR_ID_KEY --no-execute
```

### MCP server for Claude

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "etrade-paper": {
      "command": "python",
      "args": ["-m", "mcp_servers.etrade_paper.server"],
      "env": {
        "ETRADE_REPO_ROOT": "C:\\Dev\\GammaPulse"
      }
    }
  }
}
```

For Claude Code, add to `.claude/mcp_servers.json` (similar shape).

After config + restart, you can ask Claude:
- "Show my E-Trade paper account balance"
- "What positions am I currently holding?"
- "Cancel order 12345"
- "Place a paper order for 1 SPY 720 call expiring today, limit $0.50"
  (Claude will preview by default; you confirm before executing)
- "What's my paper P&L today from the auto-executor?"

## Available MCP tools

| Tool | Purpose |
|---|---|
| `et_list_accounts` | Enumerate your paper accounts |
| `et_get_balance` | Cash + buying power |
| `et_get_positions` | Currently held positions (E-Trade view) |
| `et_get_quote` | Real-time quote for symbols |
| `et_place_paper_order` | Submit option order (preview by default) |
| `et_list_orders` | OPEN / EXECUTED / CANCELLED orders |
| `et_cancel_order` | Cancel an open order |
| `et_paper_executions_today` | Local DB view of auto-executor activity |
| `et_executor_status` | Aggregated stats |
| `et_open_positions_local` | Local DB view of open positions |
| `et_renew_token` | Refresh OAuth token (within-day only) |

## What this does NOT do

- Does NOT trade real money by default (sandbox is the default; flip
  `ETRADE_USE_SANDBOX=0` only when you explicitly want production)
- Does NOT modify any logic on the `main` branch — purely a separate
  validation layer
- Does NOT enter into `paired_trades.db` (the primary forward-window
  metric on main). Comparison happens post-Stage-3 per the spec doc.

## Troubleshooting

### "No cached E-Trade token"
Run `python scripts/etrade_oauth_setup.py`.

### "401 Unauthorized" mid-day
Token may have idle-timed-out. Try:
```
python -c "import asyncio; from server.etrade import ETradeClient, get_cached_token; asyncio.run(ETradeClient(get_cached_token()).renew_access_token())"
```
Or just re-run the setup script.

### "401 Unauthorized" at start of day
Token expired at midnight. Re-run setup script.

### Order rejected with "Quote not available"
Sandbox quotes are stale or simulated. Try MARKET order instead of
LIMIT, or wait a few minutes and retry.

### Sandbox fills don't match expected behavior
Sandbox simulates fills with simulated quotes — divergence from real
market is expected. Per the spec doc, this divergence is itself
useful data once we have enough samples to characterize it.

## Pre-registered analysis

See `docs/research/ETRADE_PAPER_EXECUTION_SPEC.md` for the methodology
that compares E-Trade paper fills vs intrinsic-only sim. Trigger:
Stage 3 of `FALSIFICATION_PROTOCOL.md` met. Until then, this is
data collection only.
