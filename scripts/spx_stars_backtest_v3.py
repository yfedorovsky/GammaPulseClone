"""SPX STARS-ALIGN backtest v3 — the FAITHFUL all-gates test.

v1 tested the exit policy (unconditioned), v2 tested 2 proxy stars (trend+drive). v3 adds the
two gates that needed real SPX GEX — reconstructed by us from EOD greeks+OI
(scripts/spx_gex_eod_build.py -> data/spx_gex_eod.parquet) because Theta's index feed is gated:

  GATE stack graded per day (all must hold), using PRIOR-day GEX so there's no lookahead:
    * +gamma REGIME     : prev-EOD net gamma > 0  (POS)
    * AT-SUPPORT (king) : ATM strike within ATSUPPORT_PCT of the prev-EOD gamma king
    * spread OK         : prev-EOD ATM spread <= SPREAD_MAX
    * TREND up          : prev close > 5d MA   (from v2)
    * DRIVE up          : 10:00 > 09:30        (from v2)

Then grade ONLY the days the scanner would have fired, with the exit policy, one entry per
fire-day (DTE nearest 2 -> independent days, honest n). This is the closest-achievable
reconstruction of "all the stars aligned" from historical data.

STILL NOT modeled (no historical source): signal-not-DANGER, flow-not-fighting, directional
-prior. So v3 fires on a SUPERSET of the true scanner -> if even this can't beat the hurdle,
the live scanner (stricter) has a steep bar; if it does, the remaining gates only tighten it.
Expect a SMALL fire count -> wide CIs. Report the number honestly, significant or not.

    python scripts/spx_stars_backtest_v3.py [--atsupport 0.4] [--spread-max 0.10] [--slippage 0.0075]

ASCII-only.
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
    DTE_MAX, DTE_MIN, STORE, _atm_and_paths, sim_policy,
)
from scripts.spx_stars_backtest_v2 import _boot_ci, _tstat, build_signals  # noqa: E402
from scripts.theta_bulk_pull import scan  # noqa: E402

GEX_TABLE = ROOT / "data" / "spx_gex_eod.parquet"


def _load_gex():
    df = pl.read_parquet(GEX_TABLE).sort("d")
    days = df["d"].to_list()
    rec = {r["d"]: r for r in df.iter_rows(named=True)}
    return days, rec


def _prev_trading_day(sorted_days, D):
    # largest gex day strictly < D (binary-ish; lists are small)
    prev = None
    for d in sorted_days:
        if d < D:
            prev = d
        else:
            break
    return prev


def run(store, atsupport, spread_max, slip):
    lf = scan(store, "ohlc")
    print("building trend/drive signals + loading GEX structure ...", flush=True)
    sig = build_signals(lf)
    gdays, gex = _load_gex()

    funnel = {"considered": 0, "regime": 0, "at_support": 0, "spread": 0, "trend": 0, "drive": 0, "fire": 0}
    cand = {}  # day -> list of (dte, R, reached, stopped)
    exps = sorted(lf.select("expiration").unique().collect()["expiration"].to_list())
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
            k, ce, cp, _pe, _pp = res
            if ce is None or not cp:
                continue
            funnel["considered"] += 1
            Dp = _prev_trading_day(gdays, D)
            g = gex.get(Dp) if Dp else None
            if g is None:
                continue
            tr, dr = sig.get(D, (None, None))
            regime_ok = g["regime"] == "POS"
            at_support = abs(k - g["king"]) / k <= atsupport / 100.0
            spread_ok = (g["atm_spread_pct"] is not None) and (g["atm_spread_pct"] <= spread_max)
            if regime_ok:
                funnel["regime"] += 1
            if at_support:
                funnel["at_support"] += 1
            if spread_ok:
                funnel["spread"] += 1
            if tr:
                funnel["trend"] += 1
            if dr:
                funnel["drive"] += 1
            if regime_ok and at_support and spread_ok and tr and dr:
                funnel["fire"] += 1
                R, reached, stopped = sim_policy(ce, cp, slip)
                cand.setdefault(D, []).append((dte, R, reached, stopped))

    # one entry per fire-day: DTE nearest 2 (independent days)
    fires = []
    for D, lst in cand.items():
        dte, R, reached, stopped = min(lst, key=lambda x: abs(x[0] - 2))
        fires.append({"d": D, "dte": dte, "R": R, "reached": reached, "stopped": stopped})
    return fires, funnel


def report(fires, funnel, atsupport, spread_max, slip):
    print("\n" + "=" * 80)
    print(f"SPX STARS-ALIGN v3 — FAITHFUL GATE RECONSTRUCTION "
          f"(atsupport<={atsupport}%, spread<={spread_max}, slip {slip*100:.2f}%/side)")
    print("=" * 80)
    c = funnel["considered"]
    print("GATE FUNNEL (entry-days passing each gate, of "
          f"{c} considered 1-5 DTE ATM entries):")
    for g in ("regime", "at_support", "spread", "trend", "drive"):
        n = funnel[g]
        print(f"  {g:<11} {n:>4}  ({100*n/c:4.1f}%)")
    print(f"  ALL-ALIGNED {funnel['fire']:>3}  ({100*funnel['fire']/c:4.1f}%)  "
          f"-> {len(fires)} independent fire-days after 1-per-day dedup")
    if not fires:
        print("\n  NO fire-days survived the full gate stack. Loosen atsupport/spread or")
        print("  accept that all-stars-aligned essentially never triggered in-sample.")
        print("=" * 80)
        return
    rs = [f["R"] for f in fires]
    win = sum(1 for x in rs if x > 0) / len(rs) * 100
    stop = sum(1 for f in fires if f["stopped"]) / len(fires) * 100
    lo, hi = _boot_ci(rs)
    print(f"\nFIRE-DAY RESULT (exit policy, n={len(rs)}):")
    print(f"  meanR={_stats.mean(rs):+.3f}  medR={_stats.median(rs):+.3f}  win={win:.1f}%  "
          f"stop={stop:.1f}%  t={_tstat(rs):+.1f}")
    print(f"  95% bootstrap CI on mean: [{lo:+.3f}, {hi:+.3f}]")
    print("\n" + "=" * 80)
    m = _stats.mean(rs)
    if lo > 0:
        print(f"VERDICT: all-stars-aligned meanR={m:+.3f}, CI EXCLUDES 0 -> a REAL edge in-sample.")
    elif m > 0:
        print(f"VERDICT: all-stars-aligned meanR={m:+.3f} (positive) but CI [{lo:+.3f},{hi:+.3f}] "
              "includes 0 -> promising, NOT significant (small n). The scanner's forward")
        print("         proving-window is the only way to settle it.")
    else:
        print(f"VERDICT: all-stars-aligned meanR={m:+.3f} <= 0 -> the reconstructable gates do "
              "not clear the hurdle in-sample.")
    print("  (superset of the true scanner; remaining gates -- DANGER/flow/prior -- unmodeled.")
    print("   bull-year sample; median may be <0 so sizing stays decisive.)")
    print("=" * 80)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--atsupport", type=float, default=0.4, help="max %% dist ATM->king")
    ap.add_argument("--spread-max", type=float, default=0.10, help="max ATM spread fraction")
    ap.add_argument("--slippage", type=float, default=0.0075)
    a = ap.parse_args()
    if not GEX_TABLE.exists():
        raise SystemExit(f"missing {GEX_TABLE} — run scripts/spx_gex_eod_build.py first")
    fires, funnel = run(a.store, a.atsupport, a.spread_max, a.slippage)
    report(fires, funnel, a.atsupport, a.spread_max, a.slippage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
