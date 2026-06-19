"""
0DTE ATM-call exit-rule backtest on cached scan data for 2026-06-18.

ENTRY: fixed at 11:00 ask for ALL names (entry_ask must be > 0 to trade).
EXITS (variants tested):
  hold-15:50         : exit at 15:50 bid
  hold-15:55         : exit at 15:55 bid
  +50% target        : first bar where bid >= 1.50*entry_ask -> exit that bid; else hold-15:55 bid
  +100% target       : first bar where bid >= 2.00*entry_ask -> exit that bid; else hold-15:55 bid
  -50% stop          : first bar where bid <= 0.50*entry_ask -> exit that bid; else hold-15:55 bid
  trail-30%-from-peak: scan forward, track running peak bid; exit first bar where bid <= 0.70*peak; else hold-15:55 bid
  vwap-exit          : exit first 5-min bar (>11:00) whose underlying close < that bar's session-VWAP; exit at that bar's option bid; else hold-15:55 bid

RULES:
  - ask-in / bid-out always.
  - SURVIVORSHIP: a worthless / near-zero exit bid is a REAL loss. It is COUNTED, never dropped.
  - return = (exit_bid - entry_ask) / entry_ask
  - stdlib only (json, math).
"""
import json
import math

DATA = "data/intraday_today_20260618.json"
ENTRY_T = "11:00"
LAST_T = "15:55"
PEN_T = "15:50"

TIMES = []  # filled with the sorted 5-min grid >= 11:00


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def nearest_bar(path_by_t, target):
    """Return the bar at time==target, or nearest by abs minute distance."""
    if target in path_by_t:
        return path_by_t[target]
    tgt = hhmm_to_min(target)
    best = None
    best_d = None
    for t, b in path_by_t.items():
        d = abs(hhmm_to_min(t) - tgt)
        if best_d is None or d < best_d:
            best_d = d
            best = b
    return best


def forward_times(path_by_t, start=ENTRY_T):
    """Sorted option_path times strictly after entry (inclusive of entry+1), up to last."""
    s = hhmm_to_min(start)
    ts = sorted((t for t in path_by_t if hhmm_to_min(t) > s), key=hhmm_to_min)
    return ts


def und_vwap_below(und_by_t, t):
    """True if underlying close < session vwap at bar time t (data carries per-bar vwap)."""
    b = und_by_t.get(t)
    if b is None:
        return None
    return b["c"] < b["vwap"]


def stats(returns):
    n = len(returns)
    if n == 0:
        return dict(n=0, mean=0, median=0, win=0, best=0, worst=0)
    s = sorted(returns)
    mean = sum(s) / n
    if n % 2:
        median = s[n // 2]
    else:
        median = (s[n // 2 - 1] + s[n // 2]) / 2
    wins = sum(1 for r in returns if r > 0)
    return dict(n=n, mean=mean, median=median, win=100.0 * wins / n,
                best=max(s), worst=min(s))


def run():
    d = json.load(open(DATA))
    # Collect per-ticker entry/exit for each variant
    variants = ["hold-15:50", "hold-15:55", "+50% target", "+100% target",
                "-50% stop", "trail-30%-peak", "vwap-exit"]
    results = {v: [] for v in variants}
    per_name = {}  # ticker -> {variant: ret}

    traded = 0
    skipped = 0
    for tk, t in d.items():
        opt_by_t = {b["t"]: b for b in t["option_path"]}
        und_by_t = {b["t"]: b for b in t["underlying_bars"]}

        entry_bar = nearest_bar(opt_by_t, ENTRY_T)
        entry_ask = entry_bar["ask"]
        if not (entry_ask and entry_ask > 0):
            skipped += 1
            continue
        traded += 1

        last_bid = nearest_bar(opt_by_t, LAST_T)["bid"]
        pen_bid = nearest_bar(opt_by_t, PEN_T)["bid"]

        fwd = forward_times(opt_by_t)  # times strictly after 11:00 in chronological order

        def ret(exit_bid):
            return (exit_bid - entry_ask) / entry_ask

        pn = {}

        # hold variants
        pn["hold-15:50"] = ret(pen_bid)
        pn["hold-15:55"] = ret(last_bid)

        # +50% target: first forward bar with bid >= 1.5*entry_ask
        tgt = 1.5 * entry_ask
        hit = next((opt_by_t[tt]["bid"] for tt in fwd if opt_by_t[tt]["bid"] >= tgt), None)
        pn["+50% target"] = ret(hit) if hit is not None else ret(last_bid)

        # +100% target
        tgt2 = 2.0 * entry_ask
        hit2 = next((opt_by_t[tt]["bid"] for tt in fwd if opt_by_t[tt]["bid"] >= tgt2), None)
        pn["+100% target"] = ret(hit2) if hit2 is not None else ret(last_bid)

        # -50% stop: first forward bar with bid <= 0.5*entry_ask
        stp = 0.5 * entry_ask
        hits = next((opt_by_t[tt]["bid"] for tt in fwd if opt_by_t[tt]["bid"] <= stp), None)
        pn["-50% stop"] = ret(hits) if hits is not None else ret(last_bid)

        # trailing 30% from running peak bid
        peak = entry_bar["bid"]  # start peak at entry bid
        trail_exit = None
        for tt in fwd:
            b = opt_by_t[tt]["bid"]
            if b > peak:
                peak = b
            if peak > 0 and b <= 0.70 * peak:
                trail_exit = b
                break
        pn["trail-30%-peak"] = ret(trail_exit) if trail_exit is not None else ret(last_bid)

        # vwap-exit: first forward underlying bar whose close < its session vwap
        vwap_exit = None
        for tt in fwd:
            below = und_vwap_below(und_by_t, tt)
            if below is True:
                vwap_exit = opt_by_t[tt]["bid"]
                break
        pn["vwap-exit"] = ret(vwap_exit) if vwap_exit is not None else ret(last_bid)

        for v in variants:
            results[v].append(pn[v])
        per_name[tk] = pn

    print(f"Tickers in file: {len(d)} | traded (entry_ask>0): {traded} | skipped: {skipped}")
    print(f"All names closed UP (trend day). Survivorship: near-zero exit bids COUNTED as real ~-100% losses.\n")

    # Whipsaw check
    s50 = stats(results["hold-15:50"])
    s55 = stats(results["hold-15:55"])
    print("=== 15:50 vs 15:55 CLOSE WHIPSAW ===")
    print(f"hold-15:50  mean={s50['mean']*100:+.1f}%  median={s50['median']*100:+.1f}%")
    print(f"hold-15:55  mean={s55['mean']*100:+.1f}%  median={s55['median']*100:+.1f}%")
    flips = []
    for tk in per_name:
        a = per_name[tk]["hold-15:50"]
        b = per_name[tk]["hold-15:55"]
        if abs(a - b) >= 0.15:
            flips.append((tk, a, b))
    print("Names with |delta| >= 15pts between 15:50 and 15:55 exit:")
    for tk, a, b in sorted(flips, key=lambda x: -abs(x[1] - x[2])):
        print(f"  {tk:6} 15:50={a*100:+.1f}%  15:55={b*100:+.1f}%  delta={(b-a)*100:+.1f}pts")
    print()

    print("=== VARIANT TABLE (entry = 11:00 ask, all 30 names) ===")
    hdr = f"{'variant':18} {'n':>3} {'mean%':>8} {'median%':>8} {'win%':>6} {'best%':>8} {'worst%':>8}"
    print(hdr)
    print("-" * len(hdr))
    rows = {}
    for v in variants:
        st = stats(results[v])
        rows[v] = st
        print(f"{v:18} {st['n']:>3} {st['mean']*100:>8.1f} {st['median']*100:>8.1f} "
              f"{st['win']:>6.1f} {st['best']*100:>8.1f} {st['worst']*100:>8.1f}")

    # Which maximizes mean AND median
    best_mean = max(variants, key=lambda v: rows[v]["mean"])
    best_med = max(variants, key=lambda v: rows[v]["median"])
    print(f"\nBest MEAN:   {best_mean} ({rows[best_mean]['mean']*100:+.1f}%)")
    print(f"Best MEDIAN: {best_med} ({rows[best_med]['median']*100:+.1f}%)")

    # JSON dump for downstream
    out = {v: stats(results[v]) for v in variants}
    print("\nMACHINE:" + json.dumps(out))
    print("PERNAME:" + json.dumps(per_name))


if __name__ == "__main__":
    run()
