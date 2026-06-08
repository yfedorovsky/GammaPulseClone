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
    load_cohort, load_clusters_economic, build_candidate, _same_day_horizon,
    _score_threshold_matrix, _daily_series,
)
from autoresearch.gate import TestCard  # noqa: E402
from autoresearch.option_pnl import Bar  # noqa: E402


class _FakeNBBO:
    """Returns the same bars for any contract -> deterministic +20% EOD PnL."""
    def bars(self, ticker, expiration, strike, right, date):
        return [Bar("09:31", 1.9, 2.0), Bar("15:59", 2.4, 2.5)]  # entry ask 2.0, exit bid 2.4

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
    assert diag["n_units"] == 40                       # spot path (no source).
    assert cand.returns.shape[0] == 40
    assert cand.t1 is not None and len(cand.t1) == 40
    # SPA arrays exist, equal length, on the common day grid.
    assert cand.spa_returns is not None and cand.spa_baseline_returns is not None
    assert len(cand.spa_returns) == len(cand.spa_baseline_returns) == diag["spa_grid_days"]
    assert diag["return_proxy"] == "directional_spot_pct" and diag["unit"] == "alert"


_ECON_COLS = ("alert_type TEXT, fired_at REAL, ticker TEXT, direction TEXT, "
              "strike REAL, expiration TEXT, option_type TEXT, score REAL, "
              "verdict_eod TEXT, outcome_status TEXT")


def _make_econ_db(rows) -> str:
    fd = tempfile.NamedTemporaryFile(prefix="econ_", suffix=".db", delete=False)
    fd.close()
    con = sqlite3.connect(fd.name)
    con.execute(f"CREATE TABLE alert_outcomes ({_ECON_COLS})")
    con.executemany(
        "INSERT INTO alert_outcomes (alert_type,fired_at,ticker,direction,strike,"
        "expiration,option_type,score,verdict_eod,outcome_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return fd.name


def _erow(at, day, ticker, direction, strike, score=5.0, hh=13):
    # hh=13 UTC -> 09:00 ET, so the 09:31 fake bar is the entry.
    return (at, _ts(day, hh), ticker, direction, strike, "2026-06-18", "call",
            score, "WIN", "info_only")


def test_clusters_collapse_alerts_to_decisions():
    # 6 alerts -> 3 economic clusters: (A,d13,BULL)x3, (A,d14,BULL)x1, (B,d13,BEAR)x2.
    rows = [
        _erow("C", "2026-05-13", "A", "BULL", 100, hh=13),
        _erow("C", "2026-05-13", "A", "BULL", 101, hh=14),
        _erow("C", "2026-05-13", "A", "BULL", 102, hh=15),
        _erow("C", "2026-05-14", "A", "BULL", 100, hh=13),
        _erow("C", "2026-05-13", "B", "BEAR", 50, hh=13),
        _erow("C", "2026-05-13", "B", "BEAR", 51, hh=14),
    ]
    clusters, cov = load_clusters_economic(_make_econ_db(rows), "C", _FakeNBBO())
    assert len(clusters) == 3, [(c["ticker"], c["day"], c["direction"]) for c in clusters]
    assert cov["n_alerts_total"] == 6 and cov["n_clusters_with_data"] == 3
    # Each cluster's realized outcome is the fake +20% EOD / 50% risk = +0.4 R.
    for c in clusters:
        assert abs(c["ret"] - 0.4) < 1e-9, c
    big = [c for c in clusters if c["ticker"] == "A" and c["day"] == "2026-05-13"][0]
    assert big["n_alerts"] == 3


def test_build_candidate_economic_mode():
    rows = []
    for i in range(12):
        rows.append(_erow("CAND", f"2026-05-{13 + (i % 4):02d}", f"T{i%6}", "BULL",
                           100 + i, score=4.0 + (i % 5) * 0.2))
    for i in range(8):
        rows.append(_erow("BASE", f"2026-05-{13 + (i % 4):02d}", f"B{i%4}", "BULL", 50 + i))
    db = _make_econ_db(rows)
    card = TestCard("t", "p", "claim", "positive", "a real mechanism here", "CAND", "kill")
    cand, diag = build_candidate(card, "CAND", db_path=db, baseline_alert_type="BASE",
                                 source=_FakeNBBO(), return_mode="option_pnl")
    assert diag["unit"] == "cluster"
    assert diag["return_proxy"] == "option_pnl_r_multiple"
    assert diag["coverage"]["n_alerts_total"] == 12
    assert cand.returns.shape[0] == diag["n_units"] >= 1
    assert cand.spa_returns is not None and len(cand.spa_returns) == diag["spa_grid_days"]


def test_economic_limit_caps_clusters():
    rows = [_erow("C", f"2026-05-{13 + i:02d}", "A", "BULL", 100 + i) for i in range(10)]
    clusters, cov = load_clusters_economic(_make_econ_db(rows), "C", _FakeNBBO(), limit=4)
    assert len(clusters) == 4 and cov["n_clusters_attempted"] == 4


TESTS = [
    test_directional_return_signs,
    test_clusters_collapse_alerts_to_decisions,
    test_build_candidate_economic_mode,
    test_economic_limit_caps_clusters,
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
