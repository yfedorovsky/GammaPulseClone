"""Phase 1 / A1+A4: Backtest WHALE-RT classifier against today's flow_alerts.

Why this exists:
  Task #41 (whale classifier) + task #44 (real-time dispatch) shipped tonight.
  Today's 327K flow_alerts ran through the pre-whale code, so is_whale=0
  across the board. This script replays each alert through the CURRENT
  whale classifier gates to answer: "how many Telegram fires would have
  triggered had #41 + #44 been live during today's session?"

  Cross-checks against today's FL0WG0D screenshots (NVDA, NEE, etc.) and
  the Market Bishop NEE 77.5C catch.

Usage:
    python scripts/backtest_whale_rt_today.py [YYYY-MM-DD]

If date omitted, defaults to today.

Output:
  - Total alerts scanned
  - is_whale=1 simulated count (DB-tag floor, $1M)
  - WHALE-RT Telegram fires simulated count ($3M floor)
  - Breakdown by ticker (top 30)
  - Detailed table of would-be Telegram fires (every $3M+ ASK pass)
  - Cross-check: NVDA, NEE, CVS, NBIS specific lookups
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Repo root on sys.path so server imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.flow_alerts import (  # noqa: E402
    _classify_whale_signature,
    WHALE_MIN_NOTIONAL,
    WHALE_TELEGRAM_NOTIONAL,
)


def _parse_args() -> datetime.date:
    if len(sys.argv) > 1:
        return datetime.date.fromisoformat(sys.argv[1])
    return datetime.date.today()


def _ts_window(date: datetime.date) -> tuple[int, int]:
    start = int(datetime.datetime(date.year, date.month, date.day).timestamp())
    end = int(
        (datetime.datetime(date.year, date.month, date.day)
         + datetime.timedelta(days=1)).timestamp()
    )
    return start, end


def _row_to_alert(r: sqlite3.Row) -> dict:
    """Project a flow_alerts row into the dict shape _classify_whale_signature expects."""
    return {
        "ticker": r["ticker"],
        "notional": r["notional"] or r["sweep_notional"] or 0,
        "side": r["side"],
        "volume": r["volume"] or 0,
        "oi": r["oi"] or 0,
        "sentiment": r["sentiment"],
        "option_type": r["option_type"],
        "strike": r["strike"],
        "expiration": r["expiration"],
    }


def main() -> int:
    date = _parse_args()
    start, end = _ts_window(date)
    print("=" * 70)
    print(f"WHALE-RT BACKTEST — {date.isoformat()}")
    print("=" * 70)

    c = sqlite3.connect("./snapshots.db")
    c.row_factory = sqlite3.Row

    total = c.execute(
        "SELECT COUNT(*) AS n FROM flow_alerts WHERE ts >= ? AND ts < ?",
        (start, end),
    ).fetchone()["n"]
    print(f"Total flow_alerts on {date}: {total:,}")
    if total == 0:
        print("No data for that date. Try a session day.")
        return 1

    # Pull every alert and replay through the classifier. Streaming with a
    # cursor — 327K rows comfortably fits in memory but no need to materialise.
    rows = c.execute(
        """SELECT id, ts, ticker, strike, expiration, option_type, side,
                  sentiment, volume, oi, vol_oi, notional, sweep_notional,
                  conviction, is_whale, whale_reasons, last_price
           FROM flow_alerts
           WHERE ts >= ? AND ts < ?""",
        (start, end),
    )

    n_tagged = 0           # would-be is_whale=1 (DB tag, $1M floor)
    n_tg_fires = 0         # would-be Telegram dispatch ($3M floor)
    n_rt_dispatch = 0      # would-be real-time WHALE-RT dispatch
                           #   (subset of n_tg_fires: also requires vol>=500)

    by_ticker_tg: dict[str, int] = defaultdict(int)
    by_ticker_dollars: dict[str, float] = defaultdict(float)
    tg_fires: list[dict] = []

    # Per-ticker per-contract dedup to simulate the 10-min TTL in WHALE-RT.
    # (Approximation: collapse by contract key for the whole day. The real
    # dedup is 10-min sliding, but daily is a strict UPPER BOUND on "unique
    # contracts that would have fired" — close enough for backtest.)
    seen_contracts: set[tuple[str, float, str, str, str]] = set()

    # Realistic filters that the OPRA stream + WHALE-RT path enforces
    # but the chain-snapshot replay doesn't:
    #   1. Drop expired contracts. Chain snapshot keeps yesterday's expired
    #      contracts in the day's volume (e.g. NVDA 215P 6/3 showing $13M
    #      "buying" on 6/4 = accumulated 6/3 EOD volume re-snapshotted at
    #      9:30 today). OPRA stream only delivers today's actual trades.
    #   2. Drop opening-auction artifacts (first 60s after open). Whale
    #      classifier hits on the open-auction match prints which aren't
    #      WHALE-RT-eligible — those are settlement, not directional flow.
    #   3. Drop after-close prints (>= 16:05 ET). OPRA tape stops 16:00,
    #      anything later is settle/auction noise.
    n_dropped_expired = 0
    n_dropped_open_auction = 0
    n_dropped_after_close = 0
    open_auction_ts_end = start + (9 * 3600 + 31 * 60)   # 09:31:00 ET
    after_close_ts_start = start + (16 * 3600 + 5 * 60)  # 16:05:00 ET

    for r in rows:
        alert = _row_to_alert(r)
        is_whale, reasons = _classify_whale_signature(alert)
        if not is_whale:
            continue

        # Expired-contract filter
        try:
            exp_str = str(alert["expiration"])
            if "-" in exp_str:
                exp_date = datetime.date.fromisoformat(exp_str)
            else:
                exp_date = datetime.datetime.strptime(exp_str, "%Y%m%d").date()
            if exp_date < date:
                n_dropped_expired += 1
                continue
        except Exception:
            pass

        # Opening-auction filter
        if r["ts"] < open_auction_ts_end:
            n_dropped_open_auction += 1
            continue

        # After-close filter
        if r["ts"] >= after_close_ts_start:
            n_dropped_after_close += 1
            continue

        n_tagged += 1
        notional = float(alert["notional"] or 0)
        ticker = alert["ticker"]

        # Telegram tier ($3M)
        if notional >= WHALE_TELEGRAM_NOTIONAL:
            n_tg_fires += 1
            by_ticker_tg[ticker] += 1
            by_ticker_dollars[ticker] += notional

            # WHALE-RT path (real-time, additional vol>=500 gate)
            vol = int(alert["volume"] or 0)
            if vol >= 500:
                dedup_key = (
                    ticker, alert["strike"], alert["expiration"],
                    alert["option_type"], alert["sentiment"],
                )
                if dedup_key not in seen_contracts:
                    seen_contracts.add(dedup_key)
                    n_rt_dispatch += 1
                    tg_fires.append({
                        "ts": r["ts"],
                        "ticker": ticker,
                        "strike": alert["strike"],
                        "expiration": alert["expiration"],
                        "option_type": alert["option_type"],
                        "notional": notional,
                        "vol": vol,
                        "oi": alert["oi"],
                        "vol_oi": r["vol_oi"],
                        "reasons": ", ".join(reasons),
                    })

    print()
    print(f"DROPPED:")
    print(f"  Expired contracts (chain-snapshot artifact): {n_dropped_expired:,}")
    print(f"  Opening-auction (<9:31 ET):                  {n_dropped_open_auction:,}")
    print(f"  After-close (>=16:05 ET):                    {n_dropped_after_close:,}")
    print()
    print(f"WOULD HAVE FIRED (RTH-only, non-expired):")
    print(f"  is_whale=1 tagged (rows ≥ $1M):     {n_tagged:,}")
    print(f"  Telegram-tier ($3M floor):          {n_tg_fires:,}")
    print(f"  WHALE-RT realtime (post-dedup):     {n_rt_dispatch:,}")
    print()

    # Top 20 tickers by # of would-be Telegram fires
    print("=== TOP 20 BY TELEGRAM FIRES (pre-dedup) ===")
    top = sorted(by_ticker_tg.items(), key=lambda kv: -kv[1])[:20]
    for ticker, n in top:
        print(f"  {ticker:8s}  fires={n:4d}  total_notional=${by_ticker_dollars[ticker]/1e6:.1f}M")

    # Detailed log of would-be WHALE-RT dispatches (post-dedup, sorted by ts)
    print()
    print("=== ALL WHALE-RT REALTIME DISPATCHES (post-dedup) ===")
    print(f"{'Time':9s} {'Ticker':6s} {'Strike':8s} {'Exp':10s} {'Type':4s} {'$ Notional':>11s}  {'Vol':>6s}  {'OI':>6s} V/OI")
    print("-" * 95)
    tg_fires.sort(key=lambda d: d["ts"])
    for f in tg_fires:
        t = datetime.datetime.fromtimestamp(f["ts"]).strftime("%H:%M:%S")
        print(
            f"{t}  {f['ticker']:6s}  ${f['strike']:7g} {f['expiration']:10s} "
            f"{f['option_type'][0].upper():4s} ${f['notional']/1e6:>9.2f}M  "
            f"{f['vol']:>6d}  {f['oi']:>6d} "
            f"{f['vol_oi']!s:>4s}"
        )

    # Cross-check specific tickers from today's tweets
    print()
    print("=== CROSS-CHECK: tickers from today's tweets ===")
    for tkr in ["NVDA", "NEE", "CVS", "NBIS", "META", "MSTR", "SNDK", "COIN"]:
        n = by_ticker_tg.get(tkr, 0)
        notional = by_ticker_dollars.get(tkr, 0)
        flag = "✓" if n > 0 else "✗ MISS"
        print(f"  {flag} {tkr:6s}  Telegram-fires={n:3d}  total_$=${notional/1e6:.1f}M")

    return 0


if __name__ == "__main__":
    sys.exit(main())
