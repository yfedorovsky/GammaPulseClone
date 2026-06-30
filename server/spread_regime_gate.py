"""Spread/vol-regime gate — the anticipatory SPX scanner's GATE 0 (the one PASS).

FINAL_INTERPRETATION.md Test #6 was the single largest empirical effect in the
whole falsification effort and the ONLY pass: normal-spread days +63% / 40% WR vs
HIGH-spread days -14% / 30% WR — a 77pp win-rate gap. This promotes the classifier
from scripts/spread_regime_audit.py to a LIVE preflight veto: do NOT arm an SPX
setup when the option bid-ask spread is anomalously wide (toxic tape — dealers
backing off, cost-to-trade penalty, vol-without-direction).

Faithful to the audit's methodology: HIGH = the recent (30-min trailing) SPX ATM
option bid-ask spread, as % of mid, exceeds the DAY's OWN p90 (relative, self-
calibrating) once enough intraday samples exist. Early-session (pre-p90) falls
back to a provisional absolute threshold that is FLAGGED for SPX-specific
calibration over the 30-day shadow window.

Pure core (`atm_spread_pct` + `SpreadRegimeTracker`) is unit-testable with injected
spreads + `now`; `check_spread_regime` is the thin live adapter over the cached SPX
chain. The gate only CLASSIFIES — nothing changes until the (shadow-gated)
orchestrator consults `is_high`.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _stats
import time as _time
from typing import Any

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

# ── Pre-committed constants (mirror scripts/spread_regime_audit.py) ──
TRAIL_SEC = 30 * 60          # 30-min trailing window for the "current" spread
MIN_SAMPLES_FOR_P90 = 20     # need a real intraday distribution before trusting p90
HIGH_PCTILE = 90.0           # day-relative HIGH threshold (audit: > day p90)
# Provisional absolute fallback for early session (before MIN_SAMPLES). SPX ATM
# 0DTE spread is typically ~3-7% of mid; toxic >~10%. FLAGGED — recalibrate from
# the real SPX spread distribution accrued during the shadow window.
ABS_FALLBACK_SPREAD_PCT = 0.12


def _et_day(ts: float) -> str:
    d = (_dt.datetime.fromtimestamp(ts, _ET) if _ET
         else _dt.datetime.fromtimestamp(ts))
    return d.date().isoformat()


def _percentile(xs: list[float], q: float) -> float:
    """Linear-interpolation percentile (no numpy dep)."""
    s = sorted(xs)
    if not s:
        return float("nan")
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def atm_spread_pct(contracts: list[dict[str, Any]], spot: float | None) -> float | None:
    """ATM front-expiry option bid-ask spread as a fraction of mid.

    Picks the nearest expiration, the strike closest to spot, and averages the
    ATM call + put spread%% (a straddle proxy, more robust than one leg). Returns
    None if no usable two-sided quote exists."""
    if not contracts or not spot or spot <= 0:
        return None
    exps = [c.get("expiration_date") for c in contracts if c.get("expiration_date")]
    if not exps:
        return None
    front = min(exps)
    legs = [c for c in contracts
            if c.get("expiration_date") == front
            and c.get("strike") and c.get("bid") and c.get("ask")
            and c["bid"] > 0 and c["ask"] > 0 and c["ask"] >= c["bid"]]
    if not legs:
        return None
    atm_strike = min((c["strike"] for c in legs), key=lambda s: abs(s - spot))
    pcts = []
    for c in legs:
        if c["strike"] != atm_strike:
            continue
        mid = (c["bid"] + c["ask"]) / 2.0
        if mid > 0:
            pcts.append((c["ask"] - c["bid"]) / mid)
    return sum(pcts) / len(pcts) if pcts else None


class SpreadRegimeTracker:
    """Per-ET-day rolling buffer of ATM spread%% samples → day-relative HIGH verdict."""

    def __init__(self) -> None:
        self._by_day: dict[str, list[tuple[float, float]]] = {}

    def observe(self, spread_pct: float | None, now: float) -> None:
        if spread_pct is None or spread_pct < 0:
            return
        day = _et_day(now)
        self._by_day.setdefault(day, []).append((float(now), float(spread_pct)))
        # keep only today (the distribution is intraday, day-relative)
        for d in list(self._by_day):
            if d != day:
                del self._by_day[d]

    def assess(self, now: float) -> dict[str, Any]:
        """Verdict for the current moment. is_high=True ⇒ VETO (toxic spread)."""
        buf = self._by_day.get(_et_day(now), [])
        if not buf:
            return {"is_high": None, "n": 0, "confidence": "none", "basis": "no_data"}
        pcts = [p for _, p in buf]
        recent = [p for ts, p in buf if ts >= now - TRAIL_SEC]
        trailing = (sum(recent) / len(recent)) if recent else pcts[-1]
        n = len(pcts)
        if n >= MIN_SAMPLES_FOR_P90:
            p90 = _percentile(pcts, HIGH_PCTILE)
            is_high = trailing > p90
            conf, basis = "high", "day_p90"
        else:
            p90 = None
            is_high = trailing > ABS_FALLBACK_SPREAD_PCT
            conf, basis = "low", "abs_fallback"
        return {
            "is_high": bool(is_high),
            "trailing_30m_pct": round(trailing, 4),
            "day_p50_pct": round(_stats.median(pcts), 4),
            "day_p90_pct": (round(p90, 4) if p90 is not None else None),
            "n": n, "confidence": conf, "basis": basis,
        }


# ── Live adapter (module singleton; the orchestrator calls this) ──
_TRACKER = SpreadRegimeTracker()


def check_spread_regime(spx_state: dict[str, Any] | None,
                        now: float | None = None) -> dict[str, Any]:
    """Read the cached SPX chain, observe the current ATM spread, return the
    regime verdict. is_high=True ⇒ the scanner must NOT arm (GATE 0 veto)."""
    now = now if now is not None else _time.time()
    state = spx_state or {}
    raw = state.get("_raw_contracts") or {}
    contracts = [c for legs in raw.values() for c in legs]
    spot = state.get("actual_spot") or state.get("spot")
    pct = atm_spread_pct(contracts, spot)
    if pct is not None:
        _TRACKER.observe(pct, now)
    res = _TRACKER.assess(now)
    res["current_spread_pct"] = (round(pct, 4) if pct is not None else None)
    return res
