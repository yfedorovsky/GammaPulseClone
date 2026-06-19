"""Unified SPXW 0DTE tape collector — pulls ONCE, caches per-(day,bucket,STRIKE)
signed flow so BOTH the directional test and the magnet test run off one pull.

Pre-reg: docs/research/DEX_INTRADAY_PREREG.md (+ MAGNET addendum). Reuses the
tape/parity/delta helpers from dex_intraday_theta.py. ThetaData-heavy — market
must be CLOSED (holiday OK).

Cache row (data/dex_tape_cache.csv): day_idx, date, sec_end, spot, strike, dflow,
nflow, gross
  dflow = Σ delta×size×aggr_sign  (net signed delta flow at the strike)
  nflow = Σ price×size×100×aggr_sign  (net signed premium = call-vs-put balance)
  gross = Σ price×size×100  (total premium activity = "bubble size")
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dex_intraday_theta as T  # fetch_chunk, parity_spot, _bsm_delta, trading_days, consts

OUT = Path("data/dex_tape_cache.csv")


def build_day_perstrike(d):
    """Per-(3-min bucket, strike) signed flow for day d. Returns rows
    (sec_end, spot, strike, dflow, nflow, gross)."""
    ymd = d.strftime("%Y%m%d")
    raw = []
    for h in range(9, 16):
        for m0 in (0, 30):
            t0 = "09:30:00.000" if (h == 9 and m0 == 0) else f"{h:02d}:{m0:02d}:00.000"
            m1 = m0 + 30
            hh1, mm1 = (h + 1, 0) if m1 >= 60 else (h, m1)
            t1 = "16:00:00.000" if (hh1 > 16 or (hh1 == 16 and mm1 > 0)) else f"{hh1:02d}:{mm1:02d}:00.000"
            if t0 >= t1:
                continue
            raw += T.fetch_chunk(ymd, ymd, t0, t1)
    if len(raw) < 200:
        return []
    bsz = T.BUCKET_MIN * 60
    buckets: dict[int, list] = {}
    for row in raw:
        buckets.setdefault(int(row[0] // bsz), []).append(row)
    out = []
    close_sec = 16 * 3600
    for b in sorted(buckets):
        rows = buckets[b]
        S = T.parity_spot(rows)
        if not S or S <= 0:
            continue
        sec_end = (b + 1) * bsz
        Tyr = max(close_sec - sec_end, 120) / (365.0 * 24 * 3600)
        per: dict[float, list] = {}        # strike -> [dflow, nflow, gross]
        dcache: dict = {}
        for sec, k, is_call, size, px, bid, ask in rows:
            if abs(k / S - 1) > T.MONEY_BAND:
                continue
            if ask > 0 and px >= ask:
                sign = 1.0
            elif bid > 0 and px <= bid:
                sign = -1.0
            else:
                sign = 0.0  # mid — counts toward gross (activity) but not net flow
            key = (k, is_call)
            delta = dcache.get(key)
            if delta is None:
                delta = T._bsm_delta(S, k, Tyr, is_call)
                dcache[key] = delta
            acc = per.setdefault(k, [0.0, 0.0, 0.0])
            acc[0] += delta * size * sign
            acc[1] += px * size * 100 * sign
            acc[2] += px * size * 100
        for k, (dflow, nflow, gross) in per.items():
            out.append((sec_end, round(S, 3), k, round(dflow, 2), round(nflow, 1), round(gross, 1)))
    return out


def run():
    days = T.trading_days(T.START, T.END)
    print(f"collecting {len(days)} days {T.START}..{T.END} -> {OUT}", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w") as f:
        f.write("day_idx,date,sec_end,spot,strike,dflow,nflow,gross\n")
        for di, d in enumerate(days):
            rows = build_day_perstrike(d)
            if not rows:
                print(f"  {d} — no data", flush=True)
                continue
            for sec_end, S, k, dflow, nflow, gross in rows:
                f.write(f"{di},{d.isoformat()},{sec_end},{S},{k},{dflow},{nflow},{gross}\n")
            f.flush()
            print(f"  {d} — {len(rows)} strike-buckets", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    run()
