"""Verify the four numerical claims in T6 of the MU thread against
snapshots.db::flow_alerts. Prints a one-line PASS/FAIL per claim with
the actual value. Run before posting.

Claims under test:
  T6.1: $348M+ ASK BULLISH flow on the 700C 5/15 in 90 minutes
  T6.2: $8.89M sweep at 9:46 AM on the 750C 1/15/27
  T6.3: OI hit 3.1M contracts (whole MU chain), 100th pctile 52-wk
  T6.4: $14.5B notional / 34x 30-day avg (stock volume — NOT in flow_alerts)

Usage:
  python scripts/verify_t6_numbers.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "snapshots.db"

# Eastern time helpers (May = EDT = UTC-4)
ET = timezone(timedelta(hours=-4))


def to_unix(dt_str: str) -> int:
    """'2026-05-08 09:30' ET -> unix seconds."""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return int(dt.timestamp())


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%H:%M:%S ET")


def main() -> int:
    if not DB.exists():
        sys.exit(f"missing: {DB}")
    con = sqlite3.connect(str(DB))
    cur = con.cursor()

    print("=" * 70)
    print("T6 VERIFICATION — MU thread, 5/8/26")
    print("=" * 70)

    # ------------------------------------------------------------------
    # T6.1: $348M+ ASK BULLISH on 700C 5/15 in 90 minutes
    # ------------------------------------------------------------------
    # Find the densest 90-min ASK-BULLISH window on the 700C 5/15
    print("\n[T6.1] $348M+ ASK BULLISH flow on 700C 5/15 in 90 min")
    cur.execute(
        """
        SELECT ts, notional, side, sentiment, volume, last_price
        FROM flow_alerts
        WHERE ticker='MU' AND strike=700 AND expiration='2026-05-15'
              AND option_type='C' AND ts >= ? AND ts < ?
        ORDER BY ts
        """,
        (to_unix("2026-05-08 09:30"), to_unix("2026-05-08 16:15")),
    )
    rows = cur.fetchall()
    print(f"  total 700C 5/15 alert rows: {len(rows)}")
    ask_bull = [r for r in rows if (r[2] or "").upper() == "ASK"
                and (r[3] or "").upper().startswith("BULL")]
    print(f"  ASK + BULLISH rows: {len(ask_bull)}")
    if ask_bull:
        # Find the densest 90-min window by sliding
        ts_arr = [r[0] for r in ask_bull]
        not_arr = [r[1] or 0 for r in ask_bull]
        best_sum, best_start = 0, None
        for i, t0 in enumerate(ts_arr):
            t1 = t0 + 90 * 60
            window_sum = sum(n for t, n in zip(ts_arr, not_arr) if t0 <= t < t1)
            if window_sum > best_sum:
                best_sum, best_start = window_sum, t0
        print(f"  densest 90-min ASK BULLISH window:")
        print(f"    starts {fmt_ts(best_start)} -> {fmt_ts(best_start + 5400)}")
        print(f"    cumulative notional: ${best_sum/1e6:,.1f}M")
        claim_pass = best_sum >= 348_000_000
        print(f"  CLAIM ($348M+): {'PASS' if claim_pass else 'FAIL'}")
    else:
        print("  no ASK BULLISH rows found on 700C 5/15 — claim NOT VERIFIABLE here")

    # ------------------------------------------------------------------
    # T6.2: $8.89M sweep at 9:46am on 750C 1/15/27
    # ------------------------------------------------------------------
    print("\n[T6.2] $8.89M sweep at 9:46 AM on 750C 1/15/27")
    cur.execute(
        """
        SELECT ts, sweep_notional, sweep_contracts, sweep_side,
               last_price, sentiment, side
        FROM flow_alerts
        WHERE ticker='MU' AND strike=750 AND expiration='2027-01-15'
              AND option_type='C' AND is_sweep=1
              AND ts >= ? AND ts < ?
        ORDER BY ts
        """,
        (to_unix("2026-05-08 09:30"), to_unix("2026-05-08 16:15")),
    )
    rows = cur.fetchall()
    print(f"  750C 1/15/27 sweep rows: {len(rows)}")
    for ts, notl, ctr, side_sw, lp, sent, side in rows[:10]:
        print(f"    {fmt_ts(ts)}  ${(notl or 0)/1e6:.2f}M  "
              f"{ctr or 0} contracts  side={side_sw}  sent={sent}")
    if rows:
        # Look for the closest match to ~9:46 AM and ~$8.89M
        target_ts = to_unix("2026-05-08 09:46")
        best = min(rows, key=lambda r: (abs(r[0] - target_ts), abs((r[1] or 0) - 8_890_000)))
        print(f"  closest match: {fmt_ts(best[0])}  ${(best[1] or 0)/1e6:.2f}M")
    else:
        print("  no sweep rows found on 750C 1/15/27 — try wider strike search")
        cur.execute(
            """
            SELECT strike, expiration, ts, sweep_notional
            FROM flow_alerts
            WHERE ticker='MU' AND option_type='C' AND is_sweep=1
                  AND ts BETWEEN ? AND ?
                  AND sweep_notional > 5e6
            ORDER BY sweep_notional DESC LIMIT 10
            """,
            (to_unix("2026-05-08 09:30"), to_unix("2026-05-08 10:30")),
        )
        for k, e, t, n in cur.fetchall():
            print(f"    strike={k} exp={e} ts={fmt_ts(t)} ${(n or 0)/1e6:.2f}M")

    # ------------------------------------------------------------------
    # T6.3: OI hit 3.1M contracts (whole MU chain)
    # ------------------------------------------------------------------
    # flow_alerts records per-contract OI at alert time. Sum distinct
    # (strike,expiration,option_type) latest OI snapshot for the day.
    print("\n[T6.3] OI 3.1M contracts (whole MU chain, end of 5/8)")
    cur.execute(
        """
        SELECT SUM(latest_oi) FROM (
          SELECT strike, expiration, option_type,
                 (SELECT oi FROM flow_alerts f2
                   WHERE f2.ticker='MU' AND f2.strike=f1.strike
                     AND f2.expiration=f1.expiration
                     AND f2.option_type=f1.option_type
                     AND f2.ts >= ? AND f2.ts < ?
                   ORDER BY f2.ts DESC LIMIT 1) AS latest_oi
          FROM flow_alerts f1
          WHERE f1.ticker='MU' AND f1.ts >= ? AND f1.ts < ?
          GROUP BY f1.strike, f1.expiration, f1.option_type
        )
        """,
        (to_unix("2026-05-08 09:30"), to_unix("2026-05-08 16:15"),
         to_unix("2026-05-08 09:30"), to_unix("2026-05-08 16:15")),
    )
    total_oi = cur.fetchone()[0] or 0
    print(f"  sum of latest-snapshot OI across MU chain: {total_oi:,}")
    print(f"  note: this is OI we OBSERVED (only contracts that triggered "
          f">=1 alert).")
    print(f"  true total OI requires the full chain — query thetadata or "
          f"market_chameleon for the 3.1M figure.")

    # ------------------------------------------------------------------
    # T6.4: $14.5B notional / 34x 30-day avg (stock volume)
    # ------------------------------------------------------------------
    print("\n[T6.4] $14.5B notional / 34x avg")
    print("  flow_alerts is options-only. Stock $14.5B notional / 34x avg")
    print("  must come from your equities feed (Databento, Tradier, etc.)")
    print("  Skip — cite this from your original source.")

    print("\n" + "=" * 70)
    print("Done. Pre-post checklist for T6:")
    print("  - confirm T6.1 number (densest 90-min window above)")
    print("  - confirm T6.2 row above matches the $8.89M / 9:46am claim")
    print("  - replace T6.3 OI '3.1M' with whatever your source said, or pull "
          "full chain from thetadata snapshot")
    print("  - keep T6.4 cite-as-is, source not in this DB")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
