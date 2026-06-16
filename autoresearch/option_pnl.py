"""C6 — realistic option-premium PnL net of slippage.

Replaces the directional-spot-return proxy with per-trade OPTION returns
re-simulated from ThetaData NBBO, using worst-case retail fills:
  - entry at the ASK at/after the alert's fire time,
  - exit at the BID (TP when bid crosses the take-profit, stop when bid crosses
    the stop, else EOD at the last bid).
This mirrors scripts/realistic_slippage_backtest.py's fill model, generalized to
arbitrary alert contracts.

The economic unit is an **R-multiple**: pnl_pct / risk_pct (risk = |stop_pct|), so
a full stop ≈ -1R. R-multiples are winsorized for SPA/economic robustness.

Two horizons:
  - ``simulate_option_pnl`` — SINGLE-SESSION re-sim on the fire day (the
    original C6 model; conservative for anything longer-tenor).
  - ``simulate_option_pnl_multiday`` — fire session + up to ``hold_days``
    further TRADING sessions (sessions detected empirically: a calendar day
    with no NBBO bars is a weekend/holiday/no-quote day), TP/stop checked
    bar-by-bar across the whole path, exit at the bid on the final session,
    clamped at expiration. This is what lets a LEAP-tenor whale add be judged
    on more than its day-1 premium move.

CENSORING RULE (multi-day): a trade is gradeable only if its FULL horizon is
covered by available data — decided by the fire date, EVEN IF TP/stop already
hit inside the partial window. Including early barrier-hits from the recent
window, while their still-open cohort-mates cannot be valued, would bias the
sample toward early deciders. Too-recent trades return status ``UNRESOLVED``
and must be counted, not scored.

The NBBO source is injectable so the logic is deterministically testable
offline; the ThetaData source caches to autoresearch/_artifacts/nbbo_cache/.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol
from zoneinfo import ZoneInfo

THETA_URL = "http://127.0.0.1:25503"
_ET = ZoneInfo("America/New_York")  # ThetaData OPRA timestamps are exchange-local (ET).
_CACHE_DIR = Path(__file__).resolve().parent / "_artifacts" / "nbbo_cache"


@dataclass
class Bar:
    hhmm: str       # "HH:MM" (exchange local, as ThetaData returns).
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


class NBBOSource(Protocol):
    def bars(self, ticker: str, expiration: str, strike: float, right: str,
             date: str) -> list[Bar]:
        ...


class ThetaNBBOSource:
    """ThetaData /v3 NBBO with on-disk caching (1-minute quote bars)."""

    def __init__(self, base_url: str = THETA_URL, cache_dir: Path = _CACHE_DIR,
                 timeout: float = 30.0):
        self.base_url = base_url
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self._mem: dict[tuple, list[Bar]] = {}

    def _cache_path(self, key: tuple) -> Path:
        date, sym, exp, strike, right = key
        safe = f"{sym}_{exp}_{strike:.3f}_{right}_{date}.json".replace("/", "-")
        return self.cache_dir / safe

    def bars(self, ticker, expiration, strike, right, date) -> list[Bar]:
        right = right[0].upper()  # "call"->"C", "put"->"P".
        key = (date, ticker, expiration, float(strike), right)
        if key in self._mem:
            return self._mem[key]
        cp = self._cache_path(key)
        if cp.exists():
            raw = json.loads(cp.read_text(encoding="utf-8"))
            bars = [Bar(**b) for b in raw]
            self._mem[key] = bars
            return bars
        bars = self._fetch(ticker, expiration, strike, right, date)
        # Only cache CONFIRMED results — _fetch returns None on failure (HTTP
        # error / timeout / ThetaData error body like "Invalid session ID");
        # caching those as [] would poison the contract permanently (the
        # multi-terminal session conflict, diagnosed 2026-06-11).
        if bars is None:
            return []
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps([b.__dict__ for b in bars]), encoding="utf-8")
        self._mem[key] = bars
        return bars

    def _fetch(self, ticker, expiration, strike, right, date) -> Optional[list[Bar]]:
        params = urllib.parse.urlencode({
            "symbol": ticker, "expiration": expiration, "strike": f"{strike:.3f}",
            "right": right, "start_date": date, "end_date": date, "interval": "1m",
        })
        url = f"{self.base_url}/v3/option/history/quote?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            return None
        if text.startswith("No data"):
            return []
        if "Invalid session" in text or "error" in text[:40].lower():
            return None
        out: list[Bar] = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                bid = float(row["bid"]); ask = float(row["ask"])
            except (KeyError, ValueError):
                continue
            if bid <= 0 or ask <= 0:
                continue
            ts = row.get("timestamp", "")
            hhmm = ts[11:16] if len(ts) >= 16 else ""
            out.append(Bar(hhmm=hhmm, bid=bid, ask=ask))
        return out


@dataclass
class OptionPnLResult:
    status: str            # OK / NO_DATA / UNRESOLVED.
    pnl_pct: float = 0.0   # net % return (ask-in, bid-out).
    r_multiple: float = 0.0
    exit_reason: str = ""  # TP / STOP / EOD / HORIZON / EXPIRY.
    entry_ask: float = 0.0
    bars_seen: int = 0
    days_held: int = 0     # exit session index (0 = the fire session).
    exit_date: str = ""    # ET day of the exit session.


def _parse_day(s: str) -> Optional[_date]:
    """Parse YYYY-MM-DD or YYYYMMDD; None when unparseable."""
    t = (s or "").replace("-", "")
    if len(t) != 8 or not t.isdigit():
        return None
    try:
        return _date(int(t[:4]), int(t[4:6]), int(t[6:8]))
    except ValueError:
        return None


def simulate_option_pnl_multiday(*, ticker: str, expiration: str, strike: float,
                                 option_type: str, fire_hhmm: str, date: str,
                                 source: NBBOSource, tp_pct: float = 100.0,
                                 stop_pct: float = -50.0, hold_days: int = 0,
                                 max_calendar_scan: Optional[int] = None,
                                 ) -> OptionPnLResult:
    """Worst-case ask-in / bid-out re-sim over fire session + ``hold_days`` more
    trading sessions (expiry-clamped). Returns an R-multiple; full stop ≈ -1R.

    Sessions are detected empirically (a day with no bars doesn't count toward
    the horizon). CENSORING RULE: if the scan cannot cover the FULL horizon
    (data ends — the fire is too recent) the result is UNRESOLVED regardless of
    any TP/stop hit inside the partial window; see the module docstring.
    """
    right = "C" if option_type.lower().startswith("c") else "P"
    day0 = [b for b in source.bars(ticker, expiration, strike, right, date)
            if b.hhmm and b.hhmm >= fire_hhmm]
    if not day0 or day0[0].ask <= 0:
        return OptionPnLResult(status="NO_DATA")

    fire_day = _parse_day(date)
    expiry = _parse_day(expiration)
    sessions: list[tuple[str, list[Bar]]] = [(date, day0)]
    needed = int(hold_days) + 1
    expiry_clamped = expiry is not None and fire_day is not None and fire_day >= expiry
    if fire_day is not None and needed > 1:
        max_scan = (max_calendar_scan if max_calendar_scan is not None
                    else needed * 2 + 10)
        cal = fire_day
        for _ in range(max_scan):
            if len(sessions) >= needed:
                break
            cal = cal + timedelta(days=1)
            if expiry is not None and cal > expiry:
                expiry_clamped = True
                break
            bars = [b for b in source.bars(ticker, expiration, strike, right,
                                           cal.isoformat()) if b.hhmm]
            if bars:
                sessions.append((cal.isoformat(), bars))
    complete = len(sessions) >= needed or expiry_clamped or (
        fire_day is None)  # unparseable fire date -> fall back to what we have.
    if not complete:
        return OptionPnLResult(status="UNRESOLVED")

    entry = day0[0].ask
    tp_level = entry * (1 + tp_pct / 100.0)
    stop_level = entry * (1 + stop_pct / 100.0)
    risk = abs(stop_pct) / 100.0
    seen = 0
    for si, (sday, bars) in enumerate(sessions):
        for b in bars:
            seen += 1
            # Worst-case tiebreak: a bar spanning BOTH stop and TP fills the
            # STOP first (intrabar order is unobservable).
            if b.bid <= stop_level:
                pnl = (b.bid - entry) / entry
                return OptionPnLResult("OK", pnl * 100, pnl / risk, "STOP",
                                       entry, seen, si, sday)
            if b.bid >= tp_level:
                pnl = (b.bid - entry) / entry
                return OptionPnLResult("OK", pnl * 100, pnl / risk, "TP",
                                       entry, seen, si, sday)
    last_day, last_bars = sessions[-1]
    pnl = (last_bars[-1].bid - entry) / entry
    reason = ("EOD" if hold_days == 0
              else ("EXPIRY" if expiry_clamped and len(sessions) < needed
                    else "HORIZON"))
    return OptionPnLResult("OK", pnl * 100, pnl / risk, reason, entry, seen,
                           len(sessions) - 1, last_day)


def simulate_option_pnl(*, ticker: str, expiration: str, strike: float,
                        option_type: str, fire_hhmm: str, date: str,
                        source: NBBOSource, tp_pct: float = 100.0,
                        stop_pct: float = -50.0) -> OptionPnLResult:
    """Worst-case ask-in / bid-out re-sim on the fire session (legacy C6 model).

    Returns an R-multiple (pnl_pct / |stop_pct|). A full stop ≈ -1R.
    """
    return simulate_option_pnl_multiday(
        ticker=ticker, expiration=expiration, strike=strike,
        option_type=option_type, fire_hhmm=fire_hhmm, date=date, source=source,
        tp_pct=tp_pct, stop_pct=stop_pct, hold_days=0)


def fire_hhmm_from_ts(fired_at: float) -> str:
    """Fire time as ET HH:MM, to align with ThetaData's exchange-local bars."""
    return datetime.fromtimestamp(fired_at, tz=_ET).strftime("%H:%M")


def et_day_from_ts(fired_at: float) -> str:
    """Trading day (ET) as YYYY-MM-DD."""
    return datetime.fromtimestamp(fired_at, tz=_ET).strftime("%Y-%m-%d")


__all__ = [
    "Bar", "NBBOSource", "ThetaNBBOSource", "OptionPnLResult",
    "simulate_option_pnl", "fire_hhmm_from_ts", "et_day_from_ts", "THETA_URL",
]
