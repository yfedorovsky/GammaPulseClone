"""Unit tests for the #92 option-P&L backfill (alert_outcomes.run_option_pnl_backfill).

Pure-compute + injected-fetcher tests — NO live ThetaData Terminal required.
Run:
  python scripts/test_option_pnl_backfill.py
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402

from server import alert_outcomes as ao  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def _bars(fire_date: str, fire_ts: int, seq):
    """seq = list of (minute_offset, bid, ask). date stamped to fire_date."""
    out = []
    for (m, bid, ask) in seq:
        out.append({
            "ts": fire_ts + m * 60,
            "date": fire_date,
            "bid": bid, "ask": ask, "mid": (bid + ask) / 2.0,
        })
    return out


def test_compute_ask_in_bid_out():
    # Entry ask = 1.00; peak bid = 3.00 -> MFE +200%; low bid = 0.40 -> MAE -60%.
    fire_ts = 1_700_000_000
    fire_date = _dt.datetime.fromtimestamp(fire_ts).date().isoformat()
    bars = _bars(fire_date, fire_ts, [
        (0, 0.95, 1.00),   # entry bar: ask 1.00 is the cost basis
        (5, 2.90, 3.00),   # peak bid 2.90
        (10, 0.40, 0.50),  # trough bid 0.40
        (60, 1.20, 1.30),  # eod-ish last bar bid 1.20
    ])
    o = ao.compute_option_outcome(bars, fire_ts, fire_date)
    check("entry basis = first-bar ask", abs(o["_entry_ask"] - 1.00) < 1e-9, str(o))
    check("opt_mfe_pct = (2.90-1.00)/1.00 = +190%", abs(o["opt_mfe_pct"] - 190.0) < 0.01, str(o))
    check("opt_mae_pct = (0.40-1.00)/1.00 = -60%", abs(o["opt_mae_pct"] - (-60.0)) < 0.01, str(o))
    check("opt_high_after = max bid 2.90", abs(o["opt_high_after"] - 2.90) < 1e-9, str(o))
    check("opt_low_after = min bid 0.40", abs(o["opt_low_after"] - 0.40) < 1e-9, str(o))
    check("opt_close_eod = last bid 1.20", abs(o["opt_close_eod"] - 1.20) < 1e-9, str(o))


def test_next_day_close():
    fire_ts = 1_700_000_000
    fire_date = _dt.datetime.fromtimestamp(fire_ts).date().isoformat()
    next_date = (_dt.date.fromisoformat(fire_date) + _dt.timedelta(days=1)).isoformat()
    bars = _bars(fire_date, fire_ts, [(0, 0.95, 1.00), (30, 1.50, 1.60)])
    bars += [{"ts": fire_ts + 86400, "date": next_date, "bid": 2.0, "ask": 2.1, "mid": 2.05},
             {"ts": fire_ts + 86400 + 600, "date": next_date, "bid": 2.5, "ask": 2.6, "mid": 2.55}]
    o = ao.compute_option_outcome(bars, fire_ts, fire_date)
    check("opt_close_next_day = last next-day bid 2.50", abs(o["opt_close_next_day"] - 2.50) < 1e-9, str(o))


def test_no_bars_after_fire():
    fire_ts = 1_700_000_000
    fire_date = _dt.datetime.fromtimestamp(fire_ts).date().isoformat()
    # all bars BEFORE fire
    bars = [{"ts": fire_ts - 600, "date": fire_date, "bid": 1.0, "ask": 1.1, "mid": 1.05}]
    o = ao.compute_option_outcome(bars, fire_ts, fire_date)
    check("returns None when no bars at/after fire", o is None, str(o))


def test_backfill_end_to_end_and_idempotent():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao_test.db")
    now = time.time()
    # integer-valued so int(fired_at) == fired_at (the first minute bar lands
    # exactly at fire_ts; real ThetaData bars are minute-aligned too).
    fired_at = float(int(now) - 7200)  # 2h ago -> inside window, >1h old
    # ET fire-date, mirroring run_option_pnl_backfill (tz-robust on any host).
    fire_date = (_dt.datetime.fromtimestamp(fired_at, ao._ET) if ao._ET
                 else _dt.datetime.fromtimestamp(fired_at)).date().isoformat()

    aid = ao.log_alert(
        alert_type="CLUSTER", ticker="MU", direction="BULL",
        strike=130.0, expiration="2026-07-18", option_type="call",
        spot_at_alert=125.0, entry_price=2.50, fired_at=fired_at, db_path=db,
    )
    check("log_alert returned id", bool(aid))

    captured = {}

    async def fake_fetcher(sym, exp, strike, right, start, end):
        captured["args"] = (sym, exp, strike, right, start, end)
        ft = int(fired_at)
        return _bars(fire_date, ft, [
            (0, 2.40, 2.50),    # entry ask 2.50
            (5, 7.40, 7.50),    # peak bid 7.40 -> +196%
            (20, 1.90, 2.00),   # trough bid 1.90 -> -24%
            (120, 5.00, 5.10),  # last bid 5.00
        ])

    async def run():
        s1 = await ao.run_option_pnl_backfill(db_path=db, max_age_days=30,
                                               now=now, fetcher=fake_fetcher)
        s2 = await ao.run_option_pnl_backfill(db_path=db, max_age_days=30,
                                              now=now, fetcher=fake_fetcher)
        return s1, s2

    s1, s2 = asyncio.run(run())
    check("first run updated 1 row", s1["updated"] == 1, str(s1))
    check("ThetaData right mapped call->C", captured["args"][3] == "C", str(captured))

    import sqlite3
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT opt_mfe_pct, opt_mae_pct, opt_high_after, opt_close_eod FROM alert_outcomes WHERE alert_id=?",
        (aid,)).fetchone()
    conn.close()
    check("opt_mfe_pct populated ~ +196%", row and abs(row[0] - 196.0) < 0.01, str(row))
    check("opt_mae_pct populated ~ -24%", row and abs(row[1] - (-24.0)) < 0.01, str(row))
    check("idempotent: second run processes 0 (opt_mfe_pct no longer NULL)",
          s2["processed"] == 0, str(s2))


def test_spx_root_mapping():
    check("SPX -> SPXW root", ao._option_root_for_theta("SPX") == "SPXW")
    check("MU -> MU root", ao._option_root_for_theta("MU") == "MU")
    check("put option_type -> P", ao._right_from_option_type("put") == "P")
    check("call option_type -> C", ao._right_from_option_type("call") == "C")


if __name__ == "__main__":
    print("test_option_pnl_backfill")
    test_compute_ask_in_bid_out()
    test_next_day_close()
    test_no_bars_after_fire()
    test_backfill_end_to_end_and_idempotent()
    test_spx_root_mapping()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(1 if _FAIL else 0)
