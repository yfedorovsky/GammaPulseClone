"""
0DTE ATM-call entry-time-curve backtest on cached scan-name data for 2026-06-18.

Strategy family: ENTRY = fixed clock time, EXIT = 15:50 bid.
One 0DTE ATM call per scan ticker. ask-in / bid-out always.

HARD RULES enforced:
  (1) ask-in / bid-out always.
  (2) SURVIVORSHIP: worthless/near-zero exit bid is a REAL loss; COUNT it, never drop it.
  (3) entry_ask must be > 0 to trade.
  (4) report n, mean, median, win-rate, best, worst per variant.

stdlib only.
"""
import json
import math

DATA = "data/intraday_today_20260618.json"
ENTRY_TIMES = ["09:35", "10:00", "11:00", "11:45", "13:00", "14:30"]
EXIT_TIME = "15:50"


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def quote_at(path, target, field):
    """Return path[field] at bar t==target, else the nearest bar by clock distance."""
    exact = [b for b in path if b["t"] == target]
    if exact:
        return exact[0][field]
    tgt = _to_min(target)
    best = min(path, key=lambda b: abs(_to_min(b["t"]) - tgt))
    return best[field]


def stats(rets):
    n = len(rets)
    if n == 0:
        return None
    s = sorted(rets)
    mean = sum(rets) / n
    if n % 2:
        median = s[n // 2]
    else:
        median = (s[n // 2 - 1] + s[n // 2]) / 2
    wins = sum(1 for r in rets if r > 0)
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "win_rate": wins / n,
        "best": max(rets),
        "worst": min(rets),
    }


def main():
    d = json.load(open(DATA))
    print(f"Loaded {len(d)} tickers from {DATA}\n")

    # Trend-day sanity check: how many closed up?
    up = sum(1 for v in d.values() if v["last"] > v["open"])
    print(f"Names closing UP (last>open): {up}/{len(d)}")
    itm = sum(1 for v in d.values() if v["last"] > v["atm_strike"])
    print(f"Names closing ITM (last>atm_strike): {itm}/{len(d)}\n")

    results = {}
    for et in ENTRY_TIMES:
        rets = []
        skipped = []
        zero_exits = 0
        for tk, v in d.items():
            path = v.get("option_path") or []
            if not path:
                continue
            entry_ask = quote_at(path, et, "ask")
            exit_bid = quote_at(path, EXIT_TIME, "bid")
            # RULE 3: entry_ask must be > 0 to trade.
            if entry_ask is None or entry_ask <= 0:
                skipped.append(tk)
                continue
            ret = (exit_bid - entry_ask) / entry_ask  # RULE 1: ask-in / bid-out
            # RULE 2: do NOT drop zero/near-zero exit bids; they are real -100%-ish losses.
            if exit_bid <= 0:
                zero_exits += 1
            rets.append(ret)
        results[et] = (stats(rets), skipped, zero_exits, rets)

    # Report
    hdr = f"{'entry':>6} {'n':>3} {'mean%':>8} {'median%':>8} {'win%':>6} {'best%':>9} {'worst%':>8} {'zeroExit':>8} {'skip(ask=0)':>11}"
    print(hdr)
    print("-" * len(hdr))
    for et in ENTRY_TIMES:
        st, skipped, ze, _ = results[et]
        if st is None:
            print(f"{et:>6}  (no trades)")
            continue
        print(f"{et:>6} {st['n']:>3} {st['mean']*100:>8.1f} {st['median']*100:>8.1f} "
              f"{st['win_rate']*100:>6.1f} {st['best']*100:>9.1f} {st['worst']*100:>8.1f} "
              f"{ze:>8} {len(skipped):>11}")

    print("\nPer-entry skipped (entry_ask<=0):")
    for et in ENTRY_TIMES:
        _, skipped, _, _ = results[et]
        print(f"  {et}: {skipped}")

    # JSON dump of exact numbers for the structured report
    print("\n=== MACHINE ===")
    out = {}
    for et in ENTRY_TIMES:
        st, skipped, ze, rets = results[et]
        out[et] = {
            "n": st["n"], "mean_pct": round(st["mean"]*100, 2),
            "median_pct": round(st["median"]*100, 2),
            "win_rate_pct": round(st["win_rate"]*100, 2),
            "best_pct": round(st["best"]*100, 2),
            "worst_pct": round(st["worst"]*100, 2),
            "zero_exits": ze, "skipped_ask0": len(skipped),
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
