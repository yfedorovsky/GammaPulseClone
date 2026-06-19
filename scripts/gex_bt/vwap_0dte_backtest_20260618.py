"""
0DTE ATM-call VWAP-entry backtest on cached scan-name data (2026-06-18).

Mandate:
  ENTRY = session-VWAP-based (3 variants), EXIT = 15:50 (bid).
  ask-in / bid-out always. Worthless/near-zero exit bid = REAL loss, counted.
  entry_ask must be > 0 to trade.
  Session VWAP computed cumulatively from underlying_bars:
      vwap_t = cumsum( ((h+l+c)/3) * v ) / cumsum(v )

Variants:
  (a) FIRST 5-min CLOSE that crosses ABOVE session VWAP AFTER 10:00
      (was below at prior bar, closes above now). Entry at that bar's time.
  (b) GAP-AND-GO: at 10:00, if close already >= session VWAP -> buy at 10:00.
  (c) RECLAIM: after price has dipped BELOW VWAP (at some bar >= 10:00),
      first bar that closes back ABOVE VWAP -> buy. (i.e. requires a
      below-VWAP bar first, then a cross-up.)

Stdlib only (json, math).
"""
import json
import math

DATA = r"C:\Dev\GammaPulse\data\intraday_today_20260618.json"
EXIT_T = "15:50"
ENTRY_GATE = "10:00"  # variants act at/after this time


def t_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


GATE_MIN = t_to_min(ENTRY_GATE)
EXIT_MIN = t_to_min(EXIT_T)


def session_vwap_series(bars):
    """Return list of (t, close, vwap_cumulative) using cumsum typical*vol."""
    cum_pv = 0.0
    cum_v = 0.0
    out = []
    for b in bars:
        typ = (b["h"] + b["l"] + b["c"]) / 3.0
        v = b["v"]
        cum_pv += typ * v
        cum_v += v
        vwap = cum_pv / cum_v if cum_v > 0 else typ
        out.append((b["t"], b["c"], vwap))
    return out


def opt_at(option_path, target_t, side):
    """Return option side ('ask' or 'bid') at target_t; nearest by time if missing."""
    best = None
    best_d = None
    tgt = t_to_min(target_t)
    exact = None
    for o in option_path:
        if o["t"] == target_t:
            exact = o
            break
        d = abs(t_to_min(o["t"]) - tgt)
        if best_d is None or d < best_d:
            best_d = d
            best = o
    o = exact if exact is not None else best
    return o[side] if o is not None else None


def find_entry_a(vw):
    """First bar AFTER 10:00 that crosses from below to >= VWAP (prev close < prev vwap)."""
    prev_below = None
    for (t, c, v) in vw:
        m = t_to_min(t)
        below = c < v
        if m > GATE_MIN:
            if prev_below is True and not below:  # crossed up this bar
                return t
        prev_below = below
    return None


def find_entry_b(vw):
    """Gap-and-go: at the 10:00 bar, if close >= vwap -> buy at 10:00."""
    for (t, c, v) in vw:
        if t == ENTRY_GATE:
            return ENTRY_GATE if c >= v else None
    return None


def find_entry_c(vw):
    """Reclaim: require a bar >=10:00 that is BELOW vwap first, then first cross back up."""
    seen_below = False
    prev = None
    for (t, c, v) in vw:
        m = t_to_min(t)
        if m < GATE_MIN:
            prev = (c, v)
            continue
        below = c < v
        if m >= GATE_MIN:
            if seen_below and prev is not None and (prev[0] < prev[1]) and not below:
                return t
            if below:
                seen_below = True
        prev = (c, v)
    return None


def never_crossed_from_below(vw):
    """True if price was at/above VWAP for every bar from 10:00 onward
    (i.e. no below->above transition possible -> variant (a) misses it)."""
    any_below = False
    for (t, c, v) in vw:
        if t_to_min(t) >= GATE_MIN:
            if c < v:
                any_below = True
    return not any_below


def stats(rets):
    if not rets:
        return dict(n=0, mean=None, median=None, win=None, best=None, worst=None)
    n = len(rets)
    s = sorted(rets)
    mean = sum(rets) / n
    if n % 2:
        median = s[n // 2]
    else:
        median = (s[n // 2 - 1] + s[n // 2]) / 2
    win = sum(1 for r in rets if r > 0) / n * 100
    return dict(n=n, mean=mean * 100, median=median * 100,
                win=win, best=max(rets) * 100, worst=min(rets) * 100)


def run():
    d = json.load(open(DATA))
    variants = {"a": find_entry_a, "b": find_entry_b, "c": find_entry_c}
    results = {k: [] for k in variants}
    trade_detail = {k: [] for k in variants}

    never_cross_names = []
    never_cross_rets_a_would_be = []  # what gap-and-go (variant b) earned on these

    for tk, t in d.items():
        vw = session_vwap_series(t["underlying_bars"])
        op = t["option_path"]
        spot_ret = (t["last"] - t["open"]) / t["open"] * 100

        if never_crossed_from_below(vw):
            never_cross_names.append((tk, spot_ret))

        for vkey, fn in variants.items():
            ent_t = fn(vw)
            if ent_t is None:
                continue
            entry_ask = opt_at(op, ent_t, "ask")
            if entry_ask is None or entry_ask <= 0:
                continue  # cannot trade (rule 3)
            exit_bid = opt_at(op, EXIT_T, "bid")
            if exit_bid is None:
                exit_bid = 0.0
            ret = (exit_bid - entry_ask) / entry_ask
            results[vkey].append(ret)
            trade_detail[vkey].append((tk, ent_t, entry_ask, exit_bid, ret * 100, spot_ret))

    # Report
    print("=" * 78)
    print("0DTE ATM-CALL VWAP-ENTRY BACKTEST  --  2026-06-18 (trend day, all 30 names UP)")
    print("=" * 78)
    print(f"Total scan names: {len(d)}   exit=15:50 bid, ask-in/bid-out, zero-bid counted")
    print()

    names = {"a": "(a) FIRST cross-above-VWAP after 10:00",
             "b": "(b) GAP-AND-GO (>=VWAP at 10:00)",
             "c": "(c) RECLAIM (dip below then cross back up)"}
    for vkey in ["a", "b", "c"]:
        st = stats(results[vkey])
        print(f"--- VARIANT {names[vkey]} ---")
        if st["n"] == 0:
            print("  no trades")
        else:
            print(f"  n={st['n']:2d}  mean={st['mean']:+7.1f}%  median={st['median']:+7.1f}%  "
                  f"win={st['win']:5.1f}%  best={st['best']:+7.1f}%  worst={st['worst']:+7.1f}%")
        print()

    # never-crossed analysis
    print("=" * 78)
    print("GAP-AND-GO NAMES THAT VARIANT (a) STRUCTURALLY MISSES")
    print("(never below VWAP from 10:00 on -> no below->above cross to trigger (a))")
    print("=" * 78)
    print(f"count = {len(never_cross_names)} of {len(d)}")
    # were these winners (spot)? all closed up anyway, but rank by spot move
    ncs = sorted(never_cross_names, key=lambda x: -x[1])
    for tk, sr in ncs:
        print(f"  {tk:6} spot {sr:+6.2f}%")
    if ncs:
        msr = sum(x[1] for x in ncs) / len(ncs)
        traded_a = set(x[0] for x in trade_detail["a"])
        all_spot = {tk: (t["last"] - t["open"]) / t["open"] * 100 for tk, t in d.items()}
        crossed = [all_spot[tk] for tk in all_spot if tk not in dict(ncs)]
        mcr = sum(crossed) / len(crossed) if crossed else 0
        print()
        print(f"  mean SPOT move of NEVER-CROSSED (gap-and-go) names: {msr:+.2f}%")
        print(f"  mean SPOT move of CROSSED (variant-a-eligible) names: {mcr:+.2f}%")
        # option P/L of these names under gap-and-go (variant b)
        b_by_name = {x[0]: x[4] for x in trade_detail["b"]}
        nc_b = [b_by_name[tk] for tk, _ in ncs if tk in b_by_name]
        if nc_b:
            print(f"  variant-(b) option return on these never-crossed names: "
                  f"mean={sum(nc_b)/len(nc_b):+.1f}%  "
                  f"best={max(nc_b):+.1f}%  worst={min(nc_b):+.1f}%  n={len(nc_b)}")

    # per-trade dump for variant a and b
    for vkey in ["a", "b", "c"]:
        print()
        print(f"--- per-trade detail variant {vkey} (ticker, entry_t, ask, exit_bid, opt_ret%, spot%) ---")
        for row in sorted(trade_detail[vkey], key=lambda r: -r[4]):
            print(f"  {row[0]:6} {row[1]:>5}  ask={row[2]:.2f}  exit_bid={row[3]:.2f}  "
                  f"opt={row[4]:+7.1f}%  spot={row[5]:+5.2f}%")

    return results, trade_detail, never_cross_names


if __name__ == "__main__":
    run()
