"""Side-label tape verification — was the alert's SIDE tag real?

OPRA-tape verification (2026-06-08) proved the live system's flow-alert side tags
are unreliable on big blocks: MSTR 125C was tagged ASK (bullish buying) while 99%
of 51,847 contracts hit the BID on the tape; MU 900C / MRVL 230C were ~82-98% MID.
The side falls back to a snapshot GUESS (a single `last` print) whenever the live
tick tracker lacks coverage, and no (bid,ask,last,delta,vol,oi) heuristic can
recover where block SIZE executed — only the tape can.

This module replays the tape OFFLINE and retroactively: for a given contract +
trading day it pulls every print with its prevailing NBBO (ThetaData v3
``/option/history/trade_quote``), volume-weights the at-ask / at-bid / mid split,
and grades the alert's labeled side as CONFIRMED / INVERTED / AMBIGUOUS / NO_DATA.
Classification thresholds mirror the canonical manual check
(``scripts/theta_v3_query.py side``: >=55% at-ask = real buying, etc).

Pure-stdlib; the tape source is injectable (deterministic offline tests) and the
ThetaData source caches to ``autoresearch/_artifacts/tape_cache/`` like
``option_pnl.ThetaNBBOSource``. Read-only, offline — never touches live scoring.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .option_pnl import THETA_URL

_CACHE_DIR = Path(__file__).resolve().parent / "_artifacts" / "tape_cache"

# Volume-share thresholds (same verdict lines as theta_v3_query.py cmd_side).
ASK_DOMINANT = 0.55     # >=55% of contracts at/above the ask -> real buying.
BID_DOMINANT = 0.55     # >=55% at/below the bid -> selling.
DEFAULT_MIN_CONTRACTS = 10   # below this the tape can't support a verdict.

# Verification statuses.
CONFIRMED = "CONFIRMED"    # tape aggressor matches the labeled side.
INVERTED = "INVERTED"      # tape aggressor is the OPPOSITE side (the MSTR case).
AMBIGUOUS = "AMBIGUOUS"    # tape is MID-dominated / no clear aggressor (MU/MRVL).
NO_DATA = "NO_DATA"        # no tape coverage (or below min_contracts).
# On LIQUID names the flagged block can be a small share of the session tape, so
# a cumulative volume-weighted window washes it out and reads false-MID. When the
# alert's flagged volume is a small share of the windowed tape volume and a
# block-centered narrow window can't resolve it either, the verdict is
# LOW_RESOLUTION — "the window can't see the block", NOT a label-quality verdict.
# Excluded from the confirmation denominator (like NO_DATA).
LOW_RESOLUTION = "LOW_RESOLUTION"


@dataclass
class TapePrint:
    size: int
    price: float
    bid: float
    ask: float


class TradeTapeSource(Protocol):
    def prints(self, ticker: str, expiration: str, strike: float, right: str,
               date: str, start_time: str, end_time: str) -> list[TapePrint]:
        ...


class ThetaTradeTapeSource:
    """ThetaData /v3 trade+NBBO prints with on-disk caching."""

    def __init__(self, base_url: str = THETA_URL, cache_dir: Path = _CACHE_DIR,
                 timeout: float = 90.0):
        self.base_url = base_url
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self._mem: dict[tuple, list[TapePrint]] = {}

    def _cache_path(self, key: tuple) -> Path:
        date, sym, exp, strike, right, t0, t1 = key
        safe = (f"{sym}_{exp}_{strike:.3f}_{right}_{date}_"
                f"{t0.replace(':', '')}-{t1.replace(':', '')}.json").replace("/", "-")
        return self.cache_dir / safe

    def prints(self, ticker, expiration, strike, right, date,
               start_time, end_time) -> list[TapePrint]:
        right = right[0].upper()
        key = (date, ticker, expiration, float(strike), right, start_time, end_time)
        if key in self._mem:
            return self._mem[key]
        cp = self._cache_path(key)
        if cp.exists():
            raw = json.loads(cp.read_text(encoding="utf-8"))
            out = [TapePrint(**p) for p in raw]
            self._mem[key] = out
            return out
        out = self._fetch(ticker, expiration, strike, right, date, start_time, end_time)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps([p.__dict__ for p in out]), encoding="utf-8")
        self._mem[key] = out
        return out

    def _fetch(self, ticker, expiration, strike, right, date,
               start_time, end_time) -> list[TapePrint]:
        params = urllib.parse.urlencode({
            "symbol": ticker, "expiration": expiration, "strike": f"{strike:.3f}",
            "right": right, "start_date": date, "end_date": date,
            "start_time": start_time, "end_time": end_time,
        })
        url = f"{self.base_url}/v3/option/history/trade_quote?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return []
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            return []
        out: list[TapePrint] = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                size = int(row["size"]); price = float(row["price"])
                bid = float(row["bid"]); ask = float(row["ask"])
            except (KeyError, ValueError):
                continue
            if size <= 0:
                continue
            out.append(TapePrint(size=size, price=price, bid=bid, ask=ask))
        return out


@dataclass
class TapeSide:
    """Volume-weighted aggressor split for one contract-day window."""
    status: str                  # OK / NO_DATA.
    side: str = ""               # ASK / BID / MID (when status == OK).
    ask_frac: float = 0.0
    bid_frac: float = 0.0
    mid_frac: float = 0.0
    contracts: int = 0
    n_prints: int = 0


def classify_tape(prints: list[TapePrint],
                  min_contracts: int = DEFAULT_MIN_CONTRACTS) -> TapeSide:
    """Volume-weighted at-ask / at-bid / mid split -> dominant tape side."""
    ask = bid = mid = total = 0
    for p in prints:
        total += p.size
        if p.ask > 0 and p.price >= p.ask:
            ask += p.size
        elif p.bid > 0 and p.price <= p.bid:
            bid += p.size
        else:
            mid += p.size
    if total < min_contracts:
        return TapeSide(status=NO_DATA, contracts=total, n_prints=len(prints))
    af, bf, mf = ask / total, bid / total, mid / total
    if af >= ASK_DOMINANT:
        side = "ASK"
    elif bf >= BID_DOMINANT:
        side = "BID"
    else:
        side = "MID"
    return TapeSide(status="OK", side=side, ask_frac=af, bid_frac=bf, mid_frac=mf,
                    contracts=total, n_prints=len(prints))


def implied_side(direction: Optional[str], option_type: Optional[str]) -> Optional[str]:
    """The side label a recorded direction asserts (inverse of `_is_bull_flow`).

    BULL+call -> ASK (calls bought), BULL+put -> BID (puts sold),
    BEAR+call -> BID, BEAR+put -> ASK. Lets us verify alert_outcomes rows that
    stored a direction but never the raw side. Returns None when unmappable.
    """
    d = (direction or "").upper()
    o = (option_type or "").lower()
    if d not in ("BULL", "BEAR") or o[:1] not in ("c", "p"):
        return None
    is_call = o.startswith("c")
    if d == "BULL":
        return "ASK" if is_call else "BID"
    return "BID" if is_call else "ASK"


def verify_side(labeled_side: Optional[str], tape: TapeSide) -> str:
    """Grade a labeled side against the tape.

    CONFIRMED: tape aggressor matches the label.
    INVERTED:  tape aggressor is the opposite side — the label flipped the
               trade's direction (MSTR 125C class).
    AMBIGUOUS: tape has no clear aggressor (MID-dominated), OR the label itself
               asserts no side (MID/NEUTRAL) — unsupported either way.
    NO_DATA:   no usable tape.
    """
    if tape.status != "OK":
        return NO_DATA
    ls = (labeled_side or "").upper()
    if ls not in ("ASK", "BID"):
        return AMBIGUOUS
    if tape.side == ls:
        return CONFIRMED
    if tape.side in ("ASK", "BID"):
        return INVERTED
    return AMBIGUOUS


def _hhmm_plus(fire_hhmm: str, delta_min: int) -> tuple[int, int]:
    h, m = int(fire_hhmm[:2]), int(fire_hhmm[3:5])
    total = h * 60 + m + delta_min
    total = max(total, 9 * 60 + 30)        # clamp to session open.
    total = min(total, 16 * 60)            # clamp to session close.
    return total // 60, total % 60


def fire_window(fire_hhmm: str, buffer_min: int = 5) -> tuple[str, str]:
    """Tape window for an alert: session open -> fire time + buffer.

    The alert's volume is session-cumulative, so the size that earned the label
    executed BEFORE the fire; a small buffer catches the triggering block when
    the snapshot lagged the print.
    """
    h, m = _hhmm_plus(fire_hhmm, buffer_min)
    return "09:30:00.000", f"{h:02d}:{m:02d}:00.000"


def narrow_window(fire_hhmm: str, lookback_min: int = 30,
                  buffer_min: int = 5) -> tuple[str, str]:
    """Block-centered tape window: fire - lookback -> fire + buffer.

    Used when the full-session window dilutes the flagged block on a liquid name
    — the block that tripped the alert is the most recent flow, so a window
    anchored just before the fire isolates it from the day's unrelated churn.
    """
    h0, m0 = _hhmm_plus(fire_hhmm, -lookback_min)
    h1, m1 = _hhmm_plus(fire_hhmm, buffer_min)
    return f"{h0:02d}:{m0:02d}:00.000", f"{h1:02d}:{m1:02d}:00.000"


__all__ = [
    "TapePrint", "TradeTapeSource", "ThetaTradeTapeSource", "TapeSide",
    "classify_tape", "implied_side", "verify_side", "fire_window", "narrow_window",
    "CONFIRMED", "INVERTED", "AMBIGUOUS", "NO_DATA", "LOW_RESOLUTION",
    "ASK_DOMINANT", "BID_DOMINANT", "DEFAULT_MIN_CONTRACTS",
]
