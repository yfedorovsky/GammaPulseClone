"""SPX STARS-ALIGN backtest v2 — the SELECTIVITY test.

v1 (scripts/spx_stars_backtest.py) proved the exit policy adds value but unconditioned
near-ATM weekly-call entries are net-negative (~-1.8%/trade) with NO directional edge, so
the scanner's SELECTIVITY must clear that hurdle to be real. gex_struct_eod has no SPX/SPY,
so instead of external GEX regime we compute the scanner's two most-testable "stars" straight
from the pulled option data via put-call parity:

  * TREND (bullish):  prior-day implied spot > its trailing 5-day MA (known before entry).
  * OPENING DRIVE up: implied spot at 10:00 > at 09:30 (known at the 10:00 entry).

Then we slice the SAME exit-policy call trades by these filters and ask: does firing only on
trend-up / drive-up / both lift call expectancy above the unconditioned ~-1.8% hurdle? That
is the whole question of whether the scanner's selectivity has an edge.

No lookahead: both signals use only information available at or before the 10:00 entry.

    python scripts/spx_stars_backtest_v2.py [--slippage 0.0075] [--max-expirations N]

ASCII-only. Reuses v1's sim + ATM inference.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import statistics as _stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from scripts.spx_stars_backtest import (  # noqa: E402
    DTE_MAX, DTE_MIN, ENTRY_TOD, STORE, _atm_and_paths, _net, sim_policy,
)
from scripts.theta_bulk_pull import scan  # noqa: E402

OPEN_TOD, EOD_TOD = 570, 955   # 09:30, 15:55


def _spot_at(lf, T):
    """Per-day parity-implied spot using the last close <= tod T, pooled across
    expirations+strikes (spot ~ K + call_K - put_K, median). Returns polars (d, spot)."""
    base = (lf.with_columns(pl.col("timestamp").dt.date().alias("d"),
                            (pl.col("timestamp").dt.hour().cast(pl.Int32) * 60
                             + pl.col("timestamp").dt.minute().cast(pl.Int32)).alias("tod"))
            .filter(pl.col("close").is_not_nan() & (pl.col("close") > 0) & (pl.col("tod") <= T)))
    snap = base.sort("tod").group_by("d", "expiration", "strike", "right").agg(pl.col("close").last().alias("px"))
    c = snap.filter(pl.col("right") == "CALL").select("d", "expiration", "strike", pl.col("px").alias("call"))
    p = snap.filter(pl.col("right") == "PUT").select("d", "expiration", "strike", pl.col("px").alias("put"))
    j = (c.join(p, on=["d", "expiration", "strike"])
         .with_columns((pl.col("strike") + pl.col("call") - pl.col("put")).alias("isp")))
    return j.group_by("d").agg(pl.col("isp").median().alias("spot")).sort("d").collect(engine="streaming")


def build_signals(lf):
    """Per-day (trend_up, drive_up), both computed with no lookahead past the 10:00 entry."""
    o = _spot_at(lf, OPEN_TOD).rename({"spot": "s_open"})
    t = _spot_at(lf, ENTRY_TOD).rename({"spot": "s_1000"})
    e = _spot_at(lf, EOD_TOD).rename({"spot": "s_eod"})
    sig = (o.join(t, on="d").join(e, on="d").sort("d")
           .with_columns(pl.col("s_eod").rolling_mean(5).shift(1).alias("ma5_prev"),
                         pl.col("s_eod").shift(1).alias("eod_prev"))
           .with_columns((pl.col("eod_prev") > pl.col("ma5_prev")).alias("trend_up"),
                         (pl.col("s_1000") > pl.col("s_open")).alias("drive_up")))
    out = {}
    for row in sig.iter_rows(named=True):
        out[row["d"]] = (bool(row["trend_up"]) if row["trend_up"] is not None else None,
                         bool(row["drive_up"]) if row["drive_up"] is not None else None)
    return out


def run(store, max_exps, slip):
    lf = scan(store, "ohlc")
    print("building daily trend + opening-drive signals from parity spot ...", flush=True)
    sig = build_signals(lf)
    exps = sorted(lf.select("expiration").unique().collect()["expiration"].to_list())
    if max_exps:
        exps = exps[-max_exps:]
    trades = []
    for E in exps:
        Ed = _dt.date.fromisoformat(E[:10])
        e = (lf.filter(pl.col("expiration") == E)
             .with_columns(pl.col("timestamp").dt.date().alias("d"),
                           (pl.col("timestamp").dt.hour().cast(pl.Int32) * 60
                            + pl.col("timestamp").dt.minute().cast(pl.Int32)).alias("tod"))
             .filter(pl.col("close").is_not_nan() & pl.col("close").is_not_null() & (pl.col("close") > 0))
             .collect(engine="streaming"))
        for D in e["d"].unique().to_list():
            dte = (Ed - D).days
            if not (DTE_MIN <= dte <= DTE_MAX):
                continue
            res = _atm_and_paths(e.filter(pl.col("d") == D))
            if res is None:
                continue
            _k, ce, cp, _pe, _pp = res       # CALLS only (the scanner is long calls)
            if ce is None or not cp:
                continue
            R, reached, stopped = sim_policy(ce, cp, slip)
            tr, dr = sig.get(D, (None, None))
            trades.append({"dte": dte, "R": R, "reached": reached, "stopped": stopped,
                           "trend_up": tr, "drive_up": dr})
    return trades


def _tstat(rs):
    if len(rs) < 2:
        return 0.0
    sd = _stats.pstdev(rs)
    return (_stats.mean(rs) / (sd / (len(rs) ** 0.5))) if sd > 0 else 0.0


def _boot_ci(rs, iters=2000):
    """95% bootstrap CI on the mean. Deterministic seed so re-runs match."""
    import random
    if len(rs) < 2:
        return (0.0, 0.0)
    rng = random.Random(42)
    n = len(rs)
    means = []
    for _ in range(iters):
        s = 0.0
        for _ in range(n):
            s += rs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    return (means[int(0.025 * iters)], means[int(0.975 * iters)])


def _blk(rows):
    if not rows:
        return "n=   0"
    rs = [r["R"] for r in rows]
    win = sum(1 for x in rs if x > 0) / len(rs) * 100
    stop = sum(1 for r in rows if r["stopped"]) / len(rows) * 100
    return (f"n={len(rs):>4}  meanR={_stats.mean(rs):+.3f}  medR={_stats.median(rs):+.3f}  "
            f"win={win:4.1f}%  stop={stop:4.1f}%  t={_tstat(rs):+.1f}")


def report(trades, slip):
    base = trades
    tr = [t for t in trades if t["trend_up"] is True]
    dr = [t for t in trades if t["drive_up"] is True]
    both = [t for t in trades if t["trend_up"] is True and t["drive_up"] is True]
    neither = [t for t in trades if t["trend_up"] is False and t["drive_up"] is False]
    print("\n" + "=" * 82)
    print(f"SPX STARS-ALIGN SELECTIVITY TEST (CALLS)   slippage {slip*100:.2f}%/side, 1-5 DTE ATM")
    print("=" * 82)
    print(f"  ALL (unconditioned)      {_blk(base)}")
    print(f"  TREND up (>5d MA)        {_blk(tr)}")
    print(f"  DRIVE up (10:00>9:30)    {_blk(dr)}")
    print(f"  TREND & DRIVE up         {_blk(both)}   <- the selective subset")
    print(f"  neither (control)        {_blk(neither)}")
    bm = _stats.mean([t["R"] for t in base]) if base else 0
    sm = _stats.mean([t["R"] for t in both]) if both else 0
    nm = _stats.mean([t["R"] for t in neither]) if neither else 0
    both_rs = [t["R"] for t in both]
    lo, hi = _boot_ci(both_rs)
    print("\n" + "=" * 82)
    print(f"VERDICT: selective (trend&drive) meanR={sm:+.3f}  vs  unconditioned={bm:+.3f}  "
          f"vs  neither={nm:+.3f}")
    print(f"  selective mean 95% bootstrap CI: [{lo:+.3f}, {hi:+.3f}]  (t={_tstat(both_rs):+.1f})")
    lift = sm - bm
    monotone = nm < bm < sm
    if lo > 0:
        print(f"  -> selectivity CLEARS the hurdle: +{lift:.3f} lift, CI EXCLUDES 0 -> real.")
    elif sm > 0 and monotone:
        print(f"  -> selectivity flips expectancy positive (+{lift:.3f}) and is MONOTONE "
              "(neither<all<selective), BUT the CI includes 0 -> directionally right, "
              "NOT yet significant. Don't oversell; needs more sample / the full gate stack.")
    else:
        print("  -> selectivity does NOT convincingly lift expectancy on these two stars.")
    print("  CAVEAT: 2 of the scanner's stars only (no GEX-regime/at-support); and the year")
    print("  was strongly bullish (6200->7600) so 'trend up' partly rides beta. Regime-robust")
    print("  confirmation needs a bear/chop sample. Median still <0 -> sizing (Kelly) is decisive.")
    print("=" * 82)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--max-expirations", type=int, default=0)
    ap.add_argument("--slippage", type=float, default=0.0075)
    a = ap.parse_args()
    trades = run(a.store, a.max_expirations, a.slippage)
    report(trades, a.slippage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
