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


def _insider(strike, ts=None):
    return {"ticker": "META", "expiration": "2026-07-18", "option_type": "call",
            "sentiment": "BULLISH", "strike": strike, "insider_score": 6,
            "notional": 500_000, "vol_oi": 3.0}


def test_record_and_check_logs_at_3_strikes():
    """FALSIFICATION TEST for the 2026-06-29 dedup-at-2 bug. Drives the REAL
    record_and_check path (NOT log_cluster_outcomes directly — that's the seam the
    existing tests bypassed). Three distinct strikes must (a) return a cluster with
    n_strikes==3 and (b) land 3 alert_type='CLUSTER' rows. PRE-FIX this fails: dedup
    stamped at the 2-strike floor made strike #3 return None, so n_strikes never
    reached 3 and nothing was logged."""
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao_rc.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    ic._recent_fires.clear(); ic._cluster_dedup.clear()
    r1 = ic.record_and_check(_insider(615.0), db_path=db)   # distinct=1 -> None
    r2 = ic.record_and_check(_insider(617.5), db_path=db)   # distinct=2 -> 2-cluster, NO log
    r3 = ic.record_and_check(_insider(620.0), db_path=db)   # distinct=3 -> 3-cluster + log
    check("strike1 -> None (below 2-strike floor)", r1 is None, str(r1))
    check("strike2 -> 2-strike cluster (no dedup stamp)", r2 and r2["n_strikes"] == 2, str(r2))
    check("strike3 -> 3-strike cluster (2->3 growth NOT suppressed)",
          r3 and r3["n_strikes"] == 3, str(r3))
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    ks = conn.execute("SELECT DISTINCT strike FROM alert_outcomes WHERE alert_type='CLUSTER' ORDER BY strike").fetchall()
    conn.close()
    check("3 CLUSTER rows landed (one per leg)", n == 3, f"n={n}")
    check("legs = 615/617.5/620", [r[0] for r in ks] == [615.0, 617.5, 620.0], str(ks))


def test_record_and_check_dedup_within_window():
    """After a 3-strike fire, a 4th strike in the same window must NOT re-fire/re-log
    (returns None) — one cluster fire per (ticker,exp,direction) per 30 min."""
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao_dedup.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    ic._recent_fires.clear(); ic._cluster_dedup.clear()
    ic.record_and_check(_insider(615.0), db_path=db)
    ic.record_and_check(_insider(617.5), db_path=db)
    ic.record_and_check(_insider(620.0), db_path=db)   # fires + logs (3 rows)
    r4 = ic.record_and_check(_insider(622.5), db_path=db)  # 4th strike, same window
    check("4th strike in window -> None (deduped, no spam)", r4 is None, str(r4))
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    conn.close()
    check("still 3 CLUSTER rows (no re-log on growth)", n == 3, f"n={n}")


def test_record_and_check_time_injection():
    """now= injection (used by the historical reconstruction): 3 strikes within a
    30-min historical window cluster + log; the SAME 3 strikes spaced >30 min apart
    never reach 3 distinct in-window, so nothing fires. Proves the replay uses
    historical time, not wall-clock."""
    tmp = tempfile.mkdtemp()
    base = 1_700_000_000.0
    # within-window
    db1 = os.path.join(tmp, "ao_ti1.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    ic._recent_fires.clear(); ic._cluster_dedup.clear()
    ic.record_and_check(_insider(615.0), db_path=db1, now=base)
    ic.record_and_check(_insider(617.5), db_path=db1, now=base + 60)
    r = ic.record_and_check(_insider(620.0), db_path=db1, now=base + 120)
    check("within-window 3 strikes -> 3-cluster", r and r["n_strikes"] == 3, str(r))
    conn = sqlite3.connect(db1)
    n1 = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    conn.close()
    check("within-window logs 3 rows", n1 == 3, f"n={n1}")
    # spaced > 30 min apart -> each strike GC's the prior -> never 3 distinct in window
    db2 = os.path.join(tmp, "ao_ti2.db")
    ic._recent_fires.clear(); ic._cluster_dedup.clear()
    ic.record_and_check(_insider(615.0), db_path=db2, now=base)
    ic.record_and_check(_insider(617.5), db_path=db2, now=base + 1900)
    ic.record_and_check(_insider(620.0), db_path=db2, now=base + 3800)
    # 0 fires => log_cluster_outcomes never ran => no table; treat absent table as 0
    conn = sqlite3.connect(db2)
    try:
        n2 = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER'").fetchone()[0]
    except sqlite3.OperationalError:
        n2 = 0
    finally:
        conn.close()
    check("spaced-out strikes never cluster (0 rows)", n2 == 0, f"n={n2}")


def test_semis_shape_and_alert_type():
    """semis_signals emits strikes as a bare float list + needs its own alert_type.
    log_cluster_outcomes must tolerate that shape and tag rows 'CLUSTER_SEMIS'."""
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao_semis.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    semis = {"kind": "CLUSTER", "ticker": "MU", "expiration": "2026-08-15",
             "direction": "BULL", "option_type": "CALL", "n_strikes": 3,
             "strikes": [130.0, 135.0, 140.0], "notional": 2_000_000,
             "max_score": 6, "first_ts": 1_700_000_000, "last_ts": 1_700_000_500}
    n = ic.log_cluster_outcomes(semis, db_path=db, alert_type="CLUSTER_SEMIS")
    check("semis float-strike dict logs 3 rows", n == 3, str(n))
    conn = sqlite3.connect(db)
    at = {r[0] for r in conn.execute("SELECT DISTINCT alert_type FROM alert_outcomes").fetchall()}
    ks = conn.execute("SELECT DISTINCT strike FROM alert_outcomes ORDER BY strike").fetchall()
    conn.close()
    check("alert_type=CLUSTER_SEMIS (segmented bucket)", at == {"CLUSTER_SEMIS"}, str(at))
    check("float strikes logged 130/135/140", [r[0] for r in ks] == [130.0, 135.0, 140.0], str(ks))


def test_index_etf_routed_to_cluster_index():
    """Broad-market index/ETF 0DTE clusters log as CLUSTER_INDEX (kept out of the
    clean single-name CLUSTER bucket); single-names stay CLUSTER; an explicit
    alert_type is always respected."""
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "ao_idx.db")
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    spy = {**_cluster(3), "ticker": "SPY"}
    nvda = {**_cluster(3), "ticker": "NVDA"}
    ic.log_cluster_outcomes(spy, db_path=db)                              # -> CLUSTER_INDEX
    ic.log_cluster_outcomes(nvda, db_path=db)                             # -> CLUSTER
    ic.log_cluster_outcomes(spy, db_path=db, alert_type="CLUSTER_SEMIS")  # explicit respected
    conn = sqlite3.connect(db)
    pairs = set(conn.execute("SELECT DISTINCT alert_type, ticker FROM alert_outcomes").fetchall())
    conn.close()
    check("SPY default -> CLUSTER_INDEX", ("CLUSTER_INDEX", "SPY") in pairs, str(pairs))
    check("NVDA -> CLUSTER (single-name clean)", ("CLUSTER", "NVDA") in pairs, str(pairs))
    check("NVDA never routed to CLUSTER_INDEX", ("CLUSTER_INDEX", "NVDA") not in pairs, str(pairs))
    check("explicit CLUSTER_SEMIS respected for any ticker", ("CLUSTER_SEMIS", "SPY") in pairs, str(pairs))
    check("_is_index_etf: SPY=True, NVDA=False", ic._is_index_etf("spy") and not ic._is_index_etf("NVDA"))


def _spy(strike):
    return {"ticker": "SPY", "expiration": "2026-07-18", "option_type": "call",
            "sentiment": "BULLISH", "strike": strike, "insider_score": 6}


def test_index_cluster_telegram_suppressed():
    """Index/ETF 3-strike cluster is CAPTURED as CLUSTER_INDEX but record_and_check
    returns None (no Telegram ping); CLUSTER_INDEX_TELEGRAM=1 re-enables it."""
    tmp = tempfile.mkdtemp()
    os.environ.pop("CLUSTER_OUTCOME_LOG", None)
    os.environ.pop("CLUSTER_INDEX_TELEGRAM", None)
    db = os.path.join(tmp, "ao_sup.db")
    ic._recent_fires.clear(); ic._cluster_dedup.clear()
    ic.record_and_check(_spy(600.0), db_path=db)
    ic.record_and_check(_spy(601.0), db_path=db)
    r = ic.record_and_check(_spy(602.0), db_path=db)
    check("index 3-strike -> None (Telegram suppressed)", r is None, str(r))
    conn = sqlite3.connect(db)
    n_idx = conn.execute("SELECT COUNT(*) FROM alert_outcomes WHERE alert_type='CLUSTER_INDEX'").fetchone()[0]
    conn.close()
    check("index cluster still captured as CLUSTER_INDEX (3 legs)", n_idx == 3, f"n={n_idx}")
    # flag ON -> surfaced again
    os.environ["CLUSTER_INDEX_TELEGRAM"] = "1"
    try:
        ic._recent_fires.clear(); ic._cluster_dedup.clear()
        db2 = os.path.join(tmp, "ao_sup2.db")
        ic.record_and_check(_spy(600.0), db_path=db2)
        ic.record_and_check(_spy(601.0), db_path=db2)
        r2 = ic.record_and_check(_spy(602.0), db_path=db2)
        check("CLUSTER_INDEX_TELEGRAM=1 -> index cluster surfaced", r2 and r2["n_strikes"] == 3, str(r2))
    finally:
        os.environ.pop("CLUSTER_INDEX_TELEGRAM", None)


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
    test_record_and_check_logs_at_3_strikes()
    test_record_and_check_dedup_within_window()
    test_record_and_check_time_injection()
    test_semis_shape_and_alert_type()
    test_index_etf_routed_to_cluster_index()
    test_index_cluster_telegram_suppressed()
    test_imports()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
