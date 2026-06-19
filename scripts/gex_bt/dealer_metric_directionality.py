"""Do our recorded dealer metrics predict INDEX direction? (cross-ref GEX/VEX)

snapshots.db records, intraday for SPY/QQQ/SPX/IWM: pos_gex, neg_gex, net_delta,
net_vanna (VEX). It does NOT record charm/CEX. Test whether the sign of each
metric predicts the forward spot move (+30min, +2h, to-EOD). Pearson corr +
sign-split hit-rate. ~0 corr / ~50% hit = the metric is not directional (it is a
vol/pinning read, not a trade signal) — which is the honest expectation and the
context-engine thesis. Charm needs separate reconstruction (not recorded).

Read-only. Run: .venv\\Scripts\\python.exe scripts/gex_bt/dealer_metric_directionality.py
"""
import sqlite3
import bisect
from collections import defaultdict

con = sqlite3.connect("file:snapshots.db?mode=ro", uri=True)
IDX = ("SPY", "QQQ", "SPX", "IWM")
rows = con.execute(
    "SELECT ticker, ts, spot, pos_gex, neg_gex, net_delta, net_vanna "
    "FROM snapshots WHERE ticker IN ('SPY','QQQ','SPX','IWM') AND spot>0 AND is_stale=0 "
    "ORDER BY ticker, ts").fetchall()
con.close()

series = defaultdict(list)  # ticker -> [(ts, spot, net_gex, net_delta, net_vanna)]
for tk, ts, sp, pg, ng, nd, nv in rows:
    net_gex = (pg or 0) + (ng or 0)  # ng stored signed-negative
    series[tk].append((ts, sp, net_gex, nd or 0, nv or 0))


def fwd(arr, i, dt):
    """forward % spot move dt seconds after arr[i]."""
    t0, s0 = arr[i][0], arr[i][1]
    target = t0 + dt
    ts_list = [r[0] for r in arr]
    j = bisect.bisect_left(ts_list, target)
    if j >= len(arr):
        j = len(arr) - 1
    if abs(arr[j][0] - target) > 1800:
        return None
    return (arr[j][1] - s0) / s0 * 100


def corr(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pts)
    if n < 30:
        return None, n
    mx = sum(p[0] for p in pts) / n; my = sum(p[1] for p in pts) / n
    sxy = sum((p[0]-mx)*(p[1]-my) for p in pts)
    sxx = sum((p[0]-mx)**2 for p in pts); syy = sum((p[1]-my)**2 for p in pts)
    if sxx <= 0 or syy <= 0:
        return None, n
    return sxy / (sxx**0.5 * syy**0.5), n


HOR = [("+30m", 1800), ("+2h", 7200), ("EOD", 23400)]
METRICS = [("net_GEX", 2), ("net_delta", 3), ("net_vanna(VEX)", 4)]

for tk in IDX:
    arr = series.get(tk)
    if not arr or len(arr) < 100:
        print(f"\n{tk}: insufficient data ({len(arr) if arr else 0})"); continue
    print(f"\n=== {tk} (n={len(arr)} snapshots) ===")
    for mname, mi in METRICS:
        line = f"  {mname:16}"
        for hlabel, dt in HOR:
            xs = [r[mi] for r in arr]
            ys = [fwd(arr, i, dt) for i in range(len(arr))]
            c, n = corr(xs, ys)
            # sign-split: when metric<0, does fwd move <0 (down)?
            neg = [y for x, y in zip(xs, ys) if x is not None and x < 0 and y is not None]
            downhit = (sum(1 for y in neg if y < 0) / len(neg) * 100) if neg else 0
            line += f"  {hlabel}: r={c:+.3f}/down@neg={downhit:.0f}%" if c is not None else f"  {hlabel}: n/a"
        print(line)

print("\nREAD: |r|<0.05 and down@neg ~50% = NOT directional (vol/pinning read, not a signal).")
print("Charm/CEX is NOT recorded in snapshots -> the friend's charm claim needs a")
print("separate index-charm reconstruction (ThetaData greeks) or forward shadow-recording.")
