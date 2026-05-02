"""Interactive OAuth 1.0a setup for E-Trade.

ONE-TIME PER ENVIRONMENT (sandbox vs production):

1. Sign up for E-Trade developer account: https://developer.etrade.com/
2. Get sandbox consumer key + secret (also prod ones if you intend to
   trade real money — separate creds)
3. Add to .env:
     ETRADE_SANDBOX_KEY=...
     ETRADE_SANDBOX_SECRET=...
     ETRADE_KEY=...           # production, only set if you'll go live
     ETRADE_SECRET=...
     ETRADE_USE_SANDBOX=1     # always start sandbox-only

4. Run this script:
     python scripts/etrade_oauth_setup.py

5. It will:
   - Request a temporary OAuth request token
   - Print a URL for you to visit in your browser
   - Wait for you to paste back the verification code displayed on E-Trade's
     authorization page
   - Exchange that for the long-lived access token
   - Save tokens to .etrade_tokens.json (in repo root, gitignored)

After this, the executor and MCP server will use the cached token. Tokens
expire daily at midnight US ET — re-run this script each trading morning,
OR call ETradeClient.renew_access_token() programmatically (which extends
an idle token's life within the same day).

DAILY OPERATIONAL FLOW:
  morning:  python scripts/etrade_oauth_setup.py     (5-min interactive)
  market:   executor + MCP daemon use cached token
  midnight: token expires; tomorrow morning re-auth

USAGE:
  python scripts/etrade_oauth_setup.py                # default sandbox
  python scripts/etrade_oauth_setup.py --prod         # production
  python scripts/etrade_oauth_setup.py --renew-only   # try renewal first
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.etrade import (  # noqa: E402
    ETradeClient, Token, _consumer_credentials, _is_sandbox,
    get_cached_token, save_token,
)


async def renew_existing(client: ETradeClient) -> bool:
    print("[etrade-setup] attempting to renew existing token...", flush=True)
    ok = await client.renew_access_token()
    if ok:
        print("[etrade-setup] renewal succeeded — token good until next midnight ET")
    else:
        print("[etrade-setup] renewal failed — full re-auth required")
    return ok


async def full_oauth_flow() -> None:
    print(f"[etrade-setup] env = {'SANDBOX' if _is_sandbox() else '*** PRODUCTION ***'}")
    if not _is_sandbox():
        confirm = input(
            "*** PRODUCTION ENVIRONMENT — orders will be real money. "
            "Type 'YES PROD' to proceed: "
        ).strip()
        if confirm != "YES PROD":
            print("Aborted.")
            return

    consumer_key, consumer_secret = _consumer_credentials()
    print(f"[etrade-setup] consumer_key={consumer_key[:8]}...")

    # Step 1: request token
    print("[etrade-setup] requesting temporary request token...")
    request_token = await ETradeClient.get_request_token(
        consumer_key, consumer_secret,
    )
    print(f"[etrade-setup] request_token={request_token.oauth_token[:12]}...")

    # Step 2: browser auth
    auth_url = ETradeClient.authorize_url(consumer_key, request_token)
    print()
    print("=" * 70)
    print("BROWSER AUTHORIZATION REQUIRED")
    print("=" * 70)
    print()
    print(f"Open this URL in your browser:")
    print(f"  {auth_url}")
    print()
    print("Sign in to E-Trade if needed, click Accept, and copy the")
    print("verification code shown on the next page.")
    print()
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    verifier = input("Paste verification code here: ").strip()
    if not verifier:
        print("[etrade-setup] no code entered — aborted")
        return

    # Step 3: exchange for access token
    print("[etrade-setup] exchanging verifier for access token...")
    access_token = await ETradeClient.exchange_for_access_token(
        consumer_key, consumer_secret, request_token, verifier,
    )
    save_token(access_token)
    print(f"[etrade-setup] saved access token (env={'sandbox' if _is_sandbox() else 'prod'})")

    # Quick sanity check: list accounts
    print("[etrade-setup] sanity check — listing accounts...")
    client = ETradeClient(token=access_token)
    try:
        accounts = await client.list_accounts()
        if accounts:
            for a in accounts:
                # Field names vary; print common ones
                print(f"  account: id={a.get('accountId')} "
                      f"id_key={a.get('accountIdKey')} "
                      f"type={a.get('accountType')} status={a.get('accountStatus')}")
        else:
            print("  no accounts returned (may be normal for fresh sandbox)")
    finally:
        await client.close()
    print("[etrade-setup] done. Cached at .etrade_tokens.json")


async def main_async() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", action="store_true",
                   help="Use production (real money) instead of sandbox")
    p.add_argument("--renew-only", action="store_true",
                   help="Try renewing the cached token; only do full auth on failure")
    args = p.parse_args()

    if args.prod:
        os.environ["ETRADE_USE_SANDBOX"] = "0"

    if args.renew_only:
        cached = get_cached_token()
        if cached is not None:
            client = ETradeClient(token=cached)
            try:
                if await renew_existing(client):
                    return 0
            finally:
                await client.close()
        print("[etrade-setup] no cached token or renewal failed — full re-auth")

    await full_oauth_flow()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
