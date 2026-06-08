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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert-type", required=True, help="candidate cohort alert_type")
    ap.add_argument("--baseline", default="SOE_A", help="baseline cohort (default SOE_A)")
    ap.add_argument("--db", default=LIVE_DB_PATH)
    ap.add_argument("--vix-below", type=float, default=None)
    ap.add_argument("--vix-atleast", type=float, default=None)
    ap.add_argument("--ledger", default=str(Path(__file__).resolve().parent.parent
                                            / "autoresearch" / "_artifacts" / "demo_ledger.json"))
    ap.add_argument("--spa-reps", type=int, default=1000)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    card = TestCard(
        card_id=f"{args.alert_type}-vs-{args.baseline}",
        provenance=f"alert_outcomes.db cohort {args.alert_type} (read-only)",
        claim=f"{args.alert_type} has positive, baseline-beating directional edge",
        expected_sign="positive",
        mechanism="cohort selection captures informed directional flow that leads spot",
        target_cohort=args.alert_type,
        kill_criteria="rolling 60d Clopper-Pearson lower bound < 22.7% breakeven",
    )

    cand, diag = build_candidate(
        card, args.alert_type, db_path=args.db,
        baseline_alert_type=args.baseline,
        vix_below=args.vix_below, vix_atleast=args.vix_atleast,
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
    rep = ValidationGate(led, GateConfig(spa_reps=args.spa_reps)).evaluate(cand)
    print(rep.summary())

    if args.json_out:
        from dataclasses import asdict
        Path(args.json_out).write_text(json.dumps({
            "diagnostics": diag,
            "report": {
                "card_id": rep.card_id, "passed": rep.passed,
                "rejected_at": rep.rejected_at, "global_n_trials": rep.global_n_trials,
                "stages": [asdict(s) for s in rep.stages],
            },
        }, indent=2, default=str), encoding="utf-8")
        print(f"\n[json] wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
