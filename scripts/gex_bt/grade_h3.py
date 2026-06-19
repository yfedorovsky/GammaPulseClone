"""GRADE H3 — POS-gamma CEILING reject (intraday, Track I).

Pre-registration: docs/research/GEX_BACKTEST_PREREG.md (Direction A, H3).
H3 — Ceiling reject. In POS gamma, when spot tests within band b of the ceiling,
forward return is NEGATIVE (reject) at a rate beating the ticker base rate.

This is an intraday hypothesis (Track I): we grade gex_events_intraday
(setup_type='ceiling', regime='POS') for EVERY pre-reg cell band x horizon
(bands {0.0015,0.0030,0.0050} x horizons {15,30,60}min = 9 cells), reporting ALL
cells (multiplicity matters), not just winners.

R-unit convention (pinned to the pre-reg): per-setup risk = the band width b
(the structural stop). The setup is a SHORT (reject), so a profitable trade is a
DOWN move:
    setup_R = (-fwd_move) / b
A positive setup_R = spot fell = the reject played out. risk_pct = b*100 (percent)
is threaded into net_of_slippage so the bps haircut is converted to R honestly.

Base rate (the null): the per-ticker UNCONDITIONAL forward spot move at the same
horizon (base_rates table, fractional). H3 predicts a SHORT, so the honest beat
test compares the conditioned SHORT return to the unconditional move expressed as
a SHORT: baseline_short_R = (-base_mean)/b. We build a per-setup baseline vector
by attaching each ticker's unconditional mean move for that horizon (the table
stores the distribution moments, so the per-setup baseline is the ticker mean —
the Welch test then asks whether the conditioned sample mean beats the pooled
unconditional mean, in R units).

Pass bar (ALL must hold, per pre-reg):
  net-slippage cpcv_lower > 0  AND dsr_positive  AND pbo < 0.5
  AND regime_robust  AND beats_base_rate.

regime_robust := mean net-R > 0 in BOTH the RISK-ON and RISK-OFF day subsets
AND mean net-R > 0 with the crash-window days excluded (not carried by one regime
or by the crash days alone).

READ-ONLY on work.db (file:...?mode=ro). Writes nothing. Prints a JSON matrix.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stats as S  # noqa: E402  (the GEX rigor harness)

WORK = "file:///C:/Dev/GammaPulse/gex_backtest/work.db?mode=ro"

BANDS = [0.0015, 0.0030, 0.0050]
HORIZONS = [15, 30, 60]
HCOL = {15: "fwd_15", 30: "fwd_30", 60: "fwd_60"}
HBASE = {15: "15min", 30: "30min", 60: "60min"}

# Pre-reg GLOBAL trial count for DSR deflation: the deflation must pay for every
# (hypothesis x band x horizon) cell the family examined. H1-H4 are each
# 3 bands x 3 horizons = 9 cells; H5 is proximity-bucket x {1d,3d}. We deflate
# H3 for the FULL intraday family it belongs to (H1-H4 x 9 = 36 cells) — the
# honest selection count for "we looked at the whole intraday matrix and report
# the ceiling/POS slice". This matches the pre-reg "report ALL cells; deflate for
# the number of (hypothesis x parameter) trials".
N_TRIALS = 36

# --- Regime split (derived from SPY daily moves over the stable window) -------
# RISK-OFF = SPY intraday return <= -0.30% (stress sessions); else RISK-ON.
# CRASH window = the down-stress cluster (6/05 -1.76%, 6/09 -1.00%, 6/10 -0.94%).
RISK_OFF_DAYS = {"2026-06-03", "2026-06-05", "2026-06-08", "2026-06-09", "2026-06-10"}
CRASH_DAYS = {"2026-06-05", "2026-06-09", "2026-06-10"}


def _setups_for(band, dist_pcts):
    """Build the per-setup context list (risk_pct = band width in percent)."""
    rp = band * 100.0
    return [{"risk_pct": rp} for _ in dist_pcts]


def grade():
    con = sqlite3.connect(WORK, uri=True)
    cur = con.cursor()

    # Base rates: per-ticker unconditional mean move per horizon (fractional).
    base_mean = {}  # (ticker, horizon_min) -> mean
    for tk, hz, mean, n in cur.execute(
        "SELECT ticker, horizon, mean, n FROM base_rates WHERE horizon LIKE '%min'"
    ):
        if mean is not None and n and n > 0:
            base_mean[(tk, hz)] = mean

    cells = []
    # First, gather per-cell return vectors so DSR/PBO see the family together.
    cell_data = {}  # (band,h) -> dict
    for band in BANDS:
        for h in HORIZONS:
            col = HCOL[h]
            rows = cur.execute(
                f"SELECT ticker, et_date, dist_pct, {col} "
                f"FROM gex_events_intraday "
                f"WHERE setup_type='ceiling' AND regime='POS' AND band=? "
                f"AND {col} IS NOT NULL",
                (band,),
            ).fetchall()
            tickers = [r[0] for r in rows]
            dates = [r[1] for r in rows]
            moves = np.array([r[3] for r in rows], dtype=float)
            # SHORT (reject) R-multiple: profit on a DOWN move, risk = band.
            setup_R = (-moves) / band
            # Baseline as a SHORT, per-setup ticker unconditional mean move.
            hb = HBASE[h]
            base_vec = np.array(
                [(-base_mean.get((t, hb), 0.0)) / band for t in tickers],
                dtype=float,
            )
            cell_data[(band, h)] = {
                "tickers": tickers, "dates": dates,
                "moves": moves, "setup_R": setup_R, "base_R": base_vec,
            }

    # PBO across the 9 band x horizon variants: align columns on a common index.
    # CSCV needs an (T x N) matrix with equal-length columns; we cannot align
    # heterogeneous setups across cells (different events), so PBO is computed
    # per-band across its 3 horizons AND per-horizon across its 3 bands, and we
    # report the MAX (most pessimistic) PBO each cell participates in. This keeps
    # the overfitting test honest without fabricating a cross-cell alignment.
    # Build padded matrices by truncating to the min column length within a group.
    def pbo_for_group(keys):
        cols = [cell_data[k]["setup_R"] for k in keys]
        m = min((c.size for c in cols), default=0)
        if m < 10 or len(cols) < 2:
            return None
        M = np.column_stack([c[:m] for c in cols])
        return S.pbo_cscv(M)

    pbo_by_band = {b: pbo_for_group([(b, h) for h in HORIZONS]) for b in BANDS}
    pbo_by_h = {h: pbo_for_group([(b, h) for b in BANDS]) for h in HORIZONS}

    for band in BANDS:
        for h in HORIZONS:
            d = cell_data[(band, h)]
            setup_R = d["setup_R"]
            base_R = d["base_R"]
            dates = d["dates"]
            n = int(setup_R.size)

            net_R = S.net_of_slippage(setup_R, _setups_for(band, setup_R))
            mean_R = float(np.mean(setup_R)) if n else 0.0
            net_mean = float(np.mean(net_R)) if n else 0.0

            cpcv_mean, cpcv_lower = S.cpcv_mean_lower(net_R)
            dsr_stat, dsr_pos = S.dsr(net_R, N_TRIALS)

            # base-rate delta (net-of-slippage edge vs unconditional short).
            br_delta, br_sig = S.base_rate_delta(net_R, base_R)

            # regime split on NET-of-slippage R.
            dates_arr = np.array(dates)
            ron = net_R[np.array([dt not in RISK_OFF_DAYS for dt in dates], dtype=bool)]
            roff = net_R[np.array([dt in RISK_OFF_DAYS for dt in dates], dtype=bool)]
            nocrash = net_R[np.array([dt not in CRASH_DAYS for dt in dates], dtype=bool)]
            ron_mean = float(ron.mean()) if ron.size else float("nan")
            roff_mean = float(roff.mean()) if roff.size else float("nan")
            nocrash_mean = float(nocrash.mean()) if nocrash.size else float("nan")
            # robust: positive in BOTH regimes (each non-empty) AND positive
            # without the crash days. NaN (empty subset) => not robust.
            regime_robust = bool(
                ron.size > 0 and roff.size > 0
                and ron_mean > 0 and roff_mean > 0 and nocrash_mean > 0
            )

            pbo = None
            cands = [pbo_by_band.get(band), pbo_by_h.get(h)]
            cands = [c for c in cands if c is not None]
            if cands:
                pbo = max(cands)  # most pessimistic

            beats_base = bool(br_sig)
            # pass = full pre-reg bar.
            cpcv_ok = np.isfinite(cpcv_lower) and cpcv_lower > 0
            pbo_ok = (pbo is not None) and (pbo < 0.5)
            passes = bool(cpcv_ok and dsr_pos and pbo_ok and regime_robust and beats_base)

            cells.append({
                "band": f"{band:.4f}",
                "horizon": f"{h}min",
                "n": n,
                "mean_R": round(mean_R, 4),
                "net_R_slippage": round(net_mean, 4),
                "base_rate_delta": round(float(br_delta), 4),
                "cpcv_lower": (round(float(cpcv_lower), 4)
                               if np.isfinite(cpcv_lower) else None),
                "dsr_stat": round(float(dsr_stat), 4),
                "dsr_positive": bool(dsr_pos),
                "pbo": (round(float(pbo), 4) if pbo is not None else None),
                "regime_robust": regime_robust,
                "beats_base_rate": beats_base,
                "ron_mean": round(ron_mean, 4) if np.isfinite(ron_mean) else None,
                "roff_mean": round(roff_mean, 4) if np.isfinite(roff_mean) else None,
                "nocrash_mean": round(nocrash_mean, 4) if np.isfinite(nocrash_mean) else None,
                "n_ron": int(ron.size), "n_roff": int(roff.size),
                "passes": passes,
            })

    con.close()
    print(json.dumps({"hypothesis": "H3", "n_trials_deflation": N_TRIALS,
                      "cells": cells}, indent=2))


if __name__ == "__main__":
    grade()
