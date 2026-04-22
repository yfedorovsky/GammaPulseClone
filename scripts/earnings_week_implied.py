"""Compute implied moves for the Wed/Thu PM earnings stack via ThetaData.

Why this script: Perplexity can't pull live options data, and MarketChameleon
is paywalled. But we already pay for ThetaData Options Standard ($80/mo) —
which gives us NBBO + IV + Greeks on the full OPRA chain via REST.

Pulls 4/25 weekly expiry ATM straddle for each name and computes:
  - ATM implied move from straddle price
  - Composite IV (average of ATM call + put IV)
  - Current spot, ATM strike, straddle mid

Usage:
    python -m scripts.earnings_week_implied
    python -m scripts.earnings_week_implied --expiry 20260425
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.thetadata import ThetaDataClient  # noqa: E402


TICKERS = ["TSLA", "LRCX", "NOW", "IBM", "TXN", "INTC", "DLR"]
DEFAULT_EXPIRY = "2026-04-24"  # Weekly expiry capturing Wed PM + Thu PM earnings


def _f(v, default=0.0):
    """Coerce ThetaData string value to float."""
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def find_atm_pair(rows: list[dict], spot: float, expiry: str):
    """Find ATM call + put from chain rows. Returns (call, put) or (None, None)."""
    chain = [r for r in rows if str(r.get("expiration")) == expiry]
    if not chain:
        return None, None
    strikes = sorted({_f(r.get("strike")) for r in chain if r.get("strike")})
    strikes = [s for s in strikes if s > 0]
    if not strikes:
        return None, None
    atm_strike = min(strikes, key=lambda s: abs(s - spot))
    atm_call = next(
        (r for r in chain
         if _f(r.get("strike")) == atm_strike and r.get("right") == "CALL"),
        None,
    )
    atm_put = next(
        (r for r in chain
         if _f(r.get("strike")) == atm_strike and r.get("right") == "PUT"),
        None,
    )
    return atm_call, atm_put


def mid(q: dict) -> float | None:
    """Return mid price from bid/ask, or None if invalid."""
    if not q:
        return None
    bid = _f(q.get("bid"))
    ask = _f(q.get("ask"))
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


async def run(expiry: str, tickers: list[str]):
    client = ThetaDataClient()
    print(f"Computing ATM straddle implied moves for expiry {expiry}")
    print(f"{'Ticker':<8}{'Spot':>10}{'ATM K':>10}{'Call':>8}{'Put':>8}"
          f"{'Strdl':>8}{'Impl%':>9}{'IV_C':>8}{'IV_P':>8}")
    print("-" * 77)

    for t in tickers:
        try:
            # snapshot_chain_greeks returns (rows, underlying_price)
            rows, spot = await client.snapshot_chain_greeks(t, expiration=expiry)
        except Exception as e:
            print(f"{t:<8}  ERROR: {e}")
            continue

        if not rows or spot is None or spot <= 0:
            print(f"{t:<8}  no chain data for {expiry}")
            continue

        atm_call, atm_put = find_atm_pair(rows, spot, expiry)
        if not atm_call or not atm_put:
            print(f"{t:<8}  no ATM pair found near ${spot:.2f}")
            continue

        c_mid = mid(atm_call)
        p_mid = mid(atm_put)
        if c_mid is None or p_mid is None:
            print(f"{t:<8}  invalid quote (bid/ask missing)")
            continue

        straddle = c_mid + p_mid
        impl_move_pct = (straddle / spot) * 100
        atm_k = _f(atm_call["strike"])
        iv_c = _f(atm_call.get("implied_vol")) * 100
        iv_p = _f(atm_put.get("implied_vol")) * 100

        print(f"{t:<8}{spot:>10.2f}{atm_k:>10.2f}"
              f"{c_mid:>8.2f}{p_mid:>8.2f}{straddle:>8.2f}"
              f"{impl_move_pct:>8.2f}%{iv_c:>8.1f}{iv_p:>8.1f}")

    await client.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expiry", default=DEFAULT_EXPIRY,
                    help=f"YYYY-MM-DD expiry (default: {DEFAULT_EXPIRY})")
    ap.add_argument("--tickers", default=",".join(TICKERS),
                    help="Comma-separated tickers (default: baked-in list)")
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    asyncio.run(run(args.expiry, tickers))


if __name__ == "__main__":
    main()
