"""Unit tests for per-underlying flow z-score (task #61, 4-LLM synthesis).

Today's signed buy-to-open delta flow is normalized against the name's OWN
trailing baseline so the mechanical call-overwrite hum is washed out — only a
≥2σ deviation reads as a standout. Shadow mode by default (no dispatch change).

Run:  python scripts/test_flow_zscore.py
"""
from __future__ import annotations

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

import server.flow_noise_filter as nf  # noqa: E402
from server.flow_noise_filter import compute_flow_zscore  # noqa: E402

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


def _ts_for(days_ago: int) -> int:
    """Epoch (noon localtime) for a day N days ago, so strftime localtime
    buckets it on the intended calendar day."""
    d = date.today() - timedelta(days=days_ago)
    return int(time.mktime((d.year, d.month, d.day, 12, 0, 0, 0, 0, -1)))


def _make_db(daily: dict[int, tuple[float, str]]) -> str:
    """daily: {days_ago: (net_delta_target, 'BULL'|'BEAR')}.
    We synthesize one ASK-opening row per day whose V·|Δ|·100 equals the target
    magnitude (delta fixed 0.5 → volume = target/50)."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="zscoretest_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE flow_alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, ticker TEXT, "
        "strike REAL, expiration TEXT, option_type TEXT, volume INTEGER, "
        "oi INTEGER, vol_oi REAL, last_price REAL, bid REAL, ask REAL, "
        "side TEXT, sentiment TEXT, iv REAL, delta REAL, notional REAL, spot REAL)"
    )
    for days_ago, (mag, direction) in daily.items():
        vol = int(abs(mag) / 50)  # 50 = |Δ|0.5 × 100
        if direction == "BULL":
            otype, sent, dlt = "call", "BULLISH", 0.5
        else:
            otype, sent, dlt = "put", "BEARISH", -0.5
        conn.execute(
            "INSERT INTO flow_alerts (ts,ticker,strike,expiration,option_type,"
            "volume,oi,vol_oi,last_price,bid,ask,side,sentiment,iv,delta,notional,spot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_ts_for(days_ago), "TST", 100, "2026-12-18", otype, vol, 10, vol / 10,
             1.0, 0, 0, "ASK", sent, 0.3, dlt, vol * 100, 100),
        )
    conn.commit()
    conn.close()
    return path


def _run(daily):
    db = _make_db(daily)
    nf._DB_PATH_OVERRIDE = db
    try:
        return compute_flow_zscore("TST")
    finally:
        nf._DB_PATH_OVERRIDE = None
        os.unlink(db)


def test_untrusted_when_too_few_days():
    # only 3 prior days → below FLOW_ZSCORE_MIN_DAYS
    daily = {0: (5_000_000, "BULL"), 1: (1_000_000, "BULL"),
             2: (1_000_000, "BULL"), 3: (1_000_000, "BULL")}
    z = _run(daily)
    check("not trusted with <5 prior days", z["trusted"] is False, str(z))
    check("z is None when untrusted", z["z"] is None, str(z))


def test_normal_day_not_standout():
    # 10 prior bull days ~1M each (low variance), today also ~1.2M bull → small z
    daily = {d: (1_000_000 + (d % 3) * 50_000, "BULL") for d in range(1, 11)}
    daily[0] = (1_100_000, "BULL")
    z = _run(daily)
    check("trusted", z["trusted"] is True, str(z))
    check("normal bull day is NOT a standout", z["standout"] is False,
          f"z={z['z']}")
    check("direction BULL", z["direction"] == "BULL", str(z))


def test_bear_standout_breaks_long_bias():
    # name is habitually mildly bullish (~1M/day), today flips hard BEAR → |z|≥2
    daily = {d: (1_000_000 + (d % 4) * 30_000, "BULL") for d in range(1, 11)}
    daily[0] = (8_000_000, "BEAR")  # today: big bearish standout
    z = _run(daily)
    check("trusted", z["trusted"] is True, str(z))
    check("today reads BEAR", z["direction"] == "BEAR", str(z))
    check("bearish day is a standout (|z|>=2)", z["standout"] is True,
          f"z={z['z']:.2f}")
    check("z is strongly negative", z["z"] is not None and z["z"] <= -2.0,
          f"z={z['z']}")


def test_shadow_mode_default():
    z = _run({d: (1_000_000, "BULL") for d in range(0, 11)})
    check("gate inactive by default (shadow)", z["gate_active"] is False, str(z))


def main() -> int:
    print("=== per-underlying flow z-score (task #61) tests ===")
    for fn in (test_untrusted_when_too_few_days, test_normal_day_not_standout,
               test_bear_standout_breaks_long_bias, test_shadow_mode_default):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*52}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
