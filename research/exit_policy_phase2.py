"""Exit-policy Phase 2 — partial-scaling + CROSS-REGIME (Jan-Jun), the test that
decides whether the Phase-1 'don't cap winners' finding holds outside April.

Phase 1 (April only) said: hold-to-expiry beats every managed exit; fixed TPs are
worst. Two open questions this answers:
  1. Does the RANKING survive across regimes (incl the June selloff)?  -> per-MONTH table.
  2. Does PARTIAL SCALING (sell a fraction at +X%, run the rest) beat pure hold-to-expiry
     on a risk-adjusted basis -> attacking the -100% median while keeping the tail?

Entries: recompute qualified king-up events (king up>=0.5% + floor-leapfrog) from
gex_struct_eod across Jan-Jun, stratified-sample ~N/month -> a regime-diverse sample of the
user's short-dated long-call style. OTM+4% / DTE~21 call, real daily option paths
(/v3/option/history/eod), ask-in/bid-out fills.

Run: python research/exit_policy_phase2.py [--per-month 40 --otm 4 --dte 21]
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theta_options import expirations, strikes, pick_exp, add_cal_days, to_yyyymmdd
from exit_policy_optimizer import eod_path, agg, COMMISSION_RT

RNG = np.random.default_rng(20260621)
DB = ROOT / "gex_backtest" / "work.db"


def cross_regime_entries(per_month):
    """Qualified king-up events from gex_struct_eod, stratified-sampled per month."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql("SELECT date,root,spot,king,floor FROM gex_struct_eod", c); c.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["root", "date"])
    g = df.groupby("root")
    df["king_prev"] = g["king"].shift(1)
    df["floor_ok"] = df["floor"] >= df["king_prev"] * 0.99
    df["king_up"] = (df["king"] - df["king_prev"]) / df["king_prev"] * 100.0
    ev = df[(df["king_up"] >= 0.5) & df["floor_ok"]].dropna(subset=["king_prev"]).copy()
    ev["ym"] = ev["date"].dt.strftime("%Y-%m")
    out = []
    for ym, gg in ev.groupby("ym"):
        take = min(per_month, len(gg))
        out.append(gg.sample(take, random_state=int(RNG.integers(0, 1e6))))
    return pd.concat(out).reset_index(drop=True)


def simulate(path, entry_ask):
    """Exit policies incl partial-scaling. Returns {policy: pnl_pct}."""
    if not path or entry_ask <= 0:
        return {}
    comm = COMMISSION_RT / (entry_ask * 100.0) * 100.0
    def pnl(px):
        return (px - entry_ask) / entry_ask * 100.0
    res = {}
    res["hold_expiry"] = pnl(path[-1]["bid"]) - comm
    # wide trailing 50%
    peak = entry_ask; tr_exit = None
    for r in path[1:]:
        peak = max(peak, r["high"])
        if r["low"] <= peak * 0.5:
            tr_exit = peak * 0.5; break
    res["trail_50"] = pnl(tr_exit if tr_exit is not None else path[-1]["bid"]) - comm

    # PARTIAL SCALING: sell frac at +tp (limit), run the rest to expiry (bid).
    def scale(tp_pct, frac):
        tp = entry_ask * (1 + tp_pct / 100.0)
        sold = None
        for r in path[1:]:
            if r["high"] >= tp:
                sold = (tp - entry_ask) / entry_ask * 100.0; break
        runner = pnl(path[-1]["bid"])
        if sold is None:
            return runner - comm            # tp never hit -> whole position to expiry
        return frac * sold + (1 - frac) * runner - comm
    res["scale_half_50"] = scale(50, 0.5)
    res["scale_half_100"] = scale(100, 0.5)
    res["scale_third_100"] = scale(100, 1 / 3)
    res["scale_third_150"] = scale(150, 1 / 3)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-month", type=int, default=40)
    ap.add_argument("--otm", type=float, default=4.0)
    ap.add_argument("--dte", type=int, default=21)
    a = ap.parse_args()
    ent = cross_regime_entries(a.per_month)
    print(f"[phase2] {len(ent)} cross-regime entries, "
          f"by month {ent['ym'].value_counts().sort_index().to_dict()}")

    by_pol, by_pol_month, skips = {}, {}, 0
    for _, r in ent.iterrows():
        edate = to_yyyymmdd(r["date"]); ym = r["ym"]
        exps = expirations(r["root"])
        if not exps:
            skips += 1; continue
        exp, _ = pick_exp(exps, add_cal_days(edate, a.dte))
        ks = strikes(r["root"], exp) if exp else None
        if not ks:
            skips += 1; continue
        strike = min(ks, key=lambda k: abs(k - float(r["spot"]) * (1 + a.otm / 100.0)))
        path = eod_path(r["root"], exp, strike, "C", edate, add_cal_days(edate, 45))
        if len(path) < 3 or path[0]["ask"] <= 0:
            skips += 1; continue
        res = simulate(path, path[0]["ask"])
        for pol, v in res.items():
            by_pol.setdefault(pol, []).append(v)
            by_pol_month.setdefault(pol, {}).setdefault(ym, []).append(v)

    rows = []
    for pol, pnls in by_pol.items():
        s = agg(pnls)
        if s:
            months = {ym: round(float(np.mean(v)), 1) for ym, v in sorted(by_pol_month[pol].items())}
            rows.append({"policy": pol, **s, "by_month_expectancy": months})
    rows.sort(key=lambda r: -r["expectancy_pct"])
    out = {"n_entries": len(ent), "skips": skips, "config": {"otm": a.otm, "dte": a.dte},
           "policies": rows}
    op = ROOT / "research" / "results" / "exit_policy_phase2_crossregime.json"
    op.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{'POLICY':>16} {'n':>4} {'EXPECT%':>8} {'CI95':>15} {'med%':>6} {'WR':>5} "
          f"{'>100%':>6} {'max%':>7}")
    for r in rows:
        print(f"{r['policy']:>16} {r['n']:>4} {r['expectancy_pct']:>8} {str(r['exp_ci95']):>15} "
              f"{r['median_pct']:>6} {r['win_rate']:>5} {r['frac_gt_100pct']:>6} {r['max_pct']:>7}")
    print("\nPER-MONTH expectancy (regime robustness — watch 2026-06 selloff):")
    for r in rows:
        print(f"  {r['policy']:>16}: {r['by_month_expectancy']}")
    print(f"\nskips: {skips}  ->  {op}")


if __name__ == "__main__":
    main()
