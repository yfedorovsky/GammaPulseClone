"""Flow-triggered LEAPS — does buying LONGER-dated calls on the flow alerts beat
the short-dated version's -9.5%? Isolates THETA from directional edge.

A 270-DTE call held 5 days barely decays, so its P&L ~= delta * the 5-day move.
So this strips theta out and asks: does the flagged single-name flow actually
predict the multi-day direction? If FOLLOW goes positive at long expiries, theta
was the killer (the user's hypothesis). If FOLLOW stays negative theta-free, the
flow doesn't carry direction.

DATA LIMIT (stated honestly): we can only test SHORT holds of long-dated options
(entries old enough to complete a months-long hold predate our flow data). Buying
Jan-2027 LEAPS to hold for months is forward-looking and not backtestable here.

Per signal: at the alert, buy the ATM call (flow's spot -> nearest $5 strike) at
each expiry in EXPIRIES; sell 5 trading days later at the bid (capped <= last data
day). FADE control = the ATM put. Out -> data/leaps_flow_results.json
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
EXPIRIES = ["2026-07-17", "2026-09-18", "2026-12-18", "2027-01-15", "2027-03-19"]
HOLD = 5
LAST_DATA = "2026-06-18"
RNG = np.random.default_rng(20260620)


def load_signals():
    import sqlite3
    c = sqlite3.connect("snapshots.db")
    df = pd.read_sql(
        "SELECT ts,ticker,sentiment,spot,is_whale,is_insider,is_sweep,notional "
        "FROM flow_alerts WHERE (is_whale=1 OR is_insider=1 OR is_sweep=1) "
        "AND side='ASK' AND sentiment='BULLISH' AND notional>=300000", c)
    df = df[df.ticker.isin(NAMES) & (df.spot > 0)].copy()
    df["dt"] = pd.to_datetime(df.ts, unit="s", utc=True).dt.tz_convert("America/New_York")
    df["date"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["entry_hhmm"] = df["dt"].dt.strftime("%H:%M:%S.000")
    # entry must allow a 5-day completed hold within data
    dates_d = np.array(df["date"].tolist(), dtype="datetime64[D]")
    exitd = np.busday_offset(dates_d, HOLD, roll="forward")
    df = df[exitd <= np.datetime64(LAST_DATA)]
    df = df.sort_values("notional", ascending=False).drop_duplicates(["ticker", "date"])
    df = df.groupby("date", group_keys=False).head(30)
    return df.reset_index(drop=True)


def pnl(ticker, exp, strike, right, date, hhmm):
    e = OP.nbbo(ticker, exp.replace("-", ""), strike, right, date, hhmm)
    if not e or e[1] <= 0:
        return None
    xd = str(np.busday_offset(np.datetime64(date, "D"), HOLD, roll="forward"))
    if xd > LAST_DATA:
        xd = LAST_DATA
    x = OP.nbbo(ticker, exp.replace("-", ""), strike, right, xd, "15:55:00.000")
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
            "verdict": ("EDGE" if np.percentile(boot, 2.5) > 0 else
                        ("NEGATIVE" if np.percentile(boot, 97.5) < 0 else "NULL"))}


def run():
    sigs = load_signals()
    recs = list(sigs.itertuples(index=False))
    out = {"n_signals": len(recs), "hold_days": HOLD, "expiries": EXPIRIES,
           "note": "ATM call on flow.spot; theta-isolation (short hold of long-dated)",
           "by_expiry": {}}
    for exp in EXPIRIES:
        dte = (pd.to_datetime(exp) - pd.to_datetime(sigs.date)).dt.days
        follow, fade = [], []
        for s in recs:
            k = round(s.spot / 5) * 5
            follow.append(pnl(s.ticker, exp, k, "C", s.date, s.entry_hhmm))
            fade.append(pnl(s.ticker, exp, k, "P", s.date, s.entry_hhmm))
        OP.flush()
        out["by_expiry"][exp] = {"approx_DTE": int(dte.median()),
                                 "FOLLOW_call": stat(follow), "FADE_put": stat(fade)}
    print(json.dumps(out, indent=2))
    Path("data/leaps_flow_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
