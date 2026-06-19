"""FibLV "1-day break -> 5-day target" — POWERED replication on Databento.

The Tradier-based v2 (fib_lv_bootstrap.py) was capped at ~20 trading days by
Tradier's 1-min retention. We have local Databento US-Equities-Mini tick parquets
for SPY at data/databento_cache/SPY/ spanning 2025-10-30 -> 2026-05-01 (~127
trading days) — a fully INDEPENDENT, EARLIER window that barely overlaps the
Tradier 20 days (5/21-6/18). This is a true out-of-sample replication at 6x the
sample, across a different regime (incl. two DST transitions).

Method (identical inference to fib_lv_bootstrap.py, only the bar source differs):
  - Aggregate the trade tape (action=='T') into 1-min and 5-min OHLC bars,
    converting ts_event UTC -> America/New_York (DST-correct), RTH 09:30-16:00.
  - 1-day band  = EMA-100 +/- 2sigma on 1-min bars, RESET each day (intraday view).
  - 5-day band  = EMA-100 +/- 2sigma on 5-min bars, CONTINUOUS across days (target).
  - Break = 1-min close beyond the 1-day band, with room to the 5-day band.
  - Hit   = price reaches the 5-day band (same direction) within 60 min.
  - Control = distance-matched base rate (same room, non-break bars).
  - Inference = day-clustered bootstrap (2000 draws) -> 95% CI + one-sided p.

Reuses band/side/lift/bootstrap functions from fib_lv_bootstrap.py verbatim.
First run builds a small bar cache (data/fib_lv_databento_bars.parquet); reruns
read that. Out -> data/fib_lv_databento_results.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
import fib_lv_bootstrap as FB   # band_intraday, band_continuous, side_frame, analyze_side, FWD

CACHE = Path("data/databento_cache/SPY")
BARS_CACHE = Path("data/fib_lv_databento_bars.parquet")
ET = "America/New_York"


def _bars_from_parquet(p: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One day's parquet -> (1-min OHLC, 5-min OHLC) of the trade tape, RTH ET."""
    df = pd.read_parquet(p, columns=["ts_event", "action", "price"])
    df = df[(df["action"] == "T") & df["price"].notna()]
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    t = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(ET)
    df = pd.DataFrame({"t": t, "price": df["price"].astype(float)}).set_index("t")
    rth = df.between_time("09:30", "16:00", inclusive="left")
    if rth.empty:
        return pd.DataFrame(), pd.DataFrame()

    def ohlc(freq):
        o = rth["price"].resample(freq).ohlc().dropna()
        o = o.reset_index().rename(columns={"close": "close", "high": "high",
                                            "low": "low"})
        o["t"] = o["t"].dt.tz_localize(None)   # naive ET, matches Tradier path
        o["date"] = o["t"].dt.date
        return o[["t", "close", "high", "low", "date"]]

    return ohlc("1min"), ohlc("5min")


def build_bars() -> tuple[pd.DataFrame, pd.DataFrame]:
    if BARS_CACHE.exists():
        allb = pd.read_parquet(BARS_CACHE)
        m1 = allb[allb["iv"] == "1m"].drop(columns="iv").reset_index(drop=True)
        m5 = allb[allb["iv"] == "5m"].drop(columns="iv").reset_index(drop=True)
        return m1, m5
    files = sorted(CACHE.glob("*.parquet"))
    f1, f5 = [], []
    for i, p in enumerate(files):
        a, b = _bars_from_parquet(p)
        if not a.empty:
            f1.append(a); f5.append(b)
        if (i + 1) % 20 == 0:
            print(f"  ...{i+1}/{len(files)} days", flush=True)
    m1 = pd.concat(f1, ignore_index=True).sort_values("t").reset_index(drop=True)
    m5 = pd.concat(f5, ignore_index=True).sort_values("t").reset_index(drop=True)
    # persist compact cache
    a1 = m1.copy(); a1["iv"] = "1m"; a5 = m5.copy(); a5["iv"] = "5m"
    pd.concat([a1, a5], ignore_index=True).to_parquet(BARS_CACHE, index=False)
    return m1, m5


def build_merged() -> pd.DataFrame:
    m1, m5 = build_bars()
    m1 = FB.band_intraday(m1)
    m5 = FB.band_continuous(m5)
    m5r = m5[["t", "u5", "d5"]]
    df = pd.merge_asof(m1.sort_values("t"), m5r.sort_values("t"), on="t")
    df = df.dropna(subset=["up1", "dn1", "u5", "d5", "base"]).reset_index(drop=True)
    df["fhigh"] = df.groupby("date")["high"].transform(
        lambda s: s[::-1].rolling(FB.FWD, min_periods=1).max()[::-1].shift(-1))
    df["flow"] = df.groupby("date")["low"].transform(
        lambda s: s[::-1].rolling(FB.FWD, min_periods=1).min()[::-1].shift(-1))
    return df


def run():
    df = build_merged()
    out = {
        "instrument": "SPY", "source": "databento_equs_mini (trade tape)",
        "fwd_min": FB.FWD, "ema_n": FB.EMA_N, "n_boot": FB.N_BOOT,
        "n_bars": int(len(df)),
        "n_trading_days": int(df["date"].nunique()),
        "day_range": [str(df["date"].min()), str(df["date"].max())],
        "note": "independent of the Tradier 20-day window (barely overlaps); "
                "true out-of-sample at 6x sample.",
        "up": FB.analyze_side(df, "up"),
        "down": FB.analyze_side(df, "down"),
    }
    print(json.dumps(out, indent=2))
    Path("data/fib_lv_databento_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    run()
