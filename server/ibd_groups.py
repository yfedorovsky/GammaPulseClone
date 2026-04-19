"""IBD-style industry group rotation layer.

Source: Investor's Business Daily MarketSurge industry group rankings,
weekend review dated 2026-04-19. Top 25 groups by YTD performance with
member tickers from the top-3 groups' component lists.

Purpose:
  - Expose `get_ibd_group_info(ticker)` for the worker to annotate state
  - SCANNER tab shows industry group rank + group YTD% per ticker
  - swing_scanner detects group-level confluence (≥3 members qualifying)

Why a static table instead of live IBD scrape:
  - MarketSurge has no public API
  - Weekly manual paste is low-overhead and matches how IBD analysts use it
  - Group membership is stable week-over-week even when ranks shift

Update cadence: refresh this table each weekend off the MarketSurge list.
The `TABLE_AS_OF` date makes staleness legible.
"""
from __future__ import annotations

from typing import Any


TABLE_AS_OF = "2026-04-19"

# Top industry groups with YTD % and member tickers.
# Only groups where we have ≥2 tickers in the GammaPulse universe are listed.
# `members` lists tickers from strongest → weakest by YTD % within group.
IBD_GROUPS: list[dict[str, Any]] = [
    {
        "rank": 1,
        "name": "Telecom-Fiber Optics",
        "ytd_pct": 137.0,
        "members": ["AAOI", "VIAV", "LITE", "CIEN"],
    },
    {
        "rank": 2,
        "name": "Computer-Data Storage",
        "ytd_pct": 120.1,
        "members": ["SNDK", "WDC", "STX", "MU"],
    },
    {
        "rank": 3,
        "name": "Elec-Semiconductor Equipment",
        "ytd_pct": 64.3,
        "members": [
            "AEHR", "ICHR", "UCTT", "FORM", "TER", "MKSI", "KLIC",
            "ONTO", "NVMI", "AMAT", "LRCX", "KLAC", "ASML", "ENTG",
            "PLAB", "AESI",
        ],
    },
    {
        "rank": 6,
        "name": "Electronic-Parts",
        "ytd_pct": 53.0,
        # Not pulled from screenshot directly — conservative universe subset
        "members": ["GLW", "ANET", "VRT"],
    },
    {
        "rank": 7,
        "name": "Elec-Semiconductor Mfg",
        "ytd_pct": 44.6,
        "members": ["NVDA", "AVGO", "AMD", "TSM", "MRVL", "INTC", "SMH"],
    },
    {
        "rank": 9,
        "name": "Elec-Scientific/Mrsng",
        "ytd_pct": 42.2,
        "members": ["AXTI", "COHR"],  # photonics/measurement
    },
    {
        "rank": 13,
        "name": "Elec-Contract Mfg",
        "ytd_pct": 40.3,
        "members": [],  # no core universe overlap
    },
    {
        "rank": 19,
        "name": "Telecom Svcs-Wireless",
        "ytd_pct": 16.3,
        "members": [],
    },
    {
        "rank": 15,
        "name": "Bldg-Heavy Construction",
        "ytd_pct": 41.6,
        "members": ["ROAD"],  # Construction Partners — Sector Leader
    },
    {
        "rank": 20,
        "name": "Bldg-A/C & Heating",
        "ytd_pct": 35.1,
        "members": ["FIX"],  # Comfort Systems — Sector Leader
    },
    {
        "rank": 21,
        "name": "Mining-Gold/Silver",
        "ytd_pct": 25.0,
        # First 5 are all IBD Sector Leaders; PAAS is primary silver miner.
        "members": ["AGI", "WPM", "KGC", "GFI", "TFPM", "PAAS"],
    },
    {
        "rank": 25,
        "name": "Telecom-Infrastructure",
        "ytd_pct": 61.8,
        "members": ["ASTS", "RKLB"],  # space/satellite adjacent
    },
    # ── Thematic overlays (GammaPulse additions, not IBD official top-25) ──
    # Ranks 90+ indicate "not on the IBD paper but tracked for rotation context".
    # Scanner UI shows these as gray (rank > 5), so they're clearly differentiated
    # from real IBD top-3 (green) / top-5 (yellow) groups. They still feed the
    # GROUP_STRENGTH confluence logic if ≥3 members qualify, but won't trigger
    # the top-5 bull tailwind badge.
    {
        "rank": 99,
        "name": "Quantum Computing [thematic]",
        "ytd_pct": 0.0,  # unknown — not an IBD-reported group
        "members": ["IONQ", "RGTI", "QBTS"],  # Apr 19: IONQ qubits progress catalyst
    },
    {
        "rank": 98,
        "name": "Neocloud / AI Compute Hosting [thematic]",
        "ytd_pct": 0.0,
        # Neoclouds gaining ground on hyperscalers through 2027 per Diligence
        # Stack weekend synthesis. Different from IBD #2 Data Storage (memory)
        # and from hyperscaler software plays (MSFT/AMZN/GOOGL).
        "members": ["IREN", "CRWV", "NBIS", "APLD"],
    },
]


# ── Reverse index: ticker → group info ─────────────────────────────────

def _build_ticker_index() -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for g in IBD_GROUPS:
        for i, ticker in enumerate(g["members"]):
            # Don't overwrite if a ticker appears in multiple groups
            # (shouldn't happen with IBD — each ticker has exactly one group)
            if ticker in idx:
                continue
            idx[ticker] = {
                "rank": g["rank"],
                "name": g["name"],
                "ytd_pct": g["ytd_pct"],
                "leader_rank_in_group": i + 1,  # 1 = strongest, 2 = second, etc.
                "group_size": len(g["members"]),
            }
    return idx


_TICKER_INDEX = _build_ticker_index()


def get_ibd_group_info(ticker: str) -> dict[str, Any] | None:
    """Return IBD group info for a ticker, or None if not mapped.

    Return shape:
        {
            "rank": int,           # 1-25, 1 = strongest group YTD
            "name": str,           # "Telecom-Fiber Optics"
            "ytd_pct": float,      # group YTD % change
            "leader_rank_in_group": int,  # 1 = strongest member, 2 = 2nd, etc.
            "group_size": int,     # total members in group
        }

    Used by worker.py to annotate ticker state with `_ibd_*` fields.
    Used by swing_scanner.py to compute GROUP_STRENGTH confluence.
    """
    return _TICKER_INDEX.get(ticker.upper())


def get_group_members(rank: int) -> list[str]:
    """Return members of the group with the given rank, or empty list."""
    for g in IBD_GROUPS:
        if g["rank"] == rank:
            return list(g["members"])
    return []


def top_n_group_members(n: int = 3) -> set[str]:
    """Union of member tickers across the top-N groups by rank."""
    members: set[str] = set()
    for g in sorted(IBD_GROUPS, key=lambda x: x["rank"])[:n]:
        members.update(g["members"])
    return members


def summary() -> dict[str, Any]:
    """Diagnostic summary — shape of the table."""
    return {
        "table_as_of": TABLE_AS_OF,
        "n_groups": len(IBD_GROUPS),
        "n_tickers_mapped": len(_TICKER_INDEX),
        "top_3_groups": [
            {"rank": g["rank"], "name": g["name"], "ytd_pct": g["ytd_pct"],
             "members": g["members"]}
            for g in sorted(IBD_GROUPS, key=lambda x: x["rank"])[:3]
        ],
    }
