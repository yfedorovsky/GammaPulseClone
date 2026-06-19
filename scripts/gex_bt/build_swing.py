"""BUILD-S (Track S): consistent EOD GEX structure from chains.db.

Pre-registered under docs/research/GEX_BACKTEST_PREREG.md (Direction A, H5).
We recompute king/floor/ceiling/net-gamma with FIXED logic across every
(date, root) in chains.db::option_eod, so the GEX *structure* signal is
consistent over the full regime-diverse 2026 YTD history.

Mechanics (fixed; do not retune):
  - Pre-filter near-money strikes  abs(strike/spot - 1) <= 0.15  BEFORE any BSM.
    Vectorized with numpy; processed root-by-root to bound memory. No 25M-row loop.
  - T = max((expiration - date) in days, 0) / 365, floored at 0.5/365.
  - per-strike net_gex = sum over calls+puts+ALL expirations of
        gamma * oi * 100 * spot * spot * 0.01      (calls +, puts -)
    using the same BSM gamma as server/gex.py (_bsm_gamma) and the same
    GEX convention (CONTRACT_SIZE=100, *spot^2*0.01).
  - king    = strike of max POSITIVE net_gex
  - floor   = strike of max POSITIVE net_gex strictly BELOW spot
  - ceiling = strike of max POSITIVE net_gex strictly ABOVE spot
  - net_gamma = sum(net_gex)  (over the near-money strikes)
  - regime  = POS if net_gamma > 0 else NEG
  - forward returns from the NEXT AVAILABLE trading date for THAT root
    (not calendar+1):  fwd_ret_1d, fwd_ret_3d  (close-to-close via spot).

Output: gex_backtest/work.db::gex_struct_eod
  (date, root, spot, king, floor, ceiling, net_gamma, regime,
   dist_king_pct, dist_floor_pct, dist_ceil_pct, fwd_ret_1d, fwd_ret_3d)

READ-ONLY on chains.db (opened via file:...?mode=ro&uri=True). Writes only work.db.
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
import time

import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────
REPO = r"C:\Dev\GammaPulse"
CHAINS_DB = os.path.join(
    REPO,
    ".claude", "worktrees", "feature+autoresearch-loop", "autoresearch",
    "_artifacts", "hist_chains", "chains.db",
)
WORK_DB = os.path.join(REPO, "gex_backtest", "work.db")

# ── Fixed constants (match server/gex.py convention) ─────────────────────
CONTRACT_SIZE = 100
NEAR_MONEY_BAND = 0.15          # abs(strike/spot - 1) <= 0.15 pre-filter
T_FLOOR_YEARS = 0.5 / 365.0     # BUILD-S spec: T floored at half a day
R = 0.045                       # risk-free, matches _bsm_gamma default
Q = 0.013                       # dividend yield, matches _bsm_gamma default
SQRT_2PI = math.sqrt(2.0 * math.pi)


def _bsm_gamma_vec(S, K, sigma, T, r=R, q=Q):
    """Vectorized BSM gamma — numerically identical to server/gex.py _bsm_gamma.

    S: spot (scalar broadcast), K: strikes array, sigma: iv array, T: years array.
    Returns 0 where any input is non-positive (matches the scalar guard).
    """
    S = np.asarray(S, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)
    T = np.asarray(T, dtype=np.float64)

    valid = (S > 0) & (K > 0) & (sigma > 0) & (T > 0)
    out = np.zeros(np.broadcast(S, K, sigma, T).shape, dtype=np.float64)
    if not valid.any():
        return out

    # Compute only on valid entries to avoid log/div warnings.
    Sv = np.broadcast_to(S, out.shape)[valid]
    Kv = K[valid] if K.shape == out.shape else np.broadcast_to(K, out.shape)[valid]
    sv = sigma[valid] if sigma.shape == out.shape else np.broadcast_to(sigma, out.shape)[valid]
    Tv = T[valid] if T.shape == out.shape else np.broadcast_to(T, out.shape)[valid]

    sqrt_T = np.sqrt(Tv)
    d1 = (np.log(Sv / Kv) + (r - q + 0.5 * sv * sv) * Tv) / (sv * sqrt_T)
    pdf = np.exp(-0.5 * d1 * d1) / SQRT_2PI
    out[valid] = pdf * np.exp(-q * Tv) / (Sv * sv * sqrt_T)
    return out


def _days_between(date_str: str, exp_str: str) -> int:
    """Calendar days expiration - date, floored at 0."""
    from datetime import date as _date
    d = _date.fromisoformat(date_str)
    e = _date.fromisoformat(exp_str)
    return max((e - d).days, 0)


def build():
    t0 = time.time()
    if not os.path.exists(CHAINS_DB):
        print(f"FATAL: chains.db not found at {CHAINS_DB}", file=sys.stderr)
        sys.exit(1)

    ro_uri = f"file:{CHAINS_DB}?mode=ro"
    src = sqlite3.connect(ro_uri, uri=True)
    src.row_factory = None
    cur = src.cursor()

    roots = [r[0] for r in cur.execute(
        "SELECT DISTINCT root FROM option_eod ORDER BY root"
    )]
    print(f"roots to process: {len(roots)}")

    # ── Prepare output DB (fresh) ────────────────────────────────────────
    # Build into a tmp DB then swap, so a transient file handle on WORK_DB
    # (AV scan, prior reader) can't abort the whole run at os.remove time.
    tmp_db = WORK_DB + ".building"
    for p in (tmp_db, tmp_db + "-journal"):
        if os.path.exists(p):
            os.remove(p)
    out = sqlite3.connect(tmp_db)
    out.execute("""
        CREATE TABLE gex_struct_eod (
            date          TEXT NOT NULL,
            root          TEXT NOT NULL,
            spot          REAL,
            king          REAL,
            floor         REAL,
            ceiling       REAL,
            net_gamma     REAL,
            regime        TEXT,
            dist_king_pct  REAL,
            dist_floor_pct REAL,
            dist_ceil_pct  REAL,
            fwd_ret_1d    REAL,
            fwd_ret_3d    REAL,
            PRIMARY KEY (date, root)
        )
    """)

    total_rows = 0
    for ri, root in enumerate(roots):
        # Pull the whole root once (one root = a few hundred K rows max).
        rows = cur.execute(
            "SELECT date, expiration, strike, right, iv, spot, oi "
            "FROM option_eod WHERE root=? ",
            (root,),
        ).fetchall()
        if not rows:
            continue

        arr_date = np.array([r[0] for r in rows], dtype=object)
        arr_exp = np.array([r[1] for r in rows], dtype=object)
        arr_strike = np.array([r[2] for r in rows], dtype=np.float64)
        arr_right = np.array([r[3] for r in rows], dtype=object)
        arr_iv = np.array([np.nan if r[4] is None else r[4] for r in rows], dtype=np.float64)
        arr_spot = np.array([np.nan if r[5] is None else r[5] for r in rows], dtype=np.float64)
        arr_oi = np.array([0.0 if r[6] is None else r[6] for r in rows], dtype=np.float64)

        # Per-date spot (constant within date+root). Build ordered date list.
        uniq_dates = sorted(set(arr_date.tolist()))

        # First pass: compute structure per date, collect into dicts keyed by date.
        struct = {}   # date -> (spot, king, floor, ceiling, net_gamma, regime)
        for d in uniq_dates:
            dmask = (arr_date == d)
            spot_vals = arr_spot[dmask]
            # spot constant within group; take first finite value
            finite_spot = spot_vals[np.isfinite(spot_vals) & (spot_vals > 0)]
            if finite_spot.size == 0:
                continue
            spot = float(finite_spot[0])

            K = arr_strike[dmask]
            iv = arr_iv[dmask]
            oi = arr_oi[dmask]
            right = arr_right[dmask]
            exp = arr_exp[dmask]

            # Near-money pre-filter BEFORE any BSM.
            nm = np.abs(K / spot - 1.0) <= NEAR_MONEY_BAND
            # Also require usable inputs for the gamma calc.
            usable = nm & np.isfinite(iv) & (iv > 0) & (oi > 0) & (K > 0)
            if not usable.any():
                continue
            K = K[usable]; iv = iv[usable]; oi = oi[usable]
            right = right[usable]; exp = exp[usable]

            # T = max(days,0)/365 floored at 0.5/365.
            T = np.array(
                [max(_days_between(d, e) / 365.0, T_FLOOR_YEARS) for e in exp],
                dtype=np.float64,
            )

            gamma = _bsm_gamma_vec(spot, K, iv, T)
            sign = np.where(right == "C", 1.0, -1.0)
            gex = gamma * oi * CONTRACT_SIZE * spot * spot * 0.01 * sign

            # Aggregate per strike across calls+puts+ALL expirations.
            uK, inv = np.unique(K, return_inverse=True)
            per_strike = np.zeros(uK.shape, dtype=np.float64)
            np.add.at(per_strike, inv, gex)

            net_gamma = float(per_strike.sum())
            regime = "POS" if net_gamma > 0 else "NEG"

            pos_mask = per_strike > 0
            king = None
            if pos_mask.any():
                king = float(uK[pos_mask][np.argmax(per_strike[pos_mask])])

            # floor = max +net_gex strictly below spot
            below = pos_mask & (uK < spot)
            floor = float(uK[below][np.argmax(per_strike[below])]) if below.any() else None
            # ceiling = max +net_gex strictly above spot
            above = pos_mask & (uK > spot)
            ceiling = float(uK[above][np.argmax(per_strike[above])]) if above.any() else None

            struct[d] = (spot, king, floor, ceiling, net_gamma, regime)

        # Second pass: forward returns off NEXT AVAILABLE trading date for this root.
        dates_with_struct = [d for d in uniq_dates if d in struct]
        idx_of = {d: i for i, d in enumerate(dates_with_struct)}
        spot_by_date = {d: struct[d][0] for d in dates_with_struct}

        batch = []
        for d in dates_with_struct:
            spot, king, floor, ceiling, net_gamma, regime = struct[d]
            i = idx_of[d]
            # fwd_ret_1d: next available trading date's spot vs today's spot.
            fwd_1d = None
            if i + 1 < len(dates_with_struct):
                d1 = dates_with_struct[i + 1]
                fwd_1d = spot_by_date[d1] / spot - 1.0
            fwd_3d = None
            if i + 3 < len(dates_with_struct):
                d3 = dates_with_struct[i + 3]
                fwd_3d = spot_by_date[d3] / spot - 1.0

            dist_king = (king / spot - 1.0) if king else None
            dist_floor = (floor / spot - 1.0) if floor else None
            dist_ceil = (ceiling / spot - 1.0) if ceiling else None

            batch.append((
                d, root, spot, king, floor, ceiling, net_gamma, regime,
                dist_king, dist_floor, dist_ceil, fwd_1d, fwd_3d,
            ))

        if batch:
            out.executemany(
                "INSERT INTO gex_struct_eod VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            total_rows += len(batch)

        if (ri + 1) % 20 == 0 or ri == len(roots) - 1:
            out.commit()
            print(f"  [{ri+1}/{len(roots)}] {root}: cumulative rows={total_rows} "
                  f"({time.time()-t0:.1f}s)")

    out.commit()
    # Indexes for downstream grading.
    out.execute("CREATE INDEX ix_root_date ON gex_struct_eod(root, date)")
    out.execute("CREATE INDEX ix_regime ON gex_struct_eod(regime)")
    out.commit()

    # ── Report ───────────────────────────────────────────────────────────
    rc = out.execute("SELECT COUNT(*) FROM gex_struct_eod").fetchone()[0]
    dr = out.execute("SELECT MIN(date), MAX(date) FROM gex_struct_eod").fetchone()
    nr = out.execute("SELECT COUNT(DISTINCT root) FROM gex_struct_eod").fetchone()[0]
    print("\n=== BUILD-S COMPLETE ===")
    print(f"rows={rc}  date_range={dr[0]}..{dr[1]}  roots={nr}  elapsed={time.time()-t0:.1f}s")
    print("\n=== 3 sanity rows (liquid names) ===")
    for r in out.execute(
        "SELECT date,root,spot,king,floor,ceiling,ROUND(net_gamma,0),regime,"
        "ROUND(dist_king_pct,4),ROUND(fwd_ret_1d,4),ROUND(fwd_ret_3d,4) "
        "FROM gex_struct_eod "
        "WHERE root IN ('NVDA','META','AMD') AND date='2026-06-02' "
        "ORDER BY root"
    ):
        print(r)

    out.close()
    src.close()

    # Swap tmp -> final.
    for _ in range(20):
        try:
            if os.path.exists(WORK_DB):
                os.remove(WORK_DB)
            os.replace(tmp_db, WORK_DB)
            break
        except PermissionError:
            time.sleep(0.5)
    print(f"work.db -> {WORK_DB}")


if __name__ == "__main__":
    build()
