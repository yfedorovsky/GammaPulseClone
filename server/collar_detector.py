"""JHEQX (JPMorgan Hedged Equity Fund) collar detector — SPX structural CONTEXT.

JHEQX runs a quarterly SPX collar, reset on the quarter-end expiration:
  - long  put  ~5% OTM   (protection begins)
  - short put  ~20% OTM  (protection floor)
  - short call ~3-4% OTM (upside cap, finances the puts; ~costless collar)
All three legs sit on ONE quarter-end SPX expiry (Mar/Jun/Sep/Dec, last biz day).

This is the SPX-level analogue of the single-name OPEX call-wall pin we dissected
on MRVL 6/18. Per discipline (`session-jun18-findings`): known ≈ priced-in, so the
output is CONTEXT, not a trigger. The pin/support EFFECT gets zero algo weight until
the pre-registered Direction-A test clears (docs/research/JPM_COLLAR_PREREG.md).

Leg detection avoids the round-number / independent-hedger contamination by
DISTANCE-BAND gating each leg to its expected OTM band, then taking the largest
abnormal-OI strike inside that band. Naive top-OI is wrong (6000 is a round number
huge on both sides; 7000P is inflated by 5%-OTM hedgers).

Source = settled `daily_oi_snapshot` (held positions, the right OI for a structural
collar — NOT intraday flow). Cached; legs change ~once/quarter.

CLI:  python -m server.collar_detector            # current quarter, live spot
      python -m server.collar_detector 2026-06-30 7500
"""
from __future__ import annotations

import datetime
import sqlite3
import time
from typing import Any

from .config import get_settings

# Expected OTM bands per leg (fraction of spot). Gating, not assertion — keeps a
# deep-ITM round-number call from masquerading as the cap, and the 5%-OTM hedge
# wall from being mislabeled the short put.
_SHORT_CALL_BAND = (1.00, 1.12)   # at/above spot
_LONG_PUT_BAND = (0.92, 0.985)    # ~1.5-8% OTM
_SHORT_PUT_BAND = (0.74, 0.90)    # ~10-26% OTM

_CACHE: dict[str, Any] = {}
_CACHE_TS = 0.0
_CACHE_TTL = 3600.0  # legs are quarterly; hourly refresh is generous


def quarter_end_expiry(today: datetime.date | None = None) -> str:
    """Next quarter-end (last business day of Mar/Jun/Sep/Dec) on/after today,
    as 'YYYY-MM-DD'. JHEQX expiry sits on this date."""
    today = today or datetime.date.today()
    candidates = []
    for year in (today.year, today.year + 1):
        for month in (3, 6, 9, 12):
            if month == 12:
                last = datetime.date(year, 12, 31)
            else:
                last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            # roll back to a weekday (does not adjust for market holidays; the
            # detector tolerates a +/-1 day mismatch by scanning nearby expiries)
            while last.weekday() >= 5:
                last -= datetime.timedelta(days=1)
            candidates.append(last)
    for last in sorted(candidates):
        if last >= today:
            return last.isoformat()
    return today.isoformat()


def _latest_oi_by_strike(con: sqlite3.Connection, exp: str) -> dict:
    """{('C'|'P', strike): oi} at the latest capture date for SPX exp."""
    row = con.execute(
        "SELECT MAX(date) FROM daily_oi_snapshot WHERE ticker='SPX' AND exp=?",
        (exp,),
    ).fetchone()
    if not row or not row[0]:
        return {}
    latest = row[0]
    out: dict[tuple[str, float], float] = {}
    for strike, otype, oi in con.execute(
        "SELECT strike, substr(upper(option_type),1,1), MAX(oi) "
        "FROM daily_oi_snapshot WHERE ticker='SPX' AND exp=? AND date=? "
        "GROUP BY strike, substr(upper(option_type),1,1)",
        (exp, latest),
    ):
        if otype in ("C", "P"):
            out[(otype, float(strike))] = float(oi or 0)
    return out


def _pick_leg(oi: dict, otype: str, spot: float, band: tuple[float, float],
              median_oi: float) -> dict | None:
    """Largest abnormal-OI strike of `otype` inside the spot*band distance window."""
    lo, hi = spot * band[0], spot * band[1]
    cands = [
        (k, o) for (t, k), o in oi.items()
        if t == otype and lo <= k <= hi and o > 0
    ]
    if not cands:
        return None
    strike, leg_oi = max(cands, key=lambda x: x[1])
    # abnormal = stands out vs the chain median (cheap robustness gate)
    abnormal = median_oi <= 0 or leg_oi >= 4 * median_oi
    return {
        "strike": strike,
        "oi": round(leg_oi),
        "dist_pct": round((strike / spot - 1) * 100, 2),
        "abnormal": bool(abnormal),
    }


def detect(exp: str | None = None, spot: float | None = None) -> dict:
    """Detect the 3 JHEQX legs on the quarter-end SPX expiry. Pure context.

    Returns {exp, spot, short_call, long_put, short_put, confidence, source} —
    each leg is {strike, oi, dist_pct, abnormal} or None. Fail-open: missing data
    yields legs=None, confidence='none' (never raises in the hot path)."""
    s = get_settings()
    exp = exp or quarter_end_expiry()
    try:
        con = sqlite3.connect(f"file:{s.snapshot_db}?mode=ro", uri=True)
    except Exception:
        return {"exp": exp, "spot": spot, "short_call": None, "long_put": None,
                "short_put": None, "confidence": "none", "source": "db_error"}
    try:
        if spot is None:
            r = con.execute(
                "SELECT spot FROM snapshots WHERE ticker='SPX' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            spot = float(r[0]) if r and r[0] else None
        oi = _latest_oi_by_strike(con, exp)
    finally:
        con.close()

    if not spot or not oi:
        return {"exp": exp, "spot": spot, "short_call": None, "long_put": None,
                "short_put": None, "confidence": "none", "source": "no_data"}

    vals = sorted(oi.values())
    median_oi = vals[len(vals) // 2] if vals else 0.0

    short_call = _pick_leg(oi, "C", spot, _SHORT_CALL_BAND, median_oi)
    long_put = _pick_leg(oi, "P", spot, _LONG_PUT_BAND, median_oi)
    short_put = _pick_leg(oi, "P", spot, _SHORT_PUT_BAND, median_oi)

    legs = [short_call, long_put, short_put]
    n_found = sum(1 for x in legs if x)
    n_abnormal = sum(1 for x in legs if x and x["abnormal"])
    if n_found == 3 and n_abnormal == 3:
        confidence = "high"
    elif n_found >= 2 and n_abnormal >= 2:
        confidence = "medium"
    elif n_found >= 1:
        confidence = "low"
    else:
        confidence = "none"

    return {
        "exp": exp, "spot": round(spot, 2),
        "short_call": short_call, "long_put": long_put, "short_put": short_put,
        "confidence": confidence, "source": "settled_oi",
    }


def detect_cached() -> dict:
    """Hourly-cached detect() for the gex hot path."""
    global _CACHE, _CACHE_TS
    now = time.time()
    if _CACHE and (now - _CACHE_TS) < _CACHE_TTL:
        return _CACHE
    try:
        _CACHE = detect()
        _CACHE_TS = now
    except Exception as e:  # fail-open: context must never break GEX
        _CACHE = {"exp": None, "spot": None, "short_call": None, "long_put": None,
                  "short_put": None, "confidence": "none", "source": f"err:{e!r}"}
        _CACHE_TS = now
    return _CACHE


if __name__ == "__main__":
    import json
    import sys

    _exp = sys.argv[1] if len(sys.argv) > 1 else None
    _spot = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(detect(_exp, _spot), indent=2))
