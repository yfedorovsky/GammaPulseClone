"""Historical NCP / net-flow alert backfill (Phase 2A).

Reconstructs `net_flow_alerts` for past days using the `flow_alerts` table
that's already populated. Pure computation — no API calls.

Why: The structural_turn detector's gate 5 (NCP corroboration) reads from
net_flow_alerts. Live data only goes back to 2026-04-27 (the 0DTE engine
shipped its NCP signal then). Without this, every backtest day before
4/27 fails gate 5 → can't reach the 5/5 qualified threshold → no fires.

How: Replay flow_alerts minute-by-minute. Build (ts, price, ncp, npp)
bars. Run server.net_flow_signals.detect_signals on a sliding window.
Apply the same cooldown / confidence rules the live alert loop uses.
Insert resulting FLOW_LEADS_UP / FLOW_LEADS_DOWN events into
net_flow_alerts.

Side classification (matches live aggregator):
  flow_alerts.side = 'ASK' & call → BUY   → ncp += notional
  flow_alerts.side = 'BID' & call → SELL  → ncp -= notional
  flow_alerts.side = 'ASK' & put  → BUY   → npp += notional
  flow_alerts.side = 'BID' & put  → SELL  → npp -= notional
  side IN ('MID','NEUTRAL') → skipped

Idempotent: deletes existing net_flow_alerts rows for the (ticker, day)
range before inserting, so re-runs are safe.

Run:
  python scripts/historical_net_flow_backfill.py --start 2026-04-13 --end 2026-04-26
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

# Make `server` package importable so we can reuse the live signal detector.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.net_flow_signals import (  # noqa: E402
    ALERT_COOLDOWN_S,
    ALERT_MIN_CONFIDENCE,
    ALERT_SIGNALS,
    ROC_WINDOW_MIN,
    detect_signals,
)


SNAPSHOTS_DB = str(ROOT / "snapshots.db")

DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "SPX", "SPXW"]

# Cash session: 09:30 → 16:00 ET. Build bars for this range.
# Use UTC offsets — snapshots.db stores ts as epoch seconds.
SESSION_OPEN_HHMM = (9, 30)
SESSION_CLOSE_HHMM = (16, 0)


def daterange(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri only
            yield d
        d += dt.timedelta(days=1)


def session_bounds_epoch(d: dt.date) -> tuple[int, int]:
    """Return (open_epoch, close_epoch) for the cash session on date d.

    Uses local America/New_York time. Assumes the host machine's local
    time matches ET (which is true for the dev box per CLAUDE.md context).
    """
    open_dt = dt.datetime(d.year, d.month, d.day, *SESSION_OPEN_HHMM)
    close_dt = dt.datetime(d.year, d.month, d.day, *SESSION_CLOSE_HHMM)
    return int(open_dt.timestamp()), int(close_dt.timestamp())


def fetch_flow_alerts(
    conn: sqlite3.Connection, ticker: str, t0: int, t1: int,
) -> list[dict]:
    """Pull all flow_alerts for ticker between [t0, t1) ordered by ts."""
    cur = conn.execute(
        """SELECT ts, side, option_type, notional, spot
           FROM flow_alerts
           WHERE ticker = ? AND ts >= ? AND ts < ?
           ORDER BY ts ASC""",
        (ticker, t0, t1),
    )
    return [
        {"ts": r[0], "side": r[1], "right": r[2],
         "notional": r[3] or 0.0, "spot": r[4]}
        for r in cur.fetchall()
    ]


def build_minute_bars(
    alerts: list[dict], t0: int, t1: int,
) -> list[dict]:
    """Aggregate alerts into 1-min bars: t (close epoch), price, ncp, npp.

    Bar key is the minute-aligned epoch second (ts // 60 * 60). Price is
    the last alert's spot in that minute; if no alerts, carry forward.
    Empty minutes get carry-forward price + ncp/npp = 0 (real bar — no
    flow that minute).
    """
    bins: dict[int, dict] = {}
    for a in alerts:
        bar_t = (a["ts"] // 60) * 60
        b = bins.setdefault(
            bar_t,
            {"t": bar_t, "price": None, "ncp": 0.0, "npp": 0.0},
        )
        right = (a["right"] or "").lower()
        side = (a["side"] or "").upper()
        notional = a["notional"] or 0.0
        if notional <= 0:
            continue
        # ASK = aggressive buy, BID = aggressive sell. MID/NEUTRAL → skip.
        if side == "ASK":
            if right == "call":
                b["ncp"] += notional
            elif right == "put":
                b["npp"] += notional
        elif side == "BID":
            if right == "call":
                b["ncp"] -= notional
            elif right == "put":
                b["npp"] -= notional
        if a["spot"] is not None:
            b["price"] = a["spot"]

    # Build full minute series, carry forward price.
    bars: list[dict] = []
    last_price = None
    minute = (t0 // 60) * 60
    end = (t1 // 60) * 60
    while minute < end:
        b = bins.get(minute)
        if b is None:
            bars.append({"t": minute, "price": last_price, "ncp": 0.0, "npp": 0.0})
        else:
            if b["price"] is not None:
                last_price = b["price"]
            else:
                b["price"] = last_price
            bars.append(b)
        minute += 60
    return bars


def replay_signals(bars: list[dict]) -> list[dict]:
    """Walk bars forward; at each step run detect_signals on bars[:i+1].
    Returns list of {ts, signal, gap_direction, confidence, ncp, npp,
    price, ncp_roc, npp_roc, price_roc, description}.
    """
    out = []
    # detect_signals needs >= 2 * ROC_WINDOW_MIN bars
    min_bars = 2 * ROC_WINDOW_MIN
    for i in range(min_bars, len(bars) + 1):
        window = bars[:i]
        # detect_signals checks the LATEST bar only — so this gives one
        # decision per minute, the same way the live loop does.
        hits = detect_signals(window)
        if not hits:
            continue
        latest = window[-1]
        for h in hits:
            out.append({
                "ts": latest["t"],
                "signal": h.signal,
                "gap_direction": h.gap_direction,
                "confidence": h.confidence,
                "ncp": h.ncp,
                "npp": h.npp,
                "price": h.price,
                "price_roc": h.price_roc_pct,
                "ncp_roc": h.ncp_roc_dollars,
                "npp_roc": h.npp_roc_dollars,
                "description": h.description,
            })
    return out


def apply_cooldown_filter(hits: list[dict], ticker: str) -> list[dict]:
    """Same logic as server.net_flow_signals.NetFlowAlertState.should_fire,
    but operating on a historical sequence instead of wall clock.
    """
    kept = []
    last: tuple[str, int] | None = None  # (regime, ts)
    conf_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank = conf_rank[ALERT_MIN_CONFIDENCE]
    for h in hits:
        if h["signal"] not in ALERT_SIGNALS:
            continue
        if conf_rank.get(h["confidence"], 0) < min_rank:
            continue
        if last is None:
            kept.append(h)
            last = (h["signal"], h["ts"])
            continue
        last_signal, last_ts = last
        elapsed = h["ts"] - last_ts
        if h["signal"] == last_signal:
            if elapsed < ALERT_COOLDOWN_S:
                continue
        else:
            # Transition — require 2/3 cooldown
            if elapsed < ALERT_COOLDOWN_S * 2 / 3:
                continue
        kept.append(h)
        last = (h["signal"], h["ts"])
    return kept


def insert_alerts(
    conn: sqlite3.Connection, ticker: str, t0: int, t1: int,
    hits: list[dict],
) -> int:
    """Idempotent: delete existing rows in window, insert fresh."""
    conn.execute(
        "DELETE FROM net_flow_alerts WHERE ticker = ? AND ts >= ? AND ts < ?",
        (ticker, t0, t1),
    )
    n = 0
    for h in hits:
        conn.execute(
            """INSERT INTO net_flow_alerts
                 (ts, ticker, signal, confidence, gap_direction, spot,
                  ncp, npp, price_roc_pct, ncp_roc_dollars, npp_roc_dollars,
                  description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (h["ts"], ticker, h["signal"], h["confidence"], h["gap_direction"],
             h["price"], h["ncp"], h["npp"], h["price_roc"],
             h["ncp_roc"], h["npp_roc"], h["description"]),
        )
        n += 1
    conn.commit()
    return n


def existing_alerts_count(
    conn: sqlite3.Connection, ticker: str, t0: int, t1: int,
) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM net_flow_alerts WHERE ticker = ? AND ts >= ? AND ts < ?",
        (ticker, t0, t1),
    )
    return cur.fetchone()[0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    p.add_argument("--db", default=SNAPSHOTS_DB)
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip (ticker, day) pairs that already have any "
                   "net_flow_alerts rows (preserves live data).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be inserted, don't write.")
    args = p.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    print(f"[BACKFILL] window={start}..{end} tickers={tickers} db={args.db}")
    print(f"[BACKFILL] skip_existing={args.skip_existing} dry_run={args.dry_run}")

    conn = sqlite3.connect(args.db)
    try:
        total_hits = 0
        for d in daterange(start, end):
            t0, t1 = session_bounds_epoch(d)
            for ticker in tickers:
                existing = existing_alerts_count(conn, ticker, t0, t1)
                if existing > 0 and args.skip_existing:
                    print(f"  {d} {ticker}: SKIP (already has {existing} alerts)")
                    continue

                alerts = fetch_flow_alerts(conn, ticker, t0, t1)
                if not alerts:
                    print(f"  {d} {ticker}: no flow_alerts — skipping")
                    continue

                bars = build_minute_bars(alerts, t0, t1)
                # Skip days where price never populated (no spot in any alert)
                priced = sum(1 for b in bars if b["price"] is not None)
                if priced < 2 * ROC_WINDOW_MIN:
                    print(f"  {d} {ticker}: only {priced} priced bars — skipping")
                    continue

                hits = replay_signals(bars)
                kept = apply_cooldown_filter(hits, ticker)

                if args.dry_run:
                    print(f"  {d} {ticker}: {len(alerts)} alerts -> "
                          f"{len(bars)} bars -> {len(hits)} raw hits -> "
                          f"{len(kept)} after cooldown (dry run)")
                else:
                    n = insert_alerts(conn, ticker, t0, t1, kept)
                    total_hits += n
                    detail = ""
                    if kept:
                        signals = defaultdict(int)
                        for h in kept:
                            signals[h["signal"]] += 1
                        detail = " (" + ", ".join(
                            f"{k}:{v}" for k, v in signals.items()
                        ) + ")"
                    print(f"  {d} {ticker}: {len(alerts)} alerts -> "
                          f"{len(bars)} bars -> {n} inserted{detail}")

        print(f"\n[BACKFILL] total inserted: {total_hits}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
