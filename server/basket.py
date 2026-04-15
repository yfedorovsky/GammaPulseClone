"""Point-in-Time Quarterly Basket Selector — Live Engine.

Adapts backtest/basket_selector.py for the live signal engine.
Uses Tradier daily history + snapshot data instead of CSV files.

Computes quarterly basket on startup and caches for 3 months.
No mid-quarter changes (frozen spec v1.0).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from .config import get_settings
from .snapshots import get_daily_closes

# SPDR Sector ETFs — same as backtest
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

# Stock-to-sector mapping — same as backtest/basket_selector.py
STOCK_SECTORS = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "AMD": "XLK",
    "INTC": "XLK", "MU": "XLK", "MRVL": "XLK", "TSM": "XLK", "AMAT": "XLK",
    "LRCX": "XLK", "ANET": "XLK", "COHR": "XLK", "LITE": "XLK", "AAOI": "XLK",
    "GLW": "XLK", "CIEN": "XLK", "TSEM": "XLK", "AXTI": "XLK", "NET": "XLK",
    "SNOW": "XLK", "PLTR": "XLK", "VRT": "XLI",
    "TSLA": "XLY", "AMZN": "XLY",
    "META": "XLC", "GOOGL": "XLC",
    "RKLB": "XLI", "ASTS": "XLC",
    "SATL": "XLI", "VOYG": "XLI",
    "AEHR": "XLK", "TER": "XLK", "KLAC": "XLK",
    "WDC": "XLK", "NBIS": "XLK", "OKLO": "XLU", "IREN": "XLK",
    "SNDK": "XLK", "SMH": None, "SPY": None, "QQQ": None, "IWM": None,
}


def _percentile_rank(values: list[float]) -> list[float]:
    if not values:
        return []
    n = len(values)
    sorted_vals = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank, (idx, _) in enumerate(sorted_vals):
        ranks[idx] = rank / max(n - 1, 1)
    return ranks


def _get_quarter_start(d: date) -> date:
    """Get the start date of the current quarter."""
    quarter_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, quarter_month, 1)


async def _fetch_etf_daily(ticker: str, days: int = 90) -> list[float]:
    """Fetch daily closes for a sector ETF from Tradier."""
    import httpx

    s = get_settings()
    if not s.tradier_token:
        return []

    start = (date.today() - timedelta(days=days + 30)).isoformat()  # extra buffer
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{s.tradier_base_url}/markets/history",
                params={"symbol": ticker, "interval": "daily", "start": start},
                headers={
                    "Authorization": f"Bearer {s.tradier_token}",
                    "Accept": "application/json",
                },
            )
            if r.status_code != 200:
                return []
            bars = (r.json().get("history") or {}).get("day") or []
            if isinstance(bars, dict):
                bars = [bars]
            return [b["close"] for b in bars if b.get("close")]
    except Exception as e:
        print(f"[BASKET] ETF fetch error ({ticker}): {e}")
        return []


async def compute_live_basket(top_n: int = 3) -> dict[str, Any]:
    """Compute the current quarterly basket using live data.

    Returns {
        'sectors': ['XLK', 'XLI', 'XLC'],
        'tickers': {'AAOI', 'MU', 'ANET', ...},
        'scores': [...],
        'computed_at': '2026-04-15',
        'quarter': 'Q2 2026',
        'valid_until': '2026-07-01',
    }
    """
    import asyncio

    today = date.today()
    quarter_start = _get_quarter_start(today)
    quarter_num = (today.month - 1) // 3 + 1

    print(f"[BASKET] Computing Q{quarter_num} {today.year} basket...")

    # Fetch sector ETF daily closes (11 API calls, once per quarter)
    etf_closes: dict[str, list[float]] = {}
    tasks = {etf: _fetch_etf_daily(etf, days=90) for etf in SECTOR_ETFS}
    results = await asyncio.gather(*tasks.values())
    for etf, closes in zip(tasks.keys(), results):
        if closes:
            etf_closes[etf] = closes

    # Get SPY for RS baseline
    spy_closes = get_daily_closes("SPY", days=100)

    scores = []
    for etf, sector_name in SECTOR_ETFS.items():
        closes = etf_closes.get(etf, [])
        if len(closes) < 63:
            continue

        # 1. 3-month ETF return
        three_mo_return = (closes[-1] - closes[-63]) / closes[-63] * 100

        # 2. Breadth: % of sector members above 50-day MA
        sector_stocks = [s for s, sec in STOCK_SECTORS.items() if sec == etf]
        above_50ma = 0
        total_stocks = 0
        for stock in sector_stocks:
            stock_closes = get_daily_closes(stock, days=60)
            if len(stock_closes) < 50:
                continue
            total_stocks += 1
            current = stock_closes[-1]
            ma_50 = sum(stock_closes[-50:]) / 50
            if current > ma_50:
                above_50ma += 1
        breadth = (above_50ma / total_stocks * 100) if total_stocks > 0 else 0

        # 3. Median RS: median 20d return of sector members vs SPY
        spy_20d_ret = 0
        if len(spy_closes) >= 20:
            spy_20d_ret = (spy_closes[-1] - spy_closes[-20]) / spy_closes[-20] * 100

        rs_values = []
        for stock in sector_stocks:
            stock_closes = get_daily_closes(stock, days=30)
            if len(stock_closes) >= 20:
                stock_ret = (stock_closes[-1] - stock_closes[-20]) / stock_closes[-20] * 100
                rs_values.append(stock_ret - spy_20d_ret)

        median_rs = sorted(rs_values)[len(rs_values) // 2] if rs_values else 0

        scores.append({
            "etf": etf,
            "sector": sector_name,
            "three_mo_return": round(three_mo_return, 1),
            "breadth": round(breadth, 0),
            "median_rs": round(median_rs, 1),
            "stock_count": total_stocks,
        })

    if not scores:
        print("[BASKET] WARNING: No sector scores computed — using XLK fallback")
        return {
            "sectors": ["XLK"],
            "tickers": {s for s, sec in STOCK_SECTORS.items() if sec == "XLK"},
            "scores": [],
            "computed_at": today.isoformat(),
            "quarter": f"Q{quarter_num} {today.year}",
            "valid_until": _next_quarter_start(today).isoformat(),
        }

    # Percentile-rank each component
    returns = [s["three_mo_return"] for s in scores]
    breadths = [s["breadth"] for s in scores]
    rs_vals = [s["median_rs"] for s in scores]

    ret_ranks = _percentile_rank(returns)
    brd_ranks = _percentile_rank(breadths)
    rs_ranks = _percentile_rank(rs_vals)

    for i, s in enumerate(scores):
        s["composite"] = round(
            0.4 * ret_ranks[i] + 0.3 * brd_ranks[i] + 0.3 * rs_ranks[i], 3
        )

    scores.sort(key=lambda s: s["composite"], reverse=True)
    selected = scores[:top_n]
    selected_etfs = [s["etf"] for s in selected]

    # Map to individual stocks
    active_tickers = set()
    for stock, sector in STOCK_SECTORS.items():
        if sector in selected_etfs:
            active_tickers.add(stock)

    valid_until = _next_quarter_start(today)

    print(f"[BASKET] Q{quarter_num} {today.year} basket: {selected_etfs}")
    for s in selected:
        print(f"  {s['etf']} ({s['sector']}): composite={s['composite']:.3f} "
              f"3mo={s['three_mo_return']:+.1f}% breadth={s['breadth']:.0f}% "
              f"RS={s['median_rs']:+.1f}%")
    print(f"[BASKET] {len(active_tickers)} tickers active until {valid_until}")

    return {
        "sectors": selected_etfs,
        "tickers": active_tickers,
        "scores": selected,
        "computed_at": today.isoformat(),
        "quarter": f"Q{quarter_num} {today.year}",
        "valid_until": valid_until.isoformat(),
    }


def _next_quarter_start(d: date) -> date:
    """Get the start of the next quarter."""
    quarter_month = ((d.month - 1) // 3) * 3 + 1
    if quarter_month + 3 > 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, quarter_month + 3, 1)


# ── Cached basket (refreshed quarterly) ─────────────────────────────

_basket_cache: dict[str, Any] | None = None
_basket_cache_ts: float = 0


async def get_active_basket() -> dict[str, Any]:
    """Get the current quarterly basket, computing if needed."""
    global _basket_cache, _basket_cache_ts

    today = date.today().isoformat()

    # Return cached if still valid
    if _basket_cache:
        if today < _basket_cache.get("valid_until", ""):
            return _basket_cache
        # Quarter boundary crossed — recompute
        print(f"[BASKET] Quarter boundary crossed — recomputing")

    _basket_cache = await compute_live_basket(top_n=3)
    _basket_cache_ts = time.time()
    return _basket_cache


def get_basket_tickers() -> set[str]:
    """Synchronous accessor for the current basket tickers.

    Returns empty set if basket hasn't been computed yet.
    Used by worker.py for fast ticker filtering.
    """
    if _basket_cache:
        return _basket_cache.get("tickers", set())
    return set()


def get_basket_info() -> dict[str, Any] | None:
    """Get full basket info for API/UI display."""
    return _basket_cache
