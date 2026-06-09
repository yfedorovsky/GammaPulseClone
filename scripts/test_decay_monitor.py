"""Deterministic unit tests for autoresearch/decay_monitor.py.

Builds throwaway temp SQLite DBs with controlled WIN/LOSS/FLAT rows placed in
specific time windows, then asserts the health verdicts and CI math. No live DB,
no network, no heavy deps. Mirrors the scripts/test_*.py runner style.

Usage:
    python scripts/test_decay_monitor.py
"""
from __future__ import annotations

import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.decay_monitor import (  # noqa: E402
    DEFAULT_BREAKEVEN,
    HEALTHY,
    RETIRE_CANDIDATE,
    UNTRUSTED,
    WATCH,
    clopper_pearson_interval,
    compute_signal_health,
    wilson_interval,
    always_valid_lcb,
    always_valid_lcb_stream,
    lcb_method,
    jeffreys_interval,
    promotion_ready,
    eb_shrink_rates,
    monitor_signals,
)

# Fixed reference "now" so every window boundary is deterministic.
NOW_TS = datetime(2026, 6, 8, 16, 0, 0, tzinfo=timezone.utc).timestamp()
DAY = 86_400.0

_TABLE_COLS = "alert_type TEXT, fired_at REAL, outcome_status TEXT, verdict_eod TEXT"


def _make_db(rows: list[tuple[str, float, str, str]]) -> str:
    """Create a temp DB with the given (alert_type, fired_at, status, verdict) rows."""
    fd = tempfile.NamedTemporaryFile(prefix="decay_test_", suffix=".db", delete=False)
    fd.close()
    con = sqlite3.connect(fd.name)
    con.execute(f"CREATE TABLE alert_outcomes ({_TABLE_COLS})")
    con.executemany(
        "INSERT INTO alert_outcomes (alert_type, fired_at, outcome_status, verdict_eod) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()
    return fd.name


def _cohort(rows: list, name: str):
    for r in rows:
        if r.cohort == name:
            return r
    raise AssertionError(f"cohort {name!r} not found in results")


def _gen(cohort: str, wins: int, losses: int, flat: int, age_days: float,
         status: str = "info_only") -> list[tuple]:
    """Generate resolved rows for a cohort placed `age_days` before NOW_TS."""
    ts = NOW_TS - age_days * DAY
    out = []
    out += [(cohort, ts, status, "WIN")] * wins
    out += [(cohort, ts, status, "LOSS")] * losses
    out += [(cohort, ts, status, "FLAT")] * flat
    return out


# === CI math (pure functions) ===

def test_wilson_ordering_and_point():
    lo, point, hi = wilson_interval(30, 100)
    assert point == 0.30, point
    assert lo <= point <= hi, (lo, point, hi)
    assert 0.0 <= lo <= hi <= 1.0


def test_clopper_pearson_brackets_point():
    lo, hi = clopper_pearson_interval(30, 100)
    assert lo <= 0.30 <= hi, (lo, hi)
    assert 0.0 <= lo <= hi <= 1.0


def test_clopper_pearson_known_value():
    # Classic 0/10 -> CP upper bound is the 95% rule-of-three-ish value 0.3085.
    lo, hi = clopper_pearson_interval(0, 10)
    assert lo == 0.0
    assert abs(hi - 0.30850) < 1e-3, hi


def test_wilson_zero_n_safe():
    assert wilson_interval(0, 0) == (0.0, 0.0, 0.0)
    assert clopper_pearson_interval(0, 0) == (0.0, 1.0)


# === Verdict logic ===

def test_healthy_stays_healthy():
    # 80% win rate, large N -> Wilson lower comfortably above breakeven.
    rows = _gen("HEALTHY_SIG", wins=80, losses=20, flat=10, age_days=10)
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "HEALTHY_SIG")
    assert c.verdict == HEALTHY, (c.verdict, c.reason)
    assert c.wilson_60d[0] >= DEFAULT_BREAKEVEN


def test_recent_collapse_flips_to_retire():
    # Cohort was healthy in the prior-60d window, collapses in the recent 60d.
    rows = []
    rows += _gen("DECAYING", wins=80, losses=20, flat=5, age_days=80)   # prior window, healthy
    rows += _gen("DECAYING", wins=5, losses=45, flat=5, age_days=10)    # recent window, 10% WR
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "DECAYING")
    assert c.verdict == RETIRE_CANDIDATE, (c.verdict, c.reason)
    assert c.win_rate_60d is not None and c.win_rate_60d < DEFAULT_BREAKEVEN


def test_supported_downtrend_above_point_still_retires():
    # 60d point (30%) is ABOVE breakeven, so the simple point<breakeven rule does
    # NOT fire — but it fell from 90% with non-overlapping CIs and the 60d Wilson
    # lower (~21%) is below breakeven => RETIRE via the supported-downtrend path.
    rows = []
    rows += _gen("INFLECTING", wins=90, losses=10, flat=0, age_days=80)  # prior 90%
    rows += _gen("INFLECTING", wins=30, losses=70, flat=0, age_days=10)  # recent 30%
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "INFLECTING")
    assert c.win_rate_60d is not None and c.win_rate_60d > DEFAULT_BREAKEVEN, c.win_rate_60d
    assert c.trend_supported_down is True
    assert c.wilson_60d[0] < DEFAULT_BREAKEVEN
    assert c.verdict == RETIRE_CANDIDATE, (c.verdict, c.reason)


def test_watch_when_lower_below_but_point_above():
    # Point estimate above breakeven, small-ish N so Wilson lower dips below it,
    # and NO supported downtrend (no prior-window data) => WATCH, not RETIRE.
    rows = _gen("BORDERLINE", wins=10, losses=22, flat=3, age_days=10)  # 31.25%, n=32
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "BORDERLINE")
    assert c.win_rate_60d is not None and c.win_rate_60d >= DEFAULT_BREAKEVEN
    assert c.wilson_60d[0] < DEFAULT_BREAKEVEN
    assert c.trend_supported_down is False
    assert c.verdict == WATCH, (c.verdict, c.reason)


def test_low_n_is_untrusted():
    # 0/11 like the live SOE_AP cohort: too few rows -> UNTRUSTED, not RETIRE.
    rows = _gen("THIN", wins=0, losses=11, flat=3, age_days=10)
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "THIN")
    assert c.n_60d == 11
    assert c.verdict == UNTRUSTED, (c.verdict, c.reason)


def test_low_n_below_min_becomes_retire_when_min_lowered():
    # Same 0/11 cohort, but with min_n=5 it is trusted -> 0% < breakeven -> RETIRE.
    rows = _gen("THIN2", wins=0, losses=11, flat=3, age_days=10)
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=5)
    c = _cohort(res, "THIN2")
    assert c.verdict == RETIRE_CANDIDATE, (c.verdict, c.reason)


def test_flat_excluded_from_denominator():
    # Denominator must be WIN+LOSS only; FLAT (and a swamp of it) must not move WR.
    rows = _gen("FLATTY", wins=40, losses=10, flat=500, age_days=10)
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "FLATTY")
    assert c.n_60d == 50, c.n_60d                      # 40 + 10, NOT 550
    assert abs(c.win_rate_60d - 0.80) < 1e-12, c.win_rate_60d
    assert c.flat_60d == 500


def test_pending_excluded():
    # outcome_status == 'pending' rows must never count, regardless of verdict_eod.
    rows = _gen("PEND", wins=40, losses=10, flat=0, age_days=10)
    rows += _gen("PEND", wins=100, losses=0, flat=0, age_days=10, status="pending")
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    c = _cohort(res, "PEND")
    assert c.n_60d == 50, c.n_60d  # the 100 pending WINs are ignored


def test_ci_sanity_across_mixed_db():
    # For every resolved cohort: Wilson lower <= point <= upper, CP lo <= point <= hi,
    # all within [0, 1].
    rows = []
    rows += _gen("A", 80, 20, 5, 10)
    rows += _gen("B", 5, 45, 5, 10)
    rows += _gen("C", 10, 22, 3, 10)
    rows += _gen("D", 0, 11, 3, 10)
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=1)
    assert len(res) == 4
    for c in res:
        wlo, wpt, whi = c.wilson_60d
        cplo, cphi = c.clopper_pearson_60d
        assert 0.0 <= wlo <= whi <= 1.0, c.cohort
        assert wlo <= wpt <= whi, (c.cohort, wlo, wpt, whi)
        assert abs(wpt - c.win_rate_60d) < 1e-12, c.cohort
        assert 0.0 <= cplo <= cphi <= 1.0, c.cohort
        assert cplo <= c.win_rate_60d <= cphi, (c.cohort, cplo, c.win_rate_60d, cphi)


def test_trend_value_and_windows():
    # Sanity-check window plumbing: 90d sees both windows; trend = cur60 - prior60.
    rows = []
    rows += _gen("WIN_PLUMB", 90, 10, 0, 80)  # prior60: 90%
    rows += _gen("WIN_PLUMB", 30, 70, 0, 10)  # cur60:   30%
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=1)
    c = _cohort(res, "WIN_PLUMB")
    assert c.n_60d == 100 and abs(c.win_rate_60d - 0.30) < 1e-12
    assert c.n_prior_60d == 100 and abs(c.win_rate_prior_60d - 0.90) < 1e-12
    # 80d-old rows ARE within the 90d window, so 90d should include both => 200.
    assert c.n_90d == 200, c.n_90d
    assert abs(c.trend_60d_vs_prior - (0.30 - 0.90)) < 1e-12, c.trend_60d_vs_prior


def test_sorting_worst_first():
    rows = []
    rows += _gen("GOOD", 80, 20, 0, 10)   # HEALTHY
    rows += _gen("BAD", 2, 48, 0, 10)     # RETIRE
    rows += _gen("FEW", 0, 3, 0, 10)      # UNTRUSTED
    db = _make_db(rows)
    res = compute_signal_health(db, now_ts=NOW_TS, min_n=30)
    verdicts = [c.verdict for c in res]
    assert verdicts[0] == RETIRE_CANDIDATE, verdicts
    assert verdicts[-1] == HEALTHY, verdicts


# === C3: always-valid monitor ===

def test_always_valid_lcb_is_conservative_vs_wilson():
    # The time-uniform bound must be NO TIGHTER than the fixed-n Wilson lower bound
    # (it is wider on purpose — that is what removes optional-stopping bias).
    for wins, n in [(30, 100), (120, 300), (600, 2000)]:
        wlo = wilson_interval(wins, n)[0]
        av = always_valid_lcb(wins, n)
        assert 0.0 <= av <= wins / n, (wins, n, av)
        assert av <= wlo + 1e-9, (wins, n, av, wlo)


def test_monitor_healthy_large_n():
    rows = _gen("H", wins=1200, losses=800, flat=0, age_days=10)  # 60% over 2000
    v, _ = monitor_signals(_make_db(rows), now_ts=NOW_TS, min_n=45)
    h = [x for x in v if x.cohort == "H"][0]
    assert h.verdict == HEALTHY, h.reason
    assert h.always_valid_lcb >= DEFAULT_BREAKEVEN


def test_monitor_low_n_untrusted():
    rows = _gen("T", 3, 7, 0, 10)  # n=10 < 45
    v, st = monitor_signals(_make_db(rows), now_ts=NOW_TS, min_n=45)
    t = [x for x in v if x.cohort == "T"][0]
    assert t.verdict == UNTRUSTED and st["T"]["breach_streak"] == 0


def test_monitor_two_check_hysteresis():
    # Severe collapse: first check WATCH (streak 1), second consecutive RETIRE.
    db = _make_db(_gen("D", 15, 285, 0, 10))  # 5% over n=300
    v1, st1 = monitor_signals(db, now_ts=NOW_TS, min_n=45)
    d1 = [x for x in v1 if x.cohort == "D"][0]
    assert d1.breach is True and d1.verdict == WATCH and d1.breach_streak == 1, d1.reason
    v2, st2 = monitor_signals(db, now_ts=NOW_TS, min_n=45, prior_state=st1)
    d2 = [x for x in v2 if x.cohort == "D"][0]
    assert d2.verdict == RETIRE_CANDIDATE and d2.breach_streak == 2, d2.reason


def test_monitor_economic_gate_blocks_retire_without_deterioration():
    # Rate breach but expectancy is POSITIVE / not deteriorating -> NO breach.
    db = _make_db(_gen("D", 15, 285, 0, 10))
    v, st = monitor_signals(db, now_ts=NOW_TS, min_n=45, prior_state={"D": {"breach_streak": 1}},
                            expectancy_recent={"D": 0.5})  # healthy expectancy
    d = [x for x in v if x.cohort == "D"][0]
    assert d.breach is False and d.verdict == WATCH and st["D"]["breach_streak"] == 0
    # Same setup but expectancy deteriorating -> breach proceeds to RETIRE (streak 2).
    v2, _ = monitor_signals(db, now_ts=NOW_TS, min_n=45, prior_state={"D": {"breach_streak": 1}},
                            expectancy_recent={"D": -0.3})
    d2 = [x for x in v2 if x.cohort == "D"][0]
    assert d2.breach is True and d2.verdict == RETIRE_CANDIDATE


def test_eb_shrink_small_cohort_toward_pool():
    res = eb_shrink_rates({"big": (450, 1000), "tiny": (5, 5)})
    assert res["tiny"]["raw"] == 1.0
    assert res["tiny"]["shrunk"] < 0.95          # shrunk down toward pool
    assert res["tiny"]["ci_low"] <= res["tiny"]["shrunk"] <= res["tiny"]["ci_high"]


# === FIX-2: confseq fallback flag + split retire/promote ===

def test_lcb_method_flagged_when_confseq_absent():
    # confseq does not build on this venv. Two distinct, correctly-labelled paths:
    #  - COUNT-only -> conservative empirical-Bernstein (flagged "approx_eb").
    #  - ordered STREAM -> the pure-python betting CS, which is COVERAGE-VALIDATED
    #    (scripts/test_betting_cs.py), NOT an unverified approximation.
    _ = always_valid_lcb(120, 300)                  # count-only path
    m_count = lcb_method()
    assert "approx_eb" in m_count and "count-only" in m_count, m_count
    _ = always_valid_lcb_stream([1.0, 0.0] * 60)    # ordered stream path
    m_stream = lcb_method()
    assert "betting_cs" in m_stream and "coverage-validated" in m_stream, m_stream


def test_jeffreys_interval_brackets_and_unit():
    lo, hi = jeffreys_interval(30, 100)
    assert 0.0 <= lo <= 0.30 <= hi <= 1.0
    assert jeffreys_interval(0, 10)[0] == 0.0
    assert jeffreys_interval(10, 10)[1] == 1.0


def test_promotion_is_separate_from_retirement_bound():
    # Promotion must NOT reuse the (wide) retirement LCB. A strong, well-powered
    # signal promotes; a thin or near-breakeven one does not.
    assert promotion_ready(700, 1000, breakeven=0.227) is True     # 70% over n=1000
    assert promotion_ready(6, 20, breakeven=0.227) is False        # thin
    assert promotion_ready(60, 200, breakeven=0.227) is True       # 30% over 200, clears 22.7%
    # The promotion lower bound differs from the retirement always-valid LCB.
    rj_lo = jeffreys_interval(60, 200)[0]
    av = always_valid_lcb(60, 200)
    assert abs(rj_lo - av) > 1e-6


TESTS = [
    test_wilson_ordering_and_point,
    test_always_valid_lcb_is_conservative_vs_wilson,
    test_monitor_healthy_large_n,
    test_monitor_low_n_untrusted,
    test_monitor_two_check_hysteresis,
    test_monitor_economic_gate_blocks_retire_without_deterioration,
    test_eb_shrink_small_cohort_toward_pool,
    test_lcb_method_flagged_when_confseq_absent,
    test_jeffreys_interval_brackets_and_unit,
    test_promotion_is_separate_from_retirement_bound,
    test_clopper_pearson_brackets_point,
    test_clopper_pearson_known_value,
    test_wilson_zero_n_safe,
    test_healthy_stays_healthy,
    test_recent_collapse_flips_to_retire,
    test_supported_downtrend_above_point_still_retires,
    test_watch_when_lower_below_but_point_above,
    test_low_n_is_untrusted,
    test_low_n_below_min_becomes_retire_when_min_lowered,
    test_flat_excluded_from_denominator,
    test_pending_excluded,
    test_ci_sanity_across_mixed_db,
    test_trend_value_and_windows,
    test_sorting_worst_first,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS — autoresearch/decay_monitor.py")
    print("=" * 70)
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  — {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  — {e!r}")
            failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
