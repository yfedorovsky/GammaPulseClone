"""MAGNET test — ALTERNATE bubble definitions. Challenge the null.

Re-runs the distance-matched-placebo magnet test from data/dex_tape_cache.csv
under variations of the bubble metric, TOP_PCT, DIST band, SPIKE_X, and the
spike requirement. For each variant we report whether the bubble migrates
toward its strike MORE than a distance-matched non-bubble placebo
(one-sided bootstrap p over days; p<0.05 = bubble beats placebo = null overturned).
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"
PLACEBO_TOL = 0.0015

_DF = None
def load():
    global _DF
    if _DF is None:
        _DF = pd.read_csv(CACHE).sort_values(
            ["day_idx", "sec_end", "strike"]).reset_index(drop=True)
    return _DF


def run_variant(metric="gross", top_pct=90, dist_lo=0.002, dist_hi=0.020,
                spike_x=2.0, require_spike=True):
    """metric in {'gross','nflow_abs','dflow_abs'}.
    Returns dict with per-horizon bubble/placebo migration + bootstrap p."""
    df = load()
    # build the magnitude column the bubble ranking uses
    if metric == "gross":
        mag = df["gross"].values.astype(float)
    elif metric == "nflow_abs":
        mag = np.abs(df["nflow"].values.astype(float))
    elif metric == "dflow_abs":
        mag = np.abs(df["dflow"].values.astype(float))
    else:
        raise ValueError(metric)
    df = df.copy()
    df["mag"] = mag

    events = []  # (day, dist, b5,b15,b30, p5,p15,p30)

    for day, dd in df.groupby("day_idx"):
        bsp = dd.groupby("sec_end")["spot"].first().sort_index()
        secs = bsp.index.values.astype(float); spots = bsp.values
        thr = np.percentile(dd["mag"].values, top_pct)
        dd = dd.copy()
        dd["trail"] = dd.groupby("strike")["mag"].transform(
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
            inband = bkt[(bkt["dist"].abs() >= dist_lo) & (bkt["dist"].abs() <= dist_hi)]
            is_big = inband["mag"] >= thr
            if require_spike:
                is_spike = inband["trail"].isna() | (inband["mag"] >= spike_x * inband["trail"])
                bubbles = inband[is_big & is_spike]
            else:
                bubbles = inband[is_big]
            nonbub = inband[inband["mag"] < thr]
            for _, br in bubbles.iterrows():
                K = br["strike"]; d = br["dist"]
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
        return {"n_events": len(events), "note": "too few bubbles — inconclusive"}
    arr = np.array(events, float)
    day = arr[:, 0]

    def boot_diff(b, p, n=3000):
        m = np.isfinite(b) & np.isfinite(p)
        b, p, dd_ = b[m], p[m], day[m]
        diff = b - p
        obs = np.mean(diff)
        uniq = np.unique(dd_); idxs = {u: np.where(dd_ == u)[0] for u in uniq}
        le0 = 0
        for _ in range(n):
            ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
            if np.mean(diff[ii]) <= 0:
                le0 += 1
        return float(obs), float(np.mean(b)), float(np.mean(p)), (le0 + 1) / (n + 1)

    out = {"n_events": len(events), "n_days": int(len(np.unique(day)))}
    min_p = 1.0
    for i, m in enumerate((5, 15, 30)):
        bcol, pcol = 2 + i, 5 + i
        obs, mb, mp, pv = boot_diff(arr[:, bcol], arr[:, pcol])
        out[f"fwd{m}"] = {"bubble_migr": round(mb, 6), "placebo_migr": round(mp, 6),
                          "diff": round(obs, 6), "p": round(pv, 4)}
        min_p = min(min_p, pv)
    out["min_p_across_horizons"] = round(min_p, 4)
    # Holm threshold for the best of 3 horizons = 0.05/3
    out["beats_placebo_holm"] = bool(min_p < 0.05 / 3)
    out["beats_placebo_raw"] = bool(min_p < 0.05)
    return out


VARIANTS = [
    # (label, kwargs)
    ("BASELINE gross/90/0.2-2.0%/spike2.0", dict()),
    # (a) metric = net notional / net delta flow
    ("a_metric_nflow_abs", dict(metric="nflow_abs")),
    ("a_metric_dflow_abs", dict(metric="dflow_abs")),
    # (b) TOP_PCT
    ("b_top80", dict(top_pct=80)),
    ("b_top95", dict(top_pct=95)),
    # (c) DIST bands
    ("c_dist_0.001-0.01", dict(dist_lo=0.001, dist_hi=0.010)),
    ("c_dist_0.005-0.03", dict(dist_lo=0.005, dist_hi=0.030)),
    # (d) SPIKE_X
    ("d_spike1.5", dict(spike_x=1.5)),
    ("d_spike3.0", dict(spike_x=3.0)),
    # (e) drop spike requirement
    ("e_no_spike", dict(require_spike=False)),
]


def main():
    results = {}
    any_overturn = False
    for label, kw in VARIANTS:
        r = run_variant(**kw)
        results[label] = {"kwargs": kw, **r}
        mp = r.get("min_p_across_horizons")
        beats = r.get("beats_placebo_raw")
        if beats:
            any_overturn = True
        print(f"{label:42s} n={r.get('n_events'):>6} "
              f"min_p={mp} raw<.05={beats} holm={r.get('beats_placebo_holm')}")
    results["_any_definition_beats_placebo_raw_p<0.05"] = any_overturn
    with open("data/dex_magnet_alts_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nANY definition beats distance-matched placebo (one-sided raw p<0.05)?",
          any_overturn)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
