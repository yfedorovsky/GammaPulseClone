"""Shared Databento bar/flow loader for the SPY/QQQ microstructure tests.

POLARS rewrite (was pandas). The heavy passes (scan 160 days of MBP-1 tick
parquets, filter, resample to bars / aggregate OFI) are now a single lazy
scan_parquet -> filter -> group_by_dynamic with column projection + the
streaming engine. Same cache filenames + pandas return type, so the test
scripts are unchanged.

  load_ohlcv(ticker, freq)  -> RTH OHLCV bars (trade tape), DST-correct UTC->ET
  load_ofi(ticker, freq)    -> per-bar flow + mid-return:
        tsv  = trade-signed volume (trade>=ask:+size, <=bid:-size)  [ROBUST]
        ofi  = Cont-Kukanov-Stoikov L1 order-flow imbalance         [secondary]
        mid_open/mid_close/ret = bar mid log-return
     The contemporaneous corr(tsv, ret) is the sanity gate (must be strongly +).
"""
from __future__ import annotations
from datetime import time
from pathlib import Path
import pandas as pd, polars as pl

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "databento_cache"
OUT = ROOT / "data"
ET = "America/New_York"
_EVERY = {"1min": "1m", "5min": "5m", "1m": "1m", "5m": "5m"}


def _day_files(ticker: str) -> list[str]:
    return [str(f) for f in sorted((CACHE / ticker.upper()).glob("*.parquet"))]


def _et_rth(lf: pl.LazyFrame) -> pl.LazyFrame:
    """UTC ts_event -> naive-ET 't' + 'date', filtered to RTH [09:30,16:00)."""
    return (lf
            .with_columns(pl.col("ts_event").dt.convert_time_zone(ET).alias("t"))
            .with_columns(pl.col("t").dt.date().alias("date"))
            .filter(pl.col("t").dt.time().is_between(time(9, 30), time(16, 0),
                                                     closed="left"))
            .with_columns(pl.col("t").dt.replace_time_zone(None)))


def load_ohlcv(ticker: str, freq: str = "1min", rebuild: bool = False) -> pd.DataFrame:
    cache = OUT / f"db_ohlcv_{ticker.upper()}_{freq}.parquet"
    if cache.exists() and not rebuild:
        return pd.read_parquet(cache)
    every = _EVERY[freq]
    lf = (pl.scan_parquet(_day_files(ticker))
          .select(["ts_event", "action", "price", "size"])
          .filter((pl.col("action") == "T") & pl.col("price").is_not_null()))
    lf = (_et_rth(lf).sort("t")
          .group_by_dynamic("t", every=every, group_by="date", label="left")
          .agg([pl.col("price").first().alias("open"),
                pl.col("price").max().alias("high"),
                pl.col("price").min().alias("low"),
                pl.col("price").last().alias("close"),
                pl.col("size").sum().alias("volume")]))
    pdf = lf.collect(engine="streaming").to_pandas()
    pdf["date"] = pd.to_datetime(pdf["t"]).dt.date
    pdf = pdf.sort_values("t").reset_index(drop=True)
    pdf.to_parquet(cache, index=False)
    return pdf


def _ofi_one_day(path: str, every: str) -> pd.DataFrame:
    """OFI/TSV/mid bars for ONE day. Processed per-day so the full quote tape
    is never concatenated in memory (the all-files scan + window op OOMs at
    ~30GB on 160 days)."""
    lf = (pl.scan_parquet(path)
          .select(["ts_event", "action", "price", "size",
                   "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"])
          .filter((pl.col("bid_px_00") > 0) & (pl.col("ask_px_00") > 0)))
    lf = _et_rth(lf).sort("t")
    # single day -> plain shift(1), no .over() needed
    lf = lf.with_columns([
        pl.col("bid_px_00").shift(1).alias("pbl"),
        pl.col("bid_sz_00").shift(1).alias("qbl"),
        pl.col("ask_px_00").shift(1).alias("pal"),
        pl.col("ask_sz_00").shift(1).alias("qal"),
    ])
    lf = lf.with_columns([
        (((pl.col("bid_px_00") >= pl.col("pbl")).cast(pl.Float64) * pl.col("bid_sz_00")
          - (pl.col("bid_px_00") <= pl.col("pbl")).cast(pl.Float64) * pl.col("qbl")
          - (pl.col("ask_px_00") <= pl.col("pal")).cast(pl.Float64) * pl.col("ask_sz_00")
          + (pl.col("ask_px_00") >= pl.col("pal")).cast(pl.Float64) * pl.col("qal"))
         ).alias("e"),
        ((pl.col("bid_px_00") + pl.col("ask_px_00")) / 2.0).alias("mid"),
        # trade-signed volume: classify each TRADE against the PREVAILING
        # (prior-event) quote, not the same-row BBO — MBP-1 levels are post-event.
        pl.when((pl.col("action") == "T") & (pl.col("price") >= pl.col("pal")))
          .then(pl.col("size").cast(pl.Int64))
          .when((pl.col("action") == "T") & (pl.col("price") <= pl.col("pbl")))
          .then(-pl.col("size").cast(pl.Int64))
          .otherwise(0).alias("tsv_e"),
    ])
    bars = (lf.group_by_dynamic("t", every=every, label="left")
            .agg([pl.col("e").sum().alias("ofi"),
                  pl.col("tsv_e").sum().alias("tsv"),
                  pl.col("mid").first().alias("mid_open"),
                  pl.col("mid").last().alias("mid_close")]))
    return bars.collect().to_pandas()


def load_ofi(ticker: str, freq: str = "1min", rebuild: bool = False) -> pd.DataFrame:
    cache = OUT / f"db_ofi_{ticker.upper()}_{freq}.parquet"
    if cache.exists() and not rebuild:
        return pd.read_parquet(cache)
    import numpy as np
    every = _EVERY[freq]
    files = _day_files(ticker)
    frames = []
    for i, f in enumerate(files):
        day = _ofi_one_day(f, every)
        if len(day):
            frames.append(day)
        if (i + 1) % 25 == 0:
            print(f"  ofi {ticker} {freq}: {i+1}/{len(files)}", flush=True)
    pdf = pd.concat(frames, ignore_index=True)
    pdf["date"] = pd.to_datetime(pdf["t"]).dt.date
    pdf["ret"] = np.log(pdf["mid_close"] / pdf["mid_open"])
    pdf = pdf.sort_values("t").reset_index(drop=True)
    pdf.to_parquet(cache, index=False)
    return pdf


if __name__ == "__main__":
    for tk in ("SPY", "QQQ"):
        b = load_ohlcv(tk, "1min")
        print(f"{tk} 1min: {len(b)} bars, {b['date'].nunique()} days, "
              f"{b['date'].min()}..{b['date'].max()}")
