"""Acceptance test for the validation gate — the Phase 1 kill-criterion.

The deflation engine is only trustworthy if it PASSES a known-good signal and
REJECTS a known-overfit one. This suite proves both, then forces a targeted
rejection at EACH stage (card, dedup, min-length, CPCV, PBO, DSR, SPA, economic).

MUST run under the autoresearch venv:
    .venv-autoresearch/Scripts/python scripts/test_gate_acceptance.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from autoresearch.trials_ledger import TrialLedger  # noqa: E402
from autoresearch.gate import (  # noqa: E402
    TestCard, Candidate, GateConfig, ValidationGate, PASS, FAIL, WARN,
)


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #

def _tmp_ledger_path() -> str:
    fd = tempfile.NamedTemporaryFile(prefix="acc_ledger_", suffix=".json", delete=False)
    fd.close()
    p = Path(fd.name)
    p.unlink()
    return str(p)


def _seed_ledger(path: str, sharpes: list[float]) -> None:
    """Write a ledger file directly (fast pre-seed of global N)."""
    trials = [
        {"seq": i + 1, "trial_id": f"seed-{i+1:06d}", "recorded_at": 1_700_000_000.0,
         "label": "seed", "sharpe": float(s), "n_obs": 250,
         "skew": 0.0, "kurtosis": 3.0, "meta": {}}
        for i, s in enumerate(sharpes)
    ]
    Path(path).write_text(
        json.dumps({"schema": "autoresearch.trials_ledger/v1", "trials": trials}),
        encoding="utf-8",
    )


def _good_card(cid="EMA8-VIX-LOW") -> TestCard:
    return TestCard(
        card_id=cid,
        provenance="internal slice of alert_outcomes.db, VIX<20 cohort",
        claim="SOE A in low-VIX regime has higher net expectancy than baseline",
        expected_sign="positive",
        mechanism="dealer hedging is more mechanical in low-VIX so opening flow "
                  "leads spot more reliably",
        target_cohort="SOE_A & VIX<20",
        kill_criteria="rolling 60d Clopper-Pearson lower bound < 22.7% breakeven",
    )


def _genuine_returns(rng, T=1280, mean=0.12, sd=0.2):
    return rng.normal(mean, sd, T)


def _genuine_matrix(rng, T=1280, N=8, edge=0.12, sd=0.2, edge_col=0):
    M = rng.normal(0.0, sd, (T, N))
    M[:, edge_col] += edge
    return M


def _fast_cfg(**kw):
    base = dict(spa_reps=300)
    base.update(kw)
    return GateConfig(**base)


# --------------------------------------------------------------------------- #
# Headline: pass known-good, reject known-overfit.
# --------------------------------------------------------------------------- #

def test_known_good_PASSES():
    rng = np.random.default_rng(100)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.15, 0.18, 0.20, 0.16, 0.19])  # modest, low-dispersion prior trials.
    led = TrialLedger(path)

    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T)
    M[:, 0] = ret                                   # candidate IS the edge column.
    baseline = rng.normal(0.0, 0.2, T)              # baseline (SOE A) ~ flat.
    labels = np.array(["am"] * (T // 2) + ["pm"] * (T - T // 2))  # both regimes +EV.
    detector = rng.normal(0.0, 0.2, T)              # uncorrelated live detector.

    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=baseline, regime_labels=labels,
                     detector_returns={"king_migration": detector})
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    if not rep.passed:
        print(rep.summary())
    assert rep.passed is True, rep.rejected_at
    assert rep.rejected_at is None
    # Every stage that ran is PASS (economic may be PASS since enrichments present).
    assert all(s.status in (PASS, WARN) for s in rep.stages), rep.summary()


def test_known_overfit_REJECTED():
    rng = np.random.default_rng(101)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.2, 0.15])
    led = TrialLedger(path)

    T, N = 1280, 20
    M = rng.normal(0.0, 1.0, (T, N))                # pure noise search space.
    best_col = int(np.argmax(M.mean(axis=0)))       # the in-sample "winner".
    ret = M[:, best_col]                            # cherry-picked overfit candidate.
    baseline = rng.normal(0.0, 1.0, T)

    cand = Candidate(card=_good_card("NOISE-MINER"), returns=ret, config_matrix=M,
                     baseline_returns=baseline)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False, rep.summary()
    # It must die at a STATISTICAL overfit defense, not the card stage. A
    # cherry-picked-from-noise series has a tiny Sharpe, so it is legitimately
    # killed at MIN_LENGTH (track record too short for that Sharpe) before it even
    # reaches PBO — MinTRL is itself a selection-bias defense. CPCV/PBO/DSR are the
    # later defenses; the dedicated test_reject_pbo proves the PBO stage directly.
    assert rep.rejected_at in ("MIN_LENGTH", "CPCV", "PBO", "DSR"), rep.rejected_at


# --------------------------------------------------------------------------- #
# Targeted per-stage rejections.
# --------------------------------------------------------------------------- #

def test_reject_invalid_card():
    led = TrialLedger(_tmp_ledger_path())
    bad = _good_card()
    bad.mechanism = "    "                          # empty rationale.
    cand = Candidate(card=bad, returns=[0.1] * 100)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "TEST_CARD"
    assert led.count() == 0, "must NOT record a trial for a malformed card"


def test_reject_duplicate_card():
    led = TrialLedger(_tmp_ledger_path())
    existing = ["SOE A in low VIX regime has higher net expectancy than baseline"]
    cand = Candidate(card=_good_card(), returns=[0.1] * 100)
    rep = ValidationGate(led, _fast_cfg(), existing_claims=existing).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "TEST_CARD"
    assert "duplicate" in rep.stages[-1].message


def test_reject_min_length():
    rng = np.random.default_rng(102)
    led = TrialLedger(_tmp_ledger_path())
    ret = rng.normal(0.02, 0.3, 40)                 # weak SR, tiny T -> MinTRL huge.
    cand = Candidate(card=_good_card(), returns=ret)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "MIN_LENGTH", rep.summary()


def test_reject_cpcv():
    # Net-positive overall (passes MIN_LENGTH) but the edge is concentrated in ONE
    # group, so most combinatorial OOS test sets are negative -> median Sharpe < 0.
    rng = np.random.default_rng(103)
    led = TrialLedger(_tmp_ledger_path())
    T = 600
    ret = rng.normal(-0.02, 0.3, T)
    ret[:100] = rng.normal(0.5, 0.3, 100)           # only group 0 carries the gains.
    cand = Candidate(card=_good_card(), returns=ret)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "CPCV", rep.summary()


def test_reject_pbo():
    # Candidate series is a genuine stationary edge (clears MIN_LENGTH + CPCV) but
    # the searched config space is pure noise -> PBO ~ 0.5 -> overfitting flagged.
    rng = np.random.default_rng(104)
    led = TrialLedger(_tmp_ledger_path())
    _seed_ledger(led.path, [0.1, 0.15])
    T = 1280
    ret = _genuine_returns(rng, T)
    M = rng.normal(0.0, 1.0, (T, 20))               # noise search space.
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T))
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "PBO", rep.summary()


def test_reject_dsr_under_huge_global_n():
    # Same genuine edge, but a huge, high-dispersion global trial count inflates
    # E[max Sharpe | N] above the candidate's Sharpe -> DSR collapses.
    rng = np.random.default_rng(105)
    path = _tmp_ledger_path()
    _seed_ledger(path, list(rng.uniform(-1.0, 3.0, 800)))   # 800 prior trials, high var.
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T)
    M[:, 0] = ret
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T))
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "DSR", rep.summary()


def test_reject_spa_when_baseline_better():
    rng = np.random.default_rng(106)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.12])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T, mean=0.08, sd=0.2)
    M = _genuine_matrix(rng, T, edge=0.08)
    M[:, 0] = ret
    baseline = rng.normal(0.16, 0.2, T)             # baseline beats the candidate.
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=baseline)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "SPA", rep.summary()


def test_reject_economic_regime():
    rng = np.random.default_rng(107)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.12])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T, mean=0.12, sd=0.2)
    M = _genuine_matrix(rng, T)
    M[:, 0] = ret
    baseline = rng.normal(0.0, 0.2, T)
    # One regime bucket is net-negative even though overall expectancy is positive.
    labels = np.array(["bull"] * (T - 200) + ["bear"] * 200)
    ret = np.asarray(ret)
    ret[-200:] = rng.normal(-0.15, 0.2, 200)        # 'bear' regime loses money.
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=baseline, regime_labels=labels)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is False and rep.rejected_at == "ECONOMIC", rep.summary()
    assert "bear" in rep.stages[-1].message


def test_economic_warns_when_enrichments_missing():
    # A fully-passing candidate with NO regime/detector data -> ECONOMIC = WARN,
    # but the gate still PASSES overall (WARN is not FAIL).
    rng = np.random.default_rng(108)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.15, 0.18, 0.2])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T)
    M[:, 0] = ret
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T))
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.passed is True, rep.summary()
    assert rep.stages[-1].name == "ECONOMIC" and rep.stages[-1].status == WARN


def test_ledger_increments_per_evaluation():
    rng = np.random.default_rng(109)
    led = TrialLedger(_tmp_ledger_path())
    assert led.count() == 0
    for i in range(3):
        ret = rng.normal(0.02, 0.3, 50)             # rejected at MIN_LENGTH, but still counts.
        ValidationGate(led, _fast_cfg()).evaluate(
            Candidate(card=_good_card(f"c{i}"), returns=ret))
    assert led.count() == 3, "every backtest the gate runs must increment global N"


TESTS = [
    test_known_good_PASSES,
    test_known_overfit_REJECTED,
    test_reject_invalid_card,
    test_reject_duplicate_card,
    test_reject_min_length,
    test_reject_cpcv,
    test_reject_pbo,
    test_reject_dsr_under_huge_global_n,
    test_reject_spa_when_baseline_better,
    test_reject_economic_regime,
    test_economic_warns_when_enrichments_missing,
    test_ledger_increments_per_evaluation,
]


def main() -> int:
    print("=" * 72)
    print("ACCEPTANCE TESTS - autoresearch validation gate (Phase 1 kill-criterion)")
    print("=" * 72)
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  - {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  - {e!r}")
            failed += 1
    print("=" * 72)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
