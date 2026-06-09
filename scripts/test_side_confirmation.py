"""Tests for autoresearch/side_confirmation.py + label_confidence.py + the
Signal Health Card's "Label" column.

Pure-stdlib, deterministic (stub tape source; temp DB / cache dirs). The MSTR
125C inversion (ASK label, 99%-at-bid tape), the MU/MRVL mid-dominated ambiguity
and the labeling-artifact split-sample test are all encoded as fixtures.

Run:  python scripts/test_side_confirmation.py
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

from autoresearch.side_confirmation import (  # noqa: E402
    AMBIGUOUS, CONFIRMED, INVERTED, NO_DATA,
    TapePrint, ThetaTradeTapeSource, classify_tape, fire_window, implied_side,
    verify_side,
)
from autoresearch.label_confidence import (  # noqa: E402
    LABEL_HIGH, LABEL_LOW, LABEL_MEDIUM, LABEL_UNKNOWN,
    LabelConfidenceConfig, check_cohort_side_labels, is_side_label_dependent,
    stride_sample,
)
from autoresearch.signal_health_card import (  # noqa: E402
    LABEL_EXEMPT, LABEL_UNVERIFIED, build_cards, render_markdown,
)
from autoresearch.decay_monitor import SECONDS_PER_DAY  # noqa: E402

_passed = 0
_failed = 0
NOW = 1_700_000_000.0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def _prints(ask=0, bid=0, mid=0, px=1.0, b=0.95, a=1.05):
    """Synthetic prints: `ask` contracts at the ask, `bid` at the bid, `mid` between."""
    out = []
    if ask:
        out.append(TapePrint(size=ask, price=a, bid=b, ask=a))
    if bid:
        out.append(TapePrint(size=bid, price=b, bid=b, ask=a))
    if mid:
        out.append(TapePrint(size=mid, price=(b + a) / 2, bid=b, ask=a))
    return out


# ── classify_tape ───────────────────────────────────────────────────────────
def test_classify_tape():
    t = classify_tape(_prints(ask=90, bid=5, mid=5))
    check("ask-dominant -> ASK", t.status == "OK" and t.side == "ASK"
          and abs(t.ask_frac - 0.90) < 1e-9, f"{t}")
    # The MSTR 125C tape: 99% of size hit the bid.
    t = classify_tape(_prints(ask=1, bid=99))
    check("bid-dominant -> BID (MSTR tape)", t.side == "BID"
          and t.bid_frac >= 0.99, f"{t}")
    # The MU/MRVL tape: overwhelmingly mid.
    t = classify_tape(_prints(ask=5, bid=5, mid=90))
    check("mid-dominant -> MID", t.side == "MID", f"{t}")
    # 54/46 split: neither side reaches 55% dominance.
    t = classify_tape(_prints(ask=54, bid=46))
    check("54% ask is not dominant -> MID", t.side == "MID", f"{t}")
    t = classify_tape(_prints(ask=3, bid=2))   # 5 contracts < min 10.
    check("below min_contracts -> NO_DATA", t.status == NO_DATA, f"{t}")
    t = classify_tape([])
    check("empty tape -> NO_DATA", t.status == NO_DATA and t.contracts == 0)


# ── implied_side ────────────────────────────────────────────────────────────
def test_implied_side():
    check("BULL call -> ASK", implied_side("BULL", "call") == "ASK")
    check("BULL put -> BID", implied_side("BULL", "put") == "BID")
    check("BEAR call -> BID", implied_side("BEAR", "call") == "BID")
    check("BEAR put -> ASK", implied_side("BEAR", "put") == "ASK")
    check("NEUTRAL -> None", implied_side("NEUTRAL", "call") is None)
    check("missing -> None", implied_side(None, None) is None)


# ── verify_side ─────────────────────────────────────────────────────────────
def test_verify_side():
    ask_tape = classify_tape(_prints(ask=90, bid=10))
    bid_tape = classify_tape(_prints(ask=10, bid=90))
    mid_tape = classify_tape(_prints(mid=100))
    nodata = classify_tape([])
    check("ASK label + ask tape -> CONFIRMED", verify_side("ASK", ask_tape) == CONFIRMED)
    # The MSTR case: tagged ASK, tape says the size SOLD.
    check("ASK label + bid tape -> INVERTED", verify_side("ASK", bid_tape) == INVERTED)
    check("BID label + bid tape -> CONFIRMED", verify_side("BID", bid_tape) == CONFIRMED)
    check("ASK label + mid tape -> AMBIGUOUS", verify_side("ASK", mid_tape) == AMBIGUOUS)
    check("MID label -> AMBIGUOUS even on clean tape",
          verify_side("MID", ask_tape) == AMBIGUOUS)
    check("no tape -> NO_DATA", verify_side("ASK", nodata) == NO_DATA)


# ── fire_window / stride_sample ─────────────────────────────────────────────
def test_fire_window_and_stride():
    s, e = fire_window("10:18", buffer_min=5)
    check("window open..fire+5", s == "09:30:00.000" and e == "10:23:00.000", f"{s}..{e}")
    s, e = fire_window("15:58", buffer_min=5)
    check("window clamps at close", e == "16:00:00.000", e)

    items = list(range(100))
    sub = stride_sample(items, 10)
    check("stride caps at 10", len(sub) == 10, str(sub))
    check("stride spans first..last", sub[0] == 0 and sub[-1] == 99, str(sub))
    check("stride deterministic", sub == stride_sample(items, 10))
    check("stride no-op when small", stride_sample(items, 200) == items)


# ── cohort aggregation ──────────────────────────────────────────────────────
class _StubTape:
    """Per-ticker scripted tape; counts fetches for cache tests."""

    def __init__(self, mapping, default=None):
        self.mapping = mapping
        self.default = default if default is not None else []
        self.calls = 0

    def prints(self, ticker, expiration, strike, right, date, start, end):
        self.calls += 1
        return self.mapping.get(ticker, self.default)


def _cluster(ticker, i=0, direction="BULL", option_type="call", ret=None):
    return {"ticker": ticker, "day": "2026-06-05", "direction": direction,
            "option_type": option_type, "strike": 100.0, "expiration": "20260620",
            "fired_at": NOW + i * 60.0, "ret": ret}


def test_cohort_confirmed_high():
    tape = _StubTape({}, default=_prints(ask=900, bid=100))  # everything confirms ASK.
    clusters = [_cluster(f"T{i}", i, ret=0.5) for i in range(20)]
    res = check_cohort_side_labels("WHALE", clusters, tape)
    check("all confirmed", res.n_confirmed == 20 and res.n_inverted == 0,
          f"{res.n_confirmed}/{res.n_with_data}")
    check("band HIGH", res.band == LABEL_HIGH, res.band)
    check("confirm LCB present and sane",
          res.confirm_lcb is not None and 0.6 <= res.confirm_lcb <= 1.0,
          str(res.confirm_lcb))
    check("no artifact on consistent edge", not res.edge_is_artifact)


def test_cohort_inverted_low():
    # MSTR-class cohort: labels say ASK, tape says the size sold.
    tape = _StubTape({}, default=_prints(ask=1, bid=99))
    clusters = [_cluster(f"T{i}", i, ret=0.2) for i in range(20)]
    res = check_cohort_side_labels("WHALE", clusters, tape)
    check("all inverted", res.n_inverted == 20, f"inv={res.n_inverted}")
    check("band LOW on inversions", res.band == LABEL_LOW, res.band)


def test_cohort_mid_ambiguous_low():
    # MU/MRVL-class: mid-dominated tape -> 0 confirmations -> LOW.
    tape = _StubTape({}, default=_prints(mid=100))
    clusters = [_cluster(f"T{i}", i) for i in range(20)]
    res = check_cohort_side_labels("INFORMED", clusters, tape)
    check("all ambiguous", res.n_ambiguous == 20, f"amb={res.n_ambiguous}")
    check("band LOW on guesses", res.band == LABEL_LOW,
          f"{res.band} conf={res.confirm_frac}")


def test_cohort_medium_band():
    # 14/20 confirmed (70%), no inversions -> MEDIUM (not HIGH, not LOW).
    mapping = {f"T{i}": _prints(ask=90, bid=10) for i in range(14)}
    mapping.update({f"T{i}": _prints(mid=100) for i in range(14, 20)})
    tape = _StubTape(mapping)
    clusters = [_cluster(f"T{i}", i) for i in range(20)]
    res = check_cohort_side_labels("FLOW_HIGH", clusters, tape)
    check("70% confirmed -> MEDIUM", res.band == LABEL_MEDIUM,
          f"{res.band} conf={res.confirm_frac}")


def test_cohort_unknown_small_n():
    tape = _StubTape({}, default=_prints(ask=100))
    clusters = [_cluster(f"T{i}", i) for i in range(5)]   # 5 < min_checked 12.
    res = check_cohort_side_labels("WHALE", clusters, tape)
    check("tiny verified sample -> UNKNOWN", res.band == LABEL_UNKNOWN, res.band)


def test_cohort_no_tape_coverage():
    tape = _StubTape({}, default=[])
    clusters = [_cluster(f"T{i}", i) for i in range(15)]
    res = check_cohort_side_labels("WHALE", clusters, tape)
    check("no coverage -> all NO_DATA + UNKNOWN",
          res.n_no_data == 15 and res.band == LABEL_UNKNOWN,
          f"nodata={res.n_no_data} band={res.band}")


def test_artifact_detection():
    # Confirmed clusters lose money; ambiguous (guessed) ones carry the "edge".
    mapping = {f"C{i}": _prints(ask=95, bid=5) for i in range(12)}
    mapping.update({f"A{i}": _prints(mid=100) for i in range(18)})
    tape = _StubTape(mapping)
    clusters = ([_cluster(f"C{i}", i, ret=-0.1) for i in range(12)]
                + [_cluster(f"A{i}", 100 + i, ret=1.0) for i in range(18)])
    res = check_cohort_side_labels("WHALE", clusters, tape)
    check("full-cohort edge positive", res.edge_all is not None and res.edge_all > 0,
          str(res.edge_all))
    check("confirmed-only edge negative",
          res.edge_confirmed is not None and res.edge_confirmed <= 0,
          str(res.edge_confirmed))
    check("ARTIFACT flagged", res.edge_is_artifact, res.reason)
    # And no artifact when the confirmed subset is too thin to say.
    cfg = LabelConfidenceConfig(artifact_min_n=50)
    res2 = check_cohort_side_labels("WHALE", clusters, tape, config=cfg)
    check("artifact needs min confirmed n", not res2.edge_is_artifact)


def test_missing_contract_spec_is_no_data():
    tape = _StubTape({}, default=_prints(ask=100))
    c = _cluster("T0")
    c["strike"] = None
    res = check_cohort_side_labels("WHALE", [c], tape)
    check("missing spec -> NO_DATA, no fetch",
          res.n_no_data == 1 and tape.calls == 0,
          f"nodata={res.n_no_data} calls={tape.calls}")


def test_side_label_dependence():
    check("WHALE dependent", is_side_label_dependent("WHALE"))
    check("FLOW_MEDIUM dependent", is_side_label_dependent("FLOW_MEDIUM"))
    check("INFORMED_FLOW dependent", is_side_label_dependent("INFORMED_FLOW"))
    check("CLUSTER_BULL dependent", is_side_label_dependent("CLUSTER_BULL"))
    check("SOE_A exempt", not is_side_label_dependent("SOE_A"))
    check("ZERO_DTE_BP exempt", not is_side_label_dependent("ZERO_DTE_BP"))
    check("SCALP exempt", not is_side_label_dependent("SCALP_BUY_DIP"))


# ── ThetaTradeTapeSource caching ────────────────────────────────────────────
def test_tape_source_cache():
    calls = {"n": 0}

    class _CountingSource(ThetaTradeTapeSource):
        def _fetch(self, *a):
            calls["n"] += 1
            return _prints(ask=50, bid=50)

    with tempfile.TemporaryDirectory() as td:
        src = _CountingSource(cache_dir=Path(td))
        a = src.prints("MSTR", "20260620", 125.0, "call", "2026-06-08",
                       "09:30:00.000", "16:00:00.000")
        b = src.prints("MSTR", "20260620", 125.0, "call", "2026-06-08",
                       "09:30:00.000", "16:00:00.000")
        check("fetch happens once (memory cache)", calls["n"] == 1, str(calls))
        check("cached prints identical", a == b)
        # New instance, same cache dir -> disk cache hit, no fetch.
        src2 = _CountingSource(cache_dir=Path(td))
        c = src2.prints("MSTR", "20260620", 125.0, "call", "2026-06-08",
                        "09:30:00.000", "16:00:00.000")
        check("disk cache survives new instance", calls["n"] == 1 and c == a)


# ── Signal Health Card "Label" column ───────────────────────────────────────
def _make_db(rows):
    fd, path = tempfile.mkstemp(suffix=".db", prefix="lblcard_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE alert_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "alert_type TEXT, fired_at REAL, verdict_eod TEXT, outcome_status TEXT)")
    con.executemany(
        "INSERT INTO alert_outcomes (alert_type, fired_at, verdict_eod, outcome_status) "
        "VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


def _cohort_rows(name, n, win_frac, days_ago):
    fired = NOW - days_ago * SECONDS_PER_DAY
    wins = int(round(n * win_frac))
    return [(name, fired, "WIN" if i < wins else "LOSS", "resolved")
            for i in range(n)]


def test_card_label_column():
    rows = _cohort_rows("WHALE", 60, 0.6, 10) + _cohort_rows("SOE_A", 60, 0.6, 10)
    db = _make_db(rows)
    try:
        # WHALE verified LOW; SOE_A exempt; no entry for a dependent cohort
        # would read UNVERIFIED (checked below by omitting the map).
        tape = _StubTape({}, default=_prints(mid=100))
        clusters = [_cluster(f"T{i}", i, ret=0.1) for i in range(20)]
        lc = check_cohort_side_labels("WHALE", clusters, tape)

        cards, _ = build_cards(db, now_ts=NOW, label_confidence={"WHALE": lc})
        by = {c.cohort: c for c in cards}
        check("WHALE carries LOW band", by["WHALE"].label_band == LABEL_LOW,
              by["WHALE"].label_band)
        check("WHALE confirm frac populated",
              by["WHALE"].label_confirm_frac is not None)
        check("SOE_A exempt", by["SOE_A"].label_band == LABEL_EXEMPT)
        md = render_markdown(cards, now_ts=NOW)
        check("markdown has Label column", "| Label |" in md)
        check("markdown shows LOW cell", "LOW" in md)

        cards2, _ = build_cards(db, now_ts=NOW)  # no map at all.
        by2 = {c.cohort: c for c in cards2}
        check("dependent cohort w/o check -> UNVERIFIED",
              by2["WHALE"].label_band == LABEL_UNVERIFIED, by2["WHALE"].label_band)
        check("exempt unaffected w/o map", by2["SOE_A"].label_band == LABEL_EXEMPT)
        md2 = render_markdown(cards2, now_ts=NOW)
        check("markdown shows UNVERIFIED", "UNVERIFIED" in md2)
    finally:
        os.unlink(db)


def main() -> int:
    print("=== side confirmation / label confidence tests ===")
    for fn in (test_classify_tape, test_implied_side, test_verify_side,
               test_fire_window_and_stride, test_cohort_confirmed_high,
               test_cohort_inverted_low, test_cohort_mid_ambiguous_low,
               test_cohort_medium_band, test_cohort_unknown_small_n,
               test_cohort_no_tape_coverage, test_artifact_detection,
               test_missing_contract_spec_is_no_data, test_side_label_dependence,
               test_tape_source_cache, test_card_label_column):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
