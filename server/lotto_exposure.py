"""Phase-2a manual lotto-exposure store (read by the Mir TP monitor).

The brokers aren't wired for position reads yet (E-Trade sandbox mocked, Tradier
paper delayed), so the user (or a small script) sets their current total
concurrent lotto premium-at-risk here; the Mir TP "LOTTO EXPOSURE CAP" block
compares it to the regime-scaled cap and flags over-cap. Phase 2b will replace
this with an automatic broker pull + lotto classifier.

State file (JSON, gitignored, anchored to repo root so CWD doesn't matter):
  data/lotto_exposure.json  (override: env MIR_LOTTO_EXPOSURE_FILE)
  { "premium_at_risk": 18500, "capital": 150000, "updated_ts": 1718.., "note": "" }

Set it:  python scripts/set_lotto_exposure.py 18500 --capital 150000
Read it:  get_exposure() -> dict | None

STALENESS is first-class: a trusted monitor that goes stale misleads, so we
always carry the figure's age and the caller warns when it's old.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "lotto_exposure.json"


def _path() -> Path:
    override = os.getenv("MIR_LOTTO_EXPOSURE_FILE", "").strip()
    return Path(override) if override else _DEFAULT


def get_exposure() -> dict[str, Any] | None:
    """Current manual exposure state, or None if unset / unreadable / invalid.
    Fail-soft: a corrupt file returns None (monitor shows the 'not set' hint)."""
    p = _path()
    try:
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        prem = float(d.get("premium_at_risk"))
        if prem < 0:
            return None
        cap = d.get("capital")
        return {"premium_at_risk": prem,
                "capital": float(cap) if cap not in (None, "", 0) else None,
                "updated_ts": int(d.get("updated_ts") or 0),
                "note": str(d.get("note") or "")}
    except Exception:
        return None


def set_exposure(premium_at_risk: float, capital: float | None = None,
                 note: str = "") -> dict[str, Any]:
    """Write the exposure state (stamps updated_ts=now). Returns the written dict."""
    if premium_at_risk < 0:
        raise ValueError("premium_at_risk must be >= 0")
    d: dict[str, Any] = {"premium_at_risk": float(premium_at_risk),
                         "updated_ts": int(time.time()), "note": note}
    if capital and capital > 0:
        d["capital"] = float(capital)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d


def staleness_hours(state: dict[str, Any] | None) -> float | None:
    """Hours since the figure was set. None if unknown."""
    if not state or not state.get("updated_ts"):
        return None
    return max(0.0, (time.time() - state["updated_ts"]) / 3600.0)


def age_str(hours: float | None) -> str:
    """Human age: '3h ago' / '2.1d ago' / 'age unknown'."""
    if hours is None:
        return "age unknown"
    if hours < 24:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.1f}d ago"
