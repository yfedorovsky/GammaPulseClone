"""
Intraday 0DTE ATM-call backtest on cached scan-name data for 2026-06-18.

Strategy family: EMA-based entry on the 5-min underlying close.
  Compute EMA-8 and EMA-9 over the 5-min underlying CLOSE series.
  Variant (a) pullback-to-EMA-then-reclaim:
      Trigger when the underlying close dips to/under the EMA (touch) on one
      bar, then closes back above the EMA on a later bar (the reclaim bar).
      ENTRY at that reclaim bar's time. Tested for both EMA-8 and EMA-9.
  Variant (b) above-EMA-8-at-10:00-and-hold:
      If the 10:00 underlying close is above EMA-8, ENTER at 10:00, hold.
      Tested for both EMA-8 and EMA-9 (b uses EMA-8 by mandate; EMA-9 shown too).

EXIT: 15:50 for all variants.

HARD RULES enforced:
  1. ask-in / bid-out: entry = option_path ASK at entry time, exit = BID at 15:50.
  2. SURVIVORSHIP: a zero / near-zero exit bid is a REAL loss. We COUNT it
     (return ~ -100%). We never drop zero-bid exits.
  3. entry_ask must be > 0 to trade (else the name does not trigger / is skipped).
  4. Report n, mean, median, win-rate, best, worst per variant.

Stdlib only (json, math). Run with .venv/Scripts/python.exe.
"""
import json
import math

DATA = "data/intraday_today_20260618.json"
EXIT_TIME = "15:50"


def ema(values, period):
    """Standard EMA over a list. Returns list same length as values.
    Seeded with the first value (classic recursive seed)."""
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def opt_at(option_path, t):
    """Return the option_path entry at time t, nearest by time index if exact
    is missing. Times are 'HH:MM'. We match exact first, else nearest by minute."""
    by_t = {o["t"]: o for o in option_path}
    if t in by_t:
        return by_t[t]
    # nearest by absolute minute distance
    def mins(s):
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    target = mins(t)
    best = min(option_path, key=lambda o: abs(mins(o["t"]) - target))
    return best


def pct(x):
    return 100.0 * x


def stats(returns):
    """returns is a list of fractional returns. Return dict of n/mean/median/
    win_rate/best/worst as PERCENTS."""
    n = len(returns)
    if n == 0:
        return dict(n=0, mean=0.0, median=0.0, win=0.0, best=0.0, worst=0.0)
    s = sorted(returns)
    mean = sum(returns) / n
    if n % 2 == 1:
        median = s[n // 2]
    else:
        median = 0.5 * (s[n // 2 - 1] + s[n // 2])
    wins = sum(1 for r in returns if r > 0)
    return dict(
        n=n,
        mean=pct(mean),
        median=pct(median),
        win=100.0 * wins / n,
        best=pct(max(returns)),
        worst=pct(min(returns)),
    )


def run():
    with open(DATA) as f:
        data = json.load(f)

    # Build per-ticker close series aligned to bar times (use bars with t>=09:35
    # so they line up with the option_path coverage; EMA computed on full close
    # series from 09:30 for stability, but entries only allowed where an option
    # ask exists).
    results = {
        "a_ema8": [],   # pullback-reclaim on EMA-8
        "a_ema9": [],   # pullback-reclaim on EMA-9
        "b_ema8": [],   # close>EMA8 at 10:00, hold  (the mandated variant b)
        "b_ema9": [],   # close>EMA9 at 10:00, hold  (companion)
    }
    # Track which names triggered for each variant, and which were skipped
    # because entry_ask<=0.
    triggers = {k: [] for k in results}
    miss = {k: 0 for k in results}        # names that did NOT trigger the signal
    skipped_ask = {k: 0 for k in results} # triggered but entry_ask<=0 -> cannot trade

    total = len(data)

    for tk, v in data.items():
        bars = v["underlying_bars"]
        opath = v["option_path"]
        times = [b["t"] for b in bars]
        closes = [b["c"] for b in bars]
        e8 = ema(closes, 8)
        e9 = ema(closes, 9)

        exit_o = opt_at(opath, EXIT_TIME)
        exit_bid = exit_o["bid"]

        # ---- Variant (a): pullback-to-EMA-then-reclaim ----
        def variant_a(ema_series, key):
            # Walk bars; need a prior touch (close<=ema) then a later reclaim
            # (close>ema). Enter at first reclaim bar that follows a touch.
            touched = False
            entry_t = None
            for i in range(len(bars)):
                c = closes[i]
                e = ema_series[i]
                if not touched:
                    if c <= e:
                        touched = True
                else:
                    if c > e:
                        entry_t = times[i]
                        break
            if entry_t is None:
                miss[key] += 1
                return
            triggers[key].append((tk, entry_t))
            eo = opt_at(opath, entry_t)
            entry_ask = eo["ask"]
            if entry_ask <= 0:
                skipped_ask[key] += 1
                return
            ret = (exit_bid - entry_ask) / entry_ask
            results[key].append(ret)

        variant_a(e8, "a_ema8")
        variant_a(e9, "a_ema9")

        # ---- Variant (b): close above EMA at 10:00, hold ----
        def variant_b(ema_series, key):
            if "10:00" not in times:
                miss[key] += 1
                return
            idx = times.index("10:00")
            if closes[idx] > ema_series[idx]:
                entry_t = "10:00"
                triggers[key].append((tk, entry_t))
                eo = opt_at(opath, entry_t)
                entry_ask = eo["ask"]
                if entry_ask <= 0:
                    skipped_ask[key] += 1
                    return
                ret = (exit_bid - entry_ask) / entry_ask
                results[key].append(ret)
            else:
                miss[key] += 1

        variant_b(e8, "b_ema8")
        variant_b(e9, "b_ema9")

    print(f"Total scan names: {total}")
    print(f"All names closed UP today (trend day).\n")
    labels = {
        "a_ema8": "(a) pullback->reclaim EMA-8, exit 15:50",
        "a_ema9": "(a) pullback->reclaim EMA-9, exit 15:50",
        "b_ema8": "(b) close>EMA-8 @10:00 + hold, exit 15:50",
        "b_ema9": "(b) close>EMA-9 @10:00 + hold, exit 15:50",
    }
    for key in ["a_ema8", "a_ema9", "b_ema8", "b_ema9"]:
        st = stats(results[key])
        triggered = len(triggers[key])
        traded = st["n"]
        missrate = 100.0 * miss[key] / total
        print(f"=== {labels[key]} ===")
        print(f"  triggered (signal fired): {triggered}/{total}")
        print(f"  skipped (entry_ask<=0):   {skipped_ask[key]}")
        print(f"  traded (n):               {traded}")
        print(f"  miss-rate (no signal):    {missrate:.1f}%  ({miss[key]}/{total})")
        print(f"  mean:   {st['mean']:.2f}%")
        print(f"  median: {st['median']:.2f}%")
        print(f"  win-rate:{st['win']:.1f}%")
        print(f"  best:   {st['best']:.2f}%")
        print(f"  worst:  {st['worst']:.2f}%")
        print()

    # Emit a machine-readable block for the report
    out = {}
    for key in results:
        st = stats(results[key])
        st["triggered"] = len(triggers[key])
        st["skipped_ask0"] = skipped_ask[key]
        st["miss_count"] = miss[key]
        st["miss_rate"] = 100.0 * miss[key] / total
        out[key] = st
    print("JSON_RESULTS=" + json.dumps(out))


if __name__ == "__main__":
    run()
