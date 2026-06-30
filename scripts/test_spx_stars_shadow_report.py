"""Tests for the SPX stars-align shadow verdict tooling (exit-policy proxy + buckets).
Run: python scripts/test_spx_stars_shadow_report.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.spx_stars_shadow_report as r  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_exit_policy_pnl():
    check("stopped out (MAE<=-30) -> -30", r.exit_policy_pnl(10, -35, 20) == -30.0)
    check("MAE exactly -30 -> stop", r.exit_policy_pnl(40, -30, 50) == -30.0)
    check("target hit, eod 20 -> 1/3*33 + 2/3*20 = 24.33",
          abs(r.exit_policy_pnl(40, -10, 20) - (33/3 + 2/3*20)) < 0.01)
    check("target hit, rest clamped to MFE 60 not eod 80",
          abs(r.exit_policy_pnl(60, -5, 80) - (33/3 + 2/3*60)) < 0.01)
    check("target hit, rest clamped to stop floor",
          abs(r.exit_policy_pnl(40, -10, -50) - (33/3 + 2/3*(-30))) < 0.01)
    check("neither target nor stop -> eod", r.exit_policy_pnl(20, -12, 5) == 5.0)
    check("neither + no eod -> 0", r.exit_policy_pnl(20, -12, None) == 0.0)


def test_bucket_stats():
    now = time.time()
    rows = [
        # (mfe, mae, high, close_eod, fired_at)
        (50.0, -10.0, 30.0, 24.0, now),         # entry 20, eod +20 -> target -> 24.33
        (10.0, -35.0, 22.0, 13.0, now),         # stopped -> -30
        (15.0, -12.0, 23.0, 19.55, now - 86400),  # entry 20, eod -2.25 -> neither -> -2.25
    ]
    s = r.bucket_stats(rows)
    check("n=3", s["n"] == 3, str(s))
    check("n_days=2", s["n_days"] == 2, str(s))
    check("median_mae = -12", s["median_mae"] == -12.0, str(s))
    check("pct_reach_target = 33 (1 of 3 >= +33)", s["pct_reach_target"] == 33, str(s))
    check("pct_hit_stop = 33 (1 of 3 <= -30)", s["pct_hit_stop"] == 33, str(s))
    check("empty rows -> n=0", r.bucket_stats([])["n"] == 0)


if __name__ == "__main__":
    print("test_spx_stars_shadow_report")
    test_exit_policy_pnl()
    test_bucket_stats()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
