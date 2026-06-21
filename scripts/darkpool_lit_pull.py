"""Pull XNAS.BASIC trades and split into LIT vs DARK (TRF) prints — for the
DP-vs-lit control test (docs/research/DARKPOOL_SR_PREREG.md, control C2).

darkpool_levels.py discarded the lit prints (it filtered to TRF before caching).
To test whether dark-pool levels add anything beyond ordinary volume nodes we need
the LIT prints from the SAME source/window. Publishers in XNAS.BASIC:
  LIT  = 81 (Nasdaq), 88 (Boston), 89 (PSX)
  DARK = 82 (TRF Carteret), 83 (TRF Chicago)        [93 Consolidated -> ignored: double-count]

Caches per symbol:  data/darkpool_cache/{SYM}_LIT_{start}_{end}.parquet
                    data/darkpool_cache/{SYM}_DARK_{start}_{end}.parquet
Re-runs are free (cache hit). Cost ~$7 for the 20-name basket over one week
(estimate first with scripts/databento_darkpool_scout.py / metadata.get_cost).

Run: python scripts/darkpool_lit_pull.py --start 2026-06-15 --end 2026-06-19
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "darkpool_cache"
LIT_PUBS = (81, 88, 89)
DARK_PUBS = (82, 83)
BASKET = ["AAOI", "AEHR", "AMAT", "AMD", "ARM", "ASML", "AVGO", "AXTI", "CIEN",
          "COHR", "GLW", "INTC", "KLAC", "LITE", "LRCX", "MRVL", "MU", "NVDA",
          "POET", "TSM"]


def _key() -> str:
    k = os.getenv("DATABENTO_API_KEY", "")
    if k:
        return k
    for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if ln.strip().startswith("DATABENTO_API_KEY") and "=" in ln:
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main() -> int:
    import pandas as pd
    import databento as db
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--names", default="")
    ap.add_argument("--confirm", action="store_true", help="actually pull (else estimate only)")
    a = ap.parse_args()
    names = [s.strip().upper() for s in a.names.split(",") if s.strip()] or BASKET
    CACHE.mkdir(parents=True, exist_ok=True)
    c = db.Historical(_key())

    cost = c.metadata.get_cost(dataset="XNAS.BASIC", symbols=names, schema="trades",
                               start=a.start, end=a.end, stype_in="raw_symbol")
    print(f"[lit-pull] {len(names)} names {a.start}..{a.end}  est cost ${cost:,.2f}")
    if not a.confirm:
        print("[lit-pull] estimate only — pass --confirm to pull.")
        return 0

    for i, sym in enumerate(names, 1):
        lf = CACHE / f"{sym}_LIT_{a.start}_{a.end}.parquet"
        df_ = CACHE / f"{sym}_DARK_{a.start}_{a.end}.parquet"
        if lf.exists() and df_.exists():
            print(f"[{i}/{len(names)}] {sym}: cache hit")
            continue
        try:
            data = c.timeseries.get_range(dataset="XNAS.BASIC", symbols=[sym],
                                          schema="trades", start=a.start, end=a.end,
                                          stype_in="raw_symbol")
            d = data.to_df()[["ts_event", "price", "size", "publisher_id"]]
            lit = d[d["publisher_id"].isin(LIT_PUBS)][["ts_event", "price", "size"]]
            dark = d[d["publisher_id"].isin(DARK_PUBS)][["ts_event", "price", "size"]]
            lit.to_parquet(lf); dark.to_parquet(df_)
            print(f"[{i}/{len(names)}] {sym}: lit={len(lit):,}  dark={len(dark):,}")
            del d, lit, dark, data
        except Exception as e:
            print(f"[{i}/{len(names)}] {sym}: FAILED {e!r}")
    print("[lit-pull] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
