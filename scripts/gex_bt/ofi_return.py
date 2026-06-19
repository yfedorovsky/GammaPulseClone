"""Order-Flow Imbalance -> short-horizon return — the clean underlying-tape
sequel to the DEX flow test. Direction-A on Databento SPY/QQQ L1 quotes.

OFI = Cont-Kukanov-Stoikov (2014) from the top-of-book quote stream (computed in
databento_bars.load_ofi). Per 1-min bar we have OFI and the contemporaneous mid
log-return `ret`.

The DEX lesson, applied here:
  - CONTEMPORANEOUS corr(ofi_t, ret_t) should be strongly + (price impact = sanity).
  - PREDICTIVE corr(ofi_t, ret_{t+h}) for h=1,5,15 min: does OFI LEAD price?
    Significance via WITHIN-DAY PERMUTATION null (not paired-resample — that was
    the DEX bug). Holm-corrected across horizons.
  - PARTIAL corr(ofi_t, ret_{t+1} | ret_t): controlling the contemporaneous bar.
    If flow only "chases" the current bar (like DEX), this collapses to ~0.
  - ECONOMIC: next-bar sign-accuracy from OFI sign vs the ~half-spread cost.

Out -> data/ofi_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB

FREQ = "1min"; HORIZONS = (1, 5, 15); N_PERM = 5000
RNG = np.random.default_rng(20260619)


def _z(x):
    x = np.asarray(x, float)
    s = x.std()
    return (x - x.mean()) / s if s > 0 else x * 0.0


def perm_corr(df, xcol, ycol):
    """Pearson corr of x_t vs y, with a within-day permutation null: shuffle x
    inside each day, break any real lead-lag while preserving marginals."""
    x = df[xcol].to_numpy(); y = df[ycol].to_numpy()
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 50:
        return None
    obs = float(np.corrcoef(x, y)[0, 1])
    d = df.loc[mask, "date"].to_numpy()
    null = np.empty(N_PERM)
    idx_by_day = [np.where(d == u)[0] for u in np.unique(d)]
    for i in range(N_PERM):
        xp = x.copy()
        for ix in idx_by_day:
            xp[ix] = RNG.permutation(x[ix])
        null[i] = np.corrcoef(xp, y)[0, 1]
    p = float((np.abs(null) >= abs(obs)).mean())
    return {"corr": round(obs, 4), "perm_p": round(p, 4), "n": int(len(x))}


def partial_next_given_contemp(df):
    """partial corr(ofi_t, ret_{t+1} | ret_t) via residualization."""
    g = df.dropna(subset=["ofi", "ret", "ret_f1"]).copy()
    if len(g) < 100:
        return None
    # residualize ofi and ret_f1 on ret_t
    ret = _z(g["ret"]); ofi = _z(g["ofi"]); f1 = _z(g["ret_f1"])
    b1 = np.polyfit(ret, ofi, 1); ofi_r = ofi - np.polyval(b1, ret)
    b2 = np.polyfit(ret, f1, 1); f1_r = f1 - np.polyval(b2, ret)
    return round(float(np.corrcoef(ofi_r, f1_r)[0, 1]), 4)


def analyze(ticker):
    df = DB.load_ofi(ticker, FREQ).sort_values("t").reset_index(drop=True)
    # forward mid-returns within day
    for h in HORIZONS:
        df[f"ret_f{h}"] = df.groupby("date")["mid_close"].transform(
            lambda s: np.log(s.shift(-h) / s))
    contemp = perm_corr(df.assign(_x=df["ofi"]), "ofi", "ret")
    preds, pvals = {}, []
    for h in HORIZONS:
        r = perm_corr(df, "ofi", f"ret_f{h}")
        preds[f"h{h}"] = r
        if r:
            pvals.append((f"h{h}", r["perm_p"]))
    # Holm across horizons
    holm = {}
    for rank, (name, p) in enumerate(sorted(pvals, key=lambda kv: kv[1])):
        holm[name] = round(min(1.0, p * (len(pvals) - rank)), 4)
    # next-bar sign accuracy from OFI sign (economic)
    g = df.dropna(subset=["ret_f1"])
    sign_acc = float((np.sign(g["ofi"]) == np.sign(g["ret_f1"])).mean())
    return {
        "n_bars": int(len(df)), "n_days": int(df["date"].nunique()),
        "contemporaneous_corr(ofi,ret_t)": contemp,
        "predictive_corr(ofi,ret_t+h)": preds,
        "holm_adjusted_p": holm,
        "partial_corr(ofi,ret_t+1|ret_t)": partial_next_given_contemp(df),
        "next_bar_sign_accuracy_from_ofi": round(sign_acc, 4),
        "verdict_hint": "leads" if any(
            (r and r["perm_p"] < 0.05 and abs(r["corr"]) > 0.03)
            for r in preds.values()) else "coincident/none",
    }


def run():
    out = {"freq": FREQ, "horizons_min": list(HORIZONS), "n_perm": N_PERM,
           "method": "Cont-Kukanov-Stoikov OFI; within-day permutation null; "
                     "partial corr controls contemporaneous bar (DEX lesson)"}
    for tk in ("SPY", "QQQ"):
        out[tk] = analyze(tk)
    print(json.dumps(out, indent=2))
    Path("data/ofi_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
