"""Ordering-sensitivity robustness for the OOS S2-vs-S1 (regime-overlay) comparison.

The adversarial verification flagged that simulate()'s same-day admit-order tiebreaker
(order='king_up', a weak/near-zero momentum sort) can flip the S2-vs-S1 Calmar sign when
the cap binds. This quantifies that: per period, the (S2-S1) Calmar edge under king_up,
under neutral insertion order, and across 20 RANDOM admit-orderings (mean +/- std +
fraction of orderings where S2 beats S1). If the sign is unstable across random orderings,
the regime overlay's OOS edge is genuinely inconclusive (ordering noise dominates).

Run: python research/sizing_oos_ordering_check.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sizing_cap_backtest import simulate, metrics, calendar
from sizing_cap_backtest_oos import spy_regime, PERIODS, RESULTS

PERIOD_KEYS = ["2024H1", "2024H2", "2025H1", "2025H2", "2026H1"]
BP, CP = 0.017, 0.12
N_RAND = 20


def index_trades(trades):
    cal = calendar(trades)
    cidx = {d: i for i, d in enumerate(cal)}
    for t in trades:
        raw = {cidx[t["dates"][k]]: (t["pnl"][k], t["expo"][k]) for k in range(len(t["dates"]))}
        t["_i0"], t["_i1"] = min(raw), max(raw)
        dense, last = {}, None
        for di in range(t["_i0"], t["_i1"] + 1):
            if di in raw:
                last = raw[di]
            dense[di] = last
        t["_dmap"] = dense
    return cal


def edge(trades, cal, regime, order):
    """Calmar(S2) - Calmar(S1) for a given admit-order."""
    s1 = metrics(simulate(trades, cal, regime, BP, cap=CP, use_regime=False,
                          use_breaker=False, order=order), cal, "S1")
    s2 = metrics(simulate(trades, cal, regime, BP, cap=CP, use_regime=True,
                          use_breaker=False, order=order), cal, "S2")
    c1, c2 = s1["calmar"], s2["calmar"]
    if not (isinstance(c1, (int, float)) and isinstance(c2, (int, float))):
        return None
    return c2 - c1


def main():
    print(f"{'period':8} {'king_up':>9} {'none':>8} {'rand_mean':>10} {'rand_std':>9} "
          f"{'S2>S1 frac':>11}")
    pooled_ku, pooled_rand = [], []
    rows = []
    for p in PERIOD_KEYS:
        tape = json.loads((RESULTS / f"oos_tape_{p}.json").read_text(encoding="utf-8"))
        trades = tape["trades"]
        cal = index_trades(trades)
        regime = spy_regime(p)
        e_ku = edge(trades, cal, regime, "king_up")
        e_none = edge(trades, cal, regime, "none")
        rand = [edge(trades, cal, regime, f"shuffle:{i}") for i in range(N_RAND)]
        rand = [x for x in rand if x is not None]
        frac = float(np.mean([x > 0 for x in rand])) if rand else float("nan")
        rmean, rstd = (float(np.mean(rand)), float(np.std(rand))) if rand else (float("nan"),) * 2
        pooled_ku.append(e_ku); pooled_rand.extend(rand)
        rows.append({"period": p, "king_up": round(e_ku, 3), "none": round(e_none, 3),
                     "rand_mean": round(rmean, 3), "rand_std": round(rstd, 3),
                     "rand_frac_s2_gt_s1": round(frac, 2)})
        print(f"{p:8} {e_ku:>9.3f} {e_none:>8.3f} {rmean:>10.3f} {rstd:>9.3f} {frac:>11.2f}")
    overall = {"king_up_mean_edge": round(float(np.mean(pooled_ku)), 3),
               "random_mean_edge": round(float(np.mean(pooled_rand)), 3),
               "random_frac_s2_beats_s1": round(float(np.mean([x > 0 for x in pooled_rand])), 3),
               "n_random_runs": len(pooled_rand)}
    print(f"\nPOOLED across 5 periods: king_up mean edge {overall['king_up_mean_edge']}, "
          f"random mean edge {overall['random_mean_edge']}, "
          f"S2>S1 in {overall['random_frac_s2_beats_s1']*100:.0f}% of {overall['n_random_runs']} random runs")
    out = {"per_period": rows, "overall": overall, "n_rand_per_period": N_RAND}
    (RESULTS / "oos_ordering_sensitivity.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"-> {RESULTS / 'oos_ordering_sensitivity.json'}")


if __name__ == "__main__":
    main()
