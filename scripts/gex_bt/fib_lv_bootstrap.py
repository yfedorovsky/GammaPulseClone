"""FibLV "1-day break -> 5-day target" — DEEPENED test with proper inference.

This is the v2 of scripts/gex_bt/fib_lv_test.py. Two upgrades over v1:

  1. SAMPLE: fetch 1-min day-by-day (Tradier 400s on wide ranges but serves
     full single days back to its ~20-trading-day 1-min retention floor, ~5/22).
     v1 used a single wide query capped at ~10 days. ~20 days now = 2x. Tradier's
     20-day 1-min retention is a HARD ceiling for SPY (ThetaData stock = free-
     blocked; no other intraday SPY source). Stated honestly, not papered over.

  2. METHODOLOGY: the "5-day timeframe" outer band (the TARGET) is now computed
     on a CONTINUOUS 5-min series (trailing 100 bars across day boundaries),
     not reset per day. v1 reset it per day, which at 9:35 AM gave the band
     almost no lookback -> a meaningless "5-day" level. The "1-day timeframe"
     trigger band stays intraday-reset (1-min, matches viewing the 1D chart).

  3. INFERENCE: day-clustered bootstrap (resample whole days w/ replacement,
     2000 draws) on the DISTANCE-MATCHED lift -> 95% CI + one-sided p. v1 gave
     a point estimate with no CI. A 2-sigma break is already extended, so the
     decisive control is the distance-matched base rate (P(reach 5-day band in
     60m) among same-room non-break bars), not the raw hit rate.

Pre-registered decision rule (Direction-A): the claim survives only if the
distance-matched lift's 95% day-clustered CI excludes 0 on at least one side.
Otherwise it is momentum/vol-clustering already priced into the base rate.

Out -> data/fib_lv_bootstrap_results.json
"""
from __future__ import annotations
import json, sys
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd, requests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server.config import get_settings

try:
    from server.market_calendar import is_market_holiday
except Exception:  # pragma: no cover - fallback if signature differs
    def is_market_holiday(_d):  # type: ignore
        return False

S = get_settings(); TB = S.tradier_base_url.rstrip("/")
TH = {"Authorization": f"Bearer {S.tradier_token}", "Accept": "application/json"}
FWD = 60          # minutes to reach the 5-day band
EMA_N = 100       # FibLV EMA/sigma length (his Webull default)
N_BOOT = 2000     # day-clustered bootstrap draws
RNG = np.random.default_rng(20260619)   # fixed seed (no Math.random in scripts)
END = date(2026, 6, 18)
LOOKBACK_DAYS = 40   # calendar days back to probe; per-day fetch auto-skips gaps


def fetch_day(interval: str, d: date) -> pd.DataFrame:
    """Single trading day of bars. Empty DF if Tradier has no data (weekend,
    holiday, or beyond retention -> 400/empty)."""
    ds = d.isoformat()
    r = requests.get(f"{TB}/markets/timesales", headers=TH, timeout=30, params={
        "symbol": "SPY", "interval": interval,
        "start": f"{ds} 09:30", "end": f"{ds} 16:00", "session_filter": "open"})
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        return pd.DataFrame()
    data = (r.json().get("series") or {}).get("data") or []
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame([{"t": b["time"], "close": b["close"],
                        "high": b["high"], "low": b["low"]} for b in data])
    df["t"] = pd.to_datetime(df["t"]); df["date"] = df["t"].dt.date
    return df


def collect(interval: str, days: list[date]) -> pd.DataFrame:
    frames = []
    for d in days:
        f = fetch_day(interval, d)
        if not f.empty:
            frames.append(f)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("t").reset_index(drop=True)


def band_intraday(df: pd.DataFrame, n: int = EMA_N) -> pd.DataFrame:
    """1-day-timeframe band: EMA/sigma RESET each day (intraday view)."""
    g = df.groupby("date", group_keys=False)
    df = df.copy()
    df["base"] = g["close"].apply(lambda s: s.ewm(span=n, min_periods=20).mean())
    sd = g["close"].apply(lambda s: s.rolling(n, min_periods=20).std())
    df["up1"] = df["base"] + 2 * sd
    df["dn1"] = df["base"] - 2 * sd
    return df


def band_continuous(df: pd.DataFrame, n: int = EMA_N) -> pd.DataFrame:
    """5-day-timeframe band: EMA/sigma CONTINUOUS across day boundaries."""
    df = df.sort_values("t").copy()
    df["b5"] = df["close"].ewm(span=n, min_periods=20).mean()
    sd = df["close"].rolling(n, min_periods=20).std()
    df["u5"] = df["b5"] + 2 * sd
    df["d5"] = df["b5"] - 2 * sd
    return df


def build() -> pd.DataFrame:
    days = []
    d = END
    for _ in range(LOOKBACK_DAYS):
        if d.weekday() < 5 and not is_market_holiday(d):
            days.append(d)
        d -= timedelta(days=1)
    days = sorted(days)
    m1 = collect("1min", days)
    m5 = collect("5min", days)
    if m1.empty or m5.empty:
        raise SystemExit(json.dumps({"error": "no bars", "n1": len(m1), "n5": len(m5)}))
    # restrict 5-min to days the 1-min feed also covers (1-min is the binding floor)
    keep = set(m1["date"].unique())
    m5 = m5[m5["date"].isin(keep)].reset_index(drop=True)
    m1 = band_intraday(m1)
    m5 = band_continuous(m5)
    m5r = m5[["t", "u5", "d5"]]
    df = pd.merge_asof(m1.sort_values("t"), m5r.sort_values("t"), on="t")
    df = df.dropna(subset=["up1", "dn1", "u5", "d5", "base"]).reset_index(drop=True)
    # forward extremes within FWD minutes, per day
    df["fhigh"] = df.groupby("date")["high"].transform(
        lambda s: s[::-1].rolling(FWD, min_periods=1).max()[::-1].shift(-1))
    df["flow"] = df.groupby("date")["low"].transform(
        lambda s: s[::-1].rolling(FWD, min_periods=1).min()[::-1].shift(-1))
    return df


def side_frame(df: pd.DataFrame, side: str) -> pd.DataFrame:
    """Eligible rows for one side with break/base/dist/hit/date columns."""
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
    out = pd.DataFrame({
        "date": df["date"], "brk": brk, "dist": dist,
        "hit": hit.astype(float),
    })[elig].reset_index(drop=True)
    return out


def matched_lift(sf: pd.DataFrame, edges: np.ndarray, kmin: int = 5) -> float | None:
    """Distance-matched lift: within each dist bin (fixed global edges), mean
    hit(break) - mean hit(non-break); average over bins that have >=kmin each."""
    b = np.digitize(sf["dist"].to_numpy(), edges[1:-1])
    lifts = []
    for qi in range(len(edges) - 1):
        m = b == qi
        br = sf["brk"].to_numpy() & m
        ba = (~sf["brk"].to_numpy()) & m
        if br.sum() >= kmin and ba.sum() >= kmin:
            lifts.append(sf["hit"].to_numpy()[br].mean() - sf["hit"].to_numpy()[ba].mean())
    if not lifts:
        return None
    return float(np.mean(lifts))


def analyze_side(df: pd.DataFrame, side: str) -> dict:
    sf = side_frame(df, side)
    nb = int(sf["brk"].sum())
    if nb < 20:
        return {"n_break": nb, "note": "too few breaks for inference"}
    # fixed global quartile edges on eligible dist (so bootstrap bins are stable)
    edges = np.quantile(sf["dist"], [0, .25, .5, .75, 1.0])
    edges = np.unique(edges)
    point = matched_lift(sf, edges)
    bh = float(sf.loc[sf["brk"], "hit"].mean())
    ph = float(sf.loc[~sf["brk"], "hit"].mean())
    # day-clustered bootstrap
    days = sf["date"].unique()
    by_day = {d: sf[sf["date"] == d] for d in days}
    draws = []
    for _ in range(N_BOOT):
        pick = RNG.choice(days, size=len(days), replace=True)
        pooled = pd.concat([by_day[d] for d in pick], ignore_index=True)
        ml = matched_lift(pooled, edges)
        if ml is not None:
            draws.append(ml)
    draws = np.array(draws)
    lo, hi = (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))) \
        if len(draws) else (None, None)
    one_sided_p = float((draws <= 0).mean()) if len(draws) else None
    return {
        "n_break": nb, "n_base": int((~sf["brk"]).sum()),
        "n_days": int(len(days)),
        "break_hit_rate": round(bh, 3), "base_hit_rate": round(ph, 3),
        "raw_lift": round(bh - ph, 3),
        "dist_matched_lift": round(point, 3) if point is not None else None,
        "boot_ci95": [round(lo, 3), round(hi, 3)] if lo is not None else None,
        "one_sided_p_lift_le_0": round(one_sided_p, 4) if one_sided_p is not None else None,
        "boot_n": int(len(draws)),
        "verdict": _verdict(lo),
    }


def _verdict(lo) -> str:
    if lo is None:
        return "indeterminate"
    return "SURVIVES (CI excludes 0)" if lo > 0 else "NULL (CI includes 0)"


def run():
    df = build()
    out = {
        "instrument": "SPY", "fwd_min": FWD, "ema_n": EMA_N, "n_boot": N_BOOT,
        "n_bars": int(len(df)),
        "n_trading_days": int(df["date"].nunique()),
        "day_range": [str(df["date"].min()), str(df["date"].max())],
        "ceiling_note": "Tradier ~20-day 1-min retention is the hard SPY ceiling",
        "up": analyze_side(df, "up"),
        "down": analyze_side(df, "down"),
    }
    print(json.dumps(out, indent=2))
    Path("data").mkdir(exist_ok=True)
    Path("data/fib_lv_bootstrap_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
