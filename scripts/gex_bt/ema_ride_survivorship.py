"""EMA 9/21 "ride" = survivorship? — Direction-A test on Databento SPY/QQQ.

Our GLW X-thread asserted publicly that the "EMA ride" look (price skating the
9/21 EMA) is largely SURVIVORSHIP — you only see the rides that worked. Put a
number on it.

Claim under test: when price is in an uptrend "ride" state (close > EMA9 > EMA21),
it continues up more than a distance-matched non-ride bar at the same extension.

Method (5-min bars, EMAs continuous across days):
  - State A (ride): close > ema9 AND ema9 > ema21.
  - Forward outcome: sign of K-bar-ahead return (K=6 = 30 min).
  - DECISIVE control: distance-matched. Bucket ALL bars by extension
    (close-ema21)/ema21; within each bucket compare forward up-rate of ride vs
    non-ride. A ride is already extended, so it must beat same-extension non-rides.
  - Inference: day-clustered bootstrap (2000 draws) on the matched lift.
  - SURVIVORSHIP curve: P(still in ride after k bars | in ride now), k=1..12,
    vs the memoryless null (per-bar stay-prob ^ k). If the empirical survival
    tracks the memoryless null, long rides are just luck-of-the-draw streaks,
    not a persistent regime -> survivorship confirmed.

Mirror-tested on QQQ. Out -> data/ema_ride_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB

FREQ = "5min"; K = 6; N_BOOT = 2000
RNG = np.random.default_rng(20260619)


def ema(s, span):
    return s.ewm(span=span, min_periods=span).mean()


def prep(ticker):
    df = DB.load_ohlcv(ticker, FREQ).sort_values("t").reset_index(drop=True)
    df["e9"] = ema(df["close"], 9)
    df["e21"] = ema(df["close"], 21)
    df = df.dropna(subset=["e9", "e21"]).reset_index(drop=True)
    df["ride"] = (df["close"] > df["e9"]) & (df["e9"] > df["e21"])
    df["ext"] = (df["close"] - df["e21"]) / df["e21"]
    # forward K-bar return, within day (no cross-day leakage)
    df["fwd"] = df.groupby("date")["close"].transform(lambda s: s.shift(-K) / s - 1)
    df["up"] = (df["fwd"] > 0).astype(float)
    return df.dropna(subset=["fwd", "ext"]).reset_index(drop=True)


def matched_lift(sf, edges, kmin=5):
    b = np.digitize(sf["ext"].to_numpy(), edges[1:-1])
    lifts = []
    for qi in range(len(edges) - 1):
        m = b == qi
        r = sf["ride"].to_numpy() & m
        n = (~sf["ride"].to_numpy()) & m
        if r.sum() >= kmin and n.sum() >= kmin:
            lifts.append(sf["up"].to_numpy()[r].mean() - sf["up"].to_numpy()[n].mean())
    return float(np.mean(lifts)) if lifts else None


def survival(df):
    """Empirical P(still ride after k) from ride-state bars vs memoryless null."""
    # per-bar stay prob among ride bars (within-day next bar still ride)
    nxt = df.groupby("date")["ride"].shift(-1)
    stay = df.loc[df["ride"] & nxt.notna(), :]
    p1 = float(nxt[df["ride"] & nxt.notna()].mean())
    out = []
    for k in (1, 2, 3, 6, 9, 12):
        fk = df.groupby("date")["ride"].transform(lambda s: s.shift(-k))
        emp = float(fk[df["ride"] & fk.notna()].mean())
        out.append((k, round(emp, 3), round(p1 ** k, 3)))
    return p1, out


def analyze(ticker):
    df = prep(ticker)
    edges = np.unique(np.quantile(df["ext"], [0, .2, .4, .6, .8, 1.0]))
    point = matched_lift(df, edges)
    days = df["date"].unique()
    by = {d: df[df["date"] == d] for d in days}
    draws = []
    for _ in range(N_BOOT):
        pick = RNG.choice(days, size=len(days), replace=True)
        ml = matched_lift(pd.concat([by[d] for d in pick], ignore_index=True), edges)
        if ml is not None:
            draws.append(ml)
    draws = np.array(draws)
    lo, hi = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    p1, surv = survival(df)
    return {
        "n_bars": int(len(df)), "n_days": int(len(days)),
        "ride_up_rate": round(float(df.loc[df["ride"], "up"].mean()), 3),
        "nonride_up_rate": round(float(df.loc[~df["ride"], "up"].mean()), 3),
        "raw_lift": round(float(df.loc[df["ride"], "up"].mean()
                                 - df.loc[~df["ride"], "up"].mean()), 3),
        "dist_matched_lift": round(point, 3) if point is not None else None,
        "boot_ci95": [round(lo, 3), round(hi, 3)],
        "one_sided_p_le_0": round(float((draws <= 0).mean()), 4),
        "verdict": "CONTINUATION EDGE" if lo > 0 else "SURVIVORSHIP (no matched edge)",
        "per_bar_stay_prob": round(p1, 3),
        "survival_emp_vs_memoryless": [
            {"k": k, "empirical": e, "memoryless_null": m} for k, e, m in surv],
    }


def run():
    out = {"freq": FREQ, "fwd_bars": K}
    for tk in ("SPY", "QQQ"):
        out[tk] = analyze(tk)
    print(json.dumps(out, indent=2))
    Path("data/ema_ride_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
