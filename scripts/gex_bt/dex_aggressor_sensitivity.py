"""AGGRESSOR-proxy sensitivity / conviction-filter test.

The cache (dex_tape_cache.csv) bakes the aggressor sign at collection time
(trade>=ask -> +1 buy, <=bid -> -1 sell, mid -> 0). We CANNOT re-sign from the
cache. So instead:

(a) Quantify how much of the premium is 'net' (signed) vs 'gross' (all trades).
    If |net|/gross is small, classification noise dominates and the ~-0.05 corr
    is unsurprising regardless of which side a misclassified mid-trade lands on.

(b) Re-run the directional lead test (dflow / nflow z-scored vs fwd 5/15/30-min
    SPX returns) but restrict to buckets whose net is a LARGE fraction of gross
    (high-conviction, cleanly-signed). If a real lead exists it should survive /
    strengthen on the cleaner subset.

Mirrors dex_directional_stats.py exactly for the stats machinery so results are
directly comparable to data/dex_directional_results.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260619)
CACHE = "data/dex_tape_cache.csv"


def boot_corr(x, y, di, n=2000):
    m = np.isfinite(x) & np.isfinite(y)
    x, y, dd = x[m], y[m], di[m]
    if len(x) < 100:
        return np.nan, np.nan, 0
    obs = np.corrcoef(x, y)[0, 1]
    uniq = np.unique(dd)
    idxs = {u: np.where(dd == u)[0] for u in uniq}
    cnt = sum(abs(np.corrcoef(x[ii], y[ii])[0, 1]) >= abs(obs)
              for ii in (np.concatenate([idxs[u] for u in RNG.choice(uniq, len(uniq), replace=True)])
                         for _ in range(n)))
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


def dayz(x, di):
    z = np.full(len(x), np.nan)
    for u in np.unique(di):
        mm = di == u
        mu, sd = np.nanmean(x[mm]), np.nanstd(x[mm]) or 1e-9
        z[mm] = (x[mm] - mu) / sd
    return z


def fwd_returns(g, di, sec, spot, mins):
    out = np.full(len(g), np.nan)
    tgt = mins * 60
    for u in np.unique(di):
        mm = np.where(di == u)[0]
        ss = sec[mm]
        sp = spot[mm]
        for j, s0 in enumerate(ss):
            c = np.where(ss >= s0 + tgt)[0]
            if len(c):
                out[mm[j]] = sp[c[0]] / sp[j] - 1
    return out


def run():
    df = pd.read_csv(CACHE)

    # ---- aggregate to per-(day,bucket): net signed + gross ----
    g = df.groupby(["day_idx", "sec_end"]).agg(
        spot=("spot", "first"),
        dflow=("dflow", "sum"),     # net signed delta flow
        nflow=("nflow", "sum"),     # net signed premium (call-vs-put + buy-vs-sell)
        gross=("gross", "sum"),     # total premium activity (all trades, unsigned)
    ).reset_index()
    g = g.sort_values(["day_idx", "sec_end"]).reset_index(drop=True)

    di = g["day_idx"].values.astype(int)
    sec = g["sec_end"].values
    spot = g["spot"].values

    # =========================================================
    # (a) NET-vs-GROSS premium sensitivity
    # =========================================================
    gross = g["gross"].values
    nflow = g["nflow"].values
    dgross = (df.groupby(["day_idx", "sec_end"])["gross"].sum().values)  # same as gross

    # bucket-level conviction ratio = |net premium| / gross premium
    with np.errstate(divide="ignore", invalid="ignore"):
        conv = np.where(gross > 0, np.abs(nflow) / gross, np.nan)

    # Aggregate net/gross over ALL buckets (premium-weighted) — the headline number
    tot_gross = float(np.nansum(gross))
    tot_abs_net = float(np.nansum(np.abs(nflow)))
    # also a strike-level version (before any cancellation across strikes in a bucket)
    sl_gross = float(df["gross"].sum())
    sl_abs_net = float(df["nflow"].abs().sum())

    sens = {
        "bucket_level": {
            "sum_gross_premium": round(tot_gross, 1),
            "sum_abs_net_premium": round(tot_abs_net, 1),
            "abs_net_over_gross_ratio": round(tot_abs_net / tot_gross, 4),
            "conv_ratio_median": round(float(np.nanmedian(conv)), 4),
            "conv_ratio_mean": round(float(np.nanmean(conv)), 4),
            "conv_ratio_p25": round(float(np.nanpercentile(conv, 25)), 4),
            "conv_ratio_p75": round(float(np.nanpercentile(conv, 75)), 4),
            "conv_ratio_p90": round(float(np.nanpercentile(conv, 90)), 4),
        },
        "strike_level": {
            "sum_gross_premium": round(sl_gross, 1),
            "sum_abs_net_premium": round(sl_abs_net, 1),
            "abs_net_over_gross_ratio": round(sl_abs_net / sl_gross, 4),
        },
        "note": ("net/gross ~= fraction of premium that survives signing. "
                 "Low ratio => most trades cancel (mid-heavy or 2-sided), so "
                 "the sign of any single trade barely moves aggregate net flow; "
                 "classification noise dominates the directional signal."),
    }

    # also: what fraction of strike-level prints landed on mid (sign==0)?
    # We can't see sign directly, but a strike-bucket with gross>0 and nflow==0
    # is fully-mid OR perfectly 2-sided. Report share of zero-net strike rows.
    zero_net_rows = int((df["nflow"] == 0).sum())
    sens["strike_level"]["share_zero_net_rows"] = round(zero_net_rows / len(df), 4)
    sens["strike_level"]["n_strike_rows"] = int(len(df))

    # =========================================================
    # (b) CONVICTION-FILTERED directional lead test
    # =========================================================
    fwds = {m: fwd_returns(g, di, sec, spot, m) for m in (5, 15, 30)}

    # z-scores within day (same as baseline)
    dz_full = dayz(g["dflow"].values, di)
    nz_full = dayz(g["nflow"].values, di)

    out = {
        "sensitivity": sens,
        "baseline_full_sample": {},
        "conviction_filtered": {},
    }

    # baseline (full sample) for direct comparison
    for label, z in (("delta_flow", dz_full), ("notional_flow", nz_full)):
        for m in (5, 15, 30):
            c, p, nn = boot_corr(z, fwds[m], di)
            acc, p97 = placebo_sign(z, fwds[m], di)
            out["baseline_full_sample"][f"{label}_fwd{m}"] = {
                "corr": round(c, 4) if c == c else None,
                "boot_p": round(p, 4) if p == p else None,
                "sign_acc": round(acc, 4) if acc == acc else None,
                "placebo_97.5": round(p97, 4) if p97 == p97 else None,
                "n": nn,
            }

    # conviction thresholds: keep buckets where |net|/gross >= q (cleanly signed).
    # Use within-day-comparable z-scores but mask out low-conviction buckets.
    for qlabel, q in (("top50pct", None), ("top33pct", None), ("top10pct", None),
                      ("ge_0.30", 0.30), ("ge_0.50", 0.50)):
        if q is None:
            # quantile-based threshold on conviction ratio (global)
            pct = {"top50pct": 50, "top33pct": 67, "top10pct": 90}[qlabel]
            thr = np.nanpercentile(conv, pct)
        else:
            thr = q
        keep = conv >= thr
        # re-z-score WITHIN the kept subset per day so scale is comparable
        dvals = np.where(keep, g["dflow"].values, np.nan)
        nvals = np.where(keep, g["nflow"].values, np.nan)
        dz = dayz(dvals, di)
        nz = dayz(nvals, di)
        sub = {"conv_threshold": round(float(thr), 4),
               "n_buckets_kept": int(np.nansum(keep))}
        for label, z in (("delta_flow", dz), ("notional_flow", nz)):
            for m in (5, 15, 30):
                c, p, nn = boot_corr(z, fwds[m], di)
                acc, p97 = placebo_sign(z, fwds[m], di)
                sub[f"{label}_fwd{m}"] = {
                    "corr": round(c, 4) if c == c else None,
                    "boot_p": round(p, 4) if p == p else None,
                    "sign_acc": round(acc, 4) if acc == acc else None,
                    "placebo_97.5": round(p97, 4) if p97 == p97 else None,
                    "n": nn,
                }
        out["conviction_filtered"][qlabel] = sub

    print("=== AGGRESSOR-PROXY SENSITIVITY + CONVICTION FILTER ===")
    print(json.dumps(out, indent=2))
    Path("data/dex_aggressor_sensitivity_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
