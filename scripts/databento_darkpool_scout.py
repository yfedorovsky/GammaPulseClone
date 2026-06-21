"""FREE Databento metadata scout — before spending a cent on a dark-pool pull.

Answers the two gating questions with metadata-only calls (no data download, $0):
  1. Does our accessible dataset carry off-exchange / FINRA TRF prints at all?
     (If EQUS.MINI is lit-exchange-only, there are ZERO dark-pool prints in it
     and the whole exercise is moot.)
  2. What does the `trades` schema actually COST for the scopes we're weighing
     (1 name / 1 day  vs  bottleneck subset / 30d  vs  full universe / 30d)?

Run: python scripts/databento_darkpool_scout.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _api_key() -> str:
    k = os.getenv("DATABENTO_API_KEY", "")
    if k:
        return k
    try:  # .env fallback
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABENTO_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _universe() -> list[str]:
    try:
        from server import tickers as T
        return T.all_tickers()
    except Exception as e:
        print(f"  (could not import universe: {e!r})")
        return []


BOTTLENECK = ["MU", "AVGO", "MRVL", "NVDA", "AMD", "INTC", "ARM", "TSM", "COHR",
              "LITE", "CIEN", "GLW", "AXTI", "AAOI", "POET", "ASML", "AMAT",
              "LRCX", "KLAC", "AEHR", "VRT", "CEG", "VST", "MSFT", "GOOGL", "AMZN", "META"]

# 30-day window ending before the EQUS.MINI ~24-48h embargo.
WIN_START, WIN_END = "2026-05-18", "2026-06-18"
DAY_START, DAY_END = "2026-06-18", "2026-06-18"
DATASET = "EQUS.MINI"
SCHEMA = "trades"


def main() -> int:
    key = _api_key()
    if not key:
        print("ERROR: DATABENTO_API_KEY not set (env or .env). Cannot scout.")
        return 1
    try:
        import databento as db
    except Exception as e:
        print(f"ERROR: databento package not importable: {e!r}")
        return 1

    client = db.Historical(key)
    print("DATABENTO DARK-POOL SCOUT (metadata only, $0)")
    print("=" * 90)

    # 1) Which datasets can this key access?
    try:
        datasets = client.metadata.list_datasets()
        print(f"\n[1] Accessible datasets ({len(datasets)}):")
        print("    " + ", ".join(datasets))
        eq_candidates = [d for d in datasets if "EQUS" in d or "DBEQ" in d or "XNAS" in d or "EQ" in d.upper()]
        print(f"    US-equities candidates: {eq_candidates}")
    except Exception as e:
        print(f"[1] list_datasets failed: {e!r}")

    # 2) Does EQUS.MINI carry FINRA / TRF / off-exchange publishers?  <-- THE gate
    print(f"\n[2] Publishers in {DATASET} (looking for FINRA/TRF/off-exchange = dark-pool prints):")
    try:
        pubs = client.metadata.list_publishers()
        ds_pubs = [p for p in pubs if str(p.get("dataset", "")) == DATASET]
        if not ds_pubs:
            print(f"    (no publishers listed for {DATASET}; showing any FINRA/TRF across all datasets)")
            ds_pubs = pubs
        finra = [p for p in ds_pubs if any(k in (str(p.get("description", "")) + str(p.get("venue", ""))).upper()
                                           for k in ("FINRA", "TRF", "ADF", "OTC", "OFF"))]
        for p in ds_pubs:
            print(f"    - id={p.get('publisher_id')} venue={p.get('venue')} :: {p.get('description')}")
        print(f"\n    >>> FINRA/TRF/off-exchange publishers found: {len(finra)}")
        for p in finra:
            print(f"        * {p.get('venue')} :: {p.get('description')}")
        if not finra:
            print("        !!! NONE — EQUS.MINI appears lit-exchange-only. NO dark-pool prints here.")
            print("        !!! Would need a consolidated dataset (e.g. full US equities) for TRF blocks.")
    except Exception as e:
        print(f"    list_publishers failed: {e!r}")

    # 3) Data availability / embargo
    print(f"\n[3] {DATASET} dataset range (recency / embargo):")
    try:
        rng = client.metadata.get_dataset_range(dataset=DATASET)
        print(f"    {rng}")
    except Exception as e:
        print(f"    get_dataset_range failed: {e!r}")

    # 4) Real cost estimates for the `trades` schema
    uni = _universe()
    print(f"\n[4] Cost estimates for schema='{SCHEMA}' (USD, metadata.get_cost — FREE to call):")
    scopes = [
        ("MU, 1 day (6/18)", ["MU"], DAY_START, DAY_END),
        (f"bottleneck subset ({len(BOTTLENECK)} names), 30d", BOTTLENECK, WIN_START, WIN_END),
    ]
    if uni:
        scopes.append((f"FULL UNIVERSE ({len(uni)} names), 30d", uni, WIN_START, WIN_END))
    for label, syms, s, e in scopes:
        try:
            cost = client.metadata.get_cost(
                dataset=DATASET, symbols=syms, schema=SCHEMA,
                start=s, end=e, stype_in="raw_symbol", mode="historical-streaming",
            )
            print(f"    {label:42s} -> ${cost:,.2f}")
        except Exception as ex:
            print(f"    {label:42s} -> get_cost failed: {ex!r}")

    print("\n" + "=" * 90)
    print("READ [2] FIRST: if no FINRA/TRF publishers, EQUS.MINI has no dark-pool data — STOP.")
    print("Then weigh [4] cost vs scope before any real pull. Metadata calls above cost $0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
