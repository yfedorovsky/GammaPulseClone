"""MCP server exposing E-Trade paper-account tools to Claude.

Wraps server.etrade.ETradeClient + server.paper_executions DB queries
as MCP tools. Designed for use with Claude Desktop or Claude Code.

Tools exposed:
  - et_list_accounts          : enumerate paper accounts
  - et_get_balance            : account cash + buying power
  - et_get_positions          : current open positions
  - et_get_quote              : real-time quote
  - et_place_paper_order      : submit option order (preview by default)
  - et_list_orders            : open/executed/cancelled orders
  - et_cancel_order           : cancel an open order
  - et_paper_executions_today : query our local paper_executions table
  - et_executor_status        : aggregated stats on today's auto-executor activity
  - et_open_positions_local   : local paper_executions DB view of open positions

Auth: relies on the cached OAuth token (run scripts/etrade_oauth_setup.py
first). On token expiry, tool calls return an error directing the user
to re-auth.

Configuration in Claude Desktop config (claude_desktop_config.json):

  {
    "mcpServers": {
      "etrade-paper": {
        "command": "python",
        "args": ["-m", "mcp_servers.etrade_paper.server"]
      }
    }
  }

Configuration in Claude Code (.claude/mcp_servers.json):

  similar shape

NOTE: This server runs in the SAME working directory as the GammaPulse
repo so it can find .etrade_tokens.json + paper_executions.db. If you
launch it from a different cwd, set ETRADE_REPO_ROOT env var.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow running both as `python -m mcp_servers.etrade_paper.server`
# and directly as a script
if __name__ == "__main__" and __package__ is None:
    SCRIPT_DIR = Path(__file__).resolve().parent
    REPO_ROOT = SCRIPT_DIR.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# If launched from elsewhere, allow override
ENV_ROOT = os.getenv("ETRADE_REPO_ROOT")
if ENV_ROOT:
    REPO_ROOT = Path(ENV_ROOT)
os.chdir(REPO_ROOT)

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import Tool, TextContent  # noqa: E402

from server.etrade import ETradeClient, get_cached_token, _is_sandbox  # noqa: E402
from server import paper_executions as pe  # noqa: E402


# ── Server setup ──────────────────────────────────────────────────


server = Server("etrade-paper")


def _format_json(data: Any) -> str:
    """Pretty JSON with sane defaults, fallback to repr."""
    try:
        return json.dumps(data, indent=2, default=str)
    except Exception:
        return repr(data)


def _ensure_token() -> str | None:
    """Returns None if token is present, else an error message."""
    if get_cached_token() is None:
        return ("ERROR: No cached E-Trade token. Run "
                "`python scripts/etrade_oauth_setup.py` to grant access. "
                "Tokens expire daily at midnight US ET.")
    return None


# ── Tool definitions ─────────────────────────────────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="et_list_accounts",
            description=("List all paper accounts owned by this E-Trade user. "
                         "Returns accountId, accountIdKey, accountType, status. "
                         "Use accountIdKey for subsequent calls."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="et_get_balance",
            description=("Get cash + buying power + total value for one paper "
                         "account. Use accountIdKey from et_list_accounts."),
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id_key": {"type": "string"},
                },
                "required": ["account_id_key"],
            },
        ),
        Tool(
            name="et_get_positions",
            description="List current open positions in a paper account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id_key": {"type": "string"},
                },
                "required": ["account_id_key"],
            },
        ),
        Tool(
            name="et_get_quote",
            description=("Get real-time quote for one or more symbols. "
                         "For options use OCC symbol or compound; for "
                         "equities just the ticker."),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ticker symbols",
                    },
                },
                "required": ["symbols"],
            },
        ),
        Tool(
            name="et_place_paper_order",
            description=("Place an option order on a paper account. "
                         "DEFAULT IS preview_only=True (returns preview "
                         "without executing). Set preview_only=False to "
                         "actually submit. Order_type: MARKET or LIMIT. "
                         "Action: BUY_OPEN, SELL_CLOSE, SELL_OPEN, BUY_CLOSE."),
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id_key": {"type": "string"},
                    "ticker": {"type": "string",
                               "description": "Underlying ticker (SPY, QQQ, etc)"},
                    "expiration_date": {"type": "string",
                                        "description": "YYYY-MM-DD"},
                    "strike": {"type": "number"},
                    "call_or_put": {"type": "string", "enum": ["CALL", "PUT"]},
                    "action": {"type": "string",
                               "enum": ["BUY_OPEN", "SELL_CLOSE",
                                        "SELL_OPEN", "BUY_CLOSE"]},
                    "quantity": {"type": "integer", "minimum": 1},
                    "order_type": {"type": "string",
                                   "enum": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
                                   "default": "LIMIT"},
                    "limit_price": {"type": "number",
                                    "description": "Required for LIMIT orders"},
                    "stop_price": {"type": "number"},
                    "preview_only": {"type": "boolean", "default": True,
                                     "description": "If True (default), only preview; if False, execute"},
                },
                "required": ["account_id_key", "ticker", "expiration_date",
                             "strike", "call_or_put", "action", "quantity"],
            },
        ),
        Tool(
            name="et_list_orders",
            description="List orders by status (OPEN, EXECUTED, CANCELLED, EXPIRED).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id_key": {"type": "string"},
                    "status": {"type": "string",
                               "default": "OPEN",
                               "enum": ["OPEN", "EXECUTED", "CANCELLED",
                                        "EXPIRED", "REJECTED"]},
                },
                "required": ["account_id_key"],
            },
        ),
        Tool(
            name="et_cancel_order",
            description="Cancel an open order by orderId.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id_key": {"type": "string"},
                    "order_id": {"type": "integer"},
                },
                "required": ["account_id_key", "order_id"],
            },
        ),
        Tool(
            name="et_paper_executions_today",
            description=("Query the LOCAL paper_executions DB for today's "
                         "auto-executor activity. Returns each row's intent + "
                         "fill + exit status."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="et_executor_status",
            description=("Aggregated stats on today's auto-executor activity: "
                         "n_alerts seen, n_filled, n_open, n_closed, mean P&L."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="et_open_positions_local",
            description=("Local paper_executions DB view: positions where "
                         "entry filled but exit hasn't happened yet. Useful "
                         "for cross-checking against et_get_positions."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="et_renew_token",
            description=("Refresh the cached OAuth token to extend its idle "
                         "lifetime within the same trading day. Does NOT "
                         "survive midnight ET — use scripts/etrade_oauth_setup.py "
                         "for daily re-auth."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


# ── Tool handlers ────────────────────────────────────────────────


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    err = _ensure_token()
    if err and name != "et_renew_token":
        return [TextContent(type="text", text=err)]

    client = ETradeClient(token=get_cached_token())
    try:
        if name == "et_list_accounts":
            accts = await client.list_accounts()
            envelope = {
                "environment": "sandbox" if _is_sandbox() else "production",
                "accounts": accts,
            }
            return [TextContent(type="text", text=_format_json(envelope))]

        elif name == "et_get_balance":
            data = await client.account_balance(arguments["account_id_key"])
            return [TextContent(type="text", text=_format_json(data))]

        elif name == "et_get_positions":
            positions = await client.account_positions(arguments["account_id_key"])
            return [TextContent(
                type="text",
                text=f"Found {len(positions)} positions:\n\n" +
                     _format_json(positions),
            )]

        elif name == "et_get_quote":
            quotes = await client.quote(arguments["symbols"])
            return [TextContent(type="text", text=_format_json(quotes))]

        elif name == "et_place_paper_order":
            args = dict(arguments)
            order_type = args.get("order_type", "LIMIT")
            preview_only = args.pop("preview_only", True)
            result = await client.place_option_order(
                account_id_key=args["account_id_key"],
                symbol=args["ticker"],
                expiration_date=args["expiration_date"],
                strike=float(args["strike"]),
                call_or_put=args["call_or_put"],
                action=args["action"],
                quantity=int(args["quantity"]),
                order_type=order_type,
                limit_price=args.get("limit_price"),
                stop_price=args.get("stop_price"),
                time_in_force="DAY",
                preview_only=preview_only,
            )
            mode = "PREVIEW (not executed)" if preview_only else "EXECUTED"
            return [TextContent(
                type="text",
                text=f"Order {mode}\n\n{_format_json(result)}",
            )]

        elif name == "et_list_orders":
            status = arguments.get("status", "OPEN")
            orders = await client.list_orders(arguments["account_id_key"], status)
            return [TextContent(
                type="text",
                text=f"{len(orders)} {status} orders:\n\n" +
                     _format_json(orders),
            )]

        elif name == "et_cancel_order":
            data = await client.cancel_order(
                arguments["account_id_key"], int(arguments["order_id"]),
            )
            return [TextContent(
                type="text",
                text=f"Cancel result:\n\n{_format_json(data)}",
            )]

        elif name == "et_paper_executions_today":
            rows = pe.get_today()
            return [TextContent(
                type="text",
                text=f"{len(rows)} executions today:\n\n" + _format_json(rows),
            )]

        elif name == "et_executor_status":
            summary = pe.summary_today()
            return [TextContent(type="text", text=_format_json(summary))]

        elif name == "et_open_positions_local":
            rows = pe.get_open_positions()
            return [TextContent(
                type="text",
                text=f"{len(rows)} open positions in local DB:\n\n" +
                     _format_json(rows),
            )]

        elif name == "et_renew_token":
            ok = await client.renew_access_token()
            return [TextContent(
                type="text",
                text=("Token renewed successfully — good until midnight US ET."
                      if ok else
                      "Renewal failed — run `python scripts/etrade_oauth_setup.py` "
                      "for a full re-auth."),
            )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(
            type="text",
            text=f"ERROR calling {name}: {type(e).__name__}: {e}",
        )]
    finally:
        await client.close()


# ── Entry point ─────────────────────────────────────────────────


async def main_async() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
