"""Decision-grade experiment: does the TAPE-CONFIRMED subset have positive edge?

The flow-cohort gate REJECTed WHALE/INFORMED at negative mean R at every hold
horizon. The open question that decides SALVAGEABLE vs DEAD: do the clusters
whose side label the tape CONFIRMS show positive expectancy even though the
full cohort is negative — i.e., are the guessed/inverted labels dragging down a
real underlying edge?

  - confirmed-subset R > 0 (with honest small-n uncertainty) -> SALVAGEABLE by
    fixing labels live (greenlights the active suppress-snapshot-sided gate).
  - confirmed-subset R <= 0 -> genuinely dead as a bracketed long-premium trade,
    independent of labels; the active gate won't save it.

Unlike the gate's LABEL_CONF stage (which strides a 60-cluster sample), this
verifies EVERY resolved cluster's side against the tape, then grades each label
subset (CONFIRMED / INVERTED / AMBIGUOUS / NO_DATA) separately: n, mean R with
a seeded-bootstrap 95% CI, win rate with a Wilson 95% interval. Where the new
live ``side_source`` column is populated (2026-06-09 PM onward) the tick-vs-
snapshot split is reported as a cross-check.

Offline, read-only. Needs the venv + ThetaData Terminal up:
    .venv-autoresearch/Scripts/python scripts/grade_confirmed_subset.py
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

import numpy as np  # noqa: E402

from autoresearch.decay_monitor import wilson_interval  # noqa: E402
from autoresearch.flow_cohorts import FLOW_DB_PATH, load_flow_clusters  # noqa: E402
from autoresearch.label_confidence import (  # noqa: E402
    LabelConfidenceConfig, check_cohort_side_labels,
)
from autoresearch.option_pnl import ThetaNBBOSource  # noqa: E402
from autoresearch.side_confirmation import (  # noqa: E402
    AMBIGUOUS, CONFIRMED, INVERTED, LOW_RESOLUTION, NO_DATA, ThetaTradeTapeSource,
)

STATUSES = (CONFIRMED, INVERTED, AMBIGUOUS, LOW_RESOLUTION, NO_DATA)


def subset_stats(rets: list[float], n_boot: int = 10_000, seed: int = 42) -> dict:
    """n, mean R (+ seeded-bootstrap 95% CI), win rate (+ Wilson 95%)."""
    n = len(rets)
    if n == 0:
        return {"n": 0}
    arr = np.asarray(rets, dtype=float)
    wins = int(np.sum(arr > 0))
    wl, _, wu = wilson_interval(wins, n)
    out = {"n": n, "mean_r": float(arr.mean()), "median_r": float(np.median(arr)),
           "win_rate": wins / n, "wr_wilson_low": wl, "wr_wilson_high": wu}
    if n >= 2:
        rng = np.random.default_rng(seed)
        boots = arr[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
        out["mean_r_ci_low"] = float(np.percentile(boots, 2.5))
        out["mean_r_ci_high"] = float(np.percentile(boots, 97.5))
    return out


def grade(cohort: str, *, db: str, nbbo, tape, days: float, limit: int,
          hold_days: int) -> dict:
    lo_ts = time.time() - days * 86400.0
    clusters, cov = load_flow_clusters(db, cohort, nbbo, limit=limit,
                                       lo_ts=lo_ts, hold_days=hold_days)
    # Verify EVERY resolved cluster (no stride sampling).
    lc = check_cohort_side_labels(
        cohort, clusters, tape,
        config=LabelConfidenceConfig(sample_max=10**9))
    subsets = {}
    for status in STATUSES:
        rets = [c.ret for c in lc.checks if c.status == status and c.ret is not None]
        subsets[status] = subset_stats(rets)
    src_split = {}
    for src in ("tick", "snapshot"):
        rets = [c["ret"] for c in clusters if c.get("side_source") == src]
        if rets:
            src_split[src] = subset_stats(rets)
    return {
        "cohort": cohort, "hold_days": hold_days, "window_days": days,
        "coverage": cov,
        "full": subset_stats([c["ret"] for c in clusters]),
        "subsets": subsets,
        "side_source_split": src_split or None,
        "label_summary": {"band": lc.band, "confirm_frac": lc.confirm_frac,
                          "invert_frac": lc.invert_frac,
                          "n_with_data": lc.n_with_data,
                          "data_from": lc.data_from,
                          "data_through": lc.data_through},
    }


def _fmt(s: dict) -> str:
    if s.get("n", 0) == 0:
        return "n=0"
    ci = ""
    if "mean_r_ci_low" in s:
        ci = f" [{s['mean_r_ci_low']:+.3f}, {s['mean_r_ci_high']:+.3f}]"
    return (f"n={s['n']:<4d} meanR {s['mean_r']:+.3f}{ci}  "
            f"WR {s['win_rate']:.0%} (Wilson {s['wr_wilson_low']:.0%}-"
            f"{s['wr_wilson_high']:.0%})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohorts", default="WHALE,INFORMED")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--holds", default="0,3")
    ap.add_argument("--flow-db", default=FLOW_DB_PATH)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    nbbo, tape = ThetaNBBOSource(), ThetaTradeTapeSource()
    results = []
    for cohort in args.cohorts.split(","):
        for hold in (int(h) for h in args.holds.split(",")):
            r = grade(cohort.strip(), db=args.flow_db, nbbo=nbbo, tape=tape,
                      days=args.days, limit=args.limit, hold_days=hold)
            results.append(r)
            print("=" * 76)
            print(f"{r['cohort']}  hold={r['hold_days']}d  "
                  f"(window {r['window_days']:g}d; data "
                  f"{r['label_summary']['data_from']} .. "
                  f"{r['label_summary']['data_through']})")
            print(f"  FULL COHORT        {_fmt(r['full'])}")
            for status in STATUSES:
                s = r["subsets"][status]
                if s.get("n"):
                    print(f"  {status:<18s} {_fmt(s)}")
            if r["side_source_split"]:
                for src, s in r["side_source_split"].items():
                    print(f"  side_source={src:<9s} {_fmt(s)}")
            conf = r["subsets"][CONFIRMED]
            if conf.get("n", 0) >= 10:
                lo = conf.get("mean_r_ci_low", float("nan"))
                verdict = ("SALVAGEABLE-looking (confirmed mean R > 0"
                           + (", CI excludes 0" if lo > 0 else
                              ", but CI includes 0 — suggestive only") + ")"
                           if conf["mean_r"] > 0 else
                           "DEAD-looking (confirmed subset non-positive too)")
            else:
                verdict = f"INSUFFICIENT confirmed n ({conf.get('n', 0)})"
            print(f"  --> CONFIRMED-SUBSET READ: {verdict}")
            sys.stdout.flush()

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"\n[json] wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
