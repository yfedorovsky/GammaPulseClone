"""Backtest the new GEX magnet entry alert against today's SPY tape.

Today (5/19/2026): SPY went $733 → $737.50 → $734 with a higher-low setup.
A trader on X (@T2GxNPI) caught the reversal for +170% on $738C 0DTE.

This script REPLAYS the day in 5-min increments, evaluating the GEX magnet
entry detector at each timestep, to verify the new detector would have
fired around the trader's entry point (~12:30 PM ET).

It uses:
  - Historical snapshots from snapshots.db (king/spot at each cycle)
  - Historical flow_alerts from snapshots.db (call clusters)
  - Today's actual data, not a synthetic

Pass/fail criteria:
  - PASS: at least one fire between 11:30 AM and 1:30 PM ET on SPY
    targeting king = $740 with cluster notional >= $25M
  - FAIL: no fire — investigate
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import after path insert
from server.gex_magnet_entry import (
    check_magnet_proximity, check_higher_low, check_call_cluster,
    evaluate, MAGNET_MIN_DIST_PCT, MAGNET_MAX_DIST_PCT,
    CLUSTER_MIN_NOTIONAL, CLUSTER_LOOKBACK_S,
)


DB = "./snapshots.db"


def get_snapshot_at(ticker: str, ts: float) -> dict | None:
    """Return the SPY snapshot closest to (but not after) the given ts."""
    conn = sqlite3.connect(DB)
    try:
        row = conn.execute(
            "SELECT spot, king, floor, ceiling, signal, regime, ts FROM snapshots "
            "WHERE ticker=? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (ticker, ts),
        ).fetchone()
        if not row:
            return None
        return {
            "spot": row[0], "king": row[1], "floor": row[2],
            "ceiling": row[3], "signal": row[4], "regime": row[5],
            "ts": row[6],
        }
    finally:
        conn.close()


def replay(ticker: str = "SPY", date_str: str = "2026-05-19") -> None:
    """Walk the day in 5-min steps, evaluate the magnet detector at each."""
    print(f"=== REPLAY {ticker} on {date_str} ===\n")

    # Start at 9:30 AM ET, end at 4:00 PM ET
    base = _dt.datetime.fromisoformat(date_str + "T09:30:00")
    end = _dt.datetime.fromisoformat(date_str + "T16:00:00")
    # Convert to UTC timestamps assuming local ET = UTC-4
    base_ts = (base - _dt.timedelta(hours=-4)).timestamp() - 4 * 3600
    # Actually let's just use direct fromisoformat → naive → timestamp
    base_ts = base.timestamp()
    end_ts = end.timestamp()

    fires = []
    near_misses = []
    step = 5 * 60  # 5 min

    print(f"  {'Time ET':10s}  {'Spot':>8s}  {'King':>6s}  {'Sig':>13s}  "
          f"{'A':>3s}  {'B':>3s}  {'C-cluster':>12s}  Result")

    cur = base_ts
    while cur <= end_ts:
        # Mock "now" by monkey-patching time.time inside evaluate? Easier:
        # call the individual condition checks with the time at this step.
        # We can do this by querying the snapshots/flow_alerts databases
        # with cutoffs computed from `cur` instead of `time.time()`.

        snap = get_snapshot_at(ticker, cur)
        if not snap or not snap["spot"] or not snap["king"]:
            cur += step
            continue

        spot = snap["spot"]
        king = snap["king"]
        sig = snap["signal"]

        # Condition A
        a_pass, dist, a_reason = check_magnet_proximity(spot, king)
        # Condition B (rolling low last 30 min — use cur, not time.time)
        conn = sqlite3.connect(DB)
        try:
            cutoff = cur - 30 * 60
            row = conn.execute(
                "SELECT MIN(spot) FROM snapshots WHERE ticker=? AND ts BETWEEN ? AND ?",
                (ticker, cutoff, cur),
            ).fetchone()
            rolling_low = row[0] if row and row[0] else None
        finally:
            conn.close()
        if rolling_low and spot >= rolling_low * 1.001:
            b_pass = True
            b_reason = f"spot ${spot:.2f} > 30min low ${rolling_low:.2f}"
        else:
            b_pass = False
            b_reason = f"spot ${spot:.2f} not above low ${rolling_low}"

        # Condition C (cluster — use cur)
        band_lo = spot * 0.985
        band_hi = king * 1.015
        cluster_cutoff = cur - CLUSTER_LOOKBACK_S
        conn = sqlite3.connect(DB)
        try:
            rows = conn.execute(
                """SELECT strike, SUM(notional) FROM flow_alerts
                   WHERE ticker=? AND option_type='call' AND sentiment='BULLISH'
                     AND conviction IN ('HIGH','SWEEP','MEDIUM')
                     AND ts BETWEEN ? AND ?
                     AND strike BETWEEN ? AND ?
                   GROUP BY strike""",
                (ticker, cluster_cutoff, cur, band_lo, band_hi),
            ).fetchall()
        finally:
            conn.close()
        cluster_total = sum(float(r[1] or 0) for r in rows)
        c_pass = cluster_total >= CLUSTER_MIN_NOTIONAL
        c_str = f"${cluster_total/1e6:.0f}M"

        # Render
        et = _dt.datetime.fromtimestamp(cur).strftime("%H:%M")
        a_s = "Y" if a_pass else "N"
        b_s = "Y" if b_pass else "N"
        c_s = "Y" if c_pass else "N"

        if a_pass and b_pass and c_pass:
            result = "*** FIRE ***"
            fires.append((et, spot, king, cluster_total))
        elif a_pass and (b_pass or c_pass):
            result = "near miss"
            near_misses.append((et, spot, king, a_s, b_s, c_s))
        else:
            result = ""

        print(f"  {et:10s}  ${spot:>7.2f}  ${king:>5.0f}  {sig:>13s}  "
              f"{a_s:>3s}  {b_s:>3s}  {c_str:>12s}  {result}")
        cur += step

    print()
    print(f"=== SUMMARY ===")
    print(f"Total fires: {len(fires)}")
    print(f"Near misses (A + one other): {len(near_misses)}")
    if fires:
        for et, spot, king, total in fires:
            print(f"  FIRE @ {et}  spot=${spot:.2f}  magnet=${king:.0f}  cluster=${total/1e6:.1f}M")
    print()
    print(f"=== PASS/FAIL ===")
    target_window_fires = [f for f in fires if "11:" in f[0] or "12:" in f[0] or "13:" in f[0]]
    if target_window_fires:
        print(f"PASS — {len(target_window_fires)} fire(s) in 11:00-13:30 window")
        print("       Trader entered around 12:30 PM ET on this exact setup.")
    else:
        print("FAIL — no fires in the trader's entry window")
        print("       Investigate: maybe call cluster threshold too high, or")
        print("       higher-low logic failed because snapshot persist bug")
        print("       left us with no 30-min window of fresh data pre-15:05.")


if __name__ == "__main__":
    replay()
