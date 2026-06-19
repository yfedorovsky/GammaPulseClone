"""MAGNET placebo robustness — challenge the single distance-matched placebo control.

Re-runs the magnet test from data/dex_tape_cache.csv with THREE alternate controls:
  (a) MULTI placebo  — average migration over ALL distance-matched non-bubble strikes
                       (same side), not just the single nearest one.
  (b) OPPOSITE side  — placebo on the OPPOSITE side of spot at matched distance.
  (c) RAW / no control — does price migrate toward bubbles at all (absolute toward-rate),
                       ignoring any placebo. Tests vs the 0.5 coin-flip null.

Goal: confirm the single distance-matched control isn't masking a real effect, and that
absolute migration toward bubbles is itself non-magnetic (toward-rate ~ 0.5).
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"
DIST_LO, DIST_HI = 0.002, 0.020
TOP_PCT = 90
SPIKE_X = 2.0
PLACEBO_TOL = 0.0015


def collect():
    df = pd.read_csv(CACHE).sort_values(["day_idx", "sec_end", "strike"]).reset_index(drop=True)
    rows = []  # dict per bubble event
    for day, dd in df.groupby("day_idx"):
        bsp = dd.groupby("sec_end")["spot"].first().sort_index()
        secs = bsp.index.values.astype(float); spots = bsp.values
        thr = np.percentile(dd["gross"].values, TOP_PCT)
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
            if nonbub.empty:
                continue

            def migr(Kx, m):
                sf = fs[m]
                if not np.isfinite(sf):
                    return np.nan
                return (abs(spot_t - Kx) - abs(sf - Kx)) / spot_t

            for _, br in bubbles.iterrows():
                K = br["strike"]; d = br["dist"]; sd = np.sign(d); ad = abs(d)
                # same-side, distance-matched candidates
                same = nonbub[(np.sign(nonbub["dist"]) == sd)
                              & ((nonbub["dist"].abs() - ad).abs() <= PLACEBO_TOL)]
                # opposite-side, distance-matched candidates
                opp = nonbub[(np.sign(nonbub["dist"]) == -sd)
                             & ((nonbub["dist"].abs() - ad).abs() <= PLACEBO_TOL)]
                if same.empty:
                    continue
                # (single) nearest same-side placebo — the original control
                Kp1 = same.iloc[(same["dist"].abs() - ad).abs().argmin()]["strike"]
                rec = {"day": day, "dist": d}
                for m in (5, 15, 30):
                    rec[f"b{m}"] = migr(K, m)                       # bubble
                    rec[f"p1_{m}"] = migr(Kp1, m)                   # single placebo
                    # (a) multi: mean over ALL same-side matched placebos
                    rec[f"pm_{m}"] = np.mean([migr(k, m) for k in same["strike"].values])
                    # (b) opposite-side mean (NaN if none)
                    rec[f"po_{m}"] = (np.mean([migr(k, m) for k in opp["strike"].values])
                                      if not opp.empty else np.nan)
                rows.append(rec)
    return pd.DataFrame(rows)


def boot_p_diff(b, p, day, n=5000):
    """One-sided P(bootstrap mean(b-p) <= 0), day-clustered. Lower p = bubble beats placebo."""
    m = np.isfinite(b) & np.isfinite(p)
    b, p, day = b[m], p[m], day[m]
    diff = b - p
    obs = float(np.mean(diff))
    uniq = np.unique(day); idxs = {u: np.where(day == u)[0] for u in uniq}
    le0 = 0
    for _ in range(n):
        ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
        if np.mean(diff[ii]) <= 0:
            le0 += 1
    return obs, float(np.mean(b)), float(np.mean(p)), (le0 + 1) / (n + 1)


def boot_p_toward(b, day, n=5000):
    """RAW test: P(bootstrap toward-rate <= 0.5), day-clustered. Lower p = genuine magnet pull."""
    m = np.isfinite(b)
    b, day = b[m], day[m]
    tw = (b > 0).astype(float)
    obs = float(np.mean(tw))
    uniq = np.unique(day); idxs = {u: np.where(day == u)[0] for u in uniq}
    le = 0
    for _ in range(n):
        ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
        if np.mean(tw[ii]) <= 0.5:
            le += 1
    return obs, (le + 1) / (n + 1)


def run():
    ev = collect()
    day = ev["day"].values
    out = {"n_events": int(len(ev)), "n_days": int(ev["day"].nunique())}

    for m in (5, 15, 30):
        b = ev[f"b{m}"].values
        res_m = {}
        # (single) original control
        o, mb, mp, p = boot_p_diff(b, ev[f"p1_{m}"].values, day)
        res_m["single_placebo"] = {"bubble_migr": round(mb, 7), "placebo_migr": round(mp, 7),
                                   "b_minus_p": round(o, 7), "p_one_sided": round(p, 4)}
        # (a) multi placebo
        o, mb, mp, p = boot_p_diff(b, ev[f"pm_{m}"].values, day)
        res_m["multi_placebo"] = {"bubble_migr": round(mb, 7), "placebo_migr": round(mp, 7),
                                  "b_minus_p": round(o, 7), "p_one_sided": round(p, 4)}
        # (b) opposite-side placebo
        o, mb, mp, p = boot_p_diff(b, ev[f"po_{m}"].values, day)
        no = int(np.isfinite(ev[f"po_{m}"].values).sum())
        res_m["opposite_placebo"] = {"bubble_migr": round(mb, 7), "placebo_migr": round(mp, 7),
                                     "b_minus_p": round(o, 7), "p_one_sided": round(p, 4),
                                     "n_with_opp": no}
        # (c) RAW absolute toward-rate (no control)
        tr, pr = boot_p_toward(b, day)
        # placebo toward-rates for reference
        tr_p1 = float(np.nanmean(ev[f"p1_{m}"].values > 0))
        res_m["raw_no_control"] = {"bubble_toward_rate": round(tr, 4),
                                   "p_vs_coinflip_one_sided": round(pr, 4),
                                   "single_placebo_toward_rate": round(tr_p1, 4)}
        out[f"fwd{m}"] = res_m

    print("=== MAGNET PLACEBO ROBUSTNESS ===")
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    run()
