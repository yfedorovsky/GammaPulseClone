"""Cross-reference broker roundtrips with Telegram signal sources.

For each of the user's 91 matched roundtrips this week, find the closest
signal from multiple sources and attribute the trade to a pathway:

  - SOE A / A+ / B+ (grade-specific)
  - Mir Discord (mir_signal_cache)
  - Runner tracker (runner_tracker DAY1_BREAKOUT)
  - Scalp alerts (proxy via soe_signals SCALP grade)
  - Manual (no signal within window)

Classifies outcomes by P&L tier:
  BIG_WIN        net_pnl >= $500 OR pnl_pct >= +50%
  WIN            net_pnl > $0   AND pnl_pct < +50%
  SCRATCH        abs(net_pnl) <= $50
  LOSS           net_pnl < -$50 AND pnl_pct > -50%
  BIG_LOSS       pnl_pct <= -50%

Output: scorecard per pathway + per-ticker with actual broker P&L.

Usage:
    python -m scripts.attribute_trades_to_signals

Writes: docs/research/week_trade_attribution.md
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────

TIME_WINDOW_SECONDS = 7200  # ±2 hours — signal relevance window before entry
STRIKE_PROXIMITY = 5.0       # $5 for strong match


def classify_outcome(net_pnl: float, pnl_pct: float) -> str:
    if net_pnl >= 500 or pnl_pct >= 50:
        return "BIG_WIN"
    if pnl_pct <= -50:
        return "BIG_LOSS"
    if abs(net_pnl) <= 50:
        return "SCRATCH"
    if net_pnl > 0:
        return "WIN"
    return "LOSS"


def classify_confidence(rt: dict, sig: dict) -> str:
    """How strongly does this signal match this roundtrip?

    Broker CSVs only give us trade DATE (no intraday time), so open_ts is
    midnight. We match via SAME-DAY windowing + strike/type proximity.

    STRONG:  same ticker, same option_type, strike within $5, SAME EXPIRY
    MEDIUM:  same ticker, (option_type AND strike within $5) OR (type match + exp match)
    WEAK:    same ticker only (date-matched via outer filter)
    """
    ticker_match = rt["ticker"] == sig["ticker"]
    if not ticker_match:
        return "NONE"
    type_match = (rt["option_type"].upper() == (sig.get("option_type") or "").upper())
    strike_diff = abs(rt["strike"] - (sig.get("strike") or rt["strike"]))
    strike_close = strike_diff <= STRIKE_PROXIMITY
    exp_match = (sig.get("expiration") == rt["expiration"])

    if type_match and strike_close and exp_match:
        return "STRONG"
    if (type_match and strike_close) or (type_match and exp_match):
        return "MEDIUM"
    return "WEAK"


def load_signals(con: sqlite3.Connection) -> list[dict]:
    """Merge signals from all available sources into a unified list:
      - SOE signals (A/A+/B+)
      - Mir Discord (mir_signal_cache)
      - Runner tracker DAY1 entries
      - Flow alerts (flow_alerts table, conviction=HIGH)
      - Sweeps (signal_outcomes WHERE source_type='sweep')
      - Golden Flow (option_flow_daily re-classified via is_golden_flow)
      - Big Flow (option_flow_daily with notional >= $500K, not Golden)

    Precedence for an overlapping signal: first to fire wins in
    classify_confidence (STRONG > MEDIUM > WEAK).
    """
    signals: list[dict] = []

    # SOE signals (all grades A, A+, B+)
    rows = con.execute("""
        SELECT ts, ticker, grade, direction, strike, option_type, expiration,
               target, stop, rr_ratio, spot, entry_price
        FROM soe_signals
        WHERE ts >= strftime('%s', '2026-04-13')
          AND grade IN ('A', 'A+', 'B+')
          AND ticker IS NOT NULL
    """).fetchall()
    for r in rows:
        signals.append({
            "ts": r["ts"],
            "ticker": r["ticker"],
            "source": f"SOE_{r['grade']}",
            "grade": r["grade"],
            "strike": r["strike"],
            "option_type": r["option_type"],
            "expiration": r["expiration"],
            "target": r["target"],
            "stop": r["stop"],
            "rr": r["rr_ratio"],
        })

    # Mir Discord signals
    rows = con.execute("""
        SELECT ts, ticker, data
        FROM mir_signal_cache
        WHERE ts >= strftime('%s', '2026-04-13')
    """).fetchall()
    for r in rows:
        try:
            d = json.loads(r["data"])
        except Exception:
            continue
        # Tag CHAT_RELAY separately so it shows up as its own cohort.
        # Those are low-conviction mentions (priority 3 from Apr 18 session).
        is_chat = d.get("signal_type") == "CHAT_RELAY" or d.get("agreement") == "CHAT_RELAY"
        signals.append({
            "ts": int(r["ts"]),
            "ticker": r["ticker"],
            "source": "MIR_CHAT" if is_chat else "MIR_DISCORD",
            "grade": d.get("conviction", "HIGH"),
            "strike": d.get("strike"),
            "option_type": d.get("option_type"),
            "expiration": d.get("expiry"),
            "raw": d.get("raw", "")[:200],
        })

    # Runner tracker DAY1 entries
    rows = con.execute("""
        SELECT entry_ts, ticker, entry_path, runner_shape,
               d1_gain_pct, d1_rvol, runner_score
        FROM runner_tracker
        WHERE entry_ts >= strftime('%s', '2026-04-13')
    """).fetchall()
    for r in rows:
        signals.append({
            "ts": r["entry_ts"],
            "ticker": r["ticker"],
            "source": f"RUNNER_{r['entry_path']}",
            "grade": r["runner_shape"] or "MEASURED",
            "strike": None,
            "option_type": None,
            "expiration": None,
            "gain_pct": r["d1_gain_pct"],
            "rvol": r["d1_rvol"],
            "runner_score": r["runner_score"],
        })

    # Flow alerts (HIGH conviction only — LOW/MED are noise by design)
    rows = con.execute("""
        SELECT ts, ticker, strike, expiration, option_type, sentiment,
               conviction, notional, is_sweep
        FROM flow_alerts
        WHERE ts >= strftime('%s', '2026-04-13')
          AND conviction = 'HIGH'
          AND ticker IS NOT NULL
    """).fetchall()
    for r in rows:
        signals.append({
            "ts": r["ts"],
            "ticker": r["ticker"],
            "source": "FLOW_SWEEP" if r["is_sweep"] else "FLOW_ALERT",
            "grade": r["conviction"],
            "strike": r["strike"],
            "option_type": r["option_type"],
            "expiration": r["expiration"],
            "sentiment": r["sentiment"],
            "notional": r["notional"],
        })

    # Sweeps from signal_outcomes (the dedicated sweep detector — ISO-only)
    # Dedupe against flow_alerts table by ticker+ts bucket so we don't
    # double-count the same trade across sources.
    rows = con.execute("""
        SELECT trigger_ts, ticker, direction, trigger_price, notional,
               sweep_venues, source_id
        FROM signal_outcomes
        WHERE source_type = 'sweep'
          AND trigger_ts >= strftime('%s', '2026-04-13')
          AND ticker IS NOT NULL
    """).fetchall()
    for r in rows:
        signals.append({
            "ts": r["trigger_ts"],
            "ticker": r["ticker"],
            "source": "ISO_SWEEP",
            "grade": "HIGH" if (r["sweep_venues"] or 0) >= 3 else "MEDIUM",
            # Sweep detector doesn't carry strike/type/exp — matches on ticker+day only.
            "strike": None,
            "option_type": None,
            "expiration": None,
            "direction": r["direction"],
            "notional": r["notional"],
            "sweep_venues": r["sweep_venues"],
        })

    # Golden Flow — recompute via is_golden_flow() on option_flow_daily aggregates
    from server.option_flow_daily import is_golden_flow
    rows = con.execute("""
        SELECT date, ticker, strike, expiration, option_type, total_notional,
               buy_notional, sell_notional, total_volume, oi, spot,
               largest_print_time, largest_print_side, sweep_notional,
               largest_print_is_sweep
        FROM option_flow_daily
        WHERE date >= '2026-04-13' AND date <= '2026-04-17'
    """).fetchall()
    for r in rows:
        row_dict = dict(r)
        is_gold, _failed = is_golden_flow(row_dict)

        # Signal ts: prefer largest_print_time (ISO string), else midnight-of-date
        sig_ts = None
        lpt = r["largest_print_time"]
        if lpt:
            try:
                sig_ts = int(datetime.datetime.fromisoformat(
                    lpt.replace("Z", "+00:00") if "Z" in lpt else lpt
                ).timestamp())
            except (ValueError, TypeError):
                pass
        if not sig_ts:
            sig_ts = int(datetime.datetime.fromisoformat(r["date"]).timestamp())

        buy = r["buy_notional"] or 0
        sell = r["sell_notional"] or 0
        directional = buy + sell
        bought_pct = (buy / directional) if directional > 0 else 0
        inferred_direction = (
            "BUY" if bought_pct >= 0.65
            else "SELL" if bought_pct <= 0.35
            else "NEUTRAL"
        )

        if is_gold:
            source = "GOLDEN_FLOW"
            grade = "HIGH"
        elif (r["total_notional"] or 0) >= 500_000:
            source = "BIG_FLOW"
            grade = "MEDIUM"
        else:
            continue  # skip tiny aggregates

        signals.append({
            "ts": sig_ts,
            "ticker": r["ticker"],
            "source": source,
            "grade": grade,
            "strike": r["strike"],
            "option_type": r["option_type"],
            "expiration": r["expiration"],
            "direction": inferred_direction,
            "notional": r["total_notional"],
            "bought_pct": bought_pct,
        })

    return signals


def match_signals(roundtrips: list[dict], signals: list[dict]) -> list[dict]:
    """For each roundtrip, find the best-matching signal within the time window.

    Returns roundtrips with added fields: matched_source, matched_grade,
    match_confidence, match_signal (full dict or None)."""
    # Index signals by ticker for fast lookup
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        by_ticker[s["ticker"]].append(s)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda s: s["ts"])

    results = []
    for rt in roundtrips:
        candidates = by_ticker.get(rt["ticker"], [])
        # Same-day window: broker CSV only gives date, so open_ts is midnight.
        # Match signals from start of trade date through end of trade date.
        rt_date = datetime.date.fromtimestamp(rt["open_ts"])
        window_start = int(datetime.datetime.combine(
            rt_date, datetime.time(0, 0)).timestamp())
        window_end = int(datetime.datetime.combine(
            rt_date, datetime.time(23, 59, 59)).timestamp())
        in_window = [s for s in candidates
                     if window_start <= s["ts"] <= window_end]

        best = None
        best_conf = "NONE"
        conf_order = {"NONE": 0, "WEAK": 1, "MEDIUM": 2, "STRONG": 3}

        for s in in_window:
            conf = classify_confidence(rt, s)
            if conf_order[conf] > conf_order[best_conf]:
                best_conf = conf
                best = s
            elif conf_order[conf] == conf_order[best_conf] and best is not None:
                # Tie-break: prefer closer in time, then higher grade
                cur_diff = abs(rt["open_ts"] - best["ts"])
                new_diff = abs(rt["open_ts"] - s["ts"])
                if new_diff < cur_diff:
                    best = s

        result = dict(rt)
        result["match_source"] = best["source"] if best else "MANUAL"
        result["match_grade"] = best.get("grade") if best else None
        result["match_confidence"] = best_conf
        result["match_signal_ts"] = best["ts"] if best else None
        result["match_time_lag_min"] = int((rt["open_ts"] - best["ts"]) / 60) if best else None
        results.append(result)
    return results


def report(matched: list[dict]) -> str:
    """Produce a markdown scorecard."""
    # Classify each trade
    for rt in matched:
        rt["outcome"] = classify_outcome(rt["net_pnl"], rt["pnl_pct"])

    # ── Pathway scorecard ──────────────────────────────────────────────
    by_source: dict[str, list[dict]] = defaultdict(list)
    for rt in matched:
        by_source[rt["match_source"]].append(rt)

    md = []
    md.append(f"# Weekly Trade Attribution — {datetime.date.today().isoformat()}")
    md.append("")
    md.append(f"**Period:** 2026-04-13 to 2026-04-17")
    md.append(f"**Roundtrips analyzed:** {len(matched)}")
    md.append(f"**Total net P&L:** ${sum(rt['net_pnl'] for rt in matched):+,.2f}")
    md.append("")
    md.append("## Outcome Buckets")
    md.append("")
    bucket_counts = defaultdict(int)
    bucket_pnl = defaultdict(float)
    for rt in matched:
        bucket_counts[rt["outcome"]] += 1
        bucket_pnl[rt["outcome"]] += rt["net_pnl"]
    md.append("| Outcome | Count | Total P&L | Avg P&L |")
    md.append("|---|---:|---:|---:|")
    for b in ["BIG_WIN", "WIN", "SCRATCH", "LOSS", "BIG_LOSS"]:
        c = bucket_counts[b]
        p = bucket_pnl[b]
        a = p / c if c > 0 else 0
        md.append(f"| **{b}** | {c} | ${p:+,.2f} | ${a:+,.2f} |")
    md.append("")

    # ── Per-source scorecard ──────────────────────────────────────────
    md.append("## Scorecard By Signal Source")
    md.append("")
    md.append("| Source | Trades | Net P&L | Win Rate | Big Wins | Big Losses | Avg P&L |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    ordered_sources = sorted(by_source.keys(),
                             key=lambda s: -sum(r["net_pnl"] for r in by_source[s]))
    for src in ordered_sources:
        rts = by_source[src]
        n = len(rts)
        pnl = sum(r["net_pnl"] for r in rts)
        wins = sum(1 for r in rts if r["net_pnl"] > 0)
        bwins = sum(1 for r in rts if r["outcome"] == "BIG_WIN")
        blosses = sum(1 for r in rts if r["outcome"] == "BIG_LOSS")
        wr = wins / n * 100 if n else 0
        avg = pnl / n if n else 0
        md.append(f"| **{src}** | {n} | ${pnl:+,.2f} | {wr:.0f}% | {bwins} | {blosses} | ${avg:+,.2f} |")
    md.append("")

    # ── Big Wins detail ──────────────────────────────────────────────
    md.append("## Big Wins — What Worked")
    md.append("")
    big_wins = [rt for rt in matched if rt["outcome"] == "BIG_WIN"]
    big_wins.sort(key=lambda x: -x["net_pnl"])
    md.append(f"*{len(big_wins)} big wins (>$500 or >+50%)*")
    md.append("")
    md.append("| Ticker | Strike | Exp | Type | P&L | % | Source | Conf | Lag |")
    md.append("|---|---:|---|---|---:|---:|---|---|---:|")
    for rt in big_wins:
        lag = f"{rt['match_time_lag_min']}m" if rt['match_time_lag_min'] is not None else "—"
        md.append(
            f"| {rt['ticker']} | ${rt['strike']:g} | {rt['expiration']} | "
            f"{rt['option_type'][0]} | ${rt['net_pnl']:+.0f} | {rt['pnl_pct']:+.0f}% | "
            f"{rt['match_source']} | {rt['match_confidence']} | {lag} |"
        )
    md.append("")

    # ── Big Losses detail ────────────────────────────────────────────
    md.append("## Big Losses — What To Cut")
    md.append("")
    big_losses = [rt for rt in matched if rt["outcome"] == "BIG_LOSS"]
    big_losses.sort(key=lambda x: x["net_pnl"])
    md.append(f"*{len(big_losses)} big losses (<-50%)*")
    md.append("")
    md.append("| Ticker | Strike | Exp | Type | P&L | % | Source | Conf | Lag |")
    md.append("|---|---:|---|---|---:|---:|---|---|---:|")
    for rt in big_losses:
        lag = f"{rt['match_time_lag_min']}m" if rt['match_time_lag_min'] is not None else "—"
        md.append(
            f"| {rt['ticker']} | ${rt['strike']:g} | {rt['expiration']} | "
            f"{rt['option_type'][0]} | ${rt['net_pnl']:+.0f} | {rt['pnl_pct']:+.0f}% | "
            f"{rt['match_source']} | {rt['match_confidence']} | {lag} |"
        )
    md.append("")

    # ── By ticker ─────────────────────────────────────────────────────
    md.append("## By Ticker")
    md.append("")
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for rt in matched:
        by_ticker[rt["ticker"]].append(rt)
    md.append("| Ticker | Trades | Net P&L | WR% | Primary Source |")
    md.append("|---|---:|---:|---:|---|")
    for t in sorted(by_ticker.keys(), key=lambda x: -sum(r["net_pnl"] for r in by_ticker[x])):
        rts = by_ticker[t]
        n = len(rts)
        pnl = sum(r["net_pnl"] for r in rts)
        wins = sum(1 for r in rts if r["net_pnl"] > 0)
        wr = wins / n * 100 if n else 0
        # Most common source
        src_counts = defaultdict(int)
        for r in rts:
            src_counts[r["match_source"]] += 1
        top_src = max(src_counts.items(), key=lambda x: x[1])[0]
        md.append(f"| {t} | {n} | ${pnl:+,.2f} | {wr:.0f}% | {top_src} |")
    md.append("")

    # ── Noise vs signal summary ───────────────────────────────────────
    md.append("## Filter Recommendations")
    md.append("")
    total_manual = sum(1 for rt in matched if rt["match_source"] == "MANUAL")
    total_manual_pnl = sum(rt["net_pnl"] for rt in matched if rt["match_source"] == "MANUAL")
    md.append(f"**Manual trades (no matched signal):** {total_manual} trades, ${total_manual_pnl:+,.2f}")
    md.append("")
    md.append("### Best pathways (keep, promote):")
    for src in ordered_sources[:3]:
        rts = by_source[src]
        pnl = sum(r["net_pnl"] for r in rts)
        wr = sum(1 for r in rts if r["net_pnl"] > 0) / len(rts) * 100
        md.append(f"- **{src}**: {len(rts)} trades, ${pnl:+,.2f}, {wr:.0f}% WR")
    md.append("")
    md.append("### Worst pathways (filter out or kill):")
    for src in ordered_sources[-3:]:
        rts = by_source[src]
        pnl = sum(r["net_pnl"] for r in rts)
        wr = sum(1 for r in rts if r["net_pnl"] > 0) / len(rts) * 100
        md.append(f"- **{src}**: {len(rts)} trades, ${pnl:+,.2f}, {wr:.0f}% WR")
    md.append("")

    return "\n".join(md)


def main():
    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row

    # Load roundtrips
    rts = con.execute("SELECT * FROM broker_roundtrips").fetchall()
    roundtrips = [dict(r) for r in rts]
    print(f"Loaded {len(roundtrips)} roundtrips")

    # Load signals
    signals = load_signals(con)
    print(f"Loaded {len(signals)} signals from multiple sources")

    # Match
    matched = match_signals(roundtrips, signals)

    # Classify outcomes
    for rt in matched:
        rt["outcome"] = classify_outcome(rt["net_pnl"], rt["pnl_pct"])

    # Print quick summary to stdout
    from collections import Counter
    src_counts = Counter(rt["match_source"] for rt in matched)
    outcome_counts = Counter(rt["outcome"] for rt in matched)
    conf_counts = Counter(rt["match_confidence"] for rt in matched)
    print()
    print("Match confidence distribution:")
    for k, v in conf_counts.most_common():
        print(f"  {k}: {v}")
    print()
    print("Source attribution:")
    for k, v in src_counts.most_common():
        print(f"  {k}: {v}")
    print()
    print("Outcome distribution:")
    for k, v in outcome_counts.most_common():
        pnl = sum(rt["net_pnl"] for rt in matched if rt["outcome"] == k)
        print(f"  {k}: {v} trades, ${pnl:+,.2f}")
    print()
    # Per-source breakdown
    print("Per-source P&L:")
    by_source: dict[str, list[dict]] = defaultdict(list)
    for rt in matched: by_source[rt["match_source"]].append(rt)
    for src in sorted(by_source.keys(), key=lambda s: -sum(r["net_pnl"] for r in by_source[s])):
        rts = by_source[src]
        n = len(rts)
        pnl = sum(r["net_pnl"] for r in rts)
        wins = sum(1 for r in rts if r["net_pnl"] > 0)
        wr = wins / n * 100 if n else 0
        print(f"  {src:18s}: {n:2d} trades, ${pnl:+9,.2f}, WR {wr:.0f}%")

    # Write markdown report
    out = report(matched)
    out_path = Path("docs/research/week_trade_attribution.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    print(f"\nReport saved: {out_path}")

    con.close()


if __name__ == "__main__":
    main()
