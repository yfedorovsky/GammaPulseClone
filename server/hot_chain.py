"""Hot-chain expansion state — defense in depth (P2, 2026-05-13).

When a ticker prints a high-notional flow_alert in a single scan cycle,
mark it "hot" for a TTL window. Hot tickers get:

  1. Wider expiration coverage in worker._fetch_chain_cached
     (max_exp bumped by HOT_CHAIN_MAX_EXP_BUMP).
  2. Lower volume / notional gates in flow_alerts._process
     (vol floor lowered, notional floors lowered) so adjacent strikes
     riding the same wave clear the threshold.

This is *defense in depth* — the resume brief's motivating example
(MU $1030C miss) was already fixed on 5/12 by lowering the vol floor
500→200 and the notional floor $5M→$2M. The current chain endpoint
already returns all listed strikes (verified 5/13 probe). What this
buys us is graceful coverage when a NEW whale appears on a parabolic
name: catching the secondary / leg / follow-on prints that historically
sat just under the threshold.

State is process-local (in-memory dict). Hot status survives a single
scan cycle but is forgotten on restart — deliberate, so we don't carry
yesterday's heat into a fresh morning.

The "is this hot" check is the only thing called in the hot path
(flow_alerts gate loop, runs per contract per cycle), so keep it
allocation-free.
"""
from __future__ import annotations

import time

# Config — tunable via env if needed later.
HOT_CHAIN_NOTIONAL_THRESHOLD = 1_000_000  # $1M+ alert on a ticker marks it hot
HOT_CHAIN_TTL_SECONDS = 1800              # 30 min after last trigger
HOT_CHAIN_MAX_EXP_BUMP = 4                # +4 expirations when hot

# Lowered gate values for hot tickers (vs. defaults in flow_alerts.py).
HOT_VOL_FLOOR = 100                       # vs 200 normal
HOT_NOTIONAL_FLOOR_LOW = 500_000          # vs 1M normal (vol<500 path)
HOT_NOTIONAL_FLOOR_HIGH = 1_000_000       # vs 2M normal (V/OI fallback path)

# State.
_hot_ttl: dict[str, float] = {}        # ticker -> expiry unix ts
_last_marked_notional: dict[str, int] = {}  # ticker -> last triggering notional


def mark_hot(ticker: str, notional: float) -> None:
    """Mark a ticker hot if its alert notional clears the threshold.

    Called from flow_alerts after a qualifying alert is inserted. Cheap
    no-op below threshold so callers can pass every notional without
    branching.
    """
    if notional < HOT_CHAIN_NOTIONAL_THRESHOLD:
        return
    if not ticker:
        return
    _hot_ttl[ticker] = time.time() + HOT_CHAIN_TTL_SECONDS
    _last_marked_notional[ticker] = int(notional)


def is_hot(ticker: str) -> bool:
    """True iff `ticker` has had a $1M+ alert in the last 30 min.

    Side-effect: expires stale entries lazily so the dict doesn't grow.
    """
    expiry = _hot_ttl.get(ticker, 0.0)
    if expiry == 0.0:
        return False
    if time.time() > expiry:
        _hot_ttl.pop(ticker, None)
        _last_marked_notional.pop(ticker, None)
        return False
    return True


def hot_snapshot() -> list[tuple[str, float, int]]:
    """Diagnostic: return [(ticker, seconds_remaining, last_notional), ...].

    Used by ad-hoc REPL / status endpoints. Not called in the hot path.
    """
    now = time.time()
    out: list[tuple[str, float, int]] = []
    for ticker, expiry in list(_hot_ttl.items()):
        remaining = expiry - now
        if remaining <= 0:
            _hot_ttl.pop(ticker, None)
            _last_marked_notional.pop(ticker, None)
            continue
        out.append((ticker, remaining, _last_marked_notional.get(ticker, 0)))
    out.sort(key=lambda t: -t[1])  # most-recently-marked first
    return out


def clear_all() -> None:
    """Tests / manual override only. Not used in production paths."""
    _hot_ttl.clear()
    _last_marked_notional.clear()
