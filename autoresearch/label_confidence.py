"""Cohort-level side-label confidence — the gate's label-quality axis.

Aggregates per-cluster tape verification (``side_confirmation``) into a cohort
verdict the validation gate and the Signal Health Card can act on. This is a
SECOND quarantine axis, orthogonal to data volume (MinTRL): a cohort can be
hugely over-MinTRL and still untrustworthy because the labels that DEFINE it
(flow side tags -> direction) are snapshot guesses or tape-contradicted.

Per cohort it computes:
  - the TAPE-CONFIRMATION FRACTION (share of verified clusters whose labeled side
    the tape confirms), the inversion fraction, and a Wilson 95% lower bound on
    the confirmation rate (so a tiny verified sample can't read as confidence);
  - a band: HIGH / MEDIUM / LOW / UNKNOWN (thresholds are config, never tuned);
  - a split-sample ARTIFACT test: if the full-cohort edge is positive but the
    CONFIRMED-only subset's edge is <= 0, the apparent edge lives in the
    mislabeled part -> ``edge_is_artifact``.

Verification samples a deterministic, time-stratified subset of clusters (evenly
strided over the time-ordered list) to bound ThetaData load — no RNG, fully
reproducible. We QUARANTINE rather than down-weight: reweighting by an
unvalidated correction would bake an unproven model into every downstream
statistic.

Pure-stdlib; read-only; offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .decay_monitor import wilson_interval
from .option_pnl import fire_hhmm_from_ts
from .side_confirmation import (
    AMBIGUOUS, CONFIRMED, INVERTED, NO_DATA,
    TradeTapeSource, classify_tape, fire_window, implied_side, verify_side,
)

# Bands.
LABEL_HIGH = "HIGH"
LABEL_MEDIUM = "MEDIUM"
LABEL_LOW = "LOW"
LABEL_UNKNOWN = "UNKNOWN"

# Cohorts whose direction is DERIVED FROM flow side tags. SOE/ZERO_DTE/SCALP/MIR
# directions come from other logic and are exempt from this axis.
SIDE_LABEL_DEPENDENT_PREFIXES = (
    "FLOW_", "WHALE", "INFORMED", "CLUSTER_", "HOT_FLOW",
)


def is_side_label_dependent(alert_type: str) -> bool:
    t = (alert_type or "").upper()
    return any(t.startswith(p) for p in SIDE_LABEL_DEPENDENT_PREFIXES)


@dataclass
class LabelConfidenceConfig:
    # Banding thresholds (charter rule: config constants, never auto-tuned).
    min_checked: int = 12          # below this many verified clusters -> UNKNOWN.
    high_confirm: float = 0.80     # HIGH needs confirm_frac >= this ...
    high_invert_max: float = 0.05  # ... and invert_frac <= this ...
    high_lcb_min: float = 0.60     # ... and Wilson-LCB(confirm) >= this.
    low_confirm: float = 0.50      # LOW if confirm_frac < this ...
    low_invert: float = 0.15       # ... or invert_frac > this.
    # Split-sample artifact test.
    artifact_min_n: int = 10       # confirmed clusters needed before flagging.
    # Sampling / tape.
    sample_max: int = 60           # max clusters verified per cohort (ThetaData load).
    min_contracts: int = 10        # tape volume floor for a verdict.
    buffer_min: int = 5            # window = 09:30 -> fire + buffer.


@dataclass
class ClusterSideCheck:
    ticker: str
    day: str
    direction: str
    labeled_side: Optional[str]
    status: str                    # CONFIRMED / INVERTED / AMBIGUOUS / NO_DATA.
    tape_side: str = ""
    ask_frac: float = 0.0
    bid_frac: float = 0.0
    mid_frac: float = 0.0
    contracts: int = 0
    ret: Optional[float] = None    # the cluster's realized return, if present.


@dataclass
class LabelConfidenceResult:
    cohort: str
    band: str                      # HIGH / MEDIUM / LOW / UNKNOWN.
    n_clusters: int                # cohort clusters available.
    n_checked: int                 # clusters sampled for verification.
    n_with_data: int               # sampled clusters with usable tape.
    n_confirmed: int
    n_inverted: int
    n_ambiguous: int
    n_no_data: int
    confirm_frac: Optional[float]  # n_confirmed / n_with_data.
    invert_frac: Optional[float]
    confirm_lcb: Optional[float]   # Wilson 95% lower bound on confirm_frac.
    # Split-sample artifact test (full cohort vs CONFIRMED-only subset).
    edge_all: Optional[float] = None
    n_edge_all: int = 0
    edge_confirmed: Optional[float] = None
    n_edge_confirmed: int = 0
    edge_is_artifact: bool = False
    reason: str = ""
    checks: list[ClusterSideCheck] = field(default_factory=list)


def stride_sample(items: list, cap: int) -> list:
    """Deterministic, time-stratified subsample: evenly strided indices over the
    (time-ordered) list. cap >= len returns the list unchanged."""
    n = len(items)
    if cap <= 0 or n <= cap:
        return list(items)
    if cap == 1:
        return [items[0]]
    idx = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})
    return [items[i] for i in idx]


def _band(confirm: float, invert: float, lcb: float,
          cfg: LabelConfidenceConfig) -> str:
    if confirm < cfg.low_confirm or invert > cfg.low_invert:
        return LABEL_LOW
    if (confirm >= cfg.high_confirm and invert <= cfg.high_invert_max
            and lcb >= cfg.high_lcb_min):
        return LABEL_HIGH
    return LABEL_MEDIUM


def check_cohort_side_labels(
    cohort: str,
    clusters: list[dict],
    tape_source: TradeTapeSource,
    config: Optional[LabelConfidenceConfig] = None,
) -> LabelConfidenceResult:
    """Verify a cohort's side labels against the tape and band the confidence.

    ``clusters`` are economic-decision clusters as produced by
    ``backtest_adapter.load_clusters_economic`` — each dict needs ticker / day /
    direction / strike / expiration / option_type / fired_at, plus optionally
    ``side`` (used directly when present; otherwise the side is implied from
    direction x option_type) and ``ret`` (enables the artifact test).
    """
    cfg = config or LabelConfidenceConfig()
    ordered = sorted(clusters, key=lambda c: c.get("fired_at") or 0.0)
    sampled = stride_sample(ordered, cfg.sample_max)

    checks: list[ClusterSideCheck] = []
    for c in sampled:
        labeled = (c.get("side") or "").upper() or implied_side(
            c.get("direction"), c.get("option_type"))
        chk = ClusterSideCheck(
            ticker=c.get("ticker", ""), day=c.get("day", ""),
            direction=(c.get("direction") or "").upper(),
            labeled_side=labeled, status=NO_DATA, ret=c.get("ret"))
        spec_ok = all(c.get(k) not in (None, "") for k in
                      ("strike", "expiration", "option_type", "fired_at"))
        if spec_ok:
            start, end = fire_window(
                fire_hhmm_from_ts(float(c["fired_at"])), cfg.buffer_min)
            prints = tape_source.prints(
                c["ticker"], c["expiration"], float(c["strike"]),
                c["option_type"], c["day"], start, end)
            tape = classify_tape(prints, min_contracts=cfg.min_contracts)
            chk.status = verify_side(labeled, tape)
            if tape.status == "OK":
                chk.tape_side = tape.side
                chk.ask_frac, chk.bid_frac, chk.mid_frac = (
                    tape.ask_frac, tape.bid_frac, tape.mid_frac)
                chk.contracts = tape.contracts
        checks.append(chk)

    n_conf = sum(1 for c in checks if c.status == CONFIRMED)
    n_inv = sum(1 for c in checks if c.status == INVERTED)
    n_amb = sum(1 for c in checks if c.status == AMBIGUOUS)
    n_nod = sum(1 for c in checks if c.status == NO_DATA)
    n_data = n_conf + n_inv + n_amb

    confirm = invert = lcb = None
    band = LABEL_UNKNOWN
    reason = f"only {n_data} clusters with tape data (< {cfg.min_checked})"
    if n_data >= cfg.min_checked:
        confirm = n_conf / n_data
        invert = n_inv / n_data
        lcb, _, _ = wilson_interval(n_conf, n_data)
        band = _band(confirm, invert, lcb, cfg)
        reason = (f"confirm {confirm:.0%} (LCB {lcb:.0%}), invert {invert:.0%}, "
                  f"ambiguous {n_amb}/{n_data}")

    # Split-sample artifact test: full-cohort edge vs CONFIRMED-only edge.
    rets_all = [c.get("ret") for c in clusters if c.get("ret") is not None]
    rets_conf = [c.ret for c in checks if c.status == CONFIRMED and c.ret is not None]
    edge_all = (sum(rets_all) / len(rets_all)) if rets_all else None
    edge_conf = (sum(rets_conf) / len(rets_conf)) if rets_conf else None
    artifact = bool(
        edge_all is not None and edge_all > 0
        and edge_conf is not None and len(rets_conf) >= cfg.artifact_min_n
        and edge_conf <= 0)
    if artifact:
        reason += (f"; ARTIFACT: full-cohort edge {edge_all:+.3f} but "
                   f"confirmed-only {edge_conf:+.3f} (n={len(rets_conf)})")

    return LabelConfidenceResult(
        cohort=cohort, band=band,
        n_clusters=len(clusters), n_checked=len(checks), n_with_data=n_data,
        n_confirmed=n_conf, n_inverted=n_inv, n_ambiguous=n_amb, n_no_data=n_nod,
        confirm_frac=confirm, invert_frac=invert, confirm_lcb=lcb,
        edge_all=edge_all, n_edge_all=len(rets_all),
        edge_confirmed=edge_conf, n_edge_confirmed=len(rets_conf),
        edge_is_artifact=artifact, reason=reason, checks=checks,
    )


__all__ = [
    "LabelConfidenceConfig", "LabelConfidenceResult", "ClusterSideCheck",
    "check_cohort_side_labels", "stride_sample", "is_side_label_dependent",
    "LABEL_HIGH", "LABEL_MEDIUM", "LABEL_LOW", "LABEL_UNKNOWN",
    "SIDE_LABEL_DEPENDENT_PREFIXES",
]
