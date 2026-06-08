"""Analogues × flow confluence (task #55 follow-up).

Turns the index base-rate engine (server/analogues.py) into a market-context
layer for flow alerts. Synthesizes SPX+NDX active-pattern forward-return base
rates into a single directional bias, then tags each flow alert with whether it
ALIGNS with or FIGHTS that base rate:

  bullish call flow + bullish index base-rate  → 🎯 ANALOGUE CONFLUENCE
  bullish call flow + bearish index base-rate  → ↩️ counter base-rate

This is the multiplier we flagged in the teardown: a rare bullish pattern firing
the same day as informed call flow is a higher-conviction setup than either alone.

HOT-PATH SAFE: the alert scorer calls get_market_bias()/evaluate_flow_confluence(),
which read a pre-warmed in-memory cache (no network, no I/O). A worker hook calls
refresh_market_bias() (throttled, runs in a thread) to keep the cache fresh.
Tag-only by default — no conviction change (it's context, like the structure gate
in shadow). The trader reads it; activation/boosting can come after validation.
"""
from __future__ import annotations

import time as _time
from typing import Any

# bias thresholds on the summed vote
_BIAS_T = 12.0
_REFRESH_SEC = 1800.0  # recompute at most every 30 min
_MIN_N = 10            # ignore patterns with too few historical occurrences
_THIN_N = 25           # half-weight patterns with thin samples

_market_bias: dict[str, Any] = {}
_last_refresh: float = 0.0


# ── Pure core ─────────────────────────────────────────────────────────────
def compute_market_bias(scans: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine scan() results (e.g. SPX + NDX) into one directional base-rate
    bias. Each active pattern votes by its OWN forward-20d hit rate (the base
    rate is what matters, not the nominal bull/bear label): hit>50 = bullish,
    <50 = bearish; thin samples half-weighted.
    """
    votes: list[float] = []
    details: list[tuple[str, str, float, int]] = []
    for sc in scans or []:
        sym = sc.get("symbol", "?")
        for p in sc.get("active", []):
            f20 = (p.get("forward") or {}).get(20) or {}
            hit = f20.get("hit_rate")
            n = f20.get("n") or 0
            if hit is None or n < _MIN_N:
                continue
            vote = hit - 50.0
            if n < _THIN_N:
                vote *= 0.5
            votes.append(vote)
            details.append((sym, p.get("pattern", "?"), round(vote, 1), n))
    net = round(sum(votes), 1)
    if net >= _BIAS_T:
        bias = "BULLISH"
    elif net <= -_BIAS_T:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    score = max(-100, min(100, round(net * 2)))
    top = sorted(details, key=lambda d: abs(d[2]), reverse=True)[:3]
    return {"bias": bias, "score": score, "net_vote": net,
            "n_patterns": len(votes), "top": top}


def evaluate_flow_confluence(
    sentiment: str, market_bias: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-alert confluence verdict. Returns {tag, note, bias, aligned}.
    tag/note are None/'' when the index base-rate is NEUTRAL or unavailable."""
    mb = market_bias if market_bias is not None else get_market_bias()
    out: dict[str, Any] = {"tag": None, "note": "", "bias": mb.get("bias"),
                           "aligned": None}
    if not mb or mb.get("bias") in (None, "NEUTRAL") or mb.get("n_patterns", 0) == 0:
        return out
    sent = (sentiment or "").upper()
    is_bull = "BULL" in sent or sent in ("LONG", "CALL")
    is_bear = "BEAR" in sent or sent in ("SHORT", "PUT")
    if not (is_bull or is_bear):
        return out
    flow_dir = "BULLISH" if is_bull else "BEARISH"
    top_pat = mb["top"][0][1] if mb.get("top") else ""
    if flow_dir == mb["bias"]:
        out["aligned"] = True
        out["tag"] = f"🎯 ANALOGUE CONFLUENCE ({mb['bias']} base-rate)"
        out["note"] = f"index base-rate aligns ({top_pat}, score {mb['score']})"
    else:
        out["aligned"] = False
        out["tag"] = f"↩️ counter base-rate (index {mb['bias']})"
        out["note"] = f"flow opposes index base-rate (score {mb['score']})"
    return out


# ── Cache + refresh ───────────────────────────────────────────────────────
def get_market_bias() -> dict[str, Any]:
    """Instant, no-I/O read of the cached market base-rate bias."""
    if _market_bias:
        return dict(_market_bias)
    return {"bias": "NEUTRAL", "score": 0, "net_vote": 0, "n_patterns": 0, "top": []}


def refresh_market_bias(
    symbols: tuple[str, ...] = ("SPX", "NDX"), force: bool = False,
) -> dict[str, Any]:
    """Recompute the cached bias from fresh SPX/NDX scans. Throttled to
    _REFRESH_SEC. Does network I/O (get_scan is itself 1h-cached) — call from a
    worker thread, NEVER from the alert hot path. Safe to call every cycle."""
    global _market_bias, _last_refresh
    now = _time.time()
    if not force and _market_bias and (now - _last_refresh) < _REFRESH_SEC:
        return _market_bias
    try:
        from .analogue_data import get_scan
    except Exception:
        return _market_bias
    scans = []
    for s in symbols:
        try:
            scans.append(get_scan(s))
        except Exception as e:
            print(f"[ANALOGUE] scan {s} failed: {e!r}", flush=True)
    if scans:
        _market_bias = compute_market_bias(scans)
        _last_refresh = now
        print(f"[ANALOGUE] market base-rate bias: {_market_bias['bias']} "
              f"(score {_market_bias['score']}, {_market_bias['n_patterns']} patterns)",
              flush=True)
    return _market_bias


def _reset_for_test() -> None:
    global _market_bias, _last_refresh
    _market_bias = {}
    _last_refresh = 0.0
