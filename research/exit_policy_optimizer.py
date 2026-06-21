"""Exit-POLICY optimizer — the lever that doesn't need a predictive edge.

On a fat-tailed lottery payoff (which the king-migration / momentum option trades are),
the EXIT policy dominates expectancy: a +50% fixed TP that caps a +400% winner is wildly
different from a trailing stop that lets it run. Exit policy is about option MECHANICS
(theta, payoff shape) -> generalizes far better than directional signals.

Method: for a fixed entry distribution (the king-migration entries as a representative
sample of the user's short-dated long-call style) and a fixed contract config (OTM%+DTE),
pull the DAILY option path (/v3/option/history/eod: per-day high/low/close + bid/ask) from
entry to expiry, then simulate a MENU of exit policies on each path and compare them on
EXPECTANCY (net of realistic fills) while reporting the RIGHT TAIL (P75, %>+100%, max) so a
higher-expectancy rule that guts the tail is flagged, not silently chosen.

Fill discipline:
  entry  = EOD ASK on entry day (you buy at the offer)
  TP     = LIMIT sell: if a day's HIGH >= TP level -> filled at the TP level
  STOP   = STOP sell:  if a day's LOW  <= stop level -> filled at the stop level (can slip; honest-ish)
  trail  = if a day's LOW <= running-peak*(1-trail) -> filled at that trail level
  time/system/expiry = EOD BID on the exit day (you sell at the bid)

HONEST LIMIT: entries are April-2026 (single window). The exit-policy RANKING is far more
window-robust than entry edge (it's payoff-shape, not direction), but confirm cross-regime
(incl the June selloff) before locking a policy.

Run: python research/exit_policy_optimizer.py [--otm 4 --dte 21 --min-mig 1 --max-mig 99]
"""
from __future__ import annotations
import argparse, io, json, sys
from pathlib import Path
import numpy as np, pandas as pd, requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theta_options import THETA_URL, expirations, strikes, pick_exp, add_cal_days, to_yyyymmdd, _get

RNG = np.random.default_rng(20260621)
COMMISSION_RT = 1.30
ENTRIES = ROOT / "docs" / "research" / "king_migration_runner_backtest.csv"


def eod_path(ticker, exp, strike, right, start_int, end_int):
    """Per-day [{d, high, low, close, bid, ask}] from the EOD endpoint (one call)."""
    txt = _get(f"{THETA_URL}/v3/option/history/eod",
               {"symbol": ticker, "expiration": exp, "strike": f"{strike:.3f}",
                "right": right, "start_date": start_int, "end_date": end_int}, timeout=20)
    if not txt:
        return []
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return []
    cols = {c.lower().strip(): c for c in df.columns}
    need = ("high", "low", "close", "bid", "ask")
    if any(k not in cols for k in need):
        return []
    out = []
    for _, r in df.iterrows():
        try:
            row = {k: float(r[cols[k]]) for k in need}
        except Exception:
            continue
        if row["ask"] > 0:
            out.append(row)
    return out


def simulate(path, entry_ask, system_exit_idx):
    """Return {policy: pnl_pct} for one trade given its daily path (path[0]=entry day)."""
    if not path or entry_ask <= 0:
        return {}
    comm = COMMISSION_RT / (entry_ask * 100.0) * 100.0
    def pnl(exit_px):
        return (exit_px - entry_ask) / entry_ask * 100.0 - comm
    res = {}

    # 1) hold to SYSTEM exit (the validated dynamic exit) -> bid
    si = min(system_exit_idx, len(path) - 1)
    res["hold_system"] = pnl(path[si]["bid"])
    # 2) hold to EXPIRY (no management) -> last day bid
    res["hold_expiry"] = pnl(path[-1]["bid"])
    # 3) time stop @5 days -> bid
    res["time_5d"] = pnl(path[min(5, len(path) - 1)]["bid"])

    # barrier policies: walk forward, first touch wins
    def barrier(tp_pct, stop_pct, trail_pct):
        peak = entry_ask
        for r in path[1:]:
            peak = max(peak, r["high"])
            tp = entry_ask * (1 + tp_pct / 100.0) if tp_pct else None
            sl = entry_ask * (1 - stop_pct / 100.0) if stop_pct else None
            tr = peak * (1 - trail_pct / 100.0) if trail_pct else None
            # within a day, check stop/trail (low) and TP (high); assume worst-first (stop) is
            # conservative only if both hit same day -> take the LOSS side first (honest).
            if sl is not None and r["low"] <= sl:
                return pnl(sl)
            if tr is not None and r["low"] <= tr and tr > (sl or -1):
                return pnl(tr)
            if tp is not None and r["high"] >= tp:
                return pnl(tp)
        return pnl(path[-1]["bid"])     # never triggered -> expiry bid
    res["tp50_stop50"] = barrier(50, 50, None)
    res["tp100_stop50"] = barrier(100, 50, None)
    res["trail_30"] = barrier(None, None, 30)
    res["trail_50"] = barrier(None, None, 50)
    res["tp200_trail40"] = barrier(200, None, 40)   # let it run, lock with a wide trail
    return res


def agg(pnls):
    p = np.array(pnls, float)
    if p.size < 5:
        return None
    bm = np.array([p[RNG.integers(0, p.size, p.size)].mean() for _ in range(3000)])
    eq = np.cumsum(np.sort(p)[::-1])  # not a real DD; report path-agnostic dispersion instead
    return {"n": int(p.size),
            "expectancy_pct": round(float(p.mean()), 1),
            "exp_ci95": [round(float(np.percentile(bm, 2.5)), 1), round(float(np.percentile(bm, 97.5)), 1)],
            "median_pct": round(float(np.median(p)), 1),
            "win_rate": round(float((p > 0).mean()), 3),
            "p75_pct": round(float(np.percentile(p, 75)), 1),
            "frac_gt_100pct": round(float((p > 100).mean()), 3),
            "max_pct": round(float(p.max()), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--otm", type=float, default=4.0)
    ap.add_argument("--dte", type=int, default=21)
    ap.add_argument("--min-mig", type=int, default=1)
    ap.add_argument("--max-mig", type=int, default=99)
    a = ap.parse_args()
    df = pd.read_csv(ENTRIES)
    df = df[(df["n_migrations"] >= a.min_mig) & (df["n_migrations"] <= a.max_mig)]
    print(f"[exit-opt] {len(df)} entries, OTM +{a.otm}%, DTE~{a.dte}, "
          f"window {df['entry_day'].min()}..{df['entry_day'].max()}")

    by_policy, skips = {}, 0
    for _, r in df.iterrows():
        edate = to_yyyymmdd(r["entry_day"]); xdate = to_yyyymmdd(r["exit_day"])
        exps = expirations(r["ticker"])
        if not exps:
            skips += 1; continue
        exp, _ = pick_exp(exps, add_cal_days(edate, a.dte))
        if exp is None:
            skips += 1; continue
        ks = strikes(r["ticker"], exp)
        if not ks:
            skips += 1; continue
        strike = min(ks, key=lambda k: abs(k - float(r["entry_spot"]) * (1 + a.otm / 100.0)))
        end = min(exp, add_cal_days(edate, 45))
        path = eod_path(r["ticker"], exp, strike, "C", edate, end)
        if len(path) < 3 or path[0]["ask"] <= 0:
            skips += 1; continue
        # system exit index = days_held from the CSV (the validated dynamic exit), clamped
        sysi = int(min(max(r["days_held"], 1), len(path) - 1))
        res = simulate(path, path[0]["ask"], sysi)
        for pol, v in res.items():
            by_policy.setdefault(pol, []).append(v)

    rows = []
    for pol, pnls in by_policy.items():
        s = agg(pnls)
        if s:
            rows.append({"policy": pol, **s})
    rows.sort(key=lambda r: -r["expectancy_pct"])
    out = {"config": {"otm_pct": a.otm, "dte": a.dte, "mig": [a.min_mig, a.max_mig]},
           "n_entries": len(df), "skips": skips, "policies": rows}
    op = ROOT / "research" / "results" / f"exit_policy_otm{int(a.otm)}_dte{a.dte}_mig{a.min_mig}-{a.max_mig}.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{'POLICY':>14} {'n':>4} {'EXPECT%':>8} {'CI95':>16} {'med%':>6} {'WR':>5} "
          f"{'P75%':>6} {'>100%':>6} {'max%':>7}")
    for r in rows:
        print(f"{r['policy']:>14} {r['n']:>4} {r['expectancy_pct']:>8} {str(r['exp_ci95']):>16} "
              f"{r['median_pct']:>6} {r['win_rate']:>5} {r['p75_pct']:>6} {r['frac_gt_100pct']:>6} {r['max_pct']:>7}")
    print(f"\nskips: {skips}  ->  {op}")


if __name__ == "__main__":
    main()
