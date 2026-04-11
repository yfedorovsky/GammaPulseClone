"""Download historical options chain data from EODHD for local backtesting.

Usage:
    python -m backtest.download_eodhd --key YOUR_API_KEY --tickers SPY,QQQ,NVDA --days 730

Output:
    data/
      spots.csv              (date, ticker, open, high, low, close)
      SPY_chains.csv          (date, ticker, strike, expiration, option_type, oi, volume, gamma, delta, vega, iv, bid, ask, last)
      QQQ_chains.csv
      ...

Then run:
    python -m backtest.runner --data ./data --tickers SPY,QQQ,NVDA

EODHD API: https://eodhd.com/financial-apis/stock-options-data
Free demo key works for AAPL only. $29.99/mo for full access.
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


BASE_URL = "https://eodhd.com/api/options"
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


def fetch_options_eod(api_key: str, ticker: str, trade_date: str) -> list[dict]:
    """Fetch EOD options chain snapshot for a given date.

    EODHD returns all contracts for all expirations on that date.
    """
    url = f"{BASE_URL}/{ticker}.US"
    params = {
        "api_token": api_key,
        "from": trade_date,
        "to": trade_date,
        "fmt": "json",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 402:
            print(f"  [SKIP] {ticker} {trade_date} — API key doesn't cover this ticker (need paid plan)")
            return []
        if r.status_code != 200:
            print(f"  [WARN] {ticker} {trade_date} — HTTP {r.status_code}")
            return []
        data = r.json()
        if not data:
            return []

        contracts = []
        # EODHD returns {expirations: [{...options...}]}
        for exp_group in data if isinstance(data, list) else [data]:
            for exp_key, options in (exp_group.get("data") or {}).items():
                if not isinstance(options, dict):
                    continue
                for otype in ["calls", "puts"]:
                    for opt in options.get(otype, []):
                        greeks = opt.get("greeks") or {}
                        contracts.append({
                            "date": trade_date,
                            "ticker": ticker,
                            "strike": opt.get("strike", 0),
                            "expiration": opt.get("expirationDate", ""),
                            "option_type": "call" if otype == "calls" else "put",
                            "oi": opt.get("openInterest", 0),
                            "volume": opt.get("volume", 0),
                            "gamma": greeks.get("gamma", 0),
                            "delta": greeks.get("delta", 0),
                            "vega": greeks.get("vega", 0),
                            "iv": greeks.get("iv", 0) or opt.get("impliedVolatility", 0),
                            "bid": opt.get("bid", 0),
                            "ask": opt.get("ask", 0),
                            "last": opt.get("lastPrice", 0),
                        })
        return contracts
    except Exception as e:
        print(f"  [ERR] {ticker} {trade_date}: {e}")
        return []


def fetch_spot_history(api_key: str, ticker: str, start: str, end: str) -> list[dict]:
    """Fetch daily OHLCV bars."""
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
            print(f"  [WARN] spots {ticker} — HTTP {r.status_code}")
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
            for bar in data
            if bar.get("date")
        ]
    except Exception as e:
        print(f"  [ERR] spots {ticker}: {e}")
        return []


def get_trading_days(start: date, end: date, sample_every: int = 1) -> list[date]:
    """Generate weekday dates between start and end.

    sample_every: 1 = every day, 5 = weekly (every Monday), etc.
    Useful for reducing API calls during initial testing.
    """
    days = []
    d = start
    count = 0
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
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
    delay: float = 0.35,
):
    """Download all data and write CSVs.

    Args:
        api_key: EODHD API key
        tickers: list of ticker symbols
        start_date, end_date: "YYYY-MM-DD"
        output_dir: where to write CSVs
        sample_every: 1 = every trading day, 5 = weekly samples (reduces API calls 5x)
        delay: seconds between API calls (EODHD rate limit: ~5/sec on paid plan)
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    trading_days = get_trading_days(start, end, sample_every)

    total_days = len(trading_days)
    total_calls = total_days * len(tickers) + len(tickers)  # chains + spots
    print(f"Plan: {len(tickers)} tickers x {total_days} days = {total_days * len(tickers)} chain calls + {len(tickers)} spot calls")
    print(f"Estimated time: {total_calls * delay / 60:.0f} minutes at {delay}s delay")
    print(f"Output: {out.resolve()}")
    print()

    # 1. Download spot prices (one call per ticker, covers full range)
    print("=== Downloading spot prices ===")
    spots_path = out / "spots.csv"
    with open(spots_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SPOT_HEADERS)
        writer.writeheader()
        for ticker in tickers:
            print(f"  {ticker}...", end=" ")
            bars = fetch_spot_history(api_key, ticker, start_date, end_date)
            for bar in bars:
                writer.writerow(bar)
            print(f"{len(bars)} bars")
            time.sleep(delay)
    print(f"Spots saved: {spots_path}\n")

    # 2. Download options chains (one call per ticker per day)
    print("=== Downloading options chains ===")
    for ticker in tickers:
        chain_path = out / f"{ticker}_chains.csv"
        print(f"\n--- {ticker} ({total_days} days) ---")

        with open(chain_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CHAIN_HEADERS)
            writer.writeheader()

            for i, day in enumerate(trading_days):
                day_str = day.isoformat()
                contracts = fetch_options_eod(api_key, ticker, day_str)

                for c in contracts:
                    writer.writerow(c)

                if (i + 1) % 20 == 0 or i == 0:
                    print(f"  {day_str} — {len(contracts)} contracts  ({i+1}/{total_days})")

                time.sleep(delay)

        print(f"  Saved: {chain_path}")

    print(f"\n{'='*50}")
    print(f"Download complete!")
    print(f"Data directory: {out.resolve()}")
    print(f"\nRun backtest:")
    print(f"  python -m backtest.runner --data {output_dir} --tickers {','.join(tickers)} --start {start_date} --end {end_date}")


def main():
    parser = argparse.ArgumentParser(description="Download EODHD options data for backtesting")
    parser.add_argument("--key", required=True, help="EODHD API key")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    parser.add_argument("--start", default="2024-04-01", help="Start date")
    parser.add_argument("--end", default="2026-04-01", help="End date")
    parser.add_argument("--output", default="./data", help="Output directory")
    parser.add_argument("--sample", type=int, default=1, help="Sample every N trading days (1=daily, 5=weekly)")
    parser.add_argument("--delay", type=float, default=0.35, help="Seconds between API calls")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    download(args.key, tickers, args.start, args.end, args.output, args.sample, args.delay)


if __name__ == "__main__":
    main()
