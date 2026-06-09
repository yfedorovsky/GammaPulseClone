"""Run the validation gate on a flow_alerts cohort (Option B — live flow data).

Grades the WHALE / INFORMED / FLOW_* cohorts straight from
snapshots.db::flow_alerts (alive, complete) with OFFLINE option-PnL outcomes and
tape-verified side labels — the alert_outcomes flow pipeline is dead, so this is
the only current grading path for these cohorts. Read-only on both DBs; offline.

MUST run under the autoresearch venv, with ThetaData Terminal up:
    .venv-autoresearch/Scripts/python scripts/run_gate_on_flow_cohort.py --cohort WHALE
    .venv-autoresearch/Scripts/python scripts/run_gate_on_flow_cohort.py --cohort INFORMED --baseline WHALE --days 7
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from autoresearch.flow_cohorts import (  # noqa: E402
    FLOW_COHORTS, FLOW_DB_PATH, build_flow_candidate,
)
from autoresearch.backtest_adapter import LIVE_DB_PATH                     # noqa: E402
from autoresearch.gate import TestCard, GateConfig, ValidationGate         # noqa: E402
from autoresearch.trials_ledger import TrialLedger                         # noqa: E402
from autoresearch.option_pnl import ThetaNBBOSource                        # noqa: E402
from autoresearch.side_confirmation import ThetaTradeTapeSource            # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", required=True, choices=FLOW_COHORTS)
    ap.add_argument("--baseline", default="SOE_A",
                    help="flow cohort (WHALE/INFORMED/FLOW_*) or an "
                         "alert_outcomes alert_type (default SOE_A)")
    ap.add_argument("--flow-db", default=FLOW_DB_PATH)
    ap.add_argument("--outcomes-db", default=LIVE_DB_PATH)
    ap.add_argument("--days", type=float, default=14.0,
                    help="lookback window in days (default 14)")
    ap.add_argument("--limit", type=int, default=250, help="cap clusters per cohort")
    ap.add_argument("--no-tape", action="store_true",
                    help="skip side-label tape verification (cohort then reads "
                         "UNVERIFIED and quarantines at LABEL_CONF)")
    ap.add_argument("--seed-n", type=int, default=300,
                    help="seed the GLOBAL trial count (C4); 0 to disable")
    ap.add_argument("--ledger", default=str(Path(__file__).resolve().parent.parent
                                            / "autoresearch" / "_artifacts" / "demo_ledger.json"))
    ap.add_argument("--spa-reps", type=int, default=1000)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    card = TestCard(
        card_id=f"FLOW:{args.cohort}-vs-{args.baseline}",
        provenance=f"snapshots.db::flow_alerts cohort {args.cohort} (read-only, Option B)",
        claim=f"{args.cohort} flow clusters beat the {args.baseline} baseline on net option PnL",
        expected_sign="positive",
        mechanism="flagged informed/whale flow precedes the move so premium expands",
        target_cohort=args.cohort,
        kill_criteria="rolling always-valid lower bound < 22.7% breakeven for 2 checks",
    )

    lo_ts = time.time() - args.days * 86400.0
    cand, diag = build_flow_candidate(
        card, args.cohort, flow_db_path=args.flow_db,
        outcomes_db_path=args.outcomes_db, baseline=args.baseline,
        source=ThetaNBBOSource(),
        tape_source=None if args.no_tape else ThetaTradeTapeSource(),
        limit=args.limit, lo_ts=lo_ts,
    )

    print("=" * 72)
    print(f"FLOW GATE RUN — cohort={args.cohort}  baseline={args.baseline}  "
          f"window={args.days:g}d")
    print("=" * 72)
    print("Diagnostics:")
    for k, v in diag.items():
        print(f"  {k:22s} {v}")
    print()

    Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
    led = TrialLedger(args.ledger)
    if args.seed_n > 0:
        added = led.seed(args.seed_n,
                         reason="prior ad-hoc backtests + 4-LLM rounds + buffer (C4)")
        if added:
            print(f"[ledger] seeded global N with {added} prior trials (C4)")
    rep = ValidationGate(led, GateConfig(spa_reps=args.spa_reps)).evaluate(cand)
    print(rep.summary())

    if args.json_out:
        from dataclasses import asdict
        Path(args.json_out).write_text(json.dumps({
            "diagnostics": diag,
            "report": {
                "card_id": rep.card_id, "outcome": rep.outcome,
                "drivers": rep.drivers, "global_n_trials": rep.global_n_trials,
                "stages": [asdict(s) for s in rep.stages],
            },
        }, indent=2, default=str), encoding="utf-8")
        print(f"\n[json] wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
