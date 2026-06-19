"""
Exit-time-curve backtest for 0DTE ATM-call scan names, trade date 2026-06-18.

MANDATE
-------
Fix ENTRY = 10:00 ask for ALL scan names. EXIT at each of
12:00, 13:00, 14:00, 15:00, 15:30, 15:50, 15:55.
Produce the exit-time curve: when is the best exit, and is the final
15 min a giveback (theta / close-gamma) or a melt-up?

HARD RULES
----------
1. ask-in / bid-out always.
2. SURVIVORSHIP: a worthless/near-zero exit bid is a REAL loss (often ~-100%).
   COUNT it, never drop it.
3. entry_ask must be > 0 to trade.
4. report n, mean, median, win-rate, best, worst per variant (per exit time).
5. stdlib only (json, math). No polars.

Each ticker = one 0DTE ATM call. Entry/exit prices come from option_path:
  entry = ask at t == '10:00' (nearest earlier-or-any if exact missing)
  exit  = bid at t == EXIT_TIME (nearest if missing)
  return = (exit_bid - entry_ask) / entry_ask

NOTE: all 30 names closed UP today (trend day). Findings describe
"what exit shape worked on a trend day", not a generalizable edge.
"""
import json
import math
import os

DATA = os.path.join(os.path.dirname(__file__), "..", "..",
                    "data", "intraday_today_20260618.json")
DATA = os.path.abspath(DATA)

ENTRY_TIME = "10:00"
EXIT_TIMES = ["12:00", "13:00", "14:00", "15:00", "15:30", "15:50", "15:55"]


def _hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def nearest_row(path, target, field):
    """Return (row, used_t) for the row whose 't' is closest to target.
    Exact match preferred. field is 'ask' or 'bid' (used only to ensure
    the chosen row actually carries that field; all rows do here)."""
    if not path:
        return None, None
    tgt = _hhmm_to_min(target)
    # exact first
    for r in path:
        if r.get("t") == target and r.get(field) is not None:
            return r, r.get("t")
    # nearest by absolute time distance, tie-break to earlier bar
    best = None
    best_key = None
    for r in path:
        if r.get("t") is None or r.get(field) is None:
            continue
        d = abs(_hhmm_to_min(r["t"]) - tgt)
        key = (d, _hhmm_to_min(r["t"]))
        if best_key is None or key < best_key:
            best_key = key
            best = r
    return best, (best["t"] if best else None)


def median(xs):
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def summarize(rets):
    """rets: list of fractional returns (e.g. -1.0 .. +5.0)."""
    n = len(rets)
    if n == 0:
        return dict(n=0, mean=float("nan"), median=float("nan"),
                    win=float("nan"), best=float("nan"), worst=float("nan"))
    wins = sum(1 for r in rets if r > 0)
    return dict(
        n=n,
        mean=sum(rets) / n,
        median=median(rets),
        win=100.0 * wins / n,
        best=max(rets),
        worst=min(rets),
    )


def run(universe_filter=None, label=""):
    data = json.load(open(DATA))
    # per-exit-time accumulation
    rets_by_exit = {t: [] for t in EXIT_TIMES}
    trades = []  # detail rows for auditing
    skipped = []

    for tk, t in data.items():
        if universe_filter is not None and bool(t.get("in_universe")) != universe_filter:
            continue
        path = t.get("option_path") or []
        ent_row, ent_t = nearest_row(path, ENTRY_TIME, "ask")
        if ent_row is None:
            skipped.append((tk, "no entry row"))
            continue
        entry_ask = ent_row.get("ask")
        # RULE 3: entry_ask must be > 0 to trade
        if entry_ask is None or entry_ask <= 0:
            skipped.append((tk, f"entry_ask<=0 ({entry_ask})"))
            continue

        row = {"ticker": tk, "entry_ask": entry_ask, "entry_t": ent_t}
        for xt in EXIT_TIMES:
            ex_row, ex_t = nearest_row(path, xt, "bid")
            exit_bid = ex_row.get("bid") if ex_row else None
            if exit_bid is None:
                exit_bid = 0.0  # treat as worthless rather than dropping
            # RULE 2: near-zero / zero exit bid is a REAL loss, count it.
            ret = (exit_bid - entry_ask) / entry_ask
            rets_by_exit[xt].append(ret)
            row[xt] = ret
            row[xt + "_bid"] = exit_bid
        trades.append(row)

    return rets_by_exit, trades, skipped


def pct(x):
    return "n/a" if (x != x) else f"{100.0*x:+.1f}%"


def print_curve(rets_by_exit, header):
    print("=" * 78)
    print(header)
    print("=" * 78)
    print(f"{'exit':>6} | {'n':>3} | {'mean':>8} | {'median':>8} | "
          f"{'win%':>6} | {'best':>9} | {'worst':>8}")
    print("-" * 78)
    for xt in EXIT_TIMES:
        s = summarize(rets_by_exit[xt])
        print(f"{xt:>6} | {s['n']:>3} | {pct(s['mean']):>8} | "
              f"{pct(s['median']):>8} | {s['win']:>5.0f}% | "
              f"{pct(s['best']):>9} | {pct(s['worst']):>8}")
    print()


def main():
    print(f"DATA: {DATA}")
    print(f"ENTRY: {ENTRY_TIME} ask (ask-in)  |  EXIT: bid-out at each time\n")

    # ALL 30 scan names (mandate: "ALL names")
    all_rets, all_trades, all_skip = run(universe_filter=None,
                                         label="ALL 30 scan names")
    print_curve(all_rets, "VARIANT A — ALL 30 scan names (entry 10:00 ask)")
    print(f"  traded: {len(all_trades)}   skipped: {len(all_skip)} {all_skip}\n")

    # in_universe == True subset
    iu_rets, iu_trades, iu_skip = run(universe_filter=True,
                                      label="in_universe only")
    print_curve(iu_rets, "VARIANT B — in_universe == True subset")
    print(f"  traded: {len(iu_trades)}   skipped: {len(iu_skip)} {iu_skip}\n")

    # not-in-universe subset (for contrast)
    nu_rets, nu_trades, nu_skip = run(universe_filter=False,
                                      label="not in_universe")
    print_curve(nu_rets, "VARIANT C — in_universe == False subset")
    print(f"  traded: {len(nu_trades)}   skipped: {len(nu_skip)} {nu_skip}\n")

    # Giveback / melt-up check on the ALL set: compare 15:00 vs 15:55,
    # and 15:30 -> 15:55 leg.
    def mean_at(rb, t):
        s = summarize(rb[t])
        return s["mean"]

    print("FINAL-15-MIN SHAPE (ALL 30):")
    for a, b in [("15:00", "15:55"), ("15:30", "15:55"), ("15:50", "15:55"),
                 ("14:00", "15:55")]:
        da = mean_at(all_rets, a)
        db = mean_at(all_rets, b)
        delta = db - da
        tag = "MELT-UP" if delta > 0 else ("GIVEBACK" if delta < 0 else "flat")
        print(f"  mean {a}={pct(da)} -> {b}={pct(db)}  delta={pct(delta)}  [{tag}]")
    print()

    # find best exit by mean and by median on ALL set
    best_mean_t = max(EXIT_TIMES, key=lambda t: summarize(all_rets[t])["mean"])
    best_med_t = max(EXIT_TIMES, key=lambda t: summarize(all_rets[t])["median"])
    best_win_t = max(EXIT_TIMES, key=lambda t: summarize(all_rets[t])["win"])
    print(f"BEST EXIT (ALL 30): by mean={best_mean_t} "
          f"({pct(summarize(all_rets[best_mean_t])['mean'])}), "
          f"by median={best_med_t} "
          f"({pct(summarize(all_rets[best_med_t])['median'])}), "
          f"by win%={best_win_t} "
          f"({summarize(all_rets[best_win_t])['win']:.0f}%)")

    # dump a couple of audit rows: worst and best names at 15:55
    print("\nAUDIT — per-name return at 15:55 (entry 10:00 ask -> 15:55 bid):")
    rows = sorted(all_trades, key=lambda r: r["15:55"])
    for r in rows:
        print(f"  {r['ticker']:6s} entry@{r['entry_t']}={r['entry_ask']:.2f} "
              f"15:55bid={r['15:55_bid']:.2f}  ret={pct(r['15:55'])}")


if __name__ == "__main__":
    main()
