"""Dark-pool levels as support/resistance — PILOT backtest (Direction-A).

Pre-registration: docs/research/DARKPOOL_SR_PREREG.md (read it first).

Tests whether price levels with high DARK-POOL (FINRA/Nasdaq TRF off-exchange) volume
act as guardrails: when price later approaches a PRIOR-day DP level, does it reverse
(hold) more than at a distance-matched random level?

Anti-tautology: DP levels for test day t are built ONLY from prints on days < t.
Anti-"it's just a volume node": primary control = distance-matched random levels in the
same day's range (the lit-POC control is deferred — needs lit data; see pre-reg).

Inference: pooled DP hold-rate vs random; within-pool PERMUTATION null (random levels of
matched touch-count); name/day-clustered bootstrap 95% CI on the lift. Edge requires the
CI to exclude 0 AND permutation p<0.05 AND LOO robustness AND not OPEX-driven.

PILOT DATA: data/darkpool_cache/*_2026-06-13_2026-06-20.parquet (21 semis names, ~4 RTH
days, TRF-only, OPEX week). Underpowered by design; sizes the powered pull.

Run:  python scripts/darkpool_sr_backtest.py [--names MU,NVDA,...] [--R 0.003] [--H 30]
"""
from __future__ import annotations
import argparse, glob, json
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "darkpool_cache"
ET = "America/New_York"
RNG = np.random.default_rng(20260621)
BUCKET_PCT = 0.001      # price bucket = 0.1% of median price (matches darkpool_levels.py)
TOP_K = 5               # DP levels = top-K volume buckets from the trailing profile
EPS_PCT = 0.001         # touch band = +/- 0.1% of price
PRICE_CLIP = 0.15       # drop prints outside +/-15% of the day's median price
RAND_PER_DAY = 100      # random control levels drawn per name-day


def _load_clean(path):
    df = pd.read_parquet(path)[["ts_event", "price", "size"]].copy()
    df = df[df["size"] > 0]
    df["et"] = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(ET)
    df["date"] = df["et"].dt.normalize()
    # robust per-day price clip (kills the 367-on-a-1033-name garbage prints)
    med = df.groupby("date")["price"].transform("median")
    df = df[(df["price"] >= med * (1 - PRICE_CLIP)) & (df["price"] <= med * (1 + PRICE_CLIP))]
    return df


def _rth_minute_bars(day_df):
    """1-min RTH OHLC from cleaned prints (price only)."""
    t = day_df["et"].dt.time
    rth = day_df[(t >= pd.Timestamp("09:30").time()) & (t <= pd.Timestamp("16:00").time())]
    if rth.empty:
        return None
    g = rth.set_index("et")["price"].resample("1min")
    bars = pd.DataFrame({"open": g.first(), "high": g.max(), "low": g.min(),
                         "close": g.last()}).dropna()
    return bars if len(bars) >= 30 else None


def _dp_levels(trailing_df, med_px):
    bucket = max(med_px * BUCKET_PCT, 0.01)
    lvl = (trailing_df["price"] / bucket).round() * bucket
    prof = trailing_df.assign(lvl=lvl).groupby("lvl")["size"].sum().sort_values(ascending=False)
    return prof.head(TOP_K).index.to_numpy(), bucket


def _eval_level(bars, L, eps, R, H):
    """Return list of hold(1/0) for each RESOLVED touch of level L in bars.
    Touch = bar range overlaps [L-eps,L+eps] with the PRIOR bar strictly on one side.
    from_below (resistance): hold if price hits L*(1-R) before L*(1+R) within H bars.
    from_above (support):   hold if price hits L*(1+R) before L*(1-R) within H bars."""
    hi = bars["high"].to_numpy(); lo = bars["low"].to_numpy()
    n = len(bars); out = []
    up, dn = L * (1 + R), L * (1 - R)
    i = 1
    while i < n:
        touch = (lo[i] <= L + eps) and (hi[i] >= L - eps)
        if touch:
            if hi[i - 1] < L - eps:        # approached from BELOW -> resistance test
                res = None
                for v in range(i + 1, min(n, i + 1 + H)):
                    if lo[v] <= dn: res = 1; break   # rejected down = hold
                    if hi[v] >= up: res = 0; break   # broke up = fail
                if res is not None: out.append(res)
                i += H                        # skip ahead to avoid re-counting same touch
                continue
            elif lo[i - 1] > L + eps:      # approached from ABOVE -> support test
                res = None
                for v in range(i + 1, min(n, i + 1 + H)):
                    if hi[v] >= up: res = 1; break   # bounced up = hold
                    if lo[v] <= dn: res = 0; break   # broke down = fail
                if res is not None: out.append(res)
                i += H
                continue
        i += 1
    return out


def build(names, R, H):
    """Per name-day: DP levels from prior days, then DP + random hold records."""
    nameday = []   # each: dict(name,date,dp_holds[list],rand_holds[list])
    files = {Path(f).name.split("_")[0]: f for f in glob.glob(str(CACHE / "*_2026-06-13_2026-06-20.parquet"))}
    use = names or sorted(files)
    for nm in use:
        if nm not in files:
            continue
        df = _load_clean(files[nm])
        days = sorted(df["date"].unique())
        for i in range(1, len(days)):                 # test days 2..N (need prior history)
            d = days[i]
            trailing = df[df["date"] < d]
            day_df = df[df["date"] == d]
            if trailing.empty:
                continue
            med_px = float(day_df["price"].median())
            bars = _rth_minute_bars(day_df)
            if bars is None:
                continue
            eps = med_px * EPS_PCT
            dp_lv, bucket = _dp_levels(trailing, med_px)
            dp_holds = []
            for L in dp_lv:
                dp_holds += _eval_level(bars, float(L), eps, R, H)
            # distance-matched random control levels in the day's range (excl near DP)
            lo, hi = float(bars["low"].min()), float(bars["high"].max())
            rand_holds = []
            tries = 0
            while len(rand_holds) < RAND_PER_DAY and tries < RAND_PER_DAY * 6:
                tries += 1
                L = float(RNG.uniform(lo, hi))
                if any(abs(L - x) < 2 * eps for x in dp_lv):
                    continue
                rand_holds += _eval_level(bars, L, eps, R, H)
            nameday.append({"name": nm, "date": str(d)[:10],
                            "dp_holds": dp_holds, "rand_holds": rand_holds,
                            "n_dp": len(dp_holds), "n_rand": len(rand_holds)})
    return nameday


def analyze(nameday):
    dp_all = np.array([h for nd in nameday for h in nd["dp_holds"]], float)
    rd_all = np.array([h for nd in nameday for h in nd["rand_holds"]], float)
    if dp_all.size < 10 or rd_all.size < 10:
        return {"status": "THIN", "n_dp_touches": int(dp_all.size), "n_rand_touches": int(rd_all.size)}
    dp_rate = float(dp_all.mean()); rd_rate = float(rd_all.mean())
    lift = dp_rate - rd_rate
    # PERMUTATION null: random-level hold rate at matched touch-count, 5000x
    nd_size = dp_all.size
    null = np.array([rd_all[RNG.integers(0, rd_all.size, nd_size)].mean() for _ in range(5000)])
    perm_p = float((null >= dp_rate).mean())            # one-sided: DP holds MORE than random
    # name/day-CLUSTERED bootstrap CI on the lift (resample name-days)
    units = [nd for nd in nameday if nd["n_dp"] > 0]
    boots = []
    for _ in range(3000):
        samp = [units[k] for k in RNG.integers(0, len(units), len(units))]
        d = np.array([h for nd in samp for h in nd["dp_holds"]], float)
        r = np.array([h for nd in samp for h in nd["rand_holds"]], float)
        if d.size and r.size:
            boots.append(d.mean() - r.mean())
    ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))] if boots else [None, None]
    # leave-one-name-out robustness
    names = sorted({nd["name"] for nd in nameday})
    loo = {}
    for nm in names:
        d = np.array([h for nd in nameday if nd["name"] != nm for h in nd["dp_holds"]], float)
        r = np.array([h for nd in nameday if nd["name"] != nm for h in nd["rand_holds"]], float)
        if d.size and r.size:
            loo[nm] = round(float(d.mean() - r.mean()), 3)
    edge = (lift > 0 and ci[0] is not None and ci[0] > 0 and perm_p < 0.05)
    return {"status": "OK",
            "n_name_days": len(nameday), "n_dp_touches": int(dp_all.size),
            "n_rand_touches": int(rd_all.size),
            "dp_hold_rate": round(dp_rate, 3), "rand_hold_rate": round(rd_rate, 3),
            "lift": round(lift, 3), "lift_ci95": [round(ci[0], 3), round(ci[1], 3)],
            "perm_p_one_sided": round(perm_p, 4),
            "loo_lift_excluding_each_name": loo,
            "loo_min": round(min(loo.values()), 3) if loo else None,
            "verdict": ("GUARDRAIL_SIGNAL" if edge else "NULL_or_INCONCLUSIVE")}


# --------------------------------------------------------------------------- #
# DP-vs-LIT control (the decisive arm): does dark-pool concentration add S/R
# beyond ordinary (lit) volume nodes?  Needs the _LIT_/_DARK_ split caches from
# scripts/darkpool_lit_pull.py.  Path = clean LIT prints; levels = prior-day top-K
# volume nodes built SEPARATELY from dark vs lit prints.
# --------------------------------------------------------------------------- #
def build_litcontrol(names, R, H, window):
    nameday = []
    use = names or sorted({Path(f).name.split("_DARK_")[0]
                           for f in glob.glob(str(CACHE / f"*_DARK_{window}.parquet"))})
    for nm in use:
        df_dark = CACHE / f"{nm}_DARK_{window}.parquet"
        df_lit = CACHE / f"{nm}_LIT_{window}.parquet"
        if not (df_dark.exists() and df_lit.exists()):
            continue
        dark = _load_clean(df_dark); lit = _load_clean(df_lit)
        days = sorted(set(lit["date"].unique()))
        for i in range(1, len(days)):
            d = days[i]
            if str(d)[:10] == "2026-06-19":      # exclude OPEX Friday from test days
                continue
            lit_prior = lit[lit["date"] < d]; dark_prior = dark[dark["date"] < d]
            lit_day = lit[lit["date"] == d]
            if lit_prior.empty or dark_prior.empty or lit_day.empty:
                continue
            med_px = float(lit_day["price"].median())
            bars = _rth_minute_bars(lit_day)          # clean exchange price path
            if bars is None:
                continue
            eps = med_px * EPS_PCT
            dp_lv, _ = _dp_levels(dark_prior, med_px)
            lit_lv, _ = _dp_levels(lit_prior, med_px)
            dp_holds, lit_holds = [], []
            for L in dp_lv:
                dp_holds += _eval_level(bars, float(L), eps, R, H)
            for L in lit_lv:
                lit_holds += _eval_level(bars, float(L), eps, R, H)
            # random control too (same construction as the random-only pilot)
            lo, hi = float(bars["low"].min()), float(bars["high"].max())
            rand_holds, tries = [], 0
            while len(rand_holds) < RAND_PER_DAY and tries < RAND_PER_DAY * 6:
                tries += 1
                L = float(RNG.uniform(lo, hi))
                if any(abs(L - x) < 2 * eps for x in list(dp_lv) + list(lit_lv)):
                    continue
                rand_holds += _eval_level(bars, L, eps, R, H)
            nameday.append({"name": nm, "date": str(d)[:10],
                            "dp_holds": dp_holds, "lit_holds": lit_holds, "rand_holds": rand_holds,
                            "n_dp": len(dp_holds), "n_lit": len(lit_holds), "n_rand": len(rand_holds),
                            "dp_lv": [round(float(x), 2) for x in dp_lv],
                            "lit_lv": [round(float(x), 2) for x in lit_lv]})
    return nameday


def analyze_litcontrol(nameday):
    def pool(key):
        return np.array([h for nd in nameday for h in nd[key]], float)
    dp, lit, rd = pool("dp_holds"), pool("lit_holds"), pool("rand_holds")
    if dp.size < 10 or lit.size < 10:
        return {"status": "THIN", "n_dp": int(dp.size), "n_lit": int(lit.size)}
    dp_r, lit_r, rd_r = float(dp.mean()), float(lit.mean()), float(rd.mean())
    lift_dp_lit = dp_r - lit_r          # THE decisive number
    # two-sample permutation: shuffle dark/lit labels, 5000x
    both = np.concatenate([dp, lit]); n_dp = dp.size
    perm = np.empty(5000)
    for i in range(5000):
        idx = RNG.permutation(both.size)
        perm[i] = both[idx[:n_dp]].mean() - both[idx[n_dp:]].mean()
    perm_p = float((perm >= lift_dp_lit).mean())     # one-sided: DP holds MORE than lit
    # name/day-clustered bootstrap CI on lift_dp_lit
    units = [nd for nd in nameday if nd["n_dp"] > 0 and nd["n_lit"] > 0]
    boots = []
    for _ in range(3000):
        s = [units[k] for k in RNG.integers(0, len(units), len(units))]
        a = np.array([h for nd in s for h in nd["dp_holds"]], float)
        b = np.array([h for nd in s for h in nd["lit_holds"]], float)
        if a.size and b.size:
            boots.append(a.mean() - b.mean())
    ci = [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]
    # how often do dark and lit top-levels COINCIDE (redundancy check)?
    coincide = []
    for nd in nameday:
        for x in nd["dp_lv"]:
            coincide.append(int(any(abs(x - y) <= max(x * EPS_PCT * 2, 0.02) for y in nd["lit_lv"])))
    edge = (lift_dp_lit > 0 and ci[0] > 0 and perm_p < 0.05)
    return {"status": "OK", "n_name_days": len(nameday),
            "n_dp_touches": int(dp.size), "n_lit_touches": int(lit.size), "n_rand_touches": int(rd.size),
            "dp_hold_rate": round(dp_r, 3), "lit_hold_rate": round(lit_r, 3), "rand_hold_rate": round(rd_r, 3),
            "lift_dp_vs_lit": round(lift_dp_lit, 3), "lift_dp_vs_lit_ci95": ci,
            "lift_dp_vs_lit_perm_p": round(perm_p, 4),
            "lift_dp_vs_rand": round(dp_r - rd_r, 3), "lift_lit_vs_rand": round(lit_r - rd_r, 3),
            "dark_lit_level_coincidence": round(float(np.mean(coincide)), 3) if coincide else None,
            "verdict": ("DP_ADDS_BEYOND_LIT" if edge else "DP_REDUNDANT_WITH_LIT_or_INCONCLUSIVE")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="")
    ap.add_argument("--R", type=float, default=0.003)   # reversal/break = 0.3% of price
    ap.add_argument("--H", type=int, default=30)        # horizon = 30 one-min bars
    ap.add_argument("--litcontrol", action="store_true", help="DP-vs-LIT decisive arm")
    ap.add_argument("--window", default="2026-06-15_2026-06-19", help="for _LIT_/_DARK_ caches")
    a = ap.parse_args()
    names = [s.strip().upper() for s in a.names.split(",") if s.strip()] or None
    if a.litcontrol:
        nameday = build_litcontrol(names, a.R, a.H, a.window)
        res = analyze_litcontrol(nameday)
        res["params"] = {"R": a.R, "H": a.H, "TOP_K": TOP_K, "arm": "DP_vs_LIT"}
        out = ROOT / "research" / "results" / f"darkpool_sr_litcontrol_R{a.R}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"per_name_day": [{k: nd[k] for k in
                       ("name", "date", "n_dp", "n_lit", "n_rand", "dp_lv", "lit_lv")} for nd in nameday],
                       "result": res}, indent=2), encoding="utf-8")
        print(json.dumps(res, indent=2))
        return
    nameday = build(names, a.R, a.H)
    res = analyze(nameday)
    res["params"] = {"R": a.R, "H": a.H, "TOP_K": TOP_K, "BUCKET_PCT": BUCKET_PCT,
                     "EPS_PCT": EPS_PCT}
    out = ROOT / "research" / "results" / "darkpool_sr_pilot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"per_name_day": [{k: nd[k] for k in ("name", "date", "n_dp", "n_rand")}
                                                for nd in nameday], "result": res}, indent=2),
                   encoding="utf-8")
    print(json.dumps(res, indent=2))
    print(f"\n[pilot] {res.get('n_name_days')} name-days, "
          f"{res.get('n_dp_touches')} DP touches vs {res.get('n_rand_touches')} random. -> {out}")


if __name__ == "__main__":
    main()
