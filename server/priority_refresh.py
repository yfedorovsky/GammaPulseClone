"""Priority fast-lane refresh for heavily-watched tickers.

The main worker (server/worker.py) cycles all ~200 tickers every 2-3 min.
For intraday index/mega-cap watching (e.g. SPX heatmap during market hours),
that cadence is too slow — the "ball" on the wall lags the actual spot by
minutes.

This module spawns a parallel async task that refreshes a small fixed set
of priority tickers every N seconds using the SAME code paths as the main
worker (_compute_one + cache.put), just on a tighter cadence. Heatmap and
KING/floor/ceiling stay consistent with the normal flow; only the refresh
rate changes.

Design:
  - ISOLATED from the main worker (own TradierClient, own task loop)
  - Failures here CANNOT impact the main scan cycle
  - Feature-flagged via PRIORITY_REFRESH_ENABLED (kill switch)
  - Per-ticker error count + skip-after-N-failures safety (prevents
    infinite-loop-of-errors hot path if an API breaks)
  - Adaptive pacing: if one cycle takes longer than the target interval,
    the next one starts immediately (no negative sleep)

Rollout: start with SPX only. After 1-2 sessions of validation, expand to
SPY / QQQ / IWM. Expand beyond that only after observing cache / API /
memory behavior under steady state.

Shipped: 2026-04-21 (Tuesday intraday, low-risk introduction while market
was slow and blast radius minimal).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .cache import cache
from .config import get_settings
from .tickers import tier_of
from .tradier import TradierClient
from .worker import _compute_one


# ── Configuration ──────────────────────────────────────────────────
# KILL SWITCH: flip to False to disable the loop entirely without a
# code change to main.py. Takes effect at next backend restart.
PRIORITY_REFRESH_ENABLED = True

# Which tickers get priority refresh. Keep this list small — every entry
# multiplies API calls. Candidates beyond SPX: SPY, QQQ, IWM, NDX, RUT.
# Start with SPX only and expand after validation.
PRIORITY_TICKERS: tuple[str, ...] = ("SPX",)

# Target refresh interval in seconds. If a cycle takes LONGER than this
# (chain fetch + greeks + GEX compute), the next cycle starts immediately
# with zero sleep (the refresh rate degrades gracefully to "as fast as
# possible" rather than piling up overlapping cycles).
#
# Cadence rationale: 15s is 3-6x faster than the main worker (~2min/ticker)
# while staying well inside Tradier + ThetaData rate limits even when we
# scale to 4 tickers (SPX/SPY/QQQ/IWM = 16 req/min vs 48/min at 5s).
# GEX walls don't materially shift faster than ~10min in practice, so 15s
# refresh of KING/floor/ceiling captures all real change without paying
# API cost for redundant identical values.
PRIORITY_INTERVAL_SECONDS = 15

# Safety: if a single ticker fails N times in a row, we stop refreshing it
# for the rest of the session. Prevents a bad ticker from burning API quota.
# Reset on successful refresh.
MAX_CONSECUTIVE_ERRORS = 5


async def run_priority_refresh(stop_event: asyncio.Event) -> None:
    """Refresh PRIORITY_TICKERS every PRIORITY_INTERVAL_SECONDS.

    Uses the same _compute_one + cache.put pipeline as the main worker,
    so heatmap / KING / floor / ceiling values stay identical in shape
    to the rest of the cache. The only difference is refresh rate.

    Writes a `_priority_refresh` marker into state so consumers can tell
    whether a cached row was updated by this fast lane (useful for UI
    visual indicators or debugging).
    """
    if not PRIORITY_REFRESH_ENABLED:
        print("[priority] disabled via PRIORITY_REFRESH_ENABLED=False — task exiting cleanly")
        return

    settings = get_settings()

    # Own our own Tradier client so we don't contend with the worker's
    # connection pool. TradierClient is cheap to instantiate.
    tradier = TradierClient()

    # Match worker's greeks client selection logic. If ThetaData is
    # configured, use it; otherwise fall back to Massive or Tradier-only.
    greeks_client: Any = None
    try:
        if settings.use_thetadata_greeks:
            from .thetadata import ThetaDataClient
            greeks_client = ThetaDataClient()
            print("[priority] using ThetaData for greeks (matched to main worker)")
        elif getattr(settings, "use_massive_greeks", False) and getattr(settings, "massive_api_key", None):
            from .massive import MassiveClient  # type: ignore
            greeks_client = MassiveClient()
            print("[priority] using Massive for greeks (legacy path)")
        else:
            print("[priority] no greeks client configured — Tradier-only greeks")
    except Exception as e:
        print(f"[priority] greeks client init failed, continuing without: {e}")
        greeks_client = None

    error_counts: dict[str, int] = {t: 0 for t in PRIORITY_TICKERS}
    skip_set: set[str] = set()

    print(
        f"[priority] loop starting — tickers={list(PRIORITY_TICKERS)} "
        f"interval={PRIORITY_INTERVAL_SECONDS}s  max_errors={MAX_CONSECUTIVE_ERRORS}"
    )

    cycles_completed = 0
    successful_refreshes = 0

    try:
        while not stop_event.is_set():
            cycle_start = time.monotonic()

            for ticker in PRIORITY_TICKERS:
                if ticker in skip_set:
                    continue
                if stop_event.is_set():
                    break

                try:
                    # Fetch fresh spot + OHLCV in one batched call
                    quotes_full = await tradier.quotes_full([ticker])
                    qf = quotes_full.get(ticker) or {}
                    spot = qf.get("last")
                    if not spot:
                        # Not a hard error — during overnight/pre-market Tradier
                        # may return empty last; don't count toward error budget
                        continue

                    # Full GEX recompute via main worker's _compute_one.
                    # This is the expensive step (chain fetch + greeks + GEX math)
                    # but it keeps priority output identical to normal cycle output.
                    state = await _compute_one(
                        tradier,
                        ticker,
                        spot,
                        max_exp=12 if tier_of(ticker) <= 2 else 6,
                        greeks_client=greeks_client,
                    )
                    if state is None:
                        continue

                    # Match the worker's OHLCV injection pattern so downstream
                    # consumers (swing scanner, runner tracker, frontend) see
                    # the same shape whether the update came from priority lane
                    # or main cycle.
                    state["_today_volume"] = qf.get("volume", 0)
                    state["_avg_volume"] = qf.get("average_volume", 0)
                    state["_today_open"] = qf.get("open")
                    state["_today_high"] = qf.get("high")
                    state["_today_low"] = qf.get("low")
                    state["_prevclose"] = qf.get("prevclose")
                    # Priority-specific markers for debugging / UI
                    state["_priority_refresh"] = True
                    state["_priority_refresh_ts"] = time.time()

                    await cache.put(ticker, state)
                    error_counts[ticker] = 0  # reset on success
                    successful_refreshes += 1

                except Exception as e:  # noqa: BLE001
                    error_counts[ticker] += 1
                    print(
                        f"[priority] {ticker} refresh error "
                        f"({error_counts[ticker]}/{MAX_CONSECUTIVE_ERRORS}): {e!r}"
                    )
                    if error_counts[ticker] >= MAX_CONSECUTIVE_ERRORS:
                        skip_set.add(ticker)
                        print(
                            f"[priority] {ticker} SKIPPED for session after "
                            f"{MAX_CONSECUTIVE_ERRORS} consecutive errors — "
                            f"main worker still covers it at normal cadence"
                        )

            cycles_completed += 1

            # Heartbeat every ~60 seconds (4 cycles at 15s) so we can see
            # in the backend log that this loop is alive and healthy.
            if cycles_completed % 4 == 0:
                print(
                    f"[priority] heartbeat — cycles={cycles_completed} "
                    f"refreshes={successful_refreshes} "
                    f"skip_set={sorted(skip_set) or 'none'}"
                )

            # Adaptive pacing: if compute + API round-trips exceeded the
            # target interval, start the next cycle immediately (remaining=0).
            elapsed = time.monotonic() - cycle_start
            remaining = max(0.0, PRIORITY_INTERVAL_SECONDS - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await tradier.close()
        except Exception:
            pass
        if greeks_client:
            try:
                await greeks_client.close()
            except Exception:
                pass
        print(
            f"[priority] loop stopped — cycles={cycles_completed} "
            f"refreshes={successful_refreshes} skipped={sorted(skip_set)}"
        )
