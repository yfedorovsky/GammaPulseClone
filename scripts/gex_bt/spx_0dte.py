"""SPX (SPXW) 0DTE — same two tests as SPY/QQQ, on the European cash-settled index.

Different market: tight ATM spreads, cash settlement (no expiry pin/assignment
scramble), THE variance-premium instrument. Spot derived via ATM put-call parity
(S = K + Cmid - Pmid); drive direction taken from SPY's Databento tape (SPY and
SPX move ~identically intraday). 0DTE root = SPXW, $5 strikes near ATM.

Tests (entry 10:00, exit/close 15:55):
  LONG : buy ATM 0DTE in the drive direction, TP/stop/time-stop sweep, TRAIN/TEST.
  SELL : short ATM straddle, sell-bid/buyback-ask, stop sweep, TRAIN/TEST.
Reuses simulate() and sim_sell()/stat() from the SPY/QQQ scripts -> identical math.

Out -> data/spx_0dte_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB
import opt_path as OPATH
import opt_pnl as OP
from drive_0dte_tp import simulate, TPS, STOPS, TIME_STOPS
from seller_0dte import sim_sell, stat, STOPS as SELL_STOPS

ENTRY = "10:00"; ENTRY_HHMM = "10:00:00.000"
RATIO = 10.04          # SPX ~ SPY * 10.04 (refined per-day via parity)
RNG = np.random.default_rng(20260620)


def spx_atm(ds, spy_spot):
    """Derive SPX spot via ATM parity, return nearest-$5 ATM strike (or None)."""
    guess = round(spy_spot * RATIO / 5) * 5
    c = OP.nbbo("SPXW", ds.replace("-", ""), guess, "C", ds, ENTRY_HHMM)
    p = OP.nbbo("SPXW", ds.replace("-", ""), guess, "P", ds, ENTRY_HHMM)
    if not c or not p:
        return None
    spx = guess + (c[0] + c[1]) / 2 - (p[0] + p[1]) / 2
    return round(spx / 5) * 5


def build():
    spy = DB.load_ohlcv("SPY", "5min")
    recs = []
    for dt, day in spy.groupby("date"):
        day = day.sort_values("t")
        if len(day) < 50:
            continue
        op = float(day["open"].iloc[0])
        s = day[day["t"].dt.strftime("%H:%M") >= ENTRY]
        if not len(s):
            continue
        se = float(s["close"].iloc[0]); ds = str(dt)
        drive = "C" if se > op else "P"
        atm = spx_atm(ds, se)
        if atm is None:
            continue
        call = OPATH.get_path_ba("SPXW", ds, atm, "C", ENTRY_HHMM)
        put = OPATH.get_path_ba("SPXW", ds, atm, "P", ENTRY_HHMM)
        if not call or not put:
            continue
        leg = call if drive == "C" else put
        recs.append({"date": ds, "drive": drive, "atm": atm,
                     "long_entry_ask": leg["asks"][0], "long_mins": leg["mins"],
                     "long_bids": leg["bids"], "call": call, "put": put})
    OPATH.flush(); OP.flush()
    return recs


def straddle(r):
    cb = dict(zip(r["call"]["mins"], r["call"]["bids"])); ca = dict(zip(r["call"]["mins"], r["call"]["asks"]))
    pb = dict(zip(r["put"]["mins"], r["put"]["bids"])); pa = dict(zip(r["put"]["mins"], r["put"]["asks"]))
    mins = sorted(set(cb) & set(pb))
    return {"mins": mins, "bid": [cb[m] + pb[m] for m in mins],
            "ask": [ca[m] + pa[m] for m in mins]}


def run():
    recs = build()
    out = {"instrument": "SPXW 0DTE", "entry": ENTRY, "n_days": len(recs),
           "spot_via": "ATM put-call parity; drive from SPY tape"}
    if len(recs) < 40:
        out["note"] = "too few"; print(json.dumps(out, indent=2)); return
    cut = len(recs) // 2
    # LONG: TP/stop sweep, train/test, top by train mean
    def long_sweep(rs):
        g = {}
        for tp in TPS:
            for st in STOPS:
                for ts in TIME_STOPS:
                    g[f"tp{int(tp*100)}_st{int(st*100)}_ts{ts}"] = np.array(
                        [simulate(r["long_entry_ask"], r["long_mins"], r["long_bids"], tp, st, ts) for r in rs])
        return g
    gtr, gall = long_sweep(recs[:cut]), long_sweep(recs)
    gte = long_sweep(recs[cut:])
    top = sorted(gtr.keys(), key=lambda k: -gtr[k].mean())[:5]
    out["LONG_drive"] = {"hold_to_close": stat(gall["tp150_st100_ts9999"]),
                         "top5_by_train": [{"combo": k, "train": stat(gtr[k]),
                                            "test": stat(gte[k]), "full": stat(gall[k])} for k in top]}
    # SELL: straddle stop sweep, train/test
    sp = [straddle(r) for r in recs]
    sell = {}
    for st in SELL_STOPS:
        allp = [sim_sell(s, st) for s in sp]; allp = [x for x in allp if x is not None]
        trp = [sim_sell(s, st) for s in sp[:cut]]; trp = [x for x in trp if x is not None]
        tep = [sim_sell(s, st) for s in sp[cut:]]; tep = [x for x in tep if x is not None]
        sell[f"stop{int(st*100)}"] = {"full": stat(allp), "train": stat(trp), "test": stat(tep)}
    out["SELL_straddle"] = sell
    print(json.dumps(out, indent=2))
    Path("data/spx_0dte_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
