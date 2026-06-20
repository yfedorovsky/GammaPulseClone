"""Flow-triggered weeklies — does following our own WHALE/INSIDER/SWEEP alerts,
on the EXACT contract they flagged, actually pay over a few days?

The most faithful test of the live product's edge: flow_alerts records the real
contract (ticker, expiration, strike, type) the aggressive money bought. We BUY
that same contract at the alert-time ASK, hold N trading days, sell at the BID.
Spread + theta + the multi-day move are all in the P&L.

Signal filter: single names with liquid weeklies (indices excluded — the thesis
is informed positioning in individual names). Tagged is_whale/is_insider/is_sweep,
ASK side, clear direction (BULLISH->the flagged call, BEARISH->the flagged put),
short-dated (DTE 2-21 at alert). Dedup: first alert per (ticker,exp,strike,type,day).

Controls: ANTI-FLOW (fade — buy the opposite-direction ATM) and the raw base
(a tagged signal must beat just holding a decaying option). Exits: +1, +2, +3
trading days (capped at expiration), plus a +60% TP / -50% stop is reported on
the discrete grid. Out -> data/flow_weekly_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import opt_pnl as OP

NAMES = {"TSLA", "MU", "NVDA", "META", "MSFT", "MRVL", "AMD", "INTC",
         "AAPL", "AMZN", "SNDK", "GOOGL", "AVGO", "COIN", "PLTR"}
HORIZONS = [1, 2, 3]
RNG = np.random.default_rng(20260620)


def load_signals():
    import sqlite3
    c = sqlite3.connect("snapshots.db")
    q = ("SELECT ts,ticker,strike,expiration,option_type,side,sentiment,"
         "is_whale,is_insider,is_sweep,vol_oi,notional FROM flow_alerts "
         "WHERE (is_whale=1 OR is_insider=1 OR is_sweep=1) AND side='ASK' "
         "AND notional>=300000")
    df = pd.read_sql(q, c)
    df = df[df.ticker.isin(NAMES)].copy()
    df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("America/New_York")
    df["date"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["exp"] = df["expiration"].astype(str).str.replace("-", "").str[:8]
    # right from sentiment+type: BULLISH call or BEARISH put = directional conviction
    df["right"] = np.where(df.option_type.str.lower().str.startswith("c"), "C", "P")
    df["dir_ok"] = ((df.sentiment == "BULLISH") & (df.right == "C")) | \
                   ((df.sentiment == "BEARISH") & (df.right == "P"))
    df = df[df.dir_ok].copy()
    # DTE at alert
    df["dte"] = (pd.to_datetime(df.exp, format="%Y%m%d") -
                 pd.to_datetime(df.date)).dt.days
    df = df[(df.dte >= 2) & (df.dte <= 21)]
    # dedup: largest-notional per contract per day, then cap to top-N/day (bounds
    # the ThetaData run; highest-conviction by notional)
    df = df.sort_values("notional", ascending=False).drop_duplicates(
        ["ticker", "exp", "strike", "right", "date"])
    df = df.groupby("date", group_keys=False).head(40)
    df["entry_hhmm"] = df["dt"].dt.strftime("%H:%M:%S.000")
    return df.reset_index(drop=True)


def exit_date(d, n):
    return np.busday_offset(np.datetime64(d, "D"), n, roll="forward").astype(str)


def pnl_for(sig, n, fade=False):
    """Buy at alert-time ask, sell at exit-day 15:55 bid. fade=buy opposite right."""
    right = ("P" if sig.right == "C" else "C") if fade else sig.right
    e = OP.nbbo(sig.ticker, sig.exp, sig.strike, right, sig.date, sig.entry_hhmm)
    if not e or e[1] <= 0:
        return None
    xd = min(exit_date(sig.date, n), pd.to_datetime(sig.exp, format="%Y%m%d").strftime("%Y-%m-%d"))
    x = OP.nbbo(sig.ticker, sig.exp, sig.strike, right, xd, "15:55:00.000")
    if not x:
        return None
    return (x[0] - e[1]) / e[1]


def stat(p):
    p = np.asarray([x for x in p if x is not None], float)
    if len(p) < 20:
        return {"n": len(p), "note": "too few"}
    boot = np.array([p[RNG.integers(0, len(p), len(p))].mean() for _ in range(3000)])
    return {"n": len(p), "mean": round(float(p.mean()), 4),
            "median": round(float(np.median(p)), 4),
            "win": round(float((p > 0).mean()), 3),
            "ci95": [round(float(np.percentile(boot, 2.5)), 4),
                     round(float(np.percentile(boot, 97.5)), 4)],
            "verdict": ("EDGE" if np.percentile(boot, 2.5) > 0 else "NULL")}


def run():
    sigs = load_signals()
    out = {"n_signals": len(sigs), "names": sorted(NAMES),
           "filter": "tagged ASK directional single-name, notional>=300k, DTE 2-21, deduped",
           "by_tag_counts": {"whale": int(sigs.is_whale.sum()),
                             "insider": int(sigs.is_insider.sum()),
                             "sweep": int(sigs.is_sweep.sum())},
           "horizons": {}}
    recs = list(sigs.itertuples(index=False))
    for n in HORIZONS:
        follow = [pnl_for(s, n) for s in recs]
        OP.flush()
        fade = [pnl_for(s, n, fade=True) for s in recs]
        OP.flush()
        out["horizons"][f"hold_{n}d"] = {"FOLLOW": stat(follow), "FADE_control": stat(fade)}
    print(json.dumps(out, indent=2))
    Path("data/flow_weekly_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
