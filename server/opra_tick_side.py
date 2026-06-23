"""Sub-second OPRA tick-side — scaffold for #77 (the audit's #1 data priority).

The cross-LLM audit hammered the side-detection weakness (~10% tape-inverted /
~80% no-clear-aggressor on the snapshot path). tick_side_tracker already gives the
30-min AGGREGATE side; this complements it with the SUB-SECOND instantaneous read:
the aggressor of the trade(s) in the last ~2s, classified against the NBBO at trade
time. That's the freshest possible `side` at the moment an alert fires — strictly
better than the snapshot last-vs-NBBO guess and fresher than a 30-min average.

This module is the SCAFFOLD: the hard, testable parts — correct aggressor
classification (the quote rule / Lee-Ready) + per-contract recency state — are built
and unit-tested here. The remaining integration is one wire: feed `record()` from the
ThetaData WS trade handler (sweep_detector already consumes that stream) and let the
flow detectors prefer `recent_side()` over the snapshot fallback. PRO-tier 20K-contract
coverage is a subscription/stream-scope change, not a logic change.

Pure + dependency-free; safe to import anywhere.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

# How far back a trade counts as "now" for the instantaneous read.
DEFAULT_MAX_AGE_S = 2.0
# Cap per-contract ring so a hot contract can't grow unbounded.
_RING = 64

BUY, SELL, MID = "BUY", "SELL", "MID"


def classify_aggressor(price: float, bid: float | None, ask: float | None) -> str:
    """Quote-rule aggressor of a single trade against the prevailing NBBO.
      price >= ask   -> BUY  (lifted the offer)
      price <= bid   -> SELL (hit the bid)
      between        -> nearer side of the mid; exactly mid -> MID (indeterminate)
    Returns BUY / SELL / MID. Missing/crossed quotes -> MID."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return MID
    b = float(bid) if bid not in (None, "") else 0.0
    a = float(ask) if ask not in (None, "") else 0.0
    if a > 0 and price >= a:
        return BUY
    if b > 0 and price <= b:
        return SELL
    if b > 0 and a > 0 and a >= b:
        mid = (a + b) / 2.0
        if price > mid:
            return BUY
        if price < mid:
            return SELL
    return MID


def contract_key(ticker: str, strike: float, expiration: str, option_type: str) -> tuple:
    return ((ticker or "").upper(), float(strike), str(expiration),
            (option_type or "").lower()[:1])  # 'c'/'p'


class SubSecondSideTracker:
    """Per-contract ring of recent (ts, side, size). Thread-safe. `record()` is
    cheap; `recent_side()` nets BUY vs SELL size within max_age_s."""

    def __init__(self) -> None:
        self._rings: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=_RING))
        self._lock = threading.Lock()

    def record(self, key: tuple, price: float, bid: float | None, ask: float | None,
               size: int = 1, ts: float | None = None) -> str:
        """Classify a trade and store it. Returns the classified side."""
        side = classify_aggressor(price, bid, ask)
        t = ts if ts is not None else time.time()
        with self._lock:
            self._rings[key].append((t, side, int(size or 1)))
        return side

    def recent_side(self, key: tuple, now: float | None = None,
                    max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any] | None:
        """Instantaneous side over the last max_age_s. Returns
        {side, confidence (0-1, |net|/total), buy_size, sell_size, n, age_s} or
        None if there is no qualifying recent trade."""
        t = now if now is not None else time.time()
        cutoff = t - max_age_s
        with self._lock:
            ring = list(self._rings.get(key, ()))
        recent = [(ts, sd, sz) for (ts, sd, sz) in ring if ts >= cutoff]
        if not recent:
            return None
        buy = sum(sz for (_t, sd, sz) in recent if sd == BUY)
        sell = sum(sz for (_t, sd, sz) in recent if sd == SELL)
        total = buy + sell
        if total == 0:
            return {"side": MID, "confidence": 0.0, "buy_size": 0, "sell_size": 0,
                    "n": len(recent), "age_s": round(t - recent[-1][0], 3)}
        net = buy - sell
        side = BUY if net > 0 else (SELL if net < 0 else MID)
        return {"side": side, "confidence": round(abs(net) / total, 3),
                "buy_size": buy, "sell_size": sell, "n": len(recent),
                "age_s": round(t - recent[-1][0], 3)}

    def prune(self, older_than_s: float = 300.0, now: float | None = None) -> int:
        """Drop contracts with no trade in older_than_s. Returns rings removed."""
        t = now if now is not None else time.time()
        with self._lock:
            dead = [k for k, ring in self._rings.items()
                    if not ring or ring[-1][0] < t - older_than_s]
            for k in dead:
                del self._rings[k]
        return len(dead)


_tracker: SubSecondSideTracker | None = None


def get_subsecond_tracker() -> SubSecondSideTracker:
    global _tracker
    if _tracker is None:
        _tracker = SubSecondSideTracker()
    return _tracker
