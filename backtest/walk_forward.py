"""Walk-Forward Backtest with Point-in-Time Basket Selection.

Runs 6 variants side-by-side to test whether the edge survives
proper universe construction.

Variants:
  A: Curated (original hindsight baskets)
  B: Point-in-time quarterly (top 3 sectors, frozen)
  C: Point-in-time monthly (top 3 sectors, refreshed monthly)
  D: Scanner-only (no sector filter, all stocks eligible)
  E: Random sectors (3 random sectors per quarter)
  F: Bottom 3 sectors (worst-performing, counter-test)
"""
import sys, io, json, csv, random, math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backtest.basket_selector import (
    SECTOR_ETFS, STOCK_SECTORS, load_etf_prices,
    select_baskets, compute_sector_scores,
    get_quarterly_rebalance_dates, get_monthly_rebalance_dates,
)
from backtest.runner import load_per_ticker_csvs
from backtest.mir_backtest import run_mir_backtest, CONFIGS, MirTrade
from backtest.mir_scorer import (
    score_mir_pattern, mir_stop_and_target, _ema,
    MIR_APPROVED_TICKERS,
)
from backtest.pricing import estimate_option_pnl


def get_sector_tickers(sector_etfs: list[str]) -> set[str]:
    """Get all stock tickers belonging to the given sector ETFs."""
    tickers = set()
    for stock, sector in STOCK_SECTORS.items():
        if sector in sector_etfs:
            tickers.add(stock)
    return tickers


def run_variant(
    chains: dict,
    spots: dict,
    variant_name: str,
    allowed_tickers_by_period: dict[str, set[str]],
    rebalance_dates: list[str],
    start: str = "2025-01-01",
    end: str = "2026-04-14",
) -> dict[str, Any]:
    """Run the Mir Swing backtest with a specific universe per period."""

    CONFIGS['swing']['dte_range'] = (7, 14)

    all_trades = []
    open_trades = []
    spot_history = defaultdict(list)

    all_dates = sorted(set(chains.keys()) | set(spots.keys()))
    trading_dates = [d for d in all_dates if start <= d <= end and date.fromisoformat(d).weekday() < 5]

    # Determine which period each date belongs to
    def get_period_tickers(d: str) -> set[str]:
        # Find the most recent rebalance date <= d
        active_rd = None
        for rd in rebalance_dates:
            if rd <= d:
                active_rd = rd
        if active_rd and active_rd in allowed_tickers_by_period:
            return allowed_tickers_by_period[active_rd]
        # Fallback to first period
        if rebalance_dates and rebalance_dates[0] in allowed_tickers_by_period:
            return allowed_tickers_by_period[rebalance_dates[0]]
        return set()

    quarter_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0, "sectors": "", "eligible": 0})

    for date_str in trading_dates:
        dt = date.fromisoformat(date_str)
        day_chains = chains.get(date_str, {})
        day_spots = spots.get(date_str, {})

        allowed = get_period_tickers(date_str)

        # Track SPY for regime filter
        spy_data = day_spots.get('SPY', {})
        if spy_data.get('close'):
            spot_history['SPY'].append(spy_data['close'])

        # Regime filter: skip if SPY 20d < 0
        if len(spot_history['SPY']) >= 20:
            spy_ret = (spot_history['SPY'][-1] - spot_history['SPY'][-20]) / spot_history['SPY'][-20] * 100
            if spy_ret < 0:
                # Still check exits on open trades
                _check_exits(open_trades, all_trades, day_spots, dt, spot_history)
                continue

        # Skip Mondays
        if dt.weekday() == 0:
            _check_exits(open_trades, all_trades, day_spots, dt, spot_history)
            continue

        # Check exits
        _check_exits(open_trades, all_trades, day_spots, dt, spot_history)

        # Generate signals for allowed tickers
        for ticker in allowed:
            if ticker in ('SPY', 'QQQ'):
                continue
            if ticker not in day_chains:
                continue
            spot_data = day_spots.get(ticker, {})
            spot = spot_data.get('close', 0)
            if not spot:
                continue

            if ticker not in spot_history:
                spot_history[ticker] = []
            spot_history[ticker].append(spot)

            # Skip if already in trade
            if any(t.ticker == ticker for t in open_trades):
                continue
            if len(open_trades) >= 5:
                continue

            # Mir score
            sh = spot_history.get(ticker, [])
            mir_score, _ = score_mir_pattern(ticker, sh, dte=14, direction="BULL")
            if mir_score < 3.5:
                continue

            # EMA check
            if len(sh) >= 21:
                ema21 = _ema(sh, 21)
                if spot < ema21:
                    continue

            # SMA check
            if len(sh) >= 50:
                sma20 = sum(sh[-20:]) / 20
                sma50 = sum(sh[-50:]) / 50
                if spot < sma20 or spot < sma50:
                    continue

            # Contract selection
            exps = sorted(set(c.get('expiration', '') for c in day_chains.get(ticker, []) if c.get('expiration')))
            target_exp = None
            best_dte = 0
            for exp_str in exps:
                try:
                    exp_date = date.fromisoformat(exp_str)
                    dte = (exp_date - dt).days
                    if 7 <= dte <= 14:
                        if target_exp is None or abs(dte - 10) < abs(best_dte - 10):
                            target_exp = exp_str
                            best_dte = dte
                except ValueError:
                    continue
            if not target_exp:
                continue

            # Strike
            strikes = day_chains.get(ticker, [])
            candidates = sorted(
                [s for s in strikes if float(s.get('strike', 0)) >= spot and s.get('option_type', '').lower() == 'call'],
                key=lambda s: float(s.get('strike', 0))
            )
            if not candidates:
                continue
            strike = float(candidates[min(1, len(candidates)-1)].get('strike', 0))

            trade = MirTrade(
                date=dt,
                ticker=ticker,
                direction="BULL",
                entry_spot=spot,
                strike=strike,
                dte=best_dte,
                expiration=target_exp,
                option_type="CALL",
                mir_score=mir_score,
                stop_pct=50,
                target_pct=100,
            )
            open_trades.append(trade)

            q = date_str[:7]
            quarter_stats[q]["trades"] += 1
            quarter_stats[q]["eligible"] = len(allowed)

    # Close remaining
    for t in open_trades:
        t.exit_reason = "BACKTEST_END"
        t.outcome = "LOSS" if t.pnl_pct <= 0 else "WIN"
        all_trades.append(t)

    # Stats
    filtered = [t for t in all_trades if t.ticker not in ('SPY', 'QQQ')]
    wins = sum(1 for t in filtered if t.outcome == 'WIN')
    pnls = [t.pnl_pct for t in filtered]

    # Quarter stats
    for t in filtered:
        q = str(t.date)[:7]
        quarter_stats[q]["pnl"] += t.pnl_pct
        if t.outcome == "WIN":
            quarter_stats[q]["wins"] += 1

    CONFIGS['swing']['dte_range'] = (14, 21)

    return {
        "variant": variant_name,
        "trades": len(filtered),
        "wins": wins,
        "wr": wins / max(len(filtered), 1) * 100,
        "avg_pnl": sum(pnls) / max(len(pnls), 1),
        "total_pnl": sum(pnls),
        "quarter_stats": dict(quarter_stats),
        "by_ticker": _ticker_breakdown(filtered),
    }


def _check_exits(open_trades, all_trades, day_spots, dt, spot_history):
    """Check open trades for exits."""
    for trade in list(open_trades):
        spot_data = day_spots.get(trade.ticker, {})
        spot = spot_data.get('close', 0)
        high = spot_data.get('high', spot)
        low = spot_data.get('low', spot)
        if not spot:
            continue

        trade.days_held = (dt - trade.date).days

        # MFE
        opt_pnl = estimate_option_pnl(trade.entry_spot, high, trade.strike,
                                       trade.dte, trade.days_held, 0.30, trade.option_type)
        trade.max_favorable = max(trade.max_favorable, opt_pnl)

        # Expiration
        try:
            exp = date.fromisoformat(trade.expiration)
            if dt > exp:
                trade.exit_date = dt
                trade.pnl_pct = -100
                trade.exit_reason = "EXPIRED"
                trade.outcome = "LOSS"
                open_trades.remove(trade)
                all_trades.append(trade)
                continue
        except ValueError:
            pass

        # Current P&L
        current_pnl = estimate_option_pnl(trade.entry_spot, spot, trade.strike,
                                           trade.dte, trade.days_held, 0.30, trade.option_type)

        # Exit ladder
        if not getattr(trade, '_ladder_triggered', False) and current_pnl >= 25:
            trade._ladder_triggered = True
            trade._breakeven_stop = True

        effective_stop = 0 if getattr(trade, '_breakeven_stop', False) else -trade.stop_pct

        if trade.stop_pct and current_pnl <= effective_stop:
            trade.exit_date = dt
            if getattr(trade, '_ladder_triggered', False):
                trade.exit_reason = "BREAKEVEN_STOP"
                trade.pnl_pct = 25 * 0.5
                trade.outcome = "WIN"
            else:
                trade.exit_reason = "STOP_HIT"
                trade.pnl_pct = current_pnl
                trade.outcome = "LOSS"
            open_trades.remove(trade)
            all_trades.append(trade)
            continue

        if current_pnl >= trade.target_pct:
            trade.exit_date = dt
            trade.exit_reason = "TARGET_HIT"
            trade.pnl_pct = current_pnl
            trade.outcome = "WIN"
            open_trades.remove(trade)
            all_trades.append(trade)


def _ticker_breakdown(trades):
    by_t = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0})
    for t in trades:
        by_t[t.ticker]["pnl"] += t.pnl_pct
        if t.outcome == "WIN":
            by_t[t.ticker]["w"] += 1
        else:
            by_t[t.ticker]["l"] += 1
    return {k: {"trades": v["w"]+v["l"], "wins": v["w"], "wr": v["w"]/(v["w"]+v["l"])*100, "total_pnl": v["pnl"]}
            for k, v in by_t.items()}


def main():
    chains, spots = load_per_ticker_csvs(Path('./data'))
    prices = load_etf_prices('data/spots.csv')

    start = "2025-01-01"
    end = "2026-04-14"
    q_dates = get_quarterly_rebalance_dates(start, end)
    m_dates = get_monthly_rebalance_dates(start, end)

    # All tradeable tickers (everything we have data for, minus indices)
    all_tickers = set(STOCK_SECTORS.keys()) - {None}

    print("=" * 80)
    print("  WALK-FORWARD BACKTEST: 6 VARIANTS")
    print("=" * 80)

    results = []

    # === VARIANT A: Curated (original hindsight baskets) ===
    curated_tickers = MIR_APPROVED_TICKERS - {'SPY', 'QQQ', 'IWM', 'SMH'}
    a_periods = {rd: curated_tickers for rd in q_dates}
    r = run_variant(chains, spots, "A: Curated", a_periods, q_dates, start, end)
    results.append(r)

    # === VARIANT B: Point-in-time quarterly ===
    b_periods = {}
    for rd in q_dates:
        baskets = select_baskets(prices, prices, rd, top_n=3)
        sector_etfs = [b['etf'] for b in baskets]
        tickers = get_sector_tickers(sector_etfs) & all_tickers
        b_periods[rd] = tickers
        print(f"  B Q{rd[:7]}: {sector_etfs} -> {len(tickers)} tickers")
    r = run_variant(chains, spots, "B: PIT Quarterly", b_periods, q_dates, start, end)
    results.append(r)

    # === VARIANT C: Point-in-time monthly ===
    c_periods = {}
    for rd in m_dates:
        baskets = select_baskets(prices, prices, rd, top_n=3)
        sector_etfs = [b['etf'] for b in baskets]
        tickers = get_sector_tickers(sector_etfs) & all_tickers
        c_periods[rd] = tickers
    r = run_variant(chains, spots, "C: PIT Monthly", c_periods, m_dates, start, end)
    results.append(r)

    # === VARIANT D: Scanner-only (all tickers eligible) ===
    d_periods = {q_dates[0]: all_tickers}
    r = run_variant(chains, spots, "D: Scanner-only", d_periods, [q_dates[0]], start, end)
    results.append(r)

    # === VARIANT E: Random sectors (3 random per quarter) ===
    random.seed(42)
    e_periods = {}
    for rd in q_dates:
        rand_sectors = random.sample(list(SECTOR_ETFS.keys()), 3)
        tickers = get_sector_tickers(rand_sectors) & all_tickers
        e_periods[rd] = tickers
    r = run_variant(chains, spots, "E: Random", e_periods, q_dates, start, end)
    results.append(r)

    # === VARIANT F: Bottom 3 sectors ===
    f_periods = {}
    for rd in q_dates:
        scores = compute_sector_scores(prices, prices, rd)
        bottom = scores[-3:]  # worst 3
        sector_etfs = [b['etf'] for b in bottom]
        tickers = get_sector_tickers(sector_etfs) & all_tickers
        f_periods[rd] = tickers
    r = run_variant(chains, spots, "F: Bottom 3", f_periods, q_dates, start, end)
    results.append(r)

    # === RESULTS TABLE ===
    print("\n" + "=" * 80)
    print("  RESULTS COMPARISON")
    print("=" * 80)
    print(f"\n  {'Variant':<22} {'Trades':>6} {'WR':>6} {'Avg P&L':>8} {'Total P&L':>10}")
    print("  " + "-" * 55)
    for r in sorted(results, key=lambda x: x['avg_pnl'], reverse=True):
        print(f"  {r['variant']:<22} {r['trades']:>6} {r['wr']:>5.1f}% {r['avg_pnl']:>+7.1f}% {r['total_pnl']:>+9.0f}%")

    # PIT vs Curated comparison
    a = next(r for r in results if r['variant'].startswith('A'))
    b = next(r for r in results if r['variant'].startswith('B'))
    e = next(r for r in results if r['variant'].startswith('E'))

    if a['avg_pnl'] > 0:
        capture = b['avg_pnl'] / a['avg_pnl'] * 100
        print(f"\n  PIT Quarterly captures {capture:.0f}% of Curated edge")
    if b['avg_pnl'] > e['avg_pnl']:
        print(f"  PIT Quarterly beats Random by {b['avg_pnl'] - e['avg_pnl']:+.1f}% avg")

    # Per-quarter breakdown for top variants
    print(f"\n  Per-Quarter Detail:")
    print(f"  {'Quarter':<10} {'A:Curated':>12} {'B:PIT-Q':>12} {'D:Scanner':>12} {'E:Random':>12}")
    all_quarters = sorted(set(
        list(a.get('quarter_stats', {}).keys()) +
        list(b.get('quarter_stats', {}).keys())
    ))
    for q in all_quarters:
        aq = a.get('quarter_stats', {}).get(q, {})
        bq = b.get('quarter_stats', {}).get(q, {})
        dq = next(r for r in results if r['variant'].startswith('D')).get('quarter_stats', {}).get(q, {})
        eq = e.get('quarter_stats', {}).get(q, {})
        def fmt(qs):
            if not qs or not qs.get('trades'):
                return "   -"
            return f"{qs['wins']}/{qs['trades']} {qs['pnl']:+.0f}%"
        print(f"  {q:<10} {fmt(aq):>12} {fmt(bq):>12} {fmt(dq):>12} {fmt(eq):>12}")

    # Ticker breakdown for B (PIT Quarterly)
    print(f"\n  PIT Quarterly - Top Tickers:")
    b_tickers = b.get('by_ticker', {})
    for tk, v in sorted(b_tickers.items(), key=lambda x: x[1]['total_pnl'], reverse=True)[:10]:
        print(f"    {tk:<6} {v['wins']}/{v['trades']} ({v['wr']:.0f}% WR)  total {v['total_pnl']:+.0f}%")

    print("\n" + "=" * 80)

    # Save
    with open('walk_forward_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to walk_forward_results.json")


if __name__ == "__main__":
    main()
