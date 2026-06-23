"""Stale-spot circuit-breaker (cross-LLM audit 2026-06-23 — Gemini's one concrete,
correct prescription, verified against the docs as a real gap).

When the underlying spot feeding an alert is FROZEN — the documented DIA-stuck-6h
class of bug, flagged by snapshots._check_stale when 4+ identical spot writes span
>2 min during RTH — every distance-from-spot and GEX-alignment calc on that alert
is built on a dead price. The opening drive is exactly when this bites and exactly
when a confident-but-false alert does the most damage. This breaker tags such
alerts and (when activated) demotes their urgency so the human doesn't act on a
signal built on a frozen tape.

SHADOW BY DEFAULT (env STALE_GUARD_ACTIVE unset/0): tag + log only, notch_delta=0
— ZERO behaviour change until validated, per the no-architectural-change-until-
validated discipline. Mirrors the structure-gate shadow pattern already wired in
flow_alerts.py. Flip STALE_GUARD_ACTIVE=1 to actually demote stale-spot alerts.

Staleness affects EVERY alert equally (frozen data is frozen data), so — unlike
the structure gate — whale/INFORMED alerts are NOT exempt: a whale print priced
off a dead spot is just as misleading.
"""
from __future__ import annotations

import os
from typing import Any, Callable

DEMOTE_NOTCHES = 1


def _active() -> bool:
    return os.getenv("STALE_GUARD_ACTIVE", "0").strip().lower() in ("1", "true", "yes", "on")


def evaluate_stale(ticker: str,
                   fetcher: Callable[[str], int] | None = None) -> dict[str, Any]:
    """Decision for one alert's ticker. Returns:
      {stale: bool, tag: str|None, reason: str, notch_delta: int}
    notch_delta is 0 in shadow mode (changes nothing) and -DEMOTE_NOTCHES when
    STALE_GUARD_ACTIVE=1. `fetcher(ticker) -> 0/1` is injectable for tests;
    defaults to snapshots.is_latest_stale. Fail-soft: any error → not stale."""
    try:
        if fetcher is None:
            from .snapshots import is_latest_stale as fetcher  # type: ignore
        stale = bool(fetcher(ticker))
    except Exception:
        stale = False
    if not stale:
        return {"stale": False, "tag": None, "reason": "", "notch_delta": 0}
    return {
        "stale": True,
        "tag": "stale-spot",
        "reason": f"{ticker} spot frozen (stale snapshot) — distance/GEX calcs unreliable",
        "notch_delta": -DEMOTE_NOTCHES if _active() else 0,
    }


def stale_banner() -> str:
    """Telegram banner for a stale-spot alert (used when the guard is active)."""
    return "⚠️ STALE SPOT — price feed frozen; verify the quote before acting"
