"""Compute implied moves for the upcoming earnings stack via ThetaData.

Why this script: Perplexity can't pull live options data, and MarketChameleon
is paywalled. But we already pay for ThetaData Options Standard ($80/mo) —
which gives us NBBO + IV + Greeks on the full OPRA chain via REST.

Default behavior (run with no args):
  1. Pulls next 7 days of mega-cap earnings from Finnhub
  2. Picks the next Friday weekly expiry (captures Mon-Thu prints)
  3. Computes ATM straddle implied move for each name

Overrides:
    python -m scripts.earnings_week_implied --expiry 2026-05-01
    python -m scripts.earnings_week_implied --tickers AAPL,MSFT,GOOGL
    python -m scripts.earnings_week_implied --static    # use baked-in list

Implied move math:
  ATM straddle = ATM call mid + ATM put mid
  Implied % move = straddle / spot * 100  (single-day-ish approximation;
                   a sharper estimate uses 0.85 × straddle / spot but the
                   straight ratio matches MarketChameleon's headline number)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
from pathlib import Path

import httpx
import io as _io

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(".env")

from server.thetadata import ThetaDataClient  # noqa: E402


# Fallback list — last resort when Finnhub is unavailable AND --static used.
# Updated periodically; not a single-source-of-truth.
STATIC_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AVGO", "MRVL", "QCOM", "AMD", "MU", "KLAC", "LRCX", "AMAT",
    "V", "MA", "JPM", "BAC", "XOM", "CVX",
]

# Mega-cap filter for the Finnhub auto-pick path. Keeps the output focused
# on tape-moving names instead of every smallcap reporting that week.
MEGA_CAP = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "AVGO", "ORCL", "ADBE", "NFLX", "AMD", "QCOM", "INTC", "TSM",
    "ASML", "MU", "MRVL", "AMAT", "KLAC", "LRCX",
    "JPM", "BAC", "WFC", "GS", "MS",
    "XOM", "CVX",
    "WMT", "COST", "HD", "UNH", "JNJ", "PG", "V", "MA",
    "CRWD", "PANW", "PLTR", "SMCI", "ANET", "VRT", "DELL",
}


def next_friday(today: dt.date | None = None) -> dt.date:
    """Return the next Friday from today (or today if today is Friday)."""
    today = today or dt.date.today()
    days_until = (4 - today.weekday()) % 7
    if days_until == 0 and today.weekday() != 4:
        days_until = 7
    return today + dt.timedelta(days=days_until or 7) if today.weekday() == 4 else today + dt.timedelta(days=days_until)


def fetch_earnings_tickers(days_ahead: int = 7) -> list[str]:
    """Pull tickers reporting in the next N days, filtered to mega-cap.
    Returns [] if Finnhub unavailable."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        print("[warn] FINNHUB_API_KEY not set — falling back to static list")
        return []
    today = dt.date.today()
    end = today + dt.timedelta(days=days_ahead)
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={"from": today.isoformat(), "to": end.isoformat(), "token": key},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        print(f"[warn] Finnhub earnings fetch failed: {e}")
        return []
    items = data.get("earningsCalendar", []) or []
    tickers = sorted({i["symbol"] for i in items
                      if i.get("symbol") in MEGA_CAP})
    return tickers


THETA_REST = "http://127.0.0.1:25503"


def list_expirations(ticker: str) -> list[dt.date]:
    """Pull all available option expirations for a ticker from ThetaData REST.
    Returns sorted list of date objects, [] on failure."""
    try:
        r = httpx.get(
            f"{THETA_REST}/v3/option/list/expirations",
            params={"symbol": ticker}, timeout=10,
        )
        if r.status_code != 200:
            return []
        out: list[dt.date] = []
        for line in r.text.strip().split("\n")[1:]:  # skip header
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                d = dt.date.fromisoformat(parts[1].strip().strip('"'))
                out.append(d)
            except ValueError:
                continue
        return sorted(out)
    except Exception:
        return []


def resolve_expiry(ticker: str, target: dt.date) -> tuple[str, int]:
    """Find the smallest available expiry >= target. Returns (iso_date, days_diff).
    days_diff > 7 means monthly fallback was used and the implied move
    includes extra time premium."""
    exps = list_expirations(ticker)
    candidates = [e for e in exps if e >= target]
    if not candidates:
        return target.isoformat(), 0
    chosen = candidates[0]
    return chosen.isoformat(), (chosen - target).days


def _f(v, default=0.0):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def find_atm_pair(rows: list[dict], spot: float, expiry: str):
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
    if not q:
        return None
    bid = _f(q.get("bid"))
    ask = _f(q.get("ask"))
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


async def run(target_expiry: str, tickers: list[str]):
    client = ThetaDataClient()
    target_date = dt.date.fromisoformat(target_expiry)
    print(f"\nComputing ATM straddle implied moves (target expiry {target_expiry})")
    print(f"Tickers: {', '.join(tickers)}\n")
    print(f"{'Ticker':<8}{'Expiry':>12}{'+d':>4}{'Spot':>10}{'ATM K':>10}"
          f"{'Call':>8}{'Put':>8}{'Strdl':>8}{'Impl%':>9}{'IV_C':>8}{'IV_P':>8}")
    print("-" * 95)

    for t in tickers:
        # Per-ticker expiry resolution: smallest available >= target.
        # Falls back to monthly when ticker has no weeklies (e.g. KLAC).
        expiry, days_offset = resolve_expiry(t, target_date)
        try:
            rows, spot = await client.snapshot_chain_greeks(t, expiration=expiry)
        except Exception as e:
            print(f"{t:<8}  ERROR: {e}")
            continue

        if not rows or spot is None or spot <= 0:
            print(f"{t:<8}  no chain data for {expiry}")
            continue

        atm_call, atm_put = find_atm_pair(rows, spot, expiry)
        if not atm_call or not atm_put:
            print(f"{t:<8}  no ATM pair found near ${spot:.2f} on {expiry}")
            continue

        c_mid = mid(atm_call)
        p_mid = mid(atm_put)
        if c_mid is None or p_mid is None:
            print(f"{t:<8}  invalid quote on {expiry} (bid/ask missing)")
            continue

        straddle = c_mid + p_mid
        impl_move_pct = (straddle / spot) * 100
        atm_k = _f(atm_call["strike"])
        iv_c = _f(atm_call.get("implied_vol")) * 100
        iv_p = _f(atm_put.get("implied_vol")) * 100

        # Flag monthly fallback in the offset column. Anything > 7 days off
        # the target Friday is contaminated by extra time premium and the
        # implied % overstates the pure earnings vol.
        offset_str = f"+{days_offset}" if days_offset else "  "
        if days_offset > 7:
            offset_str = f"+{days_offset}*"

        print(f"{t:<8}{expiry:>12}{offset_str:>4}{spot:>10.2f}{atm_k:>10.2f}"
              f"{c_mid:>8.2f}{p_mid:>8.2f}{straddle:>8.2f}"
              f"{impl_move_pct:>8.2f}%{iv_c:>8.1f}{iv_p:>8.1f}")

    print("\n* = monthly fallback, no weekly available; Impl% includes "
          "extra time premium beyond the earnings event")
    await client.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expiry", default=None,
                    help="YYYY-MM-DD expiry (default: next Friday)")
    ap.add_argument("--tickers", default=None,
                    help="Comma-separated tickers (default: Finnhub mega-cap earnings next 7d)")
    ap.add_argument("--static", action="store_true",
                    help="Use baked-in STATIC_TICKERS list instead of Finnhub.")
    args = ap.parse_args()

    # Resolve expiry
    if args.expiry:
        expiry = args.expiry
    else:
        expiry = next_friday().isoformat()
        print(f"[auto] next Friday expiry: {expiry}")

    # Resolve tickers
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.static:
        tickers = STATIC_TICKERS
        print(f"[static] using baked-in list ({len(tickers)} tickers)")
    else:
        tickers = fetch_earnings_tickers()
        if not tickers:
            print(f"[fallback] using STATIC_TICKERS ({len(STATIC_TICKERS)})")
            tickers = STATIC_TICKERS
        else:
            print(f"[auto] {len(tickers)} mega-caps with earnings next 7d")

    if not tickers:
        print("No tickers to query.")
        sys.exit(1)

    asyncio.run(run(expiry, tickers))


if __name__ == "__main__":
    main()
