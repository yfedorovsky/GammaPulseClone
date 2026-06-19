#!/usr/bin/env python
"""BUILD-BASERATE — per-ticker UNCONDITIONAL forward-return distributions.

These are the NULLS that every conditional GEX setup (H1-H5 in
docs/research/GEX_BACKTEST_PREREG.md) must beat. Descriptive-not-tradeable is
the honest default; this script only measures the baseline drift, it asserts
no edge.

Two tracks (per the pre-registration):

  DAILY (Track S)  — from chains.db option_eod. Per root, build the ordered
      distinct (date -> spot) series and compute ALL 1-day and 3-day
      close-to-close spot returns. spot is constant within a (root,date) group
      (verified: max distinct spot per group == 1), so the daily series is the
      de-duplicated spot-by-date sequence. Horizons measured in TRADING days
      (consecutive rows in the series), matching close-to-close convention.

  INTRADAY (Track I) — from snapshots.db::snapshots, restricted to the
      STABLE king-selection-logic window (>= 2026-05-28, the first full day
      after commit c0549e3 "king-selection-v3" 2026-05-27; the later 1db72a9
      only refactored floor/ceiling search, not king selection). is_stale=1
      excluded. We sample forward spot MOVES at RANDOM snapshots (fixed seed),
      enforcing the RTH rule (09:30-16:00 ET) for BOTH the entry snapshot and
      the forward snapshot, and the SAME-DAY rule (forward must be the same ET
      session — no overnight gap). Horizons {15, 30, 60} min.

Output: gex_backtest/work.db::base_rates(ticker, horizon, n, mean, std,
        p25, p50, p75, skew). Returns stored as fractional (e.g. 0.012 = +1.2%).
Plus base_rates_meta(key, value) for the run manifest / coverage.

READ-ONLY on both source DBs (sqlite file:...?mode=ro uri=True). work.db is the
only thing written.
"""
from __future__ import annotations

import math
import os
import random
import sqlite3
import statistics
import time
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = "C:/Dev/GammaPulse"
CHAINS_DB = (
    ROOT
    + "/.claude/worktrees/feature+autoresearch-loop/autoresearch/"
    + "_artifacts/hist_chains/chains.db"
)
SNAPSHOTS_DB = ROOT + "/snapshots.db"   # the LIVE 4.65GB recorder (read-only)
WORK_DB = ROOT + "/gex_backtest/work.db"

# ---------------------------------------------------------------------------
# Stable-window + RTH constants
# ---------------------------------------------------------------------------
# First full ET day after king-selection-v3 (commit c0549e3, 2026-05-27).
STABLE_START_ET = datetime(2026, 5, 28, 0, 0, 0)
# This window is EDT (UTC-4) throughout (late-May..mid-Jun 2026). Use a fixed
# -4h offset to map ET<->UTC; the snapshots ts column is Unix seconds (UTC).
ET_OFFSET_SEC = -4 * 3600
RTH_OPEN_SEC = int(9.5 * 3600)    # 09:30 ET, seconds since ET-midnight
RTH_CLOSE_SEC = int(16 * 3600)    # 16:00 ET

HORIZONS_MIN = (15, 30, 60)
# Tolerance for matching a forward snapshot to the target time (ts + H).
# Cadence is ~6-7 min/ticker in RTH, so a ~4-5 min half-window reliably finds a
# neighbor without drifting far off the requested horizon.
TOL_SEC = {15: 240, 30: 300, 60: 360}

SEED = 20260616          # fixed for reproducibility
MAX_SAMPLES_PER_TICKER = 1500   # cap intraday sampling per ticker (plenty for a null)


def _utc(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


STABLE_START_UTC = _utc(STABLE_START_ET) - ET_OFFSET_SEC  # ET-midnight in UTC secs


# ---------------------------------------------------------------------------
# Distribution helper
# ---------------------------------------------------------------------------
def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _skew(vals, mean, std):
    n = len(vals)
    if n < 3 or std == 0:
        return 0.0
    m3 = sum((v - mean) ** 3 for v in vals) / n
    return m3 / (std ** 3)


def _dist(vals):
    """Return (n, mean, std, p25, p50, p75, skew) for a list of returns."""
    n = len(vals)
    if n == 0:
        return (0, None, None, None, None, None, None)
    mean = statistics.fmean(vals)
    std = statistics.pstdev(vals) if n > 1 else 0.0
    sv = sorted(vals)
    return (
        n,
        mean,
        std,
        _quantile(sv, 0.25),
        _quantile(sv, 0.50),
        _quantile(sv, 0.75),
        _skew(vals, mean, std),
    )


# ---------------------------------------------------------------------------
# DAILY (Track S)
# ---------------------------------------------------------------------------
def build_daily(work: sqlite3.Connection) -> dict:
    con = sqlite3.connect(f"file:{CHAINS_DB}?mode=ro", uri=True)
    cur = con.cursor()
    roots = [r[0] for r in cur.execute("SELECT DISTINCT root FROM option_eod ORDER BY root")]
    rows_out = []
    coverage = {"roots_total": len(roots), "roots_with_1d": 0, "roots_with_3d": 0,
                "total_1d_obs": 0, "total_3d_obs": 0}
    for rt in roots:
        # distinct (date -> spot); spot constant within (root,date) [verified].
        series = cur.execute(
            "SELECT date, AVG(spot) FROM option_eod WHERE root=? AND spot IS NOT NULL "
            "AND spot>0 GROUP BY date ORDER BY date", (rt,)
        ).fetchall()
        spots = [s for _, s in series]
        # 1-day close-to-close
        r1 = [spots[i + 1] / spots[i] - 1.0 for i in range(len(spots) - 1)
              if spots[i] > 0]
        # 3-day close-to-close
        r3 = [spots[i + 3] / spots[i] - 1.0 for i in range(len(spots) - 3)
              if spots[i] > 0]
        for horizon, vals in (("1d", r1), ("3d", r3)):
            d = _dist(vals)
            rows_out.append((rt, horizon) + d)
        if r1:
            coverage["roots_with_1d"] += 1
            coverage["total_1d_obs"] += len(r1)
        if r3:
            coverage["roots_with_3d"] += 1
            coverage["total_3d_obs"] += len(r3)
    con.close()
    work.executemany(
        "INSERT INTO base_rates(ticker,horizon,n,mean,std,p25,p50,p75,skew) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows_out
    )
    work.commit()
    return coverage


# ---------------------------------------------------------------------------
# INTRADAY (Track I)
# ---------------------------------------------------------------------------
def _et_seconds_of_day(ts_utc: int) -> int:
    """Seconds since ET-midnight for a UTC unix-second ts (fixed EDT offset)."""
    return (ts_utc + ET_OFFSET_SEC) % 86400


def _et_day_index(ts_utc: int) -> int:
    return (ts_utc + ET_OFFSET_SEC) // 86400


# ET day index 0 == 1970-01-01 (a Thursday, weekday()==3). Use that to derive
# weekday and reject weekends — the recorder logs is_stale=0 quotes on Sat/Sun
# (replayed/last-known), which are NOT real sessions and must not enter the
# intraday null. No US market holiday falls in the 2026-05-28..2026-06-16
# window (next is Juneteenth 2026-06-19, outside it), so a weekday filter
# suffices. If the window is ever extended, add an explicit holiday set here.
_EPOCH_WEEKDAY = 3  # 1970-01-01 was Thursday


def _is_weekend_et(day_index: int) -> bool:
    wd = (day_index + _EPOCH_WEEKDAY) % 7  # 0=Mon .. 6=Sun
    return wd >= 5


def build_intraday(work: sqlite3.Connection) -> dict:
    con = sqlite3.connect(f"file:{SNAPSHOTS_DB}?mode=ro", uri=True)
    cur = con.cursor()
    rng = random.Random(SEED)

    tickers = [r[0] for r in cur.execute(
        "SELECT DISTINCT ticker FROM snapshots WHERE is_stale=0 AND ts>=?",
        (STABLE_START_UTC,)
    )]

    rows_out = []
    coverage = {"tickers_total": len(tickers),
                "stable_start_utc": STABLE_START_UTC,
                "stable_start_et": STABLE_START_ET.isoformat()}
    per_h_obs = {h: 0 for h in HORIZONS_MIN}
    tickers_with = {h: 0 for h in HORIZONS_MIN}
    rth_days = set()

    for tk in tickers:
        # Pull all RTH, non-stale snapshots in the stable window for this ticker.
        # Filter RTH in SQL via ET-second-of-day on the fixed offset.
        recs = cur.execute(
            "SELECT ts, spot FROM snapshots WHERE ticker=? AND is_stale=0 AND ts>=? "
            "AND spot IS NOT NULL AND spot>0 ORDER BY ts", (tk, STABLE_START_UTC)
        ).fetchall()
        # Keep only RTH rows; bucket by ET day for the same-session forward rule.
        by_day: dict[int, list[tuple[int, float]]] = {}
        for ts, spot in recs:
            sod = _et_seconds_of_day(ts)
            if RTH_OPEN_SEC <= sod <= RTH_CLOSE_SEC:
                day = _et_day_index(ts)
                if _is_weekend_et(day):
                    continue  # reject Sat/Sun stale-quote leakage
                by_day.setdefault(day, []).append((ts, spot))
                rth_days.add(day)

        # Build per-horizon return samples for this ticker.
        h_vals = {h: [] for h in HORIZONS_MIN}
        # Flatten all candidate entry snapshots (those with room for at least
        # the smallest horizon left before close in their session).
        entries = []  # (day, idx)
        for day, arr in by_day.items():
            arr.sort()
            for i, (ts, _sp) in enumerate(arr):
                entries.append((day, i))
        if not entries:
            for h in HORIZONS_MIN:
                rows_out.append((tk, f"{h}min") + _dist([]))
            continue
        # RANDOM sampling without replacement, capped.
        rng.shuffle(entries)
        if len(entries) > MAX_SAMPLES_PER_TICKER:
            entries = entries[:MAX_SAMPLES_PER_TICKER]

        for day, i in entries:
            arr = by_day[day]
            ts0, sp0 = arr[i]
            for h in HORIZONS_MIN:
                target = ts0 + h * 60
                # forward snapshot must be SAME ET session (same `day` bucket)
                # AND within the RTH close, AND within tolerance of target.
                tol = TOL_SEC[h]
                # binary-ish forward scan from i+1 (arr is sorted by ts)
                best = None
                best_dt = None
                for j in range(i + 1, len(arr)):
                    tsj, spj = arr[j]
                    dt = tsj - target
                    if tsj > target + tol:
                        break
                    if abs(dt) <= tol:
                        if best is None or abs(dt) < abs(best_dt):
                            best, best_dt = (tsj, spj), dt
                if best is not None:
                    spj = best[1]
                    if sp0 > 0:
                        h_vals[h].append(spj / sp0 - 1.0)

        for h in HORIZONS_MIN:
            vals = h_vals[h]
            rows_out.append((tk, f"{h}min") + _dist(vals))
            if vals:
                per_h_obs[h] += len(vals)
                tickers_with[h] += 1

    con.close()
    work.executemany(
        "INSERT INTO base_rates(ticker,horizon,n,mean,std,p25,p50,p75,skew) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows_out
    )
    work.commit()
    coverage["rth_trading_days"] = len(rth_days)
    for h in HORIZONS_MIN:
        coverage[f"obs_{h}min"] = per_h_obs[h]
        coverage[f"tickers_with_{h}min"] = tickers_with[h]
    return coverage


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(os.path.dirname(WORK_DB), exist_ok=True)
    # WAL + busy_timeout so we coexist with sibling agents writing OTHER tables
    # (e.g. gex_struct_eod) in the same work.db without clobbering each other.
    # We only ever touch our own two tables (base_rates, base_rates_meta).
    work = sqlite3.connect(WORK_DB, timeout=60)
    work.execute("PRAGMA journal_mode=WAL")
    work.execute("PRAGMA busy_timeout=60000")
    work.execute("DROP TABLE IF EXISTS base_rates")
    work.execute(
        "CREATE TABLE base_rates ("
        "ticker TEXT, horizon TEXT, n INTEGER, mean REAL, std REAL, "
        "p25 REAL, p50 REAL, p75 REAL, skew REAL, "
        "PRIMARY KEY (ticker, horizon))"
    )
    work.execute("DROP TABLE IF EXISTS base_rates_meta")
    work.execute("CREATE TABLE base_rates_meta (key TEXT PRIMARY KEY, value TEXT)")

    t0 = time.time()
    print("[daily] building Track S from chains.db ...", flush=True)
    cov_d = build_daily(work)
    print(f"[daily] done: {cov_d}", flush=True)

    print("[intraday] building Track I from snapshots.db stable window ...", flush=True)
    cov_i = build_intraday(work)
    print(f"[intraday] done: {cov_i}", flush=True)

    meta = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "seed": str(SEED),
        "chains_db": CHAINS_DB,
        "snapshots_db": SNAPSHOTS_DB,
        "stable_window_commit": "c0549e3 (king-selection-v3, 2026-05-27)",
        "stable_start_et": STABLE_START_ET.isoformat(),
        "horizons_intraday_min": ",".join(map(str, HORIZONS_MIN)),
        "horizons_daily": "1d,3d",
        "rth_et": "09:30-16:00",
        "et_offset": "UTC-4 (EDT, fixed)",
        "weekend_excluded": "yes (Sat/Sun is_stale=0 leakage dropped; no holiday in window)",
        "max_samples_per_ticker": str(MAX_SAMPLES_PER_TICKER),
    }
    meta.update({f"daily_{k}": str(v) for k, v in cov_d.items()})
    meta.update({f"intraday_{k}": str(v) for k, v in cov_i.items()})
    work.executemany("INSERT INTO base_rates_meta(key,value) VALUES (?,?)",
                     list(meta.items()))
    work.commit()

    # Final coverage report
    n_rows = work.execute("SELECT COUNT(*) FROM base_rates").fetchone()[0]
    n_daily = work.execute(
        "SELECT COUNT(*) FROM base_rates WHERE horizon IN ('1d','3d') AND n>0"
    ).fetchone()[0]
    n_intra = work.execute(
        "SELECT COUNT(*) FROM base_rates WHERE horizon LIKE '%min' AND n>0"
    ).fetchone()[0]
    print(f"\nbase_rates rows: {n_rows} (daily non-empty cells {n_daily}, "
          f"intraday non-empty cells {n_intra}) in {time.time()-t0:.1f}s")
    work.close()


if __name__ == "__main__":
    main()
