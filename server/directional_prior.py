"""Short-horizon directional prior (AION-teardown roadmap #1, bear-day ensemble leg 2).

A small, TRANSPARENT, walk-forward-honest model of P(index up over N days) — the
second leg of the bear-day fix (the first being #54's dealer-structure gate). On
Fri 6/05 AION's 3-day forecast read 18.5% (correctly bearish) while our flow
engine stayed long-biased. This reproduces that signal honestly.

Design (deliberately NOT a black box):
  - pure-Python logistic regression on 6 interpretable index features
    (5d/20d momentum, distance from 50/200-DMA, centered RSI, realized vol)
  - walk-forward split (train past → test future) with rank-based AUC reported
    so we KNOW the real edge (expect ~0.52-0.60, NOT AION's implausible 0.90)
  - probability is calibrated only as far as the data supports; we surface the
    AUC alongside every prediction so it's never over-trusted

Reuses server/analogues.py feature primitives. Network-free engine; the cached
loader + endpoint live in get_directional()/main.py.
"""
from __future__ import annotations

import math
import time as _time
from typing import Any

from .analogues import compute_features

MAX_TRAIN_BARS = 2600   # ~10y — recent regime matters; keeps pure-Python fit fast
_GD_ITERS = 350
_LR = 0.3
_L2 = 0.01

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 3600.0


# ── feature extraction ────────────────────────────────────────────────────
def _rolling_std(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(len(vals)):
        if i >= n - 1:
            win = vals[i - n + 1:i + 1]
            m = sum(win) / n
            out[i] = (sum((x - m) ** 2 for x in win) / n) ** 0.5
    return out


def _feature_row(F, rvol, closes, i) -> list[float] | None:
    if i < 200:
        return None
    s50, s200, r, rv = F["sma50"][i], F["sma200"][i], F["rsi"][i], rvol[i]
    if None in (s50, s200, r, rv) or s50 == 0 or s200 == 0:
        return None
    return [
        closes[i] / closes[i - 5] - 1.0,     # 5d momentum
        closes[i] / closes[i - 20] - 1.0,    # 20d momentum
        (closes[i] - s50) / s50,             # distance from 50-DMA
        (closes[i] - s200) / s200,           # distance from 200-DMA
        (r - 50.0) / 50.0,                   # centered RSI
        rv,                                  # realized vol (20d)
    ]


def build_dataset(bars: list[dict], horizon: int = 3):
    """Returns (X, y, idxs, F, rvol, closes) for supervised rows + the frame."""
    F = compute_features(bars)
    closes = F["close"]
    n = F["n"]
    rets = [0.0] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, n)]
    rvol = _rolling_std(rets, 20)
    X, y, idxs = [], [], []
    for i in range(n):
        if i + horizon >= n:
            continue
        row = _feature_row(F, rvol, closes, i)
        if row is None:
            continue
        X.append(row)
        y.append(1 if closes[i + horizon] > closes[i] else 0)
        idxs.append(i)
    return X, y, idxs, F, rvol, closes


# ── standardize + logistic regression (pure Python) ───────────────────────
def _standardizer(X: list[list[float]]):
    d = len(X[0])
    mean = [sum(r[j] for r in X) / len(X) for j in range(d)]
    std = []
    for j in range(d):
        v = sum((r[j] - mean[j]) ** 2 for r in X) / len(X)
        std.append((v ** 0.5) or 1.0)
    return mean, std


def _apply_std(row, mean, std):
    return [(row[j] - mean[j]) / std[j] for j in range(len(row))]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


class LogReg:
    def __init__(self, lr=_LR, iters=_GD_ITERS, l2=_L2):
        self.lr, self.iters, self.l2 = lr, iters, l2
        self.w: list[float] = []
        self.b = 0.0

    def fit(self, X, y):
        m, d = len(X), len(X[0])
        self.w = [0.0] * d
        self.b = 0.0
        for _ in range(self.iters):
            gw = [0.0] * d
            gb = 0.0
            for xi, yi in zip(X, y):
                p = _sigmoid(self.b + sum(self.w[j] * xi[j] for j in range(d)))
                err = p - yi
                for j in range(d):
                    gw[j] += err * xi[j]
                gb += err
            for j in range(d):
                self.w[j] -= self.lr * (gw[j] / m + self.l2 * self.w[j])
            self.b -= self.lr * (gb / m)
        return self

    def proba(self, xi):
        return _sigmoid(self.b + sum(self.w[j] * xi[j] for j in range(len(xi))))


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based AUC (Mann-Whitney). None if a class is absent."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(scores)), key=lambda k: scores[k])
    # average ranks for ties
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    rank_sum_pos = sum(ranks[k] for k in range(len(labels)) if labels[k] == 1)
    return (rank_sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)


# ── train + evaluate + predict ────────────────────────────────────────────
def train_and_predict(bars: list[dict], horizon: int = 3,
                      train_frac: float = 0.7) -> dict[str, Any]:
    X, y, idxs, F, rvol, closes = build_dataset(bars, horizon)
    if len(X) < 300:
        return {"ok": False, "reason": f"insufficient history ({len(X)} rows)"}

    # cap to recent window for the fit (recent regime, keeps it fast)
    if len(X) > MAX_TRAIN_BARS:
        X, y, idxs = X[-MAX_TRAIN_BARS:], y[-MAX_TRAIN_BARS:], idxs[-MAX_TRAIN_BARS:]

    base_rate = round(100.0 * sum(y) / len(y), 1)

    # walk-forward: train on the past, test on the held-out future
    cut = int(len(X) * train_frac)
    Xtr, ytr, Xte, yte = X[:cut], y[:cut], X[cut:], y[cut:]
    mean, std = _standardizer(Xtr)
    Xtr_s = [_apply_std(r, mean, std) for r in Xtr]
    Xte_s = [_apply_std(r, mean, std) for r in Xte]
    wf = LogReg().fit(Xtr_s, ytr)
    te_scores = [wf.proba(r) for r in Xte_s]
    wf_auc = auc(te_scores, yte)
    te_acc = round(100.0 * sum(1 for s, t in zip(te_scores, yte)
                               if (s >= 0.5) == bool(t)) / len(yte), 1)

    # final model: refit on ALL rows (standardize on all), predict latest bar
    mean_a, std_a = _standardizer(X)
    full = LogReg().fit([_apply_std(r, mean_a, std_a) for r in X], y)
    last_row = _feature_row(F, rvol, closes, F["n"] - 1)
    prob_up = None
    if last_row is not None:
        prob_up = round(100.0 * full.proba(_apply_std(last_row, mean_a, std_a)), 1)

    lean = "NEUTRAL"
    if prob_up is not None:
        if prob_up >= 58:
            lean = "BULLISH"
        elif prob_up <= 42:
            lean = "BEARISH"

    return {
        "ok": True,
        "horizon": horizon,
        "prob_up": prob_up,            # P(up over `horizon` days), %
        "lean": lean,
        "base_rate": base_rate,        # unconditional up-rate baseline
        "wf_auc": round(wf_auc, 3) if wf_auc is not None else None,
        "wf_accuracy": te_acc,
        "n_train": len(Xtr), "n_test": len(Xte), "n_rows": len(X),
        "as_of": F["dates"][-1] if F["dates"] else None,
        "trustworthy": bool(wf_auc and wf_auc >= 0.55),  # honest gate
    }


def get_directional(symbol: str = "SPX", horizon: int = 3) -> dict[str, Any]:
    """Cached directional prior for an index (1h TTL). Loads OHLC via
    analogue_data, trains, returns the walk-forward-validated prediction."""
    key = f"{symbol.upper()}:{horizon}"
    now = _time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    from .analogue_data import load_bars
    bars, source = load_bars(symbol)
    res = train_and_predict(bars, horizon=horizon)
    res["symbol"] = symbol.upper()
    res["source"] = source
    _cache[key] = (now, res)
    return res
