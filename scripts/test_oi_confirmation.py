"""Unit tests for next-morning settled-OI confirmation cohort (task #60).

Pan-Poteshman: predictive power is in buy-to-OPEN volume. A flagged contract
whose settled OI rises by ≥ a fraction of the flagged volume by next morning is
genuine new positioning (opening); one whose OI doesn't rise was a close/churn.
This splits alerts into cohorts so win rates can be measured separately.

Run:  python scripts/test_oi_confirmation.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import server.alert_outcomes as ao  # noqa: E402
from server.alert_outcomes import (  # noqa: E402
    classify_oi,
    log_alert,
    run_oi_confirmation,
    get_oi_confirmation_report,
)

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def _tmpdb() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="oitest_")
    os.close(fd)
    os.unlink(path)  # let _ensure_schema create fresh
    return path


# ── pure classifier ───────────────────────────────────────────────────────
def test_classify_opening():
    # flagged 1000 contracts; OI rose 700 (≥ 0.5×1000) → opening/confirmed
    c, s = classify_oi(oi_now=1700, oi_at_fire=1000, flagged_volume=1000)
    check("OI grew ≥50% of vol → confirmed", c == 1 and s == "confirmed", f"{c},{s}")


def test_classify_closing():
    # flagged 1000; OI rose only 100 (< 500) → churn/unconfirmed
    c, s = classify_oi(oi_now=1100, oi_at_fire=1000, flagged_volume=1000)
    check("OI flat → unconfirmed", c == 0 and s == "unconfirmed", f"{c},{s}")


def test_classify_oi_dropped():
    # OI fell → definitely a close
    c, s = classify_oi(oi_now=400, oi_at_fire=1000, flagged_volume=1000)
    check("OI dropped → unconfirmed", c == 0 and s == "unconfirmed", f"{c},{s}")


def test_classify_no_data():
    check("missing oi_now → no_data", classify_oi(None, 1000, 1000)[1] == "no_data")
    check("missing flagged_vol → no_data", classify_oi(1700, 1000, None)[1] == "no_data")


# ── integration: log → confirm → report ───────────────────────────────────
def _yesterday_noon() -> float:
    d = date.today() - timedelta(days=1)
    return time.mktime((d.year, d.month, d.day, 12, 0, 0, 0, 0, -1))


def test_integration_cohort_split():
    db = _tmpdb()
    fut_exp = (date.today() + timedelta(days=14)).isoformat()
    ts = _yesterday_noon()
    # Two flagged contracts on same expiration, both fired yesterday.
    # A: opening (OI will be much higher this morning)
    log_alert(alert_type="CLUSTER_BULL", ticker="TST", fired_at=ts,
              direction="BULL", strike=100.0, expiration=fut_exp,
              option_type="call",
              raw_alert={"oi": 1000, "volume": 4000}, db_path=db)
    # B: churn (OI barely moved)
    log_alert(alert_type="CLUSTER_BULL", ticker="TST", fired_at=ts,
              direction="BULL", strike=110.0, expiration=fut_exp,
              option_type="call",
              raw_alert={"oi": 5000, "volume": 4000}, db_path=db)

    # verify capture
    conn = sqlite3.connect(db)
    cap = conn.execute("SELECT strike, oi_at_fire, flagged_volume FROM alert_outcomes ORDER BY strike").fetchall()
    conn.close()
    check("oi_at_fire + flagged_volume captured from raw_alert",
          cap == [(100.0, 1000, 4000), (110.0, 5000, 4000)], str(cap))

    # fake next-morning chain: strike 100 OI jumped to 4500 (Δ3500 ≥ 2000),
    # strike 110 OI to 5200 (Δ200 < 2000)
    async def fake_fetcher(ticker, exp):
        return {(100.0, "call"): 4500, (110.0, "call"): 5200}

    stats = asyncio.run(run_oi_confirmation(db_path=db, fetcher=fake_fetcher))
    check("processed both", stats["processed"] == 2, str(stats))
    check("one confirmed", stats.get("confirmed") == 1, str(stats))
    check("one unconfirmed", stats.get("unconfirmed") == 1, str(stats))

    conn = sqlite3.connect(db)
    res = dict(conn.execute(
        "SELECT strike, oi_confirmed FROM alert_outcomes").fetchall())
    conn.close()
    check("strike100 = confirmed(1)", res.get(100.0) == 1, str(res))
    check("strike110 = unconfirmed(0)", res.get(110.0) == 0, str(res))
    os.unlink(db)


def test_idempotent_no_reprocess():
    db = _tmpdb()
    fut_exp = (date.today() + timedelta(days=14)).isoformat()
    ts = _yesterday_noon()
    log_alert(alert_type="CLUSTER_BULL", ticker="TST", fired_at=ts,
              direction="BULL", strike=100.0, expiration=fut_exp,
              option_type="call",
              raw_alert={"oi": 1000, "volume": 4000}, db_path=db)
    calls = {"n": 0}

    async def fetcher(ticker, exp):
        calls["n"] += 1
        return {(100.0, "call"): 9000}

    asyncio.run(run_oi_confirmation(db_path=db, fetcher=fetcher))
    s2 = asyncio.run(run_oi_confirmation(db_path=db, fetcher=fetcher))
    check("second run processes nothing (idempotent)", s2["processed"] == 0, str(s2))
    check("fetcher only called on first pass", calls["n"] == 1, str(calls))
    os.unlink(db)


def test_today_rows_not_processed():
    """Rows fired TODAY must not be confirmed — OCC settled OI hasn't updated."""
    db = _tmpdb()
    fut_exp = (date.today() + timedelta(days=14)).isoformat()
    log_alert(alert_type="CLUSTER_BULL", ticker="TST", fired_at=time.time(),
              direction="BULL", strike=100.0, expiration=fut_exp,
              option_type="call",
              raw_alert={"oi": 1000, "volume": 4000}, db_path=db)

    async def fetcher(ticker, exp):
        return {(100.0, "call"): 9000}

    s = asyncio.run(run_oi_confirmation(db_path=db, fetcher=fetcher))
    check("today's row deferred (not processed)", s["processed"] == 0, str(s))
    os.unlink(db)


def main() -> int:
    print("=== next-morning OI-confirmation cohort (task #60) tests ===")
    for fn in (test_classify_opening, test_classify_closing,
               test_classify_oi_dropped, test_classify_no_data,
               test_integration_cohort_split, test_idempotent_no_reprocess,
               test_today_rows_not_processed):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*54}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
