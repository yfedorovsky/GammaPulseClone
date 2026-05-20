"""Earnings calendar — per-ticker next-ER lookup for Telegram badges.

P0.7 fix (2026-05-12). Fidget surfaces "Earnings: May 20" on every TGT/NVDA
alert so the operator immediately sees catalyst context. We have the data
source (Finnhub) wired in main.py but use it only as a one-shot API
endpoint; this module caches it for badge use across all alert formatters.

Source: Finnhub `/calendar/earnings` (matches existing main.py integration).
Cache: 24h per ticker (earnings dates don't change intraday).
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any

import httpx

from .config import get_settings


CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
LOOKAHEAD_DAYS = 60   # how far forward to query
WINDOW_DAYS = 14      # show badge if ER is within this many days

# ticker -> (fetch_ts, next_er_date | None)
_cache: dict[str, tuple[float, _dt.date | None]] = {}


async def _fetch_next_er(ticker: str) -> _dt.date | None:
    """Hit Finnhub for the next earnings date within LOOKAHEAD_DAYS."""
    s = get_settings()
    if not s.finnhub_api_key:
        return None
    today = _dt.date.today()
    end = today + _dt.timedelta(days=LOOKAHEAD_DAYS)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "symbol": ticker.upper(),
                    "token": s.finnhub_api_key,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            dates: list[_dt.date] = []
            for ec in data.get("earningsCalendar", []) or []:
                if ec.get("symbol", "").upper() != ticker.upper():
                    continue
                ds = ec.get("date")
                if not ds:
                    continue
                try:
                    d = _dt.date.fromisoformat(ds)
                except ValueError:
                    continue
                if d >= today:
                    dates.append(d)
            if dates:
                return min(dates)
    except Exception as e:
        print(f"[EARNINGS] fetch failed for {ticker}: {e}")
    return None


async def get_next_er(ticker: str) -> _dt.date | None:
    """Return the next earnings date for `ticker`, or None.

    Cached for 24h. Returns None on network failure / missing API key /
    no upcoming earnings within LOOKAHEAD_DAYS.
    """
    now = time.time()
    cached = _cache.get(ticker.upper())
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    er = await _fetch_next_er(ticker)
    _cache[ticker.upper()] = (now, er)
    return er


async def earnings_badge(ticker: str) -> str | None:
    """Return a one-line earnings badge for Telegram, or None.

    Format: "🔔 ER: May 20 (8d)"

    Only fires when the next earnings date is within WINDOW_DAYS to keep
    alerts focused — a 45-DTE ER tag adds noise on Tier-1 names that
    always have an ER pending.
    """
    er = await get_next_er(ticker)
    if er is None:
        return None
    today = _dt.date.today()
    dte = (er - today).days
    if dte < 0 or dte > WINDOW_DAYS:
        return None
    label = er.strftime("%b %d")
    if dte == 0:
        return f"🔔 ER TODAY ({label})"
    if dte == 1:
        return f"🔔 ER TOMORROW ({label})"
    return f"🔔 ER: {label} ({dte}d)"


def earnings_badge_sync(ticker: str) -> str | None:
    """Sync variant that ONLY reads cache (no network call).

    Used by code paths that aren't async, like the leaderboard formatter
    which is called inline from already-async contexts but can't await on
    every ticker without N round-trips per fire.
    """
    cached = _cache.get(ticker.upper())
    if not cached:
        return None
    er = cached[1]
    if er is None:
        return None
    today = _dt.date.today()
    dte = (er - today).days
    if dte < 0 or dte > WINDOW_DAYS:
        return None
    label = er.strftime("%b %d")
    if dte == 0:
        return f"🔔 ER TODAY ({label})"
    if dte == 1:
        return f"🔔 ER TOMORROW ({label})"
    return f"🔔 ER: {label} ({dte}d)"


# Earnings-in-window check for multi-day alert gating (added 2026-05-20
# per Perplexity recommendation #2 — IV crush gate). Returns:
#   (earnings_in_window: bool, days_to_er: int | None)
def er_in_window_sync(ticker: str, dte: int) -> tuple[bool, int | None]:
    """Sync check: does an earnings announcement fall WITHIN the option's
    DTE window? Returns (in_window, days_to_er) where in_window=True means
    the contract spans the ER date — IV crush risk.

    Reads from the same async cache as earnings_badge_sync. Returns
    (False, None) if cache is cold (no false positives).
    """
    cached = _cache.get(ticker.upper())
    if not cached:
        return False, None
    er = cached[1]
    if er is None:
        return False, None
    today = _dt.date.today()
    days_to = (er - today).days
    if days_to < 0:
        return False, None  # past earnings
    if days_to <= dte:
        return True, days_to
    return False, days_to


def er_blocks_long_premium(ticker: str, dte: int) -> tuple[bool, str | None]:
    """Should a long-premium (call/put BUY) alert be blocked because of
    earnings in window?

    Rule: block when ER is within DTE AND DTE >= 2 (we want to avoid
    holding through ER for IV crush; 0DTE/1DTE on ER day is a different
    play and not gated here).

    Returns (block: bool, reason: str | None).
    """
    in_window, days_to = er_in_window_sync(ticker, dte)
    if not in_window:
        return False, None
    if dte < 2:
        return False, None  # 0DTE/1DTE on ER day is a different setup
    return True, f"ER in {days_to}d (within {dte}-day DTE) — IV crush risk"
