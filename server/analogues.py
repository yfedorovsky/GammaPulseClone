"""Analogues — historical base-rate pattern engine (AION-teardown task #55).

Clone of AION's Analogues tab: scan an index's price history for technical
patterns that are firing RIGHT NOW, find every prior occurrence, and report
"this exact setup fired N times since <start>; here's the forward-return
distribution." No ML, no prediction — a factual base rate.

Pairs with our flow engine as a CONFLUENCE signal:
  "a rare breadth thrust just fired AND we're seeing informed call flow"
  is a higher-conviction setup than either alone.

This module is the pure engine (pure-Python, no deps, fully unit-tested):
  compute_features(bars) -> F
  detect_active(F)        -> patterns firing on the latest bar
  scan(bars)              -> active patterns + occurrence count + forward-return
                             stats at +5/+10/+20 days

`bars` is a list of dicts ordered oldest→newest:
  {"date": "YYYY-MM-DD", "open": float, "high": float, "low": float,
   "close": float, "volume": float}

Data loading (Stooq/yfinance/CSV) lives in scripts/analogue_scan.py — the
engine never touches the network so it stays deterministic + testable.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Callable

FWD_HORIZONS = (5, 10, 20)


# ── Indicator primitives (pure Python) ────────────────────────────────────
def sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if n <= 0 or not vals:
        return out
    k = 2.0 / (n + 1.0)
    prev: float | None = None
    for i, v in enumerate(vals):
        if prev is None:
            if i >= n - 1:
                seed = sum(vals[i - n + 1:i + 1]) / n  # seed with SMA
                out[i] = seed
                prev = seed
        else:
            prev = v * k + prev * (1 - k)
            out[i] = prev
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    avg_gain = gains / n
    avg_loss = losses / n
    out[n] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(ch, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-ch, 0.0)) / n
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _stddev(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(len(vals)):
        if i >= n - 1:
            win = vals[i - n + 1:i + 1]
            m = sum(win) / n
            var = sum((x - m) ** 2 for x in win) / n
            out[i] = var ** 0.5
    return out


def _roll_max(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(len(vals)):
        lo = max(0, i - n + 1)
        out[i] = max(vals[lo:i + 1])
    return out


def _roll_min(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(len(vals)):
        lo = max(0, i - n + 1)
        out[i] = min(vals[lo:i + 1])
    return out


# ── Feature frame ─────────────────────────────────────────────────────────
def compute_features(bars: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(b["close"]) for b in bars]
    highs = [float(b.get("high", b["close"])) for b in bars]
    lows = [float(b.get("low", b["close"])) for b in bars]
    opens = [float(b.get("open", b["close"])) for b in bars]
    dates = [b.get("date", "") for b in bars]

    macd_line: list[float | None] = [None] * len(closes)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    for i in range(len(closes)):
        if e12[i] is not None and e26[i] is not None:
            macd_line[i] = e12[i] - e26[i]
    macd_vals = [m if m is not None else 0.0 for m in macd_line]
    macd_signal = ema(macd_vals, 9)

    sma20 = sma(closes, 20)
    std20 = _stddev(closes, 20)
    bb_upper: list[float | None] = [None] * len(closes)
    bb_lower: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if sma20[i] is not None and std20[i] is not None:
            bb_upper[i] = sma20[i] + 2 * std20[i]
            bb_lower[i] = sma20[i] - 2 * std20[i]

    ranges = [highs[i] - lows[i] for i in range(len(closes))]
    return {
        "dates": dates, "close": closes, "high": highs, "low": lows, "open": opens,
        "sma20": sma20, "sma50": sma(closes, 50), "sma200": sma(closes, 200),
        "rsi": rsi(closes, 14),
        "macd": macd_line, "macd_signal": macd_signal,
        "bb_upper": bb_upper, "bb_lower": bb_lower,
        "max252": _roll_max(closes, 252), "min252": _roll_min(closes, 252),
        "range": ranges, "avg_range20": sma(ranges, 20),
        "n": len(closes),
    }


# ── Pattern detectors: fn(F, i) -> bool ───────────────────────────────────
def _consec_up(F, i, k=5):
    if i < k:
        return False
    return all(F["close"][j] > F["close"][j - 1] for j in range(i - k + 1, i + 1))


def _consec_down(F, i, k=5):
    if i < k:
        return False
    return all(F["close"][j] < F["close"][j - 1] for j in range(i - k + 1, i + 1))


def _n_day_rally(F, i, k=10, thr=0.05):
    if i < k:
        return False
    return F["close"][i] / F["close"][i - k] - 1.0 >= thr


def _n_day_drop(F, i, k=10, thr=0.05):
    if i < k:
        return False
    return F["close"][i] / F["close"][i - k] - 1.0 <= -thr


def _rsi_oversold(F, i, thr=30):
    r = F["rsi"][i]
    return r is not None and r < thr


def _rsi_overbought(F, i, thr=70):
    r = F["rsi"][i]
    return r is not None and r > thr


def _macd_bull_cross(F, i):
    if i < 1:
        return False
    a, b = F["macd"][i], F["macd_signal"][i]
    pa, pb = F["macd"][i - 1], F["macd_signal"][i - 1]
    return None not in (a, b, pa, pb) and pa <= pb and a > b


def _macd_bear_cross(F, i):
    if i < 1:
        return False
    a, b = F["macd"][i], F["macd_signal"][i]
    pa, pb = F["macd"][i - 1], F["macd_signal"][i - 1]
    return None not in (a, b, pa, pb) and pa >= pb and a < b


def _golden_cross(F, i):
    if i < 1:
        return False
    a, b = F["sma50"][i], F["sma200"][i]
    pa, pb = F["sma50"][i - 1], F["sma200"][i - 1]
    return None not in (a, b, pa, pb) and pa <= pb and a > b


def _death_cross(F, i):
    if i < 1:
        return False
    a, b = F["sma50"][i], F["sma200"][i]
    pa, pb = F["sma50"][i - 1], F["sma200"][i - 1]
    return None not in (a, b, pa, pb) and pa >= pb and a < b


def _below_200(F, i):
    s = F["sma200"][i]
    return s is not None and F["close"][i] < s


def _stretch_above_20(F, i, thr=0.05):
    s = F["sma20"][i]
    return s is not None and s > 0 and (F["close"][i] / s - 1.0) > thr


def _stretch_below_20(F, i, thr=0.05):
    s = F["sma20"][i]
    return s is not None and s > 0 and (F["close"][i] / s - 1.0) < -thr


def _above_upper_bb(F, i):
    u = F["bb_upper"][i]
    return u is not None and F["close"][i] > u


def _below_lower_bb(F, i):
    lo = F["bb_lower"][i]
    return lo is not None and F["close"][i] < lo


def _wide_range_day(F, i, k=2.0):
    a = F["avg_range20"][i]
    return a is not None and a > 0 and F["range"][i] > k * a


def _gap_up(F, i, g=0.01):
    if i < 1:
        return False
    return F["open"][i] > F["close"][i - 1] * (1 + g)


def _gap_down(F, i, g=0.01):
    if i < 1:
        return False
    return F["open"][i] < F["close"][i - 1] * (1 - g)


def _near_52w_high(F, i, pct=0.02):
    m = F["max252"][i]
    return m is not None and F["close"][i] >= m * (1 - pct)


def _near_52w_low(F, i, pct=0.02):
    m = F["min252"][i]
    return m is not None and F["close"][i] <= m * (1 + pct)


def _rsi_thrust_zweig(F, i, window=15, low=30, high=60):
    """RSI dipped below `low` within the last `window` bars, now above `high`."""
    r = F["rsi"][i]
    if r is None or r < high or i < window:
        return False
    return any(
        F["rsi"][j] is not None and F["rsi"][j] < low
        for j in range(i - window, i)
    )


def _bollinger_thrust(F, i, window=10):
    """Was below the lower band within `window` bars, now above the 20-SMA."""
    s = F["sma20"][i]
    if s is None or F["close"][i] <= s or i < window:
        return False
    return any(
        F["bb_lower"][j] is not None and F["close"][j] < F["bb_lower"][j]
        for j in range(i - window, i)
    )


# pattern registry: name -> (fn, bias)  (bias informational only)
PATTERNS: dict[str, tuple[Callable, str]] = {
    "consec_up_5d": (_consec_up, "bull"),
    "consec_down_5d": (_consec_down, "bear"),
    "rally_10d_5pct": (_n_day_rally, "bull"),
    "drop_10d_5pct": (_n_day_drop, "bear"),
    "rsi_oversold": (_rsi_oversold, "bull"),
    "rsi_overbought": (_rsi_overbought, "bear"),
    "macd_bull_cross": (_macd_bull_cross, "bull"),
    "macd_bear_cross": (_macd_bear_cross, "bear"),
    "golden_cross": (_golden_cross, "bull"),
    "death_cross": (_death_cross, "bear"),
    "below_200d": (_below_200, "bear"),
    "stretched_above_20d": (_stretch_above_20, "bear"),
    "stretched_below_20d": (_stretch_below_20, "bull"),
    "above_upper_bb": (_above_upper_bb, "bear"),
    "below_lower_bb": (_below_lower_bb, "bull"),
    "wide_range_day": (_wide_range_day, "neutral"),
    "gap_up": (_gap_up, "bull"),
    "gap_down": (_gap_down, "bear"),
    "near_52w_high": (_near_52w_high, "bull"),
    "near_52w_low": (_near_52w_low, "bear"),
    "rsi_thrust_zweig": (_rsi_thrust_zweig, "bull"),
    "bollinger_thrust": (_bollinger_thrust, "bull"),
}


# ── Detection + forward returns ───────────────────────────────────────────
def detect_active(F: dict[str, Any]) -> list[str]:
    """Patterns firing on the latest (last) bar."""
    i = F["n"] - 1
    if i < 0:
        return []
    out = []
    for name, (fn, _bias) in PATTERNS.items():
        try:
            if fn(F, i):
                out.append(name)
        except Exception:
            pass
    return out


def find_occurrences(F: dict[str, Any], pattern: str) -> list[int]:
    fn = PATTERNS[pattern][0]
    return [i for i in range(F["n"]) if _safe(fn, F, i)]


def _safe(fn, F, i) -> bool:
    try:
        return bool(fn(F, i))
    except Exception:
        return False


def forward_returns(
    closes: list[float], indices: list[int], horizons=FWD_HORIZONS,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    n = len(closes)
    for h in horizons:
        rets = [
            closes[i + h] / closes[i] - 1.0
            for i in indices if i + h < n and closes[i] > 0
        ]
        if rets:
            out[h] = {
                "n": len(rets),
                "mean_pct": round(100 * sum(rets) / len(rets), 2),
                "median_pct": round(100 * median(rets), 2),
                "hit_rate": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            }
        else:
            out[h] = {"n": 0, "mean_pct": None, "median_pct": None, "hit_rate": None}
    return out


def scan(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Full scan: active patterns + each one's historical base rate."""
    F = compute_features(bars)
    active = detect_active(F)
    results = []
    for name in active:
        occ = find_occurrences(F, name)
        # exclude the just-fired last bar from the base rate (no forward data)
        hist = [i for i in occ if i < F["n"] - 1]
        fwd = forward_returns(F["close"], hist)
        last_occ = max((i for i in hist), default=None)
        results.append({
            "pattern": name,
            "bias": PATTERNS[name][1],
            "occurrences": len(hist),
            "last_occurrence": F["dates"][last_occ] if last_occ is not None else None,
            "forward": fwd,
        })
    # sort: rarest-but-decisive first (fewest occurrences, then strongest 20d edge)
    results.sort(key=lambda r: (r["occurrences"],))
    return {
        "as_of": F["dates"][-1] if F["dates"] else None,
        "bars": F["n"],
        "active_count": len(active),
        "active": results,
    }
