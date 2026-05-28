"""Forward-return backtest for INFORMED FLOW v2 alerts.

For each INFORMED FLOW fire today (5+/6, post-Batch-1+2+3a gates), pull
the underlying spot trajectory from the snapshots table and compute
forward returns at 30min, 1h, 2h, 4h, and EOD horizons.

Score the alert direction:
  - BULL (call+BULLISH or put+BEARISH): positive return = win
  - BEAR (call+BEARISH or put+BULLISH): negative return = win

Bucket results:
  - Hit rate: % of alerts where direction was right
  - Median return: typical magnitude
  - Win/loss skew: max win vs max loss
  - 90th percentile move (the big winners)

This is the actual precision measurement the LLMs all said we'd need.

Run from project root:
    python -m scripts.backtest_informed_flow_forward_returns
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
    _detect_side,
    _detect_sentiment,
)

DB = ROOT / "snapshots.db"


def _direction_of(alert: dict) -> str:
    """Map (option_type, sentiment) to BULL/BEAR like informed_cluster does."""
    otype = (alert.get("option_type") or "").lower()
    sent = (alert.get("sentiment") or "").upper()
    if otype == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if otype == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "NEUTRAL"


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    today_start = int(datetime(date.today().year, date.today().month,
                                date.today().day, 0, 0).timestamp())
    # End of regular trading: 4:00 PM ET (16:00 local on this machine)
    market_close = int(datetime(date.today().year, date.today().month,
                                 date.today().day, 16, 0).timestamp())

    rows = conn.execute(
        """SELECT * FROM flow_alerts WHERE ts >= ? ORDER BY ts""",
        (today_start,),
    ).fetchall()
    print(f"=== Forward-return backtest: {len(rows):,} flow_alerts replayed ===")
    print()

    # Reset
    _INFORMED_FLOW_DEDUP.clear()

    # Build per-ticker snapshot ts → spot lookup
    print("Loading snapshot timeline per ticker...")
    snap_rows = conn.execute(
        """SELECT ts, ticker, spot FROM snapshots
           WHERE ts >= ? AND spot IS NOT NULL AND spot > 0
           ORDER BY ts""",
        (today_start,),
    ).fetchall()
    snap_by_ticker: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in snap_rows:
        snap_by_ticker[r["ticker"]].append((r["ts"], float(r["spot"])))
    print(f"  Loaded {sum(len(v) for v in snap_by_ticker.values()):,} snapshot points "
          f"across {len(snap_by_ticker)} tickers")
    print()

    def _spot_at(ticker: str, target_ts: int) -> float | None:
        """Find the most-recent snapshot for ticker at or just after target_ts.
        Returns None if no snapshot within 10 minutes of target."""
        snaps = snap_by_ticker.get(ticker, [])
        if not snaps:
            return None
        # Binary-ish search — snaps sorted by ts
        best = None
        best_dist = 10 * 60  # max 10 min lookback/forward
        for ts, spot in snaps:
            if abs(ts - target_ts) <= best_dist:
                # Take the first within window; tighten window
                best_dist = abs(ts - target_ts)
                best = spot
            if ts > target_ts + 10 * 60:
                break
        return best

    # Replay through classifier. Re-runs CURRENT side-detection logic on
    # each row (using bid/ask/last + vol/oi) so we get the post-P0-fix
    # sentiment — not the historical (potentially pre-fix) sentiment that
    # was stored in the DB at capture time. This is the meaningful measure:
    # "what would precision have been if v2 logic was live then?"
    fires: list[dict] = []
    for r in rows:
        alert = dict(r)
        oi = alert.get("oi", 0) or 0
        vol = alert.get("volume", 0) or 0
        notional = alert.get("notional", 0) or 0
        if oi < 100 and vol < 500:
            continue
        if notional < 10_000:
            continue

        # Re-derive side + sentiment with current logic (post-P0 fix).
        # Historical sentiment column had MID-of-spread bias for many fires.
        bid = alert.get("bid", 0) or 0
        ask = alert.get("ask", 0) or 0
        last = alert.get("last_price") or alert.get("last") or 0
        side_now = _detect_side(
            bid, ask, last,
            delta=alert.get("delta", 0) or 0,
            vol=vol, oi=oi,
            notional=notional,
        )
        sent_now = _detect_sentiment(
            (alert.get("option_type") or "").lower(), side_now
        )
        alert["side"] = side_now
        alert["sentiment"] = sent_now

        score, reasons = _classify_insider_signature(alert)
        if score < 5:
            continue
        if _is_informed_flow_duplicate(alert):
            continue

        direction = _direction_of(alert)
        if direction == "NEUTRAL":
            continue

        entry_spot = alert.get("spot", 0)
        if not entry_spot or entry_spot <= 0:
            continue

        fires.append({
            "ts": alert["ts"],
            "ticker": alert["ticker"],
            "strike": alert["strike"],
            "expiration": alert["expiration"],
            "option_type": alert["option_type"],
            "direction": direction,
            "score": score,
            "vol_oi": alert.get("vol_oi", 0),
            "notional": alert.get("notional", 0),
            "entry_spot": entry_spot,
            "reasons": reasons,
        })

    print(f"Total INFORMED FLOW fires for backtest: {len(fires)}")
    print()

    # For each fire, compute forward returns at multiple horizons
    horizons_sec = {
        "30min": 30 * 60,
        "1h": 60 * 60,
        "2h": 2 * 60 * 60,
        "4h": 4 * 60 * 60,
    }
    bucket_returns: dict[str, list[float]] = {k: [] for k in horizons_sec}
    bucket_returns["EOD"] = []
    bucket_hits: dict[str, int] = {k: 0 for k in horizons_sec}
    bucket_hits["EOD"] = 0

    # Per-ticker performance
    per_ticker: dict[str, dict] = defaultdict(lambda: {"n": 0, "wins_1h": 0, "wins_4h": 0,
                                                        "returns_1h": [], "returns_4h": []})

    # Track biggest winners and losers
    best_4h = []
    worst_4h = []

    for f in fires:
        entry = f["entry_spot"]
        sign = 1 if f["direction"] == "BULL" else -1
        for name, secs in horizons_sec.items():
            spot_then = _spot_at(f["ticker"], f["ts"] + secs)
            if spot_then is None:
                continue
            ret_pct = (spot_then - entry) / entry * 100 * sign  # signed return
            bucket_returns[name].append(ret_pct)
            if ret_pct > 0:
                bucket_hits[name] += 1
            if name == "1h":
                per_ticker[f["ticker"]]["n"] += 1
                per_ticker[f["ticker"]]["returns_1h"].append(ret_pct)
                if ret_pct > 0:
                    per_ticker[f["ticker"]]["wins_1h"] += 1
            if name == "4h":
                per_ticker[f["ticker"]]["returns_4h"].append(ret_pct)
                if ret_pct > 0:
                    per_ticker[f["ticker"]]["wins_4h"] += 1
                best_4h.append((ret_pct, f))
                worst_4h.append((ret_pct, f))

        # EOD
        eod_spot = _spot_at(f["ticker"], market_close)
        if eod_spot is not None:
            ret_eod = (eod_spot - entry) / entry * 100 * sign
            bucket_returns["EOD"].append(ret_eod)
            if ret_eod > 0:
                bucket_hits["EOD"] += 1

    print(f"=== HIT RATES + RETURN DISTRIBUTIONS ===")
    print(f"{'horizon':>8} {'n':>6} {'hit%':>7} {'median':>9} {'mean':>9} "
          f"{'p10':>9} {'p90':>9} {'min':>9} {'max':>9}")
    for h in ["30min", "1h", "2h", "4h", "EOD"]:
        rets = bucket_returns[h]
        n = len(rets)
        if not n:
            continue
        rets_sorted = sorted(rets)
        hit_pct = bucket_hits[h] / n * 100
        med = statistics.median(rets)
        mean = sum(rets) / n
        p10 = rets_sorted[int(n * 0.10)] if n >= 10 else rets_sorted[0]
        p90 = rets_sorted[int(n * 0.90)] if n >= 10 else rets_sorted[-1]
        print(f"{h:>8} {n:>6} {hit_pct:>6.1f}% "
              f"{med:>+8.2f}% {mean:>+8.2f}% "
              f"{p10:>+8.2f}% {p90:>+8.2f}% "
              f"{min(rets):>+8.2f}% {max(rets):>+8.2f}%")
    print()

    print(f"=== TOP TICKERS BY 4h WIN RATE (n>=5 fires) ===")
    ranking = []
    for t, st in per_ticker.items():
        if len(st["returns_4h"]) >= 5:
            wr = st["wins_4h"] / len(st["returns_4h"]) * 100
            med = statistics.median(st["returns_4h"])
            ranking.append((wr, t, len(st["returns_4h"]), med))
    ranking.sort(key=lambda x: -x[0])
    for wr, t, n, med in ranking[:15]:
        print(f"  {t:>6} n={n:>3}  win={wr:>5.1f}%  median={med:>+6.2f}%")
    print()

    print(f"=== BEST 10 SINGLE FIRES (by 4h return) ===")
    best_4h.sort(key=lambda x: -x[0])
    for ret, f in best_4h[:10]:
        t = datetime.fromtimestamp(f["ts"]).strftime("%H:%M:%S")
        print(f"  {t} {f['ticker']:>6} ${f['strike']:.1f}{str(f['option_type'])[0].upper()} "
              f"{f['expiration']} {f['direction']:>4} "
              f"V/OI={f['vol_oi']:.1f}x score={f['score']}/6 "
              f"entry=${f['entry_spot']:.2f}  4h ret={ret:+.2f}%")
    print()

    print(f"=== WORST 10 SINGLE FIRES (by 4h return) ===")
    worst_4h.sort(key=lambda x: x[0])
    for ret, f in worst_4h[:10]:
        t = datetime.fromtimestamp(f["ts"]).strftime("%H:%M:%S")
        print(f"  {t} {f['ticker']:>6} ${f['strike']:.1f}{str(f['option_type'])[0].upper()} "
              f"{f['expiration']} {f['direction']:>4} "
              f"V/OI={f['vol_oi']:.1f}x score={f['score']}/6 "
              f"entry=${f['entry_spot']:.2f}  4h ret={ret:+.2f}%")
    print()

    # Score breakdown — does 6/6 outperform 5/6?
    print(f"=== 6/6 vs 5/6 SCORE COMPARISON (1h horizon) ===")
    for sc in (5, 6):
        rets = [bucket_returns["1h"][i] for i, f in enumerate(fires)
                if f.get("score") == sc and i < len(bucket_returns["1h"])]
        if not rets:
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets) * 100
        med = statistics.median(rets)
        print(f"  score={sc}: n={len(rets)} win={wr:.1f}% median={med:+.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
