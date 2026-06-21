"""ThetaData v3 option data-access layer for Layer-2 translation.

Split out of option_translate.py so the "talk to ThetaData / pick a contract"
concerns live apart from the "run trades / score / render verdict" logic. All
functions are read-only against the local Theta terminal; no writes anywhere.

v3 format reminders (the terminal's list endpoints return DASHED dates in col 1,
but the quote endpoints accept YYYYMMDD): see scripts/theta_v3_query.py.
"""
from __future__ import annotations
import io
import time
import numpy as np
import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# CONFIG (was scattered magic numbers in option_translate.py)
# --------------------------------------------------------------------------- #
THETA_URL = "http://127.0.0.1:25503"   # local Theta terminal
GET_TIMEOUT = 20                       # default per-request timeout (seconds)
GET_RETRIES = 2                        # extra attempts on timeout / non-200
RETRY_BACKOFF = 0.4                    # seconds * (attempt+1) between retries
TOD_EOD = "15:55:00.000"               # near-close NBBO snapshot time (ET)
MIN_DTE_CAL = 21                       # min calendar days to expiry at entry

_EXP_CACHE: dict = {}
_STR_CACHE: dict = {}


# --------------------------------------------------------------------------- #
# low-level GET with structured retry/backoff
# --------------------------------------------------------------------------- #
def _get(url, params, timeout=GET_TIMEOUT, retries=GET_RETRIES):
    """GET returning response text on HTTP 200, else None after `retries` attempts.

    Retries on transient failures — connection/timeout exceptions AND non-200
    responses (the terminal occasionally 5xx's under load). A clean 404-style
    'no data' still ends up None, which every caller already treats as 'skip'.
    The last failure reason is intentionally swallowed (callers only need
    success/None), but the retry prevents a single transient blip from silently
    dropping an entry and biasing the sample.
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


# --------------------------------------------------------------------------- #
# contract discovery
# --------------------------------------------------------------------------- #
def expirations(symbol: str) -> list[int]:
    """Sorted list of available expirations (YYYYMMDD ints). Cached per symbol."""
    if symbol in _EXP_CACHE:
        return _EXP_CACHE[symbol]
    txt = _get(f"{THETA_URL}/v3/option/list/expirations", {"symbol": symbol})
    out = []
    if txt:
        # format: symbol,expiration  with expiration in col 1 as "YYYY-MM-DD"
        for ln in txt.splitlines()[1:]:
            parts = [p.strip().strip('"') for p in ln.split(",")]
            if len(parts) >= 2:
                t = parts[1].replace("-", "")
                if t.isdigit() and len(t) == 8:
                    out.append(int(t))
    out = sorted(out)
    _EXP_CACHE[symbol] = out
    return out


def strikes(symbol: str, exp: int) -> list[float]:
    """Sorted list of dollar strikes for (symbol, expiration). Cached."""
    key = (symbol, exp)
    if key in _STR_CACHE:
        return _STR_CACHE[key]
    txt = _get(f"{THETA_URL}/v3/option/list/strikes",
               {"symbol": symbol, "expiration": exp})
    out = []
    if txt:
        # format: symbol,strike  with strike in col 1 in dollars (e.g. 480.000)
        for ln in txt.splitlines()[1:]:
            parts = [p.strip().strip('"') for p in ln.split(",")]
            if len(parts) >= 2:
                try:
                    out.append(float(parts[1]))
                except ValueError:
                    pass
    out = sorted(out)
    _STR_CACHE[key] = out
    return out


# --------------------------------------------------------------------------- #
# NBBO (instant snapshot, with 1-min history fallback)
# --------------------------------------------------------------------------- #
def _nbbo_instant(symbol, exp, strike, right, date_int, tod=TOD_EOD):
    txt = _get(f"{THETA_URL}/v3/option/at_time/quote",
               {"symbol": symbol, "expiration": exp, "strike": f"{strike:.3f}",
                "right": right, "start_date": date_int, "end_date": date_int,
                "time_of_day": tod})
    if not txt:
        return None
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return None
    if df.empty:
        return None
    cols = {c.lower().strip(): c for c in df.columns}
    if "bid" not in cols or "ask" not in cols:
        return None
    bid = float(df[cols["bid"]].iloc[-1]); ask = float(df[cols["ask"]].iloc[-1])
    if not (np.isfinite(bid) and np.isfinite(ask)) or ask <= 0:
        return None
    return bid, ask


def _nbbo_hist(symbol, exp, strike, right, date_int, cutoff_hhmm="15:55"):
    """Fallback: last 1-min NBBO bar at/before cutoff. Recovers entries the instant
    quote misses (e.g. an illiquid ATM strike with no print exactly @15:55)."""
    txt = _get(f"{THETA_URL}/v3/option/history/quote",
               {"symbol": symbol, "expiration": exp, "strike": f"{strike:.3f}",
                "right": right, "start_date": date_int, "end_date": date_int,
                "interval": "1m"}, timeout=30)
    if not txt:
        return None
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return None
    if df.empty or "timestamp" not in {c.lower() for c in df.columns}:
        return None
    cols = {c.lower().strip(): c for c in df.columns}
    ts = df[cols["timestamp"]].astype(str)
    hhmm = ts.str.slice(11, 16)
    sub = df[(hhmm <= cutoff_hhmm)]
    if sub.empty:
        sub = df
    bid = float(sub[cols["bid"]].iloc[-1]); ask = float(sub[cols["ask"]].iloc[-1])
    if not (np.isfinite(bid) and np.isfinite(ask)) or ask <= 0:
        return None
    return bid, ask


def nbbo_at(symbol, exp, strike, right, date_int, tod=TOD_EOD):
    """(bid, ask) near EOD: instant quote first, then 1-min history fallback."""
    r = _nbbo_instant(symbol, exp, strike, right, date_int, tod)
    if r is not None:
        return r
    return _nbbo_hist(symbol, exp, strike, right, date_int)


# --------------------------------------------------------------------------- #
# date + expiry helpers
# --------------------------------------------------------------------------- #
def to_yyyymmdd(ts) -> int:
    return int(pd.Timestamp(ts).strftime("%Y%m%d"))


def add_cal_days(date_int, days) -> int:
    return to_yyyymmdd(pd.Timestamp(str(date_int)) + pd.Timedelta(days=days))


def is_monthly(exp_int) -> bool:
    """Standard monthly OPEX = 3rd Friday (weekday Fri, day 15-21). These carry the
    densest OPRA NBBO; weeklies are thinner and drive most of the no-NBBO skips."""
    ts = pd.Timestamp(str(exp_int))
    return ts.weekday() == 4 and 15 <= ts.day <= 21


def pick_exp(exps, min_int, prefer_monthly=True, max_extra_days=45):
    """Choose an expiration >= min_int. Prefer the nearest standard MONTHLY within
    `max_extra_days` of min_int (denser NBBO -> fewer skips, less weekly gamma noise);
    fall back to the nearest listed expiry. Returns (exp_int, kind) with kind in
    {'monthly','weekly'} (None,None if nothing qualifies)."""
    cand = [e for e in exps if e >= min_int]
    if not cand:
        return None, None
    if prefer_monthly:
        hi = add_cal_days(min_int, max_extra_days)
        monthlies = [e for e in cand if e <= hi and is_monthly(e)]
        if monthlies:
            return monthlies[0], "monthly"
    e0 = cand[0]
    return e0, ("monthly" if is_monthly(e0) else "weekly")
