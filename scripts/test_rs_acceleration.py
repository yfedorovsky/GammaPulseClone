"""Unit tests for server/rs_acceleration.py (task #56).

Covers the pure cores (tier_of_rank, accel_from_series, sector_breadth) and a
temp-DB roundtrip (record → fetch → compute_all_acceleration + retention).

Run:  python scripts/test_rs_acceleration.py
"""
from __future__ import annotations

import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.rs_acceleration as rsa  # noqa: E402

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


# ── tier_of_rank ──────────────────────────────────────────────────────────
def test_tier_of_rank():
    check("rank 95 -> TOP_10", rsa.tier_of_rank(95) == "TOP_10")
    check("rank 90 -> TOP_10 (boundary)", rsa.tier_of_rank(90) == "TOP_10")
    check("rank 85 -> TOP_20", rsa.tier_of_rank(85) == "TOP_20")
    check("rank 72 -> TOP_30", rsa.tier_of_rank(72) == "TOP_30")
    check("rank 50 -> BELOW_30", rsa.tier_of_rank(50) == "BELOW_30")
    check("rank None -> BELOW_30", rsa.tier_of_rank(None) == "BELOW_30")


# ── accel_from_series ─────────────────────────────────────────────────────
def test_accel_rising():
    a = rsa.accel_from_series([50, 52, 55, 60, 65, 70])
    check("rising -> ACCELERATING", a["direction"] == "ACCELERATING", str(a))
    check("rising -> positive accel", a["accel"] > 0)
    check("rising latest 70", a["latest"] == 70.0)


def test_accel_falling():
    a = rsa.accel_from_series([70, 65, 60, 55, 50, 45])
    check("falling -> DECELERATING", a["direction"] == "DECELERATING", str(a))
    check("falling -> negative accel", a["accel"] < 0)


def test_accel_flat():
    a = rsa.accel_from_series([50, 50, 51, 50, 49, 50])
    check("flat -> STABLE", a["direction"] == "STABLE", str(a))


def test_accel_short_and_empty():
    check("empty -> FLAT", rsa.accel_from_series([])["direction"] == "FLAT")
    check("single -> FLAT", rsa.accel_from_series([42])["direction"] == "FLAT")
    a2 = rsa.accel_from_series([40, 60])
    check("two points -> graded", a2["direction"] in ("ACCELERATING", "STABLE"))
    check("None values filtered", rsa.accel_from_series([None, 50, None, 55])["n"] == 2)


# ── sector_breadth ────────────────────────────────────────────────────────
def test_sector_breadth():
    # The AION divergence: a sector can win on Avg Score yet lose on Breadth-Wtd.
    universe = {
        # HIGHAVG: one monster + one mid leader → high average, shallow depth
        "AAA": {"score": 95, "universe_rank": 99},   # TOP_10
        "BBB": {"score": 90, "universe_rank": 72},   # TOP_30
        # BROAD: three names all clustered in the top tier → lower avg, deep breadth
        "CCC": {"score": 70, "universe_rank": 91},   # TOP_10
        "DDD": {"score": 70, "universe_rank": 91},   # TOP_10
        "EEE": {"score": 70, "universe_rank": 91},   # TOP_10
    }
    groups = {"HIGHAVG": ["AAA", "BBB"], "BROAD": ["CCC", "DDD", "EEE"]}
    res = rsa.sector_breadth(universe, groups)
    by = {r["sector"]: r for r in res}
    # HIGHAVG breadth_wtd = 100*(0.6*1 + 0.1*1)/2 = 35.0 ; avg = 92.5
    check("HIGHAVG breadth_wtd 35.0", by["HIGHAVG"]["breadth_wtd"] == 35.0, str(by["HIGHAVG"]))
    check("HIGHAVG avg 92.5", by["HIGHAVG"]["avg_score"] == 92.5)
    # BROAD breadth_wtd = 100*(0.6*3)/3 = 60.0 ; avg = 70.0
    check("BROAD breadth_wtd 60.0", by["BROAD"]["breadth_wtd"] == 60.0, str(by["BROAD"]))
    check("BROAD avg 70.0", by["BROAD"]["avg_score"] == 70.0)
    # the divergence: HIGHAVG higher avg but BROAD higher breadth
    check("HIGHAVG avg > BROAD avg", by["HIGHAVG"]["avg_score"] > by["BROAD"]["avg_score"])
    check("BROAD breadth > HIGHAVG breadth (depth wins)",
          by["BROAD"]["breadth_wtd"] > by["HIGHAVG"]["breadth_wtd"])
    # sorted by breadth_wtd desc → BROAD first (rewards deep participation)
    check("sorted by breadth_wtd", res[0]["sector"] == "BROAD")
    check("tier counts", by["BROAD"]["in_top10"] == 3 and by["HIGHAVG"]["in_top30"] == 1)
    # empty/missing sector skipped
    check("ghost sector skipped", rsa.sector_breadth(universe, {"GHOST": ["ZZZ"]}) == [])


# ── DB roundtrip ──────────────────────────────────────────────────────────
def test_db_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    rsa._DB_PATH_OVERRIDE = path
    try:
        rsa.init_rts_history_db()
        # build 6 days of history for 3 tickers
        rise = [50, 52, 55, 60, 65, 70]
        fall = [70, 65, 60, 55, 50, 45]
        flat = [50, 50, 51, 50, 49, 50]
        for i in range(6):
            d = (datetime.date(2026, 6, 1) + datetime.timedelta(days=i)).isoformat()
            uni = {
                "RISE": {"score": rise[i], "universe_rank": 80, "rs_score": 1, "ts_score": 1},
                "FALL": {"score": fall[i], "universe_rank": 50, "rs_score": 1, "ts_score": 1},
                "FLAT": {"score": flat[i], "universe_rank": 60, "rs_score": 1, "ts_score": 1},
            }
            n = rsa.record_rts_snapshot(uni, date=d)
            check(f"record day {i} wrote 3", n == 3) if i == 0 else None
        # fetch series oldest->newest
        ser = rsa.fetch_series("RISE", days=10)
        check("fetch_series RISE correct", ser == rise, str(ser))
        # acceleration ranking
        accel = rsa.compute_all_acceleration()
        order = [r["ticker"] for r in accel]
        check("RISE ranks above FALL", order.index("RISE") < order.index("FALL"), str(order))
        check("RISE accelerating", next(r for r in accel if r["ticker"] == "RISE")["direction"] == "ACCELERATING")
        check("FALL decelerating", next(r for r in accel if r["ticker"] == "FALL")["direction"] == "DECELERATING")
        acc = rsa.accelerators()
        dec = rsa.decelerators()
        check("accelerators has RISE", any(r["ticker"] == "RISE" for r in acc))
        check("decelerators top is FALL", dec and dec[0]["ticker"] == "FALL")
        # idempotent re-record same day
        d0 = "2026-06-01"
        rsa.record_rts_snapshot({"RISE": {"score": 99, "universe_rank": 99}}, date=d0)
        ser2 = rsa.fetch_series("RISE", days=10)
        check("idempotent upsert (no dup rows)", len(ser2) == 6, str(len(ser2)))
    finally:
        rsa._DB_PATH_OVERRIDE = None
        try:
            os.remove(path)
        except OSError:
            pass


def test_retention_prune():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    rsa._DB_PATH_OVERRIDE = path
    try:
        rsa.init_rts_history_db()
        old = (datetime.date.today() - datetime.timedelta(days=rsa.RETENTION_DAYS + 30)).isoformat()
        rsa.record_rts_snapshot({"OLD": {"score": 50, "universe_rank": 50}}, date=old)
        # a fresh record triggers prune of rows older than RETENTION_DAYS
        rsa.record_rts_snapshot({"NEW": {"score": 60, "universe_rank": 60}})
        check("old row pruned", rsa.fetch_series("OLD") == [])
        check("new row kept", len(rsa.fetch_series("NEW")) == 1)
    finally:
        rsa._DB_PATH_OVERRIDE = None
        try:
            os.remove(path)
        except OSError:
            pass


def main() -> int:
    print("=== rs_acceleration (task #56) tests ===")
    for fn in (test_tier_of_rank, test_accel_rising, test_accel_falling,
               test_accel_flat, test_accel_short_and_empty, test_sector_breadth,
               test_db_roundtrip, test_retention_prune):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
