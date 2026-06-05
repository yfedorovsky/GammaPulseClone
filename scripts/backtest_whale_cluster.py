"""Phase 3 backtest: replay today's WHALE-RT fires through whale_cluster
to count cluster-collapsed dispatches.

Goal: confirm WHALE CLUSTER would collapse the 811 individual whale
dispatches (from scripts/backtest_whale_rt_today.py) by a meaningful
factor so the noise floor goes from 125 alerts/hour to something usable.

Usage:
    python scripts/backtest_whale_cluster.py [YYYY-MM-DD]
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.flow_alerts import (  # noqa: E402
    _classify_whale_signature,
    WHALE_TELEGRAM_NOTIONAL,
)
import server.whale_cluster as wc  # noqa: E402


def _parse_args() -> datetime.date:
    if len(sys.argv) > 1:
        return datetime.date.fromisoformat(sys.argv[1])
    return datetime.date.today()


def main() -> int:
    date = _parse_args()
    start = int(datetime.datetime(date.year, date.month, date.day).timestamp())
    end = int(
        (datetime.datetime(date.year, date.month, date.day)
         + datetime.timedelta(days=1)).timestamp()
    )
    open_auction_ts_end = start + (9 * 3600 + 31 * 60)
    after_close_ts_start = start + (16 * 3600 + 5 * 60)

    print("=" * 70)
    print(f"WHALE CLUSTER BACKTEST - {date.isoformat()}")
    print("=" * 70)

    c = sqlite3.connect("./snapshots.db")
    c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT id, ts, ticker, strike, expiration, option_type, side,
                  sentiment, volume, oi, vol_oi, notional, sweep_notional
           FROM flow_alerts
           WHERE ts >= ? AND ts < ?
           ORDER BY ts ASC""",
        (start, end),
    ).fetchall()

    # Per-contract dedup TTL (mirrors WHALE-RT logic)
    seen_contracts: set[tuple] = set()
    n_individual = 0          # would-be individual WHALE-RT fires (after suppression)
    n_individual_suppressed = 0  # suppressed by active cluster window
    n_cluster = 0             # would-be cluster fires
    cluster_log: list[dict] = []

    # Patch wc.time.time() effectively: feed the row ts as "now" so the
    # cluster windows respect the replay timeline rather than wall clock.
    # whale_cluster uses time.time() directly so we monkey-patch it.
    real_time = time.time
    current_ts = [0.0]

    def _fake_time():
        return current_ts[0]
    wc.time.time = _fake_time

    try:
        for r in rows:
            ts = r["ts"]
            if ts < open_auction_ts_end or ts >= after_close_ts_start:
                continue
            try:
                exp_str = str(r["expiration"])
                exp_date = (
                    datetime.date.fromisoformat(exp_str)
                    if "-" in exp_str
                    else datetime.datetime.strptime(exp_str, "%Y%m%d").date()
                )
                if exp_date < date:
                    continue
            except Exception:
                pass

            alert = {
                "ticker": r["ticker"],
                "notional": r["notional"] or r["sweep_notional"] or 0,
                "side": r["side"],
                "volume": r["volume"] or 0,
                "oi": r["oi"] or 0,
                "sentiment": r["sentiment"],
                "option_type": r["option_type"],
                "strike": r["strike"],
                "expiration": r["expiration"],
            }
            is_whale, reasons = _classify_whale_signature(alert)
            if not is_whale:
                continue
            if alert["notional"] < WHALE_TELEGRAM_NOTIONAL:
                continue
            if int(alert["volume"] or 0) < 500:
                continue

            dedup_key = (
                alert["ticker"], alert["strike"], alert["expiration"],
                alert["option_type"], alert["sentiment"],
            )
            if dedup_key in seen_contracts:
                continue
            seen_contracts.add(dedup_key)

            # Update fake clock to this alert's ts so cluster logic sees correct timing
            current_ts[0] = float(ts)
            alert["is_whale"] = 1

            # Cluster-suppression check (mirrors sweep_detector logic).
            # If a CLUSTER has fired for this (ticker, direction) within
            # the dedup TTL, suppress the individual fire.
            direction = wc._direction_of(alert)
            ckey = (alert["ticker"].upper(), direction)
            last_cluster_ts = wc._whale_cluster_dedup.get(ckey, 0.0)
            in_active_cluster = (
                last_cluster_ts
                and current_ts[0] - last_cluster_ts < wc.WHALE_CLUSTER_DEDUP_TTL_SEC
            )

            cluster = wc.record_and_check(alert)
            if cluster and cluster["n_strikes"] >= wc.MIN_WHALE_CLUSTER_TELEGRAM_STRIKES:
                n_cluster += 1
                cluster_log.append({
                    "ts": ts,
                    "ticker": cluster["ticker"],
                    "direction": cluster["direction"],
                    "n_strikes": cluster["n_strikes"],
                    "n_expirations": cluster["n_expirations"],
                    "total_notional": cluster["total_notional"],
                    "duration_min": cluster["duration_min"],
                })
                # Cluster covers this leg — don't ALSO fire individual
                continue

            if in_active_cluster:
                # Active cluster window — silent record, no Telegram
                n_individual_suppressed += 1
                continue

            n_individual += 1
    finally:
        wc.time.time = real_time

    total_dispatches = n_individual + n_cluster
    baseline = n_individual + n_individual_suppressed + n_cluster

    print()
    print(f"Source: today's flow_alerts replayed through WHALE-RT gates")
    print(f"  Individual fires (passed through):     {n_individual}")
    print(f"  Individual suppressed by cluster:      {n_individual_suppressed}")
    print(f"  WHALE CLUSTER fires:                   {n_cluster}")
    print(f"  TOTAL Telegrams dispatched:            {total_dispatches}")
    print()
    print(f"  Pre-cluster baseline:                  {n_individual + n_individual_suppressed}")
    print(f"  Post-cluster total:                    {total_dispatches}")
    print(f"  Net change vs no-cluster:              "
          f"{total_dispatches - (n_individual + n_individual_suppressed):+d}")
    print(f"  Compression ratio:                     "
          f"{(n_individual + n_individual_suppressed)/max(total_dispatches,1):.2f}x")
    print()
    print("  Per-hour rate (6.5hr RTH):")
    print(f"    Individual:  {n_individual/6.5:.1f}/hr")
    print(f"    Cluster:     {n_cluster/6.5:.1f}/hr")
    print(f"    Combined:    {total_dispatches/6.5:.1f}/hr")
    print()

    print("=== CLUSTER FIRES (chronological) ===")
    print(f"{'Time':9s} {'Ticker':6s} {'Dir':4s} {'Strikes':>8s} {'Exps':>4s}  {'Notional':>11s}  Duration")
    print("-" * 75)
    for cl in cluster_log:
        et_time = datetime.datetime.fromtimestamp(cl["ts"]).strftime("%H:%M:%S")
        print(
            f"{et_time}  {cl['ticker']:6s}  {cl['direction']:4s}  "
            f"{cl['n_strikes']:>8d}  {cl['n_expirations']:>4d}  "
            f"${cl['total_notional']/1e6:>9.1f}M  {cl['duration_min']:>5.1f}min"
        )

    # Per-ticker cluster breakdown
    print()
    print("=== TOP TICKERS BY CLUSTER FIRES ===")
    from collections import Counter
    by_ticker = Counter(cl["ticker"] for cl in cluster_log)
    for ticker, n in by_ticker.most_common(15):
        print(f"  {ticker:8s}  {n} clusters")

    return 0


if __name__ == "__main__":
    sys.exit(main())
