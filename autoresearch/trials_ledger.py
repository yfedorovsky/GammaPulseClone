"""Global N-trials ledger — the spine of the deflation engine.

Every backtest the AutoResearch loop EVER runs must be recorded here. The
Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014) deflates an observed
Sharpe against ``E[max Sharpe | N independent trials]`` — where **N is the
global, cumulative trial count across the whole research program**, NOT a
per-signal count. Under-counting N is the single most common way a research loop
fools itself: it makes every Sharpe look more significant than it is.

The ledger therefore stores, per trial:
  - the observed Sharpe (so DSR can also use the cross-trial *variance* of Sharpes,
    which the E[max] estimator needs),
  - the sample length T behind that Sharpe,
  - sk/ kurt if known, plus free-form provenance.

Design notes:
  - Pure stdlib (JSON file). Lives in ``autoresearch/`` (gitignored runtime state),
    NEVER in the live trading DB. ``path`` is overridable for tests.
  - Append is read-modify-write with an atomic ``os.replace``. The offline loop is
    single-writer; an in-process lock guards threads. (Not a multi-process DB.)
  - A monotonic ``seq`` is the authoritative trial index; ``count()`` == len.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

# Runtime ledger path (gitignored). Tests pass an explicit temp path.
DEFAULT_LEDGER_PATH = str(Path(__file__).resolve().parent / "trials_ledger.json")
_SCHEMA = "autoresearch.trials_ledger/v2"   # v2: three-register model (FIX-3).


@dataclass
class Trial:
    """One recorded backtest trial."""
    seq: int                 # 1-based monotonic global trial index.
    trial_id: str            # human/label id (provenance), need not be unique.
    recorded_at: float       # unix seconds (UTC).
    label: str               # signal / cohort / hypothesis-card identifier.
    sharpe: float            # observed Sharpe of this trial's return series.
    n_obs: int               # T: number of returns behind `sharpe`.
    skew: Optional[float] = None
    kurtosis: Optional[float] = None   # NON-excess (normal == 3.0) by convention.
    meta: dict = field(default_factory=dict)


class TrialLedger:
    """Append-only, persistent global trial registry."""

    def __init__(self, path: str = DEFAULT_LEDGER_PATH,
                 clock: Optional[Callable[[], float]] = None):
        self.path = str(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._lock = threading.Lock()

    # --- persistence -------------------------------------------------------

    @staticmethod
    def _lock_free_open(p: Path):
        return open(p, "r", encoding="utf-8")

    def _read_doc(self) -> dict:
        p = Path(self.path)
        if not p.exists():
            return {"schema": _SCHEMA, "n_independent_seeds": 0, "scored_trials": [],
                    "family_matrices": {}, "audit_log": [], "seeded": False}
        with self._lock_free_open(p) as fh:
            doc = json.load(fh)
        if doc.get("schema") != _SCHEMA:
            raise ValueError(f"ledger schema mismatch at {self.path}: {doc.get('schema')!r}")
        doc.setdefault("n_independent_seeds", 0)
        doc.setdefault("scored_trials", [])
        doc.setdefault("family_matrices", {})
        doc.setdefault("audit_log", [])
        doc.setdefault("seeded", False)
        return doc

    def _scored(self) -> list[dict]:
        return self._read_doc()["scored_trials"]

    def _write_doc(self, doc: dict) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc["schema"] = _SCHEMA
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)  # atomic on POSIX and Windows.

    # --- public API (FIX-3 three-register model) ---------------------------
    #
    #   n_independent_seeds : count of distinct prior searches (face value).
    #                         Adds to N in E[max SR|N] but NEVER to Var(SR).
    #   scored_trials       : Sharpes of ACTUALLY-evaluated hypotheses. The ONLY
    #                         source of Var(SR^) — seeds at SR=0 must never corrupt it.
    #   family_matrices     : per-family (T x M) SR arrays for correlated sweeps;
    #                         each family contributes a participation-ratio N_eff.

    def count(self) -> int:
        """Face-value global N: seeds + scored trials + family sweep members."""
        doc = self._read_doc()
        fam_members = sum(len(m[0]) if m and isinstance(m[0], list) else 0
                          for m in doc["family_matrices"].values())
        return int(doc["n_independent_seeds"]) + len(doc["scored_trials"]) + fam_members

    def n_independent_seeds(self) -> int:
        return int(self._read_doc()["n_independent_seeds"])

    def trials(self) -> list[Trial]:
        """Scored (actually-evaluated) trials only."""
        return [Trial(**t) for t in self._scored()]

    def scored_sharpes(self) -> list[float]:
        """Sharpes of evaluated hypotheses — the ONLY source of Var(SR^) (FIX-3)."""
        return [float(t["sharpe"]) for t in self._scored()]

    # Backward-compat alias; now means "scored sharpes" (seeds are NOT included).
    def all_sharpes(self) -> list[float]:
        return self.scored_sharpes()

    def audit_log(self) -> list[dict]:
        return list(self._read_doc()["audit_log"])

    def record(self, label: str, sharpe: float, n_obs: int,
               *, skew: Optional[float] = None, kurtosis: Optional[float] = None,
               trial_id: Optional[str] = None, meta: Optional[dict] = None,
               family: Optional[str] = None) -> Trial:
        """Append ONE formally-scored experiment to the Var register. Increments N.

        The SINGLE increment point for evaluated hypotheses. Only formal, logged
        experiments that reach numerical scoring belong here — NOT LLM brainstorming
        and NOT seeds.
        """
        with self._lock:
            doc = self._read_doc()
            scored = doc["scored_trials"]
            seq = len(scored) + 1
            m = dict(meta or {})
            if family is not None:
                m["family"] = family
            tr = Trial(
                seq=seq, trial_id=trial_id or f"trial-{seq:06d}",
                recorded_at=self._clock(), label=label, sharpe=float(sharpe),
                n_obs=int(n_obs),
                skew=None if skew is None else float(skew),
                kurtosis=None if kurtosis is None else float(kurtosis),
                meta=m,
            )
            scored.append(asdict(tr))
            self._write_doc(doc)
            return tr

    def seed(self, n: int, reason: str) -> int:
        """Seed N_independent_seeds with prior ad-hoc search (C4/FIX-3).

        Documents, once, that ~N scored backtests + the cross-LLM rounds preceded
        this loop. Seeds add to N in E[max SR|N] but contribute **0 to the Var
        register** — they are a COUNT, not Sharpes (seeds at SR=0 corrupting Var was
        the bug). Idempotent: re-seeding is an audited no-op. Returns N added.
        """
        with self._lock:
            doc = self._read_doc()
            if doc.get("seeded"):
                doc["audit_log"].append(
                    {"action": "seed_skipped", "reason": reason, "at": self._clock(),
                     "note": "already seeded"})
                self._write_doc(doc)
                return 0
            doc["n_independent_seeds"] = int(doc["n_independent_seeds"]) + int(n)
            doc["seeded"] = True
            doc["audit_log"].append(
                {"action": "seed", "n": int(n), "reason": reason, "at": self._clock()})
            self._write_doc(doc)
            return int(n)

    def register_family(self, family: str, sr_matrix: Sequence[Sequence[float]]) -> None:
        """Register a correlated parameter-sweep family as a (T x M) SR matrix.

        Correlated sweeps go HERE (not as M individual scored trials), so the family
        contributes only its participation-ratio N_eff to the global N — not M.
        """
        with self._lock:
            doc = self._read_doc()
            doc["family_matrices"][family] = [list(map(float, row)) for row in sr_matrix]
            self._write_doc(doc)

    @staticmethod
    def _participation_ratio_from_matrix(mat: list) -> float:
        """N_eff = (Σλ)²/Σλ² of the column-correlation matrix of a (T x M) SR array."""
        import numpy as _np
        A = _np.asarray(mat, dtype=float)
        if A.ndim != 2 or A.shape[1] == 0:
            return 0.0
        M = A.shape[1]
        if M == 1:
            return 1.0
        C = _np.corrcoef(A, rowvar=False)
        C = _np.nan_to_num(C, nan=0.0)
        lam = _np.clip(_np.linalg.eigvalsh(C), 0.0, None)
        denom = float((lam ** 2).sum())
        return float((lam.sum() ** 2) / denom) if denom > 0 else float(M)

    def family_neff(self) -> dict[str, float]:
        doc = self._read_doc()
        return {fam: self._participation_ratio_from_matrix(mat)
                for fam, mat in doc["family_matrices"].items()}

    def effective_total_n(self) -> float:
        """Final N for DSR = seeds + Σ_family N_eff + #scored standalone trials (FIX-3)."""
        doc = self._read_doc()
        fam = sum(self._participation_ratio_from_matrix(m)
                  for m in doc["family_matrices"].values())
        return float(doc["n_independent_seeds"]) + fam + len(doc["scored_trials"])

    def effective_n(self, correlation: Optional[Sequence[Sequence[float]]] = None) -> float:
        """Participation-ratio N_eff of a correlation matrix, or the global
        ``effective_total_n()`` when no matrix is given.

        Unlike the old version, this NEVER family-collapses independent seeds — only
        a registered, structurally-dependent sweep (via its correlation matrix)
        reduces below face value (FIX-3).
        """
        if correlation is not None:
            import numpy as _np
            C = _np.asarray(correlation, dtype=float)
            if C.ndim != 2 or C.shape[0] != C.shape[1] or C.shape[0] == 0:
                raise ValueError("correlation must be a non-empty square matrix")
            lam = _np.clip(_np.linalg.eigvalsh(C), 0.0, None)
            denom = float((lam ** 2).sum())
            return float((lam.sum() ** 2) / denom) if denom > 0 else float(C.shape[0])
        return self.effective_total_n()

    def count_by_family(self) -> dict[str, int]:
        """Scored-trial counts per family tag (standalone evaluations)."""
        out: dict[str, int] = {}
        for t in self._scored():
            fam = (t.get("meta") or {}).get("family") or t.get("label") or "?"
            out[fam] = out.get(fam, 0) + 1
        return out

    def throughput_remaining(self, family: str, cap: int) -> int:
        """Remaining full-gate slots for a family vs a per-period cap (C4)."""
        used = self.count_by_family().get(family, 0)
        return max(0, int(cap) - used)


__all__ = ["Trial", "TrialLedger", "DEFAULT_LEDGER_PATH"]
