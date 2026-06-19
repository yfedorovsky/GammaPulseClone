"""Gap-fill fade backtest — does the OG GammaPulse "gap-fill zone" bearish setup
have a real edge, or was the 6/17 META alert luck? Direction-A, daily bars.

The setup (from the META 6/17 alert): a stock gaps UP, later rallies back to
re-test the post-gap high (resistance / "ceiling"), the gap below is still
unfilled -> short the re-test, target = the gap fill, stop = above the high.

Tested on a universe of liquid optionable names, daily OHLC via yfinance (decades).
No single-name intraday needed; the thesis is a daily-bar pattern.

Definitions (per ticker):
  - GAP-UP event at day t: open[t]/close[t-1]-1 >= G (default 3%).
    gap bottom = close[t-1] (the fill target); gap top = open[t].
  - The gap is "live" until a later low <= gap bottom (FILLED) or N days pass.
  - FADE TRIGGER = first later day u (t<u<=t+N), gap still unfilled, where
    close[u] >= (1-X)*max(high[t..u])  (back near the post-gap high) AND
    close[u] > gap_top                 (still extended above the gap).
  - TRADE from u: entry=close[u], target=gap_bottom, stop=max(high[t..u]) (the
    resistance). WIN = low reaches target before high exceeds stop within M days.

Hypotheses:
  H1  base structural fact: P(gap fills within N days).
  H2  the fade setup wins (target before stop).
  CONTROL (decisive): distance-matched random shorts — same target% and stop%
    distances, drawn from ALL (ticker,day) bars with no gap context. The setup
    must beat the distance-matched baseline (same discipline as FibLV/EMA-ride).
Inference: event-clustered bootstrap (resample tickers) on the win-rate lift.

Out -> data/gap_fill_fade_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

UNIV = ("META AAPL MSFT NVDA AMZN GOOGL TSLA AMD AVGO NFLX CRM ORCL ADBE COIN MU "
        "MRVL SMCI PLTR SHOP UBER ABNB SNOW DDOG NET CRWD PANW QCOM TXN INTC AMAT "
        "LRCX ARM DELL MDB ZS PYPL SQ ROKU DKNG").split()
G = 0.03      # min gap-up
N = 20        # gap stays "live" this many days
X = 0.02      # "near the high" tolerance
M = 10        # trade horizon (days to hit target or stop)
N_BOOT = 3000
RNG = np.random.default_rng(20260619)


def bars(tkr: str) -> pd.DataFrame:
    cache = Path(f"data/daily_long_{tkr}.parquet")
    if cache.exists():
        d = pd.read_parquet(cache)
    else:
        import yfinance as yf
        d = yf.download(tkr, start="2014-01-01", auto_adjust=True, progress=False)
        if d is None or d.empty:
            return pd.DataFrame()
        d = d.reset_index()
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]
        d = d[["Date", "Open", "High", "Low", "Close"]].rename(
            columns={"Date": "date", "Open": "open", "High": "high",
                     "Low": "low", "Close": "close"})
        d.to_parquet(cache, index=False)
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("date").reset_index(drop=True)


def trades_for(tkr: str):
    d = bars(tkr)
    if len(d) < 60:
        return [], []
    o, h, l, c = (d.open.to_numpy(), d.high.to_numpy(),
                  d.low.to_numpy(), d.close.to_numpy())
    n = len(d)
    fills, setups = [], []
    for t in range(1, n - 1):
        if o[t] / c[t - 1] - 1.0 < G:
            continue
        gap_bot, gap_top = c[t - 1], o[t]
        end = min(n - 1, t + N)
        # gap fill?
        filled_day = None
        run_high = h[t]
        trig = None
        for u in range(t, end + 1):
            run_high = max(run_high, h[u])
            if l[u] <= gap_bot:
                filled_day = u
                break
            if (u > t and trig is None and c[u] >= (1 - X) * run_high
                    and c[u] > gap_top):
                trig = (u, run_high)
        fills.append(1 if filled_day is not None else 0)
        if trig is None:
            continue
        u, resist = trig
        entry, target, stop = c[u], gap_bot, resist
        if stop <= entry:                      # need room above for the stop
            continue
        tgt_d = (entry - target) / entry        # how far down to target
        stop_d = (stop - entry) / entry         # how far up to stop
        if tgt_d <= 0:
            continue
        win = None
        for v in range(u + 1, min(n - 1, u + M) + 1):
            if l[v] <= target:
                win = 1
                break
            if h[v] >= stop:
                win = 0
                break
        if win is not None:
            setups.append({"tkr": tkr, "win": win, "tgt_d": tgt_d, "stop_d": stop_d})
    return fills, setups


def control_winrate(daily_by_tkr, tgt_d, stop_d, n_draws=4000):
    """Distance-matched random shorts: pick random (tkr,day), short, target tgt_d
    below / stop stop_d above, same M-day horizon. Returns win rate."""
    tkrs = list(daily_by_tkr.keys())
    wins = tot = 0
    tries = 0
    while tot < n_draws and tries < n_draws * 6:
        tries += 1
        tk = tkrs[RNG.integers(len(tkrs))]
        d = daily_by_tkr[tk]
        cl, hi, lo = d["close"], d["high"], d["low"]
        nrows = len(cl)
        if nrows < M + 5:
            continue
        i = int(RNG.integers(1, nrows - M - 1))
        entry = cl[i]
        target = entry * (1 - tgt_d)
        stop = entry * (1 + stop_d)
        res = None
        for v in range(i + 1, i + M + 1):
            if lo[v] <= target:
                res = 1
                break
            if hi[v] >= stop:
                res = 0
                break
        if res is not None:
            wins += res
            tot += 1
    return wins / tot if tot else None


def run():
    daily = {}
    all_fills, all_setups = [], []
    for tk in UNIV:
        d = bars(tk)
        if len(d) < 60:
            continue
        daily[tk] = {"close": d.close.to_numpy(), "high": d.high.to_numpy(),
                     "low": d.low.to_numpy()}
        f, s = trades_for(tk)
        all_fills += f
        all_setups += s
    sf = pd.DataFrame(all_setups)
    out = {"universe_n": len(daily), "gap_min": G, "N_live": N, "M_horizon": M,
           "n_gap_events": len(all_fills),
           "H1_gap_fill_rate_within_N": round(float(np.mean(all_fills)), 3)}
    if len(sf) < 30:
        out["note"] = f"only {len(sf)} fade setups — too few"
        print(json.dumps(out, indent=2)); Path("data/gap_fill_fade_results.json").write_text(json.dumps(out, indent=2)); return
    setup_wr = float(sf.win.mean())
    # distance-matched control: median target/stop distances of the setups
    med_t, med_s = float(sf.tgt_d.median()), float(sf.stop_d.median())
    ctrl_wr = control_winrate(daily, med_t, med_s)
    # event-clustered bootstrap (resample tickers) on the lift
    by_tk = {tk: sf[sf.tkr == tk] for tk in sf.tkr.unique()}
    tks = list(by_tk.keys())
    draws = []
    for _ in range(N_BOOT):
        pick = RNG.choice(tks, size=len(tks), replace=True)
        pooled = pd.concat([by_tk[t] for t in pick])
        draws.append(pooled.win.mean() - ctrl_wr)
    draws = np.array(draws)
    out.update({
        "n_fade_setups": len(sf),
        "setup_win_rate": round(setup_wr, 3),
        "dist_matched_control_win_rate": round(ctrl_wr, 3),
        "median_target_dist_pct": round(med_t * 100, 2),
        "median_stop_dist_pct": round(med_s * 100, 2),
        "lift_vs_control": round(setup_wr - ctrl_wr, 3),
        "boot_ci95": [round(float(np.percentile(draws, 2.5)), 3),
                      round(float(np.percentile(draws, 97.5)), 3)],
        "one_sided_p_lift_le_0": round(float((draws <= 0).mean()), 4),
        "verdict": ("EDGE (CI excludes 0)"
                    if np.percentile(draws, 2.5) > 0 else "NO EDGE vs distance-matched"),
    })
    print(json.dumps(out, indent=2))
    Path("data/gap_fill_fade_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
