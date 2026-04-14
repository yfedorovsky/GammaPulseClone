"""Mir Rules Backtest — runs Mir's momentum/trend rules on historical data.

Can run standalone (Mir rules only) or combined with GEX scoring.

Usage:
    # Mir rules only (Config 1: Swing)
    python -m backtest.mir_backtest --data ./data --config swing

    # Mir + GEX combined
    python -m backtest.mir_backtest --data ./data --config swing --with-gex

Configs:
    swing:    14-21 DTE, photonics + semi, EMA filter, -50% stop, +100% target
    scalp:    1-3 DTE, SPY/QQQ only, -50% stop, +30% target
    oversold: 7-14 DTE, NYMO < -40 proxy, EMA filter, -50% stop, +100% target
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gex_engine import compute_levels
from .mir_scorer import (
    score_mir_pattern, mir_stop_and_target, mir_size_pct,
    MIR_APPROVED_TICKERS, _ema,
)
from .pricing import estimate_option_pnl
from .results import compute_stats, print_report


CONFIGS = {
    "swing": {
        "label": "Mir Swing (14-21 DTE, sector leaders)",
        "dte_range": (14, 21),
        "tickers": None,  # all approved tickers
        "direction": "BULL",  # Mir is primarily bullish momentum
        "min_mir_score": 3.5,  # out of 6
        "stop_pct": 50,
        "target_pct": 100,
        "scale_out": 0.50,
    },
    "scalp": {
        "label": "Mir Scalp (1-3 DTE, SPY/QQQ)",
        "dte_range": (1, 3),
        "tickers": ["SPY", "QQQ"],
        "direction": "BULL",
        "min_mir_score": 2.5,
        "stop_pct": 50,
        "target_pct": 30,
        "scale_out": 0.67,
    },
    "oversold": {
        "label": "Mir Oversold Bounce (7-14 DTE, NYMO proxy)",
        "dte_range": (7, 14),
        "tickers": None,
        "direction": "BULL",
        "min_mir_score": 3.5,
        "stop_pct": 50,
        "target_pct": 100,
        "scale_out": 0.50,
        "require_oversold": True,
    },
}


@dataclass
class MirTrade:
    date: datetime.date
    ticker: str
    direction: str
    entry_spot: float
    strike: float
    dte: int
    expiration: str
    option_type: str
    mir_score: float
    gex_score: float = 0
    gex_grade: str = ""
    signal_type: str = ""
    stop_pct: float = 50
    target_pct: float = 100
    # Outcome
    exit_date: datetime.date | None = None
    exit_spot: float = 0
    exit_reason: str = ""
    pnl_pct: float = 0
    outcome: str = ""
    max_favorable: float = 0
    days_held: int = 0


def run_mir_backtest(
    chains: dict,
    spots: dict,
    config_name: str = "swing",
    with_gex: bool = False,
    account_value: float = 100_000,
) -> dict[str, Any]:
    """Run Mir's rules on historical data."""
    cfg = CONFIGS[config_name]
    print(f"\n{'='*60}")
    print(f"  Mir Backtest: {cfg['label']}")
    print(f"  GEX combined: {with_gex}")
    print(f"{'='*60}\n")

    allowed_tickers = set(cfg["tickers"]) if cfg["tickers"] else MIR_APPROVED_TICKERS
    dte_min, dte_max = cfg["dte_range"]
    direction = cfg["direction"]

    trades: list[MirTrade] = []
    open_trades: list[MirTrade] = []
    spot_history: dict[str, list[float]] = {}

    all_dates = sorted(set(chains.keys()) | set(spots.keys()))

    for date_str in all_dates:
        date = datetime.date.fromisoformat(date_str)
        if date.weekday() >= 5:
            continue

        day_chains = chains.get(date_str, {})
        day_spots = spots.get(date_str, {})

        # Check open trades for exits
        for trade in list(open_trades):
            spot_data = day_spots.get(trade.ticker, {})
            spot = spot_data.get("close", 0)
            high = spot_data.get("high", spot)
            low = spot_data.get("low", spot)
            if not spot:
                continue

            trade.days_held = (date - trade.date).days

            # Track MFE
            spot_move = ((high - trade.entry_spot) / trade.entry_spot) * 100 if direction == "BULL" else ((trade.entry_spot - low) / trade.entry_spot) * 100
            opt_pnl = estimate_option_pnl(trade.entry_spot, high if direction == "BULL" else low,
                                          trade.strike, trade.dte, trade.days_held, 0.30, trade.option_type)
            trade.max_favorable = max(trade.max_favorable, opt_pnl)

            # Check expiration
            try:
                exp_date = datetime.date.fromisoformat(trade.expiration)
                if date > exp_date:
                    trade.exit_date = date
                    trade.exit_spot = spot
                    trade.exit_reason = "EXPIRED"
                    trade.pnl_pct = -100
                    trade.outcome = "LOSS"
                    open_trades.remove(trade)
                    trades.append(trade)
                    continue
            except ValueError:
                pass

            # Check stop (-50% option value)
            current_pnl = estimate_option_pnl(trade.entry_spot, spot, trade.strike,
                                              trade.dte, trade.days_held, 0.30, trade.option_type)

            # EXIT LADDER: take partial at +25%, move stop to breakeven
            # Data: 57% of losers hit +20% before crashing to -50%
            # Speed stop REMOVED (v4/v5 showed it kills recoverable trades)
            if not getattr(trade, '_ladder_triggered', False) and current_pnl >= 25:
                trade._ladder_triggered = True
                trade._breakeven_stop = True
                # Don't exit yet — just lock in partial and raise stop

            # If ladder triggered, use breakeven stop instead of -50%
            effective_stop = 0 if getattr(trade, '_breakeven_stop', False) else -trade.stop_pct

            if trade.stop_pct and current_pnl <= effective_stop:
                trade.exit_date = date
                trade.exit_spot = spot
                if getattr(trade, '_ladder_triggered', False):
                    # Stopped at breakeven after capturing +35% on first half
                    trade.exit_reason = "BREAKEVEN_STOP"
                    trade.pnl_pct = 25 * 0.5  # kept half at +25%, other half at 0
                    trade.outcome = "WIN"
                else:
                    trade.exit_reason = "STOP_HIT"
                    trade.pnl_pct = current_pnl
                    trade.outcome = "LOSS"
                open_trades.remove(trade)
                trades.append(trade)
                continue

            # Check target (+100% or +30% depending on config)
            if current_pnl >= trade.target_pct:
                trade.exit_date = date
                trade.exit_spot = spot
                trade.exit_reason = "TARGET_HIT"
                trade.pnl_pct = current_pnl
                trade.outcome = "WIN"
                open_trades.remove(trade)
                trades.append(trade)
                continue

        # Track SPY spot for regime filter (must happen before filter check)
        spy_spot_data = day_spots.get("SPY", {})
        spy_close = spy_spot_data.get("close", 0)
        if spy_close:
            if "SPY" not in spot_history:
                spot_history["SPY"] = []
            spot_history["SPY"].append(spy_close)

        # REGIME FILTER: skip entries when SPY 20d return is negative
        # Data shows: BEAR months = 11% WR, -50% avg. BULL = 48% WR, +33% avg.
        spy_history = spot_history.get("SPY", [])
        if len(spy_history) >= 20:
            spy_20d_return = (spy_history[-1] - spy_history[-20]) / spy_history[-20] * 100
            if spy_20d_return < 0:
                continue  # skip entire day -- bearish regime

        # MONDAY SKIP: 34% WR vs 46-51% on other days
        if date.weekday() == 0:
            continue

        # Generate new signals
        for ticker in allowed_tickers:
            if ticker not in day_chains:
                continue
            spot_data = day_spots.get(ticker, {})
            spot = spot_data.get("close", 0)
            if not spot:
                continue

            # Track spot history
            if ticker not in spot_history:
                spot_history[ticker] = []
            spot_history[ticker].append(spot)

            # Skip if already have open trade on this ticker
            if any(t.ticker == ticker for t in open_trades):
                continue

            # Skip if max positions reached
            if len(open_trades) >= 5:
                continue

            # Build sector histories for RS ranking
            sector_histories = {t: spot_history[t] for t in allowed_tickers
                               if t in spot_history and t != ticker}

            # Mir score (with RS + SMA filters from RAG)
            mir_score, mir_reasons = score_mir_pattern(
                ticker, spot_history.get(ticker), dte=dte_max, direction=direction,
                sector_histories=sector_histories,
            )

            if mir_score < cfg["min_mir_score"]:
                continue

            # EMA check (require bullish structure for BULL)
            sh = spot_history.get(ticker, [])
            if len(sh) >= 21:
                ema21 = _ema(sh, 21)
                if direction == "BULL" and spot < ema21:
                    continue
                if direction == "BEAR" and spot > ema21:
                    continue

            # Oversold check if required
            if cfg.get("require_oversold") and len(sh) >= 20:
                returns = [(sh[i] - sh[i-1]) / sh[i-1] for i in range(-19, 0) if sh[i-1] > 0]
                rv = (sum(r**2 for r in returns) / len(returns)) ** 0.5 * math.sqrt(252) * 100
                # NYMO proxy: RV > 30% = oversold-ish
                if rv < 30:
                    continue

            # GEX scoring (optional)
            gex_score = 0
            gex_grade = ""
            signal_type = ""
            if with_gex and ticker in day_chains:
                state = compute_levels(day_chains[ticker], spot)
                state["spot"] = spot
                from .soe_scorer import score_signal, determine_direction, determine_signal_type
                gex_dir = determine_direction(state)
                if gex_dir:
                    gex_score, gex_grade, _ = score_signal(state, gex_dir, spot_history=sh)
                    signal_type = determine_signal_type(state, gex_dir)

            # Select contract
            exps = sorted(set(c.get("expiration", "") for c in day_chains.get(ticker, []) if c.get("expiration")))
            target_exp = None
            best_dte = 0
            for exp_str in exps:
                try:
                    exp_date = datetime.date.fromisoformat(exp_str)
                    dte = (exp_date - date).days
                    if dte_min <= dte <= dte_max:
                        if target_exp is None or abs(dte - (dte_min + dte_max) // 2) < abs(best_dte - (dte_min + dte_max) // 2):
                            target_exp = exp_str
                            best_dte = dte
                except ValueError:
                    continue

            if not target_exp:
                continue

            # Strike: ATM or 1st OTM
            strikes = day_chains.get(ticker, [])
            otype = "CALL" if direction == "BULL" else "PUT"
            if direction == "BULL":
                candidates = sorted([s for s in strikes if float(s.get("strike", 0)) >= spot and s.get("option_type", "").lower() == "call"],
                                   key=lambda s: float(s.get("strike", 0)))
            else:
                candidates = sorted([s for s in strikes if float(s.get("strike", 0)) <= spot and s.get("option_type", "").lower() == "put"],
                                   key=lambda s: float(s.get("strike", 0)), reverse=True)

            if not candidates:
                continue
            selected_strike = float(candidates[min(1, len(candidates)-1)].get("strike", 0))

            # Create trade
            stop_target = mir_stop_and_target(best_dte)
            trade = MirTrade(
                date=date,
                ticker=ticker,
                direction=direction,
                entry_spot=spot,
                strike=selected_strike,
                dte=best_dte,
                expiration=target_exp,
                option_type=otype,
                mir_score=mir_score,
                gex_score=gex_score,
                gex_grade=gex_grade,
                signal_type=signal_type,
                stop_pct=cfg["stop_pct"],
                target_pct=cfg["target_pct"],
            )
            open_trades.append(trade)

    # Close remaining
    for trade in open_trades:
        trade.exit_reason = "BACKTEST_END"
        trade.outcome = "LOSS" if trade.pnl_pct <= 0 else "WIN"
        trades.append(trade)

    # Results
    print(f"\nTotal trades: {len(trades)}")
    if trades:
        wins = sum(1 for t in trades if t.outcome == "WIN")
        losses = len(trades) - wins
        pnls = [t.pnl_pct for t in trades]
        avg_pnl = sum(pnls) / len(pnls)
        win_pnls = [p for p in pnls if p > 0]
        loss_pnls = [p for p in pnls if p <= 0]
        avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 0
        avg_loss = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0

        print(f"Wins: {wins}  |  Losses: {losses}  |  WR: {wins/len(trades)*100:.1f}%")
        print(f"Avg P&L: {avg_pnl:+.1f}%  |  Avg Win: {avg_win:+.1f}%  |  Avg Loss: {avg_loss:.1f}%")

        # Per-ticker
        by_ticker: dict[str, list] = defaultdict(list)
        for t in trades:
            by_ticker[t.ticker].append(t)
        print(f"\nPer Ticker:")
        for ticker, ticker_trades in sorted(by_ticker.items(), key=lambda x: len(x[1]), reverse=True):
            tw = sum(1 for t in ticker_trades if t.outcome == "WIN")
            tavg = sum(t.pnl_pct for t in ticker_trades) / len(ticker_trades)
            print(f"  {ticker:<6} {tw}/{len(ticker_trades)} ({tw/len(ticker_trades)*100:.0f}% WR)  avg {tavg:+.1f}%")

        # Per exit reason
        by_exit: dict[str, int] = defaultdict(int)
        for t in trades:
            by_exit[t.exit_reason] += 1
        print(f"\nExit Reasons:")
        for reason, count in sorted(by_exit.items(), key=lambda x: x[1], reverse=True):
            print(f"  {reason}: {count}")

        if with_gex:
            print(f"\nGEX Grade Distribution:")
            by_grade: dict[str, list] = defaultdict(list)
            for t in trades:
                by_grade[t.gex_grade or "N/A"].append(t)
            for grade in ["A+", "A", "B+", "B", "C", "N/A"]:
                if grade in by_grade:
                    gt = by_grade[grade]
                    gw = sum(1 for t in gt if t.outcome == "WIN")
                    gavg = sum(t.pnl_pct for t in gt) / len(gt)
                    print(f"  {grade}: {gw}/{len(gt)} ({gw/len(gt)*100:.0f}% WR)  avg {gavg:+.1f}%")

    return {
        "config": config_name,
        "label": cfg["label"],
        "with_gex": with_gex,
        "total_trades": len(trades),
        "trades": [vars(t) for t in trades],
    }


def main():
    from .runner import load_per_ticker_csvs

    parser = argparse.ArgumentParser(description="Mir Rules Backtest")
    parser.add_argument("--data", default="./data", help="Data directory")
    parser.add_argument("--config", default="swing", choices=list(CONFIGS.keys()), help="Mir config to test")
    parser.add_argument("--with-gex", action="store_true", help="Combine with GEX scoring")
    parser.add_argument("--start", default="2024-04-01")
    parser.add_argument("--end", default="2026-04-14")
    parser.add_argument("--output", default="mir_results.json")
    args = parser.parse_args()

    chains, spots = load_per_ticker_csvs(Path(args.data))

    # Filter by date range
    start = args.start
    end = args.end
    chains = {d: v for d, v in chains.items() if start <= d <= end}
    spots = {d: v for d, v in spots.items() if start <= d <= end}

    results = run_mir_backtest(chains, spots, args.config, args.with_gex)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
