"""Regime-gated FibLV band-fade — the Discord buddy's ACTUAL method.

He fades the OUTER FibLV band back toward the mean (small band-to-band moves,
NOT swinging for the fence — which he says loses, and our gap_fill_fade backtest
confirmed), and gates it on GEX/DEX regime: fade in a pinned regime, stand aside
in a volatile one. He's also SELECTIVE ("wait for the setup") — that discretion is
his likely alpha and is NOT capturable mechanically, so a flat mechanical result
does NOT disprove him; it just isolates the regime-gate's contribution.

What this tests (the testable core): does the REGIME GATE add value?
  - Outer-band touch (high>=+2sigma -> fade short; low<=-2sigma -> fade long).
  - Target = the mean (EMA-100 BASE at entry). Stop = 0.4x the target distance
    beyond the band (R:R ~2.5:1 toward the mean — a modest band-to-band fade).
  - Win = target before stop within 12 bars (1h on 5-min).
  - REGIME PROXY for GEX (real intraday SPY GEX history is heavy; this is v1):
    per-day intraday realized vol (std of 5-min log returns). LOW-vol day =
    pinned / positive-GEX-like; HIGH-vol day = volatile / negative-GEX-like.
  - DECISIVE: compare fade win-rate LOW-vol vs HIGH-vol (the "look at GEX/DEX"
    claim), each vs a distance-matched random-entry control. Day-clustered
    bootstrap on the LOW-minus-HIGH difference.

Out -> data/band_fade_regime_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import databento_bars as DB
import fib_lv_bootstrap as FB   # band_continuous (EMA100 +/- 2sigma)

FREQ = "5min"; HORIZON = 12; STOP_FRAC = 0.4; N_BOOT = 3000
RNG = np.random.default_rng(20260619)


def prep(ticker):
    d = DB.load_ohlcv(ticker, FREQ).sort_values("t").reset_index(drop=True)
    d = FB.band_continuous(d)   # adds b5 (mean), u5 (+2s), d5 (-2s)
    d = d.dropna(subset=["b5", "u5", "d5"]).reset_index(drop=True)
    d["ret"] = np.log(d["close"]).groupby(d["date"]).diff()
    rv = d.groupby("date")["ret"].std().rename("rv")
    d = d.merge(rv, on="date")
    med = rv.median()
    d["regime"] = np.where(d["rv"] <= med, "LOW", "HIGH")
    return d


def fades(d):
    """One fade trade per outer-band touch. Returns list of dicts."""
    h, l, c = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
    b, u, dn = d.b5.to_numpy(), d.u5.to_numpy(), d.d5.to_numpy()
    date = d.date.to_numpy(); regime = d.regime.to_numpy()
    n = len(d); out = []
    for i in range(n - 1):
        for side in ("short", "long"):
            if side == "short" and h[i] >= u[i]:
                entry, target = u[i], b[i]
                if entry <= target:
                    continue
                stop = entry + STOP_FRAC * (entry - target)
            elif side == "long" and l[i] <= dn[i]:
                entry, target = dn[i], b[i]
                if target <= entry:
                    continue
                stop = entry - STOP_FRAC * (target - entry)
            else:
                continue
            win = None
            for v in range(i + 1, min(n - 1, i + HORIZON) + 1):
                if date[v] != date[i]:
                    break                       # don't hold across days
                if side == "short":
                    if l[v] <= target: win = 1; break
                    if h[v] >= stop:   win = 0; break
                else:
                    if h[v] >= target: win = 1; break
                    if l[v] <= stop:   win = 0; break
            if win is None:
                continue
            tgt_d = abs(entry - target) / entry
            out.append({"side": side, "win": win, "regime": regime[i],
                        "date": date[i], "tgt_d": tgt_d,
                        "stop_d": STOP_FRAC * tgt_d})
    return out


def control(d, side, tgt_d, stop_d, regime, n_draws=4000):
    """Distance-matched random entries within the same regime's bars."""
    sub = d[d.regime == regime]
    h, l, c = sub.high.to_numpy(), sub.low.to_numpy(), sub.close.to_numpy()
    dt = sub.date.to_numpy(); n = len(sub)
    wins = tot = tries = 0
    while tot < n_draws and tries < n_draws * 6:
        tries += 1
        i = int(RNG.integers(0, n - HORIZON - 1))
        entry = c[i]
        if side == "short":
            target, stop = entry * (1 - tgt_d), entry * (1 + stop_d)
        else:
            target, stop = entry * (1 + tgt_d), entry * (1 - stop_d)
        res = None
        for v in range(i + 1, i + HORIZON + 1):
            if dt[v] != dt[i]: break
            if side == "short":
                if l[v] <= target: res = 1; break
                if h[v] >= stop:   res = 0; break
            else:
                if h[v] >= target: res = 1; break
                if l[v] <= stop:   res = 0; break
        if res is not None:
            wins += res; tot += 1
    return wins / tot if tot else None


def analyze(ticker):
    d = prep(ticker)
    f = pd.DataFrame(fades(d))
    res = {"n_touches": len(f), "n_days": int(d.date.nunique())}
    if len(f) < 50:
        res["note"] = "too few"; return res
    for reg in ("LOW", "HIGH"):
        g = f[f.regime == reg]
        if len(g) < 20:
            res[reg] = {"n": len(g), "note": "thin"}; continue
        wr = float(g.win.mean())
        mt = float(g.tgt_d.median())
        # distance-matched control: blend both sides by their share
        ctl = []
        for side in ("short", "long"):
            gs = g[g.side == side]
            if len(gs) >= 10:
                cw = control(d, side, mt, STOP_FRAC * mt, reg)
                if cw is not None:
                    ctl.append((cw, len(gs)))
        ctrl = (sum(w * n for w, n in ctl) / sum(n for _, n in ctl)) if ctl else None
        res[reg] = {"n": len(g), "win_rate": round(wr, 3),
                    "control_win_rate": round(ctrl, 3) if ctrl else None,
                    "lift_vs_control": round(wr - ctrl, 3) if ctrl else None,
                    "median_target_pct": round(mt * 100, 2)}
    # day-clustered bootstrap on LOW-minus-HIGH win-rate gap
    lo, hi = f[f.regime == "LOW"], f[f.regime == "HIGH"]
    if len(lo) >= 20 and len(hi) >= 20:
        days = f.date.unique(); by = {dd: f[f.date == dd] for dd in days}
        draws = []
        for _ in range(N_BOOT):
            pick = pd.concat([by[x] for x in RNG.choice(days, len(days), True)])
            a = pick[pick.regime == "LOW"].win; b = pick[pick.regime == "HIGH"].win
            if len(a) and len(b):
                draws.append(a.mean() - b.mean())
        draws = np.array(draws)
        res["LOW_minus_HIGH_winrate"] = {
            "obs": round(float(lo.win.mean() - hi.win.mean()), 3),
            "ci95": [round(float(np.percentile(draws, 2.5)), 3),
                     round(float(np.percentile(draws, 97.5)), 3)],
            "one_sided_p_le_0": round(float((draws <= 0).mean()), 4),
            "verdict": ("REGIME GATE ADDS VALUE"
                        if np.percentile(draws, 2.5) > 0 else "gate not significant")}
    return res


def run():
    out = {"freq": FREQ, "horizon_bars": HORIZON, "stop_frac": STOP_FRAC,
           "regime_proxy": "intraday realized-vol median split (LOW=pinned-like)",
           "note": "mechanical version; cannot capture his discretion/selectivity"}
    for tk in ("SPY", "QQQ"):
        out[tk] = analyze(tk)
    print(json.dumps(out, indent=2))
    Path("data/band_fade_regime_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
