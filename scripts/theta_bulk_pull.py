"""Bulk ThetaData option-history puller for backtesting (Options PRO: tick-level to 2012).

Pulls FULL chains (all strikes, both rights) per expiration over a date window and writes
partitioned parquet, so downstream backtests query it LAZILY (pl.scan_parquet) and never
hold millions of rows in RAM. Uses the polars-backed client (thetadata_lib.get_polars_client)
— the right tool for the millions-of-rows regime; the pandas client stays for the small-frame
live paths.

SCOPING MODEL: for each root, take expirations E with start <= E <= end (contracts that were
live & expired inside the window — the 0DTE/weekly/monthly backtest set). For each E, pull its
life within the window: [max(start, E - lookback_days), min(end, E)], split into <= chunk_days
requests (the API caps multi-day requests at ~1 month and requires a specified expiration).

Partition layout (Hive-style, so pl.scan_parquet gives you root/exp/kind columns for free):
    {out}/kind={kind}/root={root}/exp={E}/{d0}_{d1}.parquet

Resumable (skips partitions already on disk) + a manifest.jsonl. Sequential (Pro allows 8
concurrent, but sequential is simplest and avoids hammering; parallelize later if needed).

    # plan first — see how many partitions / how big before committing
    python scripts/theta_bulk_pull.py --roots SPY QQQ --start 2026-06-01 --end 2026-06-27 --kind ohlc --dry-run

    # minute OHLC (compact, great for entry/exit sim)
    python scripts/theta_bulk_pull.py --roots SPY --start 2026-06-22 --end 2026-06-27 --kind ohlc --interval 1m

    # tick trades+NBBO (the big one — chunk small)
    python scripts/theta_bulk_pull.py --roots SPY --start 2026-06-26 --end 2026-06-27 --kind trade_quote --chunk-days 1

    # lazy read for a backtest
    python scripts/theta_bulk_pull.py --scan data/theta_hist --kind ohlc

kind: ohlc | quote | trade_quote. ASCII-only output.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.thetadata_lib import get_polars_client  # noqa: E402


def _expirations_in(client, root, start, end):
    df = client.option_list_expirations(symbol=root)
    col = "expiration" if "expiration" in df.columns else df.columns[-1]
    vals = df.get_column(col).to_list() if hasattr(df, "get_column") else df[col].tolist()
    out = []
    for v in vals:
        try:
            d = _dt.date.fromisoformat(str(v)[:10])
        except ValueError:
            continue
        if start <= d <= end:
            out.append(d)
    return sorted(set(out))


def _chunks(d0, d1, size):
    cur = d0
    while cur <= d1:
        c_end = min(cur + _dt.timedelta(days=size - 1), d1)
        yield cur, c_end
        cur = c_end + _dt.timedelta(days=1)


def _pull(client, kind, root, exp, d0, d1, interval, strike_range=0):
    # strike_range=n -> only ATM +/- n strikes (2n+1), vs the whole (wide) chain.
    # Essential for SPX-class roots where the full chain is ~800 strikes.
    sr = strike_range if strike_range else None
    if kind == "ohlc":
        return client.option_history_ohlc(
            symbol=root, expiration=exp, strike="*", right="both",
            interval=interval, start_date=d0, end_date=d1, strike_range=sr)
    if kind == "quote":
        return client.option_history_quote(
            symbol=root, expiration=exp, strike="*", right="both",
            interval=interval, start_date=d0, end_date=d1, strike_range=sr)
    if kind == "trade_quote":
        return client.option_history_trade_quote(
            symbol=root, expiration=exp, strike="*", right="both",
            start_date=d0, end_date=d1, strike_range=sr)
    raise SystemExit(f"unknown kind: {kind}")


def scan(out, kind, root=None):
    """Lazy frame over the pulled store — the backtest entry point.
    Example: scan('data/theta_hist','ohlc').filter(pl.col('root')=='SPY').collect(engine='streaming')
    """
    import polars as pl
    base = Path(out) / f"kind={kind}"
    if root:
        pat = str(base / f"root={root}" / "**" / "*.parquet")
    else:
        pat = str(base / "**" / "*.parquet")
    return pl.scan_parquet(pat)


def _do_scan(out, kind, root):
    lf = scan(out, kind, root)
    n = lf.select(__import__("polars").len()).collect().item()
    print(f"scan {out}/kind={kind}" + (f"/root={root}" if root else "")
          + f"  ->  {n:,} rows across the store")
    print("  columns:", lf.collect_schema().names())
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--kind", default="ohlc", choices=["ohlc", "quote", "trade_quote"])
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--lookback-days", type=int, default=45,
                    help="per-expiration life window to pull, ending at expiry")
    ap.add_argument("--chunk-days", type=int, default=28, help="<= ~1mo API cap")
    ap.add_argument("--strike-range", type=int, default=0,
                    help="only ATM +/- N strikes (2N+1); 0 = whole chain. Use for SPX-class roots.")
    ap.add_argument("--out", default="data/theta_hist")
    ap.add_argument("--max-expirations", type=int, default=0, help="0 = all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan", metavar="OUT_DIR", help="lazy-count the store and exit")
    a = ap.parse_args()

    if a.scan:
        return _do_scan(a.scan, a.kind, a.roots[0] if a.roots else None)

    if not (a.roots and a.start and a.end):
        ap.error("--roots, --start, --end are required (unless --scan)")

    client = get_polars_client()
    if client is None:
        raise SystemExit("ThetaData polars client unavailable — check THETADATA_API_KEY")

    start = _dt.date.fromisoformat(a.start)
    end = _dt.date.fromisoformat(a.end)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    man = out / "manifest.jsonl"

    print(f"BULK PULL  kind={a.kind} interval={a.interval} window=[{start}..{end}] "
          f"lookback={a.lookback_days}d chunk={a.chunk_days}d out={out}")
    tot_rows = tot_bytes = files = 0
    t0 = time.time()
    for root in a.roots:
        exps = _expirations_in(client, root, start, end)
        if a.max_expirations:
            exps = exps[:a.max_expirations]
        print(f"\n{root}: {len(exps)} expirations in window")
        for exp in exps:
            d0 = max(start, exp - _dt.timedelta(days=a.lookback_days))
            d1 = min(end, exp)
            for c0, c1 in _chunks(d0, d1, a.chunk_days):
                part = (out / f"kind={a.kind}" / f"root={root}"
                        / f"exp={exp.isoformat()}" / f"{c0}_{c1}.parquet")
                if part.exists():
                    continue
                if a.dry_run:
                    print(f"  [plan] {root} exp={exp} {c0}..{c1}")
                    files += 1
                    continue
                try:
                    ts = time.time()
                    df = _pull(client, a.kind, root, exp, c0, c1, a.interval, a.strike_range)
                    secs = time.time() - ts
                except Exception as e:
                    print(f"  ERR {root} {exp} {c0}..{c1}: {repr(e)[:150]}")
                    continue
                if df is None or df.height == 0:
                    continue
                part.parent.mkdir(parents=True, exist_ok=True)
                df.write_parquet(part, compression="zstd")
                b = part.stat().st_size
                tot_rows += df.height
                tot_bytes += b
                files += 1
                with man.open("a") as f:
                    f.write(json.dumps({
                        "root": root, "exp": exp.isoformat(), "kind": a.kind,
                        "d0": c0.isoformat(), "d1": c1.isoformat(),
                        "rows": df.height, "bytes": b, "secs": round(secs, 1)}) + "\n")
                print(f"  {root} exp={exp} {c0}..{c1}: {df.height:>8,} rows "
                      f"{b/1e6:>6.1f}MB {secs:>4.1f}s")

    print("\n" + "-" * 60)
    if a.dry_run:
        print(f"DRY RUN: {files} partitions planned (nothing written)")
    else:
        print(f"DONE: {files} files, {tot_rows:,} rows, {tot_bytes/1e6:.1f} MB, "
              f"{time.time()-t0:.0f}s -> {out}")
        print(f'Lazy read: python scripts/theta_bulk_pull.py --scan {out} --kind {a.kind}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
