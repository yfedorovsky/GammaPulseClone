"""Bear-day regression replay — validate the bear-day ensemble against a real
crash day in snapshots.db. Default target: Friday 2026-06-05 (SPY −2.58%).

This is the canonical regression for tasks #54 (structure gate) + #58 (0DTE
put-side override). It reads the historical flow_alerts and reports:

  1. THE MOVE        — SPY open / low / close
  2. STRUCTURE       — did our GEX engine flag the short-gamma DANGER tape?
  3. LONG-BIAS       — hourly bullish-call vs bearish-put (the drowning problem)
  4. #58 REPLAY      — how many NEUTRAL 0DTE puts flip → BEARISH + the $ skew
  5. VERDICT         — PASS/FAIL vs expected regression outcomes

Pure DB read — no running backend needed. Uses the LIVE #58 thresholds from
flow_alerts so the replay can't drift from the shipped rule.

Usage:
  python scripts/replay_jun05.py                 # defaults to 2026-06-05
  python scripts/replay_jun05.py --date 2026-06-05
  python scripts/replay_jun05.py --date 2026-06-05 --db snapshots.db --ticker SPY,QQQ
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# live #58 thresholds — single source of truth
from server.flow_alerts import (  # noqa: E402
    ODTE_PUT_ATM_PCT, ODTE_PUT_MIN_VOI, ODTE_PUT_MIN_NOTIONAL,
)

_checks: list[tuple[str, bool, str]] = []


def _chk(name: str, cond: bool, detail: str = "") -> None:
    _checks.append((name, bool(cond), detail))


def main() -> int:
    ap = argparse.ArgumentParser(description="Bear-day regression replay")
    ap.add_argument("--date", default="2026-06-05", help="ET trading date YYYY-MM-DD")
    ap.add_argument("--db", default=None, help="snapshots.db path (default: config)")
    ap.add_argument("--ticker", default="SPY,QQQ", help="index ETFs, comma-sep")
    args = ap.parse_args()

    db = args.db
    if not db:
        try:
            from server.config import get_settings
            db = get_settings().snapshot_db
        except Exception:
            db = "snapshots.db"
    tickers = [t.strip().upper() for t in args.ticker.split(",") if t.strip()]
    tlist = "(" + ",".join(f"'{t}'" for t in tickers) + ")"
    D = f"date(ts,'unixepoch','-4 hours')='{args.date}'"

    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    n = c.execute(f"SELECT COUNT(*) FROM flow_alerts WHERE {D}").fetchone()[0]
    print(f"\n{'='*68}\n  BEAR-DAY REPLAY — {args.date}   [{db}]   {n:,} alerts\n{'='*68}")
    if n == 0:
        print(f"  No flow_alerts for {args.date}. Nothing to replay.")
        return 1

    # 1. THE MOVE (primary index)
    px = tickers[0]
    r = c.execute(
        f"SELECT (SELECT spot FROM flow_alerts WHERE ticker='{px}' AND {D} ORDER BY ts LIMIT 1) o,"
        f" MAX(spot) hi, MIN(spot) lo,"
        f" (SELECT spot FROM flow_alerts WHERE ticker='{px}' AND {D} ORDER BY ts DESC LIMIT 1) cl"
        f" FROM flow_alerts WHERE ticker='{px}' AND {D}").fetchone()
    move = (r["cl"] / r["o"] - 1) * 100 if r["o"] else 0
    print(f"\n1. MOVE  {px}: open {r['o']:.2f}  low {r['lo']:.2f}  close {r['cl']:.2f}  "
          f"= {move:+.2f}%")

    # 2. STRUCTURE (did we flag DANGER / NEG gamma?)
    print("\n2. STRUCTURE (our GEX read on the index):")
    reg = {row["regime"]: row["n"] for row in c.execute(
        f"SELECT regime, COUNT(*) n FROM flow_alerts WHERE ticker='{px}' AND {D} "
        f"GROUP BY regime").fetchall()}
    neg, pos = reg.get("NEG", 0), reg.get("POS", 0)
    danger = c.execute(
        f"SELECT COUNT(*) FROM flow_alerts WHERE ticker='{px}' AND {D} "
        f"AND signal IN ('DANGER','MAGNET FADE')").fetchone()[0]
    first = c.execute(
        f"SELECT MIN(ts) t FROM flow_alerts WHERE ticker IN {tlist} AND {D} "
        f"AND signal IN ('DANGER','MAGNET FADE')").fetchone()
    import datetime as _dt
    first_et = ""
    if first and first["t"]:
        first_et = _dt.datetime.fromtimestamp(first["t"], _dt.UTC).astimezone(
            _dt.timezone(_dt.timedelta(hours=-4))).strftime("%H:%M")
    print(f"   regime: NEG {neg} vs POS {pos}   |   DANGER/MAGNET-FADE signals: {danger}"
          f"   |   first fired: {first_et} ET")
    _chk("structure detected short-gamma (NEG dominant)", neg > pos and neg > 50,
         f"NEG={neg} POS={pos}")
    _chk("DANGER fired early (before 10:00 ET)", bool(first_et) and first_et < "10:00",
         f"first={first_et}")

    # 3. LONG-BIAS drowning
    print("\n3. LONG-BIAS (bullish-call vs bearish-put alerts, all tickers):")
    bc, bp = c.execute(
        f"SELECT SUM(sentiment='BULLISH' AND option_type='call'),"
        f" SUM(sentiment='BEARISH' AND option_type='put') FROM flow_alerts WHERE {D}"
    ).fetchone()
    print(f"   bullish calls {bc:,}  vs  bearish puts {bp:,}  "
          f"({'BULL-skewed (the drowning problem)' if bc > bp else 'bear-skewed'})")

    # 4. #58 REPLAY — NEUTRAL 0DTE puts that flip to BEARISH
    print(f"\n4. #58 REPLAY (NEUTRAL 0DTE puts → BEARISH; thresholds: ATM≤{ODTE_PUT_ATM_PCT:.0%}, "
          f"voi≥{ODTE_PUT_MIN_VOI}, ${ODTE_PUT_MIN_NOTIONAL/1e6:.0f}M, NEG tape):")
    flip_q = (
        f"SELECT COUNT(*) n, COALESCE(SUM(notional),0) tot FROM flow_alerts "
        f"WHERE {D} AND ticker IN {tlist} AND option_type='put' "
        f"AND expiration='{args.date}' AND sentiment='NEUTRAL' AND side='MID' "
        f"AND notional>={ODTE_PUT_MIN_NOTIONAL} AND vol_oi>={ODTE_PUT_MIN_VOI} "
        f"AND spot>0 AND ABS(strike-spot)/spot<={ODTE_PUT_ATM_PCT} AND regime='NEG'")
    f = c.execute(flip_q).fetchone()
    bal = c.execute(
        f"SELECT COALESCE(SUM(CASE WHEN sentiment='BEARISH' THEN notional END),0) bear,"
        f" COALESCE(SUM(CASE WHEN sentiment='NEUTRAL' THEN notional END),0) neut,"
        f" COALESCE(SUM(CASE WHEN sentiment='BULLISH' THEN notional END),0) bull"
        f" FROM flow_alerts WHERE {D} AND ticker IN {tlist} AND option_type='put' "
        f"AND expiration='{args.date}'").fetchone()
    fd = f["tot"] or 0
    print(f"   flips: {f['n']} alerts / ${fd:,.0f}")
    print(f"   0DTE put $ by sentiment   BEFORE -> AFTER:")
    print(f"     BEARISH  ${bal['bear']:,.0f}  ->  ${bal['bear']+fd:,.0f}")
    print(f"     NEUTRAL  ${bal['neut']:,.0f}  ->  ${bal['neut']-fd:,.0f}")
    print(f"     BULLISH  ${bal['bull']:,.0f}  (unchanged)")
    _chk("#58 flips meaningful 0DTE put $ (>=50 alerts)", f["n"] >= 50, f"flips={f['n']}")
    _chk("after #58: bearish 0DTE put $ > bullish (skew flips bearish)",
         (bal["bear"] + fd) > bal["bull"],
         f"bear={bal['bear']+fd:,.0f} bull={bal['bull']:,.0f}")

    # 5. VERDICT
    print(f"\n{'='*68}\n  VERDICT")
    ok = True
    for name, passed, detail in _checks:
        print(f"   [{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if not passed else ""))
        ok = ok and passed
    print(f"\n  {'✅ REGRESSION PASS' if ok else '❌ REGRESSION FAIL'} — "
          f"the bear-day ensemble {'correctly reframes' if ok else 'did NOT reframe'} {args.date}.")
    print(f"{'='*68}\n")
    print("  NOTE: this replays the SHIPPED detection (regime=NEG, #58 thresholds) over\n"
          "  historical alerts. After restart with STRUCTURE_GATE_ACTIVE=1, the live gate\n"
          "  additionally demotes the bullish flow + tags ⚠️ SHORT-GAMMA TAPE in real time.\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
