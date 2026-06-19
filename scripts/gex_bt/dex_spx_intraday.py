"""DEX SPX-INTRADAY check — the member's EXACT regime (SPX, intraday, at levels).

The daily single-name test (dex_backtest.py) was a decisive null, but its scope
caveat was: the member's framing is SPX-intraday. This tests THAT, with the data
we actually have — and is HONESTLY LOW POWER:

  - SPX OI: local daily_oi_snapshot, only ~22 trading days (2026-05-19+).
  - Intraday SPX path: snapshots.db spot (~70-100 RTH pts/day, our worker cadence,
    staleness-prone — not clean 5-min OHLC).
  - Greeks: FLAT-IV BSM (no entitled Theta greeks endpoint) — delta/gamma location
    is robust to flat IV; magnitudes approximate.

Effective n ≈ number of days (OI is one morning profile per day), so this CANNOT
be definitive — it is a directional sanity check of whether the member's exact
regime surprises the daily null. A properly-powered version needs ThetaData SPXW
OI history (years) + IV reconstruction + a real intraday index feed.

Out -> data/dex_spx_intraday_results.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

DB = "snapshots.db"
FLAT_IV = 0.15            # SPX flat-IV approximation for BSM greeks
R = 0.045
MAX_DTE = 30             # aggregate OI across expirations within this window
NEAR_LEVEL = 0.003       # spot within 0.3% of a wall = "approach" (index scale)
BREAK_FWD_MIN = 30       # look this many minutes forward for break/bounce
BREAK_MARGIN = 0.0015    # clear the wall by 0.15% = break
RNG = np.random.default_rng(20260618)


def _bsm_delta_gamma(S, K, T, sigma, is_call):
    T = max(T, 0.5 / 365)
    d1 = (np.log(S / K) + (R + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    gamma = stats.norm.pdf(d1) / (S * sigma * np.sqrt(T))
    delta = stats.norm.cdf(d1) if is_call else stats.norm.cdf(d1) - 1.0
    return delta, gamma


def load_oi(con, date):
    """SPX OI as-of `date`, aggregated strikes within MAX_DTE. Returns list of
    (strike, right, oi, dte)."""
    rows = con.execute(
        "SELECT strike, option_type, exp, MAX(oi) FROM daily_oi_snapshot "
        "WHERE ticker='SPX' AND date=? GROUP BY strike, option_type, exp", (date,)
    ).fetchall()
    out = []
    d0 = time.strptime(date, "%Y-%m-%d")
    for k, ot, exp, oi in rows:
        if not oi or oi <= 0:
            continue
        try:
            de = (time.mktime(time.strptime(exp, "%Y-%m-%d")) - time.mktime(d0)) / 86400
        except Exception:
            continue
        if 0 <= de <= MAX_DTE:
            out.append((float(k), (ot or "")[:1].upper(), float(oi), de))
    return out


def profile(oi_rows, spot):
    """Net DEX, net GEX, and per-strike GEX (for walls) at `spot`."""
    dex = gex = 0.0
    strike_gex: dict[float, float] = {}
    for k, right, oi, dte in oi_rows:
        if right not in ("C", "P") or abs(k / spot - 1) > 0.15:
            continue
        T = dte / 365.0
        is_call = right == "C"
        delta, gamma = _bsm_delta_gamma(spot, k, T, FLAT_IV, is_call)
        sign = 1.0 if is_call else -1.0
        dex += delta * oi * 100
        g = gamma * oi * 100 * spot * spot * 0.01 * sign
        gex += g
        strike_gex[k] = strike_gex.get(k, 0.0) + g
    return dex, gex, strike_gex


def walls(strike_gex, spot):
    above = [(k, v) for k, v in strike_gex.items() if v > 0 and k > spot]
    below = [(k, v) for k, v in strike_gex.items() if v > 0 and k < spot]
    cw = max(above, key=lambda x: x[1])[0] if above else None
    pw = max(below, key=lambda x: x[1])[0] if below else None
    return cw, pw


def intraday_path(con, date):
    """RTH SPX (ts, spot) on `date`, sorted."""
    rows = con.execute(
        "SELECT ts, spot FROM snapshots WHERE ticker='SPX' "
        "AND date(ts,'unixepoch','localtime')=? ORDER BY ts", (date,)
    ).fetchall()
    out = []
    for ts, spot in rows:
        hhmm = time.strftime("%H:%M", time.localtime(ts))
        if "09:30" <= hhmm <= "16:00" and spot and spot > 0:
            out.append((ts, float(spot)))
    return out


def run():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM daily_oi_snapshot WHERE ticker='SPX' ORDER BY date")]
    events = []  # (date, dex_z_placeholder, dex_at_approach, broke)
    per_day_dex = {}
    for d in dates:
        oi_rows = load_oi(con, d)
        path = intraday_path(con, d)
        if len(oi_rows) < 20 or len(path) < 10:
            continue
        morn_spot = path[0][1]
        _, _, sg = profile(oi_rows, morn_spot)
        cw, pw = walls(sg, morn_spot)
        per_day_dex[d] = profile(oi_rows, morn_spot)[0]
        # walk intraday, detect approaches to cw/pw
        for i, (ts, spot) in enumerate(path):
            for L in (cw, pw):
                if L is None or abs(spot / L - 1) > NEAR_LEVEL:
                    continue
                # DEX recomputed at this spot (OI fixed, greeks shift with spot)
                dex_here, _, _ = profile(oi_rows, spot)
                up = L > spot
                # forward window
                fut = [s for t2, s in path[i + 1:] if t2 - ts <= BREAK_FWD_MIN * 60]
                if not fut:
                    continue
                ext = max(fut) if up else min(fut)
                broke = (ext > L * (1 + BREAK_MARGIN)) if up else (ext < L * (1 - BREAK_MARGIN))
                bounced = (min(fut) < spot) if up else (max(fut) > spot)
                if broke:
                    events.append((d, dex_here, 1))
                elif bounced:
                    events.append((d, dex_here, 0))
    con.close()

    if len(events) < 20:
        out = {"n_events": len(events), "note": "too few events — inconclusive (data-limited)"}
        print(json.dumps(out, indent=2)); Path("data/dex_spx_intraday_results.json").write_text(json.dumps(out, indent=2)); return out

    edates = np.array([e[0] for e in events])
    dex = np.array([e[1] for e in events], float)
    y = np.array([e[2] for e in events], float)
    # per-day z-score of DEX (the trader reads "DEX unusual for the day")
    dex_z = np.copy(dex)
    for d in np.unique(edates):
        m = edates == d
        mu, sd = dex[m].mean(), dex[m].std() or 1e-9
        dex_z[m] = (dex[m] - mu) / sd
    auc = roc_auc_score(y, dex_z) if len(np.unique(y)) > 1 else None
    # within-day placebo
    null = []
    for _ in range(500):
        perm = np.copy(dex_z)
        for d in np.unique(edates):
            m = edates == d
            perm[m] = RNG.permutation(perm[m])
        try:
            null.append(roc_auc_score(y, perm))
        except Exception:
            pass
    null = np.array(null)
    p = (np.sum(np.abs(null - 0.5) >= abs((auc or 0.5) - 0.5)) + 1) / (len(null) + 1) if len(null) else None
    out = {
        "n_days": len(per_day_dex), "n_events": len(events),
        "break_rate": round(float(y.mean()), 3),
        "dex_break_auc": round(float(auc), 4) if auc else None,
        "placebo_97.5pct": round(float(np.nanpercentile(null, 97.5)), 4) if len(null) else None,
        "p": round(float(p), 4) if p is not None else None,
        "POWER_CAVEAT": f"effective n ~ {len(per_day_dex)} days; flat-IV BSM; coarse snapshot intraday. Directional only.",
    }
    print("\n=== DEX SPX-INTRADAY (LOW POWER — directional check) ===")
    print(json.dumps(out, indent=2))
    Path("data/dex_spx_intraday_results.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    run()
