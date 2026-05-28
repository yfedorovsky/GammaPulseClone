"""Forward-return backtest for INFORMED CLUSTER fires (Batch 2).

Same forward-return measurement as informed_flow_forward_returns, but
gated to CLUSTER fires only (2+ strikes same ticker/exp/direction in
30-min window). Clusters are the highest-conviction signal — hypothesis:
they should significantly outperform single-strike INFORMED FLOW fires.

Run from project root:
    python -m scripts.backtest_informed_cluster_forward_returns
"""
from __future__ import annotations

import sqlite3
import sys
import io
import statistics
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.flow_alerts import (  # noqa: E402
    _classify_insider_signature,
    _INFORMED_FLOW_DEDUP,
    _is_informed_flow_duplicate,
    _detect_side, _detect_sentiment,
)
from server.informed_cluster import (  # noqa: E402
    record_and_check, _recent_fires, _cluster_dedup,
)

DB = ROOT / "snapshots.db"


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    today_start = int(datetime(date.today().year, date.today().month,
                                date.today().day, 0, 0).timestamp())
    market_close = int(datetime(date.today().year, date.today().month,
                                 date.today().day, 16, 0).timestamp())

    rows = conn.execute(
        """SELECT * FROM flow_alerts WHERE ts >= ? ORDER BY ts""",
        (today_start,),
    ).fetchall()

    snap_rows = conn.execute(
        """SELECT ts, ticker, spot FROM snapshots
           WHERE ts >= ? AND spot IS NOT NULL AND spot > 0
           ORDER BY ts""",
        (today_start,),
    ).fetchall()
    snap_by_ticker: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in snap_rows:
        snap_by_ticker[r["ticker"]].append((r["ts"], float(r["spot"])))

    def _spot_at(ticker: str, target_ts: int) -> float | None:
        snaps = snap_by_ticker.get(ticker, [])
        if not snaps:
            return None
        best = None
        best_dist = 10 * 60
        for ts, spot in snaps:
            if abs(ts - target_ts) <= best_dist:
                best_dist = abs(ts - target_ts)
                best = spot
            if ts > target_ts + 10 * 60:
                break
        return best

    # Reset state
    _INFORMED_FLOW_DEDUP.clear()
    _recent_fires.clear()
    _cluster_dedup.clear()

    cluster_fires: list[dict] = []

    for r in rows:
        alert = dict(r)
        oi = alert.get("oi", 0) or 0
        vol = alert.get("volume", 0) or 0
        notional = alert.get("notional", 0) or 0
        if oi < 100 and vol < 500:
            continue
        if notional < 10_000:
            continue
        bid = alert.get("bid", 0) or 0
        ask = alert.get("ask", 0) or 0
        last = alert.get("last_price") or alert.get("last") or 0
        side_now = _detect_side(bid, ask, last,
                                 delta=alert.get("delta", 0) or 0,
                                 vol=vol, oi=oi, notional=notional)
        sent_now = _detect_sentiment(
            (alert.get("option_type") or "").lower(), side_now)
        alert["side"] = side_now
        alert["sentiment"] = sent_now

        score, reasons = _classify_insider_signature(alert)
        if score < 5:
            continue
        if _is_informed_flow_duplicate(alert):
            continue
        alert["is_insider"] = 1
        alert["insider_score"] = score

        # Use historical ts as "now" for cluster detector
        import time as _time
        real_time = _time.time
        _time.time = lambda alert_ts=alert["ts"]: float(alert_ts)
        try:
            cluster = record_and_check(alert)
        finally:
            _time.time = real_time

        if cluster:
            # Use earliest-fire spot as cluster entry
            cluster["entry_spot"] = alert.get("spot", 0)
            cluster_fires.append(cluster)

    print(f"=== CLUSTER forward-return backtest: {len(cluster_fires)} clusters ===")
    print()

    horizons_sec = {"30min": 1800, "1h": 3600, "2h": 7200, "4h": 14400}
    bucket_returns: dict[str, list[float]] = {k: [] for k in horizons_sec}
    bucket_returns["EOD"] = []
    bucket_hits: dict[str, int] = {k: 0 for k in horizons_sec}
    bucket_hits["EOD"] = 0

    best, worst = [], []
    per_size: dict[int, list[float]] = defaultdict(list)

    for c in cluster_fires:
        if not c.get("entry_spot") or c["entry_spot"] <= 0:
            continue
        sign = 1 if c["direction"] == "BULL" else -1
        first_ts = c["first_ts"]
        entry = c["entry_spot"]
        for name, secs in horizons_sec.items():
            spot_then = _spot_at(c["ticker"], first_ts + secs)
            if spot_then is None:
                continue
            ret = (spot_then - entry) / entry * 100 * sign
            bucket_returns[name].append(ret)
            if ret > 0:
                bucket_hits[name] += 1
            if name == "4h":
                per_size[c["n_strikes"]].append(ret)
                best.append((ret, c))
                worst.append((ret, c))
        eod_spot = _spot_at(c["ticker"], market_close)
        if eod_spot is not None:
            ret_eod = (eod_spot - entry) / entry * 100 * sign
            bucket_returns["EOD"].append(ret_eod)
            if ret_eod > 0:
                bucket_hits["EOD"] += 1

    print("=== HIT RATES — CLUSTER fires only ===")
    print(f"{'horizon':>8} {'n':>5} {'hit%':>7} {'median':>9} {'mean':>9} "
          f"{'p10':>9} {'p90':>9} {'min':>9} {'max':>9}")
    for h in ["30min", "1h", "2h", "4h", "EOD"]:
        rets = bucket_returns[h]
        n = len(rets)
        if not n:
            continue
        rets_sorted = sorted(rets)
        hit = bucket_hits[h] / n * 100
        med = statistics.median(rets)
        mean = sum(rets) / n
        p10 = rets_sorted[int(n * 0.10)] if n >= 10 else rets_sorted[0]
        p90 = rets_sorted[int(n * 0.90)] if n >= 10 else rets_sorted[-1]
        print(f"{h:>8} {n:>5} {hit:>6.1f}% "
              f"{med:>+8.2f}% {mean:>+8.2f}% "
              f"{p10:>+8.2f}% {p90:>+8.2f}% "
              f"{min(rets):>+8.2f}% {max(rets):>+8.2f}%")
    print()

    print("=== HIT RATE BY CLUSTER SIZE (4h horizon) ===")
    print(f"{'n_strikes':>10} {'count':>6} {'hit%':>7} {'median':>9} {'mean':>9}")
    for n_strikes in sorted(per_size.keys()):
        rets = per_size[n_strikes]
        if not rets:
            continue
        hit = sum(1 for r in rets if r > 0) / len(rets) * 100
        print(f"{n_strikes:>10} {len(rets):>6} {hit:>6.1f}% "
              f"{statistics.median(rets):>+8.2f}% "
              f"{sum(rets)/len(rets):>+8.2f}%")
    print()

    print("=== BEST 10 CLUSTERS (4h return) ===")
    best.sort(key=lambda x: -x[0])
    for ret, c in best[:10]:
        t = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M")
        strikes = "/".join(f"${s:g}" for s, *_ in c["strikes"][:4])
        print(f"  {t} {c['ticker']:>6} {c['expiration']} {c['direction']:>4} "
              f"({c['n_strikes']}str) ${c['total_notional']/1e6:.1f}M "
              f"entry=${c['entry_spot']:.2f}  4h={ret:+.2f}% [{strikes}]")
    print()

    print("=== WORST 10 CLUSTERS (4h return) ===")
    worst.sort(key=lambda x: x[0])
    for ret, c in worst[:10]:
        t = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M")
        strikes = "/".join(f"${s:g}" for s, *_ in c["strikes"][:4])
        print(f"  {t} {c['ticker']:>6} {c['expiration']} {c['direction']:>4} "
              f"({c['n_strikes']}str) ${c['total_notional']/1e6:.1f}M "
              f"entry=${c['entry_spot']:.2f}  4h={ret:+.2f}% [{strikes}]")
    print()

    print("=== META 5/27 0DTE CLUSTER OUTCOMES ===")
    for c in cluster_fires:
        if c["ticker"] != "META" or c["expiration"] != "2026-05-27":
            continue
        t = datetime.fromtimestamp(c["first_ts"]).strftime("%H:%M:%S")
        entry = c["entry_spot"]
        sign = 1 if c["direction"] == "BULL" else -1
        eod_spot = _spot_at("META", market_close) or 0
        ret_eod = (eod_spot - entry) / entry * 100 * sign if entry > 0 else 0
        strikes = "/".join(f"${s:g}" for s, *_ in c["strikes"])
        print(f"  {t} META {c['direction']:>4} ({c['n_strikes']}str) entry=${entry:.2f}  "
              f"EOD spot=${eod_spot:.2f}  ret={ret_eod:+.2f}%  [{strikes}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
