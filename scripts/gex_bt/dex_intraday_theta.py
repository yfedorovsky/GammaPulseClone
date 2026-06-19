"""DEX INTRADAY-FLOW test — the friend's REAL claim, on the true SPXW tape.

Pre-reg: docs/research/DEX_INTRADAY_PREREG.md. Tests whether the intraday 3-min
CHANGE in DEX (net signed buy-to-open delta FLOW — "premium building in a
direction") predicts short-horizon SPX continuation. This is the FLOW claim, NOT
the static-level claim falsified in DEX_BACKTEST_FINDINGS.md.

Data: SPXW 0DTE bulk trade_quote (whole-chain tick tape + NBBO) from ThetaData.
Spot from ATM put-call parity (tick resolution, no snapshot staleness). Delta via
flat-IV BSM. Aggressor from trade-vs-NBBO. Per-3-min net signed delta-flow +
notional-flow, per-day z-scored. Forward 5/15/30-min SPX return.

NOTE: ThetaData-heavy — run only when market CLOSED (RTH-pause rule). Holiday OK.
Out -> data/dex_intraday_results.json (+ buckets cache)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests
from scipy import stats as sps
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

REST = "http://127.0.0.1:25503"
START, END = "2026-05-05", "2026-06-18"   # ~30 trading days (true 0DTE tape)
MONEY_BAND = 0.04
BUCKET_MIN = 3
FLAT_IV = 0.15
R = 0.045
RNG = np.random.default_rng(20260619)


def trading_days(a, b):
    try:
        from server.market_calendar import is_market_holiday
    except Exception:
        is_market_holiday = lambda d: False  # noqa: E731
    d0 = dt.date.fromisoformat(a); d1 = dt.date.fromisoformat(b)
    out = []
    d = d0
    while d <= d1:
        if d.weekday() < 5 and not is_market_holiday(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _bsm_delta(S, K, T, is_call):
    if S <= 0 or K <= 0 or T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (R + 0.5 * FLAT_IV ** 2) * T) / (FLAT_IV * np.sqrt(T))
    return float(sps.norm.cdf(d1) if is_call else sps.norm.cdf(d1) - 1.0)


def fetch_chunk(exp_ymd, date_ymd, t0, t1):
    """Bulk trade_quote for one expiry/day/time-window. Returns parsed rows:
    (sec_in_day, strike, is_call, size, price, bid, ask)."""
    try:
        r = requests.get(f"{REST}/v3/option/history/trade_quote", timeout=90, params={
            "symbol": "SPXW", "expiration": exp_ymd, "start_date": date_ymd,
            "end_date": date_ymd, "start_time": t0, "end_time": t1})
    except Exception:
        return []
    if r.status_code != 200:
        return []
    lines = r.text.splitlines()
    if len(lines) < 2:
        return []
    hdr = [h.strip().strip('"') for h in lines[0].split(",")]
    ix = {n: i for i, n in enumerate(hdr)}
    need = ("strike", "right", "trade_timestamp", "size", "price", "bid", "ask")
    if any(n not in ix for n in need):
        return []
    out = []
    for ln in lines[1:]:
        c = ln.split(",")
        try:
            k = float(c[ix["strike"]])
            is_call = c[ix["right"]].strip().strip('"')[:1].upper() == "C"
            ts = c[ix["trade_timestamp"]]
            hh, mm, ss = int(ts[11:13]), int(ts[14:16]), float(ts[17:23])
            sec = hh * 3600 + mm * 60 + ss
            size = int(c[ix["size"]]); px = float(c[ix["price"]])
            bid = float(c[ix["bid"]]); ask = float(c[ix["ask"]])
        except (ValueError, IndexError):
            continue
        if size > 0 and px > 0:
            out.append((sec, k, is_call, size, px, bid, ask))
    return out


def parity_spot(rows):
    """ATM put-call parity spot from a bucket's quotes. Per strike, last call/put
    mid; pick strike with both and smallest |C-P| (ATM); S = K + Cmid - Pmid."""
    cmid, pmid = {}, {}
    for sec, k, is_call, size, px, bid, ask in rows:
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else px
        (cmid if is_call else pmid)[k] = mid
    both = [k for k in cmid if k in pmid]
    if not both:
        return None
    k = min(both, key=lambda kk: abs(cmid[kk] - pmid[kk]))
    return k + cmid[k] - pmid[k]


def build_day(d):
    """Return list of 3-min buckets for day d: (sec_end, spot, dflow, nflow)."""
    ymd = d.strftime("%Y%m%d")
    raw = []
    # pull in 30-min chunks 09:30-16:00 ET
    for h in range(9, 16):
        for m0 in (0, 30):
            if h == 9 and m0 == 0:
                t0 = "09:30:00.000"
            else:
                t0 = f"{h:02d}:{m0:02d}:00.000"
            m1 = m0 + 30
            hh1, mm1 = (h + 1, 0) if m1 >= 60 else (h, m1)
            if hh1 > 16 or (hh1 == 16 and mm1 > 0):
                t1 = "16:00:00.000"
            else:
                t1 = f"{hh1:02d}:{mm1:02d}:00.000"
            if t0 >= t1:
                continue
            raw += fetch_chunk(ymd, ymd, t0, t1)
    if len(raw) < 200:
        return []
    # group into 3-min buckets
    bsz = BUCKET_MIN * 60
    buckets: dict[int, list] = {}
    for row in raw:
        b = int(row[0] // bsz)
        buckets.setdefault(b, []).append(row)
    out = []
    close_sec = 16 * 3600
    for b in sorted(buckets):
        rows = buckets[b]
        S = parity_spot(rows)
        if not S or S <= 0:
            continue
        sec_end = (b + 1) * bsz
        T = max(close_sec - sec_end, 120) / (365.0 * 24 * 3600)
        dflow = nflow = 0.0
        dcache: dict = {}  # delta per (strike, is_call) — constant within a bucket
        for sec, k, is_call, size, px, bid, ask in rows:
            if abs(k / S - 1) > MONEY_BAND:
                continue
            if ask > 0 and px >= ask:
                sign = 1.0
            elif bid > 0 and px <= bid:
                sign = -1.0
            else:
                continue  # mid — excluded
            key = (k, is_call)
            delta = dcache.get(key)
            if delta is None:
                delta = _bsm_delta(S, k, T, is_call)
                dcache[key] = delta
            dflow += delta * size * sign
            nflow += px * size * 100 * sign
        out.append((sec_end, S, dflow, nflow))
    return out


def run():
    days = trading_days(START, END)
    print(f"pulling {len(days)} trading days {START}..{END}", flush=True)
    panel = []  # (day_idx, sec_end, spot, dflow, nflow)
    spots_by_day = {}
    for di, d in enumerate(days):
        bk = build_day(d)
        if not bk:
            print(f"  {d} — no data", flush=True)
            continue
        spots_by_day[di] = {b[0]: b[1] for b in bk}
        for sec_end, S, dflow, nflow in bk:
            panel.append((di, sec_end, S, dflow, nflow))
        print(f"  {d} — {len(bk)} buckets", flush=True)

    if len(panel) < 200:
        print(json.dumps({"n": len(panel), "note": "too few — inconclusive"}))
        return
    arr = np.array(panel, float)
    di, sec, spot, dflow, nflow = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]

    # forward returns (parity spot, same day) at +5/15/30 min
    def fwd(mins):
        out = np.full(len(panel), np.nan)
        tgt = mins * 60
        for d in np.unique(di):
            m = di == d
            secs = sec[m]; sps_ = spot[m]; idx = np.where(m)[0]
            for j, s0 in enumerate(secs):
                cand = np.where(secs >= s0 + tgt)[0]
                if len(cand):
                    out[idx[j]] = sps_[cand[0]] / sps_[j] - 1
        return out

    # per-day z-score of flows + per-day return vol
    def dayz(x):
        z = np.full(len(x), np.nan)
        for d in np.unique(di):
            m = di == d
            mu, sd = np.nanmean(x[m]), np.nanstd(x[m]) or 1e-9
            z[m] = (x[m] - mu) / sd
        return z
    dz, nz = dayz(dflow), dayz(nflow)

    def boot_corr(x, y, n=2000):
        m = np.isfinite(x) & np.isfinite(y)
        x, y, dd = x[m], y[m], di[m]
        if len(x) < 100:
            return np.nan, np.nan, 0
        obs = np.corrcoef(x, y)[0, 1]
        uniq = np.unique(dd)
        idxs = {u: np.where(dd == u)[0] for u in uniq}
        cnt = 0
        for _ in range(n):
            pick = RNG.choice(uniq, len(uniq), replace=True)
            ii = np.concatenate([idxs[u] for u in pick])
            if abs(np.corrcoef(x[ii], y[ii])[0, 1]) >= abs(obs):
                cnt += 1
        return float(obs), (cnt + 1) / (n + 1), int(len(x))

    def placebo_sign(x, y, n=500):
        m = np.isfinite(x) & np.isfinite(y)
        x, y, dd = x[m], y[m], di[m]
        if len(x) < 100:
            return np.nan, np.nan
        acc = np.mean(np.sign(x) == np.sign(y))
        null = []
        for _ in range(n):
            xp = np.copy(x)
            for u in np.unique(dd):
                mm = dd == u
                xp[mm] = RNG.permutation(xp[mm])
            null.append(np.mean(np.sign(xp) == np.sign(y)))
        null = np.array(null)
        return float(acc), float(np.nanpercentile(null, 97.5))

    res = {"n_days": int(len(np.unique(di))), "n_buckets": len(panel),
           "window": f"{START}..{END}"}
    fwds = {m: fwd(m) for m in (5, 15, 30)}
    for label, z in (("delta_flow", dz), ("notional_flow", nz)):
        for m in (5, 15, 30):
            c, p, nn = boot_corr(z, fwds[m])
            acc, p97 = placebo_sign(z, fwds[m])
            res[f"{label}_fwd{m}"] = {
                "corr": round(c, 4) if c == c else None,
                "boot_p": round(p, 4) if p == p else None,
                "sign_acc": round(acc, 4) if acc == acc else None,
                "placebo_97.5": round(p97, 4) if p97 == p97 else None,
                "n": nn}
        # contemporaneous (same-bucket) — coincident vs leading check
        # use 0-min: correlation of flow with the move DURING its own bucket
    # Holm across delta/notional x 5/15/30
    fam = {k: v["boot_p"] for k, v in res.items()
           if k.endswith(("fwd5", "fwd15", "fwd30")) and v.get("boot_p") is not None}
    ranked = sorted(fam.items(), key=lambda kv: kv[1])
    mm = len(ranked)
    res["holm"] = {k: {"p": pv, "thr": round(0.05 / (mm - i), 4), "pass": bool(pv < 0.05 / (mm - i))}
                   for i, (k, pv) in enumerate(ranked)}
    print("\n=== DEX INTRADAY-FLOW RESULTS ===")
    print(json.dumps(res, indent=2))
    Path("data/dex_intraday_results.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    run()
