"""Backfill forward returns for every alert/signal in the DB.

Populates the signal_outcomes table with 1d/3d/1w/2w/1mo underlying returns
for each row in:
  - flow_alerts (both ISO sweeps AND the legacy V/OI flow alerts)
  - soe_signals
  - option_flow_daily (per-contract daily flow aggregates)

Usage
-----
    # Backfill everything (idempotent, uses INSERT OR REPLACE)
    python scripts/backfill_outcomes.py

    # Backfill specific source only
    python scripts/backfill_outcomes.py --source sweep

    # Backfill recent only (last N days)
    python scripts/backfill_outcomes.py --days-back 30

    # Verbose per-alert logging
    python scripts/backfill_outcomes.py --verbose

How it works
------------
1. Loads daily-close map per ticker from snapshots (1yr already backfilled)
2. For each alert/signal, finds the underlying spot at trigger time and
   the forward closes at T+1, T+3, T+5, T+10, T+22 trading days.
3. Computes % returns and hit flags (direction-aware).
4. Upserts into signal_outcomes keyed by (source_type, source_id).

Missing forward closes (e.g. the signal fired yesterday, 1mo close doesn't
exist yet) stay NULL — a later run fills them in without duplicating rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.config import get_settings
from server.signal_outcomes import (
    hit_from_return,
    init_outcomes_db,
    upsert_outcomes_batch,
)


# ── Args ────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill forward returns for alerts/signals")
    p.add_argument(
        "--source", type=str, default=None,
        choices=[None, "sweep", "flow_alert", "soe_signal", "setup_forming", "net_flow_alert"],
        help="Limit to one source type (default: all).",
    )
    p.add_argument(
        "--days-back", type=int, default=365,
        help="Only backfill triggers within last N days (default 365).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


# ── DB access ──────────────────────────────────────────────────────


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db, timeout=30.0)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
    except sqlite3.OperationalError:
        pass
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def load_daily_closes_by_date(
    ticker: str, lookback_days: int = 400,
) -> dict[str, float]:
    """Return {YYYY-MM-DD: close} for a ticker from the snapshots table."""
    cutoff = int(time.time()) - lookback_days * 86400
    with _conn() as c:
        rows = c.execute(
            """SELECT date(ts, 'unixepoch') AS d, spot, ts
               FROM snapshots
               WHERE ticker = ? AND ts > ? AND spot > 0 AND spot IS NOT NULL
               GROUP BY date(ts, 'unixepoch')
               HAVING ts = MAX(ts)
               ORDER BY ts""",
            (ticker, cutoff),
        ).fetchall()
    return {r["d"]: r["spot"] for r in rows if r["spot"]}


# Trading-day forward offsets (calendar-day mapping — good enough for
# liquid equities; precise trading-day math needs a calendar library)
FORWARD_OFFSETS_CAL_DAYS = {
    "1d": 1,
    "3d": 3,
    "1w": 7,
    "2w": 14,
    "1mo": 30,
}


def _closest_on_or_after(closes: dict[str, float], start_date: dt.date, max_skip: int = 7) -> float | None:
    """Return close on start_date, or nearest following trading day within
    max_skip days (handles weekends/holidays)."""
    for off in range(max_skip):
        d = (start_date + dt.timedelta(days=off)).isoformat()
        if d in closes:
            return closes[d]
    return None


def compute_forward_returns(
    trigger_ts: int, trigger_price: float | None,
    closes: dict[str, float],
) -> dict[str, tuple[float | None, float | None]]:
    """Return {horizon: (forward_price, return_pct)} dict for each horizon.

    Baseline is ALWAYS the close on trigger_date (or nearest prior trading day
    if trigger is on a weekend/holiday). We intentionally ignore trigger_price
    from the source row because:
      - Backfilled alerts may have stale/current spot not matching trigger time
      - Close-to-close measurement is the clean, comparable methodology
      - Intraday timing drift would otherwise pollute the hit-rate stats
    """
    trigger_date = dt.datetime.fromtimestamp(trigger_ts).date()

    # Baseline = trigger-date close (or nearest prior trading day)
    baseline = _closest_on_or_after(closes, trigger_date, max_skip=3)
    if baseline is None or baseline <= 0:
        # Search backwards a few days for the most recent close before trigger
        for back in range(1, 7):
            d = (trigger_date - dt.timedelta(days=back)).isoformat()
            if d in closes:
                baseline = closes[d]
                break
    if baseline is None or baseline <= 0:
        return {h: (None, None) for h in FORWARD_OFFSETS_CAL_DAYS}

    out = {}
    for horizon, cal_days in FORWARD_OFFSETS_CAL_DAYS.items():
        target_date = trigger_date + dt.timedelta(days=cal_days)
        fwd = _closest_on_or_after(closes, target_date, max_skip=5)
        if fwd is None or fwd <= 0:
            out[horizon] = (None, None)
        else:
            ret = (fwd - baseline) / baseline
            out[horizon] = (fwd, ret)
    return out


# ── Per-source loaders ─────────────────────────────────────────────


def load_flow_alerts(days_back: int) -> list[dict[str, Any]]:
    """Load flow_alerts (includes sweeps where is_sweep=1).

    We return one row per alert with its trigger metadata. The caller
    computes forward returns from the per-ticker close map.
    """
    cutoff = int(time.time()) - days_back * 86400
    with _conn() as c:
        rows = c.execute(
            """SELECT id, ts, ticker, side, sentiment, sweep_side,
                      option_type, notional, sweep_notional,
                      is_sweep, sweep_venues, spot
               FROM flow_alerts
               WHERE ts >= ? AND ticker IS NOT NULL
               ORDER BY ts""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_soe_signals(days_back: int) -> list[dict[str, Any]]:
    """Load SOE signals. These have direction (LONG/SHORT) + grade."""
    cutoff = int(time.time()) - days_back * 86400
    with _conn() as c:
        try:
            rows = c.execute(
                """SELECT id, ts, ticker, direction, grade, score, spot
                   FROM soe_signals
                   WHERE ts >= ? AND ticker IS NOT NULL
                   ORDER BY ts""",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # table doesn't exist in this env
    return [dict(r) for r in rows]


def load_setup_forming(days_back: int) -> list[dict[str, Any]]:
    """Load SETUP FORMING fires. Always BUY (POS regime + king-magnet-up by design)."""
    cutoff = int(time.time()) - days_back * 86400
    with _conn() as c:
        try:
            rows = c.execute(
                """SELECT id, ts, ticker, score, spot
                   FROM setup_forming
                   WHERE ts >= ? AND ticker IS NOT NULL
                   ORDER BY ts""",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]


def load_net_flow_alerts(days_back: int) -> list[dict[str, Any]]:
    """Load NET FLOW alerts. Direction derived from gap_direction (bullish/bearish)."""
    cutoff = int(time.time()) - days_back * 86400
    with _conn() as c:
        try:
            rows = c.execute(
                """SELECT id, ts, ticker, signal, confidence, gap_direction, spot
                   FROM net_flow_alerts
                   WHERE ts >= ? AND ticker IS NOT NULL
                   ORDER BY ts""",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]


# ── Direction normalization ────────────────────────────────────────


def flow_alert_direction(row: dict[str, Any]) -> str:
    """Normalize flow_alert direction based on is_sweep, sweep_side, side, sentiment.

    Priority: sweep_side (BUY/SELL/NEUTRAL) → side (BID/ASK/MID) → sentiment.
    For call options at ASK = bullish; put options at ASK = bearish.
    """
    # Sweep-classified row
    if row.get("is_sweep") == 1 and row.get("sweep_side"):
        ss = str(row["sweep_side"]).upper()
        if ss in ("BUY", "SELL", "NEUTRAL"):
            return ss

    # Plain flow_alert — derive from option_type + side/sentiment
    sentiment = str(row.get("sentiment") or "").upper()
    if sentiment in ("BULLISH", "BEARISH", "NEUTRAL"):
        return {"BULLISH": "BUY", "BEARISH": "SELL", "NEUTRAL": "NEUTRAL"}[sentiment]

    # Fallback: derive from side + option_type
    side = str(row.get("side") or "").upper()
    otype = str(row.get("option_type") or "").lower()
    if side == "ASK":
        return "BUY" if otype == "call" else "SELL"
    if side == "BID":
        return "SELL" if otype == "call" else "BUY"
    return "NEUTRAL"


def soe_direction(row: dict[str, Any]) -> str:
    """Normalize SOE signal direction to BUY/SELL/NEUTRAL."""
    d = str(row.get("direction") or "").upper()
    if d in ("LONG", "BUY", "BULLISH", "CALL"):
        return "BUY"
    if d in ("SHORT", "SELL", "BEARISH", "PUT"):
        return "SELL"
    return "NEUTRAL"


# ── Main pipeline ──────────────────────────────────────────────────


def build_outcome_tuple(
    source_type: str, source_id: str, ticker: str, direction: str,
    trigger_ts: int, trigger_price: float | None,
    notional: float | None, grade: str | None,
    is_sweep: int, sweep_venues: int | None,
    fwd: dict[str, tuple[float | None, float | None]],
) -> tuple:
    trigger_date = dt.datetime.fromtimestamp(trigger_ts).strftime("%Y-%m-%d")
    def _pair(h):
        return fwd.get(h, (None, None))
    p1d, r1d = _pair("1d")
    p3d, r3d = _pair("3d")
    p1w, r1w = _pair("1w")
    p2w, r2w = _pair("2w")
    p1mo, r1mo = _pair("1mo")
    return (
        source_type, source_id, ticker.upper(), direction,
        trigger_ts, trigger_date, trigger_price,
        notional, grade, is_sweep, sweep_venues,
        p1d, p3d, p1w, p2w, p1mo,
        r1d, r3d, r1w, r2w, r1mo,
        hit_from_return(direction, r1d),
        hit_from_return(direction, r3d),
        hit_from_return(direction, r1w),
        hit_from_return(direction, r2w),
        hit_from_return(direction, r1mo),
        int(time.time()),
    )


def main() -> int:
    args = parse_args()
    init_outcomes_db()

    # 1. Collect all alerts/signals within window
    sources: dict[str, list[dict]] = {}
    if args.source in (None, "sweep", "flow_alert"):
        sources["flow_alerts"] = load_flow_alerts(args.days_back)
        print(f"[OUTCOMES] Loaded {len(sources['flow_alerts'])} flow_alerts rows")
    if args.source in (None, "soe_signal"):
        sources["soe_signals"] = load_soe_signals(args.days_back)
        print(f"[OUTCOMES] Loaded {len(sources['soe_signals'])} soe_signals rows")
    if args.source in (None, "setup_forming"):
        sources["setup_forming"] = load_setup_forming(args.days_back)
        print(f"[OUTCOMES] Loaded {len(sources['setup_forming'])} setup_forming rows")
    if args.source in (None, "net_flow_alert"):
        sources["net_flow_alerts"] = load_net_flow_alerts(args.days_back)
        print(f"[OUTCOMES] Loaded {len(sources['net_flow_alerts'])} net_flow_alerts rows")

    # 2. Group by ticker so we load each close-map once
    by_ticker: dict[str, list[tuple[str, dict]]] = {}
    for stype, rows in sources.items():
        for r in rows:
            t = (r.get("ticker") or "").upper()
            if not t:
                continue
            by_ticker.setdefault(t, []).append((stype, r))

    print(f"[OUTCOMES] {len(by_ticker)} unique tickers across all sources")

    # 3. Per ticker, load close map + compute outcomes for each alert
    t0 = time.time()
    total_tuples: list[tuple] = []
    for ticker, alerts in by_ticker.items():
        closes = load_daily_closes_by_date(ticker, lookback_days=max(args.days_back + 60, 400))
        if not closes:
            if args.verbose:
                print(f"[OUTCOMES] {ticker}: no closes available, skipping {len(alerts)} alerts")
            continue

        for stype, row in alerts:
            trigger_ts = int(row["ts"])
            trigger_price = row.get("spot")
            fwd = compute_forward_returns(trigger_ts, trigger_price, closes)

            if stype == "flow_alerts":
                direction = flow_alert_direction(row)
                is_sweep = int(row.get("is_sweep") or 0)
                source_type = "sweep" if is_sweep == 1 else "flow_alert"
                notional = row.get("sweep_notional") if is_sweep else row.get("notional")
                grade = None
                sweep_venues = row.get("sweep_venues")
            elif stype == "soe_signals":
                direction = soe_direction(row)
                source_type = "soe_signal"
                notional = None
                grade = row.get("grade")
                is_sweep = 0
                sweep_venues = None
            elif stype == "setup_forming":
                # SETUP FORMING is always bullish by construction
                # (POS regime + king magnet UP). Score stored as grade.
                direction = "BUY"
                source_type = "setup_forming"
                notional = None
                grade = f"S{int(row.get('score') or 0)}"
                is_sweep = 0
                sweep_venues = None
            elif stype == "net_flow_alerts":
                # gap_direction is bullish/bearish/neutral
                gd = (row.get("gap_direction") or "").lower()
                if gd == "bullish":
                    direction = "BUY"
                elif gd == "bearish":
                    direction = "SELL"
                else:
                    direction = "NEUTRAL"
                source_type = "net_flow_alert"
                notional = None
                # Pack signal_type + confidence into grade for cohort filtering
                grade = f"{row.get('signal','?')}/{row.get('confidence','?')}"
                is_sweep = 0
                sweep_venues = None
            else:
                continue

            total_tuples.append(build_outcome_tuple(
                source_type=source_type,
                source_id=str(row["id"]),
                ticker=ticker,
                direction=direction,
                trigger_ts=trigger_ts,
                trigger_price=trigger_price,
                notional=notional,
                grade=grade,
                is_sweep=is_sweep,
                sweep_venues=sweep_venues,
                fwd=fwd,
            ))

        if args.verbose:
            print(f"[OUTCOMES]   {ticker}: processed {len(alerts)} alerts")

    # 4. Batch upsert
    print(f"[OUTCOMES] Prepared {len(total_tuples)} outcome rows — upserting...")
    n = upsert_outcomes_batch(total_tuples)
    elapsed = time.time() - t0
    print(f"[OUTCOMES] Done in {elapsed:.1f}s — {n} rows written")

    # 5. Quick sanity summary
    from server.signal_outcomes import get_hit_rate
    for stype in ("sweep", "flow_alert", "soe_signal", "setup_forming", "net_flow_alert"):
        stats = get_hit_rate(source_type=stype, lookback_days=args.days_back, direction="BUY")
        if stats["cohort_size"]:
            h1d = stats["horizons"]["1d"]
            h1w = stats["horizons"]["1w"]
            print(
                f"[OUTCOMES] {stype} BUY cohort: n={stats['cohort_size']} | "
                f"1d hit={(h1d['rate'] or 0)*100:.0f}% (n={h1d['n']}) | "
                f"1w hit={(h1w['rate'] or 0)*100:.0f}% (n={h1w['n']})"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
