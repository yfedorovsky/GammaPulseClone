"""Daily chain snapshot collector — runs at market close, saves to CSV.

Uses your existing Tradier production key (free). Accumulates daily
options chain snapshots for backtesting. After 30-60 days you'll have
enough data for meaningful signal validation.

Usage:
    # One-time run (call at/after 4:15 PM ET):
    python -m backtest.collect_daily

    # Or schedule via Windows Task Scheduler / cron:
    # Run daily at 4:20 PM ET

Data saved to: data/daily/{YYYY-MM-DD}/
    spots.csv       (all tickers, OHLCV from Tradier)
    {TICKER}.csv    (full chain with greeks for each ticker)
    summary.json    (GEX levels computed for each ticker)
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Add parent to path so we can import server modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.config import get_settings
from server.tradier import TradierClient
from backtest.gex_engine import compute_levels
from backtest.soe_scorer import determine_direction, score_signal, score_to_grade

TICKERS = [
    "SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL",
    "AMD", "AVGO", "CRM", "NFLX", "COIN", "PLTR", "UBER", "SQ", "SHOP",
    "BA", "JPM",
]

CHAIN_HEADERS = [
    "date", "ticker", "strike", "expiration", "option_type", "oi", "volume",
    "gamma", "delta", "vega", "iv", "bid", "ask", "last",
]


async def collect(tickers: list[str] | None = None, output_dir: str = "./data/daily"):
    """Collect today's chain snapshots for all tickers."""
    tickers = tickers or TICKERS
    today = date.today().isoformat()
    out = Path(output_dir) / today
    out.mkdir(parents=True, exist_ok=True)

    print(f"Collecting {len(tickers)} tickers for {today}")
    print(f"Output: {out.resolve()}")

    client = TradierClient()
    try:
        # 1. Fetch spot prices with OHLCV (not just close)
        # Uses Tradier /markets/history for real open/high/low/close
        print("\nFetching OHLCV bars...")
        spots = {}
        spots_path = out / "spots.csv"
        with open(spots_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "open", "high", "low", "close"])
            for ticker in tickers:
                try:
                    bars = await client.history(ticker, interval="daily", start=today, end=today)
                    if bars:
                        bar = bars[-1]  # today's bar
                        spots[ticker] = bar.get("close", 0)
                        w.writerow([today, ticker, bar.get("open", 0), bar.get("high", 0), bar.get("low", 0), bar.get("close", 0)])
                    else:
                        # Fallback to quote if history not available yet
                        q = await client.quotes([ticker])
                        price = q.get(ticker, 0)
                        if price:
                            spots[ticker] = price
                            w.writerow([today, ticker, price, price, price, price])
                except Exception as e:
                    print(f"  [WARN] {ticker} OHLCV: {e}")
                    # Fallback
                    q = await client.quotes([ticker])
                    price = q.get(ticker, 0)
                    if price:
                        spots[ticker] = price
                        w.writerow([today, ticker, price, price, price, price])
        print(f"  {len(spots)} tickers with OHLCV")

        # 2. Fetch chains for each ticker
        summary = {}
        for ticker in tickers:
            print(f"\n--- {ticker} ---")
            spot = spots.get(ticker, 0)
            if not spot:
                print(f"  [SKIP] no spot price")
                continue

            # Get expirations
            exps = await client.expirations(ticker)
            if not exps:
                print(f"  [SKIP] no expirations")
                continue

            # Fetch first 4 expirations (enough for GEX)
            all_contracts = []
            for exp in exps[:4]:
                chain = await client.chain(ticker, exp)
                if chain:
                    all_contracts.extend(chain)

            if not all_contracts:
                print(f"  [SKIP] no contracts")
                continue

            # Save raw chain
            chain_path = out / f"{ticker}.csv"
            with open(chain_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CHAIN_HEADERS)
                w.writeheader()
                for opt in all_contracts:
                    greeks = opt.get("greeks") or {}
                    w.writerow({
                        "date": today,
                        "ticker": ticker,
                        "strike": opt.get("strike", 0),
                        "expiration": opt.get("expiration_date", ""),
                        "option_type": (opt.get("option_type") or "").lower(),
                        "oi": opt.get("open_interest", 0),
                        "volume": opt.get("volume", 0),
                        "gamma": greeks.get("gamma", 0),
                        "delta": greeks.get("delta", 0),
                        "vega": greeks.get("vega", 0),
                        "iv": greeks.get("mid_iv") or greeks.get("smv_vol", 0),
                        "bid": opt.get("bid", 0),
                        "ask": opt.get("ask", 0),
                        "last": opt.get("last", 0),
                    })

            # Compute GEX levels
            backtest_contracts = []
            for opt in all_contracts:
                greeks = opt.get("greeks") or {}
                backtest_contracts.append({
                    "strike": opt.get("strike", 0),
                    "oi": opt.get("open_interest", 0),
                    "gamma": greeks.get("gamma", 0),
                    "delta": greeks.get("delta", 0),
                    "vega": greeks.get("vega", 0),
                    "iv": greeks.get("mid_iv") or greeks.get("smv_vol", 0),
                    "option_type": (opt.get("option_type") or "").lower(),
                })

            state = compute_levels(backtest_contracts, spot)
            if state:
                state["spot"] = spot
                direction = determine_direction(state)
                if direction:
                    score, grade, reasons = score_signal(state, direction)
                else:
                    score, grade, reasons = 0, "C", []

                summary[ticker] = {
                    "spot": spot,
                    "king": state.get("king", 0),
                    "floor": state.get("floor", 0),
                    "ceiling": state.get("ceiling", 0),
                    "zgl": state.get("zgl", 0),
                    "signal": state.get("signal", ""),
                    "regime": state.get("regime", ""),
                    "iv": round(state.get("iv", 0) * 100, 1),
                    "direction": direction,
                    "soe_score": score,
                    "grade": grade,
                    "contracts": len(all_contracts),
                    "expirations": len(exps[:4]),
                }

                print(f"  ${spot:.2f} | King ${state['king']} | {state['signal']} | {state['regime']} gamma | SOE {score}/8 = {grade} | {len(all_contracts)} contracts")

        # 3. Save summary
        summary_path = out / "summary.json"
        with open(summary_path, "w") as f:
            json.dump({"date": today, "tickers": summary}, f, indent=2)
        print(f"\n{'='*50}")
        print(f"Saved {len(summary)} tickers to {out.resolve()}")
        print(f"Summary: {summary_path}")

    finally:
        await client.close()

    # Also append to the merged CSV for the backtest runner
    merged_dir = Path(output_dir).parent
    _append_to_merged(out, merged_dir, today)


def _append_to_merged(day_dir: Path, merged_dir: Path, today: str):
    """Append today's data to the merged CSVs used by the backtest runner."""
    merged_dir.mkdir(parents=True, exist_ok=True)

    # Append spots
    spots_merged = merged_dir / "spots.csv"
    write_header = not spots_merged.exists()
    spots_day = day_dir / "spots.csv"
    if spots_day.exists():
        with open(spots_day) as src, open(spots_merged, "a", newline="") as dst:
            reader = csv.DictReader(src)
            writer = csv.DictWriter(dst, fieldnames=["date", "ticker", "open", "high", "low", "close"])
            if write_header:
                writer.writeheader()
            for row in reader:
                writer.writerow({
                    "date": row["date"], "ticker": row["ticker"],
                    "open": row.get("open", 0), "high": row.get("high", 0),
                    "low": row.get("low", 0), "close": row.get("close", 0),
                })

    # Append chains per ticker
    for chain_file in day_dir.glob("*.csv"):
        if chain_file.name == "spots.csv":
            continue
        ticker = chain_file.stem
        merged_chain = merged_dir / f"{ticker}_chains.csv"
        write_header = not merged_chain.exists()
        with open(chain_file) as src, open(merged_chain, "a", newline="") as dst:
            reader = csv.DictReader(src)
            writer = csv.DictWriter(dst, fieldnames=CHAIN_HEADERS)
            if write_header:
                writer.writeheader()
            for row in reader:
                writer.writerow(row)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Collect daily chain snapshots from Tradier")
    parser.add_argument("--tickers", default=",".join(TICKERS), help="Comma-separated tickers")
    parser.add_argument("--output", default="./data/daily", help="Output directory")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    asyncio.run(collect(tickers, args.output))


if __name__ == "__main__":
    main()
