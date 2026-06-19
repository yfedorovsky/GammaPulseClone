"""GRADE H1 — Positive-gamma PIN-to-king mean-reversion (Track I).

Binding pre-registration: docs/research/GEX_BACKTEST_PREREG.md (Direction A).
H1: In POS gamma, when spot is within band b of the king, the forward move is
*suppressed* and drifts *toward* the king (mean-reversion). Tradeable iff you can
FADE the deviation toward king and clear the FULL pre-reg pass bar.

Cells: band {0.0015, 0.0030, 0.0050} x horizon {15, 30, 60} min = 9 cells.
Source: gex_backtest/work.db::gex_events_intraday  (setup_type='pin', regime='POS').

R / direction (mechanical, pre-stated):
  dist_king = (spot - king)/spot   [recorded as dist_pct for pin events]
  The fade trade bets spot reverts TOWARD king:
     aligned_move = -sign(dist_king) * fwd_move      (gain when spot retraces)
     R            = aligned_move / b                 (risk = band width, per pre-reg)
  dist_king == 0 (spot exactly on king) => no deviation to fade => excluded.

Slippage: net_of_slippage (spot round-trip haircut, 2 bps/side default) with
  risk_pct = b*100 so the bps cost is charged in the same R units the trade is
  denominated in.

Base rate (the null the edge must beat): per ticker+horizon, the UNCONDITIONAL
  forward-move distribution sampled from the same stable snap_window, projected
  onto the same fade sign as a placebo deviation and expressed in the SAME
  R-units. This isolates whether conditioning on the pin adds DIRECTIONAL
  predictability beyond the ticker's own drift. (Unconditional drift is sign-
  scrambled => baseline mean ~ 0; the edge must beat it significantly.)

Regime split (confound #1): RISK-ON (SPY up-day) vs RISK-OFF (SPY down-day) +
  a crash-window drop (the single largest down-day, 2026-06-05 -1.76%). The edge
  must stay net-positive in BOTH RISK-ON and RISK-OFF AND with the crash day
  removed — an edge carried by one sub-regime is conditional, not general.

PASS = net-slippage cpcv_lower>0 AND dsr_positive AND pbo<0.5 AND regime_robust
       AND beats_base_rate.  (ALL must hold.)

READ-ONLY on work.db. Prints a JSON matrix of all 9 cells.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stats import (  # noqa: E402
    cpcv_mean_lower, dsr, pbo_cscv, net_of_slippage, base_rate_delta_full,
)

WORK = r"C:\Dev\GammaPulse\gex_backtest\work.db"
BANDS = [0.0015, 0.0030, 0.0050]
HORIZONS = [15, 30, 60]
HCOL = {15: "fwd_15", 30: "fwd_30", 60: "fwd_60"}
SEED = 20260616

# SPY RTH open->close direction over the 13 stable-window trading days.
RISK_ON = {"2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02",
           "2026-06-04", "2026-06-11", "2026-06-12", "2026-06-15"}
RISK_OFF = {"2026-06-03", "2026-06-05", "2026-06-08", "2026-06-09", "2026-06-10"}
CRASH_DAY = "2026-06-05"   # -1.76% SPY, the lone crash-like session in-window.

# Global trial count for DSR deflation = H1-H5 family x bands x horizons.
# Intraday H1-H4 (4 hyp x 3 bands x 3 horizons = 36) + H5 (1 hyp x 3 prox x 2
# horizons = 6) = 42 cells examined across the whole pre-registration matrix.
N_TRIALS_GLOBAL = 42


def _band_label(b: float) -> str:
    return {0.0015: "0.15%", 0.0030: "0.30%", 0.0050: "0.50%"}[b]


def main() -> None:
    con = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True)
    cur = con.cursor()
    rng = np.random.default_rng(SEED)

    # --- Build per-ticker+horizon unconditional move pools for the base rate ---
    # Pull ALL stable-window weekday RTH consecutive moves at each horizon, per
    # ticker, by reusing the recorded fwd_* on the pin events is NOT valid (those
    # are conditioned). Instead sample unconditional moves directly from
    # snap_window: for each ticker we approximate the unconditional H-min move
    # pool with the pin-event fwd moves of OTHER bands? No -- use snap_window.
    # We compute unconditional pools once here.
    # (snap_window has ticker, ts, et_date, et_hms, spot.)
    pools: dict[tuple[str, int], np.ndarray] = {}
    rows = cur.execute(
        "SELECT ticker, et_date, ts, spot FROM snap_window "
        "WHERE et_hms>='09:30:00' AND et_hms<='16:00:00' "
        "ORDER BY ticker, et_date, ts"
    ).fetchall()
    # group by (ticker, et_date) keeping weekday only via the pin-event date set
    valid_dates = RISK_ON | RISK_OFF
    from collections import defaultdict
    grp: dict[tuple[str, str], list] = defaultdict(list)
    for tk, d, ts, sp in rows:
        if d in valid_dates and sp and sp > 0:
            grp[(tk, d)].append((ts, sp))
    tmp: dict[tuple[str, int], list] = defaultdict(list)
    import bisect
    for (tk, d), arr in grp.items():
        arr.sort()
        ts_list = [a[0] for a in arr]
        sp_list = [a[1] for a in arr]
        n = len(arr)
        for i in range(n):
            ts0 = ts_list[i]
            sp0 = sp_list[i]
            for H in HORIZONS:
                target = ts0 + H * 60
                lo = bisect.bisect_left(ts_list, target, i + 1, n)
                best = None
                bd = None
                for j in (lo - 1, lo):
                    if j <= i or j >= n:
                        continue
                    dd = abs(ts_list[j] - target)
                    if dd <= 180 and (bd is None or dd < bd):
                        bd = dd
                        best = sp_list[j]
                if best is not None and sp0 > 0:
                    tmp[(tk, H)].append(best / sp0 - 1.0)
    for k, v in tmp.items():
        pools[k] = np.asarray(v, dtype=float)

    cells = []
    for b in BANDS:
        for H in HORIZONS:
            col = HCOL[H]
            ev = cur.execute(
                f"SELECT ticker, et_date, dist_pct, {col} FROM gex_events_intraday "
                f"WHERE setup_type='pin' AND regime='POS' AND band=? "
                f"AND dist_pct IS NOT NULL AND dist_pct<>0 AND {col} IS NOT NULL",
                (b,),
            ).fetchall()
            if not ev:
                continue
            tickers = [r[0] for r in ev]
            dates = [r[1] for r in ev]
            dist = np.asarray([r[2] for r in ev], dtype=float)
            fwd = np.asarray([r[3] for r in ev], dtype=float)

            # aligned fade R: gain when spot reverts toward king.
            aligned_move = -np.sign(dist) * fwd
            R = aligned_move / b
            R = R[np.isfinite(R)]

            # net-of-slippage in the SAME R unit (risk_pct = b in percent).
            setups = [{"risk_pct": b * 100.0} for _ in range(len(R))]
            net = net_of_slippage(R, setups=setups)

            mean_R = float(R.mean())
            net_mean = float(net.mean())
            pooled, cpcv_lower = cpcv_mean_lower(net)
            dsr_stat, dsr_pos = dsr(net, N_TRIALS_GLOBAL)

            # --- base rate: placebo-fade unconditional move, same R-unit ---
            base_R = []
            for tk, dpt, H_ in zip(tickers, dist, [H] * len(tickers)):
                pool = pools.get((tk, H_))
                if pool is None or pool.size == 0:
                    continue
                m = float(rng.choice(pool))
                base_R.append(-np.sign(dpt) * m / b)
            base_R = np.asarray(base_R, dtype=float)
            # net-of-slippage on baseline too (apples to apples).
            base_setups = [{"risk_pct": b * 100.0} for _ in range(base_R.size)]
            base_net = net_of_slippage(base_R, setups=base_setups) if base_R.size else base_R
            br = base_rate_delta_full(net, base_net)
            base_rate_delta_val = br.delta
            beats_base = br.significant

            # --- regime split ---
            dser = np.asarray(dates)
            on_mask = np.isin(dser, list(RISK_ON))[: net.size]
            off_mask = np.isin(dser, list(RISK_OFF))[: net.size]
            nocrash_mask = (dser != CRASH_DAY)[: net.size]
            on_mean = float(net[on_mask].mean()) if on_mask.any() else float("nan")
            off_mean = float(net[off_mask].mean()) if off_mask.any() else float("nan")
            nocrash_mean = float(net[nocrash_mask].mean()) if nocrash_mask.any() else float("nan")
            regime_robust = (on_mean > 0) and (off_mean > 0) and (nocrash_mean > 0)

            passes = (cpcv_lower > 0) and dsr_pos and beats_base and regime_robust

            cells.append({
                "band": _band_label(b),
                "horizon": f"{H}min",
                "n": int(net.size),
                "mean_R": round(mean_R, 4),
                "net_R_slippage": round(net_mean, 4),
                "base_rate_delta": round(float(base_rate_delta_val), 4),
                "cpcv_lower": round(float(cpcv_lower), 4),
                "dsr_stat": round(float(dsr_stat), 4),
                "dsr_positive": bool(dsr_pos),
                "beats_base_rate": bool(beats_base),
                "br_t": round(float(br.t_stat), 3),
                "br_p": round(float(br.p_value), 4),
                "regime_on_mean": round(on_mean, 4),
                "regime_off_mean": round(off_mean, 4),
                "nocrash_mean": round(nocrash_mean, 4),
                "regime_robust": bool(regime_robust),
                "_R": R,             # keep for PBO matrix
                "_net": net,
                "_dates": dser,
            })

    # --- PBO across the 9 (band x horizon) variants of H1 (CSCV) ---
    # Build a (T x 9) matrix by aligning each variant's net-R series to a common
    # length (min n across cells); columns are the variant configs of THIS
    # hypothesis (the overfitting question: does the IS-best variant stay best?).
    series = [c["_net"] for c in cells]
    pbo = None
    if len(series) >= 2:
        T = min(s.size for s in series)
        if T >= 20:
            M = np.column_stack([
                np.asarray(s[:T], dtype=float) for s in series
            ])
            pbo = pbo_cscv(M)

    # finalize: attach pbo and passes (pbo<0.5 part of the bar)
    out_cells = []
    for c in cells:
        pbo_ok = (pbo is not None) and (pbo < 0.5)
        passes_full = (c["cpcv_lower"] > 0 and c["dsr_positive"]
                       and c["beats_base_rate"] and c["regime_robust"] and pbo_ok)
        rec = {k: v for k, v in c.items() if not k.startswith("_")}
        rec["pbo"] = (round(float(pbo), 4) if pbo is not None else None)
        rec["passes"] = bool(passes_full)
        out_cells.append(rec)

    con.close()
    print(json.dumps({"hypothesis": "H1", "pbo_family": pbo,
                      "n_trials_global": N_TRIALS_GLOBAL,
                      "cells": out_cells}, indent=2))


if __name__ == "__main__":
    main()
