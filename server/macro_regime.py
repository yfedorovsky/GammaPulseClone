"""Macro regime tagger — Apr 27 design (Perplexity-refined v1).

Computes a regime tag for the current moment combining:

  1. CALENDAR PRESSURE — proximity to FOMC + weighted mega-cap earnings
     count in next 72h. Source: Finnhub economic + earnings calendars
     (cached by weekend_research.py).

  2. PARTICIPATION — QQQ vs QQQE (equal-weight Nasdaq-100) relative
     return today. Narrow leadership = QQQ up while QQQE flat/down.

  3. CONCENTRATION — SPY vs XMAG (S&P ex-Magnificent-7) relative return.
     Mag-7 carrying tape = SPY/QQQ green while XMAG red.

Maps to four regime tiers:

  NONE         — normal tape, no special handling
  SOFT         — calendar pressure exists, breadth okay
  HARD         — calendar pressure + narrow leadership confirmed
  A_ONLY       — extreme event window (FOMC day, post-print first 90min)

SHADOW MODE (Apr 27 - May 2):
The tag is computed and persisted to soe_signals.macro_regime_tag for
every alert, but does NOT modify score, grade, or size. After 1-2 weeks
of accumulated outcomes we'll backtest WR by tag and decide whether to
flip the rule live.

If you want to test the live behavior, set env MACRO_REGIME_LIVE=true.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import get_settings


# ── Configuration ────────────────────────────────────────────────────

# Mega-cap weighting for earnings importance. FAANG+ get 1.0, broad
# index components 0.5, everything else 0.2. Tuned from the Apr 27
# observation that 3 random S&P prints are not the same as MSFT+AMZN+META.
MEGACAP_WEIGHTS: dict[str, float] = {
    # Tier 1 — single-name tape movers
    "AAPL": 1.0, "MSFT": 1.0, "GOOGL": 1.0, "GOOG": 1.0,
    "AMZN": 1.0, "META": 1.0, "NVDA": 1.0, "TSLA": 1.0,
    "AVGO": 1.0, "ORCL": 1.0, "NFLX": 1.0,
    # Tier 2 — sector leaders
    "AMD": 0.7, "QCOM": 0.7, "INTC": 0.7, "TSM": 0.7, "ASML": 0.7,
    "MU": 0.7, "MRVL": 0.7, "AMAT": 0.7, "KLAC": 0.7, "LRCX": 0.7,
    "JPM": 0.7, "BAC": 0.7, "WFC": 0.7, "GS": 0.7,
    "XOM": 0.5, "CVX": 0.5,
    "WMT": 0.5, "COST": 0.5, "HD": 0.5, "UNH": 0.5,
    "JNJ": 0.5, "PG": 0.5, "V": 0.5, "MA": 0.5,
    # Tier 3 — secondary names
    "CRWD": 0.4, "PANW": 0.4, "PLTR": 0.4, "SMCI": 0.4,
    "ANET": 0.4, "VRT": 0.4, "DELL": 0.4, "ADBE": 0.4,
}

DEFAULT_EARNINGS_WEIGHT = 0.2  # everything else

# Calendar cache file produced by weekend_research / earnings_week_implied
CACHE_DIR = Path("data/weekend_research_cache")
EARNINGS_CACHE = CACHE_DIR / "Finnhub_Earnings_Calendar_next_7d_.txt"
ECONOMIC_CACHE = CACHE_DIR / "Finnhub_Economic_Calendar_next_7d_.txt"


# ── Calendar pressure ────────────────────────────────────────────────

def _all_fomc_datetimes() -> list[datetime]:
    """Parse cached economic calendar — return all FOMC datetimes (past+future)."""
    if not ECONOMIC_CACHE.exists():
        return []
    text = ECONOMIC_CACHE.read_text(encoding="utf-8")
    fomc_dts: list[datetime] = []
    for line in text.splitlines():
        if "Fed Interest Rate" not in line and "FOMC" not in line:
            continue
        parts = line.split()
        for i in range(len(parts) - 1):
            try:
                dt_str = f"{parts[i]} {parts[i+1]}"
                fomc_dts.append(datetime.fromisoformat(dt_str))
                break
            except ValueError:
                continue
    return fomc_dts


def _hours_to_next_fomc() -> float | None:
    """Hours to next FOMC decision/press conference. None if not in cache."""
    fomc_dts = _all_fomc_datetimes()
    if not fomc_dts:
        return None
    now = datetime.now()
    future = [d for d in fomc_dts if d > now]
    if not future:
        return None
    return (min(future) - now).total_seconds() / 3600


def _hours_since_last_fomc() -> float | None:
    """Hours since most recent past FOMC. None if no past event in cache.
    Used for the post-event reset hook (downgrade regime for 2h after FOMC
    so we don't get stuck in HARD on stale calendar inputs)."""
    fomc_dts = _all_fomc_datetimes()
    if not fomc_dts:
        return None
    now = datetime.now()
    past = [d for d in fomc_dts if d <= now]
    if not past:
        return None
    return (now - max(past)).total_seconds() / 3600


def _megacap_earnings_within(hours: float) -> tuple[float, list[str]]:
    """Sum weighted mega-cap earnings within next N hours from cache.
    Returns (weighted_count, ticker_list_with_weights)."""
    if not EARNINGS_CACHE.exists():
        return 0.0, []
    text = EARNINGS_CACHE.read_text(encoding="utf-8")
    cutoff = datetime.now() + timedelta(hours=hours)
    weighted = 0.0
    detail: list[str] = []
    in_megacap_section = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("MEGA-CAP"):
            in_megacap_section = True
            continue
        if s.startswith("OTHER") or not s:
            in_megacap_section = False
            continue
        if not in_megacap_section:
            continue
        # Lines look like: "  2026-04-29 amc  AMZN EPS_est=1.6619"
        parts = s.split()
        if len(parts) < 3:
            continue
        try:
            event_date = datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        if event_date > cutoff:
            continue
        # Find ticker (first all-caps token after the date/hour)
        ticker = None
        for p in parts[1:]:
            if p.isupper() and 1 <= len(p) <= 5 and p not in ("AMC", "BMO"):
                ticker = p
                break
        if not ticker:
            continue
        w = MEGACAP_WEIGHTS.get(ticker, DEFAULT_EARNINGS_WEIGHT)
        weighted += w
        detail.append(f"{ticker}({w:.1f})")
    return weighted, detail


def compute_calendar_pressure() -> dict[str, Any]:
    """Returns calendar pressure score and component detail."""
    hours_fomc = _hours_to_next_fomc()
    hours_since_fomc = _hours_since_last_fomc()
    weighted_72h, names_72h = _megacap_earnings_within(72)
    weighted_48h, _ = _megacap_earnings_within(48)
    weighted_24h, _ = _megacap_earnings_within(24)

    # Post-event reset window: 2h after FOMC, downgrade one tier so we
    # don't stay stuck in HARD when the catalyst has already absorbed.
    fomc_in_post_event_window = (
        hours_since_fomc is not None and 0 < hours_since_fomc <= 2
    )

    out = {
        "hours_to_fomc": hours_fomc,
        "hours_since_last_fomc": hours_since_fomc,
        "weighted_megacap_72h": weighted_72h,
        "weighted_megacap_48h": weighted_48h,
        "weighted_megacap_24h": weighted_24h,
        "earnings_names": names_72h,
        "fomc_within_72h": hours_fomc is not None and hours_fomc <= 72,
        "fomc_within_48h": hours_fomc is not None and hours_fomc <= 48,
        "fomc_within_24h": hours_fomc is not None and hours_fomc <= 24,
        "fomc_in_post_event_window": fomc_in_post_event_window,
    }
    return out


# ── Participation (QQQ vs QQQE) ──────────────────────────────────────

def _intraday_return(ticker: str, conn: sqlite3.Connection) -> float | None:
    """Return today's open-to-latest pct change for a ticker. None if
    insufficient data."""
    today_open = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
    open_ts = int(today_open.timestamp())
    rows = conn.execute(
        "SELECT spot, ts FROM snapshots "
        "WHERE ticker = ? AND ts >= ? ORDER BY ts",
        (ticker, open_ts),
    ).fetchall()
    if len(rows) < 2:
        return None
    open_spot = rows[0][0]
    last_spot = rows[-1][0]
    if not open_spot:
        return None
    return (last_spot / open_spot - 1) * 100


def compute_breadth_state() -> dict[str, Any]:
    """Return participation + concentration tilts from QQQ/QQQE/SPY/XMAG."""
    s = get_settings()
    conn = sqlite3.connect(s.snapshot_db)
    qqq = _intraday_return("QQQ", conn)
    qqqe = _intraday_return("QQQE", conn)
    spy = _intraday_return("SPY", conn)
    xmag = _intraday_return("XMAG", conn)
    conn.close()

    # Participation: QQQ leading QQQE = narrow
    participation_gap_pct = None
    is_narrow = False
    if qqq is not None and qqqe is not None:
        participation_gap_pct = qqq - qqqe
        # >0.5pp gap = narrow leadership
        is_narrow = participation_gap_pct > 0.5

    # Concentration: SPY leading XMAG = mag-7 carrying
    concentration_gap_pct = None
    is_concentrated = False
    if spy is not None and xmag is not None:
        concentration_gap_pct = spy - xmag
        is_concentrated = concentration_gap_pct > 0.4

    # We need actual data to claim breadth is healthy. If both pairs are
    # missing (e.g., QQQE/XMAG just added to universe and no snapshots
    # accumulated yet), don't trigger downgrades.
    have_data = (
        (qqq is not None and qqqe is not None)
        or (spy is not None and xmag is not None)
    )

    return {
        "qqq_pct": qqq, "qqqe_pct": qqqe,
        "spy_pct": spy, "xmag_pct": xmag,
        "participation_gap_pct": participation_gap_pct,
        "concentration_gap_pct": concentration_gap_pct,
        "is_narrow_leadership": is_narrow,
        "is_concentrated_in_mag7": is_concentrated,
        "have_breadth_data": have_data,
        # breadth_ok requires ACTUAL data showing healthy state
        "breadth_ok": have_data and not is_narrow and not is_concentrated,
    }


# ── Composite regime tagger ──────────────────────────────────────────

def compute_macro_regime() -> dict[str, Any]:
    """Returns the regime tag + component detail. Always safe to call —
    fail-open returns NONE on any error."""
    try:
        cal = compute_calendar_pressure()
        breadth = compute_breadth_state()
    except Exception as e:
        return {"tag": "NONE", "error": str(e)}

    # Decision logic
    tag = "NONE"
    reasons: list[str] = []

    # SOFT: FOMC within 72h AND weighted megacap >= 3
    soft_trigger = (
        cal.get("fomc_within_72h")
        and cal.get("weighted_megacap_72h", 0) >= 3.0
    )
    # HARD: FOMC within 48h AND weighted megacap >= 4, OR weighted megacap >= 5
    hard_trigger = (
        (cal.get("fomc_within_48h") and cal.get("weighted_megacap_48h", 0) >= 4.0)
        or cal.get("weighted_megacap_72h", 0) >= 5.0
    )
    # A_ONLY: FOMC within 24h
    a_only_trigger = cal.get("fomc_within_24h")

    if a_only_trigger:
        tag = "A_ONLY"
        reasons.append(f"FOMC in {cal['hours_to_fomc']:.1f}h")
    elif hard_trigger:
        tag = "HARD"
        if cal.get("fomc_within_48h"):
            reasons.append(f"FOMC in {cal['hours_to_fomc']:.1f}h")
        reasons.append(
            f"weighted megacap earnings {cal['weighted_megacap_72h']:.1f}"
        )
    elif soft_trigger:
        tag = "SOFT"
        reasons.append(f"FOMC in {cal['hours_to_fomc']:.1f}h")
        reasons.append(
            f"weighted megacap earnings {cal['weighted_megacap_72h']:.1f}"
        )

    # Breadth modifier — Apr 27 (Perplexity refinement):
    #   HARD + healthy breadth -> SOFT (NOT NONE — true HARD windows
    #     should never fully relax even on midday breadth improvement)
    #   SOFT + healthy breadth -> NONE
    #   SOFT + narrow+concentrated -> HARD
    breadth_modifier = ""
    if tag == "HARD" and breadth.get("breadth_ok"):
        tag = "SOFT"  # clip to SOFT, never NONE
        breadth_modifier = " [clipped HARD -> SOFT: breadth healthy]"
    elif tag == "SOFT" and breadth.get("breadth_ok"):
        tag = "NONE"
        breadth_modifier = " [downgraded SOFT -> NONE: breadth healthy]"
    elif tag == "SOFT" and breadth.get("is_narrow_leadership") and breadth.get("is_concentrated_in_mag7"):
        tag = "HARD"
        breadth_modifier = " [upgraded SOFT -> HARD: narrow + concentrated]"

    # Post-event reset: 2h after FOMC, downgrade one tier (avoids stale
    # HARD when the catalyst has already been absorbed).
    if cal.get("fomc_in_post_event_window") and tag in ("A_ONLY", "HARD", "SOFT"):
        prev_tag = tag
        tag = {"A_ONLY": "HARD", "HARD": "SOFT", "SOFT": "NONE"}.get(tag, tag)
        reasons.append(
            f"post-event reset {prev_tag} -> {tag} "
            f"(FOMC was {cal['hours_since_last_fomc']:.1f}h ago)"
        )

    if breadth_modifier:
        reasons.append(breadth_modifier.strip(" []"))
    if breadth.get("is_narrow_leadership"):
        reasons.append(
            f"narrow leadership (QQQ {breadth.get('qqq_pct',0):+.1f}% "
            f"vs QQQE {breadth.get('qqqe_pct',0):+.1f}%)"
        )
    if breadth.get("is_concentrated_in_mag7"):
        reasons.append(
            f"mag-7 carrying (SPY {breadth.get('spy_pct',0):+.1f}% "
            f"vs XMAG {breadth.get('xmag_pct',0):+.1f}%)"
        )

    return {
        "tag": tag,
        "reasons": reasons,
        "calendar": cal,
        "breadth": breadth,
        "live_mode": os.environ.get("MACRO_REGIME_LIVE", "").lower() == "true",
    }


def macro_regime_tag() -> str:
    """Convenience wrapper — return just the tag string for storage."""
    try:
        return compute_macro_regime().get("tag", "NONE")
    except Exception:
        return "NONE"


# ── Cached fast-path for high-frequency callers (flow_alerts) ───────
#
# flow_alerts can fire dozens per minute during active flow. Computing
# the full regime each insert would be wasteful — calendar pressure
# changes hourly, breadth changes per minute. Cache the result for 60s.

_CACHE_TTL_SEC = 60
_cached_regime: dict[str, Any] | None = None
_cached_at: float = 0.0


def cached_macro_regime() -> dict[str, Any]:
    """60s-cached regime computation. Safe for high-frequency callers.
    Returns the same dict shape as compute_macro_regime()."""
    global _cached_regime, _cached_at
    now = time.time()
    if _cached_regime is not None and (now - _cached_at) < _CACHE_TTL_SEC:
        return _cached_regime
    try:
        _cached_regime = compute_macro_regime()
        _cached_at = now
    except Exception:
        _cached_regime = {"tag": "NONE", "reasons": [], "calendar": {}, "breadth": {}}
        _cached_at = now
    return _cached_regime


def cached_macro_regime_tag() -> str:
    """Convenience: cached tag-only fetch for high-freq insert paths."""
    try:
        return cached_macro_regime().get("tag", "NONE")
    except Exception:
        return "NONE"


if __name__ == "__main__":
    import sys
    import io
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass
    r = compute_macro_regime()
    print(f"\n=== MACRO REGIME ===\n  TAG: {r['tag']}\n")
    print(f"  Live mode: {r['live_mode']}")
    print(f"  Reasons:")
    for x in r.get("reasons", []):
        print(f"    - {x}")
    print(f"\n  Calendar pressure:")
    cal = r.get("calendar", {})
    print(f"    hours_to_fomc: {cal.get('hours_to_fomc')}")
    print(f"    weighted_megacap_72h: {cal.get('weighted_megacap_72h')}")
    print(f"    weighted_megacap_48h: {cal.get('weighted_megacap_48h')}")
    print(f"    weighted_megacap_24h: {cal.get('weighted_megacap_24h')}")
    print(f"    earnings_names: {cal.get('earnings_names')}")
    print(f"\n  Breadth state:")
    bd = r.get("breadth", {})
    for k, v in bd.items():
        print(f"    {k}: {v}")
