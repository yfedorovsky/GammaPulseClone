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
from typing import Callable, Optional

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

    def _load(self) -> list[dict]:
        p = Path(self.path)
        if not p.exists():
            return []
        with self._lock_free_open(p) as fh:
            doc = json.load(fh)
        if doc.get("schema") != _SCHEMA:
            raise ValueError(f"ledger schema mismatch at {self.path}: {doc.get('schema')!r}")
        return doc.get("trials", [])

    @staticmethod
    def _lock_free_open(p: Path):
        return open(p, "r", encoding="utf-8")

    def _save(self, trials: list[dict]) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema": _SCHEMA, "trials": trials}
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)  # atomic on POSIX and Windows.

    # --- public API --------------------------------------------------------

    def count(self) -> int:
        """Global N: total trials ever recorded."""
        return len(self._load())

    def trials(self) -> list[Trial]:
        return [Trial(**t) for t in self._load()]

    def all_sharpes(self) -> list[float]:
        """Every recorded Sharpe — used for the cross-trial variance in DSR."""
        return [float(t["sharpe"]) for t in self._load()]

    def record(self, label: str, sharpe: float, n_obs: int,
               *, skew: Optional[float] = None, kurtosis: Optional[float] = None,
               trial_id: Optional[str] = None, meta: Optional[dict] = None) -> Trial:
        """Append one trial and return it. Increments the global counter.

        This is the SINGLE increment point for N. Anything that runs a backtest
        must funnel through here so the deflation math sees the true global N.
        """
        with self._lock:
            existing = self._load()
            seq = len(existing) + 1
            tr = Trial(
                seq=seq,
                trial_id=trial_id or f"trial-{seq:06d}",
                recorded_at=self._clock(),
                label=label,
                sharpe=float(sharpe),
                n_obs=int(n_obs),
                skew=None if skew is None else float(skew),
                kurtosis=None if kurtosis is None else float(kurtosis),
                meta=dict(meta or {}),
            )
            existing.append(asdict(tr))
            self._save(existing)
            return tr


__all__ = ["Trial", "TrialLedger", "DEFAULT_LEDGER_PATH"]
