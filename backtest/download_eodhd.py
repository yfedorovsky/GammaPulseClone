"""Download historical options chain data from EODHD Marketplace API.

API: https://eodhd.com/api/mp/unicornbay/options/eod
Requires: All-In-One plan ($99.99/mo) or Marketplace Options subscription.

Usage:
    # Add to .env: EODHD_API_KEY=your_key
    python -m backtest.download_eodhd --start 2024-04-01 --end 2026-04-11

Output: data/ directory with CSVs ready for backtest.runner
"""
from __future__ import annotations

import argparse
import csv
import json
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

# EODHD Marketplace endpoints
CONTRACTS_URL = "https://eodhd.com/api/mp/unicornbay/options/contracts"
EOD_URL = "https://eodhd.com/api/mp/unicornbay/options/eod"
SPOT_URL = "https://eodhd.com/api/eod"

DEFAULT_TICKERS = [
    "SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL",
    "AMD", "AVGO", "CRM", "NFLX", "COIN", "PLTR", "UBER", "SQ", "SHOP",
    "BA", "JPM",
]

CHAIN_HEADERS = [
    "date", "ticker", "strike", "expiration", "option_type", "oi", "volume",
    "gamma", "delta", "vega", "iv", "bid", "ask", "last",
]
SPOT_HEADERS = ["date", "ticker", "open", "high", "low", "close"]


def fetch_eod_options(api_key: str, ticker: str, trade_date: str) -> list[dict]:
    """Fetch EOD options data for a ticker on a specific date using the Marketplace API.

    Uses filter[tradetime_eq] to get the snapshot for that exact date.
    Paginates through all results (max 1000 per page, up to 10000 offset).
    """
    all_records = []
    offset = 0
    limit = 1000

    while True:
        params = {
            "api_token": api_key,
            "filter[underlying_symbol]": ticker,
            "filter[tradetime_eq]": trade_date,
            "page[offset]": offset,
            "page[limit]": limit,
            "sort": "strike",
        }

        try:
            r = requests.get(EOD_URL, params=params, timeout=30)

            if r.status_code == 404:
                return []  # No data for this date
            if r.status_code == 429:
                print(f"    [RATE LIMIT] waiting 60s...")
                time.sleep(60)
                continue
            if r.status_code != 200:
                print(f"    [WARN] {ticker} {trade_date} HTTP {r.status_code}")
                return all_records

            data = r.json()
            records = data.get("data", [])

            for rec in records:
                attrs = rec.get("attributes", {})
                all_records.append({
                    "date": trade_date,
                    "ticker": ticker,
                    "strike": attrs.get("strike", 0),
                    "expiration": attrs.get("exp_date", ""),
                    "option_type": attrs.get("type", ""),
                    "oi": attrs.get("open_interest", 0) or 0,
                    "volume": attrs.get("volume", 0) or 0,
                    "gamma": attrs.get("gamma", 0) or 0,
                    "delta": attrs.get("delta", 0) or 0,
                    "vega": attrs.get("vega", 0) or 0,
                    "iv": attrs.get("volatility", 0) or 0,
                    "bid": attrs.get("bid", 0) or 0,
                    "ask": attrs.get("ask", 0) or 0,
                    "last": attrs.get("last", 0) or 0,
                })

            # Check if there are more pages
            meta = data.get("meta", {})
            total = meta.get("total", 0)
            offset += limit

            if offset >= total or offset >= 10000 or not records:
                break

        except Exception as e:
            print(f"    [ERR] {ticker} {trade_date}: {e}")
            break

    return all_records


def fetch_spot_history(api_key: str, ticker: str, start: str, end: str) -> list[dict]:
    """Fetch daily OHLCV bars from EODHD standard API."""
    url = f"{SPOT_URL}/{ticker}.US"
    params = {
        "api_token": api_key,
        "from": start,
        "to": end,
        "period": "d",
        "fmt": "json",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"  [WARN] spots {ticker} HTTP {r.status_code}")
            return []
        data = r.json()
        return [
            {
                "date": bar.get("date", ""),
                "ticker": ticker,
                "open": bar.get("open", 0),
                "high": bar.get("high", 0),
                "low": bar.get("low", 0),
                "close": bar.get("close") or bar.get("adjusted_close", 0),
            }
            for bar in data if bar.get("date")
        ]
    except Exception as e:
        print(f"  [ERR] spots {ticker}: {e}")
        return []


def get_trading_days(start: date, end: date, sample_every: int = 1) -> list[date]:
    """Generate weekday dates. sample_every=5 means weekly (every 5th trading day)."""
    days = []
    d = start
    count = 0
    while d <= end:
        if d.weekday() < 5:
            count += 1
            if count % sample_every == 0:
                days.append(d)
        d += timedelta(days=1)
    return days


def download(
    api_key: str,
    tickers: list[str],
    start_date: str,
    end_date: str,
    output_dir: str = "./data",
    sample_every: int = 1,
    delay: float = 0.2,
    append: bool = False,
):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    trading_days = get_trading_days(start, end, sample_every)
    total_days = len(trading_days)

    # Each EOD call counts as 10 API calls on the marketplace
    est_calls = total_days * len(tickers) * 2  # ~2 pages avg per ticker per day
    print(f"Plan: {len(tickers)} tickers x {total_days} days")
    print(f"Estimated API calls: ~{est_calls * 10:,} (each request = 10 calls)")
    print(f"Estimated time: {total_days * len(tickers) * delay / 60:.0f} min")
    print(f"Output: {out.resolve()}")
    print()

    # 1. Spot prices
    # In append mode, skip spots (use Yahoo Finance separately to avoid overwrites)
    if append:
        print("=== APPEND MODE: skipping spots (use Yahoo Finance to rebuild) ===\n")
    else:
        print("=== Downloading spot prices ===")
        spots_path = out / "spots.csv"
        with open(spots_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SPOT_HEADERS)
            writer.writeheader()
            for ticker in tickers:
                print(f"  {ticker}...", end=" ", flush=True)
                bars = fetch_spot_history(api_key, ticker, start_date, end_date)
                for bar in bars:
                    writer.writerow(bar)
                print(f"{len(bars)} bars")
                time.sleep(delay)
        print(f"Spots saved: {spots_path}\n")

    # 2. Options chains
    print("=== Downloading options chains ===")
    total_contracts = 0
    for ticker in tickers:
        chain_path = out / f"{ticker}_chains.csv"
        file_mode = "a" if append and chain_path.exists() else "w"
        print(f"\n--- {ticker} ({total_days} days) {'[APPEND]' if file_mode == 'a' else '[NEW]'} ---")

        with open(chain_path, file_mode, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CHAIN_HEADERS)
            if file_mode == "w":
                writer.writeheader()
            ticker_contracts = 0

            for i, day in enumerate(trading_days):
                day_str = day.isoformat()
                contracts = fetch_eod_options(api_key, ticker, day_str)

                for c in contracts:
                    writer.writerow(c)

                ticker_contracts += len(contracts)

                if (i + 1) % 20 == 0 or i == 0 or len(contracts) > 0:
                    print(f"  {day_str} - {len(contracts)} contracts  ({i+1}/{total_days})", flush=True)

                time.sleep(delay)

        total_contracts += ticker_contracts
        print(f"  Total: {ticker_contracts:,} contracts saved")

    print(f"\n{'='*50}")
    print(f"Download complete!")
    print(f"Total contracts: {total_contracts:,}")
    print(f"Data: {out.resolve()}")
    print(f"\nRun backtest:")
    print(f"  python -m backtest.runner --data {output_dir} --tickers {','.join(tickers)} --start {start_date} --end {end_date}")


def main():
    parser = argparse.ArgumentParser(description="Download EODHD options data for backtesting")
    parser.add_argument("--key", default="", help="EODHD API key (or set EODHD_API_KEY in .env)")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    parser.add_argument("--start", default="2024-04-01", help="Start date")
    parser.add_argument("--end", default="2026-04-11", help="End date")
    parser.add_argument("--output", default="./data", help="Output directory")
    parser.add_argument("--sample", type=int, default=1, help="Sample every N trading days (1=daily, 5=weekly)")
    parser.add_argument("--delay", type=float, default=0.2, help="Seconds between API calls")
    parser.add_argument("--append", action="store_true", help="Append to existing chain files instead of overwriting. Skips spots download.")
    args = parser.parse_args()

    api_key = args.key
    if not api_key:
        # Try .env
        try:
            env = open(".env").read()
            for line in env.split("\n"):
                if line.startswith("EODHD_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        except FileNotFoundError:
            pass

    if not api_key:
        print("ERROR: No API key. Use --key YOUR_KEY or set EODHD_API_KEY in .env")
        sys.exit(1)

    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    # Quick test first
    print("Testing API access...", flush=True)
    test = fetch_eod_options(api_key, "AAPL", "2026-04-10")
    if test:
        print(f"  OK - got {len(test)} AAPL contracts for 2026-04-10\n")
    else:
        print("  WARNING: No data returned for AAPL test. Check your API key and subscription.")
        resp = input("  Continue anyway? (y/n): ")
        if resp.lower() != "y":
            sys.exit(1)

    download(api_key, tickers, args.start, args.end, args.output, args.sample, args.delay, args.append)


if __name__ == "__main__":
    main()
