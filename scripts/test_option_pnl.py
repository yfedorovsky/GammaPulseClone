"""Deterministic tests for autoresearch/option_pnl.py (injected NBBO source).

No network. Runs anywhere with stdlib:
    .venv-autoresearch/Scripts/python scripts/test_option_pnl.py
    python scripts/test_option_pnl.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.option_pnl import (  # noqa: E402
    Bar, simulate_option_pnl, fire_hhmm_from_ts, et_day_from_ts,
)


class FakeSource:
    def __init__(self, bars):
        self._bars = bars

    def bars(self, ticker, expiration, strike, right, date):
        return list(self._bars)


def _sim(bars, fire="09:31", tp=100.0, stop=-50.0):
    return simulate_option_pnl(
        ticker="AAPL", expiration="2026-05-22", strike=300.0, option_type="call",
        fire_hhmm=fire, date="2026-05-13", source=FakeSource(bars), tp_pct=tp, stop_pct=stop)


def test_entry_at_ask_first_bar_after_fire():
    bars = [Bar("09:30", 1.0, 1.1),   # before fire -> excluded
            Bar("09:31", 1.9, 2.0),   # entry here at ask=2.0
            Bar("09:35", 2.0, 2.1)]
    r = _sim(bars)
    assert r.status == "OK" and r.entry_ask == 2.0


def test_take_profit_exit():
    bars = [Bar("09:31", 1.9, 2.0), Bar("09:40", 4.0, 4.2)]  # bid 4.0 = +100% of 2.0
    r = _sim(bars)
    assert r.exit_reason == "TP"
    assert abs(r.pnl_pct - 100.0) < 1e-9
    assert abs(r.r_multiple - 2.0) < 1e-9      # +100% / 50% risk = +2R


def test_stop_exit():
    bars = [Bar("09:31", 1.9, 2.0), Bar("09:45", 1.0, 1.1)]  # bid 1.0 = -50% of 2.0
    r = _sim(bars)
    assert r.exit_reason == "STOP"
    assert abs(r.pnl_pct + 50.0) < 1e-9
    assert abs(r.r_multiple + 1.0) < 1e-9      # -50% / 50% risk = -1R


def test_eod_exit():
    bars = [Bar("09:31", 1.9, 2.0), Bar("10:00", 2.05, 2.15), Bar("15:59", 2.1, 2.2)]
    r = _sim(bars)
    assert r.exit_reason == "EOD"
    assert abs(r.pnl_pct - 5.0) < 1e-9         # last bid 2.1 vs entry 2.0
    assert abs(r.r_multiple - 0.1) < 1e-9


def test_tp_takes_precedence_within_a_bar_sequence():
    # TP earlier than a later stop -> first crossing wins (TP).
    bars = [Bar("09:31", 1.9, 2.0), Bar("09:40", 4.0, 4.1), Bar("09:50", 0.5, 0.6)]
    r = _sim(bars)
    assert r.exit_reason == "TP"


def test_no_data():
    assert _sim([]).status == "NO_DATA"
    # All bars before fire time -> no qualifying entry.
    assert _sim([Bar("09:20", 1.0, 1.1)], fire="09:31").status == "NO_DATA"


def test_fire_hhmm_is_eastern():
    # 2026-05-13 09:31 ET should render as "09:31" (not the UTC 13:31).
    et = ZoneInfo("America/New_York")
    ts = datetime(2026, 5, 13, 9, 31, tzinfo=et).timestamp()
    assert fire_hhmm_from_ts(ts) == "09:31"
    assert et_day_from_ts(ts) == "2026-05-13"


TESTS = [
    test_entry_at_ask_first_bar_after_fire,
    test_take_profit_exit,
    test_stop_exit,
    test_eod_exit,
    test_tp_takes_precedence_within_a_bar_sequence,
    test_no_data,
    test_fire_hhmm_is_eastern,
]


def main() -> int:
    print("=" * 70)
    print("UNIT TESTS - autoresearch/option_pnl.py")
    print("=" * 70)
    passed = failed = 0
    for t in TESTS:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}  - {e}"); failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   {t.__name__}  - {e!r}"); failed += 1
    print("=" * 70)
    print(f"RESULT: {passed}/{passed + failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
