"""Direct ThetaData v3 REST query helper.

The mcp__ThetaData__* server uses deprecated v2 API endpoints and will
either time out or return HTTP 410. This script talks to the local
Theta Terminal directly on port 25503 with v3 paths/params/strike-in-
dollars/HH:MM:SS.SSS time format.

Use for ad-hoc OPRA tape verification when investigating mis-classified
trades, NBBO discrepancies, or sweep signatures.

Usage:
    # NBBO at a specific moment
    python scripts/theta_v3_query.py quote NVDA 20260702 215 C 20260604 12:32:29.000

    # Single trade at a specific moment
    python scripts/theta_v3_query.py trade NVDA 20260702 215 C 20260604 12:32:29.500

    # Trade history in a window
    python scripts/theta_v3_query.py burst NVDA 20260702 215 C 20260604 \\
        12:32:00.000 12:33:00.000

    # Aggressor-side split — "is it real, and was it BOUGHT?" (default RTH window)
    python scripts/theta_v3_query.py side MRVL 20260821 170 C 20260605
    # → 66% ask = REAL ASK BUYING; 45% ask/52% mid = MIXED/DISTRIBUTED

Required v3 format reminders:
    - URL paths use /v3/, not /v2/
    - Symbol param is `symbol=`, not `root=`
    - Expiration param is `expiration=`, not `exp=`
    - Strike is in DOLLARS (215), not thousandths (215000)
    - Time of day is HH:MM:SS.SSS, not milliseconds since midnight
    - Response is CSV, not JSON
"""
from __future__ import annotations

import sys
import requests


REST = "http://127.0.0.1:25503"


def _print_csv(text: str) -> None:
    for line in text.splitlines():
        print(line)


def cmd_quote(symbol, expiration, strike, right, date, time_of_day):
    """NBBO at a moment."""
    url = f"{REST}/v3/option/at_time/quote"
    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": strike, "right": right,
        "start_date": date, "end_date": date,
        "time_of_day": time_of_day,
    }
    r = requests.get(url, params=params, timeout=10)
    _print_csv(r.text)


def cmd_trade(symbol, expiration, strike, right, date, time_of_day):
    """Single trade at a moment."""
    url = f"{REST}/v3/option/at_time/trade"
    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": strike, "right": right,
        "start_date": date, "end_date": date,
        "time_of_day": time_of_day,
    }
    r = requests.get(url, params=params, timeout=10)
    _print_csv(r.text)


def cmd_side(symbol, expiration, strike, right, date,
             start_time="09:30:00.000", end_time="16:00:00.000"):
    """Aggressor-side analysis: trades paired with NBBO → % at/above ask
    (buying), at/below bid (selling), mid. Answers 'was this real, and
    was it BOUGHT?' for any contract+window. Default window = full RTH.

    This is the canonical 'is the print real and aggressive' check —
    e.g. MRVL 260C 8/21 on 6/5 came back 45% ask / 52% mid = mixed, while
    the 170C was 66% ask = genuine buying.
    """
    url = f"{REST}/v3/option/history/trade_quote"
    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": strike, "right": right,
        "start_date": date, "end_date": date,
        "start_time": start_time, "end_time": end_time,
    }
    try:
        r = requests.get(url, params=params, timeout=90)
    except requests.Timeout:
        print("  trade_quote timed out (>90s) — window too large. Narrow it.")
        return
    lines = r.text.splitlines()
    if len(lines) < 2:
        print(f"  no data / error: {lines[:1]}")
        return
    hdr = [h.strip().strip('"') for h in lines[0].split(",")]

    def ix(name):
        return hdr.index(name) if name in hdr else -1
    i_sz, i_px, i_bid, i_ask = ix("size"), ix("price"), ix("bid"), ix("ask")
    if min(i_sz, i_px, i_bid, i_ask) < 0:
        print(f"  unexpected columns: {hdr}")
        return
    ask = bid = mid = total = 0
    px_lo = px_hi = None
    for ln in lines[1:]:
        c = ln.split(",")
        try:
            s = int(c[i_sz]); p = float(c[i_px])
            b = float(c[i_bid]); a = float(c[i_ask])
        except (ValueError, IndexError):
            continue
        total += s
        px_lo = p if px_lo is None else min(px_lo, p)
        px_hi = p if px_hi is None else max(px_hi, p)
        if a > 0 and p >= a:
            ask += s
        elif b > 0 and p <= b:
            bid += s
        else:
            mid += s
    print(f"  {symbol} {strike}{right} {expiration}  {start_time}-{end_time}")
    print(f"  prints={len(lines)-1}  contracts={total}  "
          f"price_range=${px_lo}-${px_hi}")
    if total:
        ap, bp, mp = 100*ask/total, 100*bid/total, 100*mid/total
        print(f"  AT/ABOVE ASK: {ask:>7} ({ap:.0f}%)")
        print(f"  AT/BELOW BID: {bid:>7} ({bp:.0f}%)")
        print(f"  MID:          {mid:>7} ({mp:.0f}%)")
        if ap >= 55:
            v = "REAL ASK BUYING (aggressive)"
        elif ap >= 40:
            v = "MIXED / DISTRIBUTED (worked order or two-sided)"
        elif bp >= 55:
            v = "SELLING (hitting the bid)"
        else:
            v = "NO CLEAR AGGRESSOR"
        print(f"  VERDICT: {v}")


def cmd_burst(symbol, expiration, strike, right, date, start_time, end_time):
    """Trade history in a window — useful for sweep analysis."""
    url = f"{REST}/v3/option/history/trade"
    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": strike, "right": right,
        "start_date": date, "end_date": date,
        "start_time": start_time, "end_time": end_time,
    }
    r = requests.get(url, params=params, timeout=15)
    lines = r.text.splitlines()
    if len(lines) > 1:
        print(lines[0])  # header
        for line in lines[1:51]:
            print(line)
        if len(lines) > 51:
            print(f"... ({len(lines)-51} more rows)")
        # Summary
        total_size = 0
        venues: set[str] = set()
        prices: set[str] = set()
        for line in lines[1:]:
            cols = line.split(",")
            if len(cols) >= 14:
                try:
                    total_size += int(cols[11])
                    venues.add(cols[12])
                    prices.add(cols[13])
                except (ValueError, IndexError):
                    pass
        print()
        print(f"SUMMARY: {len(lines)-1} trades, "
              f"{total_size} contracts, "
              f"{len(venues)} distinct exchanges, "
              f"prices: {sorted(prices)[:5]}{'...' if len(prices)>5 else ''}")


def cmd_health():
    """v3 health check."""
    try:
        r = requests.get(
            f"{REST}/v3/option/list/expirations",
            params={"symbol": "SPY"}, timeout=5,
        )
        ok = r.status_code == 200
        line_count = len(r.text.splitlines())
        print(f"Status: {r.status_code}  Expirations returned: {line_count-1}  "
              f"{'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"FAIL: {e!r}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1].lower()
    args = sys.argv[2:]
    try:
        if cmd == "quote":
            cmd_quote(*args)
        elif cmd == "trade":
            cmd_trade(*args)
        elif cmd == "burst":
            cmd_burst(*args)
        elif cmd == "side":
            cmd_side(*args)
        elif cmd == "health":
            cmd_health()
        else:
            print(f"unknown command: {cmd}")
            return 1
    except TypeError as e:
        print(f"ARG ERROR: {e}\nSee docstring for usage.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
