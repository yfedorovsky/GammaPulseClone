"""0DTE option intraday NBBO-path fetcher (ThetaData v3 quote-history, 1-min).

One call returns the whole bid/ask path for an option from entry to close, so a
TP/stop/time-stop rule can be simulated minute-by-minute with realistic fills
(buy entry ASK, sell at the BID when the rule triggers). Paths cached to
data/opt_path_cache.json. Market-closed days only (weekend/holiday).
"""
from __future__ import annotations
import json
from pathlib import Path
import requests

REST = "http://127.0.0.1:25503"
_CP = Path(__file__).resolve().parent.parent.parent / "data" / "opt_path_cache.json"
_CACHE = json.loads(_CP.read_text()) if _CP.exists() else {}
_DIRTY = 0


def flush():
    _CP.write_text(json.dumps(_CACHE))


def get_path(ticker, date, strike, right, start_hhmm, end_hhmm="15:55:00.000"):
    """Return {'entry_ask': float, 'mins': [int...], 'bids': [float...]} for the
    option from start to end at 1-min, or None. mins = minutes since start."""
    global _DIRTY
    exp = date.replace("-", "")
    k = f"{ticker}|{exp}|{strike}|{right}|{date}|{start_hhmm}|{end_hhmm}"
    if k in _CACHE:
        return _CACHE[k]
    out = None
    try:
        r = requests.get(f"{REST}/v3/option/history/quote", timeout=25, params={
            "symbol": ticker, "expiration": exp, "strike": str(strike), "right": right,
            "start_date": date, "end_date": date,
            "start_time": start_hhmm, "end_time": end_hhmm, "interval": "1m"})
        lines = r.text.splitlines()
        if len(lines) >= 2:
            hdr = [h.strip().strip('"') for h in lines[0].split(",")]
            bi, ai, ti = hdr.index("bid"), hdr.index("ask"), hdr.index("timestamp")
            mins, bids, entry_ask = [], [], None
            t0 = None
            for ln in lines[1:]:
                c = ln.split(",")
                try:
                    bid, ask = float(c[bi]), float(c[ai])
                    ts = c[ti].strip('"')           # 2026-06-18T10:00:00.000
                    hh, mm = int(ts[11:13]), int(ts[14:16])
                    minute = hh * 60 + mm
                except (ValueError, IndexError):
                    continue
                if t0 is None:
                    t0 = minute
                    entry_ask = ask if ask > 0 else None
                mins.append(minute - t0); bids.append(bid)
            if entry_ask and len(bids) >= 5:
                out = {"entry_ask": entry_ask, "mins": mins, "bids": bids}
    except Exception:
        out = None
    _CACHE[k] = out
    _DIRTY += 1
    if _DIRTY % 50 == 0:
        flush()
    return out


def get_path_ba(ticker, date, strike, right, start_hhmm, end_hhmm="15:55:00.000"):
    """Like get_path but returns BOTH bid and ask paths (for sellers who buy back
    at the ask). {'mins':[...], 'bids':[...], 'asks':[...]} or None."""
    global _DIRTY
    exp = date.replace("-", "")
    k = f"BA|{ticker}|{exp}|{strike}|{right}|{date}|{start_hhmm}|{end_hhmm}"
    if k in _CACHE:
        return _CACHE[k]
    out = None
    try:
        r = requests.get(f"{REST}/v3/option/history/quote", timeout=25, params={
            "symbol": ticker, "expiration": exp, "strike": str(strike), "right": right,
            "start_date": date, "end_date": date,
            "start_time": start_hhmm, "end_time": end_hhmm, "interval": "1m"})
        lines = r.text.splitlines()
        if len(lines) >= 2:
            hdr = [h.strip().strip('"') for h in lines[0].split(",")]
            bi, ai, ti = hdr.index("bid"), hdr.index("ask"), hdr.index("timestamp")
            mins, bids, asks, t0 = [], [], [], None
            for ln in lines[1:]:
                c = ln.split(",")
                try:
                    bid, ask = float(c[bi]), float(c[ai])
                    ts = c[ti].strip('"'); minute = int(ts[11:13]) * 60 + int(ts[14:16])
                except (ValueError, IndexError):
                    continue
                if t0 is None:
                    t0 = minute
                mins.append(minute - t0); bids.append(bid); asks.append(ask)
            if len(bids) >= 5:
                out = {"mins": mins, "bids": bids, "asks": asks}
    except Exception:
        out = None
    _CACHE[k] = out
    _DIRTY += 1
    if _DIRTY % 50 == 0:
        flush()
    return out
