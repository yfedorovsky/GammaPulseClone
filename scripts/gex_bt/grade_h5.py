#!/usr/bin/env python
"""GRADE H5 — Overnight structure drift (Track S, EOD).

Pre-registered under docs/research/GEX_BACKTEST_PREREG.md (Direction A, H5):
  EOD signed distance to the gamma structure (spot vs king, net-gamma sign)
  predicts next-day / multi-day forward return BEYOND the ticker's drift.

Cells (pre-committed, no post-hoc tuning):
  proximity-bucket x horizon
    proximity buckets = the fixed band grid {0.15%, 0.30%, 0.50%} of spot,
      i.e. |dist_king_pct| <= b  (spot near the king — the H5 structure).
    horizons = {1d, 3d}  close-to-close (fwd_ret_1d, fwd_ret_3d).
  => 6 H5 cells (3 bands x 2 horizons). Report ALL of them.

Directional setup (mechanical, the H5 mean-reversion read):
  position = sign(dist_king_pct)   [king above spot -> long toward king;
                                     king below spot -> short toward king].
  signed forward return = position * fwd_ret.
  R unit = signed_ret / band_b      (fixed per-setup risk = band width, per
                                      pre-reg "move / band width").
  Win = signed_ret > 0 (drift toward the king, the hypothesis direction).
  dist_king_pct == 0 (spot exactly at king) -> no signed bet -> dropped.

Grading (the SAME machinery that graded whales — scripts/gex_bt/stats.py):
  n, mean_R, net_R_slippage (haircut applied), base_rate_delta (vs the
  per-ticker UNCONDITIONAL 1d/3d base rate — converted to the SAME R unit,
  same position sign), cpcv_lower, dsr_positive, pbo, regime_robust,
  beats_base_rate.

  passes = TRUE only if the FULL pre-reg bar holds:
    net-slippage cpcv_lower > 0 AND dsr_positive AND pbo < 0.5
    AND regime_robust AND beats_base_rate.

DSR deflation pays for the WHOLE pre-registered matrix (multiplicity):
  H1-H4 intraday = 4 hyp x 3 bands x 3 horizons = 36
  H5 swing       = 3 bands x 2 horizons        =  6
  GLOBAL n_trials = 42.

regime_robust (pre-reg confound #1 — "not carried by one regime / the crash
window"): mean net-R keeps the SAME (positive) sign in BOTH
  (a) RISK-ON vs RISK-OFF  — median split on daily POS-share breadth
      (fraction of universe in POS regime that date; a CONTEMPORANEOUS,
       no-look-ahead risk proxy), AND
  (b) crash-window IN vs OUT — the late-Feb/early-Mar 2026 selloff window
      [2026-02-24 .. 2026-03-06] removed vs the full sample.
  Both sub-splits must keep mean net-R > 0 (the edge survives, not driven by a
  single regime). Degenerate sub-samples (n<10) => not robust.

PBO matrix: the per-setup net-R series is laid out as a (T observations x N
configs) matrix where N = the 6 H5 (band x horizon) variants, aligned on a
common (date, root) index so CSCV compares config rankings IS vs OOS. Cells
with too few aligned observations -> PBO None (treated as N/A, never danger).

READ-ONLY on work.db (file:...?mode=ro&uri=True). Writes NOTHING.
Prints a JSON blob to stdout for the orchestrator.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats  # noqa: E402  (the vendored Fable grading spine)

WORK_DB = r"C:\Dev\GammaPulse\gex_backtest\work.db"

# Pre-fixed band grid (fraction of spot). NO post-hoc tuning.
BANDS = [0.0015, 0.0030, 0.0050]
BAND_LABELS = {0.0015: "0.15%", 0.0030: "0.30%", 0.0050: "0.50%"}
HORIZONS = ["1d", "3d"]
FWD_COL = {"1d": "fwd_ret_1d", "3d": "fwd_ret_3d"}

# Global pre-registered trial count for DSR deflation (multiplicity).
GLOBAL_N_TRIALS = 42  # H1-H4: 4*3*3=36  +  H5: 3*2=6

# Crash window (the explicitly pre-named regime confound).
CRASH_START, CRASH_END = "2026-02-24", "2026-03-06"

# Slippage: spot trades, default 2 bps/side. Risk is denominated in the band
# width (band_b as a fraction), so we pass risk_pct = band_b*100 (percent) so
# the bps haircut converts price-cost -> R-cost honestly (cost grows for the
# tighter bands, exactly as a band-width-denominated R should).


def _connect():
    con = sqlite3.connect(f"file:{WORK_DB}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def load_rows(con):
    """Pull H5 structure rows + the per-ticker base rates."""
    cur = con.cursor()
    rows = cur.execute(
        "SELECT date, root, dist_king_pct, fwd_ret_1d, fwd_ret_3d, regime "
        "FROM gex_struct_eod "
        "WHERE dist_king_pct IS NOT NULL"
    ).fetchall()
    # per-ticker base rate mean (unconditional fwd return), 1d & 3d.
    base = {}
    for tk, hz, mean in cur.execute(
        "SELECT ticker, horizon, mean FROM base_rates WHERE horizon IN ('1d','3d')"
    ):
        base[(tk, hz)] = mean
    # daily POS-share breadth (contemporaneous risk proxy, no look-ahead).
    breadth = {}
    for d, share in cur.execute(
        "SELECT date, SUM(CASE WHEN regime='POS' THEN 1.0 ELSE 0 END)/COUNT(*) "
        "FROM gex_struct_eod GROUP BY date"
    ):
        breadth[d] = share
    return rows, base, breadth


def build_setups(rows, base, breadth, band, horizon):
    """Return list of dicts: one per qualifying setup in this (band,horizon) cell.

    Each carries the signed R (gross), the per-ticker base-rate R (same sign &
    R unit), the date/root key (for PBO alignment), the daily breadth, and the
    crash-window flag.
    """
    fwd_idx = 3 if horizon == "1d" else 4
    out = []
    for date, root, dk, f1, f3, _reg in rows:
        if dk is None:
            continue
        if abs(dk) > band:
            continue
        pos = 0.0
        if dk > 0:
            pos = 1.0      # king above spot -> long toward king
        elif dk < 0:
            pos = -1.0     # king below spot -> short toward king
        else:
            continue       # spot exactly at king -> no directional bet
        fwd = f1 if horizon == "1d" else f3
        if fwd is None:
            continue
        signed = pos * fwd
        R = signed / band                      # fixed per-setup risk = band width
        # per-ticker base rate in the SAME R unit & SAME position sign:
        br_mean = base.get((root, horizon))
        if br_mean is None:
            br_R = 0.0
        else:
            br_R = (pos * br_mean) / band
        out.append({
            "date": date, "root": root, "R": R, "base_R": br_R,
            "risk_pct": band * 100.0,        # band width as percent (slip -> R)
            "breadth": breadth.get(date, np.nan),
            "is_crash": (CRASH_START <= date <= CRASH_END),
        })
    return out


def grade_cell(setups):
    """Compute the full pre-reg metric set for one cell's setups."""
    n = len(setups)
    if n == 0:
        return None
    R = np.array([s["R"] for s in setups], dtype=float)
    base_R = np.array([s["base_R"] for s in setups], dtype=float)
    netR = stats.net_of_slippage(R, setups)   # haircut applied (band-denominated)

    mean_R = float(np.mean(R))
    mean_netR = float(np.mean(netR))

    cpcv_mean, cpcv_lower = stats.cpcv_mean_lower(netR)
    dsr_stat, dsr_pos = stats.dsr(netR, GLOBAL_N_TRIALS)

    # base-rate delta: net-of-slippage edge R vs the per-ticker base-rate R
    # (paired: same rows; we compare the conditioned edge mean against the
    # unconditional drift expressed in the identical R unit & sign).
    br_delta, br_sig = stats.base_rate_delta(netR, base_R)

    return {
        "n": n,
        "mean_R": mean_R,
        "mean_netR": mean_netR,
        "cpcv_mean": float(cpcv_mean),
        "cpcv_lower": float(cpcv_lower),
        "dsr_stat": float(dsr_stat),
        "dsr_positive": bool(dsr_pos),
        "base_rate_delta": float(br_delta),
        "beats_base_rate": bool(br_sig),
        "_netR": netR, "_setups": setups,
    }


def regime_robust(setups, netR):
    """Edge keeps mean net-R > 0 in BOTH risk-on/off AND crash-in/out splits."""
    arr = np.asarray(netR, float)
    breadth = np.array([s["breadth"] for s in setups], float)
    crash = np.array([s["is_crash"] for s in setups], bool)

    # (a) RISK-ON / RISK-OFF: median split on contemporaneous POS-share breadth.
    good = np.isfinite(breadth)
    if good.sum() < 20:
        return False, {"reason": "insufficient breadth coverage"}
    med = np.median(breadth[good])
    on = arr[good & (breadth >= med)]
    off = arr[good & (breadth < med)]
    on_ok = on.size >= 10 and float(on.mean()) > 0
    off_ok = off.size >= 10 and float(off.mean()) > 0

    # (b) CRASH-IN / CRASH-OUT.
    out = arr[~crash]
    inn = arr[crash]
    out_ok = out.size >= 10 and float(out.mean()) > 0
    # crash sub-sample may be tiny; require it not REVERSE the edge if present.
    in_ok = (inn.size < 10) or (float(inn.mean()) > 0)

    robust = on_ok and off_ok and out_ok and in_ok
    detail = {
        "risk_on_mean": (float(on.mean()) if on.size else None), "risk_on_n": int(on.size),
        "risk_off_mean": (float(off.mean()) if off.size else None), "risk_off_n": int(off.size),
        "crash_out_mean": (float(out.mean()) if out.size else None), "crash_out_n": int(out.size),
        "crash_in_mean": (float(inn.mean()) if inn.size else None), "crash_in_n": int(inn.size),
        "split_median_breadth": float(med),
    }
    return bool(robust), detail


def build_pbo_matrix(cell_setups):
    """(T x N) net-R matrix aligned on common (date,root), one col per cell."""
    keys = {}
    for label, setups in cell_setups.items():
        for s, nr in zip(setups["_setups"], setups["_netR"]):
            keys.setdefault((s["date"], s["root"]), {})[label] = float(nr)
    labels = list(cell_setups.keys())
    rows = []
    for k, d in keys.items():
        if all(lb in d for lb in labels):       # only rows present in ALL configs
            rows.append([d[lb] for lb in labels])
    if len(rows) < 4 or len(labels) < 2:
        return None, labels, 0
    M = np.asarray(rows, float)
    return M, labels, M.shape[0]


def main():
    con = _connect()
    rows, base, breadth = load_rows(con)
    con.close()

    cells = {}
    graded = {}
    for band in BANDS:
        for hz in HORIZONS:
            label = f"king<={BAND_LABELS[band]}|{hz}"
            setups = build_setups(rows, base, breadth, band, hz)
            g = grade_cell(setups)
            graded[label] = g
            cells[label] = {"band": BAND_LABELS[band], "horizon": hz,
                            "band_frac": band}

    # PBO across the 6 H5 configs (shared matrix; per-cell PBO = the family PBO
    # — CSCV is a family-level overfit probability, applied to every member).
    pbo_cells = {lb: g for lb, g in graded.items() if g is not None}
    M, labels, T_pbo = build_pbo_matrix(pbo_cells)
    family_pbo = stats.pbo_cscv(M) if M is not None else None

    results = []
    for band in BANDS:
        for hz in HORIZONS:
            label = f"king<={BAND_LABELS[band]}|{hz}"
            g = graded[label]
            meta = cells[label]
            if g is None:
                results.append({
                    "cell": label, "band": meta["band"], "horizon": hz,
                    "n": 0, "passes": False, "note": "no qualifying setups",
                })
                continue
            rob, rob_detail = regime_robust(g["_setups"], g["_netR"])
            pbo = family_pbo
            pbo_ok = (pbo is not None) and (pbo < 0.5)
            cpcv_ok = g["cpcv_lower"] > 0
            passes = bool(cpcv_ok and g["dsr_positive"] and pbo_ok
                          and rob and g["beats_base_rate"])
            results.append({
                "cell": label,
                "band": meta["band"], "horizon": hz,
                "n": g["n"],
                "mean_R": round(g["mean_R"], 5),
                "net_R_slippage": round(g["mean_netR"], 5),
                "base_rate_delta": round(g["base_rate_delta"], 5),
                "cpcv_lower": round(g["cpcv_lower"], 5),
                "dsr_stat": round(g["dsr_stat"], 4),
                "dsr_positive": g["dsr_positive"],
                "pbo": (round(pbo, 4) if pbo is not None else None),
                "regime_robust": rob,
                "beats_base_rate": g["beats_base_rate"],
                "passes": passes,
                "_robust_detail": rob_detail,
            })

    out = {
        "hypothesis": "H5 overnight structure drift (Track S EOD): sign(dist_king_pct) "
                      "predicts fwd_ret_{1d,3d} via mean-reversion toward the king, "
                      "beyond per-ticker base rate.",
        "global_n_trials": GLOBAL_N_TRIALS,
        "family_pbo": (round(family_pbo, 4) if family_pbo is not None else None),
        "pbo_matrix_T": T_pbo,
        "pbo_configs": labels if M is not None else [],
        "cells": results,
        "n_passing": sum(1 for r in results if r.get("passes")),
    }
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    main()
