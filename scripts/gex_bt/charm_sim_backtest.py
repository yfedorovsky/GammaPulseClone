"""Simulate net CHARM (and GEX) from chains.db's real EOD greeks and test whether
it predicts next-day direction — the friend's "negative charm pushes down" claim.

chains.db has iv/spot/strike/dte/oi per contract (116 single names, YTD). We
recompute charm exactly as the live system does (server.gex._bsm_charm), sum the
dealer book per (root, date) -> net_cex, and test sign vs forward return. EOD /
single-name (not intraday-index), but n~13K root-days: if charm has ANY
directional power, this finds it.

Conventions match gex.py: charm$ = charm * oi * 100 * spot * sign (call +1 / put -1).
Run with numpy: .venv-autoresearch python OR any python with numpy.
"""
import sqlite3
import numpy as np

R, Q = 0.045, 0.013
DB = "data/chains_ytd_2026.db"


def _erf(x):  # Abramowitz-Stegun 7.1.26, vectorized, ~1e-7
    s = np.sign(x); x = np.abs(x); t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
               - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return s * y


def _cdf(x):
    return 0.5 * (1.0 + _erf(x / np.sqrt(2.0)))


def _pdf(x):
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = ("SELECT date, root, CAST(julianday(expiration)-julianday(date) AS INT) dte, "
     "strike, right, iv, spot, oi FROM option_eod "
     "WHERE iv>0 AND spot>0 AND oi>=10 "
     "AND CAST(julianday(expiration)-julianday(date) AS INT) BETWEEN 1 AND 45")
rows = con.execute(q).fetchall()
con.close()
print(f"loaded {len(rows):,} near-dated (1-45 DTE) contract-rows")

date = np.array([r[0] for r in rows])
root = np.array([r[1] for r in rows])
dte = np.array([r[2] for r in rows], dtype=float)
K = np.array([r[3] for r in rows], dtype=float)
right = np.array([r[4] for r in rows])
iv = np.array([r[5] for r in rows], dtype=float)
S = np.array([r[6] for r in rows], dtype=float)
oi = np.array([r[7] for r in rows], dtype=float)

T = dte / 365.0
sqrtT = np.sqrt(T)
d1 = (np.log(S / K) + (R - Q + 0.5 * iv * iv) * T) / (iv * sqrtT)
d2 = d1 - iv * sqrtT
common = np.exp(-Q * T) * _pdf(d1) * (2.0 * (R - Q) * T - d2 * iv * sqrtT) / (2.0 * T * iv * sqrtT)
is_call = (right == "C")
charm = np.where(is_call,
                 Q * np.exp(-Q * T) * _cdf(d1) - common,
                 -Q * np.exp(-Q * T) * _cdf(-d1) - common) / 365.0
gamma = _pdf(d1) * np.exp(-Q * T) / (S * iv * sqrtT)
sign = np.where(is_call, 1.0, -1.0)
charm_d = charm * oi * 100.0 * S * sign
gamma_d = gamma * oi * 100.0 * S * S * 0.01 * sign

# group by (root, date)
key = np.char.add(np.char.add(root, "|"), date)
uk, inv = np.unique(key, return_inverse=True)
net_cex = np.bincount(inv, weights=charm_d)
net_gex = np.bincount(inv, weights=gamma_d)
spot_g = np.bincount(inv, weights=S) / np.bincount(inv)
g_root = np.array([k.split("|")[0] for k in uk])
g_date = np.array([k.split("|")[1] for k in uk])

# forward 1-day return per root
order = np.lexsort((g_date, g_root))
fwd = np.full(len(uk), np.nan)
for i in range(len(order) - 1):
    a, b = order[i], order[i + 1]
    if g_root[a] == g_root[b] and spot_g[a] > 0:
        fwd[a] = (spot_g[b] - spot_g[a]) / spot_g[a]

m = ~np.isnan(fwd)


def report(metric, name):
    x = metric[m]; y = fwd[m] * 100
    # pooled corr
    c = np.corrcoef(x, y)[0, 1]
    neg = y[x < 0]; pos = y[x > 0]
    dn = (neg < 0).mean() * 100 if len(neg) else 0
    up = (pos > 0).mean() * 100 if len(pos) else 0
    print(f"\n{name}: n={m.sum()}  pooled corr(metric, fwd_ret) = {c:+.4f}")
    print(f"  when {name}<0 (n={len(neg)}): next-day mean={neg.mean():+.3f}%  DOWN-rate={dn:.0f}%")
    print(f"  when {name}>0 (n={len(pos)}): next-day mean={pos.mean():+.3f}%  UP-rate={up:.0f}%")


report(net_cex, "net_CHARM")
report(net_gex, "net_GEX")
print("\nREAD: |corr|<0.03 and down-rate ~50% = charm does NOT predict direction.")
print("(EOD single-name; the friend's claim is intraday-index-into-close — a narrower")
print(" case — but a ~0 result across 13K root-days is strong evidence it's priced in.)")
