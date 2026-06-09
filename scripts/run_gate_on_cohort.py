"""Run the validation gate on a real alert_outcomes cohort (end-to-end demo).

OFFLINE, read-only on the live DB. Builds a Candidate via the backtest adapter
and runs it through the deflation gate, printing the staged report + diagnostics.

MUST run under the autoresearch venv:
    .venv-autoresearch/Scripts/python scripts/run_gate_on_cohort.py --alert-type FLOW_HIGH
    .venv-autoresearch/Scripts/python scripts/run_gate_on_cohort.py --alert-type SOE_A --baseline FLOW_HIGH
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.backtest_adapter import build_candidate, LIVE_DB_PATH  # noqa: E402
from autoresearch.gate import TestCard, GateConfig, ValidationGate        # noqa: E402
from autoresearch.trials_ledger import TrialLedger                        # noqa: E402
from autoresearch.option_pnl import ThetaNBBOSource                       # noqa: E402
from autoresearch.side_confirmation import ThetaTradeTapeSource           # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert-type", required=True, help="candidate cohort alert_type")
    ap.add_argument("--baseline", default="SOE_A", help="baseline cohort (default SOE_A)")
    ap.add_argument("--db", default=LIVE_DB_PATH)
    ap.add_argument("--spot", action="store_true",
                    help="use the legacy directional-spot proxy instead of option PnL")
    ap.add_argument("--no-tape", action="store_true",
                    help="skip side-label tape verification (side-dependent cohorts "
                         "then read UNVERIFIED and quarantine at LABEL_CONF)")
    ap.add_argument("--limit", type=int, default=None, help="cap clusters per cohort")
    ap.add_argument("--seed-n", type=int, default=300,
                    help="seed the GLOBAL trial count (C4); 0 to disable")
    ap.add_argument("--ledger", default=str(Path(__file__).resolve().parent.parent
                                            / "autoresearch" / "_artifacts" / "demo_ledger.json"))
    ap.add_argument("--spa-reps", type=int, default=1000)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    card = TestCard(
        card_id=f"{args.alert_type}-vs-{args.baseline}",
        provenance=f"alert_outcomes.db cohort {args.alert_type} (read-only)",
        claim=f"{args.alert_type} clusters beat the {args.baseline} baseline on net option PnL",
        expected_sign="positive",
        mechanism="cohort selection captures informed directional flow that leads spot",
        target_cohort=args.alert_type,
        kill_criteria="rolling always-valid lower bound < 22.7% breakeven for 2 checks",
    )

    source = None if args.spot else ThetaNBBOSource()
    tape = None if (args.spot or args.no_tape) else ThetaTradeTapeSource()
    cand, diag = build_candidate(
        card, args.alert_type, db_path=args.db, baseline_alert_type=args.baseline,
        source=source, return_mode=("spot" if args.spot else "option_pnl"),
        limit=args.limit, tape_source=tape,
    )

    print("=" * 72)
    print(f"GATE RUN — candidate={args.alert_type}  baseline={args.baseline}")
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
