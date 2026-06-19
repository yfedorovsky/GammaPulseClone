"""
Opening-Range Breakout (ORB) backtest for 0DTE ATM calls on cached scan-name data.

Data: data/intraday_today_20260618.json
  { TICKER: { in_universe, open, last, atm_strike, expiration,
              underlying_bars:[{t,o,h,l,c,v,vwap}],   # 09:30..15:55 5-min
              option_path:[{t,bid,ask}] } }           # 09:35..15:55 5-min

One 0DTE ATM call per ticker.
ENTRY  = first 5-min CLOSE that exceeds the HIGH of the opening range.
         Variant A: 15-min OR = first 3 session bars (09:35,09:40,09:45)
         Variant B: 30-min OR = first 6 session bars (09:35..10:00)
EXIT   = 15:50.
Return = (exit_bid - entry_ask) / entry_ask.

HARD RULES enforced:
  - ask-in / bid-out always.
  - SURVIVORSHIP: worthless / near-zero exit bid is a REAL loss; counted, never dropped.
  - entry_ask must be > 0 to trade.
  - report n, mean, median, win-rate, best, worst per variant.

Session bars = bars with t >= '09:35' (matches the option_path window).
The leading 09:30 cash-open bar is excluded from the OR so the breakout
reference and the tradeable option quotes share the same clock.
stdlib only.
"""
import json
import math

DATA = "data/intraday_today_20260618.json"
SESSION_START = "09:35"
EXIT_T = "15:50"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return float("nan")
    m = n // 2
    if n % 2:
        return s[m]
    return (s[m - 1] + s[m]) / 2.0


def opt_at(option_path, t):
    """Return the option quote dict at time t, or nearest by time if missing."""
    exact = [o for o in option_path if o["t"] == t]
    if exact:
        return exact[0]
    # nearest by absolute minute difference
    def mins(s):
        h, mm = s.split(":")
        return int(h) * 60 + int(mm)
    target = mins(t)
    return min(option_path, key=lambda o: abs(mins(o["t"]) - target))


def run_variant(data, or_bars, label):
    """or_bars = number of leading session bars forming the opening range."""
    triggered = []   # list of dict per trade
    no_trigger = 0
    no_universe = 0
    skipped_zero_ask = 0
    total = 0

    for tk, v in data.items():
        total += 1
        bars = [b for b in v["underlying_bars"] if b["t"] >= SESSION_START]
        op = v["option_path"]
        if len(bars) < or_bars + 1:
            no_trigger += 1
            continue

        or_window = bars[:or_bars]
        or_high = max(b["h"] for b in or_window)

        # first session bar AFTER the OR whose close exceeds OR high
        entry_bar = None
        for b in bars[or_bars:]:
            if b["c"] > or_high:
                entry_bar = b
                break

        if entry_bar is None:
            no_trigger += 1
            continue

        entry_t = entry_bar["t"]
        # don't allow entry at/after exit time
        if entry_t >= EXIT_T:
            no_trigger += 1
            continue

        eq = opt_at(op, entry_t)
        entry_ask = eq["ask"]
        if not (entry_ask and entry_ask > 0):
            skipped_zero_ask += 1
            continue

        xq = opt_at(op, EXIT_T)
        exit_bid = xq["bid"]  # may be 0 -> ~ -100% loss, COUNTED
        ret = (exit_bid - entry_ask) / entry_ask

        triggered.append({
            "ticker": tk,
            "in_universe": bool(v.get("in_universe")),
            "entry_t": entry_t,
            "entry_ask": entry_ask,
            "exit_bid": exit_bid,
            "ret_pct": ret * 100.0,
        })

    rets = [r["ret_pct"] for r in triggered]
    n = len(rets)
    out = {
        "label": label,
        "or_bars": or_bars,
        "total_names": total,
        "n": n,
        "no_trigger": no_trigger,
        "skipped_zero_ask": skipped_zero_ask,
        "trades": triggered,
    }
    if n:
        wins = sum(1 for x in rets if x > 0)
        out.update({
            "mean_pct": sum(rets) / n,
            "median_pct": median(rets),
            "win_rate_pct": 100.0 * wins / n,
            "best_pct": max(rets),
            "worst_pct": min(rets),
            "trigger_rate_pct": 100.0 * n / total,
            "zero_exit_count": sum(1 for r in triggered if r["exit_bid"] == 0),
        })
    return out


def fmt(out):
    print(f"\n=== {out['label']} (OR = first {out['or_bars']} session bars) ===")
    print(f"  names total           : {out['total_names']}")
    print(f"  TRIGGERED (n trades)  : {out['n']}  "
          f"(trigger rate {out.get('trigger_rate_pct', float('nan')):.1f}%)")
    print(f"  no-trigger (no break) : {out['no_trigger']}")
    print(f"  skipped (entry_ask<=0): {out['skipped_zero_ask']}")
    if out["n"]:
        print(f"  mean return  : {out['mean_pct']:+.2f}%")
        print(f"  median return: {out['median_pct']:+.2f}%")
        print(f"  win rate     : {out['win_rate_pct']:.1f}%  ({sum(1 for t in out['trades'] if t['ret_pct']>0)}/{out['n']})")
        print(f"  best         : {out['best_pct']:+.2f}%")
        print(f"  worst        : {out['worst_pct']:+.2f}%")
        print(f"  zero-bid exits (worthless, counted as ~-100%): {out['zero_exit_count']}")
        print("  --- per-trade ---")
        for t in sorted(out["trades"], key=lambda x: -x["ret_pct"]):
            uni = "U" if t["in_universe"] else " "
            print(f"    [{uni}] {t['ticker']:<5} entry {t['entry_t']} ask {t['entry_ask']:.2f} "
                  f"-> exit bid {t['exit_bid']:.2f}  {t['ret_pct']:+8.2f}%")


def main():
    data = json.load(open(DATA))
    print(f"Loaded {len(data)} tickers from {DATA}")
    print(f"in_universe names: {sum(1 for v in data.values() if v.get('in_universe'))}")

    results = []
    for or_bars, lab in [(3, "ORB 15-min"), (6, "ORB 30-min")]:
        out = run_variant(data, or_bars, lab)
        fmt(out)
        results.append(out)
    return results


if __name__ == "__main__":
    main()
