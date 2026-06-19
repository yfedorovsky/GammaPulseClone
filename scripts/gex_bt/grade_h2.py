"""GRADE H2 — POS-gamma FLOOR BOUNCE tradeability grade.

Binding pre-reg: docs/research/GEX_BACKTEST_PREREG.md (H2).
  Hypothesis: In POS gamma, when spot tests within band b of the floor, the
  forward return is POSITIVE (bounce) at a rate beating the ticker base rate.
  Win direction = LONG (positive forward move off the floor).

Cells: band {0.0015,0.0030,0.0050} x horizon {15,30,60 min} = 9 (intraday H1-H4
grid). Track I only (intraday); H2 has no Track S overnight arm in the pre-reg
(H5 is the swing hypothesis). Reports ALL 9 cells.

R-unit (pre-reg): signed return in R = move / fixed per-setup risk = band width.
  Floor bounce is a LONG trade, so R = +fwd_return / band. (Positive fwd = win.)

Pass bar (ALL must hold on the NET-OF-SLIPPAGE series):
  net-slippage cpcv_lower > 0  AND dsr_positive  AND pbo < 0.5
  AND regime_robust  AND beats_base_rate.

Slippage: net_of_slippage with risk_pct = band*100 (band width in %), so the
  2bps/side spot haircut is charged in the SAME R units the return is in.

base_rate: per-ticker intraday base_rates (15min/30min/60min). The conditioned
  FRACTIONAL forward return must beat the event-ticker-weighted unconditional
  base-rate mean (Welch one-sided). We compare on fractional return (the native
  base_rates unit), not band-scaled R, so the comparison is apples-to-apples.

regime_robust: the edge must NOT be carried by one regime/the crash window.
  Split each event by the day's SPY intraday direction (RISK-ON vs RISK-OFF) AND
  hold out the crash window (2026-06-09, SPY's sharp down day). regime_robust =
  net-of-slippage mean R > 0 in BOTH the RISK-ON and RISK-OFF subsets (sign-
  consistent, not solely one side) AND still > 0 with the crash day removed.

DSR n_trials = GLOBAL grid the H2 family paid for = 9 (band x horizon).
READ-ONLY on source DBs; reads only work.db.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats as S  # noqa: E402

WORK = r"C:\Dev\GammaPulse\gex_backtest\work.db"
BANDS = [0.0015, 0.0030, 0.0050]
HORIZONS = [15, 30, 60]
FWD_COL = {15: "fwd_15", 30: "fwd_30", 60: "fwd_60"}
BR_HORIZON = {15: "15min", 30: "30min", 60: "60min"}
N_TRIALS = len(BANDS) * len(HORIZONS)  # 9
CRASH_DAY = "2026-06-09"


def spy_day_direction(cur):
    """et_date -> 'ON'/'OFF' from SPY first-vs-last RTH snap spot."""
    out = {}
    dates = [d for (d,) in cur.execute(
        "SELECT DISTINCT et_date FROM snap_window WHERE ticker='SPY' ORDER BY et_date"
    )]
    for d in dates:
        rows = cur.execute(
            "SELECT spot FROM snap_window WHERE ticker='SPY' AND et_date=? "
            "AND et_hms>='09:30:00' AND et_hms<='16:00:00' ORDER BY ts",
            (d,),
        ).fetchall()
        if len(rows) >= 2 and rows[0][0]:
            out[d] = "OFF" if (rows[-1][0] / rows[0][0] - 1.0) < 0 else "ON"
    return out


def base_rate_pool(cur, tickers, horizon_label):
    """Synthetic baseline sample matching the event ticker mix.

    For each event ticker we draw its per-ticker base-rate mean (the
    unconditional forward-return drift). The baseline 'sample' is the
    per-event base-rate mean, so Welch compares conditioned vs unconditional
    on the SAME ticker composition. Returns a float array (one per event row,
    in fractional return units)."""
    br = {}
    for tk, mean, n in cur.execute(
        "SELECT ticker, mean, n FROM base_rates WHERE horizon=?", (horizon_label,)
    ):
        if mean is not None and n and n > 0:
            br[tk] = float(mean)
    return br


def grade_cell(rows, band, horizon, br_map, day_dir):
    """rows: list of (ticker, et_date, fwd) for this (band,horizon) POS-floor cell,
    fwd already filtered non-null. Returns the result dict."""
    fwd = np.array([r[2] for r in rows], dtype=float)
    tickers = [r[0] for r in rows]
    dates = [r[1] for r in rows]
    n = fwd.size

    # R-units: floor bounce is LONG, R = +fwd / band.
    R = fwd / band
    setups = [{"risk_pct": band * 100.0} for _ in range(n)]
    netR = S.net_of_slippage(R, setups=setups)

    mean_R = float(R.mean()) if n else 0.0
    net_mean = float(netR.mean()) if n else 0.0

    # CPCV lower band on NET-of-slippage R (the economic series).
    _, cpcv_lower = S.cpcv_mean_lower(netR)

    # DSR on net series, deflated for the 9-cell grid.
    _, dsr_pos = S.dsr(netR, n_trials=N_TRIALS)

    # beats base rate: conditioned FRACTIONAL fwd vs per-event base-rate mean.
    baseline = np.array([br_map[t] for t in tickers if t in br_map], dtype=float)
    edge_for_br = np.array(
        [f for t, f in zip(tickers, fwd) if t in br_map], dtype=float
    )
    br_delta, beats = S.base_rate_delta(edge_for_br, baseline)

    # regime split: ON vs OFF on net R, plus crash-day-removed.
    on_idx = [i for i, d in enumerate(dates) if day_dir.get(d) == "ON"]
    off_idx = [i for i, d in enumerate(dates) if day_dir.get(d) == "OFF"]
    nocrash_idx = [i for i, d in enumerate(dates) if d != CRASH_DAY]
    on_mean = float(netR[on_idx].mean()) if on_idx else float("nan")
    off_mean = float(netR[off_idx].mean()) if off_idx else float("nan")
    nocrash_mean = float(netR[nocrash_idx].mean()) if nocrash_idx else float("nan")
    regime_robust = bool(
        len(on_idx) > 0 and len(off_idx) > 0
        and on_mean > 0 and off_mean > 0 and nocrash_mean > 0
    )

    return {
        "band": band, "horizon": horizon, "n": n,
        "mean_R": mean_R, "net_R_slippage": net_mean,
        "cpcv_lower": cpcv_lower, "dsr_positive": bool(dsr_pos),
        "base_rate_delta": br_delta, "beats_base_rate": bool(beats),
        "regime_robust": regime_robust,
        "_on_mean": on_mean, "_off_mean": off_mean, "_nocrash_mean": nocrash_mean,
        "_netR": netR,  # for PBO matrix
        "_n_on": len(on_idx), "_n_off": len(off_idx),
    }


def main():
    con = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True)
    cur = con.cursor()
    day_dir = spy_day_direction(cur)
    print("SPY day direction:", day_dir)
    print("crash window held out:", CRASH_DAY,
          "(SPY", day_dir.get(CRASH_DAY), ")")
    print()

    cells = []
    # PBO matrix: align horizons within each band? Pre-reg: PBO over (band x horizon)
    # variants of the hypothesis -> all 9 columns. Build an aligned panel by
    # truncating each column to the common min length (events are not row-aligned
    # across cells, so PBO uses each cell's net-R series as a config column).
    netR_cols = {}

    for b in BANDS:
        for h in HORIZONS:
            col = FWD_COL[h]
            rows = cur.execute(
                f"SELECT ticker, et_date, {col} FROM gex_events_intraday "
                f"WHERE setup_type='floor' AND regime='POS' AND band=? "
                f"AND {col} IS NOT NULL",
                (b,),
            ).fetchall()
            br_map = base_rate_pool(cur, [r[0] for r in rows], BR_HORIZON[h])
            res = grade_cell(rows, b, h, br_map, day_dir)
            netR_cols[(b, h)] = res.pop("_netR")
            cells.append(res)

    # ---- PBO via CSCV over the 9 (band x horizon) config columns ----
    # Build a (T x 9) matrix by truncating to the common min length. Returns are
    # i.i.d.-ish per-setup R; CSCV ranks configs by IS vs OOS performance.
    min_len = min(len(v) for v in netR_cols.values())
    keys = [(b, h) for b in BANDS for h in HORIZONS]
    M = np.column_stack([netR_cols[k][:min_len] for k in keys])
    pbo = S.pbo_cscv(M)
    print(f"PBO (CSCV over 9 band x horizon configs, T={min_len}): {pbo}")
    print()

    # PBO is a family-level number; apply it to every cell (same overfit prob).
    print(f"{'band':8}{'hor':5}{'n':>7}{'meanR':>9}{'netR':>9}{'cpcvLo':>9}"
          f"{'dsr+':>6}{'pbo':>7}{'brDlt':>9}{'beatBR':>7}{'rgmOK':>6}{'PASS':>6}")
    out = []
    for c in cells:
        pbo_ok = (pbo is not None) and (pbo < 0.5)
        passes = bool(
            c["cpcv_lower"] > 0 and c["dsr_positive"] and pbo_ok
            and c["regime_robust"] and c["beats_base_rate"]
        )
        c["pbo"] = pbo
        c["passes"] = passes
        out.append(c)
        print(f"{c['band']:<8}{c['horizon']:<5}{c['n']:>7,}"
              f"{c['mean_R']:>+9.4f}{c['net_R_slippage']:>+9.4f}"
              f"{c['cpcv_lower']:>+9.4f}{str(c['dsr_positive']):>6}"
              f"{(pbo if pbo is not None else float('nan')):>7.3f}"
              f"{c['base_rate_delta']:>+9.5f}{str(c['beats_base_rate']):>7}"
              f"{str(c['regime_robust']):>6}{str(passes):>6}")
    print()
    print("regime-split detail (net R means):")
    for c in out:
        print(f"  b={c['band']} h={c['horizon']:>2}  ON={c['_on_mean']:+.4f} "
              f"(n={c['_n_on']})  OFF={c['_off_mean']:+.4f} (n={c['_n_off']})  "
              f"noCrash={c['_nocrash_mean']:+.4f}")
    n_pass = sum(c["passes"] for c in out)
    print(f"\nCELLS PASSING FULL PRE-REG BAR: {n_pass} / {len(out)}")
    return out


if __name__ == "__main__":
    main()
