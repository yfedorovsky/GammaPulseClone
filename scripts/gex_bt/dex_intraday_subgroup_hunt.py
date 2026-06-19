"""HONEST intraday subgroup hunt — does DEX flow LEAD price, or do bubbles ATTRACT,
in ANY subgroup (even if not on average)?

Reads data/dex_tape_cache.csv (per-strike 3-min flow). Two tests, full sample is a
clean NULL for both (see dex_directional_results.json / dex_magnet_results.json):
  (1) DIRECTIONAL: does signed 3-min net delta/notional flow LEAD next-N-min SPX move?
  (2) MAGNET: do sudden large fresh "bubbles" attract price MORE than a distance-matched
      placebo strike?

We split the SAME data three a-priori ways and re-run BOTH tests inside each cell:
  (a) TREND vs RANGE days        — median split on day's |open->close return|
  (b) TIME OF DAY                — open 9:30-11:00 / midday 11:00-15:00 / power 15:00-16:00
  (c) HIGH vs LOW realized vol   — median split on day's std of 3-min returns

Anti-mining discipline:
  * Boundaries fixed a-priori (median splits / clock blocks), NOT tuned to maximize signal.
  * EVERY subgroup that "looks positive" gets its OWN within-subgroup placebo
    (permute flow within (cell, day) — breaks the flow<->outcome link inside the cell)
    AND its own within-day block bootstrap p-value.
  * Multiplicity reported explicitly: K subgroup x test x horizon cells -> expect ~K*alpha
    false positives under the null. One lucky cell of many is the EXPECTATION, not a finding.

Out -> data/dex_intraday_subgroup_results.json
Run: python scripts/gex_bt/dex_intraday_subgroup_hunt.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"

# ---- magnet config (identical to dex_magnet_stats.py) ----
DIST_LO, DIST_HI = 0.002, 0.020
TOP_PCT = 90
SPIKE_X = 2.0
PLACEBO_TOL = 0.0015

# ---- time-of-day blocks (a-priori, ET seconds-from-midnight) ----
OPEN_END = 11 * 3600          # 9:30-11:00
MID_END = 15 * 3600           # 11:00-15:00 ; power = 15:00-16:00+


# ======================================================================
#  shared: build the per-bucket aggregate panel + forward returns
# ======================================================================
def build_bucket_panel(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["day_idx", "sec_end"]).agg(
        date=("date", "first"), spot=("spot", "first"),
        dflow=("dflow", "sum"), nflow=("nflow", "sum")).reset_index()
    g = g.sort_values(["day_idx", "sec_end"]).reset_index(drop=True)
    di = g["day_idx"].values.astype(int)
    sec = g["sec_end"].values.astype(float)
    spot = g["spot"].values

    # day-z each flow within its own day
    def dayz(x):
        z = np.full(len(x), np.nan)
        for u in np.unique(di):
            mm = di == u
            mu, sd = np.nanmean(x[mm]), np.nanstd(x[mm]) or 1e-9
            z[mm] = (x[mm] - mu) / sd
        return z

    g["dz"] = dayz(g["dflow"].values)
    g["nz"] = dayz(g["nflow"].values)

    # forward returns
    for m in (5, 15, 30):
        out = np.full(len(g), np.nan)
        tgt = m * 60
        for u in np.unique(di):
            mm = np.where(di == u)[0]
            ss = sec[mm]; sp = spot[mm]
            for j, s0 in enumerate(ss):
                c = np.where(ss >= s0 + tgt)[0]
                if len(c):
                    out[mm[j]] = sp[c[0]] / sp[j] - 1
        g[f"fwd{m}"] = out

    # day-level tags
    day_tag = {}
    for u, dd in g.groupby("day_idx"):
        dd = dd.sort_values("sec_end")
        sp = dd["spot"].values
        oc = abs(sp[-1] / sp[0] - 1)                       # |open->close|
        rets = sp[1:] / sp[:-1] - 1
        rv = float(np.nanstd(rets))                        # realized vol (3-min)
        day_tag[u] = (oc, rv)
    oc_arr = np.array([day_tag[u][0] for u in g["day_idx"].values])
    rv_arr = np.array([day_tag[u][1] for u in g["day_idx"].values])
    g["day_oc"] = oc_arr
    g["day_rv"] = rv_arr

    # time-of-day block
    tod = np.where(sec < OPEN_END, "open",
            np.where(sec < MID_END, "midday", "power"))
    g["tod"] = tod
    return g


# ======================================================================
#  TEST 1 — directional: corr(flow_z, fwd) + within-day boot + within-day placebo-sign
# ======================================================================
def boot_corr(x, y, di, n=2000):
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dd = x[m], y[m], di[m]
    if len(x) < 80 or len(np.unique(dd)) < 4:
        return np.nan, np.nan, int(len(x))
    obs = np.corrcoef(x, y)[0, 1]
    uniq = np.unique(dd)
    idxs = {u: np.where(dd == u)[0] for u in uniq}
    # two-sided block bootstrap p: how often |boot corr| >= |obs|? -> sampling spread,
    # but we want a null. Use within-day permutation for the null instead (placebo_sign).
    # boot here gives the CI; p = frac of resamples with opposite-or-zero sign coverage.
    cnt = 0
    for _ in range(n):
        ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
        bc = np.corrcoef(x[ii], y[ii])[0, 1]
        if (bc * obs) <= 0:        # boot sample flips sign of the effect
            cnt += 1
    return float(obs), (cnt + 1) / (n + 1), int(len(x))


def placebo_corr(x, y, di, n=500):
    """Within-day permutation null on the correlation magnitude."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dd = x[m], y[m], di[m]
    if len(x) < 80 or len(np.unique(dd)) < 4:
        return np.nan, np.nan, np.nan
    obs = np.corrcoef(x, y)[0, 1]
    uniq = np.unique(dd)
    null = np.empty(n)
    for k in range(n):
        xp = np.copy(x)
        for u in uniq:
            mm = dd == u
            xp[mm] = RNG.permutation(xp[mm])
        null[k] = np.corrcoef(xp, y)[0, 1]
    # two-sided p: fraction of |null| >= |obs|
    p = (np.sum(np.abs(null) >= abs(obs)) + 1) / (n + 1)
    p975 = float(np.nanpercentile(np.abs(null), 97.5))
    return float(obs), float(p), p975


def directional_cell(sub: pd.DataFrame) -> dict:
    di = sub["day_idx"].values.astype(int)
    out = {}
    for label, zc in (("delta", "dz"), ("notional", "nz")):
        for m in (5, 15, 30):
            x = sub[zc].values
            y = sub[f"fwd{m}"].values
            c, bp, nn = boot_corr(x, y, di)
            _obs, pperm, p975 = placebo_corr(x, y, di)
            out[f"{label}_fwd{m}"] = {
                "corr": round(c, 4) if c == c else None,
                "boot_signflip_p": round(bp, 4) if bp == bp else None,
                "placebo_perm_p": round(pperm, 4) if pperm == pperm else None,
                "placebo_abs_97.5": round(p975, 4) if p975 == p975 else None,
                "n": nn,
            }
    return out


# ======================================================================
#  TEST 2 — magnet: bubble-minus-placebo migration (within a cell's buckets)
#  Cell filtering is applied at the (day,sec_end) bucket level BEFORE bubble detection.
# ======================================================================
def magnet_events(df: pd.DataFrame, bucket_keep) -> np.ndarray:
    """bucket_keep: set of (day_idx, sec_end) buckets allowed for THIS cell.
    Bubble detection still uses the full per-day strike tape; we just restrict which
    evaluation buckets (time points) count. Forward spot uses the full day series."""
    events = []
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
            if (day, sec_end) not in bucket_keep:
                continue
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
    return np.array(events, float) if events else np.zeros((0, 8))


def magnet_cell(arr: np.ndarray) -> dict:
    out = {}
    if arr.shape[0] < 50:
        return {"n_events": int(arr.shape[0]), "note": "too few bubbles — inconclusive"}
    day = arr[:, 0]

    def boot_diff(b, p, n=3000):
        m = np.isfinite(b) & np.isfinite(p)
        b, p, dd = b[m], p[m], day[m]
        diff = b - p
        obs = np.mean(diff)
        uniq = np.unique(dd); idxs = {u: np.where(dd == u)[0] for u in uniq}
        le0 = 0
        for _ in range(n):
            ii = np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
            if np.mean(diff[ii]) <= 0:
                le0 += 1
        return float(obs), float(np.mean(b)), float(np.mean(p)), (le0 + 1) / (n + 1)

    out["n_events"] = int(arr.shape[0])
    for i, m in enumerate((5, 15, 30)):
        bcol, pcol = 2 + i, 5 + i
        obs, mb, mp, pp = boot_diff(arr[:, bcol], arr[:, pcol])
        out[f"fwd{m}"] = {
            "bubble_migr": round(mb, 6), "placebo_migr": round(mp, 6),
            "bubble_minus_placebo": round(obs, 6), "boot_p_one_sided": round(pp, 4),
            "bubble_toward_rate": round(float(np.nanmean(arr[:, bcol] > 0)), 3),
            "placebo_toward_rate": round(float(np.nanmean(arr[:, pcol] > 0)), 3)}
    return out


# ======================================================================
#  run
# ======================================================================
def run():
    raw = pd.read_csv(CACHE)
    g = build_bucket_panel(raw)
    print(f"panel: {len(g)} buckets, {g.day_idx.nunique()} days", flush=True)

    # ---- a-priori day-level splits (median over the 32 DAYS, not the buckets) ----
    day_oc = g.groupby("day_idx")["day_oc"].first()
    day_rv = g.groupby("day_idx")["day_rv"].first()
    oc_med = float(day_oc.median())
    rv_med = float(day_rv.median())
    trend_days = set(day_oc[day_oc >= oc_med].index)
    range_days = set(day_oc[day_oc < oc_med].index)
    hivol_days = set(day_rv[day_rv >= rv_med].index)
    lovol_days = set(day_rv[day_rv < rv_med].index)
    print(f"oc_med={oc_med:.5f}  rv_med={rv_med:.6f}", flush=True)
    print(f"trend={len(trend_days)} range={len(range_days)} "
          f"hivol={len(hivol_days)} lovol={len(lovol_days)}", flush=True)

    # define subgroups as boolean masks on the bucket panel
    cells = {
        "FULL": np.ones(len(g), bool),
        "a_TREND_days": g["day_idx"].isin(trend_days).values,
        "a_RANGE_days": g["day_idx"].isin(range_days).values,
        "b_OPEN_0930_1100": (g["tod"] == "open").values,
        "b_MIDDAY_1100_1500": (g["tod"] == "midday").values,
        "b_POWER_1500_1600": (g["tod"] == "power").values,
        "c_HIVOL_days": g["day_idx"].isin(hivol_days).values,
        "c_LOVOL_days": g["day_idx"].isin(lovol_days).values,
    }

    results = {
        "meta": {
            "window": f"{raw.date.min()}..{raw.date.max()}",
            "n_days": int(g.day_idx.nunique()),
            "oc_median": round(oc_med, 6), "rv_median": round(rv_med, 6),
            "tod_blocks": {"open": "9:30-11:00", "midday": "11:00-15:00", "power": "15:00-16:00+"},
            "full_sample_verdict": "both tests NULL on full sample (see dex_directional/magnet_results.json)",
        },
        "directional": {},
        "magnet": {},
    }

    # ----- directional per cell -----
    for nm, mask in cells.items():
        sub = g[mask]
        results["directional"][nm] = directional_cell(sub)
        # quick console line: best |corr| among the 6 horizons and its perm p
        cell = results["directional"][nm]
        flat = [(k, v["corr"], v["placebo_perm_p"]) for k, v in cell.items()
                if v["corr"] is not None]
        if flat:
            bk, bc, bp = max(flat, key=lambda t: abs(t[1]))
            print(f"[DIR] {nm:20s} n={sub.shape[0]:5d} best={bk} corr={bc:+.3f} permp={bp}", flush=True)

    # ----- magnet per cell -----
    # For day-level cells, restrict the day set (keep all that day's buckets).
    # For time-of-day cells, keep only buckets in that clock block.
    bucket_keys = set(zip(g["day_idx"].values.astype(int), g["sec_end"].values.astype(int)))
    raw2 = raw.copy()
    raw2["sec_end"] = raw2["sec_end"].astype(int)
    for nm, mask in cells.items():
        keep = set(zip(g["day_idx"].values[mask].astype(int),
                       g["sec_end"].values[mask].astype(int)))
        arr = magnet_events(raw2, keep)
        results["magnet"][nm] = magnet_cell(arr)
        mc = results["magnet"][nm]
        if "fwd15" in mc:
            f = mc["fwd15"]
            print(f"[MAG] {nm:20s} ev={mc['n_events']:5d} "
                  f"b-p(15m)={f['bubble_minus_placebo']:+.2e} p={f['boot_p_one_sided']}", flush=True)
        else:
            print(f"[MAG] {nm:20s} {mc.get('note')}", flush=True)

    # ----- multiplicity accounting + survivor scan -----
    dir_cells = sum(len([k for k, v in c.items() if v["corr"] is not None])
                    for nm, c in results["directional"].items() if nm != "FULL")
    mag_cells = sum(len([k for k in c if k.startswith("fwd")])
                    for nm, c in results["magnet"].items() if nm != "FULL")
    K = dir_cells + mag_cells
    alpha = 0.05

    # survivors: subgroup cells (excluding FULL) that beat their OWN placebo at alpha
    dir_surv = []
    for nm, c in results["directional"].items():
        if nm == "FULL":
            continue
        for k, v in c.items():
            if v["placebo_perm_p"] is not None and v["placebo_perm_p"] < alpha \
               and v["boot_signflip_p"] is not None and v["boot_signflip_p"] < alpha:
                dir_surv.append({"cell": f"{nm}/{k}", "corr": v["corr"],
                                 "perm_p": v["placebo_perm_p"], "signflip_p": v["boot_signflip_p"],
                                 "n": v["n"]})
    mag_surv = []
    for nm, c in results["magnet"].items():
        if nm == "FULL":
            continue
        for k in [x for x in c if x.startswith("fwd")]:
            v = c[k]
            if v["boot_p_one_sided"] < alpha:   # one-sided: bubble beats placebo
                mag_surv.append({"cell": f"{nm}/{k}", "b_minus_p": v["bubble_minus_placebo"],
                                 "p": v["boot_p_one_sided"], "n_events": c["n_events"]})

    results["multiplicity"] = {
        "n_directional_cells": dir_cells,
        "n_magnet_cells": mag_cells,
        "K_total_subgroup_cells": K,
        "expected_false_positives_at_0.05": round(K * alpha, 2),
        "directional_survivors_beating_own_placebo": dir_surv,
        "magnet_survivors_beating_own_placebo": mag_surv,
        "n_survivors": len(dir_surv) + len(mag_surv),
        "interpretation": (
            f"{K} subgroup cells tested -> expect ~{round(K*alpha,1)} false positives at 0.05 "
            f"under the null. {len(dir_surv)+len(mag_surv)} survivor(s) found. A survivor count "
            f"<= expected_false_positives is fully consistent with NO real subgroup edge."),
    }

    Path("data/dex_intraday_subgroup_results.json").write_text(json.dumps(results, indent=2))
    print("\n=== SURVIVORS (beat own within-subgroup placebo at 0.05) ===")
    print(json.dumps(results["multiplicity"], indent=2))
    print("\nwrote data/dex_intraday_subgroup_results.json")
    return results


if __name__ == "__main__":
    run()
