"""Market dealer-structure cache + bear-day guardrail (AION-teardown task #54, Layer 2).

The flow-alert scorer runs synchronously and has no access to index GEX. This
module is the bridge: the live worker pushes SPY/QQQ MACRO structure here after
each `gex.compute_exp_data()` cycle, and the alert path reads a synthesized
market read at scoring time.

Why it exists (the Friday 6/05 lesson): our flow engine is mechanically
long-biased (sweeps are mostly call buys), so on a short-gamma down day it keeps
flagging longs that get run over. A cheap "is the index tape short-gamma /
risk-off?" gate down-weights long alerts exactly when they're most dangerous.

SAFETY: gating is OFF by default (`STRUCTURE_GATE_ACTIVE=False`, shadow mode).
In shadow mode we still compute + tag + log the read (so we can measure its
hit-rate via alert_outcomes), but we change ZERO conviction decisions until the
flag is flipped after live validation — per the "no arch changes until
validated" discipline rule.
"""
from __future__ import annotations

import os
import threading
import time as _time
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────
# Flip to True (or set env STRUCTURE_GATE_ACTIVE=1) only after live validation.
STRUCTURE_GATE_ACTIVE: bool = os.getenv("STRUCTURE_GATE_ACTIVE", "0") in ("1", "true", "True")

STRUCTURE_INDEX_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "SPX")
STRUCTURE_RISK_OFF_SCORE: int = 55     # min structure_score to treat as risk-off gate
STRUCTURE_STALE_SEC: float = 1800.0    # 30 min — beyond this, don't gate (neutral)
STRUCTURE_DEMOTE_NOTCHES: int = 1      # conviction tiers to drop a long on a short-gamma tape

# conviction ladder for notch math
_CONVICTION_LADDER = ["LOW", "MEDIUM", "HIGH"]

# ── State ─────────────────────────────────────────────────────────────────
_lock = threading.Lock()
# ticker -> {regime, score, risk_off, net_cex, charm_anchor, pos_gex, neg_gex,
#            zgl, spot, oi_mode, ts}
_index_structure: dict[str, dict[str, Any]] = {}


def update_index_structure(ticker: str, exp_data: dict[str, Any], spot: float) -> None:
    """Worker hook: cache the dealer-structure read for an index from a MACRO
    `compute_exp_data` result. Cheap; safe to call every cycle. Only SPY/QQQ
    (or whatever's in STRUCTURE_INDEX_TICKERS) are retained."""
    if not ticker:
        return
    t = ticker.upper()
    if t not in STRUCTURE_INDEX_TICKERS:
        return
    rec = {
        "regime": exp_data.get("structure_regime", "NEUTRAL"),
        "score": int(exp_data.get("structure_score", 0) or 0),
        "risk_off": bool(exp_data.get("structure_risk_off", False)),
        "net_cex": float(exp_data.get("net_cex", 0.0) or 0.0),
        "charm_anchor": exp_data.get("charm_anchor") or {},
        "pos_gex": float(exp_data.get("pos_gex", 0.0) or 0.0),
        "neg_gex": float(exp_data.get("neg_gex", 0.0) or 0.0),
        "zgl": exp_data.get("zgl", 0),
        "spot": spot,
        "oi_mode": exp_data.get("_oi_mode", "effective"),
        "ts": _time.time(),
    }
    with _lock:
        _index_structure[t] = rec


def _is_fresh(rec: dict[str, Any], now: float) -> bool:
    return rec and (now - rec.get("ts", 0.0)) <= STRUCTURE_STALE_SEC


def _one_line(t: str, rec: dict[str, Any]) -> str:
    ca = rec.get("charm_anchor") or {}
    nb = ""
    if ca:
        nb = f", charm anchor ${ca.get('strike')} {ca.get('side')} spot"
    net = (rec.get("pos_gex", 0) + rec.get("neg_gex", 0)) / 1e9
    return f"{t} {rec.get('regime')} (net γ ${net:.1f}B, score {rec.get('score')}){nb}"


def get_market_structure() -> dict[str, Any]:
    """Synthesize a market-wide dealer-structure read from the cached indices.

    Returns a dict the alert path consumes:
      risk_off   : bool  — index tape mechanically amplifies down-moves
      score      : int   — 0 calm .. 100 short-gamma (max across fresh indices)
      regime     : str   — worst (most short-gamma) index regime label
      bias       : str   — RISK_OFF | NEUTRAL | RISK_ON
      reason     : str   — human-readable, for Telegram tag / logging
      sources    : list  — per-index one-liners
      stale      : bool  — True if no fresh index data (gate stays neutral)
      gate_active: bool  — whether scoring changes are live (vs shadow)
    """
    now = _time.time()
    with _lock:
        recs = {t: dict(r) for t, r in _index_structure.items()}

    fresh = {t: r for t, r in recs.items() if _is_fresh(r, now)}
    if not fresh:
        return {
            "risk_off": False, "score": 0, "regime": "UNKNOWN", "bias": "NEUTRAL",
            "reason": "no fresh index structure", "sources": [], "stale": True,
            "gate_active": STRUCTURE_GATE_ACTIVE,
        }

    # risk-off if ANY index is short-gamma above the score floor (conservative).
    risk_off_indices = [
        t for t, r in fresh.items()
        if r.get("risk_off") and r.get("score", 0) >= STRUCTURE_RISK_OFF_SCORE
    ]
    score = max((r.get("score", 0) for r in fresh.values()), default=0)
    # worst regime = the one with the highest score
    worst_t = max(fresh, key=lambda t: fresh[t].get("score", 0))
    regime = fresh[worst_t].get("regime", "NEUTRAL")
    risk_off = bool(risk_off_indices)

    if risk_off:
        bias = "RISK_OFF"
    elif score <= 15:
        bias = "RISK_ON"
    else:
        bias = "NEUTRAL"

    sources = [_one_line(t, r) for t, r in sorted(fresh.items())]
    reason = (
        f"short-gamma index tape: {', '.join(risk_off_indices)}"
        if risk_off else f"{regime.lower()} index tape"
    )
    return {
        "risk_off": risk_off, "score": int(score), "regime": regime, "bias": bias,
        "reason": reason, "sources": sources, "stale": False,
        "gate_active": STRUCTURE_GATE_ACTIVE,
    }


def evaluate_alert(sentiment: str, ticker: str = "") -> dict[str, Any]:
    """Per-alert structure verdict. The flow-alert scorer calls this.

    Returns:
      tag         : str | None — Telegram/UI banner text (always set on risk-off,
                                 shadow OR active — it's informational)
      notch_delta : int        — conviction tiers to add (negative = demote).
                                 ZERO in shadow mode (gate inactive) — pure tag.
      reason      : str
      structure   : dict        — the get_market_structure() payload

    Direction logic: on a short-gamma (risk-off) index tape, a BULLISH/long
    alert is demoted (those get run over); a BEARISH alert is left as-is but
    marked 'structure-confirmed'. Index-ETF flow is informational only.
    """
    ms = get_market_structure()
    out: dict[str, Any] = {
        "tag": None, "notch_delta": 0, "reason": "", "structure": ms,
    }
    if ms["stale"] or not ms["risk_off"]:
        return out

    sent = (sentiment or "").upper()
    is_bullish = "BULL" in sent or sent in ("LONG", "CALL")
    is_bearish = "BEAR" in sent or sent in ("SHORT", "PUT")

    if is_bullish:
        out["tag"] = f"⚠️ SHORT-GAMMA TAPE ({ms['regime']})"
        out["reason"] = f"long flagged on risk-off tape — {ms['reason']}"
        # Only actually demote when the gate is live; shadow = tag only.
        out["notch_delta"] = -STRUCTURE_DEMOTE_NOTCHES if ms["gate_active"] else 0
    elif is_bearish:
        out["tag"] = f"✅ structure-confirmed ({ms['regime']})"
        out["reason"] = f"bearish aligned with risk-off tape — {ms['reason']}"
        out["notch_delta"] = 0  # confirmation only, no boost (conservative)
    return out


def apply_notch(conviction: str, notch_delta: int) -> str:
    """Move a conviction grade up/down the LOW/MEDIUM/HIGH ladder, clamped."""
    if notch_delta == 0 or conviction not in _CONVICTION_LADDER:
        return conviction
    i = _CONVICTION_LADDER.index(conviction)
    j = max(0, min(len(_CONVICTION_LADDER) - 1, i + notch_delta))
    return _CONVICTION_LADDER[j]


def snapshot() -> dict[str, Any]:
    """Debug/health: current cache + synthesized read."""
    now = _time.time()
    with _lock:
        recs = {
            t: {**{k: v for k, v in r.items() if k != "charm_anchor"},
                "age_sec": round(now - r.get("ts", now), 1)}
            for t, r in _index_structure.items()
        }
    return {"indices": recs, "market": get_market_structure(),
            "gate_active": STRUCTURE_GATE_ACTIVE}


def _reset_for_test() -> None:
    with _lock:
        _index_structure.clear()
