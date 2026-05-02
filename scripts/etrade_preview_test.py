"""One-shot preview-only sanity check for E-Trade integration.

Verifies that:
  1. We're in sandbox mode (asserts ETRADE_USE_SANDBOX=1)
  2. The cached OAuth token works
  3. The order placement pipeline can construct + preview an option order
     against the account ID you pass

Submits NOTHING. Uses preview_only=True. Safe to run anytime.

Usage:
  python scripts/etrade_preview_test.py --account-id YOUR_ID_KEY

Defaults to a far-OTM SPY call at $0.05 limit so even if preview_only
were ignored (it isn't), nothing would fill.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.etrade import ETradeClient, get_cached_token, _is_sandbox, _base_url  # noqa: E402


def _next_weekday(target: datetime) -> datetime:
    """If today is Sat/Sun, push to Monday. Else use target as-is."""
    while target.weekday() >= 5:
        target = target + timedelta(days=1)
    return target


async def run(account_id_key: str, ticker: str, strike: float,
              expiration: str | None) -> int:
    print(f"[test] env: sandbox={_is_sandbox()}  base_url={_base_url()}",
          flush=True)
    if not _is_sandbox():
        print("[test] ABORT — not in sandbox mode. "
              "Set ETRADE_USE_SANDBOX=1 in .env before retrying.",
              file=sys.stderr)
        return 1

    token = get_cached_token()
    if token is None:
        print("[test] ABORT — no cached token. "
              "Run scripts/etrade_oauth_setup.py first.",
              file=sys.stderr)
        return 1

    if expiration is None:
        # Default: next weekday from today
        exp_dt = _next_weekday(datetime.now())
        expiration = exp_dt.strftime("%Y-%m-%d")

    print(f"[test] account: {account_id_key}")
    print(f"[test] order: {ticker} {strike}C exp {expiration} qty 1 LIMIT $0.05")
    print(f"[test] preview_only=True (NOTHING submitted)")
    print()

    client = ETradeClient(token=token)
    try:
        result = await client.place_option_order(
            account_id_key=account_id_key,
            symbol=ticker,
            expiration_date=expiration,
            strike=float(strike),
            call_or_put="CALL",
            action="BUY_OPEN",
            quantity=1,
            order_type="LIMIT",
            limit_price=0.05,
            preview_only=True,
        )
    except Exception as e:
        print(f"[test] ERROR placing preview: {type(e).__name__}: {e}",
              file=sys.stderr)
        await client.close()
        return 1

    preview = result.get("preview_response", {}).get("PreviewOrderResponse", {})
    preview_ids = preview.get("PreviewIds", [])

    if preview_ids:
        pid = preview_ids[0].get("previewId")
        print(f"[test] PREVIEW OK — previewId={pid}")
        # Try to extract estimated commission + total cost if E-Trade returned them
        order_resp = preview.get("Order", [])
        if isinstance(order_resp, dict):
            order_resp = [order_resp]
        if order_resp:
            order = order_resp[0]
            print(f"[test] estimated total cost: ${order.get('estimatedTotalAmount')}")
            print(f"[test] estimated commission: ${order.get('estimatedCommission')}")
        print()
        print("[test] PASS — OAuth + order pipeline working. Nothing submitted.")
        await client.close()
        return 0

    print(f"[test] FAIL — preview returned no previewId")
    print(f"[test] full response: {result}")
    await client.close()
    return 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account-id", required=True,
                   help="E-Trade account_id_key (run --list-accounts to find)")
    p.add_argument("--ticker", default="SPY",
                   help="Underlying for test order (default: SPY)")
    p.add_argument("--strike", type=float, default=580.0,
                   help="Strike for test order (default: 580 — far OTM)")
    p.add_argument("--expiration", default=None,
                   help="YYYY-MM-DD, default: next weekday")
    args = p.parse_args()
    return asyncio.run(run(args.account_id, args.ticker, args.strike,
                           args.expiration))


if __name__ == "__main__":
    sys.exit(main())
