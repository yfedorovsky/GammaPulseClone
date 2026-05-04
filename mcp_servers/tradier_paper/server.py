"""MCP server exposing Tradier paper-account tools to Claude.

Replaces the E-Trade MCP after we pivoted away from E-Trade developer
sandbox (which had no UI representation and used canned responses) to
Tradier paper sandbox (real-market quotes, real UI at
brokerage.tradier.com).

Tools exposed:
  - tr_user_profile           : list accounts (incl. paper)
  - tr_balance                : cash + buying power for an account
  - tr_positions              : current open positions
  - tr_quote                  : real-time quote for symbol(s)
  - tr_place_paper_order      : submit option order (preview by default)
  - tr_list_orders            : all orders (caller filters by status)
  - tr_cancel_order           : cancel an open order
  - tr_paper_executions_today : query our local paper_executions table
  - tr_executor_status        : aggregated stats on auto-executor activity
  - tr_open_positions_local   : local DB view of open positions

Configuration in Claude Desktop config (claude_desktop_config.json):

  {
    "mcpServers": {
      "tradier-paper": {
        "command": "python",
        "args": ["-m", "mcp_servers.tradier_paper.server"],
        "env": {
          "TRADIER_REPO_ROOT": "C:\\\\Dev\\\\GammaPulse"
        }
      }
    }
  }
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ is None:
    SCRIPT_DIR = Path(__file__).resolve().parent
    REPO_ROOT = SCRIPT_DIR.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ENV_ROOT = os.getenv("TRADIER_REPO_ROOT")
if ENV_ROOT:
    REPO_ROOT = Path(ENV_ROOT)
os.chdir(REPO_ROOT)

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import Tool, TextContent  # noqa: E402

from server.tradier_paper import TradierPaperClient, SANDBOX_BASE  # noqa: E402
from server import paper_executions as pe  # noqa: E402


server = Server("tradier-paper")


def _format_json(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, default=str)
    except Exception:
        return repr(data)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tr_user_profile",
            description=("List user profile + linked accounts. Returns "
                         "account_number, type, classification, status."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tr_balance",
            description="Cash + equity + buying power for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string",
                                   "description": "Optional; uses TRADIER_PAPER_ACCOUNT_ID env if omitted"},
                },
                "required": [],
            },
        ),
        Tool(
            name="tr_positions",
            description="Current open positions in the paper account.",
            inputSchema={
                "type": "object",
                "properties": {"account_id": {"type": "string"}},
                "required": [],
            },
        ),
        Tool(
            name="tr_quote",
            description=("Real-time quote for one or more symbols. "
                         "For options use OCC format e.g. SPY260504C00720000."),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {"type": "array",
                                "items": {"type": "string"}},
                },
                "required": ["symbols"],
            },
        ),
        Tool(
            name="tr_place_paper_order",
            description=("Place an option order on Tradier paper. DEFAULT "
                         "IS preview_only=True (returns preview without "
                         "executing). Set preview_only=False to actually "
                         "submit. action: buy_to_open, sell_to_close, "
                         "sell_to_open, buy_to_close."),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "expiration_date": {"type": "string",
                                        "description": "YYYY-MM-DD"},
                    "strike": {"type": "number"},
                    "call_or_put": {"type": "string",
                                    "enum": ["CALL", "PUT"]},
                    "action": {"type": "string",
                               "enum": ["buy_to_open", "sell_to_close",
                                        "sell_to_open", "buy_to_close"]},
                    "quantity": {"type": "integer", "minimum": 1},
                    "order_type": {"type": "string",
                                   "enum": ["market", "limit", "stop", "stop_limit"],
                                   "default": "limit"},
                    "limit_price": {"type": "number"},
                    "stop_price": {"type": "number"},
                    "preview_only": {"type": "boolean", "default": True},
                },
                "required": ["ticker", "expiration_date", "strike",
                             "call_or_put", "action", "quantity"],
            },
        ),
        Tool(
            name="tr_list_orders",
            description=("List all orders for the account. Tradier doesn't "
                         "filter by status server-side — pass status_filter "
                         "to get just those (caller-side filtering)."),
            inputSchema={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "e.g. ['open', 'pending'] or ['filled']",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="tr_cancel_order",
            description="Cancel an open order by id.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
            },
        ),
        Tool(
            name="tr_paper_executions_today",
            description=("Query local paper_executions DB for today's "
                         "auto-executor activity."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tr_executor_status",
            description=("Aggregated stats: alerts seen, fills, open "
                         "positions, mean P&L."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tr_open_positions_local",
            description=("Local paper_executions DB view of open positions "
                         "(filled but not yet exited)."),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        client = TradierPaperClient()
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"ERROR: TradierPaperClient init failed: {e}\n\n"
                 f"Check TRADIER_PAPER_TOKEN + TRADIER_PAPER_ACCOUNT_ID in .env",
        )]

    try:
        if name == "tr_user_profile":
            profile = await client.user_profile()
            return [TextContent(
                type="text",
                text=f"Tradier paper profile (env={SANDBOX_BASE}):\n\n"
                     + _format_json(profile),
            )]

        elif name == "tr_balance":
            aid = arguments.get("account_id")
            data = await client.account_balance(aid)
            return [TextContent(type="text", text=_format_json(data))]

        elif name == "tr_positions":
            aid = arguments.get("account_id")
            positions = await client.account_positions(aid)
            return [TextContent(
                type="text",
                text=f"{len(positions)} open positions:\n\n"
                     + _format_json(positions),
            )]

        elif name == "tr_quote":
            quotes = await client.quote(arguments["symbols"])
            return [TextContent(type="text", text=_format_json(quotes))]

        elif name == "tr_place_paper_order":
            args = dict(arguments)
            preview_only = args.pop("preview_only", True)
            result = await client.place_option_order(
                account_id_key=None,
                symbol=args["ticker"],
                expiration_date=args["expiration_date"],
                strike=float(args["strike"]),
                call_or_put=args["call_or_put"],
                action=args["action"],
                quantity=int(args["quantity"]),
                order_type=args.get("order_type", "limit"),
                limit_price=args.get("limit_price"),
                stop_price=args.get("stop_price"),
                time_in_force="day",
                preview_only=preview_only,
            )
            mode = "PREVIEW (not executed)" if preview_only else "EXECUTED"
            return [TextContent(
                type="text",
                text=f"Order {mode}\n\n{_format_json(result)}",
            )]

        elif name == "tr_list_orders":
            status_filter = arguments.get("status_filter")
            if status_filter:
                orders = await client.list_orders_by_status(
                    statuses=tuple(s.lower() for s in status_filter),
                )
            else:
                orders = await client.list_orders()
            return [TextContent(
                type="text",
                text=f"{len(orders)} orders"
                     + (f" matching {status_filter}" if status_filter else "")
                     + f":\n\n{_format_json(orders)}",
            )]

        elif name == "tr_cancel_order":
            data = await client.cancel_order(int(arguments["order_id"]))
            return [TextContent(
                type="text",
                text=f"Cancel result:\n\n{_format_json(data)}",
            )]

        elif name == "tr_paper_executions_today":
            rows = pe.get_today()
            return [TextContent(
                type="text",
                text=f"{len(rows)} executions today:\n\n{_format_json(rows)}",
            )]

        elif name == "tr_executor_status":
            summary = pe.summary_today()
            return [TextContent(type="text", text=_format_json(summary))]

        elif name == "tr_open_positions_local":
            rows = pe.get_open_positions()
            return [TextContent(
                type="text",
                text=f"{len(rows)} open positions in local DB:\n\n"
                     + _format_json(rows),
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


async def main_async() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
