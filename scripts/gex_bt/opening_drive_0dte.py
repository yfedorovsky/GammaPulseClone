"""Test #1: 0DTE on the opening drive — does the validated underlying signal
(direction ~68% set by 10am, symmetric) actually PAY as a 0DTE option after
theta decay + the bid/ask spread?

Per Databento day (SPY, QQQ): drive = sign(spot[entry] - session open). Buy an
ATM 0DTE CALL (drive up) or PUT (drive down) at the entry time, sell at 15:55.
Realistic fills (buy ask / sell bid) via opt_pnl. Pre-registered primary entry =
10:00 (matches the "direction set by 10am" finding). Honest prior: the post-10am
continuation was NULL on the underlying, so entering at 10:00 may just buy decay
— this tests whether there's anything left after costs.

Controls: (a) RANDOM direction each day (does the drive beat a coin flip?),
(b) ALWAYS-CALL (naive long-the-index). A real edge must beat both.

Out -> data/opening_drive_0dte_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB
import opt_pnl as OP

ENTRY = "10:00"; EXITS = {"noon": "12:00:00.000", "close": "15:55:00.000"}
RNG = np.random.default_rng(20260620)


def spot_at(day, hhmm):
    s = day[day["t"].dt.strftime("%H:%M") >= hhmm]
    return float(s["close"].iloc[0]) if len(s) else None


CHECKPOINTS = ["11:00:00.000", "12:00:00.000", "13:00:00.000",
               "14:00:00.000", "15:55:00.000"]


def run_ticker(ticker, entry=ENTRY):
    d = DB.load_ohlcv(ticker, "5min")
    rows = []
    for dt, day in d.groupby("date"):
        day = day.sort_values("t")
        if len(day) < 50:
            continue
        op = float(day["open"].iloc[0])
        se = spot_at(day, entry)
        if se is None:
            continue
        drive = 1 if se > op else -1
        right = "C" if drive > 0 else "P"
        strike = round(se); ds = str(dt); exp = ds.replace("-", "")
        e = OP.nbbo(ticker, exp, strike, right, ds, f"{entry}:00.000")
        if not e or e[1] <= 0:
            continue
        entry_ask = e[1]
        bids = {}
        for hh in CHECKPOINTS:
            q = OP.nbbo(ticker, exp, strike, right, ds, hh)
            bids[hh] = q[0] if q else None
        if bids["12:00:00.000"] is None or bids["15:55:00.000"] is None:
            continue
        seen = [b for b in bids.values() if b is not None]
        rows.append({"date": ds, "drive": drive,
                     "pnl_noon": (bids["12:00:00.000"] - entry_ask) / entry_ask,
                     "pnl_close": (bids["15:55:00.000"] - entry_ask) / entry_ask,
                     "best_exit": (max(seen) - entry_ask) / entry_ask})
    df = pd.DataFrame(rows)
    OP.flush()
    if len(df) < 20:
        return {"n": len(df), "note": "too few"}

    def stat(col):
        p = df[col].to_numpy()
        boot = np.array([p[RNG.integers(0, len(p), len(p))].mean() for _ in range(2000)])
        return {"mean": round(float(p.mean()), 4), "median": round(float(np.median(p)), 4),
                "win": round(float((p > 0).mean()), 3),
                "ci95": [round(float(np.percentile(boot, 2.5)), 4),
                         round(float(np.percentile(boot, 97.5)), 4)]}
    return {"n_days": len(df), "entry": entry,
            "exit_noon": stat("pnl_noon"), "exit_close": stat("pnl_close"),
            "best_possible_exit_MFE": stat("best_exit"),
            "note": "best_exit is lookahead (max bid seen) — diagnoses timing vs hopeless"}


def run():
    out = {"strategy": "0DTE ATM long in opening-drive direction, buy-ask/sell-bid",
           "primary_entry": ENTRY}
    for tk in ("SPY", "QQQ"):
        out[tk] = {}
        for entry in ("09:45", "10:00"):
            out[tk][entry] = run_ticker(tk, entry)
    OP.flush()
    print(json.dumps(out, indent=2))
    Path("data/opening_drive_0dte_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
