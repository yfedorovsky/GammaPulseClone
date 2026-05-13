"""Alert tag taxonomy — Fidget-style structural labels.

P0.8 (2026-05-12). Fidget's unusual-activity feed shows 3-5 short tags
per alert (WHALE / PREM $XM / LEAPS / MULTI-LEG / MONTHLY / WEEKLY /
CROSS / SINGLE-LEG) that summarize the structural character of each
trade. Tags are visual taxonomy — same notional-spike alert is easier
to scan when you can immediately see "WHALE LEAPS MULTI-LEG" vs
"WHALE WEEKLY SINGLE-LEG".

All tags computable from existing fields. Caller passes an alert dict
(flow / basket / spike) and gets back a list of human-readable tags.

Tag definitions:
  WHALE        — premium >= $5M
  PREM $XM     — premium tier (rounded down to nearest $5M jump)
  LEAPS        — expiration > 200 DTE
  MONTHLY      — 3rd Friday expiration in 30-200 DTE range
  WEEKLY       — non-3rd-Friday expiration <= 30 DTE
  ZERO-DTE     — expiration is today
  MULTI-LEG    — sweep across 5+ exchanges OR basket with 5+ strikes
  SINGLE-LEG   — single venue (block trade, not split)
  ITM          — strike inside spot
  ATM          — strike within 2% of spot
  OTM-FAR      — strike > 10% from spot
  EARNINGS     — within 14 days of next earnings
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable


def _dte(expiration: str, today: _dt.date | None = None) -> int:
    """Calendar days from today to expiration ('YYYY-MM-DD')."""
    try:
        d = _dt.date.fromisoformat(expiration)
    except (ValueError, TypeError):
        return 99999
    return (d - (today or _dt.date.today())).days


def _is_third_friday(expiration: str) -> bool:
    try:
        d = _dt.date.fromisoformat(expiration)
    except (ValueError, TypeError):
        return False
    return d.weekday() == 4 and 15 <= d.day <= 21


def _premium_tag(notional: float) -> str | None:
    """Round premium DOWN to the most informative tier label."""
    if notional >= 100_000_000:
        return "PREM $100M+"
    if notional >= 50_000_000:
        return "PREM $50M+"
    if notional >= 25_000_000:
        return "PREM $25M+"
    if notional >= 10_000_000:
        return "PREM $10M+"
    if notional >= 5_000_000:
        return "PREM $5M+"
    if notional >= 1_000_000:
        return "PREM $1M+"
    return None


def _tenor_tag(expiration: str, today: _dt.date | None = None) -> str | None:
    dte = _dte(expiration, today)
    if dte <= 0:
        return "0DTE"
    if dte > 200:
        return "LEAPS"
    if 30 < dte <= 200 and _is_third_friday(expiration):
        return "MONTHLY"
    if dte <= 30 and not _is_third_friday(expiration):
        return "WEEKLY"
    if 30 < dte <= 200:
        return "MID-TERM"
    return None


def _moneyness_tag(strike: float, spot: float, option_type: str) -> str | None:
    if not spot or spot <= 0 or strike <= 0:
        return None
    pct = (strike - spot) / spot
    abs_pct = abs(pct)
    if abs_pct <= 0.02:
        return "ATM"
    # For calls: strike > spot = OTM; strike < spot = ITM
    # For puts:  strike < spot = OTM; strike > spot = ITM
    otype = (option_type or "").lower()
    if otype == "call":
        if pct < 0:
            return "DEEP-ITM" if abs_pct >= 0.10 else "ITM"
        return "OTM-FAR" if abs_pct >= 0.10 else "OTM"
    if otype == "put":
        if pct > 0:
            return "DEEP-ITM" if abs_pct >= 0.10 else "ITM"
        return "OTM-FAR" if abs_pct >= 0.10 else "OTM"
    return None


def tags_for_flow_alert(alert: dict[str, Any]) -> list[str]:
    """Tags for a single-strike flow_alert."""
    out: list[str] = []
    notional = float(alert.get("notional") or 0.0)
    if notional >= 5_000_000:
        out.append("WHALE")
    p = _premium_tag(notional)
    if p:
        out.append(p)
    exp = alert.get("expiration", "")
    t = _tenor_tag(exp)
    if t:
        out.append(t)
    if alert.get("is_sweep") or (alert.get("sweep_venues") or 0) >= 5:
        out.append("MULTI-LEG")
    elif alert.get("sweep_contracts") and (alert.get("sweep_venues") or 0) == 1:
        out.append("SINGLE-LEG")
    mt = _moneyness_tag(
        float(alert.get("strike") or 0.0),
        float(alert.get("spot") or 0.0),
        alert.get("option_type", ""),
    )
    if mt:
        out.append(mt)
    return out


def tags_for_basket(basket: dict[str, Any]) -> list[str]:
    """Tags for a multi-strike basket alert."""
    out: list[str] = []
    notional = float(basket.get("aggregate_notional") or 0.0)
    if notional >= 5_000_000:
        out.append("WHALE")
    p = _premium_tag(notional)
    if p:
        out.append(p)
    exp = basket.get("expiration", "")
    t = _tenor_tag(exp)
    if t:
        out.append(t)
    # Multi-strike basket is by definition multi-leg
    out.append("MULTI-LEG")
    # If most strikes are OTM-FAR, tag the basket as OTM-FAR
    spot = float(basket.get("spot") or 0.0)
    otype = basket.get("option_type", "")
    strikes = basket.get("strikes", []) or []
    if spot and strikes:
        moneyness = [
            _moneyness_tag(float(s.get("strike", 0)), spot, otype)
            for s in strikes
        ]
        moneyness = [m for m in moneyness if m]
        if moneyness:
            # Pick the most common
            from collections import Counter
            most = Counter(moneyness).most_common(1)[0][0]
            out.append(most)
    return out


def tags_for_spike(spike: dict[str, Any]) -> list[str]:
    """Tags for an intraday spike alert."""
    out: list[str] = []
    notional = float(spike.get("bucket_notional") or 0.0)
    if notional >= 5_000_000:
        out.append("WHALE")
    p = _premium_tag(notional)
    if p:
        out.append(p)
    # SPIKE-grade tiers
    r = float(spike.get("ratio") or 0.0)
    if r >= 100:
        out.append("EXTREME")
    elif r >= 50:
        out.append("MAJOR")
    elif r >= 25:
        out.append("STRONG")
    return out


def format_tags(tags: Iterable[str]) -> str:
    """Render tags as bracket-padded inline text for Telegram.

    Example: '[WHALE] [LEAPS] [MULTI-LEG]'
    """
    return "  ".join(f"<code>{t}</code>" for t in tags)
