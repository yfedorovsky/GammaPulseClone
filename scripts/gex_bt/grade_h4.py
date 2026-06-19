"""GRADE H4 — Negative-gamma instability (Track I, intraday).

Pre-registered under docs/research/GEX_BACKTEST_PREREG.md (Direction A, H4):

  H4 — Negative-gamma instability. In NEG gamma, the same proximity setups do
  NOT hold — realized vol is HIGHER and BREAKOUTS BEAT FADES (the inverse of
  H1-H3). Tests whether the regime tag itself carries information.

We grade EVERY pre-reg cell (setup_type x band x horizon) RESTRICTED TO
regime='NEG', and report all of them (multiplicity matters). Nothing is
cherry-picked; a null is the honest default.

ORIENTATION (the H4 inversion of H1-H3; pre-reg: "breakouts beat fades"):
  * floor  : H2 was a long bounce. H4 inverts -> BREAKDOWN short. R = -fwd/band.
  * ceiling: H3 was a short reject. H4 inverts -> BREAKOUT-UP long. R = +fwd/band.
  * pin    : H1 was fade-toward-king. H4 inverts -> BREAKOUT AWAY from king.
             R = sign(dist_from_king) * fwd / band  (bet in the displacement
             direction). dist~0 at the pin makes this the weakest arm by design;
             we report it honestly rather than redefine it post hoc.

R UNITS (pre-reg "move / fixed per-setup risk = band width"):
  R = oriented_fwd_move / band.   risk_pct passed to the slippage haircut is
  band*100 (band expressed in percent), so the bps cost is converted into the
  SAME R unit. Default 2 bps/side (4 bps round-trip), the liquid-name spot
  convention in scripts/gex_bt/stats.py.

PASS BAR (pre-committed, ALL must hold on NET-OF-SLIPPAGE R):
  1. cpcv_lower > 0      (CPCV OOS lower band on mean R)
  2. dsr_positive        (deflated Sharpe survives, n_trials = GLOBAL cell count)
  3. pbo < 0.5           (CSCV, not overfit)
  4. regime_robust       (survives RISK-ON/OFF split + not carried by one day)
  5. beats_base_rate     (oriented setup R beats the matched unconditional null)

n_trials for DSR = the global H4 trial count = #setup x #band x #horizon = 27
(every cell we examined pays for selection).

BASE RATE: the pre-reg null is the per-ticker UNCONDITIONAL forward-return
distribution. For a DIRECTIONAL H4 bet, the matched null is the SAME oriented
bet placed unconditionally. We reconstruct it from work.db::snap_window: for
each NEG setup row, sample the ticker's unconditional same-day fwd move at the
same horizon (oriented by the setup sign), giving a real Welch comparison
(stats.base_rate_delta) instead of a sign-blind summary mean.

READ-ONLY on snapshots.db/chains.db. Reads only work.db (our artifact).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stats  # noqa: E402  (the GEX rigor harness)

WORK = r"C:\Dev\GammaPulse\gex_backtest\work.db"

REGIME = "NEG"
SETUPS = ["pin", "floor", "ceiling"]
BANDS = [0.0015, 0.0030, 0.0050]
HORIZONS = [15, 30, 60]
FWD_COL = {15: "fwd_15", 30: "fwd_30", 60: "fwd_60"}

# GLOBAL trial count for DSR deflation: every H4 cell we looked at.
N_TRIALS = len(SETUPS) * len(BANDS) * len(HORIZONS)  # 27

SLIP_BPS_PER_SIDE = stats.DEFAULT_SLIP_BPS_PER_SIDE   # 2 bps/side (4 bps RT)


# --------------------------------------------------------------------------- #
# UNCONDITIONAL per-ticker forward-move pool (the pre-reg null).
# --------------------------------------------------------------------------- #
# The matched null must be UNCONDITIONAL: a regime-blind / setup-blind sample of
# the ticker's own same-day forward moves (exactly the base_rates methodology in
# build_base_rates.py — random entry, same-session, RTH). For each setup row we
# orient an independent unconditional draw from the SAME ticker & horizon by the
# setup's H4 sign. This makes "beats_base_rate" the honest test: does the NEG
# proximity setup beat what the SAME oriented bet earns at a random time?
import bisect as _bisect
import random as _random

_NULL_SEED = 20260616          # fixed (matches build_base_rates SEED)
_NULL_TOL = 180                # +/- 3 min, same as build_intraday


def _build_null_pool(con):
    """Return {ticker: {H: np.array of unconditional fwd moves}} sampled from
    snap_window at RANDOM RTH same-day entries (regime-blind)."""
    rows = con.execute(
        "SELECT ticker, et_date, ts, spot FROM snap_window "
        "WHERE et_hms >= '09:30:00' AND et_hms <= '16:00:00' "
        "ORDER BY ticker, et_date, ts"
    ).fetchall()
    byday = {}
    for tk, dt, ts, spot in rows:
        byday.setdefault((tk, dt), []).append((ts, spot))

    rng = _random.Random(_NULL_SEED)
    pool = {}
    # group entries by ticker (across its days) and sample without replacement.
    by_ticker_days = {}
    for (tk, dt), arr in byday.items():
        by_ticker_days.setdefault(tk, []).append((dt, arr))

    for tk, daylist in by_ticker_days.items():
        entries = []          # (arr, i)
        for _dt, arr in daylist:
            for i in range(len(arr)):
                entries.append((arr, i))
        rng.shuffle(entries)
        if len(entries) > 1500:           # MAX_SAMPLES_PER_TICKER (base-rate cap)
            entries = entries[:1500]
        hvals = {H: [] for H in HORIZONS}
        for arr, i in entries:
            ts0, sp0 = arr[i]
            if not sp0 or sp0 <= 0:
                continue
            tsl = [t for t, _ in arr]
            for H in HORIZONS:
                target = ts0 + H * 60
                lo = _bisect.bisect_left(tsl, target, i + 1)
                best, bestd = None, None
                for j in (lo - 1, lo):
                    if j <= i or j >= len(arr):
                        continue
                    d = abs(tsl[j] - target)
                    if d <= _NULL_TOL and (bestd is None or d < bestd):
                        bestd, best = d, arr[j][1]
                if best is not None:
                    hvals[H].append(best / sp0 - 1.0)
        pool[tk] = {H: np.asarray(v, dtype=float) for H, v in hvals.items()}
    return pool


def _orient(setup_type, fwd, dist_pct):
    """Map a raw forward move to the H4 (breakout) oriented move."""
    if setup_type == "floor":
        return -fwd                       # breakdown short
    if setup_type == "ceiling":
        return +fwd                       # breakout-up long
    # pin: breakout AWAY from king, in the displacement direction.
    s = 1.0 if (dist_pct or 0.0) >= 0 else -1.0
    return s * fwd


def _orient(setup_type, fwd, dist_pct):
    """Map a raw forward move to the H4 (breakout) oriented move."""
    if setup_type == "floor":
        return -fwd                       # breakdown short
    if setup_type == "ceiling":
        return +fwd                       # breakout-up long
    # pin: breakout AWAY from king, in the displacement direction.
    s = 1.0 if (dist_pct or 0.0) >= 0 else -1.0
    return s * fwd


# --------------------------------------------------------------------------- #
# Grade one cell.
# --------------------------------------------------------------------------- #
def grade_cell(con, null_pool, day_negshare, setup_type, band, H):
    fcol = FWD_COL[H]
    rows = con.execute(
        f"SELECT e.ticker, e.et_date, e.dist_pct, e.{fcol} "
        "FROM gex_events_intraday e "
        f"WHERE e.regime=? AND e.setup_type=? AND e.band=? AND e.{fcol} IS NOT NULL",
        (REGIME, setup_type, band),
    ).fetchall()

    oriented = []      # oriented R-multiples (move/band)
    base_oriented = [] # UNCONDITIONAL oriented R-multiples (the pre-reg null)
    days = []          # et_date per oriented obs (for the one-day-carry test)
    risk_on = []       # bool per oriented obs (risk split)
    rng = _random.Random(_NULL_SEED)

    for tk, dt, dist_pct, fwd in rows:
        if fwd is None:
            continue
        omove = _orient(setup_type, fwd, dist_pct)
        oriented.append(omove / band)
        days.append(dt)
        # risk split: RISK-OFF (stress) when day's NEG-share above median.
        risk_on.append(day_negshare.get(dt, 0.0) <= _MEDIAN_NEGSHARE)
        # matched UNCONDITIONAL null: an independent random-time forward move
        # for the SAME ticker & horizon, oriented by the same H4 sign. This is
        # the per-ticker base rate (regime/setup-blind), NOT the event's own move.
        upool = null_pool.get(tk, {}).get(H)
        if upool is not None and upool.size:
            draw = float(upool[rng.randrange(upool.size)])
            base_oriented.append(_orient(setup_type, draw, dist_pct) / band)

    n = len(oriented)
    res = {
        "setup": setup_type, "band": band, "horizon": f"{H}min", "n": n,
    }
    if n == 0:
        res.update(dict(mean_R=None, net_R_slippage=None, base_rate_delta=None,
                        beats_base_rate=False, cpcv_lower=None, dsr_positive=False,
                        pbo=None, regime_robust=False, passes=False))
        return res

    r = np.asarray(oriented, dtype=float)
    setups_ctx = [{"risk_pct": band * 100.0,
                   "slip_bps_per_side": SLIP_BPS_PER_SIDE}] * n
    net = stats.net_of_slippage(r, setups_ctx, slip_bps_per_side=SLIP_BPS_PER_SIDE)

    mean_R = float(r.mean())
    net_mean = float(net.mean())

    # 1. CPCV lower band on net-of-slippage R.
    _, cpcv_lower = stats.cpcv_mean_lower(net)

    # 2. DSR on net R, deflated for the GLOBAL trial count.
    _, dsr_pos = stats.dsr(net, N_TRIALS)

    # 5. base-rate delta: oriented setup R vs matched unconditional oriented R.
    if base_oriented:
        delta, br_sig = stats.base_rate_delta(net, np.asarray(base_oriented))
    else:
        delta, br_sig = None, False

    # 4. regime_robust: survives the RISK-ON/OFF split AND not carried by one day.
    regime_robust = _regime_robust(net, days, risk_on)

    passes = bool(
        (cpcv_lower is not None and cpcv_lower > 0)
        and dsr_pos
        and True  # pbo filled below; combined after
        and regime_robust
        and br_sig
    )

    res.update(dict(
        mean_R=round(mean_R, 4),
        net_R_slippage=round(net_mean, 4),
        base_rate_delta=(round(delta, 4) if delta is not None else None),
        beats_base_rate=bool(br_sig),
        cpcv_lower=(round(float(cpcv_lower), 4) if np.isfinite(cpcv_lower) else None),
        dsr_positive=bool(dsr_pos),
        regime_robust=bool(regime_robust),
        _net=net,            # stashed for the PBO matrix (popped before output)
        _passes_partial=passes,
    ))
    return res


def _regime_robust(net, days, risk_on):
    """Edge must (a) be positive in BOTH the risk-on and risk-off arms, and
    (b) not be carried by a single trading day (drop-one-day still positive)."""
    net = np.asarray(net, dtype=float)
    ro = np.asarray(risk_on, dtype=bool)
    if net.size < 8:
        return False
    on, off = net[ro], net[~ro]
    if on.size < 3 or off.size < 3:
        return False
    if not (on.mean() > 0 and off.mean() > 0):
        return False
    # drop-one-day: removing any single day must not flip the pooled mean <=0.
    days = np.asarray(days)
    for d in np.unique(days):
        keep = net[days != d]
        if keep.size and keep.mean() <= 0:
            return False
    return True


def main():
    con = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True)

    # Per-day NEG-share (stress proxy) over ALL events, for the risk split.
    global _MEDIAN_NEGSHARE
    day_rows = con.execute(
        "SELECT et_date, AVG(regime='NEG') FROM gex_events_intraday GROUP BY et_date"
    ).fetchall()
    day_negshare = {d: s for d, s in day_rows}
    _MEDIAN_NEGSHARE = float(np.median(list(day_negshare.values())))

    null_pool = _build_null_pool(con)

    # Grade all cells; collect per-setup PBO matrices (columns = band x horizon).
    cells = []
    pbo_cols = {st: [] for st in SETUPS}   # st -> list of net arrays
    for st in SETUPS:
        for b in BANDS:
            for H in HORIZONS:
                c = grade_cell(con, null_pool, day_negshare, st, b, H)
                cells.append(c)
                if "_net" in c:
                    pbo_cols[st].append(c.pop("_net"))

    # PBO per setup family (a column per band x horizon variant), aligned by
    # truncating to the shortest column so the matrix is rectangular.
    pbo_by_setup = {}
    for st in SETUPS:
        cols = [a for a in pbo_cols.get(st, []) if a is not None and len(a) >= 8]
        if len(cols) >= 2:
            m = min(len(a) for a in cols)
            M = np.column_stack([a[:m] for a in cols])
            pbo_by_setup[st] = stats.pbo_cscv(M)
        else:
            pbo_by_setup[st] = None

    # Finalize pass flag with PBO.
    out = []
    for c in cells:
        st = c["setup"]
        pbo = pbo_by_setup.get(st)
        partial = c.pop("_passes_partial", False)
        pbo_ok = (pbo is not None and pbo < 0.5)
        c["pbo"] = (round(float(pbo), 4) if pbo is not None else None)
        c["passes"] = bool(partial and pbo_ok)
        out.append(c)

    print(json.dumps({
        "hypothesis": "H4",
        "regime": REGIME,
        "n_trials_dsr": N_TRIALS,
        "median_negshare_split": round(_MEDIAN_NEGSHARE, 4),
        "slip_bps_per_side": SLIP_BPS_PER_SIDE,
        "pbo_by_setup": {k: (round(v, 4) if v is not None else None)
                         for k, v in pbo_by_setup.items()},
        "cells": out,
    }, indent=2))
    con.close()


if __name__ == "__main__":
    main()
