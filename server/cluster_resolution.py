"""MIXED → RESOLUTION alert tracker.

When a MIXED-bias cluster gets muted from Telegram, remember it for 15 min.
If within that window another cluster on the same ticker fires with
single-direction bias (BULLISH/BEARISH), that's a RESOLUTION — the
ambiguity resolved into directional flow. This is one of the highest-EV
patterns per Perplexity's evaluation: "When a mixed cluster resolves to
single-direction within 15 minutes, that transition is a high-quality
signal."

Shipped 2026-05-20.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


# Configuration
RESOLUTION_WINDOW_SEC = 15 * 60   # 15-minute window
RESOLUTION_MIN_LEGS_NEW = 5       # new cluster must be at least 5 legs
RESOLUTION_MIN_NOTIONAL = 50_000_000  # new cluster must be >=$50M


@dataclass
class MixedClusterRecord:
    """Snapshot of a muted MIXED cluster, kept for resolution detection."""
    ticker: str
    fired_at: float
    bias: str            # MIXED, MIXED-BULL, or MIXED-BEAR
    notional: float
    legs: int
    bull_legs: int
    bear_legs: int
    spot: float | None


# Per-ticker most-recent muted-MIXED record
_pending: dict[str, MixedClusterRecord] = {}


def remember_mixed(ticker: str, summary: dict[str, Any]) -> None:
    """Called from flow_alert_filter when a MIXED cluster gets muted.
    Records it for RESOLUTION detection within RESOLUTION_WINDOW_SEC."""
    _pending[ticker] = MixedClusterRecord(
        ticker=ticker,
        fired_at=time.time(),
        bias=summary.get("bias", "MIXED"),
        notional=float(summary.get("total_notional") or 0),
        legs=int(summary.get("legs") or 0),
        bull_legs=int(summary.get("bullish_legs") or 0),
        bear_legs=int(summary.get("bearish_legs") or 0),
        spot=summary.get("spot"),
    )


def check_resolution(
    ticker: str, new_summary: dict[str, Any]
) -> dict[str, Any] | None:
    """Called when a NEW cluster summary is about to fire for this ticker.
    If it's a single-direction bias following a recent MIXED record, build
    a RESOLUTION payload and return it. Otherwise None.
    """
    rec = _pending.get(ticker)
    if rec is None:
        return None

    age = time.time() - rec.fired_at
    if age > RESOLUTION_WINDOW_SEC:
        _pending.pop(ticker, None)
        return None

    new_bias = new_summary.get("bias", "")
    if new_bias not in ("BULLISH", "BEARISH"):
        return None  # still mixed

    new_legs = new_summary.get("legs", 0)
    new_notional = new_summary.get("total_notional", 0)
    if new_legs < RESOLUTION_MIN_LEGS_NEW or new_notional < RESOLUTION_MIN_NOTIONAL:
        return None  # not enough volume to qualify the resolution

    # Resolution detected — clear the pending state + build payload
    _pending.pop(ticker, None)

    return {
        "kind": "CLUSTER_RESOLUTION",
        "ticker": ticker,
        "resolution_direction": new_bias,
        "from_bias": rec.bias,
        "age_min": age / 60,
        "prior_notional": rec.notional,
        "prior_legs": rec.legs,
        "prior_bull": rec.bull_legs,
        "prior_bear": rec.bear_legs,
        "new_notional": new_notional,
        "new_legs": new_legs,
        "spot": new_summary.get("spot"),
        "first_ts": new_summary.get("first_ts"),
        "last_ts": new_summary.get("last_ts"),
    }


def format_resolution_telegram(payload: dict[str, Any]) -> str:
    """Telegram format for a CLUSTER_RESOLUTION alert."""
    direction = payload.get("resolution_direction", "")
    emoji = "🟢" if direction == "BULLISH" else "🔴"
    ticker = payload.get("ticker", "?")
    spot = payload.get("spot", 0) or 0
    from_bias = payload.get("from_bias", "?")
    age_min = payload.get("age_min", 0)
    prior_m = payload.get("prior_notional", 0) / 1e6
    new_m = payload.get("new_notional", 0) / 1e6
    return (
        f"⚡ <b>CLUSTER RESOLUTION — {ticker}</b>\n"
        f"\n"
        f"{emoji} Resolved {from_bias} → <b>{direction}</b>\n"
        f"Spot: ${spot:.2f}\n"
        f"\n"
        f"Prior ({from_bias}, {age_min:.1f}min ago): "
        f"${prior_m:.0f}M, {payload.get('prior_bull', 0)}B / {payload.get('prior_bear', 0)}B\n"
        f"Now ({direction}): ${new_m:.0f}M, {payload.get('new_legs', 0)} legs\n"
        f"\n"
        f"<i>High-EV pattern: ambiguity → conviction in &lt;15min.</i>"
    )
