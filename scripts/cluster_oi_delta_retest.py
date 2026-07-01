"""Re-test the INFORMED CLUSTER verdict, split by OI-delta (accumulation vs exit).

The UW/WhaleWatch "AMD trap" insight: flow can LOOK informed (high V/OI, ASK-side) yet be a
systematic EXIT — the tell is OPEN INTEREST falling across the event, not rising. GammaPulse's
own verdict graded INFORMED CLUSTER as EXHAUST on average (short-horizon markout <= 0). The
hypothesis this tests: that EXHAUST is driven by the EXIT clusters (OI shrinks); the ACCUMULATION
clusters (OI grows across the fire) may actually LEAD. If so, an OI-delta gate rehabilitates the
detector instead of killing it.

Method: for each CLUSTER / CLUSTER_SEMIS leg in alert_outcomes that has a backfilled markout AND
falls inside the oi_delta snapshot window, compute the OI change ACROSS the fire from the daily
OI snapshots:
    pre  = OI snapshot on/before the fire date
    post = OI snapshot ~4 days later (captures the settlement of the fire session)
    dOI% = (post - pre) / pre
Then split legs into ACCUM (dOI% > +10%), EXIT (dOI% < -10%), FLAT, and compare their markout.

    python scripts/cluster_oi_delta_retest.py

Read-only. ASCII output. (Only clusters fired within the ~21-day oi_delta history are gradable.)
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import statistics as _stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import oi_delta  # noqa: E402

AO_DB = "alert_outcomes.db"
ACCUM_TH, EXIT_TH = 0.10, -0.10
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def _fire_date(ts: float) -> str:
    d = _dt.datetime.fromtimestamp(ts, _ET) if _ET else _dt.datetime.fromtimestamp(ts)
    return d.date().isoformat()


def _regime(dpct: float) -> str:
    if dpct > ACCUM_TH:
        return "ACCUM"
    if dpct < EXIT_TH:
        return "EXIT"
    return "FLAT"


def run():
    c = sqlite3.connect(AO_DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT ticker, expiration, strike, option_type, fired_at,
                  opt_mark_1m_pct, opt_mark_5m_pct, opt_mark_15m_pct,
                  opt_mfe_pct, opt_mae_pct
           FROM alert_outcomes
           WHERE alert_type IN ('CLUSTER','CLUSTER_SEMIS')
             AND opt_mark_5m_pct IS NOT NULL AND expiration IS NOT NULL""").fetchall()
    c.close()

    buckets: dict[str, list[sqlite3.Row]] = {"ACCUM": [], "EXIT": [], "FLAT": []}
    stats = {"total": 0, "no_oi": 0, "expired": 0, "no_delta": 0, "graded": 0}
    for r in rows:
        stats["total"] += 1
        fd = _fire_date(r["fired_at"])
        exp = str(r["expiration"])[:10]
        if exp <= fd:                       # 0DTE / expired-same-day: no post-fire OI
            stats["expired"] += 1
            continue
        post_asof = (_dt.date.fromisoformat(fd) + _dt.timedelta(days=4)).isoformat()
        post_asof = min(post_asof, exp)     # don't look past expiry
        pre_oi, pre_d = oi_delta.get_oi_asof(r["ticker"], exp, r["strike"], r["option_type"], fd, "before")
        post_oi, post_d = oi_delta.get_oi_asof(r["ticker"], exp, r["strike"], r["option_type"], post_asof, "before")
        if pre_oi is None or post_oi is None or pre_oi <= 0:
            stats["no_oi"] += 1
            continue
        if post_d == pre_d:                 # no newer snapshot → no delta
            stats["no_delta"] += 1
            continue
        dpct = (post_oi - pre_oi) / pre_oi
        buckets[_regime(dpct)].append(r)
        stats["graded"] += 1
    return buckets, stats


def _summ(rows, col):
    xs = [r[col] for r in rows if r[col] is not None]
    if not xs:
        return "  -"
    return f"med={_stats.median(xs):+6.2f}  mean={_stats.mean(xs):+6.2f}"


def report(buckets, stats):
    print("=" * 84)
    print("INFORMED CLUSTER re-test — split by OI-delta across the fire (accumulation vs exit)")
    print("=" * 84)
    print(f"legs: {stats['total']} total | {stats['expired']} same-day-exp | "
          f"{stats['no_oi']} outside OI window | {stats['no_delta']} no delta | "
          f"{stats['graded']} GRADED")
    print("\n                      n    mark_1m         mark_5m         mark_15m        MFE            MAE")
    for name in ("ACCUM", "FLAT", "EXIT"):
        rs = buckets[name]
        if not rs:
            print(f"  {name:<6} n=  0")
            continue
        print(f"  {name:<6} n={len(rs):>4}   "
              f"{_summ(rs,'opt_mark_1m_pct'):<15} {_summ(rs,'opt_mark_5m_pct'):<15} "
              f"{_summ(rs,'opt_mark_15m_pct'):<15} {_summ(rs,'opt_mfe_pct'):<14} {_summ(rs,'opt_mae_pct')}")
    print("\n  -- convex-tail capture (the exit policy lives here): % reaching +33% MFE, % hitting -30% MAE --")
    for name in ("ACCUM", "FLAT", "EXIT"):
        rs = buckets[name]
        if not rs:
            continue
        reach = sum(1 for r in rs if r["opt_mfe_pct"] and r["opt_mfe_pct"] >= 33) / len(rs) * 100
        stop = sum(1 for r in rs if r["opt_mae_pct"] and r["opt_mae_pct"] <= -30) / len(rs) * 100
        # crude exit-policy proxy: 1/3 locked at +33 when reached, 2/3 assumed stopped at -30 when MAE<=-30
        pnl = []
        for r in rs:
            reached = r["opt_mfe_pct"] is not None and r["opt_mfe_pct"] >= 33
            stopped = r["opt_mae_pct"] is not None and r["opt_mae_pct"] <= -30
            close = r["opt_mark_15m_pct"] or 0
            if reached and stopped:
                pnl.append((1/3)*33 + (2/3)*(-30))
            elif stopped:
                pnl.append(-30)
            elif reached:
                pnl.append((1/3)*33 + (2/3)*close)
            else:
                pnl.append(close)
        print(f"  {name:<6} reach+33%={reach:4.1f}%  stop-30%={stop:4.1f}%  "
              f"exit-policy meanR={_stats.mean(pnl):+6.2f}")
    print("\n" + "=" * 84)
    a, e = buckets["ACCUM"], buckets["EXIT"]
    if len(a) >= 15 and len(e) >= 15:
        am = _stats.median([r["opt_mark_5m_pct"] for r in a if r["opt_mark_5m_pct"] is not None])
        em = _stats.median([r["opt_mark_5m_pct"] for r in e if r["opt_mark_5m_pct"] is not None])
        print(f"VERDICT: 5m markout  ACCUM med={am:+.2f}  vs  EXIT med={em:+.2f}  (spread {am-em:+.2f})")
        if am > em + 1.0:
            print("  -> OI-delta SEPARATES: accumulation clusters lead exit clusters. Gate is worth")
            print("     wiring (demote/flag EXIT clusters). Re-run with more forward data to confirm.")
        else:
            print("  -> OI-delta does NOT cleanly separate here (small/short window). Keep tagging")
            print("     forward; don't gate yet.")
    else:
        print(f"VERDICT: too few gradable legs (ACCUM={len(a)}, EXIT={len(e)}) — the oi_delta window")
        print("  (~21d) only overlaps recent clusters. Wire the live tag + accrue forward.")
    print("=" * 84)


if __name__ == "__main__":
    b, s = run()
    report(b, s)
