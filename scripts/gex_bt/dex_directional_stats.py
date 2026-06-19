"""Directional DEX-flow test — reads data/dex_tape_cache.csv (per-strike), sums to
per-bucket aggregate flow, tests whether 3-min net signed delta/notional flow LEADS
the next 5/15/30-min SPX move. Pre-reg: DEX_INTRADAY_PREREG.md (HF1/HF2/HF3).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"


def perm_corr(x, y, di, n=2000):
    """Within-day PERMUTATION null for corr(x,y) — shuffles x within each day to
    break the flow->return link while preserving day structure. p = P(|perm corr|
    >= |obs|). (Replaces a flawed paired-resample 'bootstrap' that preserved the
    x-y pairing and so centered on obs, not zero — a stability measure, not a null
    test. Red-team audit 2026-06-19.)"""
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dd = x[m], y[m], di[m]
    if len(x) < 100:
        return np.nan, np.nan, 0
    obs = np.corrcoef(x, y)[0, 1]
    uniq = np.unique(dd); idxs = {u: np.where(dd == u)[0] for u in uniq}
    cnt = 0
    for _ in range(n):
        xp = x.copy()
        for u in uniq:
            ii = idxs[u]; xp[ii] = RNG.permutation(x[ii])
        if abs(np.corrcoef(xp, y)[0, 1]) >= abs(obs):
            cnt += 1
    return float(obs), (cnt + 1) / (n + 1), int(len(x))


def placebo_sign(x, y, di, n=500):
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dd = x[m], y[m], di[m]
    if len(x) < 100:
        return np.nan, np.nan
    acc = np.mean(np.sign(x) == np.sign(y))
    null = []
    for _ in range(n):
        xp = np.copy(x)
        for u in np.unique(dd):
            mm = dd == u
            xp[mm] = RNG.permutation(xp[mm])
        null.append(np.mean(np.sign(xp) == np.sign(y)))
    return float(acc), float(np.nanpercentile(null, 97.5))


def run():
    df = pd.read_csv(CACHE)
    g = df.groupby(["day_idx", "sec_end"]).agg(
        spot=("spot", "first"), dflow=("dflow", "sum"), nflow=("nflow", "sum")).reset_index()
    g = g.sort_values(["day_idx", "sec_end"]).reset_index(drop=True)
    di = g["day_idx"].values.astype(int)
    sec = g["sec_end"].values; spot = g["spot"].values

    def dayz(x):
        z = np.full(len(x), np.nan)
        for u in np.unique(di):
            mm = di == u; mu, sd = np.nanmean(x[mm]), np.nanstd(x[mm]) or 1e-9
            z[mm] = (x[mm] - mu) / sd
        return z

    def fwd(mins):
        out = np.full(len(g), np.nan); tgt = mins * 60
        for u in np.unique(di):
            mm = np.where(di == u)[0]; ss = sec[mm]; sp = spot[mm]
            for j, s0 in enumerate(ss):
                c = np.where(ss >= s0 + tgt)[0]
                if len(c):
                    out[mm[j]] = sp[c[0]] / sp[j] - 1
        return out

    dz, nz = dayz(g["dflow"].values), dayz(g["nflow"].values)
    fwds = {m: fwd(m) for m in (5, 15, 30)}
    res = {"n_days": int(len(np.unique(di))), "n_buckets": len(g),
           "window": f"{df.date.min()}..{df.date.max()}"}
    for label, z in (("delta_flow", dz), ("notional_flow", nz)):
        for m in (5, 15, 30):
            c, p, nn = perm_corr(z, fwds[m], di)
            acc, p97 = placebo_sign(z, fwds[m], di)
            res[f"{label}_fwd{m}"] = {"corr": round(c, 4) if c == c else None,
                                      "perm_p": round(p, 4) if p == p else None,
                                      "sign_acc": round(acc, 4) if acc == acc else None,
                                      "placebo_97.5": round(p97, 4) if p97 == p97 else None, "n": nn}
    fam = {k: v["perm_p"] for k, v in res.items() if k[-1].isdigit() and v.get("perm_p") is not None}
    ranked = sorted(fam.items(), key=lambda kv: kv[1]); mm = len(ranked)
    res["holm"] = {k: {"p": pv, "thr": round(0.05 / (mm - i), 4), "pass": bool(pv < 0.05 / (mm - i))}
                   for i, (k, pv) in enumerate(ranked)}
    print("=== DIRECTIONAL DEX-FLOW ===")
    print(json.dumps(res, indent=2))
    Path("data/dex_directional_results.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    run()
