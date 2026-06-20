"""Shared QQQ backtest harness — common data loaders + Direction-A inference
primitives so every pattern test uses the SAME statistics (no agent reinvents
the controls). Import this; implement only your pattern's event detection.

Data:
  load_daily()            -> QQQ daily OHLCV 1999-2026 (date,open,high,low,close,volume)
  load_intraday(freq)     -> QQQ Databento intraday OHLCV (1min/5min, 159 days)
  load_ofi()              -> QQQ per-bar OFI/tsv/mid/ret (Databento)

Indicators: ema, sma, atr, rsi, rolling_high, rolling_low.

Inference (the discipline):
  fwd_ret(close, k)                          -> forward k-bar simple return
  event_study(fwd, mask, n_perm)             -> event vs base mean & win-rate,
                                                PERMUTATION p (random event days) +
                                                bootstrap CI on the lift. Use for
                                                directional signals (cross, vol spike).
  barrier_test(df, idx, side, tgt, stop, M)  -> win array (target before stop in M bars)
  dist_matched_control(df, side, tgt, stop,  -> base win-rate of random entries with
                       M, n)                     the SAME target/stop distances
  block_bootstrap_diff(win, ctrl_rate, ...)  -> CI + p on (setup_wr - control)
  STANDARD verdict: an edge requires the lift's 95% CI to EXCLUDE 0.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent.parent
RNG = np.random.default_rng(20260619)


# ---- data ----
def load_daily() -> pd.DataFrame:
    d = pd.read_parquet(ROOT / "data" / "qqq_daily.parquet")
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("date").reset_index(drop=True)


def load_intraday(freq: str = "5min") -> pd.DataFrame:
    import databento_bars as DB
    return DB.load_ohlcv("QQQ", freq).sort_values("t").reset_index(drop=True)


def load_ofi(freq: str = "1min") -> pd.DataFrame:
    import databento_bars as DB
    return DB.load_ofi("QQQ", freq).sort_values("t").reset_index(drop=True)


# ---- indicators ----
def ema(s, n):  return pd.Series(s).ewm(span=n, min_periods=n).mean().to_numpy()
def sma(s, n):  return pd.Series(s).rolling(n).mean().to_numpy()
def rolling_high(s, n): return pd.Series(s).rolling(n).max().to_numpy()
def rolling_low(s, n):  return pd.Series(s).rolling(n).min().to_numpy()


def atr(df, n=14):
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def rsi(s, n=14):
    s = pd.Series(s); d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, min_periods=n).mean()
    return (100 - 100/(1 + up/dn)).to_numpy()


# ---- inference ----
def fwd_ret(close, k):
    c = pd.Series(close)
    return (c.shift(-k) / c - 1.0).to_numpy()


def event_study(fwd, mask, n_perm=5000):
    """Directional signal test. fwd = forward returns aligned to bars; mask =
    boolean event flags. Permutation null = random event-day sets (controls base
    rate). Returns event vs base mean+winrate, permutation p, bootstrap CI on lift."""
    fwd = np.asarray(fwd, float); mask = np.asarray(mask, bool)
    ok = np.isfinite(fwd)
    base_idx = np.where(ok)[0]
    ev_idx = np.where(ok & mask)[0]
    n = len(ev_idx)
    if n < 20:
        return {"n_events": int(n), "note": "too few events"}
    ev_mean = float(fwd[ev_idx].mean()); base_mean = float(fwd[base_idx].mean())
    ev_win = float((fwd[ev_idx] > 0).mean()); base_win = float((fwd[base_idx] > 0).mean())
    obs = ev_mean - base_mean
    # permutation: random n events among all valid bars
    nullm = np.empty(n_perm)
    for i in range(n_perm):
        nullm[i] = fwd[RNG.choice(base_idx, n, replace=False)].mean()
    p = float((np.abs(nullm - base_mean) >= abs(obs)).mean())
    # bootstrap CI on event mean lift (resample events)
    boots = np.array([fwd[RNG.choice(ev_idx, n, replace=True)].mean() - base_mean
                      for _ in range(2000)])
    return {"n_events": int(n),
            "event_fwd_mean": round(ev_mean, 5), "base_fwd_mean": round(base_mean, 5),
            "lift": round(obs, 5),
            "event_win": round(ev_win, 3), "base_win": round(base_win, 3),
            "perm_p": round(p, 4),
            "lift_ci95": [round(float(np.percentile(boots, 2.5)), 5),
                          round(float(np.percentile(boots, 97.5)), 5)],
            "verdict": ("EDGE" if np.percentile(boots, 2.5) > 0
                        or np.percentile(boots, 97.5) < 0 else "NULL")}


def barrier_test(df, idx, side, tgt_pct, stop_pct, horizon, intraday_day_col=None):
    """For each entry index, did price hit target before stop within `horizon`
    bars? side='long'/'short'. tgt_pct/stop_pct as fractions. Returns win list
    (1/0) aligned to the subset that resolved. If intraday_day_col given, do not
    hold across that day boundary."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    day = df[intraday_day_col].to_numpy() if intraday_day_col else None
    n = len(df); out = []
    for i in idx:
        if i + 1 >= n:
            continue
        entry = c[i]
        if side == "long":
            tgt, stop = entry*(1+tgt_pct), entry*(1-stop_pct)
        else:
            tgt, stop = entry*(1-tgt_pct), entry*(1+stop_pct)
        res = None
        for v in range(i+1, min(n-1, i+horizon)+1):
            if day is not None and day[v] != day[i]:
                break
            if side == "long":
                if h[v] >= tgt: res = 1; break
                if l[v] <= stop: res = 0; break
            else:
                if l[v] <= tgt: res = 1; break
                if h[v] >= stop: res = 0; break
        if res is not None:
            out.append(res)
    return out


def dist_matched_control(df, side, tgt_pct, stop_pct, horizon, n_draws=4000,
                         intraday_day_col=None):
    n = len(df)
    idx = RNG.integers(1, n - horizon - 1, size=n_draws*3)
    wins = barrier_test(df, idx, side, tgt_pct, stop_pct, horizon, intraday_day_col)
    wins = wins[:n_draws]
    return float(np.mean(wins)) if wins else None


def block_bootstrap_diff(win_list, control_rate, n_boot=3000):
    """CI + one-sided p on (setup_winrate - control_rate)."""
    w = np.asarray(win_list, float)
    if not len(w) or control_rate is None:
        return None
    obs = w.mean() - control_rate
    boots = np.array([w[RNG.integers(0, len(w), len(w))].mean() - control_rate
                      for _ in range(n_boot)])
    return {"setup_win": round(float(w.mean()), 3), "control_win": round(control_rate, 3),
            "lift": round(float(obs), 3),
            "ci95": [round(float(np.percentile(boots, 2.5)), 3),
                     round(float(np.percentile(boots, 97.5)), 3)],
            "one_sided_p_le_0": round(float((boots <= 0).mean()), 4),
            "verdict": ("EDGE" if np.percentile(boots, 2.5) > 0 else "NULL")}
