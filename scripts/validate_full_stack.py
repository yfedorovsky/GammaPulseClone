"""End-to-end validation harness — replays a day's flow_alerts through the
FULL current detection stack and reports what WOULD fire.

Stack (in order):
  1. Side-detection v2 (#47)   — recompute side from bid/ask/last where
                                  available; measure ASK flips vs stored
  2. Dividend-arb parity (#49) — suppress sub-intrinsic deep-ITM calls
  3. Whale classifier (#41)    — $3M+ ASK, vol>=500, vol/oi>=0.30, aligned
  4. WHALE-RT dispatch (#44)   — per-contract 10-min dedup
  5. Two-tier WHALE CLUSTER (#48) — FAST intraday (30m) + SLOW multi-tenor
                                    (4h, span>30m), with individual-suppress

Run this pre-open to know the expected alert volume + the specific signals
the live system will fire if the day's pattern repeats.

Usage:
    python scripts/validate_full_stack.py [YYYY-MM-DD]
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.flow_alerts as fa  # noqa: E402
import server.whale_cluster as wc  # noqa: E402


def _parse_date() -> datetime.date:
    if len(sys.argv) > 1:
        return datetime.date.fromisoformat(sys.argv[1])
    return datetime.date.today()


def main() -> int:
    date = _parse_date()
    start = int(datetime.datetime(date.year, date.month, date.day).timestamp())
    end = start + 86400
    oa_end = start + 9 * 3600 + 31 * 60      # 09:31 ET
    ac_start = start + 16 * 3600 + 5 * 60    # 16:05 ET

    print("=" * 72)
    print(f"FULL-STACK VALIDATION — {date.isoformat()}")
    print("=" * 72)

    c = sqlite3.connect("./snapshots.db")
    c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT ts,ticker,strike,expiration,option_type,side,sentiment,
                  volume,oi,vol_oi,notional,sweep_notional,spot,last_price,
                  bid,ask,delta
           FROM flow_alerts WHERE ts>=? AND ts<? ORDER BY ts ASC""",
        (start, end),
    ).fetchall()
    total_rows = len(rows)
    print(f"Total flow_alerts rows: {total_rows:,}")
    if not total_rows:
        print("No data for that date.")
        return 1

    # Reset cluster state for a clean replay; monkeypatch time to row ts.
    wc._recent_whale_fires.clear()
    wc._whale_cluster_dedup.clear()
    wc._whale_slow_cluster_dedup.clear()
    cur = [0.0]
    real_time = time.time
    wc.time.time = lambda: cur[0]

    # Counters
    n_rth = 0
    side_flips_to_ask = 0
    n_parity_suppressed = 0
    n_whale_rt = 0
    n_fast_cluster = 0
    n_slow_cluster = 0
    n_individual_suppressed = 0

    whale_dedup: dict[tuple, float] = {}
    WHALE_RT_TTL = 600
    seen_contract: set[tuple] = set()
    whale_by_ticker: Counter = Counter()
    slow_ladders: list[dict] = []
    fast_clusters: list[dict] = []

    try:
        for r in rows:
            ts = r["ts"]
            if ts < oa_end or ts >= ac_start:
                continue
            # Expired-contract drop
            try:
                es = str(r["expiration"])
                ed = (datetime.date.fromisoformat(es) if "-" in es
                      else datetime.datetime.strptime(es, "%Y%m%d").date())
                if ed < date:
                    continue
            except Exception:
                pass
            n_rth += 1

            # ── Step 1: side-detection v2 (recompute where bid/ask present) ──
            side = r["side"]
            bid, ask, last = r["bid"] or 0, r["ask"] or 0, r["last_price"] or 0
            if bid > 0 and ask > 0 and last > 0:
                recomputed = fa._detect_side(
                    bid, ask, last, delta=r["delta"] or 0,
                    vol=r["volume"] or 0, oi=r["oi"] or 0,
                    notional=r["notional"] or 0,
                )
                if side != "ASK" and recomputed == "ASK":
                    side_flips_to_ask += 1
                side = recomputed
            sentiment = fa._detect_sentiment(
                (r["option_type"] or "").lower(), side
            )

            alert = {
                "ticker": r["ticker"], "strike": r["strike"],
                "expiration": r["expiration"],
                "option_type": (r["option_type"] or "").lower(),
                "side": side, "sentiment": sentiment,
                "volume": r["volume"], "oi": r["oi"],
                "notional": r["notional"] or r["sweep_notional"] or 0,
                "spot": r["spot"], "last": last, "delta": r["delta"],
            }

            # ── Step 2+3: parity gate + whale classifier ──
            is_whale, reasons = fa._classify_whale_signature(alert)
            if not is_whale:
                if reasons and "PARITY_ARB" in reasons[0]:
                    n_parity_suppressed += 1
                continue

            # ── Step 4: WHALE-RT dispatch ($3M Telegram floor + dedup) ──
            if alert["notional"] < fa.WHALE_TELEGRAM_NOTIONAL:
                continue
            if (alert["volume"] or 0) < 500:
                continue
            ckey = (r["ticker"], r["strike"], r["expiration"],
                    alert["option_type"], sentiment)
            if ckey in seen_contract:
                continue
            seen_contract.add(ckey)

            cur[0] = float(ts)
            alert["is_whale"] = 1

            # ── Step 5: two-tier cluster + individual suppression ──
            direction = wc._direction_of(alert)
            dkey = (r["ticker"].upper(), direction)
            in_active_cluster = (
                dkey in wc._whale_cluster_dedup
                and cur[0] - wc._whale_cluster_dedup[dkey]
                < wc.WHALE_CLUSTER_DEDUP_TTL_SEC
            )
            cluster = wc.record_and_check(alert)
            if cluster:
                if cluster["tier"] == "fast":
                    n_fast_cluster += 1
                    fast_clusters.append(cluster)
                else:
                    n_slow_cluster += 1
                    slow_ladders.append(cluster)
                continue  # cluster covers this leg
            if in_active_cluster:
                n_individual_suppressed += 1
                continue
            n_whale_rt += 1
            whale_by_ticker[r["ticker"]] += 1
    finally:
        wc.time.time = real_time

    total_telegrams = n_whale_rt + n_fast_cluster + n_slow_cluster

    print()
    print("─" * 72)
    print("PIPELINE FUNNEL")
    print("─" * 72)
    print(f"  RTH non-expired rows:              {n_rth:,}")
    print(f"  Side-v2 flips to ASK (#47):        {side_flips_to_ask:,}")
    print(f"  Parity-arb suppressed (#49):       {n_parity_suppressed:,}")
    print()
    print("  WHALE DISPATCHES (what hits Telegram):")
    print(f"    Individual WHALE-RT:             {n_whale_rt:,}")
    print(f"    Suppressed by active cluster:    {n_individual_suppressed:,}")
    print(f"    FAST  (⚡ INTRADAY CLUSTER):      {n_fast_cluster:,}")
    print(f"    SLOW  (🐋 MULTI-TENOR LADDER):    {n_slow_cluster:,}")
    print(f"    ── TOTAL Telegram alerts:        {total_telegrams:,}")
    print(f"    Per-hour (6.5h RTH):             {total_telegrams/6.5:.1f}/hr")

    print()
    print("─" * 72)
    print("TOP TICKERS BY INDIVIDUAL WHALE-RT FIRES")
    print("─" * 72)
    for tkr, n in whale_by_ticker.most_common(15):
        print(f"  {tkr:6s}  {n}")

    print()
    print("─" * 72)
    print("MULTI-TENOR LADDERS (🐋 slow-tier fires)")
    print("─" * 72)
    for cl in sorted(slow_ladders, key=lambda x: -x["total_notional"])[:20]:
        t = datetime.datetime.fromtimestamp(cl["first_ts"]).strftime("%H:%M")
        print(f"  {cl['ticker']:6s} {cl['direction']:4s}  "
              f"{cl['n_expirations']}exp  span={cl['duration_min']:.0f}min  "
              f"${cl['total_notional']/1e6:.1f}M  (first {t} ET)")

    print()
    print("─" * 72)
    print("CROSS-CHECK: competitor-flagged tickers (6/4 screenshots)")
    print("─" * 72)
    for tkr in ["NBIS", "NVDA", "NEE", "ORCL", "META", "MU", "MRVL", "AVGO"]:
        n = whale_by_ticker.get(tkr, 0)
        in_slow = sum(1 for cl in slow_ladders if cl["ticker"] == tkr)
        in_fast = sum(1 for cl in fast_clusters if cl["ticker"] == tkr)
        note = ""
        if tkr == "NEE":
            note = "  <- dividend arb, SHOULD be 0/0/0"
        print(f"  {tkr:6s}  whale-rt={n:3d}  fast={in_fast}  slow={in_slow}{note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
