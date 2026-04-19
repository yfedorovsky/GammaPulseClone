"""IBD Sector Leaders list — Bill O'Neil's curated top-16.

Different from `ibd_groups.py`:
  - ibd_groups  = every ticker has a group; rank tells rotation context
  - this module = binary list of ≤16 stocks that pass the FULL proprietary
    CAN-SLIM screen. If a stock's not here, it doesn't meet the bar.

Source: IBD weekend paper "Sector Leaders" page. Never more than 16; often
6-7 or fewer during corrections; 14-16 signals strong broad tape.

Second signal this module exposes: **list cardinality as market-regime gauge**
  16 stocks = STRONG_BULL — full list, broad strength
  13-15    = STRONG — healthy rotation
  10-12    = HEALTHY — participation normal
  7-9      = WEAKENING — list thinning
  <7       = CORRECTION — chop/slop regime per IBD methodology

Update cadence: refresh the `LEADERS` list each weekend off the paper. If
the paper shows 14 names one week and 11 the next, trimming 3 names is
itself the signal — the regime degraded.
"""
from __future__ import annotations

from typing import Any


LIST_AS_OF = "2026-04-20"  # IBD weekend edition date

# Week of 2026-04-20. 15 of 16 slots filled — regime = STRONG (healthy bull).
LEADERS: list[dict[str, Any]] = [
    {"ticker": "AGI",  "name": "Alamos Gold",           "ytd_pct": 28.0, "sector": "Mining-Gold"},
    {"ticker": "APH",  "name": "Amphenol",              "ytd_pct": 12.0, "sector": "Electronic-Connectors"},
    {"ticker": "ANET", "name": "Arista Networks",       "ytd_pct": 25.0, "sector": "Electronic-Networking"},
    {"ticker": "AVGO", "name": "Broadcom",              "ytd_pct": 17.0, "sector": "Elec-Semiconductor Mfg"},
    {"ticker": "FIX",  "name": "Comfort Systems",       "ytd_pct": 77.0, "sector": "Bldg-A/C & Heating"},
    {"ticker": "ROAD", "name": "Construction Partners", "ytd_pct": 16.0, "sector": "Bldg-Heavy Construction"},
    {"ticker": "FUTU", "name": "Futu",                  "ytd_pct":  2.0, "sector": "Finance-Investment Bkg"},
    {"ticker": "GFI",  "name": "Gold Fields",           "ytd_pct": 14.0, "sector": "Mining-Gold"},
    {"ticker": "KGC",  "name": "Kinross Gold",          "ytd_pct": 24.0, "sector": "Mining-Gold"},
    {"ticker": "MRX",  "name": "Marex",                 "ytd_pct": 34.0, "sector": "Finance-Investment Bkg"},
    {"ticker": "NVDA", "name": "Nvidia",                "ytd_pct": 36.0, "sector": "Elec-Semiconductor Mfg"},
    {"ticker": "TSM",  "name": "Taiwan Semiconductor",  "ytd_pct": 22.0, "sector": "Elec-Semiconductor Mfg"},
    {"ticker": "TFPM", "name": "Triple Flag Precious",  "ytd_pct":  9.0, "sector": "Mining-Gold"},
    {"ticker": "VRT",  "name": "Vertiv",                "ytd_pct": 90.0, "sector": "Electronic-Parts"},
    {"ticker": "WPM",  "name": "Wheaton Precious",      "ytd_pct": 30.0, "sector": "Mining-Gold"},
]


# ── Ticker set for fast membership checks ─────────────────────────────

_LEADER_SET = {row["ticker"].upper() for row in LEADERS}
_LEADER_INDEX = {row["ticker"].upper(): row for row in LEADERS}


def is_sector_leader(ticker: str) -> bool:
    """True if ticker is on the current IBD Sector Leaders list."""
    return ticker.upper() in _LEADER_SET


def get_leader_info(ticker: str) -> dict[str, Any] | None:
    """Return {ticker, name, ytd_pct, sector} if on list, else None."""
    return _LEADER_INDEX.get(ticker.upper())


# ── Market regime from list cardinality ───────────────────────────────

def leaders_count() -> int:
    return len(LEADERS)


def leaders_regime() -> dict[str, Any]:
    """Classify market regime from the list size per IBD methodology.

    The logic is O'Neil's: a shrinking list signals distribution /
    correction before price confirms. Pair with SPY 20d RTS for
    confirmation — if leaders count is falling AND SPY 20d turns
    negative, you're in a real correction, not just chop.
    """
    n = len(LEADERS)
    if n >= 16:
        label, tone = "STRONG_BULL", "bull"
    elif n >= 13:
        label, tone = "STRONG", "bull"
    elif n >= 10:
        label, tone = "HEALTHY", "neutral"
    elif n >= 7:
        label, tone = "WEAKENING", "caution"
    else:
        label, tone = "CORRECTION", "bear"
    return {
        "count": n,
        "max_possible": 16,
        "label": label,
        "tone": tone,
        "pct_full": round(n / 16 * 100, 0),
    }


# ── Universe intersection helpers ─────────────────────────────────────

def leaders_in_universe(universe: set[str]) -> list[str]:
    """Return leaders that overlap with the provided ticker universe,
    in list order. Used by Telegram alerts and UI filters."""
    return [row["ticker"] for row in LEADERS if row["ticker"] in universe]


def summary() -> dict[str, Any]:
    """Diagnostic summary for the /api endpoint."""
    return {
        "list_as_of": LIST_AS_OF,
        "regime": leaders_regime(),
        "leaders": [
            {"ticker": r["ticker"], "name": r["name"],
             "ytd_pct": r["ytd_pct"], "sector": r["sector"]}
            for r in LEADERS
        ],
    }
