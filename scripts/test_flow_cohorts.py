"""Tests for autoresearch/flow_cohorts.py (Option B — flow_alerts cohort source).

Deterministic: temp snapshots-style DB + stub NBBO/tape sources. Covers cohort
predicates (disjointness of WHALE/INFORMED vs FLOW_* tiers), direction mapping
(sentiment first, side x option_type fallback, undirected exclusion), C5
clustering, offline option-PnL outcomes, window filtering, and candidate
assembly (always side_label_dependent; LABEL_CONF uses the stored side).

MUST run under the autoresearch venv:
    .venv-autoresearch/Scripts/python scripts/test_flow_cohorts.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from autoresearch.flow_cohorts import (  # noqa: E402
    FLOW_COHORTS, build_flow_candidate, direction_from, load_flow_clusters,
)
from autoresearch.gate import TestCard  # noqa: E402
from autoresearch.option_pnl import Bar  # noqa: E402
from autoresearch.side_confirmation import TapePrint  # noqa: E402

_passed = 0
_failed = 0
NOW = 1_780_929_000.0  # 2026-06-08 14:30 UTC = 10:30 ET (inside the NBBO session).


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


# ── fixtures ────────────────────────────────────────────────────────────────
_COLS = ("ts", "ticker", "strike", "expiration", "option_type", "side",
         "sentiment", "conviction", "notional", "volume", "is_whale",
         "is_insider")


def _make_db(rows) -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="flowco_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE flow_alerts ({', '.join(_COLS)})")
    con.executemany(
        f"INSERT INTO flow_alerts ({', '.join(_COLS)}) "
        f"VALUES ({', '.join('?' * len(_COLS))})", rows)
    con.commit()
    con.close()
    return path


def _row(ticker, i=0, *, side="ASK", sentiment="BULLISH", otype="call",
         conviction="HIGH", notional=2_000_000.0, volume=500,
         whale=0, insider=0, days_offset=0):
    return (NOW + days_offset * 86400.0 + i, ticker, 100.0, "2027-01-15", otype,
            side, sentiment, conviction, notional, volume, whale, insider)


class _FakeNBBO:
    def bars(self, ticker, expiration, strike, right, date):
        return [Bar(hhmm=f"{9 + h:02d}:{m:02d}", bid=1.0, ask=1.1)
                for h in range(1, 7) for m in (0, 30)]


class _StubTape:
    def __init__(self, default):
        self.default = default

    def prints(self, ticker, expiration, strike, right, date, start, end):
        return self.default


def _ask_prints(n=100):
    return [TapePrint(size=n, price=1.05, bid=0.95, ask=1.05)]


def _bid_prints(n=100):
    return [TapePrint(size=n, price=0.95, bid=0.95, ask=1.05)]


def _card(cid="FLOW-TEST") -> TestCard:
    return TestCard(
        card_id=cid, provenance="test", claim="flow cohort beats baseline",
        expected_sign="positive", mechanism="informed flow precedes the move",
        target_cohort="WHALE", kill_criteria="lower bound below breakeven",
    )


# ── direction mapping ───────────────────────────────────────────────────────
def test_direction_from():
    check("sentiment BULLISH wins", direction_from("BULLISH", "BID", "call") == "BULL")
    check("sentiment BEARISH wins", direction_from("BEARISH", "ASK", "call") == "BEAR")
    check("fallback ASK call -> BULL", direction_from(None, "ASK", "call") == "BULL")
    check("fallback ASK put -> BEAR", direction_from("", "ASK", "put") == "BEAR")
    check("fallback BID call -> BEAR", direction_from(None, "BID", "call") == "BEAR")
    check("fallback BID put -> BULL", direction_from(None, "BID", "put") == "BULL")
    check("NEUTRAL+MID -> None", direction_from("NEUTRAL", "MID", "call") is None)
    check("missing everything -> None", direction_from(None, None, None) is None)


# ── cohort predicates ───────────────────────────────────────────────────────
def test_cohort_selection_disjoint():
    rows = [
        _row("AAA", 0, whale=1, conviction="HIGH"),            # WHALE only
        _row("BBB", 1, insider=1, conviction="HIGH"),           # INFORMED only
        _row("CCC", 2, conviction="HIGH"),                      # FLOW_HIGH
        _row("DDD", 3, conviction="MEDIUM"),                    # FLOW_MEDIUM
        _row("EEE", 4, whale=1, insider=1, conviction="HIGH"),  # both flags
    ]
    db = _make_db(rows)
    try:
        nbbo = _FakeNBBO()
        got = {}
        for cohort in FLOW_COHORTS:
            clusters, _ = load_flow_clusters(db, cohort, nbbo)
            got[cohort] = sorted(c["ticker"] for c in clusters)
        check("WHALE = whale-flagged", got["WHALE"] == ["AAA", "EEE"], str(got["WHALE"]))
        check("INFORMED = insider-flagged", got["INFORMED"] == ["BBB", "EEE"],
              str(got["INFORMED"]))
        check("FLOW_HIGH excludes flagged", got["FLOW_HIGH"] == ["CCC"],
              str(got["FLOW_HIGH"]))
        check("FLOW_MEDIUM excludes flagged", got["FLOW_MEDIUM"] == ["DDD"],
              str(got["FLOW_MEDIUM"]))
    finally:
        os.unlink(db)


def test_unknown_cohort_raises():
    try:
        load_flow_clusters(":memory:", "NOPE", _FakeNBBO())
        check("unknown cohort raises", False)
    except ValueError:
        check("unknown cohort raises", True)


# ── clustering + outcomes ───────────────────────────────────────────────────
def test_clustering_and_outcomes():
    rows = [
        # 3 same-direction repeats on one ticker-day -> ONE cluster, earliest rep,
        # score = max notional.
        _row("AAA", 0, whale=1, notional=1_000_000, volume=100),
        _row("AAA", 60, whale=1, notional=9_000_000, volume=900),
        _row("AAA", 120, whale=1, notional=2_000_000, volume=200),
        # Same ticker-day, OPPOSITE direction -> separate cluster.
        _row("AAA", 30, whale=1, side="BID", sentiment="BEARISH", notional=500_000),
        # Undirected (MID/NEUTRAL) -> excluded, counted.
        _row("AAA", 90, whale=1, side="MID", sentiment="NEUTRAL"),
        # Next day -> separate cluster.
        _row("AAA", 0, whale=1, days_offset=1, notional=3_000_000),
    ]
    db = _make_db(rows)
    try:
        clusters, cov = load_flow_clusters(db, "WHALE", _FakeNBBO())
        check("3 clusters (dir split + day split)", len(clusters) == 3,
              str([(c['ticker'], c['day'], c['direction']) for c in clusters]))
        bull0 = next(c for c in clusters
                     if c["direction"] == "BULL" and c["n_alerts"] == 3)
        check("repeats collapse, n_alerts=3", bull0["n_alerts"] == 3)
        check("rep = earliest fire (vol 100)", bull0["alert_volume"] == 100.0,
              str(bull0["alert_volume"]))
        check("score = max cluster notional", bull0["score"] == 9_000_000.0,
              str(bull0["score"]))
        check("stored side carried", bull0["side"] == "ASK", str(bull0["side"]))
        check("option-PnL outcome attached", isinstance(bull0["ret"], float))
        check("undirected counted", cov["n_alerts_undirected"] == 1, str(cov))
    finally:
        os.unlink(db)


def test_window_and_limit():
    rows = ([_row("OLD", 0, whale=1, days_offset=-30)]
            + [_row(f"T{i}", i, whale=1) for i in range(5)])
    db = _make_db(rows)
    try:
        clusters, _ = load_flow_clusters(db, "WHALE", _FakeNBBO(),
                                         lo_ts=NOW - 7 * 86400.0)
        check("lo_ts filters out old rows",
              sorted(c["ticker"] for c in clusters) == [f"T{i}" for i in range(5)],
              str([c["ticker"] for c in clusters]))
        clusters2, _ = load_flow_clusters(db, "WHALE", _FakeNBBO(), limit=2)
        check("limit caps clusters", len(clusters2) == 2, str(len(clusters2)))
        check("limit keeps the MOST RECENT clusters",
              [c["ticker"] for c in clusters2] == ["T3", "T4"],
              str([c["ticker"] for c in clusters2]))
    finally:
        os.unlink(db)


# ── candidate assembly ──────────────────────────────────────────────────────
def test_build_flow_candidate():
    rows = [_row(f"T{i}", i, whale=1, notional=1e6 * (i + 1)) for i in range(15)]
    base_rows = [_row(f"B{i}", i, insider=1) for i in range(10)]
    db = _make_db(rows + base_rows)
    try:
        tape = _StubTape(_ask_prints())
        cand, diag = build_flow_candidate(
            _card(), "WHALE", flow_db_path=db, baseline="INFORMED",
            source=_FakeNBBO(), tape_source=tape)
        check("15 candidate clusters", diag["n_units"] == 15, str(diag["n_units"]))
        check("baseline from flow_alerts",
              diag["baseline_source"] == "flow_alerts" and diag["n_baseline_units"] == 10,
              f"{diag['baseline_source']}/{diag['n_baseline_units']}")
        check("always side_label_dependent", cand.side_label_dependent)
        check("label confidence attached", cand.label_confidence is not None)
        check("ASK labels confirmed by ask tape",
              cand.label_confidence.n_confirmed == cand.label_confidence.n_checked,
              f"{cand.label_confidence.n_confirmed}/{cand.label_confidence.n_checked}")
        check("config matrix from notional thresholds",
              diag["config_matrix_shape"] is not None, str(diag["config_matrix_shape"]))

        # The stored side is what gets verified: BID-tape inverts these ASK labels.
        cand2, _ = build_flow_candidate(
            _card("FLOW-INV"), "WHALE", flow_db_path=db, baseline="INFORMED",
            source=_FakeNBBO(), tape_source=_StubTape(_bid_prints()))
        check("stored ASK side vs bid tape -> inverted",
              cand2.label_confidence.n_inverted == cand2.label_confidence.n_checked,
              f"inv={cand2.label_confidence.n_inverted}")

        # No tape source -> honestly unverified.
        cand3, _ = build_flow_candidate(
            _card("FLOW-NOTAPE"), "WHALE", flow_db_path=db, baseline="INFORMED",
            source=_FakeNBBO())
        check("no tape -> label_confidence None", cand3.label_confidence is None)
    finally:
        os.unlink(db)


def test_side_source_optional_split():
    # Without the column (this file's default schema) -> None everywhere.
    db = _make_db([_row("AAA", 0, whale=1)])
    try:
        clusters, cov = load_flow_clusters(db, "WHALE", _FakeNBBO())
        check("no column -> side_source None", clusters[0]["side_source"] is None)
        check("no column -> zero split counts",
              cov["n_side_source_tick"] == 0 and cov["n_side_source_snapshot"] == 0)
    finally:
        os.unlink(db)
    # With the column (live schema from 2026-06-09 PM) -> carried + counted.
    fd, db2 = tempfile.mkstemp(suffix=".db", prefix="flowco_src_")
    os.close(fd)
    con = sqlite3.connect(db2)
    con.execute(f"CREATE TABLE flow_alerts ({', '.join(_COLS)}, side_source)")
    con.executemany(
        f"INSERT INTO flow_alerts ({', '.join(_COLS)}, side_source) "
        f"VALUES ({', '.join('?' * (len(_COLS) + 1))})",
        [_row("TICK", 0, whale=1) + ("tick",),
         _row("GUESS", 1, whale=1) + ("snapshot",),
         _row("OLD", 2, whale=1) + (None,)])
    con.commit()
    con.close()
    try:
        clusters, cov = load_flow_clusters(db2, "WHALE", _FakeNBBO())
        by = {c["ticker"]: c["side_source"] for c in clusters}
        check("side_source carried per cluster",
              by == {"TICK": "tick", "GUESS": "snapshot", "OLD": None}, str(by))
        check("split counts", cov["n_side_source_tick"] == 1
              and cov["n_side_source_snapshot"] == 1, str(cov))
    finally:
        os.unlink(db2)


def test_hold_days_unresolved_excluded():
    # The fake NBBO only ever has fire-day bars (it ignores `date`, but the
    # multiday scan asks for LATER calendar dates which we make empty here), so
    # a 2-day hold can't be covered -> every cluster UNRESOLVED and excluded.
    class _FireDayOnlyNBBO:
        def bars(self, ticker, expiration, strike, right, date):
            from autoresearch.option_pnl import et_day_from_ts
            if date != et_day_from_ts(NOW):
                return []
            return _FakeNBBO().bars(ticker, expiration, strike, right, date)

    rows = [_row(f"T{i}", i, whale=1) for i in range(5)]
    db = _make_db(rows)
    try:
        clusters, cov = load_flow_clusters(db, "WHALE", _FireDayOnlyNBBO(),
                                           hold_days=2)
        check("uncovered horizon -> all clusters excluded",
              len(clusters) == 0 and cov["n_clusters_unresolved"] == 5,
              str(cov))
        check("coverage records hold_days", cov["hold_days"] == 2, str(cov))
        clusters0, cov0 = load_flow_clusters(db, "WHALE", _FireDayOnlyNBBO(),
                                             hold_days=0)
        check("same data resolves at hold 0",
              len(clusters0) == 5 and cov0["n_clusters_unresolved"] == 0,
              str(cov0))
    finally:
        os.unlink(db)


def test_requires_nbbo_source():
    try:
        build_flow_candidate(_card(), "WHALE", source=None)
        check("missing NBBO source raises", False)
    except ValueError:
        check("missing NBBO source raises", True)


def main() -> int:
    print("=== flow cohort source tests ===")
    for fn in (test_direction_from, test_cohort_selection_disjoint,
               test_unknown_cohort_raises, test_clustering_and_outcomes,
               test_window_and_limit, test_build_flow_candidate,
               test_side_source_optional_split,
               test_hold_days_unresolved_excluded, test_requires_nbbo_source):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
