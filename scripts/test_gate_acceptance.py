"""Acceptance test for the validation gate — the Phase 1 kill-criterion.

Updated for the C1 tiered model: the gate returns an OUTCOME in
{SHIP, SHADOW, REJECT}. SPA-beats-baseline + economic lift are the HARD gates;
PBO and DSR are DIAGNOSTIC bands that can cap the outcome (PBO>=0.50 / DSR<0.90 ->
REJECT) but are not sole gatekeepers. MIN_LENGTH no longer hard-quarantines a
positive edge — it caps at STAGING(SHADOW) until enough effective obs.

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
    TestCard, Candidate, GateConfig, ValidationGate, SHIP, SHADOW, REJECT,
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
    # These synthetic priors are EVALUATED trials with real Sharpes, so they go in
    # the v2 scored_trials register (they feed both Var(SR^) and N).
    trials = [
        {"seq": i + 1, "trial_id": f"prior-{i+1:06d}", "recorded_at": 1_700_000_000.0,
         "label": "prior", "sharpe": float(s), "n_obs": 250,
         "skew": 0.0, "kurtosis": 3.0, "meta": {}}
        for i, s in enumerate(sharpes)
    ]
    Path(path).write_text(
        json.dumps({"schema": "autoresearch.trials_ledger/v2", "n_independent_seeds": 0,
                    "scored_trials": trials, "family_matrices": {},
                    "audit_log": [], "seeded": False}),
        encoding="utf-8",
    )


def _good_card(cid="EMA8-VIX-LOW") -> TestCard:
    return TestCard(
        card_id=cid, provenance="internal slice of alert_outcomes.db",
        claim="this cohort has higher net expectancy than baseline",
        expected_sign="positive",
        mechanism="dealer hedging is more mechanical here so flow leads spot",
        target_cohort="some cohort", kill_criteria="rolling lower bound < breakeven",
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


def _full_good_candidate(rng, T=1280, cid="EMA8-VIX-LOW"):
    """A candidate that should clear every stage."""
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T)
    M[:, 0] = ret
    baseline = rng.normal(0.0, 0.2, T)
    labels = np.array(["am"] * (T // 2) + ["pm"] * (T - T // 2))
    detector = rng.normal(0.0, 0.2, T)
    return Candidate(card=_good_card(cid), returns=ret, config_matrix=M,
                     baseline_returns=baseline, regime_labels=labels,
                     detector_returns={"king_migration": detector})


# --------------------------------------------------------------------------- #
# Headline: SHIP a known-good, REJECT a known-overfit.
# --------------------------------------------------------------------------- #

def test_known_good_SHIPS():
    rng = np.random.default_rng(100)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.15, 0.18, 0.20, 0.16, 0.19])
    led = TrialLedger(path)
    rep = ValidationGate(led, _fast_cfg()).evaluate(_full_good_candidate(rng))
    if rep.outcome != SHIP:
        print(rep.summary())
    assert rep.outcome == SHIP, rep.drivers


def test_known_overfit_REJECTED():
    rng = np.random.default_rng(101)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.2, 0.15])
    led = TrialLedger(path)
    T, N = 1280, 20
    M = rng.normal(0.0, 1.0, (T, N))                # pure noise search space.
    ret = M[:, int(np.argmax(M.mean(axis=0)))]      # cherry-picked IS winner.
    cand = Candidate(card=_good_card("NOISE-MINER"), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 1.0, T))
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == REJECT, rep.summary()
    # The overfitting must be caught by a statistical stage (PBO danger / SPA / CPCV).
    assert any(d in ("PBO", "SPA", "CPCV", "DSR") for d in rep.drivers), rep.drivers


# --------------------------------------------------------------------------- #
# Card stage.
# --------------------------------------------------------------------------- #

def test_reject_invalid_card():
    led = TrialLedger(_tmp_ledger_path())
    bad = _good_card()
    bad.mechanism = "   "
    rep = ValidationGate(led, _fast_cfg()).evaluate(Candidate(card=bad, returns=[0.1] * 100))
    assert rep.outcome == REJECT and "TEST_CARD" in rep.drivers
    assert led.count() == 0, "must NOT record a trial for a malformed card"


def test_reject_duplicate_card():
    led = TrialLedger(_tmp_ledger_path())
    existing = ["this cohort has higher net expectancy than baseline"]
    rep = ValidationGate(led, _fast_cfg(), existing_claims=existing).evaluate(
        Candidate(card=_good_card(), returns=[0.1] * 100))
    assert rep.outcome == REJECT and "TEST_CARD" in rep.drivers
    assert "duplicate" in rep.stages[-1].message


# --------------------------------------------------------------------------- #
# MIN_LENGTH: negative edge -> REJECT; positive-but-thin -> SHADOW (not REJECT).
# --------------------------------------------------------------------------- #

def test_negative_edge_rejected_at_min_length():
    rng = np.random.default_rng(102)
    led = TrialLedger(_tmp_ledger_path())
    ret = rng.normal(-0.05, 0.3, 300)               # SR < 0.
    rep = ValidationGate(led, _fast_cfg()).evaluate(Candidate(card=_good_card(), returns=ret))
    assert rep.outcome == REJECT and "MIN_LENGTH" in rep.drivers, rep.summary()


def test_underpowered_positive_is_SHADOW_not_ship():
    # Genuine edge but T below the ship floor -> capped at STAGING(SHADOW), not SHIP,
    # not REJECT. (Everything else passes.)
    rng = np.random.default_rng(103)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.15, 0.18, 0.2])
    led = TrialLedger(path)
    T = 300                                          # < ship_min_obs (450).
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T); M[:, 0] = ret
    baseline = rng.normal(0.0, 0.2, T)
    labels = np.array(["am"] * 150 + ["pm"] * 150)
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=baseline, regime_labels=labels,
                     detector_returns={"d": rng.normal(0, 0.2, T)})
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == SHADOW, rep.summary()
    assert "MIN_LENGTH" in rep.drivers


# --------------------------------------------------------------------------- #
# Diagnostics drive REJECT at the right bands.
# --------------------------------------------------------------------------- #

def test_pbo_overfit_drives_reject():
    # Genuine series clears the hard gates, but the searched config space is the
    # textbook overfitting pathology: each config is tuned to a random subset of
    # time blocks (great there, terrible elsewhere), so the in-sample winner is
    # systematically the OOS loser -> PBO -> danger band -> REJECT.
    rng = np.random.default_rng(104)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.15])
    led = TrialLedger(path)
    S, block, N = 16, 80, 24
    T = S * block
    M = rng.normal(0.0, 0.1, (T, N))
    blk = np.arange(T) // block
    for j in range(N):
        fav = rng.choice(S, S // 2, replace=False)
        favmask = np.isin(blk, fav)
        M[favmask, j] += 1.0
        M[~favmask, j] -= 1.0
    ret = _genuine_returns(rng, T)
    labels = np.array(["am"] * (T // 2) + ["pm"] * (T - T // 2))
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T), regime_labels=labels,
                     detector_returns={"d": rng.normal(0, 0.2, T)})
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == REJECT and "PBO" in rep.drivers, rep.summary()
    pbo = [s for s in rep.stages if s.name == "PBO"][0].detail["pbo"]
    assert pbo >= 0.20, f"expected high PBO, got {pbo}"


def test_dsr_reject_under_huge_global_n():
    rng = np.random.default_rng(105)
    path = _tmp_ledger_path()
    _seed_ledger(path, list(rng.uniform(-1.0, 3.0, 800)))   # huge, high-variance N.
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T); M[:, 0] = ret
    labels = np.array(["am"] * 640 + ["pm"] * 640)
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T), regime_labels=labels,
                     detector_returns={"d": rng.normal(0, 0.2, T)})
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == REJECT and "DSR" in rep.drivers, rep.summary()


# --------------------------------------------------------------------------- #
# Hard gates: SPA + economic.
# --------------------------------------------------------------------------- #

def test_spa_reject_when_baseline_better():
    rng = np.random.default_rng(106)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.12])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T, mean=0.08)
    M = _genuine_matrix(rng, T, edge=0.08); M[:, 0] = ret
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.16, 0.2, T))   # baseline wins.
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == REJECT and "SPA" in rep.drivers, rep.summary()


def test_economic_regime_reject():
    rng = np.random.default_rng(107)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.1, 0.12])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T); M[:, 0] = ret
    labels = np.array(["bull"] * (T - 200) + ["bear"] * 200)
    ret = np.asarray(ret); ret[-200:] = rng.normal(-0.15, 0.2, 200)  # bear loses.
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T), regime_labels=labels)
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == REJECT and "ECONOMIC" in rep.drivers, rep.summary()
    assert "bear" in rep.stages[-1].message


def test_economic_shadow_when_enrichments_missing():
    # Clears hard gates but no regime/detector data -> ECONOMIC SHADOW -> overall
    # SHADOW (capped), NOT SHIP, NOT REJECT.
    rng = np.random.default_rng(108)
    path = _tmp_ledger_path()
    _seed_ledger(path, [0.15, 0.18, 0.2])
    led = TrialLedger(path)
    T = 1280
    ret = _genuine_returns(rng, T)
    M = _genuine_matrix(rng, T); M[:, 0] = ret
    cand = Candidate(card=_good_card(), returns=ret, config_matrix=M,
                     baseline_returns=rng.normal(0.0, 0.2, T))
    rep = ValidationGate(led, _fast_cfg()).evaluate(cand)
    assert rep.outcome == SHADOW, rep.summary()
    assert "ECONOMIC" in rep.drivers


def test_ledger_increments_per_evaluation():
    rng = np.random.default_rng(109)
    led = TrialLedger(_tmp_ledger_path())
    for i in range(3):
        ret = rng.normal(0.02, 0.3, 50)
        ValidationGate(led, _fast_cfg()).evaluate(
            Candidate(card=_good_card(f"c{i}"), returns=ret))
    assert led.count() == 3, "every backtest the gate runs must increment global N"


TESTS = [
    test_known_good_SHIPS,
    test_known_overfit_REJECTED,
    test_reject_invalid_card,
    test_reject_duplicate_card,
    test_negative_edge_rejected_at_min_length,
    test_underpowered_positive_is_SHADOW_not_ship,
    test_pbo_overfit_drives_reject,
    test_dsr_reject_under_huge_global_n,
    test_spa_reject_when_baseline_better,
    test_economic_regime_reject,
    test_economic_shadow_when_enrichments_missing,
    test_ledger_increments_per_evaluation,
]


def main() -> int:
    print("=" * 72)
    print("ACCEPTANCE TESTS - validation gate (C1 tiered model)")
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
