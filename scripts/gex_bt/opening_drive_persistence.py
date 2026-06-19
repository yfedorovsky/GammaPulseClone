"""Opening-drive persistence — "direction is set by 10:00 AM" (Alphatica claim).

Direction-A test on Databento SPY/QQQ. Per day:
  open  = first 1-min open at/after 09:30
  m10   = price at 10:00 ET
  m1030 = price at 10:30 ET
  close = last price at/before 16:00
  drive = sign(m10 - open); drive_mag = (m10-open)/open

Hypotheses:
  H1  P(sign(close - open) == drive)        — does the day end on the drive's side?
  H2  P(sign(close - m10)  == drive)        — does the post-10am move CONTINUE the drive
                                              (vs just mean-revert the early move)?
  H3  "no edge after 10:30": compare P(close-side==drive) using the 10:00 mark vs the
      10:30 mark — if direction is truly set by 10:00, adding 30 min shouldn't help.
  Conditioned on drive-magnitude quartile (does a BIG early drive predict better?).

Null = 50% (binomial), plus a day-bootstrap CI. n = trading days. Mirror on QQQ.
Out -> data/opening_drive_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB

N_BOOT = 5000
RNG = np.random.default_rng(20260619)


def _at(day, hhmm):
    """price at/just-after a HH:MM bar within a day's 1-min frame."""
    sub = day[day["t"].dt.strftime("%H:%M") >= hhmm]
    return float(sub["close"].iloc[0]) if len(sub) else np.nan


def per_day(ticker):
    df = DB.load_ohlcv(ticker, "1min")
    rows = []
    for d, g in df.groupby("date"):
        g = g.sort_values("t")
        if len(g) < 60:
            continue
        op = float(g["close"].iloc[0])
        m10, m1030 = _at(g, "10:00"), _at(g, "10:30")
        cl = float(g["close"].iloc[-1])
        if not np.isfinite([op, m10, m1030, cl]).all():
            continue
        drive = np.sign(m10 - op)
        if drive == 0:
            continue
        rows.append({
            "date": d, "drive": drive, "mag": (m10 - op) / op,
            "close_side_open": float(np.sign(cl - op) == drive),
            "close_side_m10": float(np.sign(cl - m10) == drive),
            "drive1030": np.sign(m1030 - op),
            "close_side_1030": float(np.sign(cl - m1030) == np.sign(m1030 - op)),
        })
    return pd.DataFrame(rows)


def _ci(x):
    x = np.asarray(x, float)
    bs = [RNG.choice(x, size=len(x), replace=True).mean() for _ in range(N_BOOT)]
    return round(float(x.mean()), 3), [round(float(np.percentile(bs, 2.5)), 3),
                                       round(float(np.percentile(bs, 97.5)), 3)]


def analyze(ticker):
    df = per_day(ticker)
    n = len(df)
    h1, h1ci = _ci(df["close_side_open"])
    h2, h2ci = _ci(df["close_side_m10"])
    h3, h3ci = _ci(df["close_side_1030"])
    # magnitude conditioning on H1
    df["mq"] = pd.qcut(df["mag"].abs(), 4, labels=False, duplicates="drop")
    byq = [(int(q), round(float(s["close_side_open"].mean()), 3), int(len(s)))
           for q, s in df.groupby("mq")]
    # REGIME ROBUSTNESS: H1 split by drive sign (does it hold for down-drives,
    # or is 73% just the bull-trend regime?)
    up_d = df[df["drive"] > 0]; dn_d = df[df["drive"] < 0]
    h1_up, h1_up_ci = _ci(up_d["close_side_open"]) if len(up_d) else (None, None)
    h1_dn, h1_dn_ci = _ci(dn_d["close_side_open"]) if len(dn_d) else (None, None)
    def verdict(v, ci):
        return "EDGE (CI>0.5)" if ci[0] > 0.5 else ("ANTI (CI<0.5)" if ci[1] < 0.5 else "NULL (spans 0.5)")
    return {
        "n_days": n,
        "H1_close_on_drive_side": {"rate": h1, "ci95": h1ci, "verdict": verdict(h1, h1ci)},
        "H2_post10am_continues_drive": {"rate": h2, "ci95": h2ci, "verdict": verdict(h2, h2ci)},
        "H3_using_1030_mark": {"rate": h3, "ci95": h3ci,
                               "note": "vs H1 (10:00 mark); if ~equal, direction set by 10:00"},
        "H1_by_drive_magnitude_quartile": byq,
        "H1_by_drive_sign": {
            "up_drive": {"rate": h1_up, "ci95": h1_up_ci, "n": int(len(up_d))},
            "down_drive": {"rate": h1_dn, "ci95": h1_dn_ci, "n": int(len(dn_d))},
        },
    }


def run():
    out = {"null": 0.5, "n_boot": N_BOOT}
    for tk in ("SPY", "QQQ"):
        out[tk] = analyze(tk)
    print(json.dumps(out, indent=2))
    Path("data/opening_drive_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
