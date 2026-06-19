"""Falsification: the 0DTE gap-and-go call across regimes (TREND 6/18 vs RED 6/05).

For the 7 semis names common to both days: does the scan (up >=5% from open at
11:45) fire, and what does the 0DTE ATM call do (buy 11:45 ask -> sell 15:50 bid,
survivorship-correct)? Answers whether the strategy survives a non-gift tape.

Run: .venv\\Scripts\\python.exe scripts/gex_bt/regime_compare.py
"""
import json

DAYS = [("TREND 6/18", "data/intraday_today_20260618.json"),
        ("RED   6/05", "data/intraday_20260605.json")]
NAMES = ["WOLF", "SMCI", "CRDO", "ALAB", "BE", "GLW", "TSM"]


def at(path_pts, t, key):
    """value at time t (HH:MM) from a [{t,...}] list, nearest <= t."""
    best = None
    for p in path_pts:
        if p["t"] <= t and p.get(key) is not None:
            best = p[key]
    return best


for label, path in DAYS:
    try:
        d = json.load(open(path))
    except FileNotFoundError:
        print(f"{label}: file missing"); continue
    scanned, all_rows = [], []
    for n in NAMES:
        rec = d.get(n)
        if not rec:
            continue
        op = rec["open"]
        bars = rec["underlying_bars"]
        opath = rec["option_path"]
        u1145 = at(bars, "11:45", "c")
        up = (u1145 - op) / op * 100 if (u1145 and op) else None
        ask = at(opath, "11:45", "ask")
        bid = at(opath, "15:50", "bid")
        if ask is None or bid is None or ask <= 0:
            continue
        ret = (bid - ask) / ask * 100
        worthless = bid <= 0.01
        # DYNAMIC entry: enter when the name FIRST crosses +5% from open
        # (how the live scan actually fires), buy the call then, exit 15:50.
        cross_t = None
        for b in bars:
            if b.get("c") is not None and op and (b["c"] - op) / op >= 0.05:
                cross_t = b["t"]; break
        dyn_ask = at(opath, cross_t, "ask") if cross_t else None
        dyn_ret = (bid - dyn_ask) / dyn_ask * 100 if (dyn_ask and dyn_ask > 0) else None
        row = {"n": n, "up": up, "ret": ret, "worthless": worthless,
               "scanned": (up is not None and up >= 5),
               "cross_t": cross_t, "dyn_ret": dyn_ret}
        all_rows.append(row)
        if row["scanned"]:
            scanned.append(row)

    def summ(rows):
        if not rows:
            return "n=0"
        rets = sorted(r["ret"] for r in rows)
        n = len(rets); mean = sum(rets)/n; med = rets[n//2]
        win = sum(1 for r in rets if r > 0)/n*100
        wl = sum(1 for r in rows if r["worthless"])/n*100
        return f"n={n}  mean={mean:+.0f}%  median={med:+.0f}%  win={win:.0f}%  worthless={wl:.0f}%"

    crossed = [r for r in all_rows if r["dyn_ret"] is not None]

    def summ_dyn(rows):
        if not rows:
            return "n=0"
        rets = sorted(r["dyn_ret"] for r in rows)
        n = len(rets); mean = sum(rets)/n; med = rets[n//2]
        win = sum(1 for x in rets if x > 0)/n*100
        return f"n={n}  mean={mean:+.0f}%  median={med:+.0f}%  win={win:.0f}%"

    print(f"\n=== {label} ===")
    print(f"  DYNAMIC scan (enter when FIRST crossing +5% from open intraday):")
    print(f"    fired on {len(crossed)}/{len(all_rows)} names -> {summ_dyn(crossed)}")
    print(f"  fixed-11:45 scan fired on {len(scanned)}/{len(all_rows)} -> {summ(scanned)}")
    for r in all_rows:
        flag = ("X@" + r["cross_t"]) if r["cross_t"] else "  --  "
        dyn = f"{r['dyn_ret']:+6.0f}%" if r["dyn_ret"] is not None else "   --"
        print(f"    cross {flag:>8}  {r['n']:5} up@1145={r['up']:+5.1f}%  dyn_call={dyn}  hold1145={r['ret']:+6.0f}%  {'WORTHLESS' if r['worthless'] else ''}")
