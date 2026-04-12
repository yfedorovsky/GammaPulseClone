"""Contract selection grid search.

Runs the backtest engine across multiple strike_offset x target_dte
combinations and reports results side-by-side.

Usage:
    python -m backtest.grid_search --data ./data --tickers SPY,QQQ

ChatGPT recommended order:
  Tier 1 core: 1st OTM/14, ATM/14, 1st OTM/7, ATM/7
  Tier 2 extension: 1st OTM/21, ATM/21
  Tier 3 tail-risk: 2nd OTM/14, 2nd OTM/7, 2nd OTM/21
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from .runner import load_per_ticker_csvs, run_backtest
from .results import compute_stats


GRID = [
    # Tier 1 core
    {"label": "ATM/7",      "strike_offset": 0, "target_dte": 7},
    {"label": "ATM/14",     "strike_offset": 0, "target_dte": 14},
    {"label": "1st OTM/7",  "strike_offset": 1, "target_dte": 7},
    {"label": "1st OTM/14", "strike_offset": 1, "target_dte": 14},
    # Tier 2 extension
    {"label": "ATM/21",     "strike_offset": 0, "target_dte": 21},
    {"label": "1st OTM/21", "strike_offset": 1, "target_dte": 21},
    # Tier 3 tail-risk
    {"label": "2nd OTM/7",  "strike_offset": 2, "target_dte": 7},
    {"label": "2nd OTM/14", "strike_offset": 2, "target_dte": 14},
    {"label": "2nd OTM/21", "strike_offset": 2, "target_dte": 21},
]


def run_grid(
    data_path: str,
    tickers: list[str],
    start_date: str,
    end_date: str,
    account_value: float = 100_000,
) -> list[dict[str, Any]]:
    """Run backtest for each grid cell and collect results."""
    from .runner import load_per_ticker_csvs

    data_dir = Path(data_path)
    if data_dir.is_dir():
        chains, spots = load_per_ticker_csvs(data_dir)
    else:
        print(f"Error: {data_dir} not found")
        sys.exit(1)

    print(f"Grid search: {len(GRID)} cells x {len(tickers)} tickers")
    print(f"Period: {start_date} -> {end_date}")
    print(f"Data: {len(chains)} dates loaded\n")

    all_results = []

    for cell in GRID:
        label = cell["label"]
        strike_offset = cell["strike_offset"]
        dte = cell["target_dte"]

        print(f"--- {label} (strike_offset={strike_offset}, target_dte={dte}) ---")

        # Patch select_contract defaults for this cell
        # We do this by monkey-patching the module defaults before running
        import backtest.soe_scorer as scorer
        original_select = scorer.select_contract

        def patched_select(state, direction, exps, trade_date=None,
                          _so=strike_offset, _dte=dte, **kwargs):
            return original_select(state, direction, exps, trade_date,
                                  strike_offset=_so, target_dte=_dte)

        scorer.select_contract = patched_select

        try:
            results = run_backtest(chains, spots, tickers, start_date, end_date, account_value)
            stats = compute_stats(results)

            summary = stats.get("summary", {})
            by_grade = stats.get("by_grade", {})
            benchmark = stats.get("benchmark", {})

            cell_result = {
                "label": label,
                "strike_offset": strike_offset,
                "target_dte": dte,
                "trades": summary.get("signals_traded", 0),
                "win_rate": summary.get("win_rate", 0),
                "avg_pnl": summary.get("avg_pnl", 0),
                "avg_win": summary.get("avg_win", 0),
                "avg_loss": summary.get("avg_loss", 0),
                "total_return": summary.get("total_return", 0),
                "max_drawdown": summary.get("max_drawdown", 0),
                "expectancy": summary.get("avg_pnl", 0),
                "overall_alpha": benchmark.get("overall_alpha", 0),
                "by_grade": by_grade,
                "by_ticker": stats.get("by_ticker", {}),
            }
            all_results.append(cell_result)

            print(f"  Trades: {cell_result['trades']}  WR: {cell_result['win_rate']}%  "
                  f"Avg: {cell_result['avg_pnl']:+.1f}%  "
                  f"Win: {cell_result['avg_win']:+.1f}%  Loss: {cell_result['avg_loss']:.1f}%  "
                  f"DD: {cell_result['max_drawdown']:.1f}%  "
                  f"Alpha: {cell_result['overall_alpha']:+.1f}%")
        except Exception as e:
            print(f"  ERROR: {e}")
            all_results.append({"label": label, "error": str(e)})
        finally:
            scorer.select_contract = original_select

        print()

    return all_results


def print_grid_report(results: list[dict]) -> None:
    """Print side-by-side comparison of all grid cells."""
    valid = [r for r in results if "error" not in r and r.get("trades", 0) > 0]

    if not valid:
        print("No valid results")
        return

    print("\n" + "=" * 90)
    print("  CONTRACT SELECTION GRID SEARCH RESULTS")
    print("=" * 90)
    print(f"  {'CONFIG':<15} {'TRADES':>6} {'WR':>6} {'AVG P&L':>8} {'AVG WIN':>8} {'AVG LOSS':>9} {'DD':>6} {'ALPHA':>8} {'EV':>8}")
    print("-" * 90)

    # Sort by expectancy descending
    ranked = sorted(valid, key=lambda r: r.get("expectancy", 0), reverse=True)

    for i, r in enumerate(ranked):
        marker = " <-- BEST" if i == 0 else ""
        print(f"  {r['label']:<15} {r['trades']:>6} {r['win_rate']:>5.1f}% {r['avg_pnl']:>+7.1f}% "
              f"{r['avg_win']:>+7.1f}% {r['avg_loss']:>8.1f}% {r['max_drawdown']:>5.1f}% "
              f"{r.get('overall_alpha', 0):>+7.1f}% {r['expectancy']:>+7.1f}%{marker}")

    # Per-ticker breakdown for top 3
    print(f"\n-- Top 3 Per-Ticker Breakdown --")
    for r in ranked[:3]:
        print(f"\n  {r['label']}:")
        for ticker, tv in sorted(r.get("by_ticker", {}).items()):
            print(f"    {ticker:<6} {tv['win_rate']:>5.1f}% WR  ({tv['wins']}W / {tv['trades']}T)  avg {tv['avg_pnl']:+.1f}%")

    print("=" * 90)

    # Decision framework (per ChatGPT)
    print("\n  DECISION CRITERIA (pre-registered):")
    print("  1. Positive expectancy")
    print("  2. Lower avg loss magnitude")
    print("  3. Lower drawdown")
    print("  4. Then total return")
    print("  Minimum 20 trades combined, 8 per ticker for ticker-specific conclusions")


def main():
    parser = argparse.ArgumentParser(description="Contract selection grid search")
    parser.add_argument("--data", default="./data", help="Path to data directory")
    parser.add_argument("--tickers", default="SPY,QQQ", help="Comma-separated tickers")
    parser.add_argument("--start", default="2024-04-01", help="Start date")
    parser.add_argument("--end", default="2026-04-11", help="End date")
    parser.add_argument("--account", type=float, default=100_000, help="Starting account")
    parser.add_argument("--output", default="grid_results.json", help="Output JSON")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    results = run_grid(args.data, tickers, args.start, args.end, args.account)
    print_grid_report(results)

    # Save
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
