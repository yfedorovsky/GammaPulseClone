"""Track I (BUILD-I) — extract intraday GEX-structure SETUP events from the
stable-logic snapshot window and attach same-day forward moves.

Reads gex_backtest/work.db::snap_window (built by copy_snap_window.py) and
writes gex_backtest/work.db::gex_events_intraday.

Pre-reg (docs/research/GEX_BACKTEST_PREREG.md) fixed parameters — DO NOT TUNE:
  bands b ∈ {0.0015, 0.0030, 0.0050}   (0.15% / 0.30% / 0.50% of spot)
  horizons H ∈ {15, 30, 60} minutes
  forward = nearest snapshot to ts+H, SAME trading day only, ±3 min tolerance.

Setup definitions (per snapshot, per band):
  dist_king  = (spot - king)    / spot
  dist_floor = (spot - floor)   / spot
  dist_ceil  = (spot - ceiling) / spot
  pin     when abs(dist_king)  <= b
  floor   when 0 <= dist_floor <= b   (spot at/above floor, within b)
  ceiling when -b <= dist_ceil <= 0   (spot at/below ceiling, within b)

Scope decisions (honest, pre-named confounds):
  * RTH only: ET time in [09:30:00, 16:00:00].
  * Weekdays only (Mon-Fri). Sat/Sun rows in snapshots are weekend recordings,
    not tradeable sessions — excluded.
  * No overnight: forward search is restricted to the same (ticker, et_date).
  * floor/ceiling setups require a real level: floor>0 / ceiling>0. (floor==0
    is the legacy "no floor" serialization; spot is never ~0 so the band test
    would almost never trigger anyway, but we guard explicitly.)
  * dist_pct recorded = the signed distance that DEFINES the setup
    (dist_king for pin, dist_floor for floor, dist_ceil for ceiling).
"""
import sqlite3
import bisect

WORK = r"C:\Dev\GammaPulse\gex_backtest\work.db"

BANDS = [0.0015, 0.0030, 0.0050]
HORIZONS = [15, 30, 60]          # minutes
TOL = 3 * 60                     # +/- 3 minute tolerance, in seconds
RTH_LO = "09:30:00"
RTH_HI = "16:00:00"
WEEKDAY = set(range(0, 5))       # Mon..Fri (date.weekday(): Mon=0)


def _nearest_fwd(ts_list, spot_list, i, target):
    """Return spot at the snapshot nearest to `target` ts within TOL, or None.

    ts_list is the ascending per-(ticker,date) timestamp list; i is the index of
    the current snapshot (search forward only). Picks the row whose |ts-target|
    is minimal and <= TOL.
    """
    n = len(ts_list)
    # bisect for insertion point of target
    lo = bisect.bisect_left(ts_list, target, i, n)
    best_idx = None
    best_d = None
    for j in (lo - 1, lo):
        if j <= i or j >= n:
            continue
        d = abs(ts_list[j] - target)
        if d <= TOL and (best_d is None or d < best_d):
            best_d = d
            best_idx = j
    if best_idx is None:
        return None
    return spot_list[best_idx]


def main() -> None:
    con = sqlite3.connect(WORK)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS gex_events_intraday")
    cur.execute(
        """
        CREATE TABLE gex_events_intraday (
            ticker     TEXT NOT NULL,
            ts         INTEGER NOT NULL,
            et_date    TEXT NOT NULL,
            setup_type TEXT NOT NULL,   -- pin | floor | ceiling
            band       REAL NOT NULL,
            regime     TEXT,
            dist_pct   REAL,            -- signed distance that defines the setup
            fwd_15     REAL,
            fwd_30     REAL,
            fwd_60     REAL
        )
        """
    )

    import datetime as _dt

    # Pull weekday RTH rows ordered for streaming by (ticker, et_date, ts).
    cur.execute(
        """
        SELECT ticker, et_date, ts, et_hms, spot, king, floor, ceiling, regime
        FROM snap_window
        WHERE et_hms >= ? AND et_hms <= ?
        ORDER BY ticker, et_date, ts
        """,
        (RTH_LO, RTH_HI),
    )

    out = []
    cur_key = None
    rows = []  # buffered rows for current (ticker, et_date)

    def flush(key, group):
        if not key:
            return
        ticker, et_date = key
        # weekday gate
        if _dt.date.fromisoformat(et_date).weekday() not in WEEKDAY:
            return
        ts_list = [r[0] for r in group]
        spot_list = [r[1] for r in group]
        for i, (ts, spot, king, floor, ceiling, regime) in enumerate(group):
            if not spot or spot <= 0:
                continue
            dist_king = (spot - king) / spot if king and king > 0 else None
            dist_floor = (spot - floor) / spot if floor and floor > 0 else None
            dist_ceil = (spot - ceiling) / spot if ceiling and ceiling > 0 else None

            # forward moves (compute once per snapshot, reused across setups)
            fwd = {}
            for H in HORIZONS:
                target = ts + H * 60
                sfwd = _nearest_fwd(ts_list, spot_list, i, target)
                fwd[H] = ((sfwd - spot) / spot) if (sfwd is not None) else None

            for b in BANDS:
                emitted = []  # (setup_type, dist_pct)
                if dist_king is not None and abs(dist_king) <= b:
                    emitted.append(("pin", dist_king))
                if dist_floor is not None and 0.0 <= dist_floor <= b:
                    emitted.append(("floor", dist_floor))
                if dist_ceil is not None and -b <= dist_ceil <= 0.0:
                    emitted.append(("ceiling", dist_ceil))
                for setup_type, dist_pct in emitted:
                    out.append(
                        (ticker, ts, et_date, setup_type, b, regime, dist_pct,
                         fwd[15], fwd[30], fwd[60])
                    )

        if len(out) >= 50000:
            cur.executemany(
                "INSERT INTO gex_events_intraday VALUES (?,?,?,?,?,?,?,?,?,?)", out
            )
            out.clear()

    for ticker, et_date, ts, et_hms, spot, king, floor, ceiling, regime in cur.fetchall():
        key = (ticker, et_date)
        if key != cur_key:
            flush(cur_key, rows)
            rows = []
            cur_key = key
        rows.append((ts, spot, king, floor, ceiling, regime))
    flush(cur_key, rows)

    if out:
        cur.executemany(
            "INSERT INTO gex_events_intraday VALUES (?,?,?,?,?,?,?,?,?,?)", out
        )
    cur.execute("CREATE INDEX ix_ev ON gex_events_intraday(setup_type, regime, band)")
    con.commit()

    # ---- report ----
    cur.execute("SELECT COUNT(*) FROM gex_events_intraday")
    print("total events:", f"{cur.fetchone()[0]:,}")
    cur.execute(
        "SELECT COUNT(DISTINCT et_date) FROM gex_events_intraday"
    )
    print("trading days w/ events:", cur.fetchone()[0])
    print("\ncounts by (setup_type, regime, band):")
    cur.execute(
        """
        SELECT setup_type, regime, band, COUNT(*) AS n,
               SUM(fwd_15 IS NOT NULL) AS h15,
               SUM(fwd_30 IS NOT NULL) AS h30,
               SUM(fwd_60 IS NOT NULL) AS h60
        FROM gex_events_intraday
        GROUP BY setup_type, regime, band
        ORDER BY setup_type, regime, band
        """
    )
    print(f"{'setup':8} {'reg':4} {'band':7} {'n':>8} {'fwd15':>8} {'fwd30':>8} {'fwd60':>8}")
    for st, rg, b, n, h15, h30, h60 in cur.fetchall():
        print(f"{st:8} {rg:4} {b:<7} {n:>8,} {h15:>8,} {h30:>8,} {h60:>8,}")
    con.close()


if __name__ == "__main__":
    main()
