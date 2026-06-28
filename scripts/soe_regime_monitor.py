"""SOE regime-failure monitor (#122-E, 2026-06-27 semis-selloff post-mortem).

Standing instrumentation so a Friday-6/26-style regime failure gets caught
*live* instead of in a post-mortem. That day SOE fired 169 directional-long
bull signals into a choppy capitulation; resolved win rate ~2%.

This is READ-ONLY. It buckets resolved SOE bull fires by (signal_type x
day-tape-regime) and prints the win rate, then flags TODAY if the tape is chop
and the directional-long engine is firing heavily anyway.

Day-tape regime (per the chop-gate's market-wide test): SPY intraday
efficiency |net|/path and day-range. CHOP = eff < 0.70 AND range < 1.5%,
DOWN = net move <= -0.4% (trend down), else UP/MIXED.

Usage:
    python scripts/soe_regime_monitor.py [--days 20] [--db PATH] [--today]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server.soe_chop_gate import SUPPRESS_TYPES, PIN_TYPE  # noqa: E402

UP_GLYPH = chr(9650)  # the up-triangle BULL marker in soe_signals.direction


def _spy_regime(con: sqlite3.Connection, day: str) -> tuple[str, float, float, float]:
    """Return (regime, eff, range_pct, net_pct) for SPY on an ET day."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(
        tzinfo=timezone(timedelta(hours=-4)))
    lo = int(start.timestamp()); hi = lo + 24 * 3600
    spots = [r[0] for r in con.execute(
        "SELECT spot FROM snapshots WHERE ticker='SPY' AND ts>=? AND ts<? AND spot>0 "
        "ORDER BY ts", (lo, hi)).fetchall()]
    if len(spots) < 5:
        return "UNKNOWN", 0.0, 0.0, 0.0
    net = spots[-1] - spots[0]
    path = sum(abs(spots[i] - spots[i - 1]) for i in range(1, len(spots))) or 1e-9
    eff = abs(net) / path
    rng = (max(spots) - min(spots)) / spots[0]
    net_pct = net / spots[0]
    if rng < 0.001:  # < 0.1% range = no real session (weekend / stale)
        return "CLOSED", eff, rng * 100, net_pct * 100
    if eff < 0.70 and rng < 0.015:
        regime = "CHOP"
    elif net_pct <= -0.004:
        regime = "TREND_DOWN"
    elif net_pct >= 0.004:
        regime = "TREND_UP"
    else:
        regime = "MIXED"
    return regime, eff, rng * 100, net_pct * 100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--db", default=os.environ.get(
        "SNAPSHOTS_DB_PATH", r"C:\Dev\GammaPulse\snapshots.db"))
    ap.add_argument("--today", action="store_true",
                    help="only print today's live regime-failure check")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    days = [r[0] for r in con.execute(
        "SELECT DISTINCT date(ts,'unixepoch','-4 hours') d FROM soe_signals "
        "ORDER BY d DESC LIMIT ?", (args.days,)).fetchall()]
    days.sort()
    regimes = {d: _spy_regime(con, d) for d in days}

    # (signal_type, regime) -> [wins, losses]
    cell: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for d in days:
        regime = regimes[d][0]
        for st, status in con.execute(
            "SELECT signal_type, status FROM soe_signals "
            "WHERE date(ts,'unixepoch','-4 hours')=? AND direction=? ",
                (d, UP_GLYPH)).fetchall():
            if status == "WIN":
                cell[(st, regime)][0] += 1
            elif status in ("LOSS", "EXPIRED"):
                cell[(st, regime)][1] += 1

    def kind(st):
        return "DIR-LONG" if st in SUPPRESS_TYPES else ("PIN" if st == PIN_TYPE else "OTHER")

    if not args.today:
        print(f"=== SOE bull resolved WR by signal_type x day-regime "
              f"(last {len(days)} trading days) ===")
        print(f"{'signal_type':22s} {'regime':11s} {'kind':9s} {'W':>4s} {'L':>4s} {'WR':>6s}")
        rows = sorted(cell.items(), key=lambda kv: (-(kv[1][0] + kv[1][1])))
        for (st, regime), (w, l) in rows:
            n = w + l
            if n == 0:
                continue
            wr = 100 * w / n
            flag = "  <-- LOSING" if (kind(st) == "DIR-LONG" and regime in
                                      ("CHOP", "TREND_DOWN") and wr < 15 and n >= 5) else ""
            print(f"{st:22s} {regime:11s} {kind(st):9s} {w:4d} {l:4d} {wr:5.0f}%{flag}")

        # Aggregate: directional-long in CHOP vs TREND_UP
        print("\n=== headline: directional-long bull WR by regime ===")
        agg: dict[str, list] = defaultdict(lambda: [0, 0])
        for (st, regime), (w, l) in cell.items():
            if kind(st) == "DIR-LONG":
                agg[regime][0] += w; agg[regime][1] += l
        for regime, (w, l) in sorted(agg.items()):
            n = w + l
            if n:
                print(f"  {regime:11s}: {w:3d}W/{l:3d}L = {100*w/n:.0f}% WR (n={n})")

    # Today's live check
    today = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    reg = _spy_regime(con, today)
    fires = con.execute(
        "SELECT signal_type FROM soe_signals WHERE date(ts,'unixepoch','-4 hours')=? "
        "AND direction=?", (today, UP_GLYPH)).fetchall()
    dl = sum(1 for (st,) in fires if st in SUPPRESS_TYPES)
    pin = sum(1 for (st,) in fires if st == PIN_TYPE)
    print(f"\n=== TODAY {today}: SPY regime={reg[0]} "
          f"(eff {reg[1]:.2f}, range {reg[2]:.2f}%, net {reg[3]:+.2f}%) ===")
    print(f"  SOE bull fires today: {len(fires)} | directional-long {dl} | pinning {pin}")
    if reg[0] in ("CHOP", "TREND_DOWN") and dl >= 10:
        print(f"  ** REGIME-FAILURE WARNING: {dl} directional-long bull fires into a "
              f"{reg[0]} tape — the Friday-6/26 pattern. Chop gate should be ACTIVE. **")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
