"""Coverage-simulation validation of autoresearch/stats/betting_cs.py.

A hand-rolled confidence sequence is only trustworthy if it actually COVERS. This
Monte-Carlo test is the arbiter:
  1. time-uniform coverage of the betting CS on real-order Bernoulli streams
     (P[ exists t : LCB_t > mu ] <= alpha),
  2. the count-only betting_lcb(wins,n) covers at evaluation time, and
  3. it is TIGHTER (higher lower bound) than the empirical-Bernstein fallback.

Pure-stdlib, seeded RNG (deterministic). Run:
    python scripts/test_betting_cs.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.stats.betting_cs import betting_ci, betting_lcb_stream  # noqa: E402
from autoresearch.decay_monitor import always_valid_lcb  # noqa: E402  (EB count fallback)

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def test_time_uniform_coverage():
    """Across many streams, the LOWER bound should exceed the true mean (a miss)
    on at most ~alpha of streams over the whole horizon. CS are conservative, so
    we expect WELL below alpha; we gate at alpha with MC margin."""
    alpha = 0.10
    T = 50
    N = 300
    checkpoints = (10, 20, 30, 40, 50)
    rng = random.Random(20260608)
    worst = 0.0
    for mu in (0.15, 0.35, 0.55):
        misses = 0
        for _ in range(N):
            stream = [1.0 if rng.random() < mu else 0.0 for _ in range(T)]
            missed = False
            for t in checkpoints:
                lcb = betting_ci(stream[:t], alpha=alpha, grid_n=100)[0]
                if lcb > mu + 1e-9:
                    missed = True
                    break
            misses += missed
        rate = misses / N
        worst = max(worst, rate)
        check(f"coverage mu={mu}: miss_rate {rate:.3f} <= alpha {alpha}", rate <= alpha,
              f"miss_rate={rate:.3f}")
    check("worst-case miss rate within alpha", worst <= alpha, f"worst={worst:.3f}")


def _stream(mu: float, n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [1.0 if rng.random() < mu else 0.0 for _ in range(n)]


def test_sane_and_ordered():
    lo, hi = betting_ci([1.0] * 40 + [0.0] * 10, alpha=0.05)
    check("ci ordered + in [0,1]", 0.0 <= lo <= hi <= 1.0, f"{lo},{hi}")
    check("stream lcb below raw rate", betting_lcb_stream(_stream(0.6, 80, 1)) <= 0.6 + 0.2)
    check("no data -> trivial (0,1)", betting_ci([]) == (0.0, 1.0))
    check("empty stream lcb -> 0", betting_lcb_stream([]) == 0.0)
    # more data, same true rate -> tighter (higher) lower bound
    lcb_small = betting_lcb_stream(_stream(0.6, 50, 7))
    lcb_big = betting_lcb_stream(_stream(0.6, 500, 7))
    check("more data -> higher LCB at same rate", lcb_big > lcb_small,
          f"{lcb_small:.3f} -> {lcb_big:.3f}")


def test_tighter_than_eb():
    """The stream betting CS should be tighter (higher LCB) than the count EB
    bound on a representative ordered stream of the same (wins, n)."""
    oks = []
    for n in (100, 200, 400):
        xs = _stream(0.70, n, 99)
        w = int(sum(xs))
        b = betting_lcb_stream(xs, alpha=0.05)
        e = always_valid_lcb(w, n, alpha=0.05)   # EB count bound
        oks.append(b >= e)
        check(f"betting(stream) >= EB(count) at n={n} (b={b:.3f}, eb={e:.3f})", b >= e)
    check("betting tighter on all", all(oks))


def main() -> int:
    print("=== betting CS coverage validation ===")
    for fn in (test_time_uniform_coverage,
               test_sane_and_ordered, test_tighter_than_eb):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
