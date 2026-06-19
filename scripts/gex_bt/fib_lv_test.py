"""FibLV "1-day break -> 5-day target" test (Discord friend's claim).

FibLV decoded from his Webull screenshot = Bollinger(EMA-100, 2 sigma) with inner
fib lines at 1.0 and 0.382 sigma. BASE=EMA100, outer band=EMA100 +/- 2*std100.
Claim: when price breaks the 1-DAY-timeframe outer band, it "almost always"
travels to the 5-DAY-timeframe band level.

Test (SPY = his instrument, clean 1m/5m via Tradier):
 - 1-day FibLV = EMA100 +/- 2*std100 on 1-MIN bars (tight).
 - 5-day FibLV = same on 5-MIN bars (wide, the target).
 - Break = 1m close beyond the 1-day outer band, with room to the 5-day band.
 - Hit = price reaches the 5-day band (same direction) within 60 min.
 - DECISIVE control: base rate = P(reach the 5-day band in 60m) from ALL bars with
   the same room-to-target (distance-matched) -- a 2sigma break is already extended,
   so the break must beat a distance-matched baseline, not just have a high raw rate.

Out -> data/fib_lv_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, requests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server.config import get_settings

S = get_settings(); TB = S.tradier_base_url.rstrip("/")
TH = {"Authorization": f"Bearer {S.tradier_token}", "Accept": "application/json"}
FWD = 60   # minutes to reach target


def bars(interval, start, end):
    r = requests.get(f"{TB}/markets/timesales", headers=TH, timeout=40, params={
        "symbol": "SPY", "interval": interval, "start": start, "end": end,
        "session_filter": "open"})
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        print(f"  bars({interval}) http={r.status_code} len={len(r.text)}", flush=True)
        return pd.DataFrame()
    d = (r.json().get("series") or {}).get("data") or []
    df = pd.DataFrame([{"t": b["time"], "close": b["close"], "high": b["high"],
                        "low": b["low"]} for b in d])
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["t"]); df["date"] = df["t"].dt.date
    return df


def fiblv(df, n=100):
    g = df.groupby("date", group_keys=False)
    df = df.copy()
    df["base"] = g["close"].apply(lambda s: s.ewm(span=n, min_periods=20).mean())
    sd = g["close"].apply(lambda s: s.rolling(n, min_periods=20).std())
    df["up1"] = df["base"] + 2 * sd
    df["dn1"] = df["base"] - 2 * sd
    return df


def run():
    m1 = bars("1min", "2026-06-04 09:30", "2026-06-18 16:00")
    if m1.empty:
        m1 = bars("1min", "2026-06-09 09:30", "2026-06-18 16:00")
    m5 = bars("5min", "2026-05-12 09:30", "2026-06-18 16:00")
    if m1.empty or m5.empty:
        print(json.dumps({"error": "no bars", "n1": len(m1), "n5": len(m5)})); return
    m1 = fiblv(m1); m5 = fiblv(m5)
    m5r = m5[["t", "up1", "dn1"]].rename(columns={"up1": "u5", "dn1": "d5"})
    df = pd.merge_asof(m1.sort_values("t"), m5r.sort_values("t"), on="t")
    df = df.dropna(subset=["up1", "dn1", "u5", "d5", "base"]).reset_index(drop=True)

    # forward extremes within FWD minutes, per day
    df["fhigh"] = df.groupby("date")["high"].transform(
        lambda s: s[::-1].rolling(FWD, min_periods=1).max()[::-1].shift(-1))
    df["flow"] = df.groupby("date")["low"].transform(
        lambda s: s[::-1].rolling(FWD, min_periods=1).min()[::-1].shift(-1))

    out = {"window": "2026-05-19..06-18", "n_bars": int(len(df)), "fwd_min": FWD}
    for side in ("up", "down"):
        if side == "up":
            room = df["close"] < df["u5"]
            brk = df["close"] > df["up1"]
            dist = (df["u5"] - df["close"]) / df["close"]
            hit = df["fhigh"] >= df["u5"]
        else:
            room = df["close"] > df["d5"]
            brk = df["close"] < df["dn1"]
            dist = (df["close"] - df["d5"]) / df["close"]
            hit = df["flow"] <= df["d5"]
        elig = room & dist.notna() & hit.notna()
        b = elig & brk
        base = elig & ~brk
        if b.sum() < 30:
            out[side] = {"n_break": int(b.sum()), "note": "too few breaks"}; continue
        # distance-matched: bin eligible rows by dist quartile, compare hit-rate
        q = pd.qcut(dist[elig], 4, labels=False, duplicates="drop")
        rows = []
        for qi in sorted(pd.unique(q.dropna())):
            mask = elig.copy(); mask[:] = False
            idx = dist[elig].index[q == qi]
            mb = df.index.isin(idx) & brk
            mbase = df.index.isin(idx) & ~brk
            if mb.sum() >= 5 and mbase.sum() >= 5:
                rows.append((float(hit[mb].mean()), float(hit[mbase].mean()),
                             int(mb.sum()), int(mbase.sum())))
        bh = float(hit[b].mean()); ph = float(hit[base].mean())
        # distance-matched avg lift
        lifts = [r[0] - r[1] for r in rows]
        out[side] = {
            "n_break": int(b.sum()), "n_base": int(base.sum()),
            "break_hit_rate": round(bh, 3), "base_hit_rate": round(ph, 3),
            "raw_lift": round(bh - ph, 3),
            "dist_matched_lift": round(float(np.mean(lifts)), 3) if lifts else None,
            "per_quartile": [(round(r[0], 2), round(r[1], 2), r[2], r[3]) for r in rows],
            "n_days": int(df.loc[b, "date"].nunique()),
        }
    print(json.dumps(out, indent=2))
    Path("data/fib_lv_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
