"""Dark-pool price LEVELS from real off-exchange (FINRA/Nasdaq TRF) prints.

Uses Databento XNAS.BASIC (Nasdaq Basic + NLS Plus), which DOES carry the FINRA/Nasdaq
TRF off-exchange prints (publishers FINN id=82 Carteret, FINC id=83 Chicago) WITH price
and size. Filters to those off-exchange publishers, then builds a price-volume profile —
the high-volume price nodes ARE the "dark pool levels" people talk about (and that FINRA's
ATS weekly tape can't give you, since it has no price).

Pay-per-query on the existing Databento key (~$0.27/symbol/day). Caches to
data/darkpool_cache/ so re-runs are free.

CAVEAT: XNAS.BASIC = Nasdaq TRF only (Carteret + Chicago). The smaller NYSE-TRF slice of
off-exchange is not included (for Nasdaq-listed names like MU it captures ~all of it).
And: "a price node = support/resistance" is an UNTESTED claim — this gives you the levels,
not proof they predict. NIA.

Run:
  python scripts/darkpool_levels.py MU --start 2026-06-18 --end 2026-06-19
  python scripts/darkpool_levels.py MU --start 2026-06-04 --end 2026-06-19   # multi-day
  python scripts/darkpool_levels.py MU --start 2026-06-18 --end 2026-06-19 --block 1000000
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "darkpool_cache"
TRF_PUBLISHERS = (82, 83)  # FINN = FINRA/Nasdaq TRF Carteret, FINC = TRF Chicago


def _key() -> str:
    k = os.getenv("DATABENTO_API_KEY", "")
    if k:
        return k
    try:
        for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("DATABENTO_API_KEY") and "=" in ln:
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def load(symbol: str, start: str, end: str):
    """Off-exchange (TRF) prints for symbol over [start, end). Cached parquet."""
    import pandas as pd
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / f"{symbol}_{start}_{end}.parquet"
    if cf.exists():
        print(f"[dp] cache hit {cf.name}")
        return pd.read_parquet(cf)
    import databento as db
    print(f"[dp] pulling XNAS.BASIC {symbol} {start}..{end} (~${0.27*max(1,(pd.Timestamp(end)-pd.Timestamp(start)).days):.2f})")
    c = db.Historical(_key())
    data = c.timeseries.get_range(dataset="XNAS.BASIC", symbols=[symbol], schema="trades",
                                  start=start, end=end, stype_in="raw_symbol")
    df = data.to_df()
    df = df[df["publisher_id"].isin(TRF_PUBLISHERS)][["ts_event", "price", "size"]].copy()
    df.to_parquet(cf)
    print(f"[dp] cached {len(df)} off-exchange prints -> {cf.name}")
    return df


def main() -> int:
    import pandas as pd
    ap = argparse.ArgumentParser(description="Dark-pool price levels from TRF prints")
    ap.add_argument("symbol")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--bucket", type=float, default=0.0, help="price bucket $ (0=auto ~0.1pct of price)")
    ap.add_argument("--block", type=float, default=1_000_000, help="block notional floor $ (default 1M)")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    df = load(args.symbol, args.start, args.end)
    if df.empty:
        print("No off-exchange prints in window.")
        return 0
    df["notional"] = df["price"] * df["size"]
    tot_sh, tot_no = df["size"].sum(), df["notional"].sum()
    px = df["price"].median()
    bucket = args.bucket or round(max(px * 0.001, 0.01), 2)

    df["lvl"] = (df["price"] / bucket).round() * bucket
    prof = (df.groupby("lvl").agg(shares=("size", "sum"), prints=("size", "count"),
                                  notional=("notional", "sum"))
            .sort_values("shares", ascending=False))

    print(f"\nDARK-POOL LEVELS — {args.symbol}  {args.start}..{args.end}  (FINRA/Nasdaq TRF off-exchange; NIA)")
    print("=" * 84)
    print(f"off-exchange prints={len(df):,}  shares={tot_sh/1e6:.1f}M  notional=${tot_no/1e9:.2f}B  "
          f"bucket=${bucket:g}  px~${px:,.2f}")
    print(f"\nTOP {args.top} DARK-POOL PRICE LEVELS (by off-exchange share volume):")
    print(f"  {'PRICE':>10s} {'shares':>9s} {'%ofOE':>6s} {'prints':>8s} {'notional':>9s}")
    for lvl, r in prof.head(args.top).iterrows():
        pct = r["shares"] / tot_sh * 100
        bar = "#" * int(pct / 2)
        print(f"  ${lvl:>9,.2f} {r['shares']/1e6:>7.2f}M {pct:>5.1f}% {int(r['prints']):>8,} "
              f"${r['notional']/1e6:>7.0f}M {bar}")

    blocks = df[df["notional"] >= args.block].sort_values("notional", ascending=False)
    print(f"\nBLOCK PRINTS (>= ${args.block/1e6:g}M notional): {len(blocks)} prints, "
          f"${blocks['notional'].sum()/1e9:.2f}B")
    for _, r in blocks.head(8).iterrows():
        print(f"  {str(r['ts_event'])[:19]}  ${r['price']:>9,.2f}  {int(r['size']):>8,} sh  "
              f"${r['notional']/1e6:>6.1f}M")
    print("-" * 84)
    print("Levels = where the most off-exchange volume printed. Whether they act as S/R is")
    print("UNTESTED — this is the data, not a validated edge. Nasdaq TRF only (NYSE-TRF excl). NIA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
