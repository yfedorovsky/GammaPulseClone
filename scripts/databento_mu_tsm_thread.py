"""One-shot Databento pull for the MU/TSM thread fact-check.

Pulls EQUS.MINI OHLCV bars to firm up these thread claims:
  - 3/31/26 MU + TSM intraday (where the alleged ASK sweeps hit)
  - 5/8/26 MU intraday (the parabolic +15.5% / $14.5B notional day)
  - April 2026 MU daily (low + month-end close)
  - 30 trading days of MU daily volume preceding 5/8 (for the "34x avg" claim)

Outputs CSVs to docs/research/thread_databento/. No caching, no parquet
build — just files for me to read back and tighten the tweets.

Usage:
  python scripts/databento_mu_tsm_thread.py
  python scripts/databento_mu_tsm_thread.py --dry-run    # cost estimate only

Cost: 5 small queries on EQUS.MINI ohlcv schemas. Estimated <$1.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "docs" / "research" / "thread_databento"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _client():
    api_key = os.getenv("DATABENTO_API_KEY")
    if not api_key:
        sys.exit("ERROR: DATABENTO_API_KEY not set")
    import databento as db
    return db.Historical(api_key)


def pull(client, label, schema, symbols, start, end, *, dry_run=False):
    out_path = OUT_DIR / f"{label}.csv"
    if dry_run:
        try:
            cost = client.metadata.get_cost(
                dataset="EQUS.MINI",
                symbols=symbols,
                schema=schema,
                start=start,
                end=end,
            )
            print(f"  {label}: estimated cost = ${cost:.4f}")
        except Exception as e:
            print(f"  {label}: cost estimate failed: {e}")
        return
    print(f"  {label}: fetching {schema} {symbols} {start} -> {end}", flush=True)
    data = client.timeseries.get_range(
        dataset="EQUS.MINI",
        symbols=symbols,
        schema=schema,
        start=start,
        end=end,
        stype_in="raw_symbol",
    )
    df = data.to_df()
    df.to_csv(out_path)
    print(f"  {label}: wrote {len(df)} rows -> {out_path.name}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="show estimated cost without fetching")
    args = p.parse_args()

    client = _client()
    dry = args.dry_run

    # 1+2: MU + TSM intraday on 3/31/26 (the alleged whale-sweep day)
    pull(client, "mu_tsm_2026-03-31_1m", "ohlcv-1m",
         ["MU", "TSM"],
         "2026-03-31T13:30:00Z", "2026-03-31T20:00:00Z",
         dry_run=dry)

    # 3: MU intraday on 5/8 — SKIPPED. EQUS.MINI is embargoed 24-48h after
    # the trading day without a live license. Re-run separately on 5/9 or 5/10
    # if needed. We can cite Perplexity's $746.81 close for T6 anyway.

    # 4: MU daily for April 2026 (low + month-end close)
    pull(client, "mu_2026-04_daily", "ohlcv-1d",
         ["MU"],
         "2026-04-01", "2026-04-30",
         dry_run=dry)

    # 5: MU daily for 30 trading days preceding 5/8 (for "34x avg vol" denom).
    # End at 5/7 (last day available without live license) — gives us the
    # 30d-rolling-avg denominator. The 5/8 numerator comes from Perplexity.
    pull(client, "mu_30d_pre_2026-05-08_daily", "ohlcv-1d",
         ["MU"],
         "2026-03-25", "2026-05-07",
         dry_run=dry)

    print(f"\nDone. Files in: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
