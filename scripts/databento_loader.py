"""DBN file loader + parquet cache for Databento US Equities Mini.

Reads `*.dbn.zst` files from the Databento download (one per day per
instrument, given the request was split by Day + multi-instrument), caches
to a local parquet store keyed by (date, ticker), and exposes a query
function that returns a pandas DataFrame for a given (ticker, date,
time_window).

Schema mapping for MBP-1 on EQUS.MINI:
  - Each row = one event (trade or quote update at top of book)
  - Action: 'T' = trade; 'A' = add (quote update at the BBO); others
  - For each row we get: ts_event, ts_recv, action, side, price, size,
    bid_px_00, ask_px_00, bid_sz_00, ask_sz_00 (the BBO at this event)

This is the foundation for `lee_ready_classifier.py` and `gate8_audit.py`.

Usage (after Databento download completes):
  python scripts/databento_loader.py --dbn-dir <path> --build-cache
  python -c "from scripts.databento_loader import load_window; \
             df = load_window('SPY', '2026-04-21', '10:23', '10:53'); \
             print(df.head())"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterator

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Default location where Databento downloads land. Adjust if needed.
DEFAULT_DBN_DIR = ROOT / "data" / "databento_equs_mini"
CACHE_DIR = ROOT / "data" / "databento_cache"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DBN_DIR.mkdir(parents=True, exist_ok=True)


def _list_dbn_files(dbn_dir: Path) -> list[Path]:
    """Recursively find all *.dbn.zst files under dbn_dir."""
    return sorted(dbn_dir.rglob("*.dbn.zst"))


def _read_dbn_to_df(path: Path) -> pd.DataFrame:
    """Read one .dbn.zst file into a pandas DataFrame.

    Databento's DBNStore.to_df() handles the zstd decompression and
    type conversions internally. We do minimal post-processing here to
    keep the cache representation close to the raw feed.
    """
    from databento import DBNStore
    store = DBNStore.from_file(str(path))
    df = store.to_df()
    if df.empty:
        return df
    # DBNStore.to_df() returns ts_recv as the index by default — promote
    # it to a regular column so downstream code can treat it uniformly.
    if df.index.name == "ts_recv":
        df = df.reset_index()
    # Normalize timestamp columns to int64 nanoseconds for space-efficient
    # comparisons. ts_event = matching-engine timestamp; ts_recv = capture
    # server timestamp.
    if "ts_event" in df.columns:
        df["ts_event_ns"] = pd.to_datetime(df["ts_event"], utc=True) \
            .astype("int64")
    if "ts_recv" in df.columns:
        df["ts_recv_ns"] = pd.to_datetime(df["ts_recv"], utc=True) \
            .astype("int64")
    # Standardize symbol column name (sometimes 'symbol', sometimes
    # 'raw_symbol' depending on schema/version).
    if "symbol" not in df.columns and "raw_symbol" in df.columns:
        df["symbol"] = df["raw_symbol"]
    return df


def _cache_path(ticker: str, date: str) -> Path:
    """Cache layout: data/databento_cache/<TICKER>/<YYYY-MM-DD>.parquet"""
    safe_ticker = ticker.upper()
    return CACHE_DIR / safe_ticker / f"{date}.parquet"


def build_cache_from_dbn_dir(
    dbn_dir: Path = DEFAULT_DBN_DIR, force: bool = False,
) -> dict[str, int]:
    """Walk dbn_dir, read each .dbn.zst, split by (ticker, date), write
    parquet cache files. Idempotent: skips dates already cached unless
    force=True.

    Databento's "split by Day" + multi-instrument request typically
    produces one .dbn.zst file per date containing all requested
    instruments. We split by symbol after loading each file.
    """
    files = _list_dbn_files(dbn_dir)
    if not files:
        print(f"  [loader] no *.dbn.zst files in {dbn_dir}", flush=True)
        return {"files_seen": 0, "rows_cached": 0, "cache_files_written": 0}

    rows_total = 0
    files_written = 0
    for f in files:
        print(f"  [loader] reading {f.name}", flush=True)
        df = _read_dbn_to_df(f)
        if df.empty:
            continue
        # Determine the date(s) covered by this file. With "split by Day"
        # there should be a single date; check anyway.
        if "ts_event" in df.columns:
            df["_date"] = pd.to_datetime(df["ts_event"], utc=True) \
                .dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
        else:
            df["_date"] = "unknown"
        if "symbol" not in df.columns:
            print(f"    skip: no 'symbol' column in {f.name}", flush=True)
            continue
        for (ticker, date), sub in df.groupby(["symbol", "_date"]):
            cpath = _cache_path(ticker, date)
            if cpath.exists() and not force:
                continue
            cpath.parent.mkdir(parents=True, exist_ok=True)
            sub.drop(columns=["_date"]).to_parquet(cpath, index=False)
            files_written += 1
            rows_total += len(sub)
            print(f"    -> {ticker} {date}: {len(sub):,} rows", flush=True)
    return {
        "files_seen": len(files),
        "rows_cached": rows_total,
        "cache_files_written": files_written,
    }


def cache_status() -> pd.DataFrame:
    """Return a DataFrame of (ticker, date, rows) for everything cached."""
    rows = []
    for ticker_dir in CACHE_DIR.iterdir():
        if not ticker_dir.is_dir():
            continue
        for f in ticker_dir.glob("*.parquet"):
            date = f.stem
            try:
                size = pd.read_parquet(f, columns=["ts_event_ns"]) \
                    .shape[0] if f.exists() else 0
            except Exception:
                size = 0
            rows.append({"ticker": ticker_dir.name, "date": date,
                         "rows": size, "path": str(f)})
    return pd.DataFrame(rows).sort_values(["ticker", "date"]) \
        .reset_index(drop=True) if rows else pd.DataFrame()


def load_window(
    ticker: str, date: str,
    start_hhmm: str | None = None, end_hhmm: str | None = None,
    actions: list[str] | None = None,
) -> pd.DataFrame:
    """Return all MBP-1 events for (ticker, date) within the given
    HH:MM window (ET). If actions specified, filter to those event types.

    Common usage:
      - all events in 10-minute window: load_window('SPY', '2026-04-21',
                                                    '10:48', '10:58')
      - just trades: load_window(..., actions=['T'])
      - just quote updates: load_window(..., actions=['A'])
    """
    cpath = _cache_path(ticker, date)
    if not cpath.exists():
        raise FileNotFoundError(
            f"No cache for {ticker} {date} — run build_cache_from_dbn_dir() "
            f"first, or check {cpath}"
        )
    df = pd.read_parquet(cpath)
    if df.empty:
        return df
    # Time filter (assumes ts_event is UTC; convert to ET for hhmm match)
    if start_hhmm or end_hhmm:
        ts_et = pd.to_datetime(df["ts_event"], utc=True) \
            .dt.tz_convert("America/New_York")
        df = df.assign(_hhmm=ts_et.dt.strftime("%H:%M"))
        if start_hhmm:
            df = df[df["_hhmm"] >= start_hhmm]
        if end_hhmm:
            df = df[df["_hhmm"] <= end_hhmm]
        df = df.drop(columns=["_hhmm"])
    if actions:
        df = df[df["action"].isin(actions)]
    return df.reset_index(drop=True)


def get_trades(ticker: str, date: str,
               start_hhmm: str | None = None,
               end_hhmm: str | None = None) -> pd.DataFrame:
    """Convenience: return only trade events with matched BBO context.

    Each row has ts_event, price, size, side (aggressor side per Databento
    classification), bid_px_00, ask_px_00, bid_sz_00, ask_sz_00.
    """
    return load_window(ticker, date, start_hhmm, end_hhmm, actions=["T"])


def get_quotes(ticker: str, date: str,
               start_hhmm: str | None = None,
               end_hhmm: str | None = None) -> pd.DataFrame:
    """Convenience: return only quote-update events at the BBO."""
    return load_window(ticker, date, start_hhmm, end_hhmm,
                       actions=["A", "C", "M", "R"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbn-dir", default=str(DEFAULT_DBN_DIR),
                    help="Directory containing Databento .dbn.zst files")
    ap.add_argument("--build-cache", action="store_true",
                    help="Build/refresh the parquet cache from DBN files")
    ap.add_argument("--force", action="store_true",
                    help="Re-cache even if parquet exists")
    ap.add_argument("--status", action="store_true",
                    help="Print cache status (tickers × dates × rows)")
    ap.add_argument("--peek", nargs=2, metavar=("TICKER", "DATE"),
                    help="Print head/tail of one cached (ticker, date)")
    args = ap.parse_args()

    if args.build_cache:
        result = build_cache_from_dbn_dir(Path(args.dbn_dir), force=args.force)
        print(f"\n[loader] {result}", flush=True)

    if args.status:
        s = cache_status()
        if s.empty:
            print("[loader] cache is empty")
        else:
            by_ticker = s.groupby("ticker").agg(
                days=("date", "nunique"), rows=("rows", "sum"),
            )
            print(by_ticker.to_string())
            print(f"\nTotal: {s['rows'].sum():,} rows across "
                  f"{s['ticker'].nunique()} tickers, "
                  f"{s['date'].nunique()} unique dates")

    if args.peek:
        ticker, date = args.peek
        df = load_window(ticker, date)
        print(f"\n{ticker} {date}: {len(df):,} rows")
        print("\nColumns:", list(df.columns))
        print("\nHead:")
        print(df.head(3).to_string())
        print("\nAction counts:")
        if "action" in df.columns:
            print(df["action"].value_counts().head(10).to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
