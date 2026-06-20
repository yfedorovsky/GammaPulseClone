"""Opening-drive 0DTE with TAKE-PROFIT / STOP / TIME-STOP — extensive sweep.

Test #1 showed: held-to-close, the drive 0DTE long is a lottery (median -77%),
BUT the best-possible-exit (MFE) was +33-42% median on ~60% of days — the move
is real, holding kills it. This realizes the MFE with mechanical exit rules,
backtested minute-by-minute on the option's actual NBBO path (buy entry ASK,
sell at BID when a rule triggers). No lookahead.

Sweep: entry {09:35,09:45,10:00} x TP {25,50,75,100,150}% x STOP {30,50,70,none}%
x TIME-STOP {120,240,close}. SPY+QQQ. Direction = sign(spot[entry]-open), ATM 0DTE.

OVERFIT GUARD (the point of "extensive"): split days into TRAIN (first ~half) and
TEST (last ~half). Sweep+rank on TRAIN; report the top combos' OUT-OF-SAMPLE TEST
performance + full-sample. A combo that only shines in-sample is overfit noise.
Also a momentum filter: require |drive move| >= MOVE_MIN.

Out -> data/drive_0dte_tp_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB
import opt_path as OPATH

ENTRIES = ["09:35", "09:45", "10:00"]
TPS = [0.25, 0.50, 0.75, 1.00, 1.50]
STOPS = [0.30, 0.50, 0.70, 1.00]      # 1.00 == effectively no stop (option to 0)
TIME_STOPS = [120, 240, 9999]          # minutes after entry; 9999 = close
MOVE_MIN = 0.0                         # momentum filter (0 = take all drives)
RNG = np.random.default_rng(20260620)


def spot_at(day, hhmm):
    s = day[day["t"].dt.strftime("%H:%M") >= hhmm]
    return float(s["close"].iloc[0]) if len(s) else None


def simulate(entry_ask, mins, bids, tp, stop, time_stop):
    """Walk the 1-min bid path. Exit at first bid >= ask*(1+tp) [TP], or
    bid <= ask*(1-stop) [STOP], or at time_stop minute, else last bid. Sell at bid."""
    tp_px = entry_ask * (1 + tp); stop_px = entry_ask * (1 - stop)
    last = bids[-1]
    for mn, b in zip(mins, bids):
        if mn > time_stop:
            break
        if b >= tp_px:
            return (b - entry_ask) / entry_ask
        if b <= stop_px:
            return (b - entry_ask) / entry_ask
        last = b
    return (last - entry_ask) / entry_ask


def build_days(ticker, entry):
    """For each day: entry_ask, bid path, drive move%. Cached fetch."""
    d = DB.load_ohlcv(ticker, "5min")
    recs = []
    for dt, day in d.groupby("date"):
        day = day.sort_values("t")
        if len(day) < 50:
            continue
        op = float(day["open"].iloc[0]); se = spot_at(day, entry)
        if se is None:
            continue
        move = (se - op) / op
        right = "C" if move > 0 else "P"; strike = round(se); ds = str(dt)
        path = OPATH.get_path(ticker, ds, strike, right, f"{entry}:00.000")
        if not path:
            continue
        recs.append({"date": ds, "move": move, "entry_ask": path["entry_ask"],
                     "mins": path["mins"], "bids": path["bids"]})
    OPATH.flush()
    return recs


def sweep(recs):
    """All combos -> per-combo pnl array (one per day)."""
    grid = {}
    for tp in TPS:
        for stop in STOPS:
            for ts in TIME_STOPS:
                key = f"tp{int(tp*100)}_st{int(stop*100)}_ts{ts}"
                pnl = [simulate(r["entry_ask"], r["mins"], r["bids"], tp, stop, ts)
                       for r in recs if abs(r["move"]) >= MOVE_MIN]
                grid[key] = np.array(pnl)
    return grid


def stat(p):
    if len(p) < 15:
        return None
    boot = np.array([p[RNG.integers(0, len(p), len(p))].mean() for _ in range(2000)])
    return {"n": len(p), "mean": round(float(p.mean()), 4),
            "median": round(float(np.median(p)), 4),
            "win": round(float((p > 0).mean()), 3),
            "ci95": [round(float(np.percentile(boot, 2.5)), 4),
                     round(float(np.percentile(boot, 97.5)), 4)],
            "sharpe_day": round(float(p.mean() / (p.std() + 1e-9)), 3)}


def analyze(ticker, entry):
    recs = build_days(ticker, entry)
    if len(recs) < 40:
        return {"n": len(recs), "note": "too few"}
    cut = len(recs) // 2
    train, test = recs[:cut], recs[cut:]
    g_tr, g_te, g_all = sweep(train), sweep(test), sweep(recs)
    # rank combos by TRAIN mean
    ranked = sorted(g_tr.keys(), key=lambda k: -g_tr[k].mean())
    top = []
    for k in ranked[:6]:
        top.append({"combo": k, "train": stat(g_tr[k]), "test": stat(g_te[k]),
                    "full": stat(g_all[k])})
    # baseline: hold to close, no tp/stop
    base = stat(g_all["tp150_st100_ts9999"])
    return {"n_days": len(recs), "entry": entry,
            "hold_to_close_baseline": base,
            "top6_by_train_mean": top}


def run():
    out = {"strategy": "opening-drive 0DTE long + TP/stop/time-stop, 1-min path, train/test split",
           "sweep": {"entries": ENTRIES, "tp": TPS, "stop": STOPS, "time_stops": TIME_STOPS}}
    for tk in ("SPY", "QQQ"):
        out[tk] = {}
        for entry in ENTRIES:
            out[tk][entry] = analyze(tk, entry)
            OPATH.flush()
    print(json.dumps(out, indent=2))
    Path("data/drive_0dte_tp_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
