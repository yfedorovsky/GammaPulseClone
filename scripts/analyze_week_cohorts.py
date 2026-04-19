"""Cohort analysis of the 91 broker roundtrips (Apr 13-17 week).

Picks up where attribute_trades_to_signals.py left off — it produced the
per-source scorecard. This script slices by every other dimension that
survives the limitation that broker CSVs only give trade DATE (no intraday
timestamps): DTE-at-entry, hold duration, direction, broker, entry day
of week, and signal-confidence tier.

Time-of-day for entries is inferred from the matched SOE signal timestamp
when confidence is STRONG or MEDIUM — broker open_ts is always midnight.

Outputs: docs/research/week_cohort_analysis.md
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


# ── Reuse attribution logic from the existing script ─────────────────

from scripts.attribute_trades_to_signals import (
    classify_confidence,
    classify_outcome,
    load_signals,
    match_signals,
)


# ── Cohort helpers ────────────────────────────────────────────────────

def dte_bucket(dte: int) -> str:
    if dte <= 0:
        return "0DTE"
    if dte <= 2:
        return "1-2DTE"
    if dte <= 7:
        return "3-7DTE"
    if dte <= 14:
        return "8-14DTE"
    if dte <= 30:
        return "15-30DTE"
    return "30+DTE"


def hold_bucket(hold_minutes: int) -> str:
    # Broker CSVs day-rounded — hold_minutes is effectively 0 / 1440 / 2880...
    days = hold_minutes / 1440
    if days == 0:
        return "same-day"
    if days <= 1:
        return "overnight"
    if days <= 3:
        return "2-3 days"
    return "4+ days"


def cohort_table(rows: list[dict], dim: str, label: str, order: list[str] | None = None) -> list[str]:
    """Group rows by dim, return markdown table lines."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[dim]].append(r)
    keys = order if order else sorted(groups.keys(), key=lambda k: -sum(r["net_pnl"] for r in groups[k]))
    lines = [f"## By {label}", "",
             f"| {label} | N | Net P&L | WR% | Avg P&L | Big Wins | Big Losses |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for k in keys:
        if k not in groups:
            continue
        g = groups[k]
        n = len(g)
        pnl = sum(r["net_pnl"] for r in g)
        wins = sum(1 for r in g if r["net_pnl"] > 0)
        wr = wins / n * 100
        avg = pnl / n
        bw = sum(1 for r in g if r["outcome"] == "BIG_WIN")
        bl = sum(1 for r in g if r["outcome"] == "BIG_LOSS")
        lines.append(f"| {k} | {n} | ${pnl:+,.0f} | {wr:.0f}% | ${avg:+,.0f} | {bw} | {bl} |")
    lines.append("")
    return lines


def dte_at_entry(open_ts: int, expiration: str) -> int:
    open_date = datetime.date.fromtimestamp(open_ts)
    try:
        exp_date = datetime.date.fromisoformat(expiration)
    except (ValueError, TypeError):
        return -1
    return (exp_date - open_date).days


def signal_time_of_day(match_signal_ts: int | None) -> str | None:
    if not match_signal_ts:
        return None
    dt = datetime.datetime.fromtimestamp(match_signal_ts)
    mins = dt.hour * 60 + dt.minute
    if mins < 600:      # <10:00
        return "09:30-10:00 open"
    if mins < 690:      # <11:30
        return "10:00-11:30 morning"
    if mins < 810:      # <13:30
        return "11:30-13:30 lunch"
    if mins < 900:      # <15:00
        return "13:30-15:00 PM"
    if mins < 960:      # <16:00
        return "15:00-16:00 power hour"
    return "post-close"


def weekday_name(ts: int) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][datetime.date.fromtimestamp(ts).weekday()]


# ── Main ──────────────────────────────────────────────────────────────

def main():
    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row

    rts = [dict(r) for r in con.execute("SELECT * FROM broker_roundtrips").fetchall()]
    signals = load_signals(con)
    matched = match_signals(rts, signals)

    # Enrich with cohort fields
    for r in matched:
        r["outcome"] = classify_outcome(r["net_pnl"], r["pnl_pct"])
        r["dte"] = dte_at_entry(r["open_ts"], r["expiration"])
        r["dte_bucket"] = dte_bucket(r["dte"])
        r["hold_bucket"] = hold_bucket(r["hold_minutes"])
        r["weekday"] = weekday_name(r["open_ts"])
        r["time_of_day"] = signal_time_of_day(r.get("match_signal_ts"))

    total_pnl = sum(r["net_pnl"] for r in matched)
    wr_all = sum(1 for r in matched if r["net_pnl"] > 0) / len(matched) * 100

    md = []
    md.append("# Week Cohort Analysis — 2026-04-13 to 2026-04-17")
    md.append("")
    md.append(f"**Roundtrips:** {len(matched)} | **Net:** ${total_pnl:+,.2f} | **WR:** {wr_all:.1f}%")
    md.append("")
    md.append("Broker CSVs give date-only timestamps, so entry time-of-day uses the")
    md.append("matched SOE signal timestamp when confidence >= MEDIUM. Day-of-week")
    md.append("uses the broker trade date directly.")
    md.append("")

    # DTE at entry
    md += cohort_table(
        matched, "dte_bucket", "DTE at entry",
        order=["0DTE", "1-2DTE", "3-7DTE", "8-14DTE", "15-30DTE", "30+DTE"],
    )

    # Hold duration
    md += cohort_table(
        matched, "hold_bucket", "Hold duration",
        order=["same-day", "overnight", "2-3 days", "4+ days"],
    )

    # Direction (CALL vs PUT)
    md += cohort_table(matched, "option_type", "Direction",
                       order=["CALL", "PUT"])

    # Day of week
    md += cohort_table(matched, "weekday", "Day of week",
                       order=["Mon", "Tue", "Wed", "Thu", "Fri"])

    # Match confidence
    md += cohort_table(matched, "match_confidence", "Match confidence",
                       order=["STRONG", "MEDIUM", "WEAK", "NONE"])

    # Broker
    md += cohort_table(matched, "broker", "Broker")

    # Entry time-of-day (signal-inferred, only for non-MANUAL)
    with_tod = [r for r in matched if r["time_of_day"]]
    if with_tod:
        md += cohort_table(
            with_tod, "time_of_day", f"Entry time-of-day (n={len(with_tod)} with signal match)",
            order=["09:30-10:00 open", "10:00-11:30 morning",
                   "11:30-13:30 lunch", "13:30-15:00 PM",
                   "15:00-16:00 power hour", "post-close"],
        )

    # DTE × Direction cross-tab (puts specifically)
    md.append("## DTE × Direction (does short-DTE put buying kill us?)")
    md.append("")
    md.append("| Bucket | CALL N | CALL P&L | CALL WR | PUT N | PUT P&L | PUT WR |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    for b in ["0DTE", "1-2DTE", "3-7DTE", "8-14DTE", "15-30DTE", "30+DTE"]:
        calls = [r for r in matched if r["dte_bucket"] == b and r["option_type"] == "CALL"]
        puts = [r for r in matched if r["dte_bucket"] == b and r["option_type"] == "PUT"]
        def stats(rows):
            if not rows:
                return 0, 0, 0
            n = len(rows)
            p = sum(r["net_pnl"] for r in rows)
            w = sum(1 for r in rows if r["net_pnl"] > 0) / n * 100
            return n, p, w
        cn, cp, cw = stats(calls)
        pn, pp, pw = stats(puts)
        md.append(f"| {b} | {cn} | ${cp:+,.0f} | {cw:.0f}% | {pn} | ${pp:+,.0f} | {pw:.0f}% |")
    md.append("")

    # Ticker churn — ticker repeats
    md.append("## Ticker Repeat Behavior")
    md.append("")
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in matched:
        by_ticker[r["ticker"]].append(r)
    repeat_tickers = [(t, g) for t, g in by_ticker.items() if len(g) >= 3]
    repeat_tickers.sort(key=lambda x: -sum(r["net_pnl"] for r in x[1]))
    md.append(f"**Tickers traded 3+ times this week:** {len(repeat_tickers)}")
    md.append("")
    md.append("| Ticker | N | Net P&L | WR% | Wins | Losses | Avg Hold |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    for t, g in repeat_tickers:
        n = len(g)
        pnl = sum(r["net_pnl"] for r in g)
        wins = sum(1 for r in g if r["net_pnl"] > 0)
        losses = n - wins
        avg_hold = mean(r["hold_minutes"] for r in g) / 1440
        md.append(f"| {t} | {n} | ${pnl:+,.0f} | {wins/n*100:.0f}% | {wins} | {losses} | {avg_hold:.1f}d |")
    md.append("")

    # Scaled-in disasters (same strike + exp + type >= 3 trades)
    md.append("## Scaled-In Positions (same contract ≥3 entries)")
    md.append("")
    contract_key = lambda r: (r["ticker"], r["option_type"], r["strike"], r["expiration"])
    by_contract: dict[tuple, list[dict]] = defaultdict(list)
    for r in matched:
        by_contract[contract_key(r)].append(r)
    scaled = [(k, g) for k, g in by_contract.items() if len(g) >= 3]
    scaled.sort(key=lambda x: sum(r["net_pnl"] for r in x[1]))
    if scaled:
        md.append("| Contract | N | Net P&L | WR% | Avg Entry | First→Last Entry |")
        md.append("|---|---:|---:|---:|---:|---:|")
        for (tk, ot, strike, exp), g in scaled:
            g_sorted = sorted(g, key=lambda r: r["open_ts"])
            n = len(g)
            pnl = sum(r["net_pnl"] for r in g)
            wins = sum(1 for r in g if r["net_pnl"] > 0)
            avg_entry = mean(r["open_price"] for r in g)
            first_last = f"${g_sorted[0]['open_price']:.2f}→${g_sorted[-1]['open_price']:.2f}"
            md.append(f"| {tk} ${strike:g}{ot[0]} {exp} | {n} | ${pnl:+,.0f} | {wins/n*100:.0f}% | ${avg_entry:.2f} | {first_last} |")
        md.append("")
    else:
        md.append("_No contracts with ≥3 entries._")
        md.append("")

    # Signal lag distribution for winners vs losers
    md.append("## Signal Lag — Winners vs Losers (attributed trades only)")
    md.append("")
    md.append("*Lag = minutes between signal fire and broker entry. Negative = signal fired before entry.*")
    md.append("")
    attributed = [r for r in matched if r["match_time_lag_min"] is not None]
    winners = [r for r in attributed if r["net_pnl"] > 0]
    losers = [r for r in attributed if r["net_pnl"] <= 0]

    def lag_stats(rows):
        if not rows:
            return "—"
        lags = [abs(r["match_time_lag_min"]) for r in rows]
        return f"N={len(rows)}, median={median(lags):.0f}m, mean={mean(lags):.0f}m"

    md.append(f"- **Winners:** {lag_stats(winners)}")
    md.append(f"- **Losers:** {lag_stats(losers)}")
    md.append("")

    # Top-level findings callout block
    md.append("## Key Patterns")
    md.append("")
    findings = []

    # Pattern 1: PUT performance
    puts = [r for r in matched if r["option_type"] == "PUT"]
    calls = [r for r in matched if r["option_type"] == "CALL"]
    if puts and calls:
        p_wr = sum(1 for r in puts if r["net_pnl"] > 0) / len(puts) * 100
        c_wr = sum(1 for r in calls if r["net_pnl"] > 0) / len(calls) * 100
        p_pnl = sum(r["net_pnl"] for r in puts)
        c_pnl = sum(r["net_pnl"] for r in calls)
        findings.append(
            f"**PUT vs CALL gap:** {len(puts)} puts, {p_wr:.0f}% WR, ${p_pnl:+,.0f} vs "
            f"{len(calls)} calls, {c_wr:.0f}% WR, ${c_pnl:+,.0f}."
        )

    # Pattern 2: short-dated bleed
    zero = [r for r in matched if r["dte_bucket"] == "0DTE"]
    one_two = [r for r in matched if r["dte_bucket"] == "1-2DTE"]
    if zero or one_two:
        short = zero + one_two
        s_wr = sum(1 for r in short if r["net_pnl"] > 0) / len(short) * 100 if short else 0
        s_pnl = sum(r["net_pnl"] for r in short)
        findings.append(
            f"**Short-dated (0-2DTE):** {len(short)} trades, {s_wr:.0f}% WR, ${s_pnl:+,.0f}."
        )

    # Pattern 3: scale-in damage
    if scaled:
        scale_pnl = sum(r["net_pnl"] for g in [x[1] for x in scaled] for r in g)
        scale_n = sum(len(g) for _, g in scaled)
        findings.append(
            f"**Scale-in positions ({len(scaled)} contracts, {scale_n} fills):** total ${scale_pnl:+,.0f}."
        )

    # Pattern 4: weekday concentration
    by_wd = defaultdict(list)
    for r in matched:
        by_wd[r["weekday"]].append(r)
    wd_pnl = {wd: sum(r["net_pnl"] for r in g) for wd, g in by_wd.items()}
    best_wd = max(wd_pnl, key=wd_pnl.get)
    worst_wd = min(wd_pnl, key=wd_pnl.get)
    findings.append(
        f"**Weekday spread:** best = {best_wd} (${wd_pnl[best_wd]:+,.0f}), "
        f"worst = {worst_wd} (${wd_pnl[worst_wd]:+,.0f})."
    )

    # Pattern 5: overnight vs same-day
    same = [r for r in matched if r["hold_bucket"] == "same-day"]
    over = [r for r in matched if r["hold_bucket"] != "same-day"]
    if same and over:
        s_wr = sum(1 for r in same if r["net_pnl"] > 0) / len(same) * 100
        o_wr = sum(1 for r in over if r["net_pnl"] > 0) / len(over) * 100
        findings.append(
            f"**Hold duration:** same-day {len(same)} trades {s_wr:.0f}% WR "
            f"${sum(r['net_pnl'] for r in same):+,.0f}; held {len(over)} trades "
            f"{o_wr:.0f}% WR ${sum(r['net_pnl'] for r in over):+,.0f}."
        )

    for f in findings:
        md.append(f"- {f}")
    md.append("")

    md.append("## Caveats")
    md.append("")
    md.append("- **Sample size**: 91 trades / 5 days. Cells with N<5 are noise.")
    md.append("- **Time-of-day is approximate**: uses matched SOE signal timestamp")
    md.append("  when available (MEDIUM+ confidence); broker timestamps are day-only.")
    md.append("- **Survivorship**: only trades taken. Signals skipped aren't here.")
    md.append("- **Scale-in contracts**: FIFO-paired at import, so partial-fill")
    md.append("  sequences may split across multiple roundtrips (each fill → one rt).")
    md.append("")

    out_path = Path("docs/research/week_cohort_analysis.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out_path}")
    con.close()


if __name__ == "__main__":
    main()
