"""Day-of-week swing rhythm — Discord friend's claim. Direction-A on Databento.

He trades: "buy Tuesday, sell Wednesday; buy Thursday, sell Friday; and play
Tuesday/Thursday lows for a bounce (ride 0DTE)." Three checkable rules:

  R1  Close-to-close return grouped by ENTRY weekday.
        buy-Tue-close -> sell-next-close  == the return that lands on Wednesday.
        buy-Thu-close -> sell-next-close  == the return that lands on Friday.
      (next SESSION, holiday-safe). Null = 0. Flag Tue-entry and Thu-entry.
  R2  Intraday "low then bounce": per day, low_to_close = (close-low)/low and
      range_pos = (close-low)/(high-low) [0=closed on low, 1=on high]. Do Tue &
      Thu bounce off their low into the close MORE than Mon/Wed/Fri?
  R3  "Tue/Thu lows are entries": open_to_low depth = (low-open)/open (how far it
      dips from the open) paired with the subsequent low->close bounce — is the
      dip-then-recover bigger on Tue/Thu?

Inference: bootstrap over the sample (per weekday) for R1; Tue/Thu-vs-rest
difference bootstrap for R2/R3. Small n per weekday (~n_days/5) -> wide CIs,
reported honestly. Multiple weekdays tested -> Holm note. Mirror on QQQ.
Out -> data/day_of_week_results.json
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
WD = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}


def daily(ticker):
    df = DB.load_ohlcv(ticker, "1min")
    rows = []
    for d, g in df.groupby("date"):
        g = g.sort_values("t")
        if len(g) < 60:
            continue
        rows.append({"date": pd.Timestamp(d), "open": float(g["close"].iloc[0]),
                     "high": float(g["high"].max()), "low": float(g["low"].min()),
                     "close": float(g["close"].iloc[-1])})
    da = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    da["wd"] = da["date"].dt.weekday
    da["cc_ret"] = da["close"].pct_change()           # close_D / close_{D-1} - 1
    da["entry_wd"] = da["wd"].shift(1)                  # weekday of the prior close
    da["low_to_close"] = (da["close"] - da["low"]) / da["low"]
    rng = (da["high"] - da["low"]).replace(0, np.nan)
    da["range_pos"] = (da["close"] - da["low"]) / rng
    da["open_to_low"] = (da["low"] - da["open"]) / da["open"]
    return da


def _mean_ci(x):
    x = np.asarray(pd.Series(x).dropna(), float)
    if len(x) < 5:
        return None, None, len(x)
    bs = [RNG.choice(x, size=len(x), replace=True).mean() for _ in range(N_BOOT)]
    return (round(float(x.mean()), 5),
            [round(float(np.percentile(bs, 2.5)), 5),
             round(float(np.percentile(bs, 97.5)), 5)], len(x))


def _diff_ci(a, b):
    """Tue/Thu (a) minus rest (b), bootstrap diff of means."""
    a = np.asarray(pd.Series(a).dropna(), float); b = np.asarray(pd.Series(b).dropna(), float)
    obs = float(a.mean() - b.mean())
    bs = [RNG.choice(a, len(a), True).mean() - RNG.choice(b, len(b), True).mean()
          for _ in range(N_BOOT)]
    return round(obs, 5), [round(float(np.percentile(bs, 2.5)), 5),
                           round(float(np.percentile(bs, 97.5)), 5)]


def _r1_table(cc, entry_wd):
    """close-to-close mean + bootstrap CI + p, by entry weekday, with Holm."""
    res, pvals = {}, []
    for wd, name in WD.items():
        x = np.asarray(pd.Series(cc[entry_wd == wd]).dropna(), float)
        if len(x) < 10:
            res[name] = {"n": int(len(x)), "note": "too few"}; continue
        bs = np.array([RNG.choice(x, len(x), True).mean() for _ in range(N_BOOT)])
        ci = [round(float(np.percentile(bs, 2.5)), 5),
              round(float(np.percentile(bs, 97.5)), 5)]
        p = float(2 * min((bs <= 0).mean(), (bs >= 0).mean()))
        res[name] = {"mean_ret": round(float(x.mean()), 5), "ci95": ci,
                     "n": int(len(x)), "p": round(p, 4),
                     "verdict": "EDGE" if (ci[0] > 0 or ci[1] < 0) else "NULL"}
        pvals.append((name, p))
    holm = {}
    for rank, (nm, p) in enumerate(sorted(pvals, key=lambda kv: kv[1])):
        holm[nm] = round(min(1.0, p * (len(pvals) - rank)), 4)
    return res, holm


def r1_long(ticker):
    """POWERED R1: close-to-close by entry weekday on 30+ yrs of daily data
    (yfinance), full-history + last-5yr (day-of-week effects are regime-dependent).
    Best-effort: returns None if offline."""
    cache = Path(f"data/daily_long_{ticker}.parquet")
    try:
        if cache.exists():
            d = pd.read_parquet(cache)
        else:
            import yfinance as yf
            d = yf.download(ticker, start="1993-01-01", auto_adjust=True,
                            progress=False)
            if d is None or d.empty:
                return None
            d = d.reset_index()
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [c[0] for c in d.columns]
            d = d[["Date", "Close"]].rename(columns={"Date": "date", "Close": "close"})
            d.to_parquet(cache, index=False)
        d["date"] = pd.to_datetime(d["date"])
        d = d.sort_values("date").reset_index(drop=True)
        d["wd"] = d["date"].dt.weekday
        d["cc"] = d["close"].pct_change()
        d["entry_wd"] = d["wd"].shift(1)
        full_res, full_holm = _r1_table(d["cc"].to_numpy(), d["entry_wd"].to_numpy())
        recent = d[d["date"] >= (d["date"].max() - pd.Timedelta(days=365 * 5))]
        rec_res, rec_holm = _r1_table(recent["cc"].to_numpy(), recent["entry_wd"].to_numpy())
        return {
            "source": f"yfinance {ticker} daily",
            "full": {"range": [str(d['date'].min().date()), str(d['date'].max().date())],
                     "n_days": int(len(d)), "by_entry_weekday": full_res, "holm_p": full_holm},
            "last_5yr": {"n_days": int(len(recent)), "by_entry_weekday": rec_res,
                         "holm_p": rec_holm},
        }
    except Exception as e:
        return {"error": repr(e)[:160]}


def analyze(ticker):
    da = daily(ticker)
    # R1: close-to-close return by entry weekday
    r1 = {}
    pvals = []
    for wd, name in WD.items():
        m, ci, n = _mean_ci(da.loc[da["entry_wd"] == wd, "cc_ret"])
        if m is None:
            r1[name] = {"n": n, "note": "too few"}; continue
        # two-sided bootstrap p that mean==0
        x = np.asarray(da.loc[da["entry_wd"] == wd, "cc_ret"].dropna(), float)
        bs = np.array([RNG.choice(x, len(x), True).mean() for _ in range(N_BOOT)])
        p = float(2 * min((bs <= 0).mean(), (bs >= 0).mean()))
        r1[name] = {"mean_ret": m, "ci95": ci, "n": n, "p": round(p, 4),
                    "verdict": "EDGE" if (ci[0] > 0 or ci[1] < 0) else "NULL"}
        pvals.append((name, p))
    holm = {}
    for rank, (nm, p) in enumerate(sorted(pvals, key=lambda kv: kv[1])):
        holm[nm] = round(min(1.0, p * (len(pvals) - rank)), 4)
    # R2/R3: Tue&Thu vs rest
    tt = da["wd"].isin([1, 3])
    out = {
        "n_days": int(len(da)),
        "R1_LONG_powered_30yr": r1_long(ticker),
        "R1_databento_6mo_by_entry_weekday": r1,
        "R1_databento_holm_p": holm,
        "R1_key": "Tue-entry == buy-Tue/sell-Wed ; Thu-entry == buy-Thu/sell-Fri",
        "R2_low_to_close_bounce": {
            "tue_thu_mean": round(float(da.loc[tt, "low_to_close"].mean()), 5),
            "rest_mean": round(float(da.loc[~tt, "low_to_close"].mean()), 5),
            "diff_tt_minus_rest": _diff_ci(da.loc[tt, "low_to_close"],
                                           da.loc[~tt, "low_to_close"]),
        },
        "R2_range_position_close": {
            "tue_thu_mean": round(float(da.loc[tt, "range_pos"].mean()), 3),
            "rest_mean": round(float(da.loc[~tt, "range_pos"].mean()), 3),
            "diff_tt_minus_rest": _diff_ci(da.loc[tt, "range_pos"],
                                           da.loc[~tt, "range_pos"]),
            "note": "1.0 = closed on the high (full bounce), 0.0 = closed on the low",
        },
        "R3_dip_depth_from_open": {
            "tue_thu_mean": round(float(da.loc[tt, "open_to_low"].mean()), 5),
            "rest_mean": round(float(da.loc[~tt, "open_to_low"].mean()), 5),
            "note": "more negative = deeper dip below the open before any bounce",
        },
    }
    return out


def run():
    out = {"n_boot": N_BOOT, "window": "databento SPY/QQQ cache"}
    for tk in ("SPY", "QQQ"):
        out[tk] = analyze(tk)
    print(json.dumps(out, indent=2))
    Path("data/day_of_week_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
