"""
0DTE ATM-call backtest on cached scan data for 2026-06-18 (a trend day; ALL 30 names closed UP).

Strategy family: fixed ENTRY=11:45, EXIT=15:50. Filter on intraday strength at 11:45.
  - X-filter: only enter names whose underlying close at 11:45 is >= X% above the day open.
    X in {0, 5, 8, 10, 12}.
  - RVOL alt: rank names by 11:45 entry-bar volume and take top-K.

Rules:
  (1) ask-in / bid-out always.
  (2) survivorship: a near-zero / worthless exit bid is a REAL loss (~-100%). COUNT it, never drop.
  (3) entry_ask must be > 0 to trade.
  (4) report n, mean, median, win-rate, best, worst per variant.

stdlib only (json, math).
"""
import json
import math

DATA = "data/intraday_today_20260618.json"
ENTRY_T = "11:45"
EXIT_T = "15:50"


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def nearest_bar(path, target, key_t="t"):
    """Return the bar whose time == target, else the nearest by absolute minute distance."""
    if not path:
        return None
    tgt = to_min(target)
    exact = [b for b in path if b[key_t] == target]
    if exact:
        return exact[0]
    return min(path, key=lambda b: abs(to_min(b[key_t]) - tgt))


def underlying_close_at(ubars, target):
    b = nearest_bar(ubars, target)
    return b["c"] if b else None


def underlying_vol_at(ubars, target):
    b = nearest_bar(ubars, target)
    return b["v"] if b else None


def build_trades(d, restrict_universe):
    """Return list of dicts: ticker, ret, entry_ask, exit_bid, strength_pct, entry_vol."""
    trades = []
    for tk, v in d.items():
        if restrict_universe and not v.get("in_universe"):
            continue
        op = v["open"]
        ubars = v["underlying_bars"]
        opt = v["option_path"]
        # strength at 11:45
        c1145 = underlying_close_at(ubars, ENTRY_T)
        if c1145 is None or op in (None, 0):
            continue
        strength = (c1145 / op - 1.0) * 100.0
        vol1145 = underlying_vol_at(ubars, ENTRY_T)
        # option entry/exit
        eb = nearest_bar(opt, ENTRY_T)
        xb = nearest_bar(opt, EXIT_T)
        if eb is None or xb is None:
            continue
        entry_ask = eb["ask"]
        exit_bid = xb["bid"]
        if entry_ask is None or entry_ask <= 0:
            continue  # rule (3): cannot trade
        # rule (2): exit_bid of 0 is a real -100% loss, kept.
        ret = (exit_bid - entry_ask) / entry_ask
        trades.append({
            "ticker": tk,
            "ret": ret,
            "entry_ask": entry_ask,
            "exit_bid": exit_bid,
            "strength_pct": strength,
            "entry_vol": vol1145 if vol1145 is not None else 0,
        })
    return trades


def stats(rets):
    n = len(rets)
    if n == 0:
        return dict(n=0, mean=None, median=None, win=None, best=None, worst=None)
    s = sorted(rets)
    mean = sum(s) / n
    if n % 2:
        median = s[n // 2]
    else:
        median = (s[n // 2 - 1] + s[n // 2]) / 2.0
    win = sum(1 for r in rets if r > 0) / n * 100.0
    return dict(n=n, mean=mean * 100.0, median=median * 100.0,
                win=win, best=max(rets) * 100.0, worst=min(rets) * 100.0)


def pct(x):
    return f"{x:6.1f}%" if x is not None else "   n/a"


def run(label, trades):
    print(f"\n===== {label} (pool n={len(trades)}) =====")
    print("\n-- X% strength filter (underlying up >= X% from open at 11:45) --")
    print(f"{'X':>4} {'n':>3} {'mean':>8} {'median':>8} {'win%':>7} {'best':>9} {'worst':>9}  names")
    rows_x = {}
    for X in [0, 5, 8, 10, 12]:
        sub = [t for t in trades if t["strength_pct"] >= X]
        st = stats([t["ret"] for t in sub])
        rows_x[X] = (st, sub)
        names = ",".join(sorted(t["ticker"] for t in sub))
        print(f"{X:>4} {st['n']:>3} {pct(st['mean'])} {pct(st['median'])} "
              f"{(f'{st[chr(119)+chr(105)+chr(110)]:5.1f}%' if st['win'] is not None else '  n/a'):>7} "
              f"{pct(st['best'])} {pct(st['worst'])}  {names}")

    print("\n-- RVOL alt: rank by 11:45 entry-bar volume, take top-K --")
    print(f"{'K':>4} {'n':>3} {'mean':>8} {'median':>8} {'win%':>7} {'best':>9} {'worst':>9}  names")
    ranked = sorted(trades, key=lambda t: t["entry_vol"], reverse=True)
    rows_v = {}
    for K in [3, 5, 8, 10]:
        sub = ranked[:K]
        if not sub:
            continue
        st = stats([t["ret"] for t in sub])
        rows_v[K] = (st, sub)
        names = ",".join(t["ticker"] for t in sub)
        print(f"{K:>4} {st['n']:>3} {pct(st['mean'])} {pct(st['median'])} "
              f"{(f'{st[chr(119)+chr(105)+chr(110)]:5.1f}%' if st['win'] is not None else '  n/a'):>7} "
              f"{pct(st['best'])} {pct(st['worst'])}  {names}")
    return rows_x, rows_v


def main():
    d = json.load(open(DATA))
    print(f"Loaded {len(d)} tickers from {DATA}")
    print(f"ENTRY={ENTRY_T} ask-in, EXIT={EXIT_T} bid-out. Survivorship: zero exit-bid kept as real loss.")

    # detail dump of every in-universe trade so the zero-bid losses are visible
    tr_univ = build_trades(d, restrict_universe=True)
    print("\n-- per-name detail (in-universe pool) --")
    print(f"{'tk':>6} {'strength%':>9} {'entryVol':>10} {'entry_ask':>9} {'exit_bid':>8} {'ret%':>8}")
    for t in sorted(tr_univ, key=lambda x: -x["strength_pct"]):
        print(f"{t['ticker']:>6} {t['strength_pct']:9.2f} {t['entry_vol']:>10} "
              f"{t['entry_ask']:9.2f} {t['exit_bid']:8.2f} {t['ret']*100:8.1f}")
    zero = [t for t in tr_univ if t["exit_bid"] <= 0.0]
    print(f"  zero/worthless exit-bids counted as losses: {len(zero)} -> {[t['ticker'] for t in zero]}")

    run("IN-UNIVERSE (12 scan names) PRIMARY", tr_univ)

    tr_all = build_trades(d, restrict_universe=False)
    run("ALL 30 NAMES (incl. out-of-universe) reference", tr_all)


if __name__ == "__main__":
    main()
