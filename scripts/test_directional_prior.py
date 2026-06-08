"""Unit tests for server/directional_prior.py (bear-day ensemble leg 2).

Includes an HONESTY check: on random-walk noise the walk-forward AUC must land
near 0.5 (no fake edge) — the discipline lesson from the AION teardown.

Run:  python scripts/test_directional_prior.py
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.directional_prior as dp  # noqa: E402

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


def _bars(closes, pad=0.2):
    return [{"date": f"2010-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
             "open": c, "high": c + pad, "low": c - pad, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


# ── AUC ───────────────────────────────────────────────────────────────────
def test_auc():
    check("perfect AUC=1", dp.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0)
    check("reversed AUC=0", dp.auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0)
    a = dp.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1])
    check("all-tie AUC=0.5", a == 0.5, str(a))
    check("one class -> None", dp.auc([0.1, 0.2], [1, 1]) is None)


# ── logistic regression learns a real signal ──────────────────────────────
def test_logreg_learns():
    random.seed(7)
    X, y = [], []
    for _ in range(400):
        x0 = random.uniform(-2, 2)
        noise = [random.uniform(-1, 1) for _ in range(3)]
        X.append([x0] + noise)
        # y depends on x0 with a little label noise
        p = 1 if x0 + random.uniform(-0.3, 0.3) > 0 else 0
        y.append(p)
    cut = 300
    mean, std = dp._standardizer(X[:cut])
    Xtr = [dp._apply_std(r, mean, std) for r in X[:cut]]
    Xte = [dp._apply_std(r, mean, std) for r in X[cut:]]
    m = dp.LogReg().fit(Xtr, y[:cut])
    scores = [m.proba(r) for r in Xte]
    a = dp.auc(scores, y[cut:])
    check("logreg learns separable signal (AUC>0.85)", a is not None and a > 0.85, str(a))
    check("weight on informative feature dominates",
          abs(m.w[0]) > max(abs(w) for w in m.w[1:]), str([round(w, 2) for w in m.w]))


# ── dataset ────────────────────────────────────────────────────────────────
def test_build_dataset():
    closes = [100 + math.sin(i / 10) * 5 + i * 0.05 for i in range(500)]
    X, y, idxs, F, rvol, c = dp.build_dataset(_bars(closes), horizon=3)
    check("dataset has rows", len(X) > 100, str(len(X)))
    check("6 features", len(X[0]) == 6)
    check("labels binary", set(y) <= {0, 1})
    check("warmup respected (first idx>=200)", idxs[0] >= 200)


# ── train_and_predict ───────────────────────────────────────────────────────
def test_train_predict_trend():
    # gentle uptrend + noise → enough rows; prob_up should be a valid pct
    random.seed(11)
    closes = []
    px = 100.0
    for i in range(1400):
        px *= (1 + 0.0004 + random.uniform(-0.01, 0.01))
        closes.append(px)
    res = dp.train_and_predict(_bars(closes), horizon=3)
    check("train ok", res.get("ok") is True, str(res)[:120])
    check("prob_up in [0,100]", res["prob_up"] is None or 0 <= res["prob_up"] <= 100)
    check("wf_auc present", res["wf_auc"] is not None)
    check("base_rate present", 0 <= res["base_rate"] <= 100)
    check("lean valid", res["lean"] in ("BULLISH", "BEARISH", "NEUTRAL"))
    check("has as_of", res["as_of"] is not None)


def test_insufficient_history():
    res = dp.train_and_predict(_bars([100 + i for i in range(250)]), horizon=3)
    check("short history -> not ok", res.get("ok") is False)


def test_honesty_on_noise():
    # pure random walk → the model should find NO real edge (AUC ~ 0.5)
    random.seed(3)
    closes = []
    px = 100.0
    for _ in range(1800):
        px *= (1 + random.gauss(0, 0.01))
        closes.append(px)
    res = dp.train_and_predict(_bars(closes), horizon=3)
    check("noise: trains", res.get("ok") is True)
    auc_v = res["wf_auc"]
    check("noise: AUC near 0.5 (no fake edge)", auc_v is not None and 0.38 <= auc_v <= 0.62,
          f"auc={auc_v}")
    check("noise: not flagged trustworthy", res["trustworthy"] is False or auc_v < 0.55)


def main() -> int:
    print("=== directional_prior (bear-day ensemble leg 2) tests ===")
    for fn in (test_auc, test_logreg_learns, test_build_dataset,
               test_train_predict_trend, test_insufficient_history,
               test_honesty_on_noise):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*48}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
