"""Phase 4 / B3: subscription plan dry-run.

Calls _build_subscription_plan against the current cache state and
prints per-tier spec counts WITHOUT actually subscribing to ThetaData.
Useful for verifying the Tier2 budget bump (#45) is right-sized before
the live worker hits the cap.

Usage:
    python scripts/subscription_plan_dryrun.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import sweep_detector as sd  # noqa: E402
from server.cache import cache  # noqa: E402


async def _amain() -> int:
    # Seed the cache with a minimal fake spot for every root in the
    # subscription tiers so _build_subscription_plan can compute strike
    # radii. Production uses live spots; the dry-run uses placeholders.
    print("Seeding cache with placeholder spots...")
    placeholder_state = {}
    all_roots = (
        list(sd.MVP_WATCHLIST_ROOTS)
        + list(sd.TIER2_THEMATIC_ROOTS)
    )
    # Round-number placeholder spots — actual values don't change the
    # tier-budget math much because TIER2_MAX_RADIUS=60 caps strike count
    # on high-priced names anyway.
    # Realistic spot prices (sampled from 6/4 close). The dryrun is
    # sensitive to spot because radius = floor(spot * otm_pct / step) so
    # higher spots = more strikes per radius. Round to nearest $5.
    REALISTIC_SPOTS = {
        # Index/ETF
        "SPY": 590, "QQQ": 510, "IWM": 215, "DIA": 405,
        "SPX": 5890, "SPXW": 5890, "NDX": 21400, "RUT": 2120, "VIX": 14,
        "SMH": 245, "GLD": 305, "SLV": 36, "USO": 76, "IBIT": 60, "FXI": 50,
        # Mega-caps
        "AAPL": 200, "NVDA": 215, "MSFT": 470, "TSLA": 425, "META": 640,
        "AMZN": 215, "GOOGL": 175, "GOOG": 180, "AMD": 140, "AVGO": 1750,
        "NFLX": 720, "CRM": 280, "ORCL": 180,
        # 4/22 adds
        "UNH": 580, "INTC": 23, "BA": 220, "LLY": 825, "XOM": 115,
        "JPM": 260, "GS": 595, "MS": 130, "BRK.B": 460, "WMT": 95, "BABA": 95,
        # 6/4 adds
        "NEE": 85, "PDD": 135, "NKE": 80,
        # Tier2 thematic — sample
        "CEG": 290, "VST": 165, "EXC": 45, "SO": 90, "DUK": 120,
        "AEP": 100, "INTU": 695, "PYPL": 75,
        "MRVL": 65, "ANET": 95, "GEV": 480, "VRT": 110, "PLTR": 135,
        "DELL": 145, "PANW": 350, "SNDK": 95, "WDC": 85, "STX": 195,
        "MU": 905, "ASML": 770, "LRCX": 105, "KLAC": 980, "AMAT": 200,
        "TSM": 200, "ALAB": 110, "CRDO": 100, "AEHR": 18, "ARM": 165,
        "FSLR": 215, "MSTR": 415, "COIN": 295, "HOOD": 75, "NBIS": 95,
        "AMKR": 22, "TXN": 195, "AAOI": 60, "COHR": 88, "GLW": 60,
        "LITE": 105, "VICR": 75, "NOW": 1050, "SNOW": 220, "DDOG": 145,
        "RKLB": 30, "ASTS": 30, "LMT": 475, "BE": 25, "OKLO": 80,
        "IONQ": 50, "HIMS": 65, "AXTI": 5,
    }
    for root in all_roots:
        spot = float(REALISTIC_SPOTS.get(root, 100))
        await cache.put(root, {
            "actual_spot": spot,
            "_spot": spot,
            "_raw_contracts": {},
        })

    print()
    print("=" * 70)
    print("SUBSCRIPTION PLAN DRY-RUN")
    print("=" * 70)
    specs = await sd._build_subscription_plan()
    print()
    print(f"Total specs: {len(specs):,}")
    print(f"Hard cap (SUBSCRIPTION_MAX_PLANNED): {sd.SUBSCRIPTION_MAX_PLANNED:,}")
    print(f"Target (SUBSCRIPTION_TARGET):        {sd.SUBSCRIPTION_TARGET:,}")
    print(f"Headroom under target:               {sd.SUBSCRIPTION_TARGET - len(specs):,}")
    print()

    # Per-root spec count
    print("=== SPECS BY ROOT (top 25) ===")
    by_root = Counter(s.root for s in specs)
    for root, n in by_root.most_common(25):
        print(f"  {root:8s}  {n:>5d} specs")

    # Check whether 6/4 NEE-class names actually got coverage
    print()
    print("=== 6/4 GAP-FILL COVERAGE ===")
    for tkr in ["NEE", "PDD", "FXI", "NKE", "CEG", "VST", "EXC", "SO",
                "DUK", "AEP", "INTU", "PYPL"]:
        n = by_root.get(tkr, 0)
        flag = "OK" if n > 0 else "MISS"
        print(f"  [{flag}]  {tkr:6s}  {n} specs")

    print()
    if len(specs) >= sd.SUBSCRIPTION_TARGET:
        print(
            f"WARNING: plan hit target {sd.SUBSCRIPTION_TARGET:,} — some "
            f"tiers may have been truncated."
        )
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
