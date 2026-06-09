"""Signal Health Report — Signal Health Cards over the live alert_outcomes DB.

Read-only / shadow. Prints the summary table and (optionally) writes a Markdown +
JSON artifact. This is the day-to-day "which live signals are decaying, and what
should I do?" report — it operationalizes the retirement-timing thesis on data we
already have.

Usage:
    python scripts/signal_health_report.py
    python scripts/signal_health_report.py --md-out health.md --json-out health.json
    python scripts/signal_health_report.py --breakeven 0.227 --min-n 30
    python scripts/signal_health_report.py --economics --label-confidence  (Theta up)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows cp1252 console chokes on the verdict emoji.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from datetime import datetime, timezone  # noqa: E402

from autoresearch.decay_monitor import DEFAULT_BREAKEVEN, DEFAULT_MIN_N, LIVE_DB_PATH  # noqa: E402
from autoresearch.signal_health_card import (  # noqa: E402
    build_cards, render_json, render_markdown,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Signal Health Cards (read-only).")
    ap.add_argument("--db", default=LIVE_DB_PATH, help="alert_outcomes DB path.")
    ap.add_argument("--breakeven", type=float, default=DEFAULT_BREAKEVEN)
    ap.add_argument("--min-n", type=float, default=DEFAULT_MIN_N)
    ap.add_argument("--md-out", help="write the full Markdown report here.")
    ap.add_argument("--json-out", help="write the cards as JSON here.")
    ap.add_argument("--economics", action="store_true",
                    help="compute per-cohort option-PnL expectancy via ThetaData "
                         "NBBO (slower; needs Theta Terminal up + the venv).")
    ap.add_argument("--label-confidence", action="store_true",
                    help="tape-verify side labels for flow-derived cohorts "
                         "(WHALE/INFORMED/FLOW_*/CLUSTER_*) via ThetaData "
                         "trade_quote (slower; needs Theta Terminal up). "
                         "Without it those cohorts honestly read UNVERIFIED.")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).timestamp()
    cohorts = None
    if args.economics or args.label_confidence:
        # First pass (cheap) just to learn the cohort list.
        cohorts = [c.cohort for c in
                   build_cards(args.db, now_ts=now, breakeven=args.breakeven,
                               min_n=args.min_n)[0]]

    exp_recent = exp_prior = None
    if args.economics:
        from autoresearch.cohort_economics import cohort_expectancy
        from autoresearch.option_pnl import ThetaNBBOSource
        exp_recent, exp_prior, _cov = cohort_expectancy(
            args.db, cohorts, ThetaNBBOSource(), now_ts=now)

    label_conf = None
    if args.label_confidence:
        from autoresearch.backtest_adapter import load_clusters_economic
        from autoresearch.label_confidence import (
            check_cohort_side_labels, is_side_label_dependent)
        from autoresearch.option_pnl import ThetaNBBOSource
        from autoresearch.side_confirmation import ThetaTradeTapeSource
        nbbo, tape = ThetaNBBOSource(), ThetaTradeTapeSource()
        label_conf = {}
        for cohort in cohorts:
            if not is_side_label_dependent(cohort):
                continue
            # Same cluster cap as cohort_economics — bounds the NBBO re-sim load;
            # the tape check itself further samples (LabelConfidenceConfig.sample_max).
            clusters, _cov = load_clusters_economic(args.db, cohort, nbbo, limit=400)
            if clusters:
                label_conf[cohort] = check_cohort_side_labels(cohort, clusters, tape)

    cards, _ = build_cards(args.db, now_ts=now, breakeven=args.breakeven,
                           min_n=args.min_n, expectancy_recent=exp_recent,
                           expectancy_prior=exp_prior,
                           label_confidence=label_conf)
    md = render_markdown(cards, now_ts=now)

    if args.md_out:
        Path(args.md_out).write_text(md, encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(render_json(cards), indent=2), encoding="utf-8")

    # Console: just the summary table (the cards go to the artifact).
    summary = md.split("## Cards")[0].rstrip()
    print(summary)
    n_retire = sum(1 for c in cards if c.verdict == "RETIRE_CANDIDATE")
    n_watch = sum(1 for c in cards if c.verdict == "WATCH")
    print(f"\n[signal_health] {len(cards)} cohorts · {n_retire} retire-candidate · "
          f"{n_watch} watch · md={args.md_out or '-'} json={args.json_out or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
