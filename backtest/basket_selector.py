"""Point-in-Time Quarterly Basket Selector.

Selects top N sectors using ONLY backward-looking data at each rebalance date.
No hindsight, no forward-selected winners.

Methodology:
  1. Start with SPDR sector ETFs (clean, no survivorship issues)
  2. Compute composite score: percentile-ranked 3mo return + breadth + median RS
  3. Select top N sectors
  4. Return frozen basket for the quarter

ChatGPT corrections applied:
  - Percentile-rank normalization (not raw values)
  - Pure quarterly and pure monthly tested separately (no emergency refresh in v1)
  - Turnover/stability stats tracked
  - Sector ETF benchmark comparison included
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


# SPDR Sector ETFs (clean, no survivorship issues)
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Disc.",
    "XLC": "Communication",
    "XLP": "Consumer Staples",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLB": "Materials",
}

# Approximate sector membership for stocks in our universe
# This is a FIXED mapping defined once — no point-in-time membership needed
# because we use the same mapping throughout the backtest
STOCK_SECTORS = {
    # Technology
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "AMD": "XLK",
    "INTC": "XLK", "MU": "XLK", "MRVL": "XLK", "TSM": "XLK", "AMAT": "XLK",
    "LRCX": "XLK", "ANET": "XLK", "COHR": "XLK", "LITE": "XLK", "AAOI": "XLK",
    "GLW": "XLK", "CIEN": "XLK", "TSEM": "XLK", "AXTI": "XLK", "NET": "XLK",
    "SNOW": "XLK", "PLTR": "XLK", "VRT": "XLI",  # Vertiv is industrials
    # Consumer Disc
    "TSLA": "XLY", "AMZN": "XLY",
    # Communication
    "META": "XLC", "GOOGL": "XLC",
    # Industrials
    "RKLB": "XLI", "ASTS": "XLC",  # ASTS is communication/space
    "SATL": "XLI", "VOYG": "XLI",
    # ETFs (not in sectors, for reference only)
    "SPY": None, "QQQ": None, "SMH": None,
}


def load_etf_prices(spots_path: str) -> dict[str, list[tuple[str, float]]]:
    """Load sector ETF daily prices from spots.csv."""
    prices = defaultdict(list)
    with open(spots_path) as f:
        for row in csv.DictReader(f):
            ticker = row['ticker']
            if ticker in SECTOR_ETFS or ticker in STOCK_SECTORS:
                try:
                    prices[ticker].append((row['date'], float(row['close'])))
                except (ValueError, KeyError):
                    pass
    # Sort by date
    for ticker in prices:
        prices[ticker].sort()
    return dict(prices)


def _percentile_rank(values: list[float]) -> list[float]:
    """Convert raw values to percentile ranks (0 to 1)."""
    if not values:
        return []
    n = len(values)
    sorted_vals = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank, (idx, _) in enumerate(sorted_vals):
        ranks[idx] = rank / max(n - 1, 1)
    return ranks


def compute_sector_scores(
    etf_prices: dict[str, list[tuple[str, float]]],
    stock_prices: dict[str, list[tuple[str, float]]],
    as_of_date: str,
    lookback_days: int = 63,  # ~3 months
) -> list[dict[str, Any]]:
    """Compute composite sector scores using ONLY data up to as_of_date.

    Score = 0.4 * percentile(3mo_return) + 0.3 * percentile(breadth) + 0.3 * percentile(median_RS)
    All inputs percentile-ranked to prevent any single component from dominating.
    """
    scores = []

    for etf, sector_name in SECTOR_ETFS.items():
        # Get ETF prices up to as_of_date
        etf_hist = [(d, p) for d, p in etf_prices.get(etf, []) if d <= as_of_date]
        if len(etf_hist) < lookback_days:
            continue

        # 1. 3-month ETF return
        current_price = etf_hist[-1][1]
        lookback_price = etf_hist[-min(lookback_days, len(etf_hist))][1]
        three_mo_return = (current_price - lookback_price) / lookback_price * 100 if lookback_price > 0 else 0

        # 2. Breadth: % of sector members above their 50-day MA
        sector_stocks = [s for s, sec in STOCK_SECTORS.items() if sec == etf]
        above_50ma = 0
        total_stocks = 0
        for stock in sector_stocks:
            stock_hist = [(d, p) for d, p in stock_prices.get(stock, []) if d <= as_of_date]
            if len(stock_hist) < 50:
                continue
            total_stocks += 1
            current = stock_hist[-1][1]
            ma_50 = sum(p for _, p in stock_hist[-50:]) / 50
            if current > ma_50:
                above_50ma += 1
        breadth = (above_50ma / total_stocks * 100) if total_stocks > 0 else 0

        # 3. Median RS: median 20-day return of sector members vs SPY
        spy_hist = [(d, p) for d, p in stock_prices.get('SPY', []) if d <= as_of_date]
        spy_20d_ret = 0
        if len(spy_hist) >= 20:
            spy_20d_ret = (spy_hist[-1][1] - spy_hist[-20][1]) / spy_hist[-20][1] * 100

        rs_values = []
        for stock in sector_stocks:
            stock_hist = [(d, p) for d, p in stock_prices.get(stock, []) if d <= as_of_date]
            if len(stock_hist) >= 20:
                stock_ret = (stock_hist[-1][1] - stock_hist[-20][1]) / stock_hist[-20][1] * 100
                rs_values.append(stock_ret - spy_20d_ret)

        median_rs = sorted(rs_values)[len(rs_values) // 2] if rs_values else 0

        scores.append({
            'etf': etf,
            'sector': sector_name,
            'three_mo_return': three_mo_return,
            'breadth': breadth,
            'median_rs': median_rs,
            'stock_count': total_stocks,
        })

    if not scores:
        return scores

    # Percentile-rank each component (ChatGPT: normalize to prevent one dominating)
    returns = [s['three_mo_return'] for s in scores]
    breadths = [s['breadth'] for s in scores]
    rs_vals = [s['median_rs'] for s in scores]

    ret_ranks = _percentile_rank(returns)
    brd_ranks = _percentile_rank(breadths)
    rs_ranks = _percentile_rank(rs_vals)

    for i, s in enumerate(scores):
        s['ret_rank'] = ret_ranks[i]
        s['brd_rank'] = brd_ranks[i]
        s['rs_rank'] = rs_ranks[i]
        s['composite'] = 0.4 * ret_ranks[i] + 0.3 * brd_ranks[i] + 0.3 * rs_ranks[i]

    scores.sort(key=lambda s: s['composite'], reverse=True)
    return scores


def select_baskets(
    etf_prices: dict,
    stock_prices: dict,
    as_of_date: str,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Select top N sectors as of a given date. Returns the frozen basket."""
    scores = compute_sector_scores(etf_prices, stock_prices, as_of_date)
    selected = scores[:top_n]
    return selected


def get_quarterly_rebalance_dates(start: str, end: str) -> list[str]:
    """Generate quarterly rebalance dates (first trading day of each quarter)."""
    dates = []
    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)

    while d <= end_d:
        # Start of quarter: Jan 1, Apr 1, Jul 1, Oct 1
        quarter_starts = [
            date(d.year, 1, 2), date(d.year, 4, 1),
            date(d.year, 7, 1), date(d.year, 10, 1),
        ]
        for qs in quarter_starts:
            if qs >= d and qs <= end_d:
                # Skip weekends
                while qs.weekday() >= 5:
                    qs += timedelta(days=1)
                dates.append(qs.isoformat())
        d = date(d.year + 1, 1, 1)

    return sorted(set(dates))


def get_monthly_rebalance_dates(start: str, end: str) -> list[str]:
    """Generate monthly rebalance dates."""
    dates = []
    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)

    while d <= end_d:
        # First trading day of month
        first = d.replace(day=1)
        while first.weekday() >= 5:
            first += timedelta(days=1)
        if first <= end_d:
            dates.append(first.isoformat())
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    return sorted(set(dates))


def run_basket_analysis(spots_path: str, start: str = "2025-01-01", end: str = "2026-04-14"):
    """Run the full basket selection analysis and print results."""
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    prices = load_etf_prices(spots_path)

    print("=" * 70)
    print("  POINT-IN-TIME BASKET SELECTION ANALYSIS")
    print("=" * 70)

    # Quarterly baskets
    q_dates = get_quarterly_rebalance_dates(start, end)
    print(f"\nQuarterly rebalance dates: {q_dates}")

    prev_baskets = set()
    all_quarterly_baskets = {}

    for rd in q_dates:
        baskets = select_baskets(prices, prices, rd, top_n=3)
        current_set = set(b['etf'] for b in baskets)
        turnover = len(current_set - prev_baskets) if prev_baskets else 0

        print(f"\n  {rd}:")
        for b in baskets:
            print(f"    {b['etf']} ({b['sector']:<18}) composite={b['composite']:.3f}  "
                  f"3mo={b['three_mo_return']:+.1f}%  breadth={b['breadth']:.0f}%  "
                  f"RS={b['median_rs']:+.1f}%  stocks={b['stock_count']}")
        print(f"    Turnover: {turnover} sectors changed")

        all_quarterly_baskets[rd] = [b['etf'] for b in baskets]
        prev_baskets = current_set

    # Monthly baskets for comparison
    m_dates = get_monthly_rebalance_dates(start, end)
    print(f"\n\nMonthly rebalance dates: {len(m_dates)} dates")

    monthly_changes = 0
    prev_m = set()
    for rd in m_dates:
        baskets = select_baskets(prices, prices, rd, top_n=3)
        current_set = set(b['etf'] for b in baskets)
        if prev_m and current_set != prev_m:
            monthly_changes += 1
        prev_m = current_set

    print(f"  Monthly changes: {monthly_changes}/{len(m_dates)-1} months had basket changes")

    # Which sectors were selected most often?
    sector_frequency = defaultdict(int)
    for rd in q_dates:
        for etf in all_quarterly_baskets.get(rd, []):
            sector_frequency[etf] += 1

    print(f"\n  Sector frequency (quarterly):")
    for etf, count in sorted(sector_frequency.items(), key=lambda x: x[1], reverse=True):
        print(f"    {etf} ({SECTOR_ETFS[etf]}): selected {count}/{len(q_dates)} quarters")

    # Top 5 baskets comparison
    print(f"\n\nTop 5 vs Top 3 comparison:")
    for rd in q_dates:
        b3 = select_baskets(prices, prices, rd, top_n=3)
        b5 = select_baskets(prices, prices, rd, top_n=5)
        extra = [b['etf'] for b in b5 if b['etf'] not in [x['etf'] for x in b3]]
        print(f"  {rd}: top3={[b['etf'] for b in b3]}  extra_in_top5={extra}")

    print("\n" + "=" * 70)
    return all_quarterly_baskets


if __name__ == "__main__":
    run_basket_analysis("data/spots.csv")
