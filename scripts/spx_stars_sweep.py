"""Robustness sweeps for the SPX STARS-ALIGN backtest — is v3's +2.1% real or cherry-picked?

v3 found the all-gates fire-set (n=51) has meanR +0.021, but a single threshold choice on
n=51 fat-tailed trades proves nothing. This harness answers the robustness questions the
verdict hinges on:
  1. GATE thresholds  — sweep at-support %, spread max, entry time, DTE. Does the edge persist
                        across reasonable choices, or only at one lucky corner?
  2. EXIT policy      — grid scale-point / stop / scale-fraction on the fire-set. Is
                        1/3@+33%/-30% good, or is there a robustly better (or worse) policy?

It builds the candidate set ONCE (the slow part: extract every 1-5 DTE ATM call path + its
gate signals) and caches it to parquet, so each sweep is instant and a teardown can't cost
the 3-min build. Then it re-filters + re-simulates cheaply per parameter cell.

    python scripts/spx_stars_sweep.py --build     # build/refresh the candidate cache
    python scripts/spx_stars_sweep.py             # run the sweeps from cache

ASCII-only. Reuses v3 gate inputs (GEX table + trend/drive signals).
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

from scripts.spx_stars_backtest import DTE_MAX, DTE_MIN, STORE, _atm_and_paths  # noqa: E402
from scripts.spx_stars_backtest_v2 import _boot_ci, _tstat, build_signals  # noqa: E402
from scripts.spx_stars_backtest_v3 import _load_gex, _prev_trading_day  # noqa: E402
from scripts.theta_bulk_pull import scan  # noqa: E402

CACHE = ROOT / "data" / "spx_cand_cache.parquet"
ENTRY_TODS = {"0945": 585, "1000": 600, "1030": 630, "1400": 840}


def build(store=STORE, entry_label="1000"):
    T = ENTRY_TODS[entry_label]
    lf = scan(store, "ohlc")
    print(f"building candidate cache (entry {entry_label}) ...", flush=True)
    sig = build_signals(lf)
    gdays, gex = _load_gex()
    rows = []
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
            res = _atm_and_paths(e.filter(pl.col("d") == D), entry_tod=T)
            if res is None:
                continue
            k, ce, cp, _pe, _pp = res
            if ce is None or not cp:
                continue
            Dp = _prev_trading_day(gdays, D)
            g = gex.get(Dp) if Dp else None
            if g is None:
                continue
            tr, dr = sig.get(D, (None, None))
            rows.append({
                "d": D, "dte": dte, "k": float(k), "entry": float(ce),
                "king_prev": float(g["king"]), "regime_pos": g["regime"] == "POS",
                "spread_prev": g["atm_spread_pct"],
                "trend": bool(tr) if tr is not None else False,
                "drive": bool(dr) if dr is not None else False,
                "hi": [float(x[0]) for x in cp], "lo": [float(x[1]) for x in cp],
                "cl": [float(x[2]) for x in cp],
            })
    df = pl.DataFrame(rows)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(CACHE)
    print(f"cached {df.height} candidates -> {CACHE}")
    return df


def _net(r, s):
    return ((1 + r) * (1 - s) - (1 + s)) / (1 + s)


def sim(entry, hi, lo, cl, slip, target, stop, scale):
    tgt = entry * (1 + target)
    stp = entry * (1 + stop)
    scaled = False
    for h, l, _c in zip(hi, lo, cl):
        if l <= stp:
            if scaled:
                return scale * _net(target, slip) + (1 - scale) * _net(stop, slip)
            return _net(stop, slip)
        if not scaled and h >= tgt:
            scaled = True
    close = cl[-1] if cl else entry
    run = (close - entry) / entry
    if scaled:
        return scale * _net(target, slip) + (1 - scale) * _net(run, slip)
    return _net(run, slip)


def _dedup_one_per_day(cands):
    by_day = {}
    for c in cands:
        d = c["d"]
        if d not in by_day or abs(c["dte"] - 2) < abs(by_day[d]["dte"] - 2):
            by_day[d] = c
    return list(by_day.values())


def _fires(cands, atsupport, spread_max):
    out = []
    for c in cands:
        if not c["regime_pos"] or not c["trend"] or not c["drive"]:
            continue
        if abs(c["k"] - c["king_prev"]) / c["k"] > atsupport / 100.0:
            continue
        sp = c["spread_prev"]
        if sp is None or sp > spread_max:
            continue
        out.append(c)
    return _dedup_one_per_day(out)


def _grade(fires, slip, target, stop, scale):
    rs = [sim(c["entry"], c["hi"], c["lo"], c["cl"], slip, target, stop, scale) for c in fires]
    return rs


def _line(rs):
    if len(rs) < 3:
        return f"n={len(rs):>3}  (too few)"
    lo, hi = _boot_ci(rs)
    return (f"n={len(rs):>3}  meanR={_stats.mean(rs):+.3f}  medR={_stats.median(rs):+.3f}  "
            f"t={_tstat(rs):+.1f}  CI[{lo:+.3f},{hi:+.3f}]")


def sweeps(slip=0.0075):
    cands = pl.read_parquet(CACHE).to_dicts()
    # cast list cols back
    print("=" * 92)
    print(f"ROBUSTNESS SWEEPS  (from {len(cands)} cached candidates, slippage {slip*100:.2f}%/side)")
    print("=" * 92)

    print("\n[1] GATE THRESHOLD sweep (exit policy fixed 1/3 @ +33% / -30%):")
    print("    at-support%   spread-max   ->  fire-day result")
    for ats in (0.2, 0.4, 0.7, 1.0):
        for spr in (0.03, 0.06, 0.12):
            f = _fires(cands, ats, spr)
            print(f"    {ats:>5.1f}%       {spr:>5.2f}        {_line(_grade(f, slip, 0.33, -0.30, 1/3))}")

    print("\n[2] EXIT-POLICY sweep on the v3 fire-set (at-support 0.4%, spread 0.12):")
    fires = _fires(cands, 0.4, 0.12)
    print(f"    (fire-set n={len(fires)})  target / stop / scale-frac  ->  result")
    for tgt in (0.25, 0.33, 0.50):
        for stp in (-0.25, -0.30, -0.40):
            print(f"    +{tgt*100:>2.0f}% / {stp*100:>3.0f}% / 1/3    {_line(_grade(fires, slip, tgt, stp, 1/3))}")
    print("    -- scale fraction (target +33%, stop -30%) --")
    for sc in (0.0, 1/3, 0.5, 1.0):
        lbl = "run-all(0)" if sc == 0 else ("half" if sc == 0.5 else ("all-out(1)" if sc == 1 else "third"))
        print(f"    scale {lbl:<11} {_line(_grade(fires, slip, 0.33, -0.30, sc))}")

    print("\n[3] DTE bucket (v3 gates, exit 1/3@+33%/-30%):")
    for lo_d, hi_d in ((1, 1), (2, 2), (3, 5), (1, 5)):
        sub = [c for c in fires if lo_d <= c["dte"] <= hi_d]
        print(f"    DTE {lo_d}-{hi_d}   {_line(_grade(sub, slip, 0.33, -0.30, 1/3))}")

    print("\n[4] SLIPPAGE sensitivity (v3 fire-set, 1/3@+33%/-30%):")
    for s in (0.0, 0.005, 0.0075, 0.015):
        print(f"    slip {s*100:>4.2f}%/side   {_line(_grade(fires, s, 0.33, -0.30, 1/3))}")
    print("=" * 92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--entry", default="1000", choices=list(ENTRY_TODS))
    ap.add_argument("--slippage", type=float, default=0.0075)
    a = ap.parse_args()
    if a.build or not CACHE.exists():
        build(a.store, a.entry)
    sweeps(a.slippage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
