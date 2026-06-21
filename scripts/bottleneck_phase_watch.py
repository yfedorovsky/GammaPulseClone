"""Bottleneck Phase-2 watch (framework #4) — surfaces when an asymmetric chokepoint
name is MOVING in the flow the system already captures.

WHY: the bottleneck playbook's validation-sequencing framework says the highest
risk-adjusted entry is the Serenity Phase 1->2 transition (first institutional buying
/ formal partnership / earnings beat). A fully-automated Phase-2 detector would need a
13F / news feed we don't have. So this is the HONEST operational version: read the live
flow_alerts (read-only) and report which bottleneck-universe names showed flow activity,
HIGHLIGHTING the Phase 1-2 asymmetric set — because flow waking up on a pre-consensus
chokepoint name is your cue to go check the MANUAL confirmation signal.

This is a CONTEXT report. It does NOT trigger trades and is NOT wired into Telegram
(structure detects context, it does not predict). The Phase-2 CONFIRMATION itself
(13F / partnership / earnings) stays manual.

Run:
  python scripts/bottleneck_phase_watch.py             # last 5 days (default)
  python scripts/bottleneck_phase_watch.py --days 1    # just the most recent session
  python scripts/bottleneck_phase_watch.py --watch-only  # only Phase 1-2 (asymmetric) names
  python scripts/bottleneck_phase_watch.py --json

NOT investment advice. DYODD.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bottleneck_scorecard import context_for, universe_tickers, PHASE_WATCH_MAX  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snapshots.db")


# ─────────────────────────────────────────────────────────────────────────────
# Pure logic (unit-testable without a DB)
# ─────────────────────────────────────────────────────────────────────────────

def summarize_flow(rows: list[dict]) -> dict[str, dict]:
    """Aggregate raw flow_alerts rows into a per-ticker summary.

    Each row: {ticker, sentiment, conviction, notional, is_sweep, is_insider, is_whale}.
    """
    agg: dict[str, dict] = {}
    for r in rows:
        tk = (r.get("ticker") or "").upper()
        if not tk:
            continue
        a = agg.setdefault(tk, {"ticker": tk, "n": 0, "notional": 0.0,
                                "sentiments": Counter(), "convictions": Counter(),
                                "sweep": False, "insider": False, "whale": False})
        a["n"] += 1
        a["notional"] += float(r.get("notional") or 0)
        if r.get("sentiment"):
            a["sentiments"][str(r["sentiment"]).upper()] += 1
        if r.get("conviction"):
            a["convictions"][str(r["conviction"]).upper()] += 1
        a["sweep"] = a["sweep"] or bool(r.get("is_sweep"))
        a["insider"] = a["insider"] or bool(r.get("is_insider"))
        a["whale"] = a["whale"] or bool(r.get("is_whale"))
    for a in agg.values():
        a["dominant_sentiment"] = a["sentiments"].most_common(1)[0][0] if a["sentiments"] else "?"
    return agg


def build_watch(agg: dict[str, dict], watch_only: bool = False) -> list[dict]:
    """Join per-ticker flow summaries to the bottleneck context, flag the Phase 1-2
    asymmetric set, and sort (watch-set first by phase, then by notional desc)."""
    out = []
    for tk, a in agg.items():
        ctx = context_for(tk)
        if ctx is None:
            continue  # not a bottleneck-universe name
        is_watch = ctx["phase"] <= PHASE_WATCH_MAX
        if watch_only and not is_watch:
            continue
        out.append({
            "ticker": tk, "layer": ctx["layer"], "phase": ctx["phase"],
            "conviction": ctx["conviction"], "role": ctx["role"],
            "is_watch": is_watch, "validation_signal": ctx["watch"],
            "n": a["n"], "notional": a["notional"],
            "dominant_sentiment": a["dominant_sentiment"],
            "sweep": a["sweep"], "insider": a["insider"], "whale": a["whale"],
        })
    # watch-set first (lowest phase first = most asymmetric), then biggest flow
    out.sort(key=lambda r: (not r["is_watch"], r["phase"], -r["notional"]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DB read (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def load_flow(db_path: str, days: float) -> list[dict]:
    tickers = universe_tickers()
    cutoff = time.time() - days * 86400
    qmarks = ",".join("?" * len(tickers))
    sql = (f"SELECT ticker, sentiment, conviction, notional, is_sweep, is_insider, is_whale "
           f"FROM flow_alerts WHERE ticker IN ({qmarks}) AND ts >= ?")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        cur = conn.execute(sql, (*tickers, cutoff))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_notional(v: float) -> str:
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Bottleneck Phase-2 context watch (framework #4)")
    ap.add_argument("--days", type=float, default=5.0, help="lookback window in days (default 5)")
    ap.add_argument("--watch-only", action="store_true", help="only Phase 1-2 (asymmetric) names")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        rows = load_flow(args.db, args.days)
    except Exception as e:
        print(f"[phase-watch] flow_alerts read failed: {e!r}", flush=True)
        return 1

    watch = build_watch(summarize_flow(rows), watch_only=args.watch_only)

    if args.json:
        print(json.dumps({"days": args.days, "rows": watch}, indent=2, default=str))
        return 0

    print(f"BOTTLENECK PHASE-2 WATCH - flow last {args.days:g}d  (CONTEXT report, not a trigger; NIA)")
    print("=" * 100)
    if not rows:
        print("No flow_alerts for any bottleneck-universe name in the window "
              "(weekend/holiday/off-hours, or no recent session). Try a larger --days.")
        return 0

    watch_set = [r for r in watch if r["is_watch"]]
    rest = [r for r in watch if not r["is_watch"]]

    def line(r):
        tags = "".join(t for t, on in (("S", r["sweep"]), ("I", r["insider"]), ("W", r["whale"])) if on) or "-"
        conv = "*" * r["conviction"]
        print(f"  {r['ticker']:6s} P{r['phase']} {r['layer']:10s} {conv:5s} "
              f"flow={r['n']:>5d} {_fmt_notional(r['notional']):>7s} {r['dominant_sentiment']:8s} [{tags:3s}]")
        print(f"         > confirm: {r['validation_signal']}")

    print("PHASE 1-2 ASYMMETRIC WATCH (flow is moving on a pre-consensus chokepoint -> "
          "go CHECK for institutional/partnership/earnings confirmation):")
    if watch_set:
        for r in watch_set:
            line(r)
    else:
        print("  (none active in window)")

    if not args.watch_only and rest:
        print("\nPhase 3 consensus names also active (context only, asymmetry already priced):")
        for r in rest:
            conv = "*" * r["conviction"]
            print(f"  {r['ticker']:6s} P{r['phase']} {r['layer']:10s} {conv:5s} "
                  f"flow={r['n']:>5d} {_fmt_notional(r['notional']):>7s} {r['dominant_sentiment']}")

    print("-" * 100)
    print("Tags: S=sweep I=insider W=whale present in window. CONV *=1..5.")
    print("The Phase-2 CONFIRMATION (13F / formal partnership / earnings beat) is MANUAL — "
          "this only flags WHEN to go look. NIA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
