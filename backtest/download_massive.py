"""Download intraday bars from Massive (formerly Polygon.io).

Gets 15-min, 5-min, or 1-min bars for backtesting Mir's intraday rules
(15-min 20 SMA pullback, power hour entries, first hour avoidance).

Usage:
    # 15-min bars, last 60 days (free Yahoo limit)
    python -m backtest.download_massive --tickers MU,LRCX,AMAT,SMH --interval 15 --days 60

    # 5-min bars, 6 months
    python -m backtest.download_massive --tickers SPY,QQQ --interval 5 --days 180

    # 1-min bars, 30 days
    python -m backtest.download_massive --tickers MU --interval 1 --days 30

API: https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}
Massive Starter ($29/mo): 2 years history, no rate limit issues.

Output: data/intraday/{TICKER}_{interval}min.csv
Columns: datetime, ticker, open, high, low, close, volume, vwap
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)


BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

DEFAULT_TICKERS = [
    "MU", "LRCX", "AMAT", "SMH", "LITE", "COHR", "AAOI",
    "SPY", "QQQ", "NVDA", "TSLA", "AMD", "AVGO",
]

INTRADAY_HEADERS = [
    "datetime", "ticker", "open", "high", "low", "close", "volume", "vwap",
]


def fetch_bars(
    api_key: str,
    ticker: str,
    multiplier: int,
    timespan: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch aggregate bars from Polygon/Massive API.

    Args:
        multiplier: bar size (e.g. 15 for 15-min)
        timespan: 'minute', 'hour', 'day'
    """
    url = f"{BASE_URL}/{ticker}/range/{multiplier}/{timespan}/{start_date}/{end_date}"
    all_bars = []
    params = {
        "apiKey": api_key,
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            print(f"    [RATE LIMIT] waiting 60s...")
            time.sleep(60)
            r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"    [WARN] {ticker} HTTP {r.status_code}")
            return []

        data = r.json()
        results = data.get("results", [])

        for bar in results:
            # Convert epoch ms to datetime string
            ts_ms = bar.get("t", 0)
            from datetime import datetime
            dt = datetime.fromtimestamp(ts_ms / 1000)

            all_bars.append({
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": ticker,
                "open": bar.get("o", 0),
                "high": bar.get("h", 0),
                "low": bar.get("l", 0),
                "close": bar.get("c", 0),
                "volume": bar.get("v", 0),
                "vwap": bar.get("vw", 0),
            })

        # Handle pagination
        next_url = data.get("next_url")
        while next_url:
            r = requests.get(next_url, params={"apiKey": api_key}, timeout=30)
            if r.status_code != 200:
                break
            data = r.json()
            for bar in data.get("results", []):
                ts_ms = bar.get("t", 0)
                dt = datetime.fromtimestamp(ts_ms / 1000)
                all_bars.append({
                    "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ticker": ticker,
                    "open": bar.get("o", 0),
                    "high": bar.get("h", 0),
                    "low": bar.get("l", 0),
                    "close": bar.get("c", 0),
                    "volume": bar.get("v", 0),
                    "vwap": bar.get("vw", 0),
                })
            next_url = data.get("next_url")
            time.sleep(0.2)

    except Exception as e:
        print(f"    [ERR] {ticker}: {e}")

    return all_bars


def download_intraday(
    api_key: str,
    tickers: list[str],
    interval_min: int = 15,
    days_back: int = 60,
    output_dir: str = "./data/intraday",
    delay: float = 0.3,
):
    """Download intraday bars for all tickers."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    end = date.today()
    start = end - timedelta(days=days_back)

    # Polygon free tier: max 2 years. Paid: unlimited.
    # But intraday data is typically available for ~2 years max.
    # Split into 30-day chunks to avoid hitting response limits.
    chunk_days = 30

    print(f"Downloading {interval_min}-min bars for {len(tickers)} tickers")
    print(f"Period: {start} -> {end} ({days_back} days)")
    print(f"Output: {out.resolve()}")
    print()

    for ticker in tickers:
        filepath = out / f"{ticker}_{interval_min}min.csv"
        print(f"--- {ticker} ---")

        all_bars = []
        chunk_start = start

        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), end)
            print(f"  {chunk_start} -> {chunk_end}...", end=" ", flush=True)

            bars = fetch_bars(
                api_key, ticker,
                multiplier=interval_min,
                timespan="minute",
                start_date=chunk_start.isoformat(),
                end_date=chunk_end.isoformat(),
            )
            all_bars.extend(bars)
            print(f"{len(bars)} bars")

            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(delay)

        # Write CSV
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=INTRADAY_HEADERS)
            writer.writeheader()
            for bar in all_bars:
                writer.writerow(bar)

        print(f"  Total: {len(all_bars)} bars saved to {filepath}")
        print()

    print(f"{'='*50}")
    print(f"Download complete! Files in {out.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Download intraday bars from Massive/Polygon")
    parser.add_argument("--key", default="", help="Massive/Polygon API key (or MASSIVE_API_KEY in .env)")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    parser.add_argument("--interval", type=int, default=15, help="Bar interval in minutes (1, 5, 15)")
    parser.add_argument("--days", type=int, default=60, help="Days of history to download")
    parser.add_argument("--output", default="./data/intraday", help="Output directory")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between API calls")
    args = parser.parse_args()

    api_key = args.key
    if not api_key:
        try:
            env = open(".env").read()
            for line in env.split("\n"):
                if line.startswith("MASSIVE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        except FileNotFoundError:
            pass

    if not api_key:
        print("ERROR: No API key. Use --key or set MASSIVE_API_KEY in .env")
        sys.exit(1)

    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    # Quick test
    print("Testing API access...", flush=True)
    test = fetch_bars(api_key, "SPY", args.interval, "minute",
                      (date.today() - timedelta(days=5)).isoformat(),
                      date.today().isoformat())
    if test:
        print(f"  OK - got {len(test)} SPY bars\n")
    else:
        print("  WARNING: No data returned. Check API key and subscription.")
        resp = input("  Continue anyway? (y/n): ")
        if resp.lower() != "y":
            sys.exit(1)

    download_intraday(api_key, tickers, args.interval, args.days, args.output, args.delay)


if __name__ == "__main__":
    main()
