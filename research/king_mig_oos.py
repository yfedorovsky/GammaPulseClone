"""King-migration OOS re-validation (Jan-Jun 2026) — does the spot edge survive
OUTSIDE April, or was the n=174 validation an April artifact?

The validated detector used live 5-min snapshots + a 5-gate qualifier. The EOD
gex_struct_eod table has only daily king/floor, so this is a COARSER daily proxy:
  event = day-over-day king UP >= MIN_PCT  AND  floor-leapfrog (floor[t] >= king[t-1]*0.99)
          (the floor-leapfrog gate is the key 'real migration not noise' filter, and
           it IS in the EOD data).
Then forward HORIZON-trading-day SPOT return on event days vs the unconditional base.
Inference: permutation null + DAY-clustered bootstrap CI (market-wide days correlate).
The decisive output is the MONTH-BY-MONTH lift — is it April-only?

Run: python research/king_mig_oos.py [--min-pct 0.5 --horizon 5 --no-leapfrog]
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(20260621)
DB = ROOT / "gex_backtest" / "work.db"


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql("SELECT date,root,spot,king,floor FROM gex_struct_eod", c)
    c.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["root", "date"]).reset_index(drop=True)


def build(df, min_pct, horizon, leapfrog):
    df = df.copy()
    g = df.groupby("root")
    df["king_prev"] = g["king"].shift(1)
    df["fwd"] = g["spot"].shift(-horizon) / df["spot"] - 1.0
    df["king_chg_pct"] = (df["king"] - df["king_prev"]) / df["king_prev"] * 100.0
    ev = df["king_chg_pct"] >= min_pct
    if leapfrog:
        ev = ev & (df["floor"] >= df["king_prev"] * 0.99)
    df["event"] = ev.fillna(False)
    df["ym"] = df["date"].dt.strftime("%Y-%m")
    return df.dropna(subset=["fwd"]).reset_index(drop=True)


def analyze(df):
    ev = df[df["event"]]["fwd"].to_numpy()
    base = df["fwd"].to_numpy()
    if ev.size < 20:
        return {"status": "THIN", "n_events": int(ev.size)}
    ev_mean, base_mean = float(ev.mean()), float(base.mean())
    lift = ev_mean - base_mean
    # permutation null: random base draws of size n_events
    n = ev.size
    null = np.array([base[RNG.integers(0, base.size, n)].mean() for _ in range(5000)])
    perm_p = float((null >= ev_mean).mean())
    # DAY-clustered bootstrap CI on the lift (resample dates)
    ev_by_d, base_by_d = {}, {}
    for d, gg in df.groupby("date"):
        ev_by_d[d] = gg[gg["event"]]["fwd"].to_numpy()
        base_by_d[d] = gg["fwd"].to_numpy()
    dates = np.array(list(base_by_d.keys()))
    boots = []
    for _ in range(3000):
        ds = dates[RNG.integers(0, len(dates), len(dates))]
        e = np.concatenate([ev_by_d[d] for d in ds if ev_by_d[d].size])
        b = np.concatenate([base_by_d[d] for d in ds])
        if e.size and b.size:
            boots.append(e.mean() - b.mean())
    ci = [round(float(np.percentile(boots, 2.5)) * 100, 2),
          round(float(np.percentile(boots, 97.5)) * 100, 2)]
    # MONTH-BY-MONTH: event fwd mean, base fwd mean, lift, n
    months = {}
    for ym, gg in df.groupby("ym"):
        e = gg[gg["event"]]["fwd"].to_numpy()
        if e.size >= 8:
            months[ym] = {"n_ev": int(e.size),
                          "event_fwd_pct": round(float(e.mean()) * 100, 2),
                          "base_fwd_pct": round(float(gg["fwd"].mean()) * 100, 2),
                          "lift_pct": round(float(e.mean() - gg["fwd"].mean()) * 100, 2),
                          "win": round(float((e > 0).mean()), 3)}
    # April vs non-April
    apr = df[(df["ym"] == "2026-04") & df["event"]]["fwd"]
    nonapr = df[(df["ym"] != "2026-04") & df["event"]]["fwd"]
    apr_base = df[df["ym"] == "2026-04"]["fwd"]; non_base = df[df["ym"] != "2026-04"]["fwd"]
    return {"status": "OK", "n_events": int(ev.size), "n_rows": int(len(df)),
            "event_fwd_pct": round(ev_mean * 100, 2), "base_fwd_pct": round(base_mean * 100, 2),
            "lift_pct": round(lift * 100, 2), "lift_ci95_pct": ci, "perm_p": round(perm_p, 4),
            "event_win": round(float((ev > 0).mean()), 3),
            "month_by_month": dict(sorted(months.items())),
            "april_lift_pct": round(float(apr.mean() - apr_base.mean()) * 100, 2) if len(apr) else None,
            "april_n": int(len(apr)),
            "non_april_lift_pct": round(float(nonapr.mean() - non_base.mean()) * 100, 2) if len(nonapr) else None,
            "non_april_n": int(len(nonapr)),
            "verdict": "SURVIVES_OOS" if (lift > 0 and ci[0] > 0 and perm_p < 0.05) else "FRAGILE_or_NULL"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pct", type=float, default=0.5)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--no-leapfrog", action="store_true")
    a = ap.parse_args()
    df = build(load(), a.min_pct, a.horizon, leapfrog=not a.no_leapfrog)
    res = analyze(df)
    res["params"] = {"min_king_up_pct": a.min_pct, "horizon_days": a.horizon,
                     "floor_leapfrog": not a.no_leapfrog}
    out = ROOT / "research" / "results" / "king_mig_oos.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
