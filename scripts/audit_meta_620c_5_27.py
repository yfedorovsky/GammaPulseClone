"""Forensic audit: META $620C 0DTE on 2026-05-27.

Reported event: someone loaded ~$16,300 on META 0DTE 620C around 2PM ET.
~5 min later META announced paid subscriptions. Contract ran to $5.1M
(~31,000% ROI in ~10 min).

Question: did our flow detector catch the entry?

Pulls:
  1. All META alerts near $620 strike between 1:30-3:00 PM ET
  2. META snapshots over the window
  3. Cluster summary for grading
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "snapshots.db"

# Window: 1:30 PM ET (17:30 UTC) through 3:00 PM ET (19:00 UTC)
# 2026-05-27 is in EDT (UTC-4)
T_START = int(datetime(2026, 5, 27, 17, 30).timestamp())
T_END = int(datetime(2026, 5, 27, 19, 0).timestamp())
STRIKE_LO = 600
STRIKE_HI = 640


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT ts, strike, option_type, conviction, sentiment,
               notional, volume, oi, vol_oi, is_sweep, expiration,
               bid, ask, spot
        FROM flow_alerts
        WHERE ticker = 'META' AND ts BETWEEN ? AND ?
          AND strike BETWEEN ? AND ?
        ORDER BY ts
        """,
        (T_START, T_END, STRIKE_LO, STRIKE_HI),
    ).fetchall()

    print(f"=== META alerts in window 1:30-3:00 PM ET, strike {STRIKE_LO}-{STRIKE_HI} ===")
    print(f"Total: {len(rows)} alerts")
    print()

    # Focus on the 620C 0DTE (exp = 2026-05-27)
    target_strike = 620.0
    target_exp = "2026-05-27"
    print(f"=== Filtered to ${target_strike} CALL exp={target_exp} (0DTE) ===")
    print()
    print(
        f"{'time ET':>10} {'strike':>8} {'sent':>6} {'sweep':>6} "
        f"{'conv':>6} {'vol':>8} {'oi':>8} {'V/OI':>7} "
        f"{'notional':>14} {'bid':>6} {'ask':>6} {'spot':>8}"
    )
    matched = 0
    for r in rows:
        if abs(r["strike"] - target_strike) > 0.1:
            continue
        if (r["option_type"] or "").lower() != "call":
            continue
        if r["expiration"] != target_exp:
            continue
        matched += 1
        dt = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        sweep = "SWEEP" if r["is_sweep"] else "."
        sent = (r["sentiment"] or "")[:6]
        conv = (r["conviction"] or "")[:6]
        print(
            f"{dt:>10} {r['strike']:>8.1f} {sent:>6} {sweep:>6} "
            f"{conv:>6} {r['volume']:>8,} {r['oi']:>8,} {r['vol_oi']:>7.1f} "
            f"${r['notional']:>13,.0f} {r['bid'] or 0:>6.2f} {r['ask'] or 0:>6.2f} "
            f"${r['spot'] or 0:>7.2f}"
        )
    print(f"\nTotal matched: {matched}")
    print()

    # Also show ALL META alerts in window grouped by strike for context
    print(f"=== All META strikes in window (grouped) ===")
    by_strike: dict[tuple[float, str, str], dict] = {}
    for r in rows:
        key = (r["strike"], r["option_type"] or "", r["expiration"] or "")
        d = by_strike.setdefault(
            key,
            {
                "count": 0, "tot_not": 0.0, "first_ts": r["ts"], "last_ts": r["ts"],
                "max_voi": 0.0, "sweeps": 0,
            },
        )
        d["count"] += 1
        d["tot_not"] += r["notional"] or 0
        d["first_ts"] = min(d["first_ts"], r["ts"])
        d["last_ts"] = max(d["last_ts"], r["ts"])
        d["max_voi"] = max(d["max_voi"], r["vol_oi"] or 0)
        d["sweeps"] += 1 if r["is_sweep"] else 0
    print(
        f"{'strike':>8} {'type':>5} {'exp':>12} {'#':>4} {'sweeps':>7} "
        f"{'max V/OI':>9} {'tot notional':>14} {'first':>10} {'last':>10}"
    )
    for key, d in sorted(by_strike.items(), key=lambda kv: -kv[1]["tot_not"])[:20]:
        first_t = datetime.fromtimestamp(d["first_ts"]).strftime("%H:%M:%S")
        last_t = datetime.fromtimestamp(d["last_ts"]).strftime("%H:%M:%S")
        print(
            f"{key[0]:>8.1f} {key[1]:>5} {key[2]:>12} {d['count']:>4} "
            f"{d['sweeps']:>7} {d['max_voi']:>9.1f} ${d['tot_not']:>13,.0f} "
            f"{first_t:>10} {last_t:>10}"
        )

    # Snapshot of META price action in window
    print()
    print(f"=== META snapshot timeline (1-min sampled) ===")
    snaps = conn.execute(
        """
        SELECT ts, spot, actual_spot, signal, regime
        FROM snapshots
        WHERE ticker = 'META' AND ts BETWEEN ? AND ?
        ORDER BY ts
        """,
        (T_START, T_END),
    ).fetchall()
    if snaps:
        last_minute = -1
        for s in snaps:
            m = s["ts"] // 60
            if m == last_minute:
                continue
            last_minute = m
            dt = datetime.fromtimestamp(s["ts"]).strftime("%H:%M:%S")
            print(
                f"{dt} | spot=${s['actual_spot'] or s['spot']:.2f} | "
                f"signal={s['signal']} | regime={s['regime']}"
            )
    else:
        print("(no snapshot rows in window)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
