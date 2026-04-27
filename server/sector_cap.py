"""Sector-bucket cohort cap.

Phase 2 #4. Replaces the flat 8% cohort cap with per-bucket position-count
limits. Rationale (cross-LLM consensus, ChatGPT + Grok): correlated
positions cluster by theme. A flat cap doesn't distinguish 4 photonics
names + 1 oil from 5 photonics names — but these have very different
risk profiles.

Bucket assignments come from the QM × Minervini cohort + IBD theme tags
already used in setups_week_apr27.md. Tickers outside these buckets are
treated as "uncategorized" and capped at 2 (loose default).

Action when bucket exceeds cap:
  - Block new opens in that bucket
  - Caller can choose to log + skip or reduce size

Usage:
    from server.sector_cap import bucket_for, count_positions_in_bucket, gate

    g = gate(ticker="AAOI", current_open_positions=["GLW", "CIEN", "MU"])
    if g["blocked"]:
        return  # bucket full

State source: pass a list of currently-open ticker symbols (from your
position tracker / trade log).
"""
from __future__ import annotations

from typing import Any

# Bucket map — each cohort ticker assigned to one theme.
# From docs/research/setups_week_apr27.md.
SECTOR_BUCKETS: dict[str, str] = {
    # Photonics / fiber / AI infra (high inter-correlation)
    "GLW": "PHOTONICS", "AAOI": "PHOTONICS", "CIEN": "PHOTONICS",
    "VICR": "PHOTONICS", "LASR": "PHOTONICS", "UCTT": "PHOTONICS",
    "CAMT": "PHOTONICS",
    # Memory / NAND
    "SNDK": "MEMORY", "MU": "MEMORY",
    # Oilfield services (very tight cluster, oil price driven)
    "AESI": "OFS", "PUMP": "OFS", "RES": "OFS",
    "PTEN": "OFS", "NBR": "OFS",
    # Specialty materials / chemicals / lithium
    "TROX": "MATERIALS", "LAR": "MATERIALS",
    # Biotech
    "ANAB": "BIOTECH", "GHRS": "BIOTECH", "CAPR": "BIOTECH",
}

# Per-bucket maximum concurrent positions.
# Tighter buckets get lower caps (reflects intra-bucket correlation strength).
BUCKET_CAPS: dict[str, int] = {
    "PHOTONICS": 3,    # 7-name bucket, very theme-correlated
    "MEMORY": 2,       # 2-name bucket
    "OFS": 2,          # 5-name bucket, oil-price macro
    "MATERIALS": 2,    # 2-name bucket
    "BIOTECH": 2,      # 3-name bucket, idiosyncratic but event-driven
    "_UNCATEGORIZED": 2,  # default loose cap
}


def bucket_for(ticker: str) -> str:
    """Return the bucket label for a ticker, or _UNCATEGORIZED."""
    return SECTOR_BUCKETS.get(ticker.upper(), "_UNCATEGORIZED")


def count_positions_in_bucket(open_tickers: list[str], bucket: str) -> int:
    """How many of the currently-open tickers are in the given bucket."""
    return sum(1 for t in open_tickers if bucket_for(t) == bucket)


def gate(ticker: str, open_tickers: list[str]) -> dict[str, Any]:
    """Should this new entry be blocked by the sector-bucket cap?

    Args:
        ticker: the proposed new entry
        open_tickers: list of tickers with currently-open positions

    Returns:
        {
            "blocked": bool,
            "bucket": str,
            "current_count": int,
            "cap": int,
            "reason": str,
        }
    """
    b = bucket_for(ticker)
    cap = BUCKET_CAPS.get(b, BUCKET_CAPS["_UNCATEGORIZED"])
    cnt = count_positions_in_bucket(open_tickers, b)
    if cnt >= cap:
        return {
            "blocked": True, "bucket": b, "current_count": cnt, "cap": cap,
            "reason": (f"Sector bucket {b} at cap ({cnt}/{cap}); "
                       f"existing: {[t for t in open_tickers if bucket_for(t) == b]}"),
        }
    return {
        "blocked": False, "bucket": b, "current_count": cnt, "cap": cap,
        "reason": f"Bucket {b} has room ({cnt}/{cap})",
    }


if __name__ == "__main__":
    # Smoke tests
    open_pos = ["AAOI", "CIEN", "GLW"]
    for t in ["VICR", "MU", "AESI", "TROX", "TSLA"]:
        g = gate(t, open_pos)
        print(f"  {t:<6} bucket={g['bucket']:<15} blocked={g['blocked']}  "
              f"({g['current_count']}/{g['cap']})  {g['reason']}")
