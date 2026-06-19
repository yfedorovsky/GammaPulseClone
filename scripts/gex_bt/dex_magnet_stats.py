"""MAGNET test — Quant Data's stated claim ("sudden large fresh bubbles attract
price / are magnets for flow"). Reads data/dex_tape_cache.csv. Pre-reg:
DEX_INTRADAY_PREREG.md (MAGNET addendum, HM1).

A "bubble" = a strike-bucket with top-decile GROSS premium flow, away from spot by
0.2-2.0%, that is a SPIKE vs that strike's trailing baseline (sudden/fresh). For
each bubble we ask: did price MIGRATE TOWARD that strike over the next N min — MORE
than a DISTANCE-MATCHED non-bubble strike (the decisive control: nearby strikes
attract price by mere proximity; the bubble must beat a same-distance placebo).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"
DIST_LO, DIST_HI = 0.002, 0.020     # bubble must be 0.2-2.0% from spot
TOP_PCT = 90                        # top-decile gross = "large"
SPIKE_X = 2.0                       # gross >= SPIKE_X * strike's trailing mean = "sudden"
PLACEBO_TOL = 0.0015               # distance-match tolerance for the placebo strike


def run():
    df = pd.read_csv(CACHE).sort_values(["day_idx", "sec_end", "strike"]).reset_index(drop=True)
    out_h = {}
    events = []  # (day, dist, migr5, migr15, migr30, pmigr5, pmigr15, pmigr30)

    for day, dd in df.groupby("day_idx"):
        # per-bucket spot series for forward migration
        bsp = dd.groupby("sec_end")["spot"].first().sort_index()
        secs = bsp.index.values.astype(float); spots = bsp.values
        thr = np.percentile(dd["gross"].values, TOP_PCT)
        # trailing mean gross per strike (for spike/freshness)
        dd = dd.copy()
        dd["trail"] = dd.groupby("strike")["gross"].transform(
            lambda s: s.expanding().mean().shift(1))

        def fwd_spot(s0, tgt):
            c = np.where(secs >= s0 + tgt * 60)[0]
            return spots[c[0]] if len(c) else np.nan

        for sec_end, bkt in dd.groupby("sec_end"):
            spot_t = bkt["spot"].iloc[0]
            fs = {m: fwd_spot(sec_end, m) for m in (5, 15, 30)}
            if not np.isfinite(fs[15]):
                continue
            bkt = bkt.copy()
            bkt["dist"] = (bkt["strike"] - spot_t) / spot_t
            inband = bkt[(bkt["dist"].abs() >= DIST_LO) & (bkt["dist"].abs() <= DIST_HI)]
            bubbles = inband[(inband["gross"] >= thr)
                             & ((inband["trail"].isna()) | (inband["gross"] >= SPIKE_X * inband["trail"]))]
            nonbub = inband[inband["gross"] < thr]
            for _, br in bubbles.iterrows():
                K = br["strike"]; d = br["dist"]
                # distance-matched placebo: same side, |dist| within tol, NOT a bubble
                cand = nonbub[(np.sign(nonbub["dist"]) == np.sign(d))
                              & ((nonbub["dist"].abs() - abs(d)).abs() <= PLACEBO_TOL)]
                if cand.empty:
                    continue
                Kp = cand.iloc[(cand["dist"].abs() - abs(d)).abs().argmin()]["strike"]

                def migr(Kx, m):
                    sf = fs[m]
                    if not np.isfinite(sf):
                        return np.nan
                    return (abs(spot_t - Kx) - abs(sf - Kx)) / spot_t

                events.append((day, d,
                               migr(K, 5), migr(K, 15), migr(K, 30),
                               migr(Kp, 5), migr(Kp, 15), migr(Kp, 30)))

    if len(events) < 50:
        print(json.dumps({"n_events": len(events), "note": "too few bubbles — inconclusive"}))
        return
    arr = np.array(events, float)
    day = arr[:, 0]
    res = {"n_events": len(events), "n_days": int(len(np.unique(day))),
           "window": f"{df.date.min()}..{df.date.max()}"}

    def boot_diff(b, p, n=3000):
        m = np.isfinite(b) & np.isfinite(p)
        b, p, dd = b[m], p[m], day[m]
        diff = b - p
        obs = np.mean(diff)
        uniq = np.unique(dd); idxs = {u: np.where(dd == u)[0] for u in uniq}
        # one-sided: P(bootstrap mean <= 0) — does bubble beat placebo?
        le0 = 0
        for _ in range(n):
            ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
            if np.mean(diff[ii]) <= 0:
                le0 += 1
        return float(obs), float(np.mean(b)), float(np.mean(p)), (le0 + 1) / (n + 1)

    for i, m in enumerate((5, 15, 30)):
        bcol, pcol = 2 + i, 5 + i
        obs, mb, mp, p = boot_diff(arr[:, bcol], arr[:, pcol])
        # toward-rate: fraction migrating toward (migr>0)
        tb = np.nanmean(arr[:, bcol] > 0); tp = np.nanmean(arr[:, pcol] > 0)
        out_h[f"fwd{m}"] = {
            "bubble_migr": round(mb, 6), "placebo_migr": round(mp, 6),
            "bubble_minus_placebo": round(obs, 6), "boot_p_one_sided": round(p, 4),
            "bubble_toward_rate": round(float(tb), 3), "placebo_toward_rate": round(float(tp), 3)}
    res["magnet"] = out_h
    # Holm across horizons
    fam = {k: v["boot_p_one_sided"] for k, v in out_h.items()}
    ranked = sorted(fam.items(), key=lambda kv: kv[1]); mm = len(ranked)
    res["holm"] = {k: {"p": pv, "thr": round(0.05 / (mm - i), 4), "pass": bool(pv < 0.05 / (mm - i))}
                   for i, (k, pv) in enumerate(ranked)}
    print("=== MAGNET TEST (bubble vs distance-matched placebo) ===")
    print(json.dumps(res, indent=2))
    Path("data/dex_magnet_results.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    run()
