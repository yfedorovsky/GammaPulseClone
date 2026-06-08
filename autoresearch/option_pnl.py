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

Honest scope: this is a SINGLE-SESSION re-sim on the alert's fire day (like the
0DTE backtester). Multi-day holds are truncated to the fire session — a
conservative, intraday-realized economic return, not a hold-to-expiry P/L. The
NBBO source is injectable so the logic is deterministically testable offline; the
ThetaData source caches to autoresearch/_artifacts/nbbo_cache/.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps([b.__dict__ for b in bars]), encoding="utf-8")
        self._mem[key] = bars
        return bars

    def _fetch(self, ticker, expiration, strike, right, date) -> list[Bar]:
        params = urllib.parse.urlencode({
            "symbol": ticker, "expiration": expiration, "strike": f"{strike:.3f}",
            "right": right, "start_date": date, "end_date": date, "interval": "1m",
        })
        url = f"{self.base_url}/v3/option/history/quote?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return []
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            return []
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
    status: str            # OK / NO_DATA.
    pnl_pct: float = 0.0   # net % return (ask-in, bid-out).
    r_multiple: float = 0.0
    exit_reason: str = ""  # TP / STOP / EOD.
    entry_ask: float = 0.0
    bars_seen: int = 0


def simulate_option_pnl(*, ticker: str, expiration: str, strike: float,
                        option_type: str, fire_hhmm: str, date: str,
                        source: NBBOSource, tp_pct: float = 100.0,
                        stop_pct: float = -50.0) -> OptionPnLResult:
    """Worst-case ask-in / bid-out re-sim on the fire session.

    Returns an R-multiple (pnl_pct / |stop_pct|). A full stop ≈ -1R.
    """
    right = "C" if option_type.lower().startswith("c") else "P"
    bars = [b for b in source.bars(ticker, expiration, strike, right, date)
            if b.hhmm and b.hhmm >= fire_hhmm]
    if not bars:
        return OptionPnLResult(status="NO_DATA")
    entry = bars[0].ask
    if entry <= 0:
        return OptionPnLResult(status="NO_DATA")
    tp_level = entry * (1 + tp_pct / 100.0)
    stop_level = entry * (1 + stop_pct / 100.0)
    risk = abs(stop_pct) / 100.0
    for b in bars:
        if b.bid >= tp_level:
            pnl = (b.bid - entry) / entry
            return OptionPnLResult("OK", pnl * 100, pnl / risk, "TP", entry, len(bars))
        if b.bid <= stop_level:
            pnl = (b.bid - entry) / entry
            return OptionPnLResult("OK", pnl * 100, pnl / risk, "STOP", entry, len(bars))
    pnl = (bars[-1].bid - entry) / entry
    return OptionPnLResult("OK", pnl * 100, pnl / risk, "EOD", entry, len(bars))


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
