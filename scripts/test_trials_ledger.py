"""Deterministic tests for autoresearch/trials_ledger.py.

Usage:
    python scripts/test_trials_ledger.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.trials_ledger import TrialLedger, Trial  # noqa: E402


def _tmp_path() -> str:
    fd = tempfile.NamedTemporaryFile(prefix="ledger_", suffix=".json", delete=False)
    fd.close()
    p = Path(fd.name)
    p.unlink()  # start from "does not exist"
    return str(p)


def _fixed_clock():
    return 1_700_000_000.0


def test_empty_count_zero():
    led = TrialLedger(_tmp_path())
    assert led.count() == 0
    assert led.trials() == []
    assert led.all_sharpes() == []


def test_record_increments_global_n():
    led = TrialLedger(_tmp_path(), clock=_fixed_clock)
    led.record("sigA", sharpe=1.2, n_obs=200)
    led.record("sigA", sharpe=0.9, n_obs=200)   # SAME label -> N still increments.
    led.record("sigB", sharpe=2.0, n_obs=120)
    assert led.count() == 3, "N is GLOBAL, not per-label"


def test_seq_monotonic_and_ids():
    led = TrialLedger(_tmp_path(), clock=_fixed_clock)
    t1 = led.record("x", 1.0, 100)
    t2 = led.record("y", 1.0, 100)
    assert (t1.seq, t2.seq) == (1, 2)
    assert t1.trial_id == "trial-000001" and t2.trial_id == "trial-000002"


def test_persistence_across_instances():
    path = _tmp_path()
    a = TrialLedger(path, clock=_fixed_clock)
    a.record("x", 1.5, 200, skew=-0.4, kurtosis=5.0, meta={"card": "c1"})
    b = TrialLedger(path)  # fresh instance, same file
    assert b.count() == 1
    tr = b.trials()[0]
    assert tr.label == "x" and tr.sharpe == 1.5 and tr.n_obs == 200
    assert tr.skew == -0.4 and tr.kurtosis == 5.0 and tr.meta["card"] == "c1"


def test_all_sharpes_collects_all():
    led = TrialLedger(_tmp_path(), clock=_fixed_clock)
    for s in (0.5, 1.0, 1.5, -0.2):
        led.record("s", s, 100)
    assert led.all_sharpes() == [0.5, 1.0, 1.5, -0.2]


def test_recorded_at_uses_clock():
    led = TrialLedger(_tmp_path(), clock=_fixed_clock)
    tr = led.record("x", 1.0, 100)
    assert tr.recorded_at == _fixed_clock()


def test_custom_trial_id_preserved():
    led = TrialLedger(_tmp_path(), clock=_fixed_clock)
    tr = led.record("x", 1.0, 100, trial_id="EMA8-VIX<20-2026Q2")
    assert tr.trial_id == "EMA8-VIX<20-2026Q2"
    # seq is still authoritative/monotonic regardless of custom id.
    assert tr.seq == 1


def test_schema_mismatch_raises():
    path = _tmp_path()
    Path(path).write_text('{"schema": "bogus/v9", "trials": []}', encoding="utf-8")
    led = TrialLedger(path)
    try:
        led.count()
    except ValueError as e:
        assert "schema mismatch" in str(e)
    else:
        raise AssertionError("expected ValueError on schema mismatch")


def test_atomic_no_tmp_left_behind():
    path = _tmp_path()
    led = TrialLedger(path, clock=_fixed_clock)
    led.record("x", 1.0, 100)
    assert not Path(path + ".tmp").exists(), "temp file should be renamed away"
    assert Path(path).exists()


TESTS = [
    test_empty_count_zero,
    test_record_increments_global_n,
    test_seq_monotonic_and_ids,
    test_persistence_across_instances,
    test_all_sharpes_collects_all,
    test_recorded_at_uses_clock,
    test_custom_trial_id_preserved,
    test_schema_mismatch_raises,
    test_atomic_no_tmp_left_behind,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - autoresearch/trials_ledger.py")
    print("=" * 70)
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
    print("=" * 70)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
