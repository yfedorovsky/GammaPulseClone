"""Tests for autoresearch/signal_health_card.py (Signal Health Card).

Pure-stdlib, deterministic (temp DB + fixed now_ts). Covers the card-specific
logic (trend classification, action mapping) and an end-to-end build over a
synthetic alert_outcomes DB.

Run:  python scripts/test_signal_health_card.py
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

from autoresearch import signal_health_card as shc  # noqa: E402
from autoresearch.signal_health_card import (  # noqa: E402
    ACT_ACCUMULATE, ACT_INVESTIGATE, ACT_NONE, ACT_PREPARE_RETIREMENT,
    TREND_DETERIORATING, TREND_IMPROVING, TREND_INSUFFICIENT, TREND_STABLE,
    build_cards, classify_trend, render_json, render_markdown, suggested_action,
)
from autoresearch.decay_monitor import (  # noqa: E402
    HEALTHY, RETIRE_CANDIDATE, UNTRUSTED, WATCH, SECONDS_PER_DAY,
)

_passed = 0
_failed = 0
NOW = 1_700_000_000.0  # fixed clock.


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


# ── pure unit tests ────────────────────────────────────────────────────────
def test_classify_trend():
    # both windows >= min_n; +12pp -> IMPROVING
    t, d = classify_trend(0.60, 0.48, 40, 40, min_n=30)
    check("trend improving", t == TREND_IMPROVING and abs(d - 0.12) < 1e-9, f"{t},{d}")
    # -20pp -> DETERIORATING
    t, d = classify_trend(0.20, 0.40, 40, 40, min_n=30)
    check("trend deteriorating", t == TREND_DETERIORATING, f"{t},{d}")
    # +2pp -> STABLE
    t, _ = classify_trend(0.50, 0.48, 40, 40, min_n=30)
    check("trend stable", t == TREND_STABLE, t)
    # thin prior window -> INSUFFICIENT
    t, d = classify_trend(0.50, 0.50, 40, 5, min_n=30)
    check("trend insufficient when thin", t == TREND_INSUFFICIENT and d is None, f"{t},{d}")


def test_suggested_action():
    check("healthy -> none", suggested_action(HEALTHY, 0, TREND_STABLE) == ACT_NONE)
    check("untrusted -> accumulate",
          suggested_action(UNTRUSTED, 0, TREND_INSUFFICIENT) == ACT_ACCUMULATE)
    check("watch -> investigate", suggested_action(WATCH, 1, TREND_STABLE) == ACT_INVESTIGATE)
    check("retire streak>=2 -> prepare",
          suggested_action(RETIRE_CANDIDATE, 2, TREND_STABLE) == ACT_PREPARE_RETIREMENT)
    check("retire provisional -> investigate",
          suggested_action(RETIRE_CANDIDATE, 1, TREND_STABLE) == ACT_INVESTIGATE)
    check("healthy but deteriorating trend -> investigate",
          suggested_action(HEALTHY, 0, TREND_DETERIORATING) == ACT_INVESTIGATE)


# ── integration over a synthetic DB ────────────────────────────────────────
_COLS = ("ts", "alert_type", "fired_at", "verdict_eod", "outcome_status")


def _make_db(rows: list[tuple]) -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="shc_")
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
    """n resolved rows for a cohort, fired `days_ago` before NOW."""
    fired = NOW - days_ago * SECONDS_PER_DAY
    wins = int(round(n * win_frac))
    out = []
    for i in range(n):
        v = "WIN" if i < wins else "LOSS"
        out.append((name, fired, v, "resolved"))
    return out


def test_build_cards_end_to_end():
    rows = []
    # n must be large enough that the (deliberately wide) always-valid LCB clears
    # breakeven — at small n even an 80%-win signal honestly reads WATCH, not green.
    rows += _cohort_rows("HEALTHY_SIG", 400, 0.80, days_ago=20)    # strong, well-powered
    rows += _cohort_rows("DEAD_SIG", 60, 0.05, days_ago=20)        # well below breakeven
    rows += _cohort_rows("THIN_SIG", 8, 0.50, days_ago=10)         # n < min_n -> UNTRUSTED
    # deteriorating: high prior-60d, low recent-60d (both >= min_n)
    rows += _cohort_rows("FADING_SIG", 40, 0.85, days_ago=80)      # prior-60d window
    rows += _cohort_rows("FADING_SIG", 40, 0.25, days_ago=15)      # recent-60d window
    db = _make_db(rows)
    try:
        cards, state = build_cards(db, now_ts=NOW, breakeven=0.227, min_n=30)
        by = {c.cohort: c for c in cards}

        check("4 cohorts carded", len(cards) == 4, str(sorted(by)))
        # Wilson contract holds on the 60d dashboard
        ok_ci = all(
            (c.rate_60d is None) or
            (c.wilson_60d_low <= c.rate_60d <= c.wilson_60d_high)
            for c in cards)
        check("wilson low<=rate<=high (60d)", ok_ci)

        h = by["HEALTHY_SIG"]
        check("healthy verdict + no action",
              h.verdict == HEALTHY and h.suggested_action == ACT_NONE,
              f"{h.verdict},{h.suggested_action}")

        d = by["DEAD_SIG"]
        check("dead signal flagged (watch/retire, not healthy)",
              d.verdict in (WATCH, RETIRE_CANDIDATE) and
              d.suggested_action in (ACT_INVESTIGATE, ACT_PREPARE_RETIREMENT),
              f"{d.verdict},{d.suggested_action}")

        t = by["THIN_SIG"]
        check("thin -> untrusted + accumulate",
              t.verdict == UNTRUSTED and t.suggested_action == ACT_ACCUMULATE,
              f"{t.verdict},{t.suggested_action}")

        f = by["FADING_SIG"]
        check("fading -> DETERIORATING trend",
              f.trend == TREND_DETERIORATING, f"{f.trend} d={f.trend_delta}")

        # worst-first ordering: a RETIRE/WATCH cohort precedes HEALTHY
        check("sorted worst-first", cards[0].verdict != HEALTHY, cards[0].verdict)

        # renderers don't blow up and contain structure
        md = render_markdown(cards, now_ts=NOW)
        check("markdown has summary + a cohort", "## Summary" in md and "HEALTHY_SIG" in md)
        js = render_json(cards)
        check("json is list of dicts", isinstance(js, list) and isinstance(js[0], dict))
    finally:
        os.unlink(db)


def test_hysteresis_streak_drives_retire_action():
    """A confirmed breach streak (prior_state) -> RETIRE_CANDIDATE -> prepare."""
    rows = _cohort_rows("DEAD_SIG", 60, 0.05, days_ago=20)
    db = _make_db(rows)
    try:
        cards, _ = build_cards(db, now_ts=NOW, breakeven=0.227, min_n=30,
                               prior_state={"DEAD_SIG": {"breach_streak": 1}})
        c = cards[0]
        check("streak->2 yields RETIRE_CANDIDATE", c.verdict == RETIRE_CANDIDATE,
              f"{c.verdict} streak={c.breach_streak}")
        check("retire -> prepare-retirement action",
              c.suggested_action == ACT_PREPARE_RETIREMENT, c.suggested_action)
    finally:
        os.unlink(db)


def main() -> int:
    print("=== signal health card tests ===")
    for fn in (test_classify_trend, test_suggested_action,
               test_build_cards_end_to_end, test_hysteresis_streak_drives_retire_action):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
