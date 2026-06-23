"""Tests for INFORMED CLUSTER -> alert_outcomes logging (unblocks audit C10).
Run: python scripts/test_cluster_outcomes.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import informed_cluster as ic  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def _cluster(n_strikes=3):
    ts = int(time.time()) - 7200
    strikes = [(130.0 + i, ts, 5, 2_000_000, 12.0) for i in range(n_strikes)]
    return {
        "ticker": "MU", "expiration": "2026-07-18", "direction": "BULL",
        "option_type": "call", "strikes": strikes, "n_strikes": n_strikes,
        "first_ts": ts, "last_ts": ts, "total_notional": 6_000_000,
        "max_score": 6, "avg_vol_oi": 12.0, "duration_min": 5.0,
    }


def test_logs_each_leg():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    n = ic.log_cluster_outcomes(_cluster(3), db_path=db)
    check("logged 3 legs", n == 3, str(n))
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT alert_type, grade, ticker, strike, option_type FROM alert_outcomes ORDER BY strike").fetchall()
    conn.close()
    check("all alert_type=CLUSTER", all(r[0] == "CLUSTER" for r in rows), str(rows))
    check("grade tags strike count", all(r[1] == "3strike" for r in rows), str(rows))
    check("strikes 130/131/132 logged", [r[3] for r in rows] == [130.0, 131.0, 132.0], str(rows))
    check("option_type=call", all(r[4] == "call" for r in rows), str(rows))


def test_4strike_grade():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    ic.log_cluster_outcomes(_cluster(4), db_path=db)
    conn = sqlite3.connect(db)
    grades = {r[0] for r in conn.execute("SELECT DISTINCT grade FROM alert_outcomes").fetchall()}
    conn.close()
    check("4-strike cluster tagged grade=4strike", grades == {"4strike"}, str(grades))


def test_env_disable():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao.db")
    os.environ["CLUSTER_OUTCOME_LOG"] = "0"
    try:
        n = ic.log_cluster_outcomes(_cluster(3), db_path=db)
        check("CLUSTER_OUTCOME_LOG=0 disables logging", n == 0, str(n))
    finally:
        os.environ.pop("CLUSTER_OUTCOME_LOG", None)


def test_imports():
    import importlib
    import server.flow_alerts as fa
    importlib.reload(fa)
    check("flow_alerts + informed_cluster import OK", fa is not None and hasattr(ic, "record_and_check"))


if __name__ == "__main__":
    print("test_cluster_outcomes")
    test_logs_each_leg()
    test_4strike_grade()
    test_env_disable()
    test_imports()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
