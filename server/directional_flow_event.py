"""Directional Flow Event — unified normalization layer (cross-LLM audit, ChatGPT rec #9).

The audit's clarity finding: INFORMED FLOW / WHALE / WHALE CLUSTER / SPIKE / INFORMED
CLUSTER are five brands for variations on ONE idea (a directional, dollar-weighted,
time-concentrated flow event). ChatGPT: "merge them into one object with standardized
fields so the trader judges one thing with consistent metadata instead of a zoo of brands."

This is the SAFE core of that recommendation: a NORMALIZER, not a rip-out. Every existing
detector keeps firing and stays validated; this maps any of their payloads into one
`DirectionalFlowEvent` with the five fields ChatGPT named:
    dollar_size · cluster_breadth · aggressor_quality · time_concentration · catalyst_proximity

Additive + pure (no I/O, no dispatch change). The UI / a future unified Telegram path can
render `DirectionalFlowEvent` objects uniformly; wiring dispatch through it is a deliberate
follow-up the operator opts into — this layer just makes the data consistent first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Aggressor-source quality — the audit's "side is often a snapshot guess" concern made
# first-class: HIGH = live OPRA tick tape, MED = a dollar-size/V-OI override (inferred but
# strong), LOW = snapshot last-vs-NBBO guess (the ~10%-inverted/~80%-no-aggressor path).
Q_HIGH, Q_MED, Q_LOW, Q_UNK = "HIGH", "MED", "LOW", "UNKNOWN"


def _aggressor_quality(d: dict[str, Any]) -> str:
    src = (d.get("side_source") or "").lower()
    if src == "tick":
        return Q_HIGH
    if d.get("_whale_override") or d.get("_side_override") or d.get("side_override"):
        return Q_MED
    if src == "snapshot":
        return Q_LOW
    # fall back on the side itself: a clean ASK/BID with no source tag = low-confidence
    side = (d.get("side") or "").upper()
    if side in ("ASK", "BID"):
        return Q_LOW
    if side == "MID":
        return Q_LOW
    return Q_UNK


def _direction(d: dict[str, Any]) -> str:
    # explicit direction (clusters) wins
    dir_ = (d.get("direction") or "").upper()
    if dir_ in ("BULL", "BEAR", "NEUTRAL"):
        return dir_
    sent = (d.get("sentiment") or "").upper()
    otype = (d.get("option_type") or "").lower()
    if sent == "BULLISH":
        return "BULL" if otype != "put" else "BEAR"
    if sent == "BEARISH":
        return "BEAR" if otype != "put" else "BULL"
    return "NEUTRAL"


@dataclass
class DirectionalFlowEvent:
    """One normalized flow event. The five standardized ChatGPT fields are
    dollar_size / cluster_breadth / aggressor_quality / time_concentration_min /
    catalyst_in_window; the rest are the contract + provenance."""
    ticker: str
    direction: str                       # BULL / BEAR / NEUTRAL
    source: str                          # INFORMED_FLOW / WHALE / WHALE_CLUSTER / SPIKE / INFORMED_CLUSTER
    dollar_size: float                   # notional ($)
    cluster_breadth: int                 # distinct strikes (1 = single-strike)
    aggressor_quality: str               # HIGH / MED / LOW / UNKNOWN
    time_concentration_min: float | None  # span of the event in minutes (None = instantaneous)
    catalyst_in_window: bool | None      # scheduled earnings in [fire, expiration] (None = unknown)
    conviction: str                      # HIGH / MEDIUM / LOW
    vol_oi: float | None = None
    strike: float | None = None
    expiration: str | None = None
    option_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ── normalizers ──────────────────────────────────────────────────────────
    @classmethod
    def from_flow(cls, d: dict[str, Any], source: str = "INFORMED_FLOW") -> "DirectionalFlowEvent":
        """Single-contract flow payload (flow_alerts): INFORMED FLOW / WHALE / SPIKE."""
        return cls(
            ticker=(d.get("ticker") or "").upper(),
            direction=_direction(d),
            source=source,
            dollar_size=float(d.get("notional") or 0),
            cluster_breadth=1,
            aggressor_quality=_aggressor_quality(d),
            time_concentration_min=None,
            catalyst_in_window=d.get("earnings_in_window") if d.get("earnings_in_window") is not None else None,
            conviction=(d.get("conviction") or "").upper() or "LOW",
            vol_oi=(float(d["vol_oi"]) if d.get("vol_oi") not in (None, "") else None),
            strike=(float(d["strike"]) if d.get("strike") not in (None, "") else None),
            expiration=d.get("expiration"),
            option_type=(d.get("option_type") or "").lower() or None,
            raw=d,
        )

    @classmethod
    def from_cluster(cls, c: dict[str, Any], source: str = "INFORMED_CLUSTER") -> "DirectionalFlowEvent":
        """Multi-strike cluster payload (informed_cluster / whale_cluster)."""
        return cls(
            ticker=(c.get("ticker") or "").upper(),
            direction=_direction(c),
            source=source,
            dollar_size=float(c.get("total_notional") or 0),
            cluster_breadth=int(c.get("n_strikes") or 1),
            aggressor_quality=Q_MED,  # clusters of informed fires = inferred-strong by construction
            time_concentration_min=(float(c["duration_min"]) if c.get("duration_min") is not None else None),
            catalyst_in_window=c.get("earnings_in_window") if c.get("earnings_in_window") is not None else None,
            conviction=(c.get("conviction") or "HIGH").upper(),
            vol_oi=(float(c["avg_vol_oi"]) if c.get("avg_vol_oi") is not None else None),
            strike=None,
            expiration=c.get("expiration"),
            option_type=(c.get("option_type") or "").lower() or None,
            raw=c,
        )

    # ── consistent rendering ─────────────────────────────────────────────────
    def significance(self) -> float:
        """One comparable urgency number across all sources (the audit's 'one ranker'
        instead of per-detector additive scores). Dollar-weighted, lifted by breadth,
        aggressor quality and conviction; DISCOUNTED for a catalyst (De Silva / IV-crush
        finding) and for low side quality. Purely for sorting — not a P&L claim."""
        import math
        s = math.log10(max(self.dollar_size, 1)) * 10            # ~$1M -> 60, ~$10M -> 70
        s += (self.cluster_breadth - 1) * 6                       # each extra strike
        s += {"HIGH": 8, "MED": 3, "LOW": -4, "UNKNOWN": -2}.get(self.aggressor_quality, 0)
        s += {"HIGH": 6, "MEDIUM": 2, "LOW": -3}.get(self.conviction, 0)
        if self.catalyst_in_window:                              # flow into earnings underperforms
            s -= 8
        return round(s, 1)

    def summary(self) -> str:
        bits = [f"{self.ticker} {self.direction}", f"${self.dollar_size:,.0f}"]
        if self.cluster_breadth > 1:
            bits.append(f"{self.cluster_breadth} strikes")
        bits.append(f"side:{self.aggressor_quality}")
        if self.catalyst_in_window:
            bits.append("⚠️ER-in-window")
        bits.append(f"[{self.source}]")
        return "  ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker, "direction": self.direction, "source": self.source,
            "dollar_size": self.dollar_size, "cluster_breadth": self.cluster_breadth,
            "aggressor_quality": self.aggressor_quality,
            "time_concentration_min": self.time_concentration_min,
            "catalyst_in_window": self.catalyst_in_window, "conviction": self.conviction,
            "vol_oi": self.vol_oi, "strike": self.strike, "expiration": self.expiration,
            "option_type": self.option_type, "significance": self.significance(),
        }
