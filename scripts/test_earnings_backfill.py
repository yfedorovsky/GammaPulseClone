"""Tests for the earnings-in-window backfill (#119). Run: python scripts/test_earnings_backfill.py"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402

from server import alert_outcomes as ao  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_in_and_out_of_window():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    now = time.time()
    fired = float(int(now) - 7200)
    fire_d = (_dt.datetime.fromtimestamp(fired, ao._ET) if ao._ET
              else _dt.datetime.fromtimestamp(fired)).date()
    exp_in = (fire_d + _dt.timedelta(days=20)).isoformat()    # earnings inside
    exp_out = (fire_d + _dt.timedelta(days=2)).isoformat()    # earnings after expiry
    er_date = fire_d + _dt.timedelta(days=10)

    a_in = ao.log_alert(alert_type="CLUSTER", ticker="MU", strike=130.0,
                        expiration=exp_in, option_type="call", fired_at=fired, db_path=db)
    a_out = ao.log_alert(alert_type="CLUSTER", ticker="MU", strike=131.0,
                         expiration=exp_out, option_type="call", fired_at=fired, db_path=db)

    async def fake_fetch(tk):
        return [er_date] if tk == "MU" else []

    s = asyncio.run(ao.run_earnings_backfill(db_path=db, max_age_days=30, now=now, fetcher=fake_fetch))
    check("processed 2", s["processed"] == 2, str(s))
    check("1 in-window, 1 out", s["in_window"] == 1 and s["not_in_window"] == 1, str(s))

    conn = sqlite3.connect(db)
    row_in = conn.execute("SELECT earnings_in_window, earnings_days_to FROM alert_outcomes WHERE alert_id=?", (a_in,)).fetchone()
    row_out = conn.execute("SELECT earnings_in_window, earnings_days_to FROM alert_outcomes WHERE alert_id=?", (a_out,)).fetchone()
    conn.close()
    check("in-window row = 1, days_to=10", row_in == (1, 10), str(row_in))
    check("out-window row = 0", row_out[0] == 0, str(row_out))


def test_deferred_on_fetch_failure():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    now = time.time()
    fired = float(int(now) - 7200)
    fd = (_dt.datetime.fromtimestamp(fired, ao._ET) if ao._ET else _dt.datetime.fromtimestamp(fired)).date()
    aid = ao.log_alert(alert_type="CLUSTER", ticker="ZZZ", strike=1.0,
                       expiration=(fd + _dt.timedelta(days=20)).isoformat(),
                       option_type="call", fired_at=fired, db_path=db)

    async def fail_fetch(tk):
        return None  # fetch failure

    s = asyncio.run(ao.run_earnings_backfill(db_path=db, max_age_days=30, now=now, fetcher=fail_fetch))
    check("fetch failure -> deferred", s["deferred"] == 1, str(s))
    conn = sqlite3.connect(db)
    v = conn.execute("SELECT earnings_in_window FROM alert_outcomes WHERE alert_id=?", (aid,)).fetchone()[0]
    conn.close()
    check("deferred row stays NULL (retry later)", v is None, str(v))


def test_idempotent():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    now = time.time()
    fired = float(int(now) - 7200)
    fd = (_dt.datetime.fromtimestamp(fired, ao._ET) if ao._ET else _dt.datetime.fromtimestamp(fired)).date()
    ao.log_alert(alert_type="CLUSTER", ticker="MU", strike=130.0,
                 expiration=(fd + _dt.timedelta(days=20)).isoformat(),
                 option_type="call", fired_at=fired, db_path=db)

    async def f(tk):
        return [fd + _dt.timedelta(days=5)]

    asyncio.run(ao.run_earnings_backfill(db_path=db, max_age_days=30, now=now, fetcher=f))
    s2 = asyncio.run(ao.run_earnings_backfill(db_path=db, max_age_days=30, now=now, fetcher=f))
    check("idempotent: second run processes 0", s2["processed"] == 0, str(s2))


if __name__ == "__main__":
    print("test_earnings_backfill")
    test_in_and_out_of_window()
    test_deferred_on_fetch_failure()
    test_idempotent()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
