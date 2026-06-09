"""The validation gate — the make-or-break deflation pipeline.

Implements the ordered, cheap-rejection-first fitness function from the charter
(docs/research/autoresearch/PROJECT.md and SYNTHESIS.md sec.5):

    0. TEST CARD + DEDUP   pre-registered card; reject semantic duplicates.   [cheap]
    1. MinTRL / MinBTL     cohort T must exceed the min length given GLOBAL N.
    2. CPCV                purged + embargoed OOS Sharpe distribution.
    3. PBO < 0.05          in-sample optimum must not rank below OOS median.
    4. DSR >= 0.95         deflate Sharpe vs E[max Sharpe | GLOBAL N].
    5. Hansen SPA p<0.05   must statistically BEAT the baseline (SOE A), not zero.
    6. ECONOMIC NULL       +EV net of slippage; regime-robust; orthogonal.

Disciplines (un-foolable-ness): (a) every gate run records ONE trial into the
global ledger BEFORE deflation, so N — and therefore the DSR/MinBTL hurdle —
includes this attempt; (b) a mechanistic claim is required before any stat runs;
(c) the gate never tunes its own thresholds.

Stages short-circuit: the first FAIL stops the pipeline (cheap rejections first).
A stage whose REQUIRED inputs are missing FAILS (you cannot pass what you cannot
test); optional enrichments (regime split, orthogonality) WARN instead.

This module needs numpy/scipy/arch -> run under .venv-autoresearch. It is offline
and proposes only; nothing here ships to live scoring.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional, Sequence

import numpy as np

from .stats.deflated_sharpe import (
    sharpe_ratio, _moments, deflated_sharpe_ratio,
    min_track_record_length, min_backtest_length,
)
from .stats.cscv_pbo import cscv_pbo
from .stats.cpcv import cpcv_splits, cpcv_oos_sharpes
from .stats.spa import spa_beats_baseline
from .trials_ledger import TrialLedger
from .dedup import is_duplicate

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

# Outcome tiers (C1): the gate no longer returns a naive pass/fail. SPA-beats-
# baseline + economic lift are the HARD gates; PBO and DSR are DIAGNOSTIC bands
# that can cap the outcome at SHADOW or REJECT but are not sole gatekeepers.
SHIP, SHADOW, REJECT = "SHIP", "SHADOW", "REJECT"
_TIER_RANK = {REJECT: 0, SHADOW: 1, SHIP: 2}


def _worst(*tiers: str) -> str:
    """Combine outcome tiers — the overall outcome is the worst (lowest) tier."""
    return min(tiers, key=lambda t: _TIER_RANK[t])


# --------------------------------------------------------------------------- #
# Inputs.
# --------------------------------------------------------------------------- #

@dataclass
class TestCard:
    """Pre-registered hypothesis card. All fields are required & non-trivial."""
    card_id: str
    provenance: str          # where the idea came from (internal slice / paper / etc.)
    claim: str               # the falsifiable claim.
    expected_sign: str       # 'positive' or 'negative'.
    mechanism: str           # mechanistic rationale (WHY it should work).
    target_cohort: str       # which alert_outcomes cohort/regime this applies to.
    kill_criteria: str       # what observation would retire it.

    def validate(self) -> Optional[str]:
        """Return an error string if the card is incomplete, else None."""
        required = {
            "card_id": self.card_id, "provenance": self.provenance,
            "claim": self.claim, "mechanism": self.mechanism,
            "target_cohort": self.target_cohort, "kill_criteria": self.kill_criteria,
        }
        for name, val in required.items():
            if not val or not str(val).strip():
                return f"missing/empty required field: {name}"
        if self.expected_sign not in ("positive", "negative"):
            return f"expected_sign must be 'positive' or 'negative', got {self.expected_sign!r}"
        if len(self.mechanism.split()) < 3:
            return "mechanism must be a real rationale (>= 3 words), not a placeholder"
        return None


@dataclass
class Candidate:
    """A hypothesis + the data needed to validate it.

    ``returns`` is the candidate's realistic (ask-bid, net-of-slippage) per-trade
    return series, time-ordered.
    """
    card: TestCard
    returns: Sequence[float]
    config_matrix: Optional[np.ndarray] = None          # (T, N) variants -> PBO.
    baseline_returns: Optional[Sequence[float]] = None  # aligned baseline -> SPA.
    t1: Optional[Sequence[int]] = None                  # label horizon -> CPCV purge.
    regime_labels: Optional[Sequence] = None            # per-return regime tag.
    detector_returns: Optional[dict] = None             # {name: aligned returns} -> orthogonality.
    # Optional SPA-specific aligned pair. Candidate vs baseline often live on
    # different per-trade indices (different cohorts), so SPA compares them on a
    # COMMON grid (e.g. daily P/L). When both are set, the SPA stage uses these
    # instead of (returns, baseline_returns); CPCV/DSR/PBO still use `returns`.
    spa_returns: Optional[Sequence[float]] = None
    spa_baseline_returns: Optional[Sequence[float]] = None


@dataclass
class GateConfig:
    breakeven: float = 0.227
    spa_alpha: float = 0.05
    mintrl_prob: float = 0.95
    minbtl_target_sr: float = 1.0
    cpcv_groups: int = 6
    cpcv_k_test: int = 2
    # Embargo as a fraction of samples; for cluster-level series, 1 cluster ~ 1
    # trading day, so a small fraction already embargoes the hold horizon (C5).
    cpcv_embargo_pct: float = 0.02
    cpcv_median_sharpe_min: float = 0.0
    pbo_blocks: Optional[int] = None   # None -> adaptive block-size by T (FIX-1).
    orthogonality_max_abs_corr: float = 0.7
    spa_reps: int = 1000
    dedup_jaccard_max: float = 0.9        # token-Jaccard lexical-dup threshold.
    dedup_charngram_max: float = 0.85     # char-trigram lexical-dup threshold (paraphrase).
    dedup_structural_min: float = 0.6     # same cohort+sign + claim/mechanism overlap.
    min_regime_n: int = 20

    # --- C1 diagnostic bands (PBO is NOT a p-value; 0.50 is the danger line) ---
    # PBO: >=0.50 REJECT (hard) · 0.20-0.50 REJECT-deploy · 0.10-0.20 SHADOW · <0.10 SHIP.
    pbo_danger: float = 0.50
    pbo_no_deploy: float = 0.20
    pbo_shadow: float = 0.10
    # DSR (secondary): >=0.95 admit · 0.90-0.95 shadow · <0.90 reject.
    dsr_admit: float = 0.95
    dsr_shadow: float = 0.90
    # Power / staging (threshold lock): n>=staging => STAGING(shadow); ship needs
    # >= ship_min_obs effective cluster obs AND T>=MinTRL.
    staging_min_obs: int = 200
    ship_min_obs: int = 450


# --------------------------------------------------------------------------- #
# Output.
# --------------------------------------------------------------------------- #

@dataclass
class StageResult:
    name: str
    status: str            # PASS / FAIL / WARN / SKIP (display).
    tier: str = SHIP       # SHIP / SHADOW / REJECT contribution to the outcome.
    role: str = "gate"     # "gate" (hard) or "diagnostic" (PBO/DSR).
    detail: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class GateReport:
    card_id: str
    outcome: str                       # SHIP / SHADOW / REJECT.
    drivers: list[str]                 # stage names that set the final tier.
    global_n_trials: int
    stages: list[StageResult] = field(default_factory=list)

    # Backward-compatible convenience flags.
    @property
    def passed(self) -> bool:          # "did it clear to SHIP?"
        return self.outcome == SHIP

    @property
    def rejected(self) -> bool:
        return self.outcome == REJECT

    @property
    def shippable(self) -> bool:
        return self.outcome == SHIP

    def summary(self) -> str:
        head = f"GATE [{self.card_id}]  ->  {self.outcome}"
        if self.drivers:
            head += f"  (set by: {', '.join(self.drivers)})"
        head += f"   global N={self.global_n_trials}"
        lines = [head, "-" * 72]
        for s in self.stages:
            tag = "diag" if s.role == "diagnostic" else "GATE"
            lines.append(f"  [{s.status:4s}|{s.tier:6s}|{tag}] {s.name:12s} {s.message}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #

def _normalize_claim(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return set(toks)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- #
# The gate.
# --------------------------------------------------------------------------- #

class ValidationGate:
    def __init__(self, ledger: TrialLedger, config: Optional[GateConfig] = None,
                 existing_claims: Optional[list[str]] = None,
                 existing_cards: Optional[list] = None):
        self.ledger = ledger
        self.cfg = config or GateConfig()
        # Novelty corpus for Stage-0 dedup. Prefer full prior TestCards (enables
        # the structural cohort+sign rule); bare claim strings are accepted too
        # (lexical-only). See autoresearch/dedup.py.
        self._corpus: list = list(existing_cards or []) + list(existing_claims or [])

    def evaluate(self, cand: Candidate) -> GateReport:
        stages: list[StageResult] = []

        # --- Stage 0: TEST CARD + DEDUP (no stats; never records a trial) --- #
        s0 = self._stage_card(cand)
        stages.append(s0)
        if s0.tier == REJECT:
            return self._finish(cand, stages)

        # Record this attempt as ONE global trial BEFORE deflation, so N (and the
        # MinBTL/DSR hurdles) include it. This is the single global-N increment.
        r = np.asarray(cand.returns, dtype=float)
        sr = sharpe_ratio(r)
        skew, kurt = _moments(r)
        self.ledger.record(
            label=cand.card.card_id, sharpe=sr, n_obs=int(r.size),
            skew=skew, kurtosis=kurt,
            meta={"claim": cand.card.claim, "cohort": cand.card.target_cohort},
        )
        global_n = self.ledger.count()

        # All remaining stages run (no short-circuit) so the report is a complete
        # diagnostic. The overall outcome is the WORST tier across them; SPA and
        # ECONOMIC are the hard gates, PBO and DSR are diagnostic bands (C1).
        stages.append(self._stage_minlen(r, sr, skew, kurt, global_n))
        stages.append(self._stage_cpcv(r))
        stages.append(self._stage_pbo(cand))            # diagnostic
        stages.append(self._stage_dsr(sr, skew, kurt, r.size))  # diagnostic
        stages.append(self._stage_spa(cand))            # HARD gate
        stages.append(self._stage_economic(cand, r))    # HARD gate
        return self._finish(cand, stages)

    # --- stages ----------------------------------------------------------- #

    def _stage_card(self, cand: Candidate) -> StageResult:
        err = cand.card.validate()
        if err:
            return StageResult("TEST_CARD", FAIL, tier=REJECT, message=f"invalid card: {err}")
        dup = is_duplicate(
            cand.card, self._corpus,
            token_max=self.cfg.dedup_jaccard_max,
            charngram_max=self.cfg.dedup_charngram_max,
            structural_min=self.cfg.dedup_structural_min,
        )
        if dup.is_dup:
            return StageResult("TEST_CARD", FAIL, tier=REJECT,
                               detail={"kind": dup.kind, "score": round(dup.score, 3),
                                       "match": dup.match_id},
                               message=f"duplicate ({dup.kind}): {dup.reason}")
        return StageResult("TEST_CARD", PASS, tier=SHIP, message="card complete, not a duplicate")

    def _stage_minlen(self, r, sr, skew, kurt, global_n) -> StageResult:
        T = int(r.size)
        mintrl = min_track_record_length(sr, skew, kurt, prob=self.cfg.mintrl_prob)
        minbtl = min_backtest_length(global_n, self.cfg.minbtl_target_sr)
        need = max(mintrl, minbtl)
        detail = {"T": T, "mintrl": mintrl, "minbtl": minbtl, "required": need,
                  "global_n": global_n, "sharpe": sr}
        if sr <= 0:
            return StageResult("MIN_LENGTH", FAIL, tier=REJECT, role="gate", detail=detail,
                               message=f"no positive edge (SR={sr:+.3f}); MinTRL=inf")
        if T >= need and T >= self.cfg.ship_min_obs:
            return StageResult("MIN_LENGTH", PASS, tier=SHIP, role="gate", detail=detail,
                               message=f"T={T} >= need {need:.0f} and ship floor {self.cfg.ship_min_obs}")
        # Underpowered for shipping, but not a hard reject — staging/shadow (pooling
        # at family level may rescue it; see C2).
        why = (f"T={T} < need {need:.0f}" if T < need
               else f"T={T} < ship floor {self.cfg.ship_min_obs}")
        return StageResult("MIN_LENGTH", WARN, tier=SHADOW, role="gate", detail=detail,
                           message=f"STAGING — {why} (MinTRL={mintrl:.0f}, MinBTL={minbtl:.0f})")

    def _stage_cpcv(self, r) -> StageResult:
        n = int(r.size)
        if n < self.cfg.cpcv_groups:
            return StageResult("CPCV", WARN, tier=SHADOW, role="gate",
                               message=f"too few samples (n={n}) for {self.cfg.cpcv_groups} groups — not assessed")
        splits = cpcv_splits(n, self.cfg.cpcv_groups, self.cfg.cpcv_k_test,
                             embargo_pct=self.cfg.cpcv_embargo_pct)
        sharpes = cpcv_oos_sharpes(r, splits)
        med = float(np.median(sharpes))
        frac_pos = float(np.mean(np.asarray(sharpes) > 0))
        ok = med > self.cfg.cpcv_median_sharpe_min
        return StageResult("CPCV", PASS if ok else FAIL, tier=SHIP if ok else REJECT, role="gate",
                           detail={"n_paths": len(splits), "median_oos_sharpe": med,
                                   "frac_paths_positive": frac_pos},
                           message=f"{len(splits)} OOS paths, median Sharpe {med:+.3f}, "
                                   f"{frac_pos:.0%} positive")

    def _stage_pbo(self, cand: Candidate) -> StageResult:
        # DIAGNOSTIC (C1): PBO is the prob the IS-winner ranks below OOS median.
        # 0.50 is the danger line, NOT 0.05. Bands cap the outcome but PBO is not a
        # sole gatekeeper.
        if cand.config_matrix is None:
            return StageResult("PBO", WARN, tier=SHADOW, role="diagnostic",
                               message="no config_matrix — overfitting not assessed (shadow)")
        M = np.asarray(cand.config_matrix, dtype=float)
        try:
            res = cscv_pbo(M, n_blocks=self.cfg.pbo_blocks)   # auto block-size (FIX-1).
        except ValueError as e:
            return StageResult("PBO", WARN, tier=SHADOW, role="diagnostic",
                               message=f"PBO not assessed: {e}")
        if res.pbo is None:
            # Too few obs for a meaningful PBO -> N/A diagnostic, NOT danger. Power
            # is judged by MIN_LENGTH / the win-rate CI instead (FIX-1).
            return StageResult("PBO", WARN, tier=SHADOW, role="diagnostic",
                               detail={"pbo": None, "status": res.status},
                               message=f"PBO N/A ({res.status}: T too small) — leaning on win-rate CI")
        pbo = res.pbo
        if pbo >= self.cfg.pbo_danger:
            tier, st, note = REJECT, FAIL, "DANGER (>=0.50): IS-winner ~ random OOS"
        elif pbo >= self.cfg.pbo_no_deploy:
            tier, st, note = REJECT, FAIL, "no-deploy band (0.20-0.50)"
        elif pbo >= self.cfg.pbo_shadow:
            tier, st, note = SHADOW, WARN, "shadow band (0.10-0.20)"
        else:
            tier, st, note = SHIP, PASS, "acceptable (<0.10)"
        return StageResult("PBO", st, tier=tier, role="diagnostic",
                           detail={"pbo": pbo, "n_configs": res.n_configs,
                                   "n_combinations": res.n_combinations},
                           message=f"PBO={pbo:.3f} — {note}")

    def _stage_dsr(self, sr, skew, kurt, T) -> StageResult:
        # DIAGNOSTIC / SECONDARY (C1). FIX-3: variance from SCORED trials only
        # (never seeds at SR=0); the N hurdle uses the effective GLOBAL count
        # (seeds + family N_eff + scored).
        scored_sr = self.ledger.scored_sharpes()  # includes this candidate (recorded above).
        n_eff = self.ledger.effective_total_n()
        res = deflated_sharpe_ratio(sr, scored_sr, T=int(T), skew=skew, kurt=kurt,
                                    n_trials=int(round(n_eff)))
        dsr = res.dsr
        if dsr >= self.cfg.dsr_admit:
            tier, st, note = SHIP, PASS, f"admit (>={self.cfg.dsr_admit})"
        elif dsr >= self.cfg.dsr_shadow:
            tier, st, note = SHADOW, WARN, f"shadow ({self.cfg.dsr_shadow}-{self.cfg.dsr_admit})"
        else:
            tier, st, note = REJECT, FAIL, f"reject (<{self.cfg.dsr_shadow})"
        return StageResult("DSR", st, tier=tier, role="diagnostic",
                           detail={"dsr": dsr, "sr_observed": res.sr_observed,
                                   "sr0_benchmark": res.sr0, "n_trials": res.n_trials},
                           message=f"DSR={dsr:.3f} — {note}; SR {res.sr_observed:.3f} "
                                   f"vs E[max|N={res.n_trials}] {res.sr0:.3f}")

    def _stage_spa(self, cand: Candidate) -> StageResult:
        # HARD GATE: must beat the baseline (SOE A) on economic PnL, not zero.
        if cand.spa_returns is not None and cand.spa_baseline_returns is not None:
            cand_s, base_s = cand.spa_returns, cand.spa_baseline_returns
        else:
            cand_s, base_s = cand.returns, cand.baseline_returns
        if base_s is None:
            return StageResult("SPA", FAIL, tier=REJECT, role="gate",
                               message="no baseline series: cannot prove it beats SOE A")
        try:
            res = spa_beats_baseline(cand_s, base_s,
                                     alpha=self.cfg.spa_alpha, reps=self.cfg.spa_reps)
        except ValueError as e:
            return StageResult("SPA", WARN, tier=SHADOW, role="gate",
                               message=f"SPA not assessed: {e}")
        beats = res.beats_baseline
        return StageResult("SPA", PASS if beats else FAIL, tier=SHIP if beats else REJECT, role="gate",
                           detail={"pvalue_consistent": res.pvalue_consistent,
                                   "candidate_mean": res.candidate_mean,
                                   "baseline_mean": res.baseline_mean},
                           message=f"p={res.pvalue_consistent:.3f} (alpha {self.cfg.spa_alpha}); "
                                   f"mean {res.candidate_mean:+.4f} vs baseline {res.baseline_mean:+.4f}")

    def _stage_economic(self, cand: Candidate, r) -> StageResult:
        # HARD GATE: positive net expectancy + regime-robust + orthogonal.
        mean_ret = float(r.mean())
        detail = {"mean_return_net": mean_ret}
        notes = [f"mean net {mean_ret:+.4f}"]
        if mean_ret <= 0:
            return StageResult("ECONOMIC", FAIL, tier=REJECT, role="gate", detail=detail,
                               message=f"non-positive net expectancy ({mean_ret:+.4f})")

        checked = False
        if cand.regime_labels is not None:
            labels = np.asarray(cand.regime_labels)
            bad, buckets = [], {}
            for lab in set(labels.tolist()):
                seg = r[labels == lab]
                if seg.size >= self.cfg.min_regime_n:
                    m = float(seg.mean()); buckets[str(lab)] = m
                    if m <= 0:
                        bad.append(str(lab))
            detail["regime_means"] = buckets
            if bad:
                return StageResult("ECONOMIC", FAIL, tier=REJECT, role="gate", detail=detail,
                                   message=f"negative expectancy in regime(s): {', '.join(bad)}")
            if buckets:
                checked = True
                notes.append(f"regime-robust ({len(buckets)} buckets)")

        if cand.detector_returns:
            corrs, high = {}, []
            for name, series in cand.detector_returns.items():
                s = np.asarray(series, dtype=float)
                if s.shape[0] == r.shape[0] and s.std() > 0 and r.std() > 0:
                    c = float(np.corrcoef(r, s)[0, 1]); corrs[name] = c
                    if abs(c) > self.cfg.orthogonality_max_abs_corr:
                        high.append(f"{name}({c:+.2f})")
            detail["detector_correlations"] = corrs
            if high:
                return StageResult("ECONOMIC", FAIL, tier=REJECT, role="gate", detail=detail,
                                   message=f"too correlated with live detector(s): {', '.join(high)}")
            if corrs:
                checked = True
                notes.append("orthogonal to live detectors")

        if checked:
            return StageResult("ECONOMIC", PASS, tier=SHIP, role="gate", detail=detail,
                               message="; ".join(notes))
        return StageResult("ECONOMIC", WARN, tier=SHADOW, role="gate", detail=detail,
                           message="; ".join(notes) + " [regime & orthogonality NOT checked]")

    def _finish(self, cand, stages) -> GateReport:
        outcome = SHIP
        for s in stages:
            outcome = _worst(outcome, s.tier)
        drivers = [s.name for s in stages if s.tier == outcome] if outcome != SHIP else []
        return GateReport(
            card_id=cand.card.card_id,
            outcome=outcome,
            drivers=drivers,
            global_n_trials=self.ledger.count(),
            stages=stages,
        )


__all__ = [
    "TestCard", "Candidate", "GateConfig", "ValidationGate",
    "GateReport", "StageResult", "PASS", "FAIL", "WARN", "SKIP",
    "SHIP", "SHADOW", "REJECT",
]
