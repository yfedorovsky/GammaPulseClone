"""Append the most recent missing days of US Equities Mini SPY+QQQ to the
existing Databento cache.

Driven by `cache_status()`: looks at the max-cached date per ticker, asks
the Databento Historical API for everything from (max_date + 1) up to
`--end YYYY-MM-DD`, downloads as DBN to data/databento_equs_mini/, and
runs build_cache_from_dbn_dir to extend the parquet cache.

Cost: US Equities Mini MBP-1 SPY+QQQ for 1 day ≈ $0.20-$0.50 each
based on the original $125 credit covering 6 months × 2 tickers.

Usage:
  python scripts/databento_append_recent.py --end 2026-05-01
  # or, add a specific date range:
  python scripts/databento_append_recent.py --start 2026-04-30 --end 2026-05-01

Requires DATABENTO_API_KEY in .env or environment.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DBN_DIR = ROOT / "data" / "databento_equs_mini"
DBN_DIR.mkdir(parents=True, exist_ok=True)

from scripts.databento_loader import (  # noqa: E402
    cache_status, _read_dbn_to_df, _cache_path,
)

TICKERS = ["SPY", "QQQ"]


def _get_client():
    api_key = os.getenv("DATABENTO_API_KEY")
    if not api_key:
        print("ERROR: DATABENTO_API_KEY not set in .env or environment",
              file=sys.stderr)
        sys.exit(1)
    import databento as db
    return db.Historical(api_key)


def _existing_max_date(ticker: str) -> str | None:
    """Return YYYY-MM-DD of last cached day for ticker, or None if empty."""
    df = cache_status()
    if df.empty:
        return None
    df = df.copy()
    df["date"] = df["path"].astype(str).str.extract(r"(\d{4}-\d{2}-\d{2})")[0]
    sub = df[df["ticker"] == ticker]
    if sub.empty:
        return None
    return sub["date"].max()


def _next_date(d: str) -> str:
    return (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_one_day(client, ticker: str, date: str) -> Path | None:
    """Fetch one day of EQUS.MINI MBP-1 for the ticker via the Historical
    API and write the DBN to disk. Returns the file path on success,
    None on failure."""
    out_path = DBN_DIR / f"{ticker}_{date}_mbp-1.dbn.zst"
    if out_path.exists():
        print(f"  {ticker} {date}: DBN already on disk, skipping fetch")
        return out_path
    start_iso = f"{date}T13:30:00Z"   # 09:30 ET in UTC (no DST handling needed for May)
    end_iso = f"{date}T20:00:00Z"     # 16:00 ET
    print(f"  {ticker} {date}: requesting MBP-1 {start_iso} to {end_iso}",
          flush=True)
    try:
        data = client.timeseries.get_range(
            dataset="EQUS.MINI",
            symbols=[ticker],
            schema="mbp-1",
            start=start_iso,
            end=end_iso,
        )
    except Exception as e:
        print(f"  {ticker} {date}: FETCH FAILED: {type(e).__name__}: {e}",
              flush=True)
        return None
    try:
        data.to_file(str(out_path))
    except Exception as e:
        print(f"  {ticker} {date}: WRITE FAILED: {type(e).__name__}: {e}",
              flush=True)
        return None
    sz_kb = out_path.stat().st_size / 1024
    print(f"  {ticker} {date}: wrote {out_path.name} ({sz_kb:.0f} KB)",
          flush=True)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=None,
                   help="YYYY-MM-DD start date (default: max cached + 1)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD end date (inclusive)")
    p.add_argument("--tickers", nargs="+", default=TICKERS)
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be fetched without calling API")
    args = p.parse_args()

    end_d = datetime.fromisoformat(args.end)

    # Build the per-ticker date list
    work: list[tuple[str, str]] = []
    for ticker in args.tickers:
        if args.start:
            cur = datetime.fromisoformat(args.start)
        else:
            mx = _existing_max_date(ticker)
            if mx is None:
                print(f"  {ticker}: cache empty — use --start explicitly",
                      file=sys.stderr)
                continue
            cur = datetime.fromisoformat(_next_date(mx))
            print(f"  {ticker}: max cached = {mx}, starting at {cur.strftime('%Y-%m-%d')}",
                  flush=True)
        while cur <= end_d:
            # Skip weekends (Databento bills weekend days too if requested)
            if cur.weekday() < 5:
                work.append((ticker, cur.strftime("%Y-%m-%d")))
            cur += timedelta(days=1)

    if not work:
        print("Nothing to fetch — cache is already up to date.")
        return 0

    print(f"\nWill fetch {len(work)} (ticker, date) pairs:")
    for t, d in work:
        print(f"  {t} {d}")
    print()

    if args.dry_run:
        print("(dry run — no API calls made)")
        return 0

    client = _get_client()
    fetched: list[Path] = []
    for ticker, date in work:
        p = fetch_one_day(client, ticker, date)
        if p is not None:
            fetched.append(p)

    if not fetched:
        print("\nNo files fetched. Exiting without cache rebuild.")
        return 1

    # Process ONLY the new files (not all 250+ in DBN_DIR) — the loader's
    # build_cache_from_dbn_dir reads every DBN it sees, which on a populated
    # cache directory is wastefully slow and can OOM.
    print(f"\nFetched {len(fetched)} DBN files. Building parquet cache "
          f"for new files only...", flush=True)
    import pandas as pd
    n_written = 0
    for f in fetched:
        print(f"  [loader] reading {f.name}", flush=True)
        df = _read_dbn_to_df(f)
        if df.empty:
            print(f"    skip: empty dataframe", flush=True)
            continue
        if "ts_event" in df.columns:
            df["_date"] = pd.to_datetime(df["ts_event"], utc=True) \
                .dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
        else:
            df["_date"] = "unknown"
        if "symbol" not in df.columns:
            print(f"    skip: no 'symbol' column", flush=True)
            continue
        for (ticker, date), sub in df.groupby(["symbol", "_date"]):
            cpath = _cache_path(ticker, date)
            if cpath.exists():
                print(f"    -> {ticker} {date}: parquet already exists, skipping",
                      flush=True)
                continue
            cpath.parent.mkdir(parents=True, exist_ok=True)
            sub.drop(columns=["_date"]).to_parquet(cpath, index=False)
            n_written += 1
            print(f"    -> {ticker} {date}: wrote {len(sub):,} rows -> "
                  f"{cpath.relative_to(ROOT)}", flush=True)
    print(f"\nWrote {n_written} new parquet files", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
