"""One-time validation script for Tradier paper account setup.

Verifies:
  1. TRADIER_PAPER_TOKEN is set in .env
  2. Token works against sandbox.tradier.com
  3. user/profile returns linked accounts
  4. Account balance + positions queryable

Run AFTER adding TRADIER_PAPER_TOKEN to .env. If TRADIER_PAPER_ACCOUNT_ID
isn't set, this script will print the available account IDs and you can
add the right one.

Usage:
  python scripts/tradier_paper_setup.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    print("=" * 70)
    print("  Tradier Paper Account Setup Validation")
    print("=" * 70)

    if not os.getenv("TRADIER_PAPER_TOKEN"):
        print("FAIL: TRADIER_PAPER_TOKEN not set in .env")
        print()
        print("To fix:")
        print("  1. Sign up / log in at https://developer.tradier.com")
        print("  2. Generate Sandbox Access Token")
        print("  3. Add to .env:")
        print("       TRADIER_PAPER_TOKEN=<your_sandbox_token>")
        print("  4. Re-run this script")
        return 1
    print(f"  [+] TRADIER_PAPER_TOKEN set "
          f"({os.environ['TRADIER_PAPER_TOKEN'][:8]}...)")

    # Defer import until env check passes (so the env error message is clear)
    from server.tradier_paper import TradierPaperClient, SANDBOX_BASE

    print(f"  [+] base URL: {SANDBOX_BASE}")

    # We'll override the account ID req for this script
    has_account_id = os.getenv("TRADIER_PAPER_ACCOUNT_ID") is not None
    if not has_account_id:
        # Set a placeholder so client init doesn't error
        os.environ["TRADIER_PAPER_ACCOUNT_ID"] = "PLACEHOLDER"

    client = TradierPaperClient()
    try:
        print(f"  [.] querying user profile + accounts...")
        profile = await client.user_profile()
    except Exception as e:
        print(f"  [X] FAIL: {type(e).__name__}: {e}")
        await client.close()
        return 1

    accounts_payload = profile.get("account") or []
    if isinstance(accounts_payload, dict):
        accounts_payload = [accounts_payload]
    print(f"  [+] returned {len(accounts_payload)} account(s)")
    print()
    for a in accounts_payload:
        print(f"    account: number={a.get('account_number')} "
              f"type={a.get('type')} "
              f"classification={a.get('classification')} "
              f"status={a.get('status')}")
    print()

    if not has_account_id:
        print("=" * 70)
        if accounts_payload:
            primary = accounts_payload[0]
            acct_num = primary.get("account_number")
            print(f"  Add this to your .env:")
            print(f"    TRADIER_PAPER_ACCOUNT_ID={acct_num}")
        print("=" * 70)
        await client.close()
        return 0

    # If account ID is set, do balance + positions sanity check
    aid = os.environ["TRADIER_PAPER_ACCOUNT_ID"]
    print(f"  [.] querying account_balance for {aid}...")
    try:
        balance = await client.account_balance(aid)
        cash = balance.get("cash", {}).get("cash_available")
        equity = balance.get("total_equity")
        bp = balance.get("margin", {}).get("option_buying_power") or \
             balance.get("cash", {}).get("cash_available")
        print(f"  [+] equity=${equity}  cash=${cash}  option_BP=${bp}")
    except Exception as e:
        print(f"  [X] account_balance failed: {type(e).__name__}: {e}")
        await client.close()
        return 1

    print(f"  [.] querying positions...")
    try:
        positions = await client.account_positions(aid)
        print(f"  [+] {len(positions)} open positions")
        for p in positions[:5]:
            print(f"      {p.get('symbol')} qty={p.get('quantity')} "
                  f"cost_basis=${p.get('cost_basis')}")
    except Exception as e:
        print(f"  [!] positions failed: {type(e).__name__}: {e} "
              f"(may be normal if no positions)")

    print(f"  [.] testing quote endpoint...")
    try:
        quotes = await client.quote(["SPY"])
        spy = quotes[0] if quotes else {}
        last = spy.get("last")
        print(f"  [+] SPY last=${last}")
    except Exception as e:
        print(f"  [X] quote failed: {type(e).__name__}: {e}")
        await client.close()
        return 1

    print()
    print("=" * 70)
    print("  ALL CHECKS PASSED — ready to launch tradier_executor")
    print("=" * 70)
    print()
    print("  Next: python -m server.tradier_executor")

    await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
