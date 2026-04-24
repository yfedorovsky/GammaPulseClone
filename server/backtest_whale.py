"""0DTE / 1DTE whale-lotto backtest.

Scans historical flow_alerts for the 'cheap whale' pattern:
  - 0/1 DTE expiration
  - Contract price at entry ≤ $0.50
  - Volume during day ≥ 20,000
  - V/OI ratio at some point ≥ 10x

For each qualifying contract (grouped by ticker/strike/exp/type), computes:
  - entry_price   = min observed price during the loading phase
  - peak_price    = max observed price intraday
  - max_multiple  = peak_price / entry_price
  - time_to_peak  = minutes from first alert to peak price

Reports hit-rate distribution across max-multiple bins: 2x, 5x, 10x, 50x.

Created 2026-04-23 after UW flagged QQQ 649P 0DTE ($0.09 → $4.33 = 4700%)
and we classified it MEDIUM because notional ≈ $500k (our HIGH bar is $5M).
This backtest validates whether the classifier-override pattern is
statistically profitable before we wire it to Telegram.

Usage:
    python -m server.backtest_whale
    python -m server.backtest_whale --min-vol 30000 --max-entry 0.30
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

DB_PATH = "./snapshots.db"


@dataclass
class WhaleSetup:
    ticker: str
    strike: float
    expiration: str
    option_type: str
    first_alert_ts: int
    entry_price: float
    peak_price: float
    peak_ts: int
    max_vol: int
    max_vol_oi: float
    n_alerts: int

    @property
    def max_multiple(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return self.peak_price / self.entry_price

    @property
    def time_to_peak_min(self) -> int:
        return int((self.peak_ts - self.first_alert_ts) / 60)


def find_whale_setups(
    min_vol: int = 20_000,
    max_entry_price: float = 0.50,
    min_vol_oi: float = 10.0,
    since_days: int = 30,
) -> list[WhaleSetup]:
    """Scan flow_alerts for cheap-whale entries and compute max-multiple."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        since_ts = int(datetime.datetime.now().timestamp()) - since_days * 86400
        cur = conn.execute(
            """
            SELECT ts, ticker, strike, expiration, option_type,
                   volume, oi, vol_oi, last_price, notional
            FROM flow_alerts
            WHERE ts >= ?
            ORDER BY ticker, strike, expiration, option_type, ts ASC
            """,
            (since_ts,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Group by contract
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["ticker"], r["strike"], r["expiration"], r["option_type"])
        groups[key].append(dict(r))

    setups: list[WhaleSetup] = []
    for key, alerts in groups.items():
        ticker, strike, expiration, option_type = key

        # Must be 0-1 DTE on the day the first alert fired
        first_ts = alerts[0]["ts"]
        first_date = datetime.datetime.fromtimestamp(first_ts).date()
        try:
            exp_date = datetime.date.fromisoformat(expiration)
        except (ValueError, TypeError):
            continue
        dte = (exp_date - first_date).days
        if dte < 0 or dte > 1:
            continue

        # Cheap-whale qualifier
        max_vol = max((a["volume"] or 0) for a in alerts)
        max_voi = max((a["vol_oi"] or 0) for a in alerts)
        if max_vol < min_vol or max_voi < min_vol_oi:
            continue

        # Entry = lowest price while vol was still loading (first half of alerts)
        half = max(1, len(alerts) // 2)
        loading_prices = [a["last_price"] or 0 for a in alerts[:half] if (a["last_price"] or 0) > 0]
        if not loading_prices:
            continue
        entry_price = min(loading_prices)
        if entry_price > max_entry_price:
            continue

        # Peak = max price across all alerts, tracking timestamp
        peak_price = 0.0
        peak_ts = first_ts
        for a in alerts:
            p = a["last_price"] or 0
            if p > peak_price:
                peak_price = p
                peak_ts = a["ts"]
        if peak_price <= entry_price:
            continue

        setups.append(WhaleSetup(
            ticker=ticker, strike=strike, expiration=expiration,
            option_type=option_type,
            first_alert_ts=first_ts,
            entry_price=round(entry_price, 3),
            peak_price=round(peak_price, 3),
            peak_ts=peak_ts,
            max_vol=max_vol,
            max_vol_oi=round(max_voi, 1),
            n_alerts=len(alerts),
        ))

    return setups


def summarize(setups: list[WhaleSetup]) -> dict[str, Any]:
    """Aggregate stats by max-multiple bins + time-to-peak distribution."""
    if not setups:
        return {"n": 0}

    multiples = [s.max_multiple for s in setups]
    ttp_minutes = [s.time_to_peak_min for s in setups if s.time_to_peak_min > 0]

    bins = [2, 3, 5, 10, 20, 50, 100]
    hit_rates: dict[str, dict[str, Any]] = {}
    for b in bins:
        hits = sum(1 for m in multiples if m >= b)
        pct = round(hits / len(multiples) * 100, 1)
        hit_rates[f"{b}x+"] = {"n_hits": hits, "pct_of_setups": pct}

    return {
        "n_setups": len(setups),
        "max_multiple_stats": {
            "min": round(min(multiples), 2),
            "median": round(statistics.median(multiples), 2),
            "avg": round(statistics.mean(multiples), 2),
            "max": round(max(multiples), 2),
        },
        "hit_rate_by_multiple": hit_rates,
        "time_to_peak_min": {
            "median": round(statistics.median(ttp_minutes), 1) if ttp_minutes else None,
            "p25": round(statistics.quantiles(ttp_minutes, n=4)[0], 1) if len(ttp_minutes) >= 4 else None,
            "p75": round(statistics.quantiles(ttp_minutes, n=4)[2], 1) if len(ttp_minutes) >= 4 else None,
        },
    }


def print_top_setups(setups: list[WhaleSetup], n: int = 15) -> None:
    sorted_by_mult = sorted(setups, key=lambda s: s.max_multiple, reverse=True)[:n]
    print(f"\n=== Top {n} setups by max-multiple ===")
    print(f"{'When':19s}  {'Ticker':6s}  {'Contract':22s}  {'Entry':>6s}  {'Peak':>6s}  {'Mult':>6s}  {'Vol':>8s}  {'V/OI':>5s}  {'TTP':>5s}")
    for s in sorted_by_mult:
        when = datetime.datetime.fromtimestamp(s.first_alert_ts).strftime("%Y-%m-%d %H:%M")
        contract = f"${int(s.strike)}{s.option_type[0].upper()} {s.expiration}"
        mult = f"{s.max_multiple:.1f}x"
        print(
            f"{when:19s}  {s.ticker:6s}  {contract:22s}  ${s.entry_price:>5.2f}  ${s.peak_price:>5.2f}  "
            f"{mult:>6s}  {s.max_vol:>8,}  {s.max_vol_oi:>5.1f}  {s.time_to_peak_min:>4d}m"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vol", type=int, default=20_000, help="Minimum single-day volume")
    ap.add_argument("--max-entry", type=float, default=0.50, help="Max entry price ($)")
    ap.add_argument("--min-vol-oi", type=float, default=10.0, help="Min vol/OI ratio")
    ap.add_argument("--days", type=int, default=30, help="Lookback days")
    ap.add_argument("--top", type=int, default=15, help="Show top N by multiple")
    args = ap.parse_args()

    print(
        f"Scanning last {args.days} days for cheap-whale setups: "
        f"vol >= {args.min_vol:,}, entry <= ${args.max_entry:.2f}, v/oi >= {args.min_vol_oi}"
    )
    setups = find_whale_setups(
        min_vol=args.min_vol,
        max_entry_price=args.max_entry,
        min_vol_oi=args.min_vol_oi,
        since_days=args.days,
    )

    summary = summarize(setups)
    import json
    print(json.dumps(summary, indent=2, default=str))
    print_top_setups(setups, n=args.top)


if __name__ == "__main__":
    main()
