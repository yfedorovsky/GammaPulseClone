"""Seller side: short ATM 0DTE straddle — the variance-risk-premium test.

Test #1's buyer median of -77% is the seller's bread: if 0DTE implied (the
straddle price) systematically overstates the realized intraday move, the SELLER
is paid. This is a VOL bet (direction-agnostic), not the mirror of the directional
buyer. Realistic: SELL at the bid (collect credit), BUY BACK at the ask (pay to
close) -> the seller ALSO pays the spread, so the variance premium must beat
spread + tail losses.

Per day: at entry, ATM strike. Credit = call_bid + put_bid. Walk the 1-min path;
buy back at the ask if straddle cost >= credit*(1+STOP) [stop], else at close.
P&L% = (credit - buyback)/credit. Sweep entry x stop. TRAIN/TEST split (overfit
guard). Tail-aware: report worst-day and the full distribution, not just the mean.

Out -> data/seller_0dte_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB
import opt_path as OPATH

ENTRIES = ["09:45", "10:00", "11:00"]
STOPS = [0.5, 1.0, 2.0, 99.0]    # buy back if cost >= credit*(1+stop); 99 = no stop
RNG = np.random.default_rng(20260620)


def spot_at(day, hhmm):
    s = day[day["t"].dt.strftime("%H:%M") >= hhmm]
    return float(s["close"].iloc[0]) if len(s) else None


def straddle_path(ticker, ds, strike, entry):
    c = OPATH.get_path_ba(ticker, ds, strike, "C", f"{entry}:00.000")
    p = OPATH.get_path_ba(ticker, ds, strike, "P", f"{entry}:00.000")
    if not c or not p:
        return None
    cb = dict(zip(c["mins"], c["bids"])); ca = dict(zip(c["mins"], c["asks"]))
    pb = dict(zip(p["mins"], p["bids"])); pa = dict(zip(p["mins"], p["asks"]))
    mins = sorted(set(cb) & set(pb))
    if len(mins) < 5:
        return None
    bid = [cb[m] + pb[m] for m in mins]     # straddle bid (sell-to-open credit)
    ask = [ca[m] + pa[m] for m in mins]     # straddle ask (buy-to-close cost)
    return {"mins": mins, "bid": bid, "ask": ask}


def sim_sell(sp, stop):
    credit = sp["bid"][0]
    if credit <= 0:
        return None
    cap = credit * (1 + stop)
    for a in sp["ask"][1:]:
        if a >= cap:
            return (credit - a) / credit          # stopped out
    return (credit - sp["ask"][-1]) / credit       # bought back at close


def build(ticker, entry):
    d = DB.load_ohlcv(ticker, "5min")
    recs = []
    for dt, day in d.groupby("date"):
        day = day.sort_values("t")
        if len(day) < 50:
            continue
        se = spot_at(day, entry)
        if se is None:
            continue
        sp = straddle_path(ticker, str(dt), round(se), entry)
        if sp:
            recs.append(sp)
    OPATH.flush()
    return recs


def stat(p):
    p = np.asarray(p, float)
    if len(p) < 15:
        return None
    boot = np.array([p[RNG.integers(0, len(p), len(p))].mean() for _ in range(2000)])
    return {"n": len(p), "mean": round(float(p.mean()), 4),
            "median": round(float(np.median(p)), 4),
            "win": round(float((p > 0).mean()), 3),
            "worst": round(float(p.min()), 3),
            "ci95": [round(float(np.percentile(boot, 2.5)), 4),
                     round(float(np.percentile(boot, 97.5)), 4)],
            "sharpe_day": round(float(p.mean() / (p.std() + 1e-9)), 3)}


def analyze(ticker, entry):
    recs = build(ticker, entry)
    if len(recs) < 40:
        return {"n": len(recs), "note": "too few"}
    cut = len(recs) // 2
    out = {"n_days": len(recs), "entry": entry, "by_stop": {}}
    for stop in STOPS:
        allp = [sim_sell(r, stop) for r in recs]; allp = [x for x in allp if x is not None]
        trp = [sim_sell(r, stop) for r in recs[:cut]]; trp = [x for x in trp if x is not None]
        tep = [sim_sell(r, stop) for r in recs[cut:]]; tep = [x for x in tep if x is not None]
        out["by_stop"][f"stop{int(stop*100)}"] = {
            "full": stat(allp), "train": stat(trp), "test": stat(tep)}
    return out


def run():
    out = {"strategy": "short ATM 0DTE straddle, sell-bid/buyback-ask, stop on cost*(1+x)",
           "entries": ENTRIES, "stops": STOPS}
    for tk in ("SPY", "QQQ"):
        out[tk] = {}
        for entry in ENTRIES:
            out[tk][entry] = analyze(tk, entry)
            OPATH.flush()
    print(json.dumps(out, indent=2))
    Path("data/seller_0dte_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
