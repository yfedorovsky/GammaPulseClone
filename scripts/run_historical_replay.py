"""Historical replay — YTD signature backtest CLI (charter: HISTORICAL_REPLAY.md).

Phases (each resumable; all caches idempotent):
  1. FETCH  — bulk EOD chains for the universe into the durable store
              (autoresearch/_artifacts/hist_chains/chains.db). First YTD run is
              an overnight job; re-runs are instant.
  2. SCAN   — the PORTED live whale/informed signature over every cached day.
  3. REPLAY — tape fire-time + side per candidate (no look-ahead), C5 clusters,
              multiday option-PnL outcomes (censoring rule).
  4. GATE   — the full validation gate incl. LABEL_CONF; verdict matrix format.

Usage (venv + ThetaData Terminal up):
  .venv-autoresearch/Scripts/python scripts/run_historical_replay.py \
      --cohort WHALE --start 2026-01-02 --end 2026-06-09 --universe top150 \
      --hold-days 3
  --fetch-only        run phase 1 and stop (the overnight pre-fetch)
  --no-fetch          assume the cache is populated (phases 2-4 only)
  --universe          top<N> (by live flow_alerts notional, ex index/levered)
                      or comma list (NVDA,MSTR,...) or @file (one root/line)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from autoresearch.replay.chain_fetcher import (  # noqa: E402
    FetchConfig, FetchStats, fetch_root, open_store, trading_days,
)
from autoresearch.replay.signature_scan import (  # noqa: E402
    WHALE_EXCLUDED_TICKERS, scan_day,
)
from autoresearch.replay.replay_cohorts import (  # noqa: E402
    build_replay_clusters, build_replay_candidate,
)
from autoresearch.gate import TestCard, GateConfig, ValidationGate  # noqa: E402
from autoresearch.trials_ledger import TrialLedger  # noqa: E402
from autoresearch.option_pnl import ThetaNBBOSource  # noqa: E402
from autoresearch.side_confirmation import ThetaTradeTapeSource  # noqa: E402

SNAPSHOTS_DB = r"C:\Dev\GammaPulse\snapshots.db"
_ART = Path(__file__).resolve().parent.parent / "autoresearch" / "_artifacts"


def _keep_awake() -> None:
    """Inhibit system sleep while fetching (the 6/10 overnight run died to
    machine sleep). Reverts automatically when the process exits."""
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        print("[fetch] keep-awake set (system sleep inhibited)", flush=True)
    except Exception as e:
        print(f"[fetch] keep-awake unavailable: {e!r}", flush=True)


def _rth_pause(enabled: bool) -> None:
    """Block while US RTH is in session (09:20-16:05 ET, weekdays).

    The LIVE trading system shares this ThetaData terminal — a daytime bulk
    fetch would compete with its sub-30s latency edge. Charter says overnight."""
    if not enabled:
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo
    announced = False
    while True:
        now = datetime.now(ZoneInfo("America/New_York"))
        mins = now.hour * 60 + now.minute
        in_rth = now.weekday() < 5 and (9 * 60 + 20) <= mins < (16 * 60 + 5)
        if not in_rth:
            if announced:
                print(f"[fetch] RTH over — resuming ({now:%H:%M} ET)", flush=True)
            return
        if not announced:
            print(f"[fetch] RTH PAUSE — live terminal has priority until "
                  f"16:05 ET (now {now:%H:%M} ET)", flush=True)
            announced = True
        time.sleep(300)


def resolve_universe(spec: str) -> list[str]:
    if spec.startswith("@"):
        return [l.strip().upper() for l in Path(spec[1:]).read_text().splitlines()
                if l.strip()]
    if spec.lower().startswith("top"):
        n = int(spec[3:])
        con = sqlite3.connect("file:" + SNAPSHOTS_DB.replace("\\", "/") + "?mode=ro",
                              uri=True)
        try:
            rows = con.execute(
                "SELECT ticker, SUM(notional) FROM flow_alerts "
                "GROUP BY ticker ORDER BY 2 DESC").fetchall()
        finally:
            con.close()
        out = [t for t, _ in rows if t and t.upper() not in WHALE_EXCLUDED_TICKERS]
        return out[:n]
    return [t.strip().upper() for t in spec.split(",") if t.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", choices=("WHALE", "INFORMED"), default="WHALE")
    ap.add_argument("--start", default="2026-01-02")
    ap.add_argument("--end", default="2026-06-09")
    ap.add_argument("--universe", default="top150")
    ap.add_argument("--hold-days", type=int, default=3)
    ap.add_argument("--baseline", default="SOE_A")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--bulk", action="store_true",
                    help="FAST fetch via expiration=* (whole chain per root-day, "
                         "1 request vs ~25) + 6 concurrent (PRO budget). ~10x "
                         "fewer requests; 150 roots x 5 days = ~90s. Default for "
                         "new fetches; the legacy per-expiration path remains for "
                         "reference.")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent requests for --bulk (PRO allows 8 account-"
                         "wide; default 6 leaves headroom for the live system)")
    ap.add_argument("--no-rth-pause", action="store_true",
                    help="fetch through market hours too (default: pause "
                         "09:20-16:05 ET — the live system owns the terminal)")
    ap.add_argument("--cap-tape", type=int, default=None,
                    help="safety cap on tape-verified candidates (most-recent "
                         "first dropped LAST; logged when it truncates)")
    ap.add_argument("--min-notional", type=float, default=None,
                    help="candidate notional floor before the tape stage. "
                         "Default: 3e6 for WHALE (the live TELEGRAM tier — the "
                         "alerts the operator actually receives; the $1M tier "
                         "is DB-audit only), no floor for INFORMED.")
    ap.add_argument("--top-k-day", type=int, default=2,
                    help="tape at most K candidates per (root, day, right), "
                         "largest notional first (WHALE) / score then notional "
                         "(INFORMED). The C5 cluster representative is "
                         "essentially always among the day's largest prints; "
                         "0 = no cap. Approximation documented in "
                         "REPLAY_FINDINGS.md.")
    ap.add_argument("--seed-n", type=int, default=300)
    ap.add_argument("--spa-reps", type=int, default=1000)
    ap.add_argument("--ledger", default=str(_ART / "demo_ledger.json"))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    roots = resolve_universe(args.universe)
    print(f"[replay] universe: {len(roots)} roots "
          f"({', '.join(roots[:8])}{', ...' if len(roots) > 8 else ''})",
          flush=True)
    con = open_store()

    # ── Phase 1: FETCH ────────────────────────────────────────────────────
    if not args.no_fetch:
        cfg = FetchConfig()
        cfg.max_workers = args.workers
        stats = FetchStats()
        t0 = time.time()
        _keep_awake()
        _rth_pause(not args.no_rth_pause)   # bulk is a short burst; pause once up front.
        if args.bulk:
            from autoresearch.replay.chain_fetcher import fetch_universe_bulk

            def _prog(done, total, st):
                print(f"[bulk {done}/{total}] rows={st.n_rows} fail={st.n_failures} "
                      f"({time.time()-t0:.0f}s)", flush=True)
            fetch_universe_bulk(con, roots, args.start, args.end, cfg, stats,
                                progress=_prog)
        else:
            for i, root in enumerate(roots, 1):
                _rth_pause(not args.no_rth_pause)
                fetch_root(con, root, args.start, args.end, cfg, stats)
                print(f"[fetch {i}/{len(roots)}] {root}: cum reqs={stats.n_requests} "
                      f"cached={stats.n_cached_skips} rows={stats.n_rows} "
                      f"fail={stats.n_failures} ({time.time()-t0:.0f}s)", flush=True)
        print(f"[fetch] DONE — {stats.n_requests} requests, {stats.n_rows} rows, "
              f"{stats.n_failures} failures, {stats.n_cached_skips} cache skips "
              f"({time.time()-t0:.0f}s)", flush=True)
        if stats.failures:
            print(f"[fetch] failed keys (will retry on next run): "
                  f"{stats.failures[:10]}{'...' if len(stats.failures) > 10 else ''}")
    if args.fetch_only:
        con.close()
        return 0

    # ── Phase 2: SCAN ─────────────────────────────────────────────────────
    days = trading_days(con, args.start, args.end)
    print(f"[scan] {len(days)} cached trading days {days[0]}..{days[-1]}", flush=True)
    candidates = []
    for d in days:
        candidates += scan_day(con, d, args.cohort, roots=roots)
    print(f"[scan] {len(candidates)} {args.cohort} candidates "
          f"(side-pending, pre-tape)", flush=True)

    # ── Tape triage (2026-06-10): MU alone produced 6,058 side-pending whale
    # candidates YTD — taping every $1M candidate across 150 roots is ~100K
    # full-day tape calls. Grade the actionable tier instead.
    min_notional = args.min_notional
    if min_notional is None and args.cohort == "WHALE":
        min_notional = 3_000_000.0      # live WHALE_TELEGRAM_NOTIONAL.
    if min_notional:
        before = len(candidates)
        candidates = [c for c in candidates if c.notional >= min_notional]
        print(f"[scan] notional >= ${min_notional/1e6:g}M (Telegram tier): "
              f"{before} -> {len(candidates)}", flush=True)
    if args.top_k_day and args.top_k_day > 0:
        by_key: dict = {}
        for c in candidates:
            by_key.setdefault((c.root, c.date, c.right), []).append(c)
        before = len(candidates)
        kept = []
        for key, group in by_key.items():
            group.sort(key=lambda c: (c.score_if_ask, c.notional), reverse=True)
            kept += group[:args.top_k_day]
        candidates = sorted(kept, key=lambda c: c.date)
        print(f"[scan] top-{args.top_k_day} per (root,day,right): "
              f"{before} -> {len(candidates)}", flush=True)

    if args.cap_tape is not None and len(candidates) > args.cap_tape:
        # Keep the most recent (the relevant regime) — log the truncation.
        candidates = sorted(candidates, key=lambda c: c.date)[-args.cap_tape:]
        print(f"[scan] CAP: tape-verifying only the most recent "
              f"{args.cap_tape} candidates", flush=True)

    # ── Phase 3: REPLAY (tape fire + clusters + outcomes) ─────────────────
    tape, nbbo = ThetaTradeTapeSource(), ThetaNBBOSource()
    clusters, coverage = build_replay_clusters(
        candidates, tape, nbbo, hold_days=args.hold_days)
    print(f"[replay] coverage: {coverage}", flush=True)

    # ── Phase 4: GATE ─────────────────────────────────────────────────────
    card = TestCard(
        card_id=f"REPLAY:{args.cohort}-{args.start}..{args.end}",
        provenance="historical chain cache + OPRA tape (HISTORICAL_REPLAY.md)",
        claim=f"the live {args.cohort} signature has positive net option PnL "
              f"over {args.start}..{args.end} with tape-clean side labels",
        expected_sign="positive",
        mechanism="institutional accumulation precedes the move so premium expands",
        target_cohort=f"REPLAY:{args.cohort}",
        kill_criteria="negative net expectancy across the replay window",
    )
    cand, diag = build_replay_candidate(
        card, args.cohort, clusters, coverage, baseline=args.baseline,
        nbbo_source=nbbo, tape_source=tape, hold_days=args.hold_days)
    print("Diagnostics:")
    for k, v in diag.items():
        print(f"  {k:22s} {v}")
    print()
    led = TrialLedger(args.ledger)
    if args.seed_n > 0:
        led.seed(args.seed_n, reason="prior ad-hoc backtests + 4-LLM rounds (C4)")
    rep = ValidationGate(led, GateConfig(spa_reps=args.spa_reps)).evaluate(cand)
    print(rep.summary())

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "diagnostics": diag,
            "report": {"card_id": rep.card_id, "outcome": rep.outcome,
                       "drivers": rep.drivers,
                       "global_n_trials": rep.global_n_trials,
                       "stages": [asdict(s) for s in rep.stages]},
        }, indent=2, default=str), encoding="utf-8")
        print(f"\n[json] wrote {args.json_out}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
