"""Which flow-alert property cut (if any) survives as a real signal?

For this week's flow_alerts, compute forward spot move (signed by sentiment)
and bucket by every filterable property (is_whale, is_insider, conviction,
notional, vol/OI, regime, stacked). A bucket is 'keepable' only if hit>55% AND
n>=100 (else it is small-sample noise — the trap that has fooled us all
session). Output = the empirical basis for the Telegram filter.

Read-only on snapshots.db. Run: .venv\\Scripts\\python.exe scripts/gex_bt/flow_survival.py
"""
import sqlite3
import time
import bisect
from collections import defaultdict

WK = time.time() - 7 * 86400
con = sqlite3.connect("file:snapshots.db?mode=ro", uri=True)

# spot history per ticker
sts, spx = defaultdict(list), defaultdict(list)
for tk, ts, sp in con.execute(
        "SELECT ticker, ts, spot FROM snapshots WHERE ts>? AND spot>0 ORDER BY ts", (WK,)):
    sts[tk].append(ts); spx[tk].append(sp)

fa = con.execute(
    "SELECT ts, ticker, sentiment, conviction, notional, vol_oi, is_whale, is_insider, regime "
    "FROM flow_alerts WHERE ts>?", (WK,)).fetchall()
con.close()


def fwd(tk, t, dt):
    arr = sts.get(tk)
    if not arr:
        return None
    i = bisect.bisect_right(arr, t) - 1
    if i < 0:
        return None
    s0 = spx[tk][i]
    j = bisect.bisect_left(arr, t + dt)
    if j >= len(arr):
        j = len(arr) - 1
    if abs(arr[j] - (t + dt)) > 1800:
        return None
    return (spx[tk][j] - s0) / s0


rows = []
for ts, tk, sent, conv, notion, voloi, isw, isi, reg in fa:
    d = -1 if (sent or "").upper().find("BEAR") >= 0 else 1
    r = fwd(tk, ts, 1800)
    if r is None:
        continue
    rows.append({"ret": d * r * 100, "conv": conv, "notion": notion or 0,
                 "voloi": voloi or 0, "isw": isw or 0, "isi": isi or 0,
                 "reg": (reg or "?")})
print(f"flow_alerts this week with forward data: {len(rows)}")


def show(label, sub):
    if not sub:
        print(f"  {label:34} n=0"); return
    n = len(sub); rets = [x["ret"] for x in sub]
    hit = sum(1 for x in rets if x > 0) / n * 100
    mean = sum(rets) / n
    flag = "  <-- KEEPABLE" if (hit > 55 and n >= 100) else ""
    print(f"  {label:34} n={n:5} hit={hit:4.0f}% mean={mean:+.3f}%{flag}")


print("\n=== baseline ===")
show("ALL flow_alerts", rows)
print("\n=== by flag ===")
show("is_whale=1", [r for r in rows if r["isw"]])
show("is_insider=1", [r for r in rows if r["isi"]])
show("whale AND insider", [r for r in rows if r["isw"] and r["isi"]])
print("\n=== by conviction ===")
for c in sorted(set(str(r["conv"]) for r in rows)):
    show(f"conviction={c}", [r for r in rows if str(r["conv"]) == c])
print("\n=== by notional ===")
for lo in (1e6, 3e6, 10e6, 25e6):
    show(f"notional >= ${lo/1e6:.0f}M", [r for r in rows if r["notion"] >= lo])
print("\n=== by vol/OI ===")
for lo in (5, 10, 20, 50):
    show(f"vol/OI >= {lo}x", [r for r in rows if r["voloi"] >= lo])
print("\n=== by regime ===")
for reg in sorted(set(r["reg"] for r in rows)):
    show(f"regime={reg}", [r for r in rows if r["reg"] == reg])
print("\n=== stacked best-guess (whale+insider+big+high vol/OI) ===")
show("whale & insider & >$3M & voOI>=10", [r for r in rows if r["isw"] and r["isi"] and r["notion"] >= 3e6 and r["voloi"] >= 10])
print("\nKEEPABLE = hit>55% AND n>=100. If none flagged -> no predictive subset; filter on")
print("magnitude-as-context + volume, not on a phantom signal.")
