"""Tests for autoresearch/cohort_economics.py (windowed option-PnL expectancy).

Deterministic: a stub NBBO source (winner/loser by ticker) + a temp DB. Needs the
venv (backtest_adapter imports numpy).

Run:  .venv-autoresearch/Scripts/python scripts/test_cohort_economics.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.cohort_economics import cohort_expectancy  # noqa: E402
from autoresearch.decay_monitor import SECONDS_PER_DAY  # noqa: E402
from autoresearch.option_pnl import Bar  # noqa: E402

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


class StubNBBO:
    """Winner tickers rise through TP (R≈+2.4); losers fall through stop (R≈-1.4).
    Bars use hhmm '23:59' so they're always >= any fire time."""
    WIN = {"WIN", "FADE_PRIOR"}    # rise to 2x entry -> TP
    LOSE = {"LOSE", "FADE_RECENT"}  # fall to 0.3 -> STOP

    def bars(self, ticker, expiration, strike, right, date):
        if ticker in self.WIN:
            return [Bar("23:59", 0.9, 1.0), Bar("23:59", 2.2, 2.3)]
        return [Bar("23:59", 0.9, 1.0), Bar("23:59", 0.3, 0.4)]


_COLS = ("alert_type", "ticker", "direction", "strike", "expiration",
         "option_type", "score", "fired_at", "verdict_eod", "outcome_status")


def _make_db(rows: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="cohecon_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE alert_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "alert_type TEXT, ticker TEXT, direction TEXT, strike REAL, expiration TEXT, "
        "option_type TEXT, score REAL, fired_at REAL, verdict_eod TEXT, outcome_status TEXT)")
    con.executemany(
        f"INSERT INTO alert_outcomes ({','.join(_COLS)}) "
        f"VALUES ({','.join('?' for _ in _COLS)})",
        [tuple(r[c] for c in _COLS) for r in rows])
    con.commit()
    con.close()
    return path


def _row(alert_type, ticker, days_ago):
    return {"alert_type": alert_type, "ticker": ticker, "direction": "BULL",
            "strike": 100.0, "expiration": "2026-12-18", "option_type": "call",
            "score": 1.0, "fired_at": NOW - days_ago * SECONDS_PER_DAY,
            "verdict_eod": "WIN", "outcome_status": "resolved"}


def test_recent_expectancy_sign():
    rows = [_row("WIN_SIG", "WIN", 10), _row("LOSE_SIG", "LOSE", 10)]
    db = _make_db(rows)
    try:
        recent, prior, cov = cohort_expectancy(
            db, ["WIN_SIG", "LOSE_SIG"], StubNBBO(), now_ts=NOW)
    finally:
        os.unlink(db)
    check("winner cohort positive R", recent.get("WIN_SIG", 0) > 1.5, str(recent))
    check("loser cohort negative R", recent.get("LOSE_SIG", 0) < 0, str(recent))
    check("no prior-window data for recent-only cohorts", "WIN_SIG" not in prior, str(prior))


def test_windowing_deteriorating():
    # FADE_SIG: prior-window rows = winners, recent-window rows = losers.
    rows = [_row("FADE_SIG", "FADE_PRIOR", 80),   # prior 60-120d window
            _row("FADE_SIG", "FADE_RECENT", 10)]  # recent 60d window
    db = _make_db(rows)
    try:
        recent, prior, cov = cohort_expectancy(db, ["FADE_SIG"], StubNBBO(), now_ts=NOW)
    finally:
        os.unlink(db)
    check("recent < prior (deteriorating economics)",
          recent.get("FADE_SIG") is not None and prior.get("FADE_SIG") is not None
          and recent["FADE_SIG"] < prior["FADE_SIG"],
          f"recent={recent.get('FADE_SIG')} prior={prior.get('FADE_SIG')}")


def test_empty_cohort_omitted():
    db = _make_db([_row("WIN_SIG", "WIN", 10)])
    try:
        recent, prior, cov = cohort_expectancy(db, ["NOPE"], StubNBBO(), now_ts=NOW)
    finally:
        os.unlink(db)
    check("cohort with no rows omitted", "NOPE" not in recent and "NOPE" not in prior)


def main() -> int:
    print("=== cohort economics tests ===")
    for fn in (test_recent_expectancy_sign, test_windowing_deteriorating,
               test_empty_cohort_omitted):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*44}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
