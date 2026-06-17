"""Benchmark: SQLite (current signature_scan path) vs polars/parquet for the
WHALE candidate scan over the full chain cache. Terminal-free; reads the local
cache only. Reproduces the numbers in docs/research/autoresearch/BENCH.md.

    .venv-autoresearch/Scripts/python scripts/bench_polars_vs_sqlite.py

Needs polars + pyarrow in the venv (pip install polars pyarrow). The parquet
export is one-time and cached next to chains.db.
"""
import sys
import time
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = "autoresearch/_artifacts/hist_chains/chains.db"
PARQUET = "autoresearch/_artifacts/hist_chains/option_eod.parquet"

import polars as pl  # noqa: E402
from autoresearch.replay.signature_scan import WHALE_EXCLUDED_TICKERS  # noqa: E402


def export_parquet():
    """One-time sqlite -> parquet export (timed). Returns (seconds, rows, MB)."""
    if Path(PARQUET).exists():
        return None
    t0 = time.time()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pl.read_database(
        "SELECT date, root, expiration, strike, right, volume, close, oi, "
        "delta, spot FROM option_eod", connection=con)
    con.close()
    df.write_parquet(PARQUET)
    return time.time() - t0, df.height, Path(PARQUET).stat().st_size / 1e6


def sqlite_scan():
    """The realistic current approach (signature_scan.scan_day): per-day SQL
    pull + per-row Python filter, mirroring the live WHALE signature gates."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    n = 0
    days = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM option_eod ORDER BY date")]
    for d in days:
        for row in con.execute(
            "SELECT root, volume, close, oi FROM option_eod "
            "WHERE date=? AND COALESCE(volume,0)>0", (d,)):
            root = (row["root"] or "").upper()
            if root in WHALE_EXCLUDED_TICKERS:
                continue
            vol = int(row["volume"] or 0)
            close = float(row["close"] or 0.0)
            if vol * close * 100.0 < 3_000_000:
                continue
            if vol < 500:
                continue
            oi = int(row["oi"] or 0)
            if oi > 0 and vol < oi * 0.30:
                continue
            n += 1
    con.close()
    return n


def polars_scan():
    """Same filter, vectorized over the parquet (lazy scan)."""
    return (pl.scan_parquet(PARQUET)
            .filter(
                (pl.col("volume").fill_null(0) > 0)
                & (~pl.col("root").str.to_uppercase().is_in(list(WHALE_EXCLUDED_TICKERS)))
                & (pl.col("volume").fill_null(0) * pl.col("close").fill_null(0.0) * 100.0 >= 3_000_000)
                & (pl.col("volume").fill_null(0) >= 500)
                & ((pl.col("oi").fill_null(0) == 0)
                   | (pl.col("volume").fill_null(0) >= pl.col("oi").fill_null(0) * 0.30))
            ).select(pl.len()).collect().item())


def main():
    exp = export_parquet()
    if exp:
        print(f"[export] sqlite->parquet: {exp[0]:.1f}s  ({exp[1]:,} rows, {exp[2]:.0f} MB)")
    print("warming caches (OS page cache)...")
    sqlite_scan(); polars_scan()

    t0 = time.time(); n_sql = sqlite_scan(); t_sql = time.time() - t0
    t0 = time.time(); n_pl = polars_scan(); t_pl = time.time() - t0

    print("\nWHALE candidate scan over the full chain cache (identical filter):")
    print(f"  SQLite (current per-row path): {t_sql:6.2f}s  -> {n_sql:,} candidates")
    print(f"  polars (parquet, vectorized) : {t_pl:6.2f}s  -> {n_pl:,} candidates")
    print(f"  speedup: {t_sql/t_pl:.1f}x   (results match: {n_sql == n_pl})")


if __name__ == "__main__":
    main()
