"""Resolve every SOE signal from Apr 14 onwards — WIN / LOSS / PENDING / EXPIRED.

For each signal, walk forward through Tradier 5-min bars from signal_ts and
check whether spot touched target (WIN) or stop (LOSS) first. Ambiguous
bars (both target and stop in same candle range) are marked AMBIGUOUS and
excluded from win-rate calcs.

This tells us raw signal quality INDEPENDENT of whether the user took the
trade, entry slippage, position sizing, or exit discipline. Answers the
question "is the signal good?" separate from "did I execute well?"

Usage:
    python -m scripts.backtest_signals_week
    python -m scripts.backtest_signals_week --grades A A+ B+
    python -m scripts.backtest_signals_week --start 2026-04-14

Output: docs/research/week_signal_outcomes.md
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.tradier import TradierClient


def load_signals(start_iso: str, grades: list[str]) -> list[dict]:
    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(grades))
    rows = con.execute(f"""
        SELECT id, ts, ticker, direction, grade, strike, option_type, expiration,
               spot, entry_price, target, stop, rr_ratio, dte
        FROM soe_signals
        WHERE ts >= strftime('%s', ?)
          AND grade IN ({placeholders})
          AND target IS NOT NULL AND stop IS NOT NULL
          AND ticker IS NOT NULL AND spot IS NOT NULL
        ORDER BY ts
    """, (start_iso, *grades)).fetchall()
    con.close()
    return [dict(r) for r in rows]


async def pull_5min_bars(tc: TradierClient, ticker: str, start_iso: str, end_iso: str) -> list[dict]:
    """Pull 5-min intraday bars from Tradier for a given ticker / date range."""
    try:
        bars = await tc.history(ticker, interval="5min", start=start_iso, end=end_iso)
        return bars or []
    except Exception as e:
        print(f"  [{ticker}] bar fetch error: {e}")
        return []


def resolve_signal(signal: dict, bars: list[dict]) -> dict:
    """Walk-forward through bars. Return outcome dict.

    BULL signals: target above spot, stop below.
      WIN if bar_high >= target before bar_low <= stop
      LOSS if bar_low <= stop before bar_high >= target
      AMBIGUOUS if both touched within same bar
      PENDING if neither touched and we have no more bars

    BEAR signals: target below spot, stop above.
      WIN if bar_low <= target
      LOSS if bar_high >= stop

    Returns {outcome, resolved_ts, bars_to_resolve, max_fav_pct, max_adv_pct}.
    """
    direction = signal["direction"]
    is_bull = direction == "▲" or direction == "BULL" or direction == "bull"
    target = signal["target"]
    stop = signal["stop"]
    spot = signal["spot"]
    entry_ts = signal["ts"]

    # Only consider bars AFTER signal entry
    relevant_bars = [b for b in bars if _bar_to_epoch(b["time"]) > entry_ts]
    if not relevant_bars:
        return {"outcome": "PENDING", "bars_checked": 0}

    max_fav_pct = 0.0  # max favorable excursion
    max_adv_pct = 0.0  # max adverse excursion

    for i, b in enumerate(relevant_bars):
        high, low = b["high"], b["low"]

        if is_bull:
            fav = (high - spot) / spot * 100
            adv = (spot - low) / spot * 100
            max_fav_pct = max(max_fav_pct, fav)
            max_adv_pct = max(max_adv_pct, adv)
            target_hit = high >= target
            stop_hit = low <= stop
        else:
            fav = (spot - low) / spot * 100
            adv = (high - spot) / spot * 100
            max_fav_pct = max(max_fav_pct, fav)
            max_adv_pct = max(max_adv_pct, adv)
            target_hit = low <= target
            stop_hit = high >= stop

        if target_hit and stop_hit:
            return {
                "outcome": "AMBIGUOUS",
                "resolved_ts": _bar_to_epoch(b["time"]),
                "bars_checked": i + 1,
                "max_fav_pct": round(max_fav_pct, 2),
                "max_adv_pct": round(max_adv_pct, 2),
            }
        if target_hit:
            return {
                "outcome": "WIN",
                "resolved_ts": _bar_to_epoch(b["time"]),
                "bars_checked": i + 1,
                "max_fav_pct": round(max_fav_pct, 2),
                "max_adv_pct": round(max_adv_pct, 2),
            }
        if stop_hit:
            return {
                "outcome": "LOSS",
                "resolved_ts": _bar_to_epoch(b["time"]),
                "bars_checked": i + 1,
                "max_fav_pct": round(max_fav_pct, 2),
                "max_adv_pct": round(max_adv_pct, 2),
            }

    return {
        "outcome": "PENDING",
        "bars_checked": len(relevant_bars),
        "max_fav_pct": round(max_fav_pct, 2),
        "max_adv_pct": round(max_adv_pct, 2),
    }


def _bar_to_epoch(ts) -> int:
    """Handle both int epoch and ISO string from Tradier history endpoints."""
    if isinstance(ts, (int, float)):
        return int(ts)
    if isinstance(ts, str):
        try:
            dt = datetime.datetime.fromisoformat(ts)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def group_signals_by_ticker(signals: list[dict]) -> dict[str, list[dict]]:
    by_ticker = defaultdict(list)
    for s in signals:
        by_ticker[s["ticker"]].append(s)
    return by_ticker


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-04-14")
    parser.add_argument("--grades", nargs="+", default=["A", "A+", "B+"])
    args = parser.parse_args()

    print("=" * 78)
    print(f"Signal-outcome backtest — grades {args.grades}, from {args.start}")
    print("=" * 78)

    signals = load_signals(args.start, args.grades)
    print(f"Loaded {len(signals)} signals")
    print()

    by_ticker = group_signals_by_ticker(signals)
    print(f"Unique tickers: {len(by_ticker)}")
    print()

    # Pull bars per ticker — reuse for multiple signals per ticker
    tc = TradierClient()
    today = datetime.date.today().isoformat()
    bars_by_ticker: dict[str, list[dict]] = {}

    try:
        for i, ticker in enumerate(sorted(by_ticker.keys()), 1):
            first_sig = min(by_ticker[ticker], key=lambda s: s["ts"])
            # Start bar fetch from earliest signal day
            start_dt = datetime.datetime.fromtimestamp(first_sig["ts"]).date()
            bars = await pull_5min_bars(
                tc, ticker, start_dt.isoformat(), today
            )
            bars_by_ticker[ticker] = bars
            if i % 20 == 0:
                print(f"  fetched {i}/{len(by_ticker)} tickers...")
    finally:
        await tc.close()

    print(f"Got bars for {sum(1 for b in bars_by_ticker.values() if b)}/{len(by_ticker)} tickers")
    print()

    # Resolve each signal
    results = []
    for s in signals:
        bars = bars_by_ticker.get(s["ticker"], [])
        if not bars:
            results.append({**s, "outcome": "NO_BARS", "bars_checked": 0})
            continue
        outcome = resolve_signal(s, bars)
        results.append({**s, **outcome})

    # ── Aggregate stats ──────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("RESULTS BY GRADE")
    print("=" * 78)
    for grade in args.grades:
        sub = [r for r in results if r["grade"] == grade]
        n = len(sub)
        wins = sum(1 for r in sub if r["outcome"] == "WIN")
        losses = sum(1 for r in sub if r["outcome"] == "LOSS")
        pending = sum(1 for r in sub if r["outcome"] == "PENDING")
        ambig = sum(1 for r in sub if r["outcome"] == "AMBIGUOUS")
        nobars = sum(1 for r in sub if r["outcome"] == "NO_BARS")
        resolved = wins + losses
        wr = wins / resolved * 100 if resolved > 0 else 0
        print(f"\n  {grade}: {n} signals")
        print(f"    WIN: {wins}  LOSS: {losses}  PENDING: {pending}  AMBIG: {ambig}  NO_BARS: {nobars}")
        print(f"    Win rate (on resolved): {wins}/{resolved} = {wr:.1f}%")
        if sub:
            # MFE/MAE averages
            mfe_vals = [r.get("max_fav_pct", 0) for r in sub if "max_fav_pct" in r]
            mae_vals = [r.get("max_adv_pct", 0) for r in sub if "max_adv_pct" in r]
            if mfe_vals:
                print(f"    Avg MFE: {sum(mfe_vals)/len(mfe_vals):+.2f}% | Avg MAE: {sum(mae_vals)/len(mae_vals):+.2f}%")

    # ── By ticker (top 15) ───────────────────────────────────────────
    print("\n" + "=" * 78)
    print("TOP 15 TICKERS BY FIRE COUNT — win rate per ticker")
    print("=" * 78)
    per_ticker: dict[str, dict] = {}
    for r in results:
        t = r["ticker"]
        per_ticker.setdefault(t, {"n": 0, "w": 0, "l": 0, "p": 0})
        per_ticker[t]["n"] += 1
        if r["outcome"] == "WIN": per_ticker[t]["w"] += 1
        elif r["outcome"] == "LOSS": per_ticker[t]["l"] += 1
        elif r["outcome"] == "PENDING": per_ticker[t]["p"] += 1

    top = sorted(per_ticker.items(), key=lambda x: -x[1]["n"])[:20]
    print(f"  {'ticker':>8} {'fires':>6} {'WIN':>4} {'LOSS':>4} {'PEND':>5} {'WR%':>6}")
    for t, s in top:
        res = s["w"] + s["l"]
        wr = s["w"] / res * 100 if res > 0 else 0
        print(f"  {t:>8} {s['n']:>6} {s['w']:>4} {s['l']:>4} {s['p']:>5} {wr:>5.1f}%")

    # ── By time of day ───────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("BY TIME OF DAY (ET, grouped by hour)")
    print("=" * 78)
    per_hour: dict[int, dict] = defaultdict(lambda: {"n": 0, "w": 0, "l": 0})
    for r in results:
        dt = datetime.datetime.fromtimestamp(r["ts"])
        hour = dt.hour
        per_hour[hour]["n"] += 1
        if r["outcome"] == "WIN": per_hour[hour]["w"] += 1
        elif r["outcome"] == "LOSS": per_hour[hour]["l"] += 1
    print(f"  {'hour':>5} {'fires':>6} {'WIN':>4} {'LOSS':>4} {'WR%':>6}")
    for h in sorted(per_hour.keys()):
        s = per_hour[h]
        res = s["w"] + s["l"]
        wr = s["w"] / res * 100 if res > 0 else 0
        print(f"  {h:>4}:00 {s['n']:>6} {s['w']:>4} {s['l']:>4} {wr:>5.1f}%")

    # ── Save markdown report ─────────────────────────────────────────
    out_path = Path("docs/research/week_signal_outcomes.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Signal Outcome Backtest — {args.start} to {today}\n\n")
        f.write("**Method:** Walk-forward through 5-min Tradier bars from signal timestamp. ")
        f.write("WIN = spot hit target price. LOSS = spot hit stop price. ")
        f.write("AMBIGUOUS = both hit in same bar.\n\n")
        f.write(f"Total signals analyzed: {len(results)}\n\n")
        f.write("## Raw Win Rate By Grade\n\n")
        f.write("| Grade | Fires | WIN | LOSS | PENDING | AMBIG | Win Rate (on resolved) |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for grade in args.grades:
            sub = [r for r in results if r["grade"] == grade]
            if not sub: continue
            n = len(sub)
            w = sum(1 for r in sub if r["outcome"] == "WIN")
            l = sum(1 for r in sub if r["outcome"] == "LOSS")
            p = sum(1 for r in sub if r["outcome"] == "PENDING")
            a = sum(1 for r in sub if r["outcome"] == "AMBIGUOUS")
            resolved = w + l
            wr = w / resolved * 100 if resolved > 0 else 0
            f.write(f"| {grade} | {n} | {w} | {l} | {p} | {a} | **{wr:.1f}%** |\n")
        f.write("\n")
        f.write("## Top 20 Tickers\n\n")
        f.write("| Ticker | Fires | WIN | LOSS | PEND | WR% |\n|---|---:|---:|---:|---:|---:|\n")
        for t, s in top:
            res = s["w"] + s["l"]
            wr = s["w"] / res * 100 if res > 0 else 0
            f.write(f"| {t} | {s['n']} | {s['w']} | {s['l']} | {s['p']} | {wr:.1f}% |\n")
        f.write("\n")
        f.write("## By Hour (ET)\n\n")
        f.write("| Hour | Fires | WIN | LOSS | WR% |\n|---|---:|---:|---:|---:|\n")
        for h in sorted(per_hour.keys()):
            s = per_hour[h]
            res = s["w"] + s["l"]
            wr = s["w"] / res * 100 if res > 0 else 0
            f.write(f"| {h:02d}:00 | {s['n']} | {s['w']} | {s['l']} | {wr:.1f}% |\n")

        f.write(f"\n## Methodology Caveats\n\n")
        f.write("- **5-min bar resolution:** fast wick-through moves are detected; tick-level precision is not. ")
        f.write("For signals with tight target/stop bands this may miss inter-candle noise. "
                "Generally this favors WIN classification since rapid spikes register on 5-min bars.\n")
        f.write("- **No option price tracking:** spot hits target doesn't guarantee the option itself would have paid "
                "1R+ return (depends on delta, IV crush, theta). This backtest measures SPOT-BASED signal quality only. "
                "Option-level P&L would be different.\n")
        f.write("- **Multiple signals per ticker:** a ticker firing 18 B+ signals in 4 days produces 18 rows here. "
                "Treated as independent observations even though they may be re-alerts of the same underlying setup.\n")
        f.write("- **No dedup by time:** signals fired within minutes of each other on the same ticker are counted separately.\n")
        f.write("- **Sample size by grade:** small A-grade cohort means confidence intervals are wide.\n")

    print(f"\nReport saved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
