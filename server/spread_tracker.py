"""Live spread tracker for the structural-turn shadow-mode spread gate.

Polls Tradier `/markets/quotes` every POLL_INTERVAL_SEC for each ticker
in WATCH_LIST, maintains a per-ticker deque of (ts, bid, ask) samples
covering the last WINDOW_MIN minutes, and exposes get_spread_30m_mean()
for the structural-turn evaluator.

Designed for SHADOW MODE per cross-LLM round-3 consensus
(docs/feedback/cross_llm_implementation_review_may01.md):

  - The spread gate is logged but does NOT block production fires
  - Every structural-turn evaluation gets `spread_30m_mean` recorded
  - `would_gate_spread` is logged as a separate column for post-hoc
    "with-gate" cohort simulation in the bootstrap analysis
  - Avoids tail-truncation bias that would attenuate the spread
    coefficient in the eventual logistic regression

Why a separate module: the live structural-turn loop runs at 60s
cadence and can't afford a synchronous quote pull on its critical
path. The spread tracker runs independently every 30s and the
evaluator just reads from its in-memory state.

Usage:
    tracker = SpreadTracker(["SPY", "QQQ", "IWM"])
    asyncio.create_task(tracker.run(stop_event))
    ...
    spread_30m = tracker.get_spread_30m_mean("SPY")  # may be None
"""
from __future__ import annotations

import asyncio
import time as _time
from collections import deque
from typing import Iterable

from .tradier import TradierClient


# Poll cadence — 30s gives us ~60 samples in a 30-min window per ticker,
# fast enough to react to spread regime changes within minutes.
POLL_INTERVAL_SEC = 30

# Rolling window for spread averaging — matches the "30m trailing mean
# spread" metric used by Test #6 and the static-historical-p90 thresholds
# in docs/research/background_distributions.md.
WINDOW_MIN = 30
WINDOW_SEC = WINDOW_MIN * 60

# Cap deque length defensively — at 30s cadence we get 60 samples per
# 30 min window. 200 covers any clock jitter / brief slow polls.
DEQUE_MAXLEN = 200


class SpreadTracker:
    """Per-ticker rolling NBBO spread tracker.

    Stores (ts, bid, ask, spread) tuples in a deque; on read, drops
    samples older than WINDOW_SEC and returns the mean spread of the
    remainder. None when:
      - the deque is empty (warm-up)
      - all stored samples have aged out
      - the most recent sample is > 5 min old (Tradier outage)
    """

    def __init__(self, tickers: Iterable[str]) -> None:
        self.tickers: list[str] = list(tickers)
        self._samples: dict[str, deque[tuple[int, float, float, float]]] = {
            t: deque(maxlen=DEQUE_MAXLEN) for t in self.tickers
        }
        self._client: TradierClient | None = None
        self._last_poll_ts: int = 0

    # ── Public read API ─────────────────────────────────────────────

    def get_spread_30m_mean(self, ticker: str) -> float | None:
        """Mean stock NBBO spread over the trailing 30-min window.

        Returns None if insufficient or stale data (callers should
        treat None as "gate dormant" — proceed with the fire).
        """
        dq = self._samples.get(ticker)
        if not dq:
            return None
        now = int(_time.time())
        cutoff = now - WINDOW_SEC

        # Drop stale samples from the left of the deque
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        if not dq:
            return None

        # If the most recent sample is older than 5 min, the feed is
        # likely down — return None rather than a stale mean
        if now - dq[-1][0] > 300:
            return None

        spreads = [s[3] for s in dq if s[3] > 0]
        if not spreads:
            return None
        return sum(spreads) / len(spreads)

    def get_latest_spread(self, ticker: str) -> float | None:
        """Most recent single-sample spread (for diagnostics)."""
        dq = self._samples.get(ticker)
        if not dq:
            return None
        return dq[-1][3]

    def n_samples(self, ticker: str) -> int:
        return len(self._samples.get(ticker) or [])

    def last_poll_age_sec(self) -> int:
        if self._last_poll_ts == 0:
            return -1
        return int(_time.time()) - self._last_poll_ts

    # ── Polling loop ────────────────────────────────────────────────

    async def _poll_once(self) -> int:
        """One Tradier batch pull + sample append. Returns # samples added."""
        if self._client is None:
            self._client = TradierClient()
        try:
            quotes = await self._client.quotes_full(self.tickers)
        except Exception as e:
            print(f"[spread_tracker] poll failed: {type(e).__name__}: {e}",
                  flush=True)
            return 0

        now = int(_time.time())
        added = 0
        for ticker in self.tickers:
            q = quotes.get(ticker)
            if not q:
                continue
            bid = q.get("bid")
            ask = q.get("ask")
            if bid is None or ask is None:
                continue
            try:
                bid_f = float(bid)
                ask_f = float(ask)
            except (TypeError, ValueError):
                continue
            # Reject obviously bad quotes (locked / crossed / pre-market
            # zero-spread placeholders). Spread gate threshold table is
            # populated from RTH samples only.
            if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f:
                continue
            spread = ask_f - bid_f
            self._samples[ticker].append((now, bid_f, ask_f, spread))
            added += 1
        self._last_poll_ts = now
        return added

    async def run(self, stop_event: asyncio.Event) -> None:
        """Background loop. Polls every POLL_INTERVAL_SEC during RTH.

        Skips polling outside US market hours (rough check — ET hour
        and weekday only; finer-grained holiday calendar lives elsewhere
        in the codebase and isn't worth duplicating here).
        """
        print(f"[spread_tracker] starting — tickers={self.tickers}, "
              f"interval={POLL_INTERVAL_SEC}s, window={WINDOW_MIN}min",
              flush=True)
        try:
            while not stop_event.is_set():
                # Skip outside RTH (rough: ET 09:30–16:00 weekdays)
                from datetime import datetime as _dt
                try:
                    import pytz
                    ny = _dt.now(pytz.timezone("America/New_York"))
                except Exception:
                    ny = _dt.utcnow()
                in_rth = (ny.weekday() < 5
                          and ((ny.hour == 9 and ny.minute >= 30)
                               or (10 <= ny.hour < 16)))
                if in_rth:
                    try:
                        await self._poll_once()
                    except Exception as e:
                        print(f"[spread_tracker] poll error: "
                              f"{type(e).__name__}: {e}", flush=True)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=POLL_INTERVAL_SEC,
                    )
                    break
                except asyncio.TimeoutError:
                    continue
        finally:
            if self._client is not None:
                try:
                    await self._client.close()
                except Exception:
                    pass
            print("[spread_tracker] stopped", flush=True)


# ── Module-level singleton (set by the live worker on startup) ──────

_TRACKER: SpreadTracker | None = None


def set_global_tracker(tracker: SpreadTracker) -> None:
    """Live worker calls this once at startup so structural_turn.py can
    look up spreads via the module-level helper without threading the
    tracker instance through every call site."""
    global _TRACKER
    _TRACKER = tracker


def get_spread_30m_mean(ticker: str) -> float | None:
    """Module-level lookup for evaluate_turn(). None if no tracker is
    registered (e.g., backtest runs, tests) — gate stays dormant."""
    if _TRACKER is None:
        return None
    return _TRACKER.get_spread_30m_mean(ticker)
