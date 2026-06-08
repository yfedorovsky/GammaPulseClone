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
_SCHEMA = "autoresearch.trials_ledger/v1"


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
            return {"schema": _SCHEMA, "trials": [], "audit_log": [], "seeded": False}
        with self._lock_free_open(p) as fh:
            doc = json.load(fh)
        if doc.get("schema") != _SCHEMA:
            raise ValueError(f"ledger schema mismatch at {self.path}: {doc.get('schema')!r}")
        doc.setdefault("trials", [])
        doc.setdefault("audit_log", [])
        doc.setdefault("seeded", False)
        return doc

    def _trials_list(self) -> list[dict]:
        return self._read_doc()["trials"]

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

    # --- public API --------------------------------------------------------

    def count(self) -> int:
        """Global N: total trials ever recorded (seeds + formal experiments)."""
        return len(self._trials_list())

    def trials(self) -> list[Trial]:
        return [Trial(**t) for t in self._trials_list()]

    def all_sharpes(self) -> list[float]:
        """Every recorded Sharpe — used for the cross-trial variance in DSR."""
        return [float(t["sharpe"]) for t in self._trials_list()]

    def audit_log(self) -> list[dict]:
        return list(self._read_doc()["audit_log"])

    def record(self, label: str, sharpe: float, n_obs: int,
               *, skew: Optional[float] = None, kurtosis: Optional[float] = None,
               trial_id: Optional[str] = None, meta: Optional[dict] = None,
               family: Optional[str] = None) -> Trial:
        """Append ONE formally-scored experiment and return it. Increments N.

        This is the SINGLE increment point for the global trial count. Only
        formal, logged experiments that reach numerical scoring belong here — NOT
        LLM brainstorming (C4). ``family`` groups near-duplicate variants for the
        effective-N (N_eff) deflation.
        """
        with self._lock:
            doc = self._read_doc()
            trials = doc["trials"]
            seq = len(trials) + 1
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
            trials.append(asdict(tr))
            self._write_doc(doc)
            return tr

    # --- C4: seeding + effective-N + throughput ----------------------------

    def seed(self, n: int, reason: str, *, sharpe: float = 0.0) -> int:
        """Seed the GLOBAL trial count with prior ad-hoc search (C4).

        Documents, once, that ~N scored backtests + the cross-LLM rounds preceded
        this loop, so the DSR/MinBTL hurdle does not pretend the program started
        from zero trials. Idempotent: re-seeding is a no-op (audited). Returns the
        number of seed trials actually added.
        """
        with self._lock:
            doc = self._read_doc()
            if doc.get("seeded"):
                doc["audit_log"].append(
                    {"action": "seed_skipped", "reason": reason, "at": self._clock(),
                     "note": "already seeded"})
                self._write_doc(doc)
                return 0
            trials = doc["trials"]
            base = len(trials)
            for i in range(int(n)):
                seq = base + i + 1
                trials.append(asdict(Trial(
                    seq=seq, trial_id=f"seed-{seq:06d}", recorded_at=self._clock(),
                    label="seed", sharpe=float(sharpe), n_obs=0,
                    meta={"seed": True, "family": "seed"})))
            doc["seeded"] = True
            doc["audit_log"].append(
                {"action": "seed", "n": int(n), "reason": reason, "at": self._clock()})
            self._write_doc(doc)
            return int(n)

    def count_by_family(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self._trials_list():
            fam = (t.get("meta") or {}).get("family") or t.get("label") or "?"
            out[fam] = out.get(fam, 0) + 1
        return out

    def effective_n(self, correlation: Optional[Sequence[Sequence[float]]] = None) -> float:
        """Effective number of INDEPENDENT trials (N_eff).

        With a trial-by-trial ``correlation`` matrix (e.g. of return vectors), uses
        the participation ratio (sum λ)^2 / sum(λ^2) of its eigenvalues — so a
        cluster of near-duplicate variants collapses toward one independent trial.
        Without a matrix, falls back to the number of distinct trial families
        (a conservative cluster count). N_eff feeds the deflation N so re-running
        correlated variants does not permanently lock the DSR gate.
        """
        if correlation is not None:
            import numpy as _np  # lazy: keep the stdlib import surface clean.
            C = _np.asarray(correlation, dtype=float)
            if C.ndim != 2 or C.shape[0] != C.shape[1] or C.shape[0] == 0:
                raise ValueError("correlation must be a non-empty square matrix")
            lam = _np.linalg.eigvalsh(C)
            lam = _np.clip(lam, 0.0, None)
            denom = float((lam ** 2).sum())
            if denom <= 0:
                return float(C.shape[0])
            return float((lam.sum() ** 2) / denom)
        return float(len(self.count_by_family()))

    def throughput_remaining(self, family: str, cap: int) -> int:
        """Remaining full-gate slots for a signal family vs a per-period cap (C4).

        The follow-up caps full-gate throughput to a single-digit number of
        materially-distinct candidates per family per quarter; everything else
        stays in cheap triage. Returns max(0, cap - formal trials in `family`).
        """
        used = self.count_by_family().get(family, 0)
        return max(0, int(cap) - used)


__all__ = ["Trial", "TrialLedger", "DEFAULT_LEDGER_PATH"]
