"""OHLC loader + cached scan for the Analogues engine (task #55 follow-up).

Kept separate from server/analogues.py so the engine stays pure / network-free /
deterministic. This module owns the (network) data fetch + a TTL cache so the
/api/analogues endpoint doesn't refetch on every request.

Sources tried in order: Stooq CSV (stdlib, long history) → yfinance → local CSV.
"""
from __future__ import annotations

import csv
import io
import time
import urllib.request
from typing import Any

from .analogues import scan

_STOOQ = {
    "SPX": "^spx", "SPY": "spy.us", "NDX": "^ndx", "QQQ": "qqq.us",
    "DJI": "^dji", "RUT": "^rut", "IWM": "iwm.us", "VIX": "^vix",
}
_YF = {"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "RUT": "^RUT", "VIX": "^VIX"}

_SCAN_TTL = 3600.0  # 1h — patterns are EOD/daily, no need to refetch faster
_scan_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _from_stooq(sym: str) -> list[dict]:
    s = _STOOQ.get(sym.upper(), sym.lower())
    url = f"https://stooq.com/q/d/l/?s={s}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    bars = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            bars.append({
                "date": row["Date"], "open": float(row["Open"]),
                "high": float(row["High"]), "low": float(row["Low"]),
                "close": float(row["Close"]), "volume": float(row.get("Volume") or 0),
            })
        except (KeyError, ValueError):
            continue
    return bars


def _from_yfinance(sym: str) -> list[dict]:
    import pandas as pd  # type: ignore
    import yfinance as yf  # type: ignore
    yfs = _YF.get(sym.upper(), sym.upper())
    df = yf.download(yfs, period="max", interval="1d",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    bars = []
    for idx, row in df.iterrows():
        try:
            bars.append({
                "date": str(idx.date()), "open": float(row["Open"]),
                "high": float(row["High"]), "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]) if "Volume" in row else 0.0,
            })
        except (ValueError, TypeError):
            continue
    return bars


def _from_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    bars = []
    for row in rows:
        bars.append({
            "date": row.get("Date") or row.get("date"),
            "open": float(row.get("Open") or row.get("open")),
            "high": float(row.get("High") or row.get("high")),
            "low": float(row.get("Low") or row.get("low")),
            "close": float(row.get("Close") or row.get("close")),
            "volume": float(row.get("Volume") or row.get("volume") or 0),
        })
    return bars


def load_bars(sym: str, csv_path: str | None = None) -> tuple[list[dict], str]:
    if csv_path:
        return _from_csv(csv_path), f"csv:{csv_path}"
    errs = []
    try:
        bars = _from_stooq(sym)
        if len(bars) > 250:
            return bars, "stooq"
        errs.append(f"stooq returned {len(bars)} bars")
    except Exception as e:
        errs.append(f"stooq: {e!r}")
    try:
        return _from_yfinance(sym), "yfinance"
    except Exception as e:
        errs.append(f"yfinance: {e!r}")
    raise RuntimeError(f"Could not load OHLC for {sym}: {'; '.join(errs)}")


def get_scan(sym: str) -> dict[str, Any]:
    """Cached scan for an index/ETF (1h TTL)."""
    now = time.time()
    key = sym.upper()
    hit = _scan_cache.get(key)
    if hit and (now - hit[0]) < _SCAN_TTL:
        return hit[1]
    bars, source = load_bars(key)
    res = scan(bars)
    res["source"] = source
    res["symbol"] = key
    _scan_cache[key] = (now, res)
    return res
