"""Reusable 0DTE option-P&L harness (ThetaData NBBO, realistic fills).

Shared by the short-term options-edge tests (opening-drive, flow-triggered,
momentum). Buy at the ASK, sell at the BID -> the bid/ask spread AND theta decay
are baked into every P&L. Quotes are cached to data/opt_nbbo_cache.json so reruns
are instant and we don't re-hammer the shared ThetaData terminal.

ThetaData v3 (port 25503), market-closed days only (weekend/holiday) per the
shared-terminal rule. 0DTE => expiration = the trade date.
"""
from __future__ import annotations
import json
from pathlib import Path
import requests

REST = "http://127.0.0.1:25503"
_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "opt_nbbo_cache.json"
_CACHE = json.loads(_CACHE_PATH.read_text()) if _CACHE_PATH.exists() else {}
_DIRTY = 0


def _key(ticker, exp, strike, right, date, hhmm):
    return f"{ticker}|{exp}|{strike}|{right}|{date}|{hhmm}"


def flush():
    _CACHE_PATH.write_text(json.dumps(_CACHE))


def nbbo(ticker, exp, strike, right, date, hhmm):
    """(bid, ask) for an option at a moment, or None. exp/date 'YYYYMMDD'/'YYYY-MM-DD'.
    strike in dollars (int/float). right 'C'/'P'. hhmm 'HH:MM:SS.000'."""
    global _DIRTY
    k = _key(ticker, exp, strike, right, date, hhmm)
    if k in _CACHE:
        v = _CACHE[k]
        return tuple(v) if v else None
    try:
        r = requests.get(f"{REST}/v3/option/at_time/quote", timeout=12, params={
            "symbol": ticker, "expiration": exp, "strike": str(strike), "right": right,
            "start_date": date, "end_date": date, "time_of_day": hhmm})
        lines = r.text.splitlines()
        out = None
        if len(lines) >= 2:
            hdr = [h.strip().strip('"') for h in lines[0].split(",")]
            row = lines[1].split(",")
            bi, ai = hdr.index("bid"), hdr.index("ask")
            bid, ask = float(row[bi]), float(row[ai])
            if ask > 0 and bid >= 0:
                out = (bid, ask)
    except Exception:
        out = None
    _CACHE[k] = out
    _DIRTY += 1
    if _DIRTY % 100 == 0:
        flush()
    return tuple(out) if out else None


def long_pnl(ticker, date, strike, right, entry_hhmm, exit_hhmm):
    """Buy a 0DTE option at the entry ASK, sell at the exit BID. Returns
    {entry_ask, exit_bid, pnl_pct} or None if either quote is missing."""
    exp = date.replace("-", "")
    e = nbbo(ticker, exp, strike, right, date, entry_hhmm)
    x = nbbo(ticker, exp, strike, right, date, exit_hhmm)
    if not e or not x:
        return None
    entry_ask, exit_bid = e[1], x[0]
    if entry_ask <= 0:
        return None
    return {"entry_ask": entry_ask, "exit_bid": exit_bid,
            "pnl_pct": (exit_bid - entry_ask) / entry_ask}
