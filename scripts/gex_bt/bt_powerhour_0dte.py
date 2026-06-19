"""
Backtest: late-day 0DTE ATM-call entry, power-hour exit.
Strategy family: ENTRY at {14:00, 14:30, 15:00} ask, EXIT at {15:50, 15:55} bid.
One 0DTE ATM call per scan ticker (30 names). Trend day: ALL 30 closed up.

HARD RULES:
 - ask-in / bid-out always.
 - SURVIVORSHIP: worthless/near-zero exit bid is a REAL loss; COUNT it (~-100%), never drop.
 - entry_ask must be > 0 to trade.
 - Report n, mean, median, win-rate, best, worst per variant.
Stdlib only.
"""
import json
import math

DATA = r"C:/Dev/GammaPulse/data/intraday_today_20260618.json"


def to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def nearest_quote(path, target, field):
    """Return the quote field at bar t==target, else nearest bar by time."""
    tgt = to_min(target)
    best = None
    best_d = None
    for q in path:
        d = abs(to_min(q["t"]) - tgt)
        if best_d is None or d < best_d:
            best_d = d
            best = q
    if best is None:
        return None, None
    return best.get(field), best.get("t")


def pct_stats(vals):
    n = len(vals)
    if n == 0:
        return dict(n=0, mean=None, median=None, win=None, best=None, worst=None)
    s = sorted(vals)
    mean = sum(vals) / n
    if n % 2:
        median = s[n // 2]
    else:
        median = (s[n // 2 - 1] + s[n // 2]) / 2
    wins = sum(1 for v in vals if v > 0)
    return dict(
        n=n,
        mean=mean * 100,
        median=median * 100,
        win=wins / n * 100,
        best=max(vals) * 100,
        worst=min(vals) * 100,
    )


def main():
    with open(DATA) as f:
        data = json.load(f)

    entries = ["14:00", "14:30", "15:00"]
    exits = ["15:50", "15:55"]

    results = {}  # (entry, exit) -> list of returns
    detail = {}   # (entry, exit) -> list of (ticker, entry_ask, exit_bid, ret)

    for entT in entries:
        for exT in exits:
            key = (entT, exT)
            results[key] = []
            detail[key] = []

    skipped = []  # (ticker, reason)
    n_tickers = 0
    n_up = 0

    for tk, rec in data.items():
        n_tickers += 1
        # confirm trend-day framing: closed up?
        if rec.get("last") is not None and rec.get("open") is not None and rec["last"] > rec["open"]:
            n_up += 1
        path = rec.get("option_path") or []
        if not path:
            for k in results:
                skipped.append((tk, "no_option_path"))
            continue
        for entT in entries:
            entry_ask, ent_used = nearest_quote(path, entT, "ask")
            for exT in exits:
                key = (entT, exT)
                if entry_ask is None or entry_ask <= 0:
                    # rule 3: entry_ask must be > 0 to trade -> no trade
                    skipped.append((tk, f"entry_ask<=0@{entT}"))
                    continue
                exit_bid, ex_used = nearest_quote(path, exT, "bid")
                if exit_bid is None:
                    exit_bid = 0.0  # treat missing exit as worthless (survivorship)
                # SURVIVORSHIP: near-zero / zero bid is a real loss, counted.
                ret = (exit_bid - entry_ask) / entry_ask
                results[key].append(ret)
                detail[key].append((tk, entry_ask, exit_bid, ret))

    print(f"tickers={n_tickers}  closed_up={n_up}/{n_tickers}")
    print("=" * 92)
    hdr = f"{'entry':>6} {'exit':>6} {'n':>4} {'mean%':>9} {'median%':>9} {'win%':>7} {'best%':>9} {'worst%':>9}"
    print(hdr)
    print("-" * 92)
    summary = {}
    for entT in entries:
        for exT in exits:
            key = (entT, exT)
            st = pct_stats(results[key])
            summary[key] = st
            if st["n"] == 0:
                print(f"{entT:>6} {exT:>6} {0:>4}  (no trades)")
                continue
            print(
                f"{entT:>6} {exT:>6} {st['n']:>4} {st['mean']:>9.2f} {st['median']:>9.2f} "
                f"{st['win']:>7.2f} {st['best']:>9.2f} {st['worst']:>9.2f}"
            )
    print("=" * 92)

    # Count zero/near-zero exit bids (survivorship audit) for one representative variant
    print("\nSurvivorship audit (exit bid <= 0.02 counted as ~total loss):")
    for entT in entries:
        for exT in exits:
            key = (entT, exT)
            zeros = sum(1 for (_, _, eb, _) in detail[key] if eb <= 0.02)
            print(f"  {entT}->{exT}: {zeros}/{len(detail[key])} names exited at <=0.02 bid")

    # Show worst/best names for the 15:00->15:55 variant (most power-hour-concentrated)
    key = ("15:00", "15:55")
    print(f"\nDetail for {key[0]}->{key[1]} (sorted by return):")
    for tk, ea, eb, r in sorted(detail[key], key=lambda x: x[3]):
        print(f"  {tk:>6}  ask={ea:>6.2f} bid={eb:>6.2f}  ret={r*100:>8.2f}%")

    if skipped:
        print(f"\nSkipped (no-trade) records: {len(skipped)}")
        # dedupe reasons
        from collections import Counter
        c = Counter(r for _, r in skipped)
        for reason, cnt in c.items():
            print(f"  {reason}: {cnt}")


if __name__ == "__main__":
    main()
