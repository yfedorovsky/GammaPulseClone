"""Tests for the multi-day-hold option-PnL model (option_pnl.simulate_option_pnl_multiday).

Pure-stdlib, deterministic (per-date scripted NBBO source). Covers: legacy
hold_days=0 equivalence, cross-day TP/STOP, horizon exit, weekend/holiday
session skipping, expiration clamping, and the CENSORING RULE — a horizon not
covered by available data is UNRESOLVED even when TP/stop already hit inside
the partial window (including early barrier-hits while their still-open
cohort-mates can't be valued would bias the sample toward early deciders).

Run:  python scripts/test_option_pnl_multiday.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from autoresearch.option_pnl import (  # noqa: E402
    Bar, simulate_option_pnl, simulate_option_pnl_multiday,
)

_passed = 0
_failed = 0

# Fire on Monday 2026-06-01; 06-06/06-07 are the weekend.
FIRE = "2026-06-01"
WEEK = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
        "2026-06-08", "2026-06-09"]
FAR_EXP = "2027-01-15"


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def _day(bid, ask=None, n=3):
    """A session of n flat bars at the given quote."""
    ask = ask if ask is not None else bid + 0.10
    return [Bar(hhmm=f"{10 + i:02d}:00", bid=bid, ask=ask) for i in range(n)]


class _DayNBBO:
    """Scripted per-date bars; days absent from the map return no bars."""

    def __init__(self, days: dict):
        self.days = days

    def bars(self, ticker, expiration, strike, right, date):
        return self.days.get(date, [])


def _sim(days, hold_days, expiration=FAR_EXP, tp_pct=100.0, stop_pct=-50.0):
    return simulate_option_pnl_multiday(
        ticker="T", expiration=expiration, strike=100.0, option_type="call",
        fire_hhmm="09:30", date=FIRE, source=_DayNBBO(days),
        tp_pct=tp_pct, stop_pct=stop_pct, hold_days=hold_days)


# Entry = day-0 first ask = 1.10 in all fixtures below.
# TP level = 2.20 (bid), STOP level = 0.55 (bid).


def test_legacy_equivalence():
    days = {FIRE: _day(1.00)}
    old = simulate_option_pnl(
        ticker="T", expiration=FAR_EXP, strike=100.0, option_type="call",
        fire_hhmm="09:30", date=FIRE, source=_DayNBBO(days))
    new = _sim(days, hold_days=0)
    check("hold 0 == legacy (EOD, same pnl)",
          old.status == new.status == "OK" and old.exit_reason == new.exit_reason == "EOD"
          and abs(old.pnl_pct - new.pnl_pct) < 1e-9,
          f"{old} vs {new}")
    check("legacy fields default sane", new.days_held == 0 and new.exit_date == FIRE,
          f"{new.days_held},{new.exit_date}")


def test_tp_on_day3():
    # Horizon (hold 3 = 4 sessions) fully covered; TP bid arrives on day 3.
    days = {WEEK[0]: _day(1.00), WEEK[1]: _day(1.05), WEEK[2]: _day(2.50),
            WEEK[3]: _day(1.00)}
    r = _sim(days, hold_days=3)
    # Day 3 (index 2) bid 2.50 >= TP 2.20.
    check("TP fires on day 3", r.status == "OK" and r.exit_reason == "TP"
          and r.days_held == 2 and r.exit_date == WEEK[2], f"{r}")
    check("TP pnl from exit bid", abs(r.pnl_pct - (2.50 - 1.10) / 1.10 * 100) < 1e-9,
          str(r.pnl_pct))


def test_stop_on_day2():
    days = {WEEK[0]: _day(1.00), WEEK[1]: _day(0.40), WEEK[2]: _day(3.00)}
    r = _sim(days, hold_days=2)
    check("STOP fires day 2 before day-3 TP", r.exit_reason == "STOP"
          and r.days_held == 1, f"{r}")
    check("stop R ~ -1.16R (gap below stop)",
          abs(r.r_multiple - ((0.40 - 1.10) / 1.10) / 0.5) < 1e-9, str(r.r_multiple))


def test_horizon_exit():
    days = {d: _day(1.20) for d in WEEK[:4]}
    r = _sim(days, hold_days=3)
    check("HORIZON exit on session 4 last bid", r.exit_reason == "HORIZON"
          and r.days_held == 3 and r.exit_date == WEEK[3], f"{r}")


def test_weekend_skip():
    # Hold 5: needs 6 sessions; the weekend (no bars) must not count.
    days = {d: _day(1.20) for d in WEEK[:5]} | {WEEK[5]: _day(1.50)}
    r = _sim(days, hold_days=5)
    check("weekend days don't count toward horizon",
          r.status == "OK" and r.exit_date == WEEK[5] and r.days_held == 5, f"{r}")


def test_expiry_clamp():
    # Expires Wednesday: hold 5 clamps to 3 sessions, exit reason EXPIRY.
    days = {d: _day(1.20) for d in WEEK[:3]}
    r = _sim(days, hold_days=5, expiration="2026-06-03")
    check("expiry clamps the horizon", r.status == "OK" and r.exit_reason == "EXPIRY"
          and r.exit_date == "2026-06-03" and r.days_held == 2, f"{r}")
    # Dashless expiration format parses too.
    r2 = _sim(days, hold_days=5, expiration="20260603")
    check("dashless expiration parses", r2.exit_reason == "EXPIRY", f"{r2}")


def test_unresolved_when_data_ends():
    days = {WEEK[0]: _day(1.20), WEEK[1]: _day(1.20)}   # data stops Tuesday.
    r = _sim(days, hold_days=5)
    check("horizon past data end -> UNRESOLVED", r.status == "UNRESOLVED", f"{r}")


def test_censoring_rule_overrides_early_tp():
    # TP hits on the fire day (entry 1.10, later bid 2.50 >= TP 2.20), but the
    # 5-day horizon is NOT covered by data: censoring returns UNRESOLVED anyway.
    days = {WEEK[0]: [Bar(hhmm="10:00", bid=1.00, ask=1.10),
                      Bar(hhmm="11:00", bid=2.50, ask=2.60)]}
    r = _sim(days, hold_days=5)
    check("early TP inside uncovered horizon -> UNRESOLVED (censoring rule)",
          r.status == "UNRESOLVED", f"{r}")
    # Same path with hold 0 IS resolved (horizon = fire session only).
    r2 = _sim(days, hold_days=0)
    check("same path resolves at hold 0", r2.status == "OK" and r2.exit_reason == "TP",
          f"{r2}")


def test_worst_case_tiebreak_across_days():
    # A day-2 bar whose bid is below the stop AND a later same-day bar above TP:
    # walking bar-by-bar, the stop bar comes first.
    days = {WEEK[0]: _day(1.00),
            WEEK[1]: [Bar(hhmm="10:00", bid=0.40, ask=0.50),
                      Bar(hhmm="11:00", bid=3.00, ask=3.10)]}
    r = _sim(days, hold_days=1)
    check("stop-before-tp ordering preserved across days", r.exit_reason == "STOP", f"{r}")


def test_no_data_day0():
    r = _sim({WEEK[1]: _day(1.00)}, hold_days=2)
    check("no fire-day bars -> NO_DATA", r.status == "NO_DATA", f"{r}")


def main() -> int:
    print("=== multi-day option-PnL tests ===")
    for fn in (test_legacy_equivalence, test_tp_on_day3, test_stop_on_day2,
               test_horizon_exit, test_weekend_skip, test_expiry_clamp,
               test_unresolved_when_data_ends,
               test_censoring_rule_overrides_early_tp,
               test_worst_case_tiebreak_across_days, test_no_data_day0):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
