"""Tick-level ASK-vs-BID volume tracker for option flow side classification.

Replaces the snapshot-based _detect_side in flow_alerts.py for contracts
that have recent OPRA tick coverage. Returns None when a bucket is too thin
to be authoritative — caller falls back to the snapshot detector.

Why this exists:
  flow_alerts._detect_side reads `last` from the 30s chain snapshot. After a
  big ASK-side institutional print, retail follow-up prints land mid-bid,
  `last` settles to mid, and we tag MID/BID. Real example (2026-05-08):
  INTC 5/15 $120C had $5M+ ASK-side buying around 11:30 AM but our system
  tagged BEARISH BID at 10:16 AM and never re-evaluated.

  The OPRA tick stream (server/sweep_detector.py + server/thetadata.py)
  already attaches the pre-trade NBBO to every ThetaTrade via
  ThetaStream._attach_nbbo. classify_side(price, bid, ask) returns
  BUY/SELL/NEUTRAL strictly from price vs the NBBO at print time. We just
  keep a rolling 60s window of (size, side) per contract and report which
  side dominates.

Sweep detector remains the canonical aggressor classifier for ISO sweeps;
this tracker generalizes the idea to ALL (non-excluded, non-auction) trades
for the broader flow scanner.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from .thetadata import ThetaTrade


# Window and threshold tuning (Bug #2 fix, 2026-05-12).
#
# Symptom: GLD 6/18 $380C tagged BID BEARISH all afternoon despite FL0WG0D
# and Bullflow.io confirming massive ASK-side call buying. QCOM 6/18 $270C
# tagged MID NEUTRAL despite 75% ASK fills. Both contracts had thin OPRA
# bucket sizes (well under the 50-contract floor) so the snapshot fallback
# took over — and snapshot side detection on late-day ITM/wide-spread
# contracts is unreliable because `last` lags the quote.
#
# Fix:
#   1. Lower MIN_WINDOW_SIZE 50 -> 20 so smaller-but-real buckets count.
#   2. Soften DOMINANCE_RATIO 1.5 -> 1.3 so a 130:100 split still classifies.
# The fallback_rate is logged in TickSideTracker.stats() — audit weekly to
# confirm we didn't trade accuracy for noise.
WINDOW_SECONDS = 60.0
MIN_WINDOW_SIZE = 20  # was 50; relaxed 2026-05-12
DOMINANCE_RATIO = 1.3  # was 1.5; relaxed 2026-05-12
MAX_TRADES_PER_BUCKET = 200

# (ticker_upper, strike_float, exp_str, right_lower)
BucketKey = tuple[str, float, str, str]


@dataclass
class _Bucket:
    trades: Deque[tuple[float, int, str]] = field(
        default_factory=lambda: deque(maxlen=MAX_TRADES_PER_BUCKET)
    )
    ask_vol: int = 0
    bid_vol: int = 0
    mid_vol: int = 0

    @property
    def total_size(self) -> int:
        return self.ask_vol + self.bid_vol + self.mid_vol

    def add(self, ts: float, size: int, side: str) -> None:
        # If maxlen is full, the next append silently evicts trades[0].
        # Decrement counters for the evictee first so totals stay consistent.
        if self.trades.maxlen is not None and len(self.trades) == self.trades.maxlen:
            _, old_size, old_side = self.trades[0]
            self._dec(old_size, old_side)
        self.trades.append((ts, size, side))
        self._inc(size, side)

    def prune(self, cutoff: float) -> None:
        while self.trades and self.trades[0][0] < cutoff:
            _, old_size, old_side = self.trades.popleft()
            self._dec(old_size, old_side)

    def _inc(self, size: int, side: str) -> None:
        if side == "ASK":
            self.ask_vol += size
        elif side == "BID":
            self.bid_vol += size
        else:
            self.mid_vol += size

    def _dec(self, size: int, side: str) -> None:
        if side == "ASK":
            self.ask_vol -= size
        elif side == "BID":
            self.bid_vol -= size
        else:
            self.mid_vol -= size


class TickSideTracker:
    """Per-contract rolling 60s window of ASK/BID/MID-classified trade volume.

    add_trade() is called from the sweep_detector consume loop for every
    qualifying (non-excluded, non-auction) trade. latest_side() is called
    from the 30s flow scanner — returns None when the bucket is too thin
    to be authoritative (caller falls back to snapshot-based _detect_side).
    """

    def __init__(self) -> None:
        self._buckets: dict[BucketKey, _Bucket] = {}
        self.trades_seen = 0
        self.lookups = 0
        self.fallback_triggered = 0

    @staticmethod
    def _key(
        ticker: str, strike: float, expiration: str, right: str,
    ) -> BucketKey:
        # ThetaTrade.right is 'call'/'put'; flow_alerts otype is 'call'/'put';
        # SubscribeSpec uses 'C'/'P'. Normalize all of them.
        r = right.lower()
        if r == "c":
            r = "call"
        elif r == "p":
            r = "put"
        return (ticker.upper(), float(strike), str(expiration), r)

    def add_trade(self, trade: ThetaTrade) -> None:
        side_raw = trade.side  # 'BUY'/'SELL'/'NEUTRAL' from classify_side
        if side_raw == "BUY":
            side = "ASK"
        elif side_raw == "SELL":
            side = "BID"
        else:
            side = "MID"
        key = self._key(trade.ticker, trade.strike, trade.expiration, trade.right)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket()
            self._buckets[key] = bucket
        bucket.add(time.time(), trade.size, side)
        self.trades_seen += 1

    def latest_side(
        self, ticker: str, strike: float, expiration: str, right: str,
    ) -> str | None:
        """Return 'ASK' / 'BID' / 'MID' from the rolling 60s window, or None
        if the window has fewer than MIN_WINDOW_SIZE contracts. None tells
        the caller to fall back to the legacy snapshot detector."""
        self.lookups += 1
        key = self._key(ticker, strike, expiration, right)
        bucket = self._buckets.get(key)
        if bucket is None:
            self.fallback_triggered += 1
            return None
        bucket.prune(time.time() - WINDOW_SECONDS)
        if bucket.total_size < MIN_WINDOW_SIZE:
            self.fallback_triggered += 1
            return None
        # max(_, 1) guards the dominance ratio when the opposite side is zero.
        if bucket.ask_vol > DOMINANCE_RATIO * max(bucket.bid_vol, 1):
            return "ASK"
        if bucket.bid_vol > DOMINANCE_RATIO * max(bucket.ask_vol, 1):
            return "BID"
        return "MID"

    def prune_all(self) -> None:
        """Drop empty buckets and prune stale ticks from active ones. Called
        from the sweep_detector heartbeat to bound memory growth."""
        cutoff = time.time() - WINDOW_SECONDS
        empty: list[BucketKey] = []
        for key, bucket in self._buckets.items():
            bucket.prune(cutoff)
            if bucket.total_size == 0:
                empty.append(key)
        for k in empty:
            del self._buckets[k]

    def stats(self) -> dict[str, object]:
        active = [
            (k, b.total_size, b.ask_vol, b.bid_vol)
            for k, b in self._buckets.items() if b.total_size > 0
        ]
        active.sort(key=lambda x: x[1], reverse=True)
        top = [
            f"{k[0]} {k[1]:g}{k[3][0].upper()}/{k[2]} sz={sz} a={a} b={b}"
            for k, sz, a, b in active[:5]
        ]
        rate = self.fallback_triggered / self.lookups if self.lookups else 0.0
        return {
            "tracked_contracts": len(active),
            "trades_seen": self.trades_seen,
            "lookups": self.lookups,
            "fallback_rate": round(rate, 3),
            "top_active": top,
        }


_tracker: TickSideTracker | None = None


def get_tracker() -> TickSideTracker:
    """Module-level singleton. flow_alerts imports this directly to avoid
    threading a tracker reference through the lifespan plumbing."""
    global _tracker
    if _tracker is None:
        _tracker = TickSideTracker()
    return _tracker
