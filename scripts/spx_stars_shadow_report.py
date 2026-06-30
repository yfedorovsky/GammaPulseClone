"""SPX STARS-ALIGN shadow-test verdict report.

Grades the shadow scanner against its own falsification plan (the design synthesis):
SPX_STARS must beat BOTH adversarial controls (SPX_STARS_PUT = opposite direction,
SPX_STARS_RANDMOMENT = random moment) AND the CLUSTER_INDEX EXHAUST baseline, on a
realized EXIT-POLICY P&L — or it's just leveraged SPX longs and gets cut.

The edge (if any) lives in the EXIT, so we grade the exit policy, not raw direction:
  scale `SCALE` at +`TARGET`% (the reachable convex band), run the rest, hard stop at
  `STOP`%. Pessimistic ordering: if BOTH target and stop were touched, assume the stop
  came first. Applied UNIFORMLY to every bucket, so the relative ranking is fair even
  though the absolute proxy is conservative. Inputs come from the #92 option-P&L
  backfill (opt_mfe/opt_mae/opt_high_after/opt_close_eod), the same harness that
  produced the markout EXHAUST verdict.

Run:  python scripts/spx_stars_shadow_report.py [--days 45]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
import statistics as _stats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = str(ROOT / "alert_outcomes.db")

TARGET = 33.0   # the reachable +MFE band (opening-drive data: median best-MFE +33%)
STOP = -30.0    # structural hard stop (structural_turn discipline)
SCALE = 1.0 / 3.0

# PASS bars (from the synthesis falsification plan)
MIN_FIRES = 30
MIN_DAYS = 15
MIN_REACH_TARGET_PCT = 40.0
MAE_FLOOR = -32.0   # must escape the single-name -32 / index -80 theta incineration


def exit_policy_pnl(mfe, mae, eod, stop: float = STOP, target: float = TARGET,
                    scale: float = SCALE) -> float:
    """Proxy realized P&L %% of the scale-at-target / run-rest / hard-stop policy.
    Pessimistic ordering (stop before target if both touched)."""
    if mae is not None and mae <= stop:
        return float(stop)
    if mfe is not None and mfe >= target:
        rest = eod if eod is not None else target
        rest = max(stop, min(rest, mfe))
        return scale * target + (1 - scale) * rest
    return float(eod) if eod is not None else 0.0


def _et_day(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).date().isoformat()


def _rows(at: str, days: int) -> list[tuple]:
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return conn.execute(
            """SELECT opt_mfe_pct, opt_mae_pct, opt_high_after, opt_close_eod, fired_at
               FROM alert_outcomes
               WHERE alert_type=? AND opt_mfe_pct IS NOT NULL AND fired_at>?""",
            (at, cutoff)).fetchall()
    finally:
        conn.close()


def bucket_stats(rows: list[tuple]) -> dict:
    pnls, mfes, maes, days = [], [], [], set()
    for mfe, mae, high, close_eod, fa in rows:
        if mfe is None or mae is None:
            continue
        entry = high / (1 + mfe / 100) if (high and (1 + mfe / 100) > 0) else None
        eod = ((close_eod - entry) / entry * 100) if (entry and entry > 0 and close_eod is not None) else None
        pnls.append(exit_policy_pnl(mfe, mae, eod))
        mfes.append(mfe); maes.append(mae); days.add(_et_day(fa))
    n = len(pnls)
    if not n:
        return {"n": 0}
    return {
        "n": n, "n_days": len(days),
        "median_pnl": round(_stats.median(pnls), 1),
        "mean_pnl": round(_stats.mean(pnls), 1),
        "pct_pos": round(sum(1 for p in pnls if p > 0) / n * 100),
        "median_mfe": round(_stats.median(mfes), 1),
        "median_mae": round(_stats.median(maes), 1),
        "pct_reach_target": round(sum(1 for m in mfes if m >= TARGET) / n * 100),
        "pct_hit_stop": round(sum(1 for m in maes if m <= STOP) / n * 100),
    }


def _fmt(s: dict) -> str:
    if not s.get("n"):
        return "n=0 (no graded rows yet)"
    return (f"n={s['n']} ({s['n_days']}d) | exit-P&L med {s['median_pnl']:+.1f}% "
            f"mean {s['mean_pnl']:+.1f}% pos {s['pct_pos']}% | MFE {s['median_mfe']:+.1f}% "
            f"MAE {s['median_mae']:+.1f}% | reach+{int(TARGET)}% {s['pct_reach_target']}% "
            f"hit{int(STOP)}% {s['pct_hit_stop']}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()

    buckets = {k: bucket_stats(_rows(k, args.days)) for k in (
        "SPX_STARS", "SPX_STARS_PUT", "SPX_STARS_RANDMOMENT", "CLUSTER_INDEX", "CLUSTER")}

    print(f"SPX STARS-ALIGN - shadow verdict (last {args.days}d, exit policy: "
          f"scale 1/3 @+{int(TARGET)}%, stop {int(STOP)}%)")
    print("=" * 92)
    labels = {"SPX_STARS": "SPX_STARS (the setup)",
              "SPX_STARS_PUT": "  control: opposite-dir PUT",
              "SPX_STARS_RANDMOMENT": "  control: random moment",
              "CLUSTER_INDEX": "baseline: CLUSTER_INDEX (EXHAUST)",
              "CLUSTER": "baseline: CLUSTER (single-name)"}
    for k, lab in labels.items():
        print(f"  {lab:<34} {_fmt(buckets[k])}")

    s = buckets["SPX_STARS"]
    print("\nVERDICT")
    if not s.get("n") or s["n"] < MIN_FIRES or s["n_days"] < MIN_DAYS:
        have = f"{s.get('n', 0)} fires / {s.get('n_days', 0)} days"
        print(f"  [WAIT] INSUFFICIENT DATA - need >={MIN_FIRES} fires across >={MIN_DAYS} days "
              f"(have {have}). Keep accruing; do not act on intermediate results.")
        return 0
    pnl = s["median_pnl"]
    beats = {k: (pnl > buckets[k].get("median_pnl", 1e9)) for k in
             ("SPX_STARS_PUT", "SPX_STARS_RANDMOMENT", "CLUSTER_INDEX")}
    checks = {
        "median exit-P&L > 0": pnl > 0,
        "beats opposite-dir PUT control": beats["SPX_STARS_PUT"],
        "beats random-moment control": beats["SPX_STARS_RANDMOMENT"],
        "beats CLUSTER_INDEX baseline": beats["CLUSTER_INDEX"],
        f"median MAE > {MAE_FLOOR:.0f}% (escapes theta)": s["median_mae"] > MAE_FLOOR,
        f"reaches +{int(TARGET)}% on ≥{MIN_REACH_TARGET_PCT:.0f}%": s["pct_reach_target"] >= MIN_REACH_TARGET_PCT,
    }
    for c, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {c}")
    verdict = "==> PASS - promote toward live (still paper P&L first)" if all(checks.values()) \
        else "==> FAIL - it's leveraged SPX longs / no edge. Retire as research artifact."
    print(f"\n  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
