"""Noise audit: did this week's SENT Telegram alerts have follow-through?

For each alert in logs/telegram_audit.jsonl with sent=True, measure the
UNDERLYING forward move (snapshots.db spot) over +30min and to EOD, SIGNED by
the alert's direction (flow_alerts.sentiment, nearest within 300s; default
BULL — the system is long-biased). A 'benefit' alert moves in-direction; noise
is ~50% hit-rate / ~0 mean = a coin flip the user shouldn't be pinged for.

Read-only on snapshots.db. Run: .venv\\Scripts\\python.exe scripts/gex_bt/alert_benefit_week.py
"""
import json
import sqlite3
import time
import bisect
from collections import defaultdict

WK = time.time() - 7 * 86400
SNAP = "snapshots.db"

# ---- spot history per ticker (sorted) ----
con = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
spot_ts = defaultdict(list)
spot_px = defaultdict(list)
for tk, ts, sp in con.execute(
        "SELECT ticker, ts, spot FROM snapshots WHERE ts>? AND spot>0 ORDER BY ts", (WK,)):
    spot_ts[tk].append(ts); spot_px[tk].append(sp)

# ---- direction per (ticker, ts) from flow_alerts ----
flow = defaultdict(list)  # ticker -> [(ts, sentiment)]
for tk, ts, sent in con.execute(
        "SELECT ticker, ts, sentiment FROM flow_alerts WHERE ts>?", (WK,)):
    flow[tk].append((ts, (sent or "").upper()))
for tk in flow:
    flow[tk].sort()
con.close()


def spot_at(tk, t):
    arr = spot_ts.get(tk)
    if not arr:
        return None
    i = bisect.bisect_right(arr, t) - 1
    if i < 0:
        i = 0
    if abs(arr[i] - t) > 1800:  # no spot within 30 min
        return None
    return spot_px[tk][i]


def direction(tk, t):
    rows = flow.get(tk)
    if not rows:
        return 1  # default bull
    best, bestdt = None, 1e9
    lo = bisect.bisect_left([r[0] for r in rows], t - 300)
    for ts, s in rows[lo:]:
        if ts > t + 300:
            break
        dt = abs(ts - t)
        if dt < bestdt:
            bestdt, best = dt, s
    if best and "BEAR" in best:
        return -1
    return 1  # BULL / NEUTRAL / unknown -> bull (long-biased system)


# ---- sent alerts ----
sent = []
with open("logs/telegram_audit.jsonl", encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        try:
            ts = float(e.get("ts", 0))
        except ValueError:
            continue
        if ts <= WK or str(e.get("sent", "")).lower() not in ("true", "1"):
            continue
        sent.append((ts, e.get("ticker", "?"), e.get("category", "?")))

by = defaultdict(list)  # category -> [(ret30, retEOD)]
for ts, tk, cat in sent:
    s0 = spot_at(tk, ts)
    if not s0:
        continue
    d = direction(tk, ts)
    s30 = spot_at(tk, ts + 1800)
    # EOD = last snapshot for that ticker on that calendar day
    arr = spot_ts.get(tk, [])
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    eod_px = None
    for j in range(len(arr) - 1, -1, -1):
        if arr[j] < ts:
            break
        if time.strftime("%Y-%m-%d", time.localtime(arr[j])) == day:
            eod_px = spot_px[tk][j]; break
    r30 = d * (s30 - s0) / s0 * 100 if s30 else None
    reod = d * (eod_px - s0) / s0 * 100 if eod_px else None
    by[cat].append((r30, reod))


def stat(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return "n=0"
    n = len(v); mean = sum(v) / n; med = v[n // 2]
    hit = sum(1 for x in v if x > 0) / n * 100
    return f"n={n:4} mean={mean:+.2f}% med={med:+.2f}% hit={hit:.0f}%"


print("=== this week SENT alerts — directional forward move (signed by sentiment) ===")
print(f"{'category':12} {'+30min':40} {'to EOD'}")
order = sorted(by, key=lambda c: -len(by[c]))
tot30 = []
for c in order:
    r30 = [a for a, _ in by[c]]
    reod = [b for _, b in by[c]]
    tot30 += [a for a in r30 if a is not None]
    print(f"{c:12} {stat(r30):40} {stat(reod)}")
print(f"\nALL combined +30min: {stat(tot30)}")
print("READ: hit ~50% AND mean ~0 = coin flip = NOISE. >55% hit w/ +mean = worth keeping.")
