"""King-migration EXECUTION optimizer — measure the REAL option economics of the
validated king-migration runner, and compare coarse execution choices (DTE, strike
moneyness, exit) on EXPECTANCY, protecting the right tail.

WHY: the validated backtest (docs/research/king_migration_runner_backtest.csv, n=174,
+4.14% spot for 4-6 migrations) measured SPOT returns only. Whether that translates to
OPTION profit after ask-in/bid-out fills + theta, and which strike/DTE/exit captures it
best, was never measured. This does, with the hardened ThetaData fill layer.

HONEST LIMIT: all 174 entries are 2026-04-10..04-22 (one ~2-week window, 174 names).
So FINE-tuned optima would overfit April. The robust read is the COARSE comparison
(option-economics of DTE/strike/exit) + bootstrap CIs; treat any specific 'winner' as
hypothesis-generating until confirmed on out-of-sample king-migration entries.

Objective (per the user): maximize EXPECTANCY (mean option P&L% net of fills+commission),
report the right-tail (P75, %>+100%) so a higher-expectancy rule that guts the tail is
flagged, not silently chosen.

Phase 1 (this file): entry=ask on entry_day, exit=bid on the SYSTEM exit_day; sweep
DTE x strike. Phase 2 (exit-rule simulation on the daily option path) is separate.

Run: python research/exec_optimizer.py [--min-mig 4 --max-mig 6] [--n 174]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theta_options import expirations, strikes, nbbo_at, pick_exp, add_cal_days, to_yyyymmdd

RNG = np.random.default_rng(20260621)
COMMISSION_RT = 1.30
DTE_GRID = [14, 21, 35]          # target calendar DTE at entry
OTM_GRID = [0.0, 0.04, 0.08]     # ATM, +4% OTM, +8% OTM (call side)
ENTRIES = ROOT / "docs" / "research" / "king_migration_runner_backtest.csv"


def boot_ci_mean(x, n_boot=4000, ci=95):
    x = np.asarray(x, float)
    if x.size < 5:
        return None
    bm = np.array([x[RNG.integers(0, x.size, x.size)].mean() for _ in range(n_boot)])
    lo, hi = np.percentile(bm, [(100 - ci) / 2, 100 - (100 - ci) / 2])
    return {"point": round(float(x.mean()), 1),
            "ci95": [round(float(lo), 1), round(float(hi), 1)],
            "excludes_0": bool(lo > 0 or hi < 0)}


def one_trade(ticker, entry_day, exit_day, entry_spot, dte, otm):
    """Buy ATM/OTM call DTE-out on entry_day close; sell at the system exit_day close.
    Returns (pnl_pct, info) or (None, skip_reason)."""
    edate = to_yyyymmdd(entry_day); xdate = to_yyyymmdd(exit_day)
    exps = expirations(ticker)
    if not exps:
        return None, "no_exp"
    exp, kind = pick_exp(exps, add_cal_days(edate, dte))
    if exp is None:
        return None, "no_exp"
    # exit no later than the last tradable day at/before expiry
    x_eff = min(xdate, exp)
    ks = strikes(ticker, exp)
    if not ks:
        return None, "no_strikes"
    strike = min(ks, key=lambda k: abs(k - entry_spot * (1 + otm)))
    en = nbbo_at(ticker, exp, strike, "C", edate)
    if en is None:
        return None, "no_entry_nbbo"
    ex = nbbo_at(ticker, exp, strike, "C", x_eff)
    if ex is None:
        return None, "no_exit_nbbo"
    entry_ask, exit_bid = en[1], ex[0]
    comm = COMMISSION_RT / (entry_ask * 100.0) * 100.0
    pnl = (exit_bid - entry_ask) / entry_ask * 100.0 - comm
    return pnl, {"exp": exp, "kind": kind, "strike": strike,
                 "entry_ask": round(entry_ask, 2), "exit_bid": round(exit_bid, 2)}


def agg(pnls):
    p = np.array(pnls, float)
    if p.size < 5:
        return {"n": int(p.size), "note": "thin"}
    return {"n": int(p.size),
            "expectancy_pct": round(float(p.mean()), 1),
            "expectancy_ci95": boot_ci_mean(p)["ci95"],
            "median_pct": round(float(np.median(p)), 1),
            "win_rate": round(float((p > 0).mean()), 3),
            "p75_pct": round(float(np.percentile(p, 75)), 1),
            "frac_gt_100pct": round(float((p > 100).mean()), 3),
            "max_pct": round(float(p.max()), 1), "min_pct": round(float(p.min()), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-mig", type=int, default=1)
    ap.add_argument("--max-mig", type=int, default=99)
    ap.add_argument("--n", type=int, default=999)
    a = ap.parse_args()
    df = pd.read_csv(ENTRIES)
    df = df[(df["n_migrations"] >= a.min_mig) & (df["n_migrations"] <= a.max_mig)].head(a.n)
    print(f"[exec-opt] {len(df)} entries (mig {a.min_mig}-{a.max_mig}), "
          f"window {df['entry_day'].min()}..{df['entry_day'].max()}")

    cells = {}   # (dte, otm) -> list of pnl
    skips = {}
    for _, r in df.iterrows():
        for dte in DTE_GRID:
            for otm in OTM_GRID:
                pnl, info = one_trade(r["ticker"], r["entry_day"], r["exit_day"],
                                      float(r["entry_spot"]), dte, otm)
                if pnl is None:
                    skips[info] = skips.get(info, 0) + 1
                    continue
                cells.setdefault((dte, otm), []).append(pnl)

    rows = []
    for (dte, otm), pnls in sorted(cells.items()):
        rows.append({"dte": dte, "otm_pct": int(otm * 100), **agg(pnls)})
    rows = [r for r in rows if r.get("expectancy_pct") is not None]
    rows.sort(key=lambda r: -r["expectancy_pct"])

    out = {"n_entries": len(df), "window": [df["entry_day"].min(), df["entry_day"].max()],
           "mig_filter": [a.min_mig, a.max_mig], "skips": skips,
           "grid": rows,
           "best_expectancy": rows[0] if rows else None}
    op = ROOT / "research" / "results" / f"exec_opt_kingmig_mig{a.min_mig}-{a.max_mig}.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{'DTE':>4} {'OTM%':>5} {'n':>4} {'EXPECT%':>8} {'CI95':>16} {'med%':>6} "
          f"{'WR':>5} {'P75%':>6} {'>100%':>6} {'max%':>7}")
    for r in rows:
        print(f"{r['dte']:>4} {r['otm_pct']:>5} {r['n']:>4} {r['expectancy_pct']:>8} "
              f"{str(r['expectancy_ci95']):>16} {r['median_pct']:>6} {r['win_rate']:>5} "
              f"{r['p75_pct']:>6} {r['frac_gt_100pct']:>6} {r['max_pct']:>7}")
    print(f"\nskips: {skips}  ->  {op}")


if __name__ == "__main__":
    main()
