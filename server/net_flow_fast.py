"""Fast-tick NetFlow aggregator for 0DTE alerting on index tickers.

Extends `net_flow.py` (which does 1-min bars on 17 tickers for structural
reads) with a SEPARATE aggregator for SPY/SPX/QQQ/IWM that bins into
10-second bars. Purpose: drive 0DTE confluence alerts that need sub-minute
freshness.

## Why a separate aggregator (not a flag on the existing one)

The existing `NetFlowAggregator` produces 1-min bars that feed the
NetFlow tab UI and the `run_net_flow_alert_loop` regime detector.
Changing its cadence would:
  1. Break backward compatibility with the UI (1-min bars assumed)
  2. Explode memory (10s × 24h × 17 tickers = 147K bars vs 24K for 1min)
  3. Not be needed for most tickers (only indexes get scalp-relevant 0DTE
     flow at sub-minute granularity)

Cleaner: keep the main aggregator at 1-min. Add this tight fast-tick
aggregator targeted at just the 4 index tickers we run 0DTE alerts on.

## Configuration

- BAR_SECONDS = 10 (6 bars/min, 360 bars/hour, 8,640 bars/24h)
- ROC_WINDOW_BARS = 12 (2 minutes of lookback for rate-of-change)
- FAST_TICKERS = ('SPY', 'SPX', 'SPXW', 'QQQ', 'IWM')

Bars retained: 1 hour (360) — sufficient for 2-min ROC plus some baseline
for percentile ranking. No need for 24h on fast-tick aggregator.

## Sign convention

Identical to `net_flow.py`:
  NCP = call_buy_notional − call_sell_notional   (bullish positioning)
  NPP = put_buy_notional  − put_sell_notional    (bearish positioning)

Shipped 2026-04-22 overnight (0DTE alert engine).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from .cache import cache
from .thetadata import EXCLUDE_CONDITIONS, NON_ISO_AUCTION_CONDITIONS, ThetaTrade


# ── Configuration ─────────────────────────────────────────────────

FAST_TICKERS: tuple[str, ...] = ("SPY", "SPX", "SPXW", "QQQ", "IWM")
BAR_SECONDS = 10
BARS_RETAINED = 360  # 1 hour of 10s bars
ROC_WINDOW_BARS = 12  # 2-minute rate-of-change window
STALL_CONFIRM_BARS = 3  # 30-second stall confirmation


# ── Data structures ───────────────────────────────────────────────


@dataclass
class FastBar:
    """10-second bin of net-flow data for 0DTE alerting."""
    t: int                    # bar-close epoch seconds (end of 10s window)
    price: float | None = None
    ncp: float = 0.0
    npp: float = 0.0
    call_buy_notional: float = 0.0
    call_sell_notional: float = 0.0
    put_buy_notional: float = 0.0
    put_sell_notional: float = 0.0
    call_trade_count: int = 0
    put_trade_count: int = 0

    def to_row(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "price": self.price,
            "ncp": round(self.ncp, 2),
            "npp": round(self.npp, 2),
            "signed_vol": round(self.ncp + self.npp, 2),
            "call_trades": self.call_trade_count,
            "put_trades": self.put_trade_count,
        }


# ── Aggregator ────────────────────────────────────────────────────


class FastTickNetFlowAggregator:
    """10-second-bin per-ticker NCP/NPP tracker for 0DTE alerting.

    Maintained alongside the main NetFlowAggregator; both receive every
    trade via live_flow_aggregator's hot path. Fast aggregator only
    processes trades for FAST_TICKERS (gate in add_trade), so it's
    cheaper per trade than the broader 1-min aggregator.
    """

    def __init__(self):
        # ticker → deque of closed FastBar (maxlen = BARS_RETAINED)
        self._history: dict[str, deque[FastBar]] = {}
        # ticker → in-progress bar
        self._current: dict[str, FastBar] = {}
        # Telemetry
        self.trades_seen = 0
        self.trades_tracked = 0
        self.trades_skipped_not_fast_ticker = 0
        self.bars_rotated = 0

    # ── Bar timing ────────────────────────────────────────────────

    @staticmethod
    def _bar_close_epoch(ts: float) -> int:
        """Return the epoch seconds of the CLOSE of the current 10s bar.

        Bar close = next multiple of BAR_SECONDS. e.g. at ts=103.4 with
        BAR_SECONDS=10, close = 110.
        """
        sec = int(ts)
        return (sec // BAR_SECONDS + 1) * BAR_SECONDS

    # ── Trade ingestion ──────────────────────────────────────────

    @staticmethod
    def _should_track(ticker: str) -> bool:
        return ticker.upper() in FAST_TICKERS

    def add_trade(self, trade: ThetaTrade) -> None:
        """Fold a trade into the current 10s bar. Fast-path gating."""
        self.trades_seen += 1

        if trade.condition in EXCLUDE_CONDITIONS:
            return
        if trade.condition in NON_ISO_AUCTION_CONDITIONS:
            return

        ticker = (trade.ticker or "").upper()
        if not self._should_track(ticker):
            self.trades_skipped_not_fast_ticker += 1
            return

        side = trade.side
        if side == "NEUTRAL":
            return

        notional = trade.notional
        if notional <= 0:
            return

        bar = self._get_or_create_current(ticker)
        right = (trade.right or "").lower()
        if right == "call":
            bar.call_trade_count += 1
            if side == "BUY":
                bar.call_buy_notional += notional
                bar.ncp += notional
            else:
                bar.call_sell_notional += notional
                bar.ncp -= notional
        elif right == "put":
            bar.put_trade_count += 1
            if side == "BUY":
                bar.put_buy_notional += notional
                bar.npp += notional
            else:
                bar.put_sell_notional += notional
                bar.npp -= notional
        else:
            return

        self.trades_tracked += 1

    def _get_or_create_current(self, ticker: str) -> FastBar:
        bar = self._current.get(ticker)
        close_epoch = self._bar_close_epoch(time.time())
        if bar is None:
            new_bar = FastBar(t=close_epoch)
            self._current[ticker] = new_bar
            return new_bar
        if bar.t < close_epoch:
            # rotate
            self._history.setdefault(ticker, deque(maxlen=BARS_RETAINED)).append(bar)
            self.bars_rotated += 1
            new_bar = FastBar(t=close_epoch)
            self._current[ticker] = new_bar
            return new_bar
        return bar

    # ── Async housekeeping (price backfill) ──────────────────────

    async def backfill_prices(self) -> None:
        """Grab spot from worker cache and patch any None-priced bars."""
        try:
            snap = await cache.snapshot()
        except Exception:
            return
        for ticker in FAST_TICKERS:
            state = snap.get(ticker) or {}
            spot = state.get("actual_spot") or state.get("spot") or state.get("_spot")
            if not spot:
                continue
            spot = float(spot)
            # Patch current bar
            cur = self._current.get(ticker)
            if cur is not None and cur.price is None:
                cur.price = spot
            # Patch recent history (walk back until priced)
            hist = self._history.get(ticker) or deque()
            for bar in reversed(hist):
                if bar.price is None:
                    bar.price = spot
                else:
                    break

    # ── Query API ────────────────────────────────────────────────

    def series(self, ticker: str, bars: int = BARS_RETAINED) -> list[FastBar]:
        """Return the last N bars (oldest → newest), including current."""
        ticker = ticker.upper()
        hist = self._history.get(ticker) or deque()
        tail = list(hist)[-bars:]
        cur = self._current.get(ticker)
        if cur is not None and (cur.call_trade_count + cur.put_trade_count) > 0:
            tail.append(cur)
        return tail

    def stats(self) -> dict[str, Any]:
        return {
            "trades_seen": self.trades_seen,
            "trades_tracked": self.trades_tracked,
            "trades_skipped_not_fast_ticker": self.trades_skipped_not_fast_ticker,
            "bars_rotated": self.bars_rotated,
            "fast_tickers": list(FAST_TICKERS),
            "tickers_active": len(self._history),
            "bar_seconds": BAR_SECONDS,
            "bars_retained": BARS_RETAINED,
        }


# ── Fast-tick signal detector ─────────────────────────────────────


def fast_roc(bars: list[FastBar], field: str, window: int = ROC_WINDOW_BARS) -> float:
    """Rate-of-change over the last `window` bars for one field.

    For 'price' returns % change. For ncp/npp returns dollar change.
    """
    if len(bars) < window + 1:
        return 0.0
    newest = bars[-1]
    older = bars[-window - 1]
    new_v = getattr(newest, field, None)
    old_v = getattr(older, field, None)
    if new_v is None or old_v is None:
        return 0.0
    if field == "price":
        if old_v == 0:
            return 0.0
        return (new_v - old_v) / old_v * 100.0
    return new_v - old_v


@dataclass
class FastFlowSnapshot:
    """Compact snapshot of fast-tick flow state for the confluence engine."""
    ticker: str
    price: float | None
    price_roc_2min_pct: float
    ncp_roc_2min_dollars: float
    npp_roc_2min_dollars: float
    bullish_strength: float   # 0-1 normalized
    bearish_strength: float   # 0-1 normalized
    # Fresh burst detection — last 30s of flow signed
    burst_signed_30s: float
    burst_call_notional_30s: float
    burst_put_notional_30s: float
    # Stall indicator
    is_stalled: bool

    def to_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "price_roc_2min_pct": round(self.price_roc_2min_pct, 3),
            "ncp_roc_2min_m": round(self.ncp_roc_2min_dollars / 1e6, 3),
            "npp_roc_2min_m": round(self.npp_roc_2min_dollars / 1e6, 3),
            "bullish_strength": round(self.bullish_strength, 2),
            "bearish_strength": round(self.bearish_strength, 2),
            "burst_signed_30s_k": round(self.burst_signed_30s / 1e3, 1),
            "burst_call_k": round(self.burst_call_notional_30s / 1e3, 1),
            "burst_put_k": round(self.burst_put_notional_30s / 1e3, 1),
            "is_stalled": self.is_stalled,
        }


def snapshot_fast_flow(
    aggregator: FastTickNetFlowAggregator, ticker: str
) -> FastFlowSnapshot | None:
    """Produce a compact fast-flow snapshot for the confluence engine."""
    bars = aggregator.series(ticker)
    if len(bars) < ROC_WINDOW_BARS + 1:
        return None

    latest = bars[-1]
    price_roc = fast_roc(bars, "price")
    ncp_roc = fast_roc(bars, "ncp")
    npp_roc = fast_roc(bars, "npp")

    # Bullish strength: NCP rising rapidly OR NPP falling rapidly
    # Normalize to 0-1 using absolute-dollar bucket thresholds.
    # $500K/2min = moderate, $2M/2min = strong, $5M+ = extreme
    def _normalize_premium_roc(roc: float) -> float:
        if roc <= 0:
            return 0.0
        if roc < 500_000:
            return roc / 500_000 * 0.33   # 0-0.33 range
        if roc < 2_000_000:
            return 0.33 + (roc - 500_000) / 1_500_000 * 0.33  # 0.33-0.66
        if roc < 5_000_000:
            return 0.66 + (roc - 2_000_000) / 3_000_000 * 0.34  # 0.66-1.0
        return 1.0

    bullish_strength = max(
        _normalize_premium_roc(ncp_roc),
        _normalize_premium_roc(-npp_roc),  # NPP falling = bullish
    )
    bearish_strength = max(
        _normalize_premium_roc(-ncp_roc),  # NCP falling = bearish
        _normalize_premium_roc(npp_roc),   # NPP rising = bearish
    )

    # Last 3 bars (30s) as "burst" — recent hot flow
    recent_3 = bars[-3:]
    burst_call = sum((b.call_buy_notional - b.call_sell_notional) for b in recent_3)
    burst_put = sum((b.put_buy_notional - b.put_sell_notional) for b in recent_3)
    burst_signed = burst_call - burst_put  # + = bullish, − = bearish

    # Stall: last STALL_CONFIRM_BARS have minimal ncp/npp change
    is_stalled = False
    if len(bars) >= STALL_CONFIRM_BARS:
        recent_stall = bars[-STALL_CONFIRM_BARS:]
        total_activity = sum(
            abs(b.ncp) + abs(b.npp) for b in recent_stall
        )
        # Threshold: < $100K of ANY directional flow over the stall window
        if total_activity < 100_000:
            is_stalled = True

    return FastFlowSnapshot(
        ticker=ticker.upper(),
        price=latest.price,
        price_roc_2min_pct=price_roc,
        ncp_roc_2min_dollars=ncp_roc,
        npp_roc_2min_dollars=npp_roc,
        bullish_strength=bullish_strength,
        bearish_strength=bearish_strength,
        burst_signed_30s=burst_signed,
        burst_call_notional_30s=burst_call,
        burst_put_notional_30s=burst_put,
        is_stalled=is_stalled,
    )


# ── Singleton + rotation loop ────────────────────────────────────


_fast_aggregator: FastTickNetFlowAggregator | None = None


def get_fast_net_flow_aggregator() -> FastTickNetFlowAggregator:
    global _fast_aggregator
    if _fast_aggregator is None:
        _fast_aggregator = FastTickNetFlowAggregator()
    return _fast_aggregator


async def run_fast_net_flow_loop(stop_event: asyncio.Event) -> None:
    """Periodic housekeeping for fast-tick aggregator.

    - Every 2 seconds: backfill prices from worker cache
    - Heartbeat every 30s (15 cycles)
    """
    agg = get_fast_net_flow_aggregator()
    print(
        f"[net_flow_fast] rotation loop starting — bar={BAR_SECONDS}s retained={BARS_RETAINED} "
        f"tickers={FAST_TICKERS}"
    )
    cycles = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
            break
        except asyncio.TimeoutError:
            pass
        try:
            await agg.backfill_prices()
            cycles += 1
            if cycles % 15 == 0:
                print(f"[net_flow_fast] heartbeat — {agg.stats()}")
        except Exception as e:  # noqa: BLE001
            print(f"[net_flow_fast] loop error: {e}")
    print("[net_flow_fast] rotation loop stopped")
