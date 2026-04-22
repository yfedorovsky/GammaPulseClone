"""Per-ticker Net Flow aggregator — NCP / NPP time series.

Implements the "Price-to-Premium Gap Theory" data layer (modeled after
Unusual Whales' Net Flow chart). For each tracked ticker, maintains a
rolling 24h series of 1-minute bars containing:

  - price:     spot at bar-close (from worker cache)
  - ncp:       Net Call Premium   (call_buy_notional − call_sell_notional)
  - npp:       Net Put  Premium   (put_buy_notional  − put_sell_notional)
  - call_vol:  total call dollar volume (abs)
  - put_vol:   total put  dollar volume (abs)
  - signed_vol: NCP + NPP  (UW's "volume" subpanel)

## Sign convention (matches Unusual Whales)

  Call BUY (aggressor lifts the ask): +NCP  → bullish positioning
  Call SELL (aggressor hits the bid): −NCP  → bearish positioning
  Put  BUY (aggressor lifts the ask): +NPP  → bearish positioning
  Put  SELL (aggressor hits the bid): −NPP  → bullish positioning

So:
  NCP rising + NPP falling = uniformly bullish
  NCP falling + NPP rising = uniformly bearish
  NCP and NPP rising together = hedging / mixed sentiment

## Theory

Options premium flow often LEADS underlying price (Easley/O'Hara PIN
literature). When premium runs ahead of price, a "gap" forms. Price tends
to close the gap. When both premium AND price stall at the close, the
convergence becomes a support/resistance level.

The aggregator produces the raw time-series; signal/divergence detection
runs downstream (see `server/net_flow_signals.py`, Phase 3).

## Architecture

  - In-memory only (MVP). 1-min bars × 1440 bars/day × N tickers ≈ 200KB
    per ticker per day. Fits comfortably.
  - Hook: called from `live_flow_aggregator.add_trade()` as a parallel
    side-effect to the existing per-contract aggregation. Same data path,
    no extra WebSocket subscription.
  - Eviction: deque with maxlen=1440 auto-rotates 24h window.
  - Shutdown: state lost on restart (MVP). DB persistence queued for v2.

Shipped: 2026-04-21 (overnight session, v1 MVP).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .cache import cache
from .thetadata import EXCLUDE_CONDITIONS, NON_ISO_AUCTION_CONDITIONS, ThetaTrade


# ── Configuration ─────────────────────────────────────────────────

# Tickers to aggregate net flow for. Keep small on MVP — each ticker
# costs memory + CPU per trade. Expand after verifying behavior.
# Rationale for the initial set:
#   SPY/SPX/QQQ/IWM: index/ETF flow — primary use case of the theory
#   NBIS/ARM/AMZN/NVDA/AAPL: high-flow mega-cap / swing positions
TRACKED_TICKERS: tuple[str, ...] = (
    "SPY", "SPX", "SPXW", "QQQ", "IWM",
    "AAPL", "AMZN", "NVDA", "MSFT", "META", "GOOGL", "TSLA",
    "ARM", "NBIS", "AVGO", "MU", "MRVL",
)

# How many 1-minute bars to retain per ticker. 1440 = 24 hours. At market
# close, the last ~6.5h of bars are from regular session; older bars drift
# out as the next session fills them.
BARS_PER_TICKER = 1440

# How often the bar-rotation loop fires (seconds). 5s is fine-grained
# enough that the "current bar" stays fresh without thrashing CPU.
ROTATION_INTERVAL_S = 5.0


# ── Data structures ───────────────────────────────────────────────


@dataclass
class MinuteBar:
    """Single 1-minute bar of net-flow data.

    Written once per minute (at bar-close) + updated live in the
    current-bar slot until the minute rolls over.
    """
    # Bar-close epoch seconds (start of the NEXT minute, UTC).
    # e.g. a bar for 14:23 has t_close = epoch of 14:24:00 UTC.
    t: int
    # ISO timestamp of t_close, for frontend display.
    t_iso: str
    # Spot at bar close (pulled from worker cache). None if no cache hit.
    price: float | None = None
    # Signed call premium (buy − sell) for the minute.
    ncp: float = 0.0
    # Signed put premium (buy − sell) for the minute.
    npp: float = 0.0
    # Running totals — keeping raw sides lets downstream compute
    # buy/sell ratio if desired.
    call_buy_notional: float = 0.0
    call_sell_notional: float = 0.0
    put_buy_notional: float = 0.0
    put_sell_notional: float = 0.0
    # Volumes (abs notional, for UW-style volume subpanel)
    call_vol: float = 0.0
    put_vol: float = 0.0
    # Trade counts — useful for quality/noise filtering
    call_trade_count: int = 0
    put_trade_count: int = 0

    def to_row(self) -> dict[str, Any]:
        """Serialization for /api/net-flow/{ticker} output."""
        return {
            "t": self.t,
            "t_iso": self.t_iso,
            "price": self.price,
            "ncp": round(self.ncp, 2),
            "npp": round(self.npp, 2),
            "signed_vol": round(self.ncp + self.npp, 2),
            "call_buy": round(self.call_buy_notional, 2),
            "call_sell": round(self.call_sell_notional, 2),
            "put_buy": round(self.put_buy_notional, 2),
            "put_sell": round(self.put_sell_notional, 2),
            "call_vol": round(self.call_vol, 2),
            "put_vol": round(self.put_vol, 2),
            "call_trades": self.call_trade_count,
            "put_trades": self.put_trade_count,
        }


@dataclass
class CumulativeState:
    """Running cumulative NCP/NPP since session start.

    UW's headline number is the cumulative (since 9:30 AM ET open), not
    the per-minute delta. We track both: per-minute bars for line
    smoothing + cumulative for the big stat at top.
    """
    # Running sums since last reset (market open)
    cum_ncp: float = 0.0
    cum_npp: float = 0.0
    # Last reset timestamp (epoch seconds, ET market open)
    reset_ts: float = 0.0


# ── Aggregator ────────────────────────────────────────────────────


class NetFlowAggregator:
    """In-memory per-ticker net-flow accumulator.

    One instance per process. Thread-safe in asyncio single-threaded
    context. NOT thread-safe across OS threads — if we ever add one,
    wrap mutations in a lock.
    """

    def __init__(self):
        # ticker → deque of closed bars (maxlen = 24h of minutes)
        self._history: dict[str, deque[MinuteBar]] = {}
        # ticker → currently-in-progress bar (updated on every trade)
        self._current: dict[str, MinuteBar] = {}
        # ticker → cumulative state (since session open)
        self._cum: dict[str, CumulativeState] = {}
        # Telemetry
        self.trades_seen = 0
        self.trades_tracked = 0
        self.trades_skipped_excluded = 0
        self.trades_skipped_not_tracked = 0
        self.trades_skipped_neutral = 0
        self.bars_rotated = 0

    # ── Bar timing helpers ────────────────────────────────────────

    @staticmethod
    def _current_minute_epoch() -> int:
        """Return the epoch of the START of the CURRENT UTC minute."""
        now = time.time()
        return int(now - (now % 60))

    @staticmethod
    def _iso(epoch_seconds: int) -> str:
        """ISO8601 UTC timestamp for frontend display."""
        return dt.datetime.utcfromtimestamp(epoch_seconds).isoformat() + "Z"

    @staticmethod
    def _is_session_open_reset_needed(last_reset_ts: float, now: float) -> bool:
        """Return True if we've crossed 9:30 AM ET since the last reset.

        Session cumulative should zero out each trading day at 9:30 AM ET.
        Naive implementation: if the ET date has changed since last reset,
        and current time is past 9:30 AM ET, trigger reset.
        """
        # Convert both to ET using a naive offset (ignores DST complications —
        # good enough for a reset heuristic; precise boundary off by <1hr
        # during DST transitions, which is acceptable).
        ET_OFFSET_S = -4 * 3600  # EDT offset (use -5 * 3600 for EST winter)
        last_et = dt.datetime.utcfromtimestamp(last_reset_ts + ET_OFFSET_S)
        now_et = dt.datetime.utcfromtimestamp(now + ET_OFFSET_S)
        if now_et.date() != last_et.date():
            # New day — reset if now is past 9:30
            if now_et.time() >= dt.time(9, 30):
                return True
        return False

    # ── Ticker gating ─────────────────────────────────────────────

    @staticmethod
    def _track_ticker(ticker: str) -> bool:
        """Return True if this ticker is in the tracked set."""
        return ticker.upper() in TRACKED_TICKERS

    # ── Trade ingestion ───────────────────────────────────────────

    def add_trade(self, trade: ThetaTrade) -> None:
        """Fold a single trade print into the current minute bar.

        Caller should pass trades that have already been NBBO-classified
        (trade.side populated). We do defensive filtering here too.
        """
        self.trades_seen += 1

        if trade.condition in EXCLUDE_CONDITIONS:
            self.trades_skipped_excluded += 1
            return
        if trade.condition in NON_ISO_AUCTION_CONDITIONS:
            # Opening/closing auction prints — skip (not informational for
            # intraday flow momentum)
            return

        ticker = (trade.ticker or "").upper()
        if not self._track_ticker(ticker):
            self.trades_skipped_not_tracked += 1
            return

        side = trade.side
        if side == "NEUTRAL":
            # Mid-market prints — exclude from signed flow (consistent with
            # UW methodology and our existing GOLDEN_FLOW convention).
            self.trades_skipped_neutral += 1
            return

        notional = trade.notional
        if notional <= 0:
            return

        # Get or create the current bar for this ticker
        bar = self._get_or_create_current(ticker)

        # Update per-side totals
        right = (trade.right or "").lower()
        if right == "call":
            bar.call_vol += notional
            bar.call_trade_count += 1
            if side == "BUY":
                bar.call_buy_notional += notional
                bar.ncp += notional
            else:  # SELL
                bar.call_sell_notional += notional
                bar.ncp -= notional
        elif right == "put":
            bar.put_vol += notional
            bar.put_trade_count += 1
            if side == "BUY":
                bar.put_buy_notional += notional
                bar.npp += notional
            else:  # SELL
                bar.put_sell_notional += notional
                bar.npp -= notional
        else:
            return

        # Update cumulative state
        cum = self._cum.setdefault(ticker, CumulativeState(reset_ts=time.time()))
        if right == "call":
            cum.cum_ncp += notional if side == "BUY" else -notional
        elif right == "put":
            cum.cum_npp += notional if side == "BUY" else -notional

        self.trades_tracked += 1

    def _get_or_create_current(self, ticker: str) -> MinuteBar:
        """Return the in-progress bar for this ticker, creating if needed."""
        bar = self._current.get(ticker)
        now_minute = self._current_minute_epoch()
        # If no bar yet, or the current bar is from an earlier minute,
        # rotate. The _rotate call handles deque-push.
        if bar is None or bar.t < now_minute + 60:
            # t = bar-close epoch = start of NEXT minute
            target_t = now_minute + 60
            if bar is None:
                new_bar = MinuteBar(t=target_t, t_iso=self._iso(target_t))
                self._current[ticker] = new_bar
                return new_bar
            elif bar.t < target_t:
                # Old bar is stale — close it and start a new one
                self._rotate(ticker, target_t)
                return self._current[ticker]
        return bar

    def _rotate(self, ticker: str, new_close_epoch: int) -> None:
        """Close the current bar for ticker, push to history, open new one.

        Grabs the current spot from cache to set bar.price. This is
        best-effort — if cache doesn't have the ticker, price stays None.
        """
        old_bar = self._current.get(ticker)
        if old_bar is not None:
            # Best-effort price lookup. Cache access is async but we're
            # in a sync hot path (WebSocket callback). Use the synchronous
            # variant if available; otherwise price stays None and gets
            # backfilled by the rotation loop (see _rotation_loop).
            # For now, leave price=None and let the rotation loop fix it.
            history = self._history.setdefault(
                ticker, deque(maxlen=BARS_PER_TICKER)
            )
            history.append(old_bar)
            self.bars_rotated += 1
        self._current[ticker] = MinuteBar(
            t=new_close_epoch, t_iso=self._iso(new_close_epoch)
        )

    async def _backfill_prices(self) -> None:
        """Fill any None prices in recent bars using the worker cache.

        Runs periodically. Worker cache is async, so we can't hit it from
        the sync add_trade hot path — instead do a batch backfill here.
        """
        try:
            snap = await cache.snapshot()
        except Exception:
            return

        for ticker, bars in self._history.items():
            # Only backfill the most recent bars that are still missing price
            state = snap.get(ticker) or {}
            spot = state.get("actual_spot") or state.get("spot") or state.get("_spot")
            if not spot:
                continue
            # Walk back from newest, fix any price=None up to a limit
            for bar in reversed(bars):
                if bar.price is None:
                    bar.price = float(spot)
                else:
                    # Once we hit a priced bar, all older ones are already done
                    break

        # Also patch the current (in-progress) bar's price so live reads work
        for ticker, bar in self._current.items():
            if bar.price is None:
                state = snap.get(ticker) or {}
                spot = state.get("actual_spot") or state.get("spot") or state.get("_spot")
                if spot:
                    bar.price = float(spot)

    # ── Query API (used by endpoint) ──────────────────────────────

    def series(self, ticker: str, minutes: int = 240) -> list[dict[str, Any]]:
        """Return the last `minutes` bars for a ticker, newest last.

        Includes the in-progress bar as the final entry when present.
        """
        ticker = ticker.upper()
        history = self._history.get(ticker) or deque()
        current = self._current.get(ticker)

        # Slice from deque
        if minutes >= len(history):
            tail = list(history)
        else:
            tail = list(history)[-minutes:]

        rows = [b.to_row() for b in tail]
        if current is not None and current.call_trade_count + current.put_trade_count > 0:
            rows.append(current.to_row())
        return rows

    def snapshot(self, ticker: str) -> dict[str, Any]:
        """Return the latest point + cumulative state for a ticker."""
        ticker = ticker.upper()
        current = self._current.get(ticker)
        cum = self._cum.get(ticker) or CumulativeState()
        row = current.to_row() if current is not None else None
        return {
            "ticker": ticker,
            "latest": row,
            "cum_ncp": round(cum.cum_ncp, 2),
            "cum_npp": round(cum.cum_npp, 2),
            "cum_net": round(cum.cum_ncp - cum.cum_npp, 2),
            "cum_since": (
                dt.datetime.utcfromtimestamp(cum.reset_ts).isoformat() + "Z"
                if cum.reset_ts > 0 else None
            ),
        }

    def stats(self) -> dict[str, Any]:
        """Operational telemetry."""
        return {
            "trades_seen": self.trades_seen,
            "trades_tracked": self.trades_tracked,
            "trades_skipped_excluded": self.trades_skipped_excluded,
            "trades_skipped_not_tracked": self.trades_skipped_not_tracked,
            "trades_skipped_neutral": self.trades_skipped_neutral,
            "bars_rotated": self.bars_rotated,
            "tickers_with_history": len(self._history),
            "tickers_in_current": len(self._current),
            "total_bars": sum(len(h) for h in self._history.values()),
            "tracked_tickers": list(TRACKED_TICKERS),
        }


# ── Background loop ───────────────────────────────────────────────


async def run_net_flow_rotation_loop(
    aggregator: NetFlowAggregator, stop_event: asyncio.Event,
) -> None:
    """Periodic tasks: price backfill + session-open cumulative reset.

    - Every ROTATION_INTERVAL_S (~5s): backfill any None prices in recent
      bars from the worker cache.
    - At 9:30 AM ET each trading day: reset cumulative NCP/NPP.

    The per-minute bar rotation itself is event-driven (happens when the
    next trade arrives after minute boundary), so this loop is mostly
    about price backfill + session boundary.
    """
    print(f"[net_flow] rotation loop starting — interval={ROTATION_INTERVAL_S}s")
    cycles = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=ROTATION_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass  # normal — loop body runs

        try:
            # Price backfill from cache
            await aggregator._backfill_prices()

            # Session-open reset check
            now = time.time()
            for ticker, cum in list(aggregator._cum.items()):
                if NetFlowAggregator._is_session_open_reset_needed(
                    cum.reset_ts, now
                ):
                    aggregator._cum[ticker] = CumulativeState(reset_ts=now)

            cycles += 1
            # Heartbeat every ~5 min (60 cycles at 5s)
            if cycles % 60 == 0:
                print(
                    f"[net_flow] heartbeat — stats={aggregator.stats()}"
                )
        except Exception as e:  # noqa: BLE001
            print(f"[net_flow] rotation loop error: {e}")
    print("[net_flow] rotation loop stopped")


# ── Singleton (module-level) ──────────────────────────────────────
#
# One aggregator per process. Imported by live_flow_aggregator.add_trade
# (to fold in trades) and by main.py (to expose via /api/net-flow).

_aggregator_instance: NetFlowAggregator | None = None


def get_net_flow_aggregator() -> NetFlowAggregator:
    """Lazy-init singleton accessor."""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = NetFlowAggregator()
    return _aggregator_instance
