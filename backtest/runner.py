"""Local backtest runner — reads CSV/parquet data, runs through the engine.

Usage:
    python -m backtest.runner --data ./data --tickers SPY,QQQ,NVDA --start 2024-04-01 --end 2026-04-01

Data format (CSV):
    One file per ticker: {ticker}_chains.csv
    Columns: date, strike, expiration, option_type, oi, volume, gamma, delta, vega, iv, bid, ask, last

    Plus spot prices: spots.csv
    Columns: date, ticker, open, high, low, close

    Or: a single merged file with all data.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from .simulator import BacktestEngine
from .results import compute_stats, print_report


DEFAULT_TICKERS = [
    "SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL",
    "AMD", "AVGO", "CRM", "NFLX", "COIN", "PLTR", "UBER", "SQ", "SHOP",
    "BA", "JPM",
]


def load_chain_csv(path: str | Path) -> dict[str, dict[str, list[dict]]]:
    """Load option chain data from CSV.

    Returns: {date_str: {ticker: [contracts]}}
    """
    data: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get("date", "")
            ticker = row.get("ticker", "").upper()
            if not date or not ticker:
                continue
            data[date][ticker].append({
                "strike": float(row.get("strike", 0)),
                "oi": float(row.get("oi") or row.get("open_interest", 0)),
                "gamma": float(row.get("gamma", 0)),
                "delta": float(row.get("delta", 0)),
                "vega": float(row.get("vega", 0)),
                "iv": float(row.get("iv") or row.get("mid_iv", 0)),
                "option_type": row.get("option_type", "").lower(),
                "volume": float(row.get("volume", 0)),
                "bid": float(row.get("bid", 0)),
                "ask": float(row.get("ask", 0)),
                "last": float(row.get("last", 0)),
                "expiration": row.get("expiration", ""),
            })

    return dict(data)


def load_spots_csv(path: str | Path) -> dict[str, dict[str, dict[str, float]]]:
    """Load spot prices from CSV.

    Returns: {date_str: {ticker: {open, high, low, close}}}
    """
    data: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get("date", "")
            ticker = row.get("ticker", "").upper()
            if not date or not ticker:
                continue
            data[date][ticker] = {
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
            }

    return dict(data)


def load_per_ticker_csvs(data_dir: str | Path) -> tuple[dict, dict]:
    """Load data from per-ticker CSV files.

    Expects: {data_dir}/{TICKER}_chains.csv and {data_dir}/spots.csv
    """
    data_dir = Path(data_dir)
    all_chains: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    spots = {}

    spots_path = data_dir / "spots.csv"
    if spots_path.exists():
        spots = load_spots_csv(spots_path)

    for f in data_dir.glob("*_chains.csv"):
        ticker = f.stem.replace("_chains", "").upper()
        chain_data = load_chain_csv(f)
        for date, ticker_chains in chain_data.items():
            for t, contracts in ticker_chains.items():
                all_chains[date][t].extend(contracts)

    return dict(all_chains), spots


def run_backtest(
    chains: dict[str, dict[str, list[dict]]],
    spots: dict[str, dict[str, dict[str, float]]],
    tickers: list[str],
    start_date: str = "2024-04-01",
    end_date: str = "2026-04-01",
    account_value: float = 100_000,
) -> dict[str, Any]:
    """Run the full backtest.

    Args:
        chains: {date_str: {ticker: [contracts]}}
        spots: {date_str: {ticker: {open, high, low, close}}}
        tickers: list of ticker symbols to process
        start_date, end_date: ISO date strings
    """
    engine = BacktestEngine(account_value=account_value)
    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)

    # Get sorted trading dates
    all_dates = sorted(set(chains.keys()) | set(spots.keys()))
    trading_dates = [
        d for d in all_dates
        if start <= datetime.date.fromisoformat(d) <= end
    ]

    print(f"Backtest: {len(tickers)} tickers, {len(trading_dates)} trading days")
    print(f"Period: {start_date} → {end_date}")
    print(f"Account: ${account_value:,.0f}")
    print()

    tickers_set = set(t.upper() for t in tickers)
    processed = 0

    for date_str in trading_dates:
        date = datetime.date.fromisoformat(date_str)

        # Skip weekends
        if date.weekday() >= 5:
            continue

        day_chains = chains.get(date_str, {})
        day_spots = spots.get(date_str, {})

        # Set confluence from SPY/QQQ/IWM
        from .gex_engine import compute_levels
        confl = {}
        for idx_ticker in ["SPY", "QQQ", "IWM"]:
            if idx_ticker in day_chains and idx_ticker in day_spots:
                spot = day_spots[idx_ticker]["close"]
                state = compute_levels(day_chains[idx_ticker], spot)
                confl[idx_ticker] = state
        if confl:
            engine.set_confluence(
                confl.get("SPY", {}),
                confl.get("QQQ", {}),
                confl.get("IWM", {}),
            )

        # Process each ticker
        for ticker in tickers_set:
            if ticker not in day_chains:
                continue
            spot_data = day_spots.get(ticker, {})
            spot = spot_data.get("close", 0)
            if not spot:
                continue

            # Get available expirations
            exps = sorted(set(
                c.get("expiration", "") for c in day_chains[ticker] if c.get("expiration")
            ))

            signals = engine.process_day(
                date=date,
                ticker=ticker,
                chain_contracts=day_chains[ticker],
                spot=spot,
                daily_high=spot_data.get("high"),
                daily_low=spot_data.get("low"),
                available_expirations=exps,
            )

            processed += 1
            if processed % 500 == 0:
                print(f"  Processed {processed} ticker-days... ({date_str})")

    # Force close remaining positions
    last_spots = {}
    if trading_dates:
        last_day = spots.get(trading_dates[-1], {})
        last_spots = {t: d["close"] for t, d in last_day.items()}
    engine.force_close_all(
        datetime.date.fromisoformat(trading_dates[-1]) if trading_dates else datetime.date.today(),
        last_spots,
    )

    results = engine.get_results()
    print(f"\nProcessed {processed} ticker-days total")
    return results


def main():
    parser = argparse.ArgumentParser(description="GammaPulse SOE Backtest")
    parser.add_argument("--data", required=True, help="Path to data directory or merged CSV")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    parser.add_argument("--start", default="2024-04-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-04-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--account", type=float, default=100_000, help="Starting account value")
    parser.add_argument("--output", default="backtest_results.json", help="Output JSON file")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    data_path = Path(args.data)

    # Load data
    if data_path.is_dir():
        print(f"Loading per-ticker CSVs from {data_path}...")
        chains, spots = load_per_ticker_csvs(data_path)
    elif data_path.suffix == ".csv":
        print(f"Loading merged CSV from {data_path}...")
        chains = load_chain_csv(data_path)
        spots_path = data_path.parent / "spots.csv"
        spots = load_spots_csv(spots_path) if spots_path.exists() else {}
    else:
        print(f"Error: {data_path} is not a directory or CSV file")
        sys.exit(1)

    print(f"Loaded {len(chains)} dates with chain data")
    print(f"Loaded {len(spots)} dates with spot data")

    # Run
    results = run_backtest(chains, spots, tickers, args.start, args.end, args.account)

    # Stats
    stats = compute_stats(results)
    print_report(stats)

    # Save
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        # Convert non-serializable types
        def serialize(obj):
            if isinstance(obj, datetime.date):
                return obj.isoformat()
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)
        json.dump(stats, f, indent=2, default=serialize)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
