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

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


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


@dataclass
class GateConfig:
    breakeven: float = 0.227
    dsr_min: float = 0.95
    pbo_max: float = 0.05
    spa_alpha: float = 0.05
    mintrl_prob: float = 0.95
    minbtl_target_sr: float = 1.0
    cpcv_groups: int = 6
    cpcv_k_test: int = 2
    cpcv_embargo_pct: float = 0.01
    cpcv_median_sharpe_min: float = 0.0
    pbo_blocks: int = 16
    orthogonality_max_abs_corr: float = 0.7
    spa_reps: int = 1000
    dedup_jaccard_max: float = 0.9
    min_regime_n: int = 20


# --------------------------------------------------------------------------- #
# Output.
# --------------------------------------------------------------------------- #

@dataclass
class StageResult:
    name: str
    status: str            # PASS / FAIL / WARN / SKIP.
    detail: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class GateReport:
    card_id: str
    passed: bool
    rejected_at: Optional[str]
    global_n_trials: int
    stages: list[StageResult] = field(default_factory=list)

    def summary(self) -> str:
        head = f"GATE [{self.card_id}]  ->  {'PASS' if self.passed else 'FAIL'}"
        if self.rejected_at:
            head += f"  (rejected at: {self.rejected_at})"
        head += f"   global N={self.global_n_trials}"
        lines = [head, "-" * 72]
        for s in self.stages:
            lines.append(f"  [{s.status:4s}] {s.name:18s} {s.message}")
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
                 existing_claims: Optional[list[str]] = None):
        self.ledger = ledger
        self.cfg = config or GateConfig()
        # Semantic-dedup corpus. Phase 1 uses token-Jaccard; embedding/AST dedup
        # (AlphaAgent-style) is a later upgrade — see PROJECT.md.
        self._existing = [_normalize_claim(c) for c in (existing_claims or [])]

    def evaluate(self, cand: Candidate) -> GateReport:
        stages: list[StageResult] = []
        rejected_at: Optional[str] = None

        def add(res: StageResult) -> bool:
            stages.append(res)
            return res.status != FAIL

        # --- Stage 0: TEST CARD + DEDUP (no stats yet) --------------------- #
        s0 = self._stage_card(cand)
        if not add(s0):
            return self._finish(cand, stages, "TEST_CARD")

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

        # --- Stage 1: MinTRL / MinBTL -------------------------------------- #
        if not add(self._stage_minlen(r, sr, skew, kurt, global_n)):
            return self._finish(cand, stages, "MIN_LENGTH")

        # --- Stage 2: CPCV OOS distribution -------------------------------- #
        if not add(self._stage_cpcv(r)):
            return self._finish(cand, stages, "CPCV")

        # --- Stage 3: PBO -------------------------------------------------- #
        if not add(self._stage_pbo(cand)):
            return self._finish(cand, stages, "PBO")

        # --- Stage 4: DSR -------------------------------------------------- #
        if not add(self._stage_dsr(sr, skew, kurt, r.size)):
            return self._finish(cand, stages, "DSR")

        # --- Stage 5: Hansen SPA vs baseline ------------------------------- #
        if not add(self._stage_spa(cand)):
            return self._finish(cand, stages, "SPA")

        # --- Stage 6: economic null ---------------------------------------- #
        if not add(self._stage_economic(cand, r)):
            return self._finish(cand, stages, "ECONOMIC")

        return self._finish(cand, stages, None)

    # --- stages ----------------------------------------------------------- #

    def _stage_card(self, cand: Candidate) -> StageResult:
        err = cand.card.validate()
        if err:
            return StageResult("TEST_CARD", FAIL, message=f"invalid card: {err}")
        claim = _normalize_claim(cand.card.claim)
        for prior in self._existing:
            j = _jaccard(claim, prior)
            if j >= self.cfg.dedup_jaccard_max:
                return StageResult("TEST_CARD", FAIL,
                                   detail={"jaccard": j},
                                   message=f"semantic duplicate of an existing card (Jaccard {j:.2f})")
        return StageResult("TEST_CARD", PASS, message="card complete, not a duplicate")

    def _stage_minlen(self, r, sr, skew, kurt, global_n) -> StageResult:
        T = int(r.size)
        mintrl = min_track_record_length(sr, skew, kurt, prob=self.cfg.mintrl_prob)
        minbtl = min_backtest_length(global_n, self.cfg.minbtl_target_sr)
        need = max(mintrl, minbtl)
        ok = T >= need
        msg = (f"T={T}, MinTRL={mintrl:.0f}, MinBTL(N={global_n})={minbtl:.0f}, "
               f"need>={need:.0f}")
        return StageResult("MIN_LENGTH", PASS if ok else FAIL,
                           detail={"T": T, "mintrl": mintrl, "minbtl": minbtl,
                                   "required": need, "global_n": global_n},
                           message=msg)

    def _stage_cpcv(self, r) -> StageResult:
        n = int(r.size)
        if n < self.cfg.cpcv_groups:
            return StageResult("CPCV", FAIL,
                               message=f"too few samples (n={n}) for {self.cfg.cpcv_groups} groups")
        splits = cpcv_splits(n, self.cfg.cpcv_groups, self.cfg.cpcv_k_test,
                             embargo_pct=self.cfg.cpcv_embargo_pct)
        sharpes = cpcv_oos_sharpes(r, splits)
        med = float(np.median(sharpes))
        frac_pos = float(np.mean(np.asarray(sharpes) > 0))
        ok = med > self.cfg.cpcv_median_sharpe_min
        return StageResult("CPCV", PASS if ok else FAIL,
                           detail={"n_paths": len(splits), "median_oos_sharpe": med,
                                   "frac_paths_positive": frac_pos},
                           message=f"{len(splits)} OOS paths, median Sharpe {med:+.3f}, "
                                   f"{frac_pos:.0%} positive")

    def _stage_pbo(self, cand: Candidate) -> StageResult:
        if cand.config_matrix is None:
            return StageResult("PBO", FAIL,
                               message="no config_matrix: cannot assess overfitting "
                                       "without the searched configuration space")
        M = np.asarray(cand.config_matrix, dtype=float)
        res = cscv_pbo(M, n_blocks=self.cfg.pbo_blocks)
        ok = res.pbo < self.cfg.pbo_max
        return StageResult("PBO", PASS if ok else FAIL,
                           detail={"pbo": res.pbo, "n_configs": res.n_configs,
                                   "n_combinations": res.n_combinations},
                           message=f"PBO={res.pbo:.3f} (max {self.cfg.pbo_max}) "
                                   f"over {res.n_configs} configs")

    def _stage_dsr(self, sr, skew, kurt, T) -> StageResult:
        all_sr = self.ledger.all_sharpes()  # includes this candidate (recorded above).
        res = deflated_sharpe_ratio(sr, all_sr, T=int(T), skew=skew, kurt=kurt)
        ok = res.dsr >= self.cfg.dsr_min
        return StageResult("DSR", PASS if ok else FAIL,
                           detail={"dsr": res.dsr, "sr_observed": res.sr_observed,
                                   "sr0_benchmark": res.sr0, "n_trials": res.n_trials},
                           message=f"DSR={res.dsr:.3f} (min {self.cfg.dsr_min}); "
                                   f"SR {res.sr_observed:.3f} vs E[max|N={res.n_trials}] {res.sr0:.3f}")

    def _stage_spa(self, cand: Candidate) -> StageResult:
        if cand.baseline_returns is None:
            return StageResult("SPA", FAIL,
                               message="no baseline_returns: cannot prove it beats SOE A")
        try:
            res = spa_beats_baseline(cand.returns, cand.baseline_returns,
                                     alpha=self.cfg.spa_alpha, reps=self.cfg.spa_reps)
        except ValueError as e:
            return StageResult("SPA", FAIL, message=f"SPA error: {e}")
        return StageResult("SPA", PASS if res.beats_baseline else FAIL,
                           detail={"pvalue_consistent": res.pvalue_consistent,
                                   "candidate_mean": res.candidate_mean,
                                   "baseline_mean": res.baseline_mean},
                           message=f"p={res.pvalue_consistent:.3f} (alpha {self.cfg.spa_alpha}); "
                                   f"mean {res.candidate_mean:+.4f} vs baseline {res.baseline_mean:+.4f}")

    def _stage_economic(self, cand: Candidate, r) -> StageResult:
        mean_ret = float(r.mean())
        detail = {"mean_return_net": mean_ret}
        notes = [f"mean net return {mean_ret:+.4f}"]
        if mean_ret <= 0:
            return StageResult("ECONOMIC", FAIL, detail=detail,
                               message=f"non-positive net expectancy ({mean_ret:+.4f})")

        # Regime robustness (optional enrichment).
        regime_status = SKIP
        if cand.regime_labels is not None:
            labels = np.asarray(cand.regime_labels)
            bad = []
            buckets = {}
            for lab in set(labels.tolist()):
                seg = r[labels == lab]
                if seg.size >= self.cfg.min_regime_n:
                    m = float(seg.mean())
                    buckets[str(lab)] = m
                    if m <= 0:
                        bad.append(str(lab))
            detail["regime_means"] = buckets
            if bad:
                return StageResult("ECONOMIC", FAIL, detail=detail,
                                   message=f"negative expectancy in regime(s): {', '.join(bad)}")
            regime_status = PASS if buckets else SKIP
            notes.append(f"regime-robust ({len(buckets)} buckets)" if buckets
                         else "regime split too thin")

        # Orthogonality to existing live detectors (optional enrichment).
        corr_status = SKIP
        if cand.detector_returns:
            corrs = {}
            high = []
            for name, series in cand.detector_returns.items():
                s = np.asarray(series, dtype=float)
                if s.shape[0] == r.shape[0] and s.std() > 0 and r.std() > 0:
                    c = float(np.corrcoef(r, s)[0, 1])
                    corrs[name] = c
                    if abs(c) > self.cfg.orthogonality_max_abs_corr:
                        high.append(f"{name}({c:+.2f})")
            detail["detector_correlations"] = corrs
            if high:
                return StageResult("ECONOMIC", FAIL, detail=detail,
                                   message=f"too correlated with live detector(s): {', '.join(high)}")
            corr_status = PASS if corrs else SKIP
            notes.append("orthogonal to live detectors" if corrs else "no aligned detector series")

        msg = "; ".join(notes)
        if regime_status == SKIP and corr_status == SKIP:
            return StageResult("ECONOMIC", WARN, detail=detail,
                               message=msg + " [regime & orthogonality NOT checked]")
        return StageResult("ECONOMIC", PASS, detail=detail, message=msg)

    def _finish(self, cand, stages, rejected_at) -> GateReport:
        passed = rejected_at is None
        return GateReport(
            card_id=cand.card.card_id,
            passed=passed,
            rejected_at=rejected_at,
            global_n_trials=self.ledger.count(),
            stages=stages,
        )


__all__ = [
    "TestCard", "Candidate", "GateConfig", "ValidationGate",
    "GateReport", "StageResult", "PASS", "FAIL", "WARN", "SKIP",
]
