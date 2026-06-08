"""Deterministic tests for autoresearch/backtest_adapter.py (temp DB).

MUST run under the autoresearch venv (imports numpy + gate):
    .venv-autoresearch/Scripts/python scripts/test_backtest_adapter.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from autoresearch.backtest_adapter import (  # noqa: E402
    load_cohort, build_candidate, _same_day_horizon, _score_threshold_matrix,
    _daily_series,
)
from autoresearch.gate import TestCard  # noqa: E402

_COLS = ("alert_type TEXT, fired_at REAL, direction TEXT, score REAL, "
         "vix_at_alert REAL, spot_at_alert REAL, outcome_resolution_spot REAL, "
         "verdict_eod TEXT, outcome_status TEXT")


def _ts(day: str, hh: int = 10) -> float:
    return datetime(int(day[:4]), int(day[5:7]), int(day[8:10]), hh,
                    tzinfo=timezone.utc).timestamp()


def _make_db(rows) -> str:
    fd = tempfile.NamedTemporaryFile(prefix="adapter_", suffix=".db", delete=False)
    fd.close()
    con = sqlite3.connect(fd.name)
    con.execute(f"CREATE TABLE alert_outcomes ({_COLS})")
    con.executemany(
        "INSERT INTO alert_outcomes "
        "(alert_type,fired_at,direction,score,vix_at_alert,spot_at_alert,"
        " outcome_resolution_spot,verdict_eod,outcome_status) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return fd.name


def _row(at, day, direction, spot, resol, score=5.0, verdict="WIN",
         status="info_only", hh=10):
    return (at, _ts(day, hh), direction, score, None, spot, resol, verdict, status)


def test_directional_return_signs():
    rows = [
        _row("C", "2026-05-13", "BULL", 100.0, 102.0),   # +2% bull up -> +2
        _row("C", "2026-05-14", "BEAR", 100.0, 98.0),    # bear down -> +2
        _row("C", "2026-05-15", "BULL", 100.0, 95.0),    # bull down -> -5
    ]
    t = load_cohort(_make_db(rows), "C")
    rets = [round(x["ret"], 6) for x in t]
    assert rets == [2.0, 2.0, -5.0], rets


def test_excludes_pending_and_flat_and_nulls():
    rows = [
        _row("C", "2026-05-13", "BULL", 100, 101, verdict="WIN"),
        _row("C", "2026-05-13", "BULL", 100, 101, verdict="FLAT"),      # excluded
        _row("C", "2026-05-13", "BULL", 100, 101, verdict="WIN", status="pending"),  # excluded
        ("C", _ts("2026-05-13"), "BULL", 5.0, None, None, 101, "WIN", "info_only"),  # null spot
    ]
    t = load_cohort(_make_db(rows), "C")
    assert len(t) == 1, [x["verdict"] for x in t]


def test_same_day_horizon():
    days = ["2026-05-13", "2026-05-13", "2026-05-14", "2026-05-14", "2026-05-14"]
    # last index sharing each day: day13 -> idx1, day14 -> idx4.
    assert _same_day_horizon(days) == [1, 1, 4, 4, 4]


def test_score_threshold_matrix_shape_and_zeroing():
    rets = np.array([1.0, -2.0, 3.0, -1.0, 2.0])
    scores = [1.0, 2.0, 3.0, 4.0, 5.0]
    M = _score_threshold_matrix(rets, scores, n_configs=5)
    assert M is not None and M.shape[0] == 5 and M.shape[1] >= 2
    # The highest-threshold column keeps only the top-scoring trades (rest 0).
    # Column 0 (threshold=min) keeps everything.
    assert np.allclose(M[:, 0], rets)
    # Every entry is either the trade's return (kept) or 0 (dropped) — nothing else.
    assert np.all((M == 0) | (M == rets[:, None]))


def test_score_matrix_none_when_no_variation():
    rets = np.array([1.0, 2.0, 3.0])
    assert _score_threshold_matrix(rets, [5.0, 5.0, 5.0]) is None   # constant score
    assert _score_threshold_matrix(rets, [5.0, None, 5.0]) is None  # missing score


def test_daily_series_aggregates_and_fills():
    trades = [
        {"day": "2026-05-13", "ret": 1.0},
        {"day": "2026-05-13", "ret": 3.0},   # mean 2.0
        {"day": "2026-05-15", "ret": -4.0},
    ]
    grid = ["2026-05-13", "2026-05-14", "2026-05-15"]
    s = _daily_series(trades, grid)
    assert list(s) == [2.0, 0.0, -4.0]       # no-trade day -> 0


def test_build_candidate_assembles_arrays():
    rows = []
    for i in range(40):
        day = f"2026-05-{13 + (i % 5):02d}"
        rows.append(_row("CAND", day, "BULL", 100.0, 100.0 + (i % 7) - 3,
                         score=4.0 + (i % 5) * 0.3, hh=10 + (i % 6)))
    for i in range(30):
        day = f"2026-05-{13 + (i % 5):02d}"
        rows.append(_row("BASE", day, "BULL", 100.0, 100.0 + (i % 3) - 1, score=5.0))
    db = _make_db(rows)
    card = TestCard("t", "p", "claim text", "positive", "a real mechanism here",
                    "CAND", "kill when bad")
    cand, diag = build_candidate(card, "CAND", db_path=db, baseline_alert_type="BASE")
    assert diag["n_trades"] == 40
    assert cand.returns.shape[0] == 40
    assert cand.t1 is not None and len(cand.t1) == 40
    # SPA arrays exist, equal length, on the common day grid.
    assert cand.spa_returns is not None and cand.spa_baseline_returns is not None
    assert len(cand.spa_returns) == len(cand.spa_baseline_returns) == diag["spa_grid_days"]
    assert diag["return_proxy"] == "directional_spot_pct"


TESTS = [
    test_directional_return_signs,
    test_excludes_pending_and_flat_and_nulls,
    test_same_day_horizon,
    test_score_threshold_matrix_shape_and_zeroing,
    test_score_matrix_none_when_no_variation,
    test_daily_series_aggregates_and_fills,
    test_build_candidate_assembles_arrays,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - autoresearch/backtest_adapter.py")
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
