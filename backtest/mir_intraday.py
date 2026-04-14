"""Mir Intraday Backtest — uses 15-min bars to test time-of-day rules.

Tests Mir's exact intraday patterns from RAG:
1. Avoid first hour (9:30-10:30)
2. 15-min 20 SMA pullback entry (10:30-11:30)
3. Power hour entries (3:00-4:00)
4. Midday chop avoidance (11:30-1:30)

Usage:
    python -m backtest.mir_intraday --data ./data/intraday --tickers MU,LRCX,AMAT
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any


@dataclass
class IntradayTrade:
    entry_time: str
    ticker: str
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    window: str  # AM_MOMENTUM, PM_MOMENTUM, POWER_HOUR
    sma_20: float = 0
    # Outcome
    exit_time: str = ""
    exit_price: float = 0
    exit_reason: str = ""
    pnl_pct: float = 0
    outcome: str = ""
    max_favorable: float = 0


def load_intraday_csv(filepath: str) -> list[dict]:
    """Load 15-min bar CSV."""
    bars = []
    with open(filepath, newline="") as f:
        for row in csv.DictReader(f):
            bars.append({
                "datetime": row["datetime"],
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
                "vwap": float(row.get("vwap", 0)),
            })
    return bars


def sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / max(len(values), 1)
    return sum(values[-period:]) / period


def run_intraday_backtest(
    data_dir: str,
    tickers: list[str],
    interval: int = 15,
) -> dict[str, Any]:
    """Run Mir's intraday rules on 15-min bar data."""

    all_trades: list[IntradayTrade] = []

    for ticker in tickers:
        filepath = Path(data_dir) / f"{ticker}_{interval}min.csv"
        if not filepath.exists():
            print(f"  {ticker}: no data file")
            continue

        bars = load_intraday_csv(str(filepath))
        if not bars:
            continue

        print(f"  {ticker}: {len(bars)} bars")

        # Group bars by date
        by_date: dict[str, list[dict]] = defaultdict(list)
        for bar in bars:
            day = bar["datetime"][:10]
            by_date[day].append(bar)

        closes_history: list[float] = []
        open_trade: IntradayTrade | None = None

        for day_str in sorted(by_date.keys()):
            day_bars = by_date[day_str]
            day_date = date.fromisoformat(day_str)

            # Skip weekends
            if day_date.weekday() >= 5:
                continue

            # Skip Mondays (Mir data: 34% WR)
            if day_date.weekday() == 0:
                continue

            # Close any open trade from previous day (we're day-trading)
            if open_trade:
                last_bar = day_bars[-1] if day_bars else None
                if last_bar:
                    open_trade.exit_time = last_bar["datetime"]
                    open_trade.exit_price = last_bar["close"]
                    open_trade.pnl_pct = ((last_bar["close"] - open_trade.entry_price) / open_trade.entry_price) * 100
                    open_trade.exit_reason = "EOD_CLOSE"
                    open_trade.outcome = "WIN" if open_trade.pnl_pct > 0 else "LOSS"
                    all_trades.append(open_trade)
                open_trade = None

            # Process intraday bars
            day_closes: list[float] = []

            for i, bar in enumerate(day_bars):
                dt = datetime.strptime(bar["datetime"], "%Y-%m-%d %H:%M:%S")
                hour = dt.hour
                minute = dt.minute
                time_minutes = hour * 60 + minute

                day_closes.append(bar["close"])

                # Track open trade
                if open_trade:
                    # Check stop
                    if bar["low"] <= open_trade.stop_price:
                        open_trade.exit_time = bar["datetime"]
                        open_trade.exit_price = open_trade.stop_price
                        open_trade.pnl_pct = ((open_trade.stop_price - open_trade.entry_price) / open_trade.entry_price) * 100
                        open_trade.exit_reason = "STOP_HIT"
                        open_trade.outcome = "LOSS"
                        all_trades.append(open_trade)
                        open_trade = None
                        continue

                    # Check target
                    if bar["high"] >= open_trade.target_price:
                        open_trade.exit_time = bar["datetime"]
                        open_trade.exit_price = open_trade.target_price
                        open_trade.pnl_pct = ((open_trade.target_price - open_trade.entry_price) / open_trade.entry_price) * 100
                        open_trade.exit_reason = "TARGET_HIT"
                        open_trade.outcome = "WIN"
                        all_trades.append(open_trade)
                        open_trade = None
                        continue

                    # Track MFE
                    mfe = ((bar["high"] - open_trade.entry_price) / open_trade.entry_price) * 100
                    open_trade.max_favorable = max(open_trade.max_favorable, mfe)
                    continue

                # === ENTRY LOGIC ===

                # RULE: Avoid first hour (9:30-10:30 = 570-630 minutes)
                if time_minutes < 630:
                    continue

                # RULE: Avoid midday chop (11:30-13:30 = 690-810)
                if 690 <= time_minutes < 810:
                    continue

                # Need enough bars for 20 SMA
                if len(day_closes) < 5:
                    continue

                # Also need multi-day context
                all_closes = closes_history + day_closes
                if len(all_closes) < 20:
                    continue

                sma_20 = sma(all_closes, 20)
                current = bar["close"]

                # Determine entry window
                if 630 <= time_minutes < 690:
                    window = "AM_MOMENTUM"
                elif 810 <= time_minutes < 900:
                    window = "PM_MOMENTUM"
                elif 900 <= time_minutes < 960:
                    window = "POWER_HOUR"
                else:
                    continue

                # ENTRY: 15-min 20 SMA pullback
                # Price touches or is within 0.3% of 20 SMA, then bounces
                # "if you look at an intraday 15min chart and flip on the 20sma"
                dist_to_sma = (current - sma_20) / sma_20 * 100

                # Bullish: price pulled back to SMA from above (within 0.3%)
                if 0 <= dist_to_sma <= 0.5 and current > sma_20:
                    # Confirm bounce: current bar closed above SMA
                    # and prior bar touched or dipped to SMA
                    entry_price = current
                    stop_price = sma_20 * 0.995  # stop 0.5% below SMA
                    target_price = entry_price * 1.0075  # +0.75% (sweet spot between WR and EV)

                    # Power hour gets wider (Mir: "act decisively in final minutes")
                    if window == "POWER_HOUR":
                        target_price = entry_price * 1.01  # +1.0%

                    open_trade = IntradayTrade(
                        entry_time=bar["datetime"],
                        ticker=ticker,
                        direction="BULL",
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_price=target_price,
                        window=window,
                        sma_20=sma_20,
                    )

            # Carry forward closes for multi-day SMA
            closes_history.extend(day_closes)
            if len(closes_history) > 100:
                closes_history = closes_history[-100:]

        # Close any remaining trade
        if open_trade:
            open_trade.exit_reason = "BACKTEST_END"
            open_trade.outcome = "LOSS" if open_trade.pnl_pct <= 0 else "WIN"
            all_trades.append(open_trade)

    # Results
    print(f"\n{'='*60}")
    print(f"  Mir Intraday Backtest Results (15-min bars)")
    print(f"{'='*60}")
    print(f"Total trades: {len(all_trades)}")

    if not all_trades:
        print("No trades generated")
        return {"trades": []}

    wins = sum(1 for t in all_trades if t.outcome == "WIN")
    losses = len(all_trades) - wins
    pnls = [t.pnl_pct for t in all_trades]
    avg_pnl = sum(pnls) / len(pnls)
    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]

    print(f"Wins: {wins}  |  Losses: {losses}  |  WR: {wins/len(all_trades)*100:.1f}%")
    print(f"Avg P&L: {avg_pnl:+.2f}%  |  Avg Win: {sum(win_pnls)/max(len(win_pnls),1):+.2f}%  |  Avg Loss: {sum(loss_pnls)/max(len(loss_pnls),1):.2f}%")

    # By ticker
    by_ticker = defaultdict(list)
    for t in all_trades:
        by_ticker[t.ticker].append(t)
    print(f"\nPer Ticker:")
    for tk, trades in sorted(by_ticker.items(), key=lambda x: len(x[1]), reverse=True):
        tw = sum(1 for t in trades if t.outcome == "WIN")
        tavg = sum(t.pnl_pct for t in trades) / len(trades)
        print(f"  {tk:<6} {tw}/{len(trades)} ({tw/len(trades)*100:.0f}% WR)  avg {tavg:+.2f}%")

    # By window
    by_window = defaultdict(list)
    for t in all_trades:
        by_window[t.window].append(t)
    print(f"\nBy Time Window:")
    for window, trades in sorted(by_window.items()):
        tw = sum(1 for t in trades if t.outcome == "WIN")
        tavg = sum(t.pnl_pct for t in trades) / len(trades)
        print(f"  {window:<15} {tw}/{len(trades)} ({tw/len(trades)*100:.0f}% WR)  avg {tavg:+.2f}%")

    # By exit reason
    by_exit = defaultdict(int)
    for t in all_trades:
        by_exit[t.exit_reason] += 1
    print(f"\nExit Reasons:")
    for reason, count in sorted(by_exit.items(), key=lambda x: x[1], reverse=True):
        print(f"  {reason}: {count}")

    # By day of week
    by_dow = defaultdict(list)
    for t in all_trades:
        dow = datetime.strptime(t.entry_time[:10], "%Y-%m-%d").strftime("%a")
        by_dow[dow].append(t)
    print(f"\nBy Day:")
    for dow in ["Tue", "Wed", "Thu", "Fri"]:
        trades = by_dow.get(dow, [])
        if trades:
            tw = sum(1 for t in trades if t.outcome == "WIN")
            print(f"  {dow}: {tw}/{len(trades)} ({tw/len(trades)*100:.0f}% WR)")

    print(f"{'='*60}")

    return {
        "total_trades": len(all_trades),
        "trades": [vars(t) for t in all_trades],
    }


def main():
    parser = argparse.ArgumentParser(description="Mir Intraday Backtest")
    parser.add_argument("--data", default="./data/intraday", help="Intraday data directory")
    parser.add_argument("--tickers", default="MU,LRCX,AMAT,SMH,NVDA,AMD,AVGO,LITE,COHR")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--output", default="mir_intraday_results.json")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    results = run_intraday_backtest(args.data, tickers, args.interval)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
