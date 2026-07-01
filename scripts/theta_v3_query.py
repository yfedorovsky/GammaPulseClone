"""Ad-hoc ThetaData OPRA tape query helper — Terminal-free (Python library).

Migrated 2026-06-30 off the local Theta Terminal REST (port 25503) to the `thetadata`
Python library (gRPC direct to Theta), so it runs headless from any context — no Terminal
required. Same commands, same output. Auth via THETADATA_API_KEY (loaded from .env by
server.thetadata_lib).

Use for ad-hoc OPRA tape verification when investigating mis-classified trades, NBBO
discrepancies, or sweep signatures.

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

Arg format (unchanged):
    - Expiration / date: YYYYMMDD (e.g. 20260702)
    - Strike: DOLLARS (215)
    - Right: C or P
    - Time of day: HH:MM:SS.SSS
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.thetadata_lib import _get_client  # noqa: E402


def _client():
    c = _get_client()
    if c is None:
        print("ThetaData library unavailable — check THETADATA_API_KEY in .env")
        sys.exit(2)
    return c


def _date(s: str) -> _dt.date:
    s = str(s).replace("-", "")
    return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _right(r: str) -> str:
    return "call" if str(r).upper().startswith("C") else "put"


def _strike(s) -> str:
    return f"{float(s):.2f}"


def _col(df, *names):
    lc = {str(c).lower(): c for c in df.columns}
    for n in names:
        if n in lc:
            return lc[n]
    return None


def cmd_quote(symbol, expiration, strike, right, date, time_of_day):
    """NBBO at a moment (the 1s quote bar at that timestamp)."""
    c = _client()
    df = c.option_history_quote(
        symbol=symbol, expiration=str(expiration), strike=_strike(strike),
        right=_right(right), interval="1s", start_date=_date(date), end_date=_date(date),
        start_time=time_of_day, end_time=time_of_day,
    )
    print(df.to_string() if df is not None and len(df) else "  (no quote at that moment)")


def cmd_trade(symbol, expiration, strike, right, date, time_of_day):
    """Trade(s) at a moment."""
    c = _client()
    df = c.option_history_trade(
        symbol=symbol, expiration=str(expiration), strike=_strike(strike),
        right=_right(right), start_date=_date(date), end_date=_date(date),
        start_time=time_of_day, end_time=time_of_day,
    )
    print(df.to_string() if df is not None and len(df) else "  (no trade at that moment)")


def cmd_side(symbol, expiration, strike, right, date,
             start_time="09:30:00.000", end_time="16:00:00.000"):
    """Aggressor-side analysis: trades paired with NBBO → % at/above ask (buying),
    at/below bid (selling), mid. The canonical 'is this real, and was it BOUGHT?' check.
    Default window = full RTH."""
    c = _client()
    df = c.option_history_trade_quote(
        symbol=symbol, expiration=str(expiration), strike=_strike(strike),
        right=_right(right), start_date=_date(date), end_date=_date(date),
        start_time=start_time, end_time=end_time,
    )
    if df is None or len(df) == 0:
        print("  no data for that contract/window")
        return
    i_sz, i_px = _col(df, "size"), _col(df, "price")
    i_bid, i_ask = _col(df, "bid"), _col(df, "ask")
    if None in (i_sz, i_px, i_bid, i_ask):
        print(f"  unexpected columns: {list(df.columns)}")
        return
    ask = bid = mid = total = 0
    px_lo = px_hi = None
    for row in df.itertuples(index=False):
        d = row._asdict()
        try:
            s = int(d[i_sz]); p = float(d[i_px])
            b = float(d[i_bid]); a = float(d[i_ask])
        except (ValueError, TypeError):
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
    print(f"  prints={len(df)}  contracts={total}  price_range=${px_lo}-${px_hi}")
    if total:
        ap, bp, mp = 100 * ask / total, 100 * bid / total, 100 * mid / total
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
    c = _client()
    df = c.option_history_trade(
        symbol=symbol, expiration=str(expiration), strike=_strike(strike),
        right=_right(right), start_date=_date(date), end_date=_date(date),
        start_time=start_time, end_time=end_time,
    )
    if df is None or len(df) == 0:
        print("  no trades in window")
        return
    print(df.head(50).to_string())
    if len(df) > 50:
        print(f"... ({len(df)-50} more rows)")
    i_sz, i_ex, i_px = _col(df, "size"), _col(df, "exchange"), _col(df, "price")
    total_size, venues, prices = 0, set(), set()
    for row in df.itertuples(index=False):
        d = row._asdict()
        try:
            total_size += int(d[i_sz]); venues.add(d[i_ex]); prices.add(round(float(d[i_px]), 2))
        except (ValueError, TypeError):
            pass
    print(f"\nSUMMARY: {len(df)} trades, {total_size} contracts, "
          f"{len(venues)} distinct exchanges, prices: {sorted(prices)[:5]}"
          f"{'...' if len(prices) > 5 else ''}")


def cmd_health():
    """Library health check (auth + a cheap list call)."""
    c = _client()
    try:
        df = c.option_list_expirations(symbol="SPY")
        n = len(df) if df is not None else 0
        print(f"OK — library authenticated, SPY expirations returned: {n}")
    except Exception as e:
        print(f"FAIL: {e!r}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1].lower()
    args = sys.argv[2:]
    dispatch = {"quote": cmd_quote, "trade": cmd_trade, "burst": cmd_burst,
                "side": cmd_side, "health": cmd_health}
    fn = dispatch.get(cmd)
    if fn is None:
        print(f"unknown command: {cmd}")
        return 1
    try:
        fn(*args)
    except TypeError as e:
        print(f"ARG ERROR: {e}\nSee docstring for usage.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
