"""Tests for the Terminal-free ThetaData library backend (server/thetadata_lib) and
the library-first/REST-fallback selector in alert_outcomes._fetch_bars_auto.

Mocks the ThetaClient with a synthetic pandas frame — no network, no Terminal, no key.
Run: python scripts/test_thetadata_lib.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from server import alert_outcomes as ao  # noqa: E402
from server import thetadata_lib as tl  # noqa: E402

_ET = ZoneInfo("America/New_York")
_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


class FakeClient:
    """Records calls; returns a preset frame from option_history_quote."""
    def __init__(self, df):
        self._df = df
        self.calls: list[dict] = []

    def option_history_quote(self, **kw):
        self.calls.append(kw)
        return self._df


def _df(rows):
    """rows: list of (hh, mm, bid, ask) on 2026-06-29 ET."""
    return pd.DataFrame({
        "symbol": ["SPY"] * len(rows),
        "expiration": ["2026-07-01"] * len(rows),
        "strike": [737.0] * len(rows),
        "right": ["CALL"] * len(rows),
        "timestamp": [pd.Timestamp(f"2026-06-29 {h:02d}:{m:02d}:00", tz=_ET)
                      for (h, m, _, _) in rows],
        "bid": [b for (_, _, b, _) in rows],
        "ask": [a for (_, _, _, a) in rows],
    })


def _greeks_df(rows, right, spot=746.51):
    """rows: (strike, expiration, gamma, iv, charm, vanna)."""
    n = len(rows)
    return pd.DataFrame({
        "strike": [r[0] for r in rows],
        "expiration": [r[1] for r in rows],
        "right": [right.upper()] * n,
        "delta": [0.5] * n, "gamma": [r[2] for r in rows],
        "theta": [-0.1] * n, "vega": [0.2] * n,
        "implied_vol": [r[3] for r in rows],
        "charm": [r[4] for r in rows], "vanna": [r[5] for r in rows],
        "underlying_price": [spot] * n,
    })


class FakeGreeksClient:
    def __init__(self, calls_df, puts_df):
        self._c, self._p = calls_df, puts_df

    def option_snapshot_greeks_all(self, **kw):
        return self._c if kw.get("right") == "call" else self._p


def _install(df):
    """Force _get_client() to return a FakeClient wrapping df."""
    tl._client = FakeClient(df)
    tl._init_failed = False
    return tl._client


def _uninstall():
    tl._client = None
    tl._init_failed = True  # sticky-off so no real client is built


def test_basic_parse():
    _install(_df([(9, 31, 4.10, 4.14), (9, 32, 4.52, 4.56)]))
    bars = tl.fetch_option_nbbo_bars("SPY", "2026-07-01", 737.0, "C",
                                     "2026-06-29", "2026-06-29")
    check("returns 2 bars", len(bars) == 2, str(len(bars)))
    check("keys present", bars and set(bars[0]) == {"ts", "date", "bid", "ask", "mid"},
          str(bars[0].keys()) if bars else "none")
    check("mid computed", bars and abs(bars[0]["mid"] - 4.12) < 1e-9, str(bars[0]))
    check("date is ET fire day", bars and bars[0]["date"] == "2026-06-29", str(bars[0]))
    check("sorted ascending by ts", bars[0]["ts"] < bars[1]["ts"])
    _uninstall()


def test_nan_and_nonpositive_filtered():
    _install(_df([(9, 30, float("nan"), float("nan")),  # pre-open empty
                  (9, 31, 0.0, 0.0),                     # zero quote
                  (9, 32, 4.52, 4.56)]))                 # real
    bars = tl.fetch_option_nbbo_bars("SPY", "2026-07-01", 737.0, "C",
                                     "2026-06-29", "2026-06-29")
    check("NaN + zero bars dropped, 1 real kept", len(bars) == 1, str(len(bars)))
    _uninstall()


def test_request_mapping():
    fc = _install(_df([(9, 31, 1.0, 1.1)]))
    tl.fetch_option_nbbo_bars("SPY", "2026-07-01", 737.0, "C", "2026-06-29", "2026-06-29")
    tl.fetch_option_nbbo_bars("SPY", "2026-07-01", 737.0, "P", "2026-06-29", "2026-06-29")
    kwc, kwp = fc.calls[0], fc.calls[1]
    check("right C -> 'call'", kwc["right"] == "call", str(kwc.get("right")))
    check("right P -> 'put'", kwp["right"] == "put", str(kwp.get("right")))
    check("strike formatted dollars '737.00'", kwc["strike"] == "737.00", str(kwc.get("strike")))
    check("interval 1m", kwc["interval"] == "1m", str(kwc.get("interval")))
    import datetime as _dt
    check("start/end passed as date objects",
          isinstance(kwc["start_date"], _dt.date) and isinstance(kwc["end_date"], _dt.date),
          f"{type(kwc['start_date'])}")
    _uninstall()


def test_unavailable_returns_empty():
    _uninstall()
    check("no client -> [] (REST fallback path)",
          tl.fetch_option_nbbo_bars("SPY", "2026-07-01", 737.0, "C",
                                    "2026-06-29", "2026-06-29") == [])


def test_auto_prefers_library_then_falls_back():
    # library HAS data -> auto returns library bars, REST not consulted
    _install(_df([(9, 31, 4.10, 4.14)]))
    saved_rest = ao.fetch_option_nbbo_bars
    ao.fetch_option_nbbo_bars = lambda *a, **k: [{"ts": 0, "date": "REST", "bid": 9, "ask": 9, "mid": 9}]
    saved_force = ao._FORCE_REST
    try:
        ao._FORCE_REST = False
        got = ao._fetch_bars_auto("SPY", "2026-07-01", 737.0, "C", "2026-06-29", "2026-06-29")
        check("auto uses library when it has data", len(got) == 1 and got[0]["date"] == "2026-06-29", str(got))
        # library EMPTY -> falls back to REST
        _install(_df([]))
        got2 = ao._fetch_bars_auto("SPY", "2026-07-01", 737.0, "C", "2026-06-29", "2026-06-29")
        check("auto falls back to REST when library empty", got2 and got2[0]["date"] == "REST", str(got2))
        # FORCE_REST -> library skipped entirely even when it has data
        ao._FORCE_REST = True
        _install(_df([(9, 31, 4.10, 4.14)]))
        got3 = ao._fetch_bars_auto("SPY", "2026-07-01", 737.0, "C", "2026-06-29", "2026-06-29")
        check("THETA_FORCE_REST=1 forces REST", got3 and got3[0]["date"] == "REST", str(got3))
    finally:
        ao.fetch_option_nbbo_bars = saved_rest
        ao._FORCE_REST = saved_force
        _uninstall()


def test_snapshot_chain_greeks_all():
    calls = _greeks_df([
        (747.0, "2026-07-01", 0.092, 0.11, -9.7, 0.35),   # real ATM 1DTE
        (750.0, "2026-07-08", 0.050, 0.12, -3.0, 0.20),   # later exp
        (740.0, "2026-07-01", 0.000, 0.00, 0.0, 0.0),     # iv<=0 -> dropped
    ], "call")
    puts = _greeks_df([(745.0, "2026-07-01", 0.10, 0.12, -8.0, -0.3)], "put")
    tl._client = FakeGreeksClient(calls, puts)
    tl._init_failed = False
    try:
        g, spot, ts = tl.snapshot_chain_greeks_all("SPY")
        check("spot from underlying_price", spot == 746.51, str(spot))
        check("iv<=0 row filtered", (740.0, "2026-07-01", "call") not in g)
        k = (747.0, "2026-07-01", "call")
        check("real gamma passthrough (not synth)", g.get(k, {}).get("gamma") == 0.092, str(g.get(k)))
        check("charm + vanna passthrough",
              g[k]["charm"] == -9.7 and g[k]["vanna"] == 0.35, str(g.get(k)))
        check("put side keyed too", (745.0, "2026-07-01", "put") in g)
        # range filter mirrors snapshot_greeks gte/lte
        g2, _, _ = tl.snapshot_chain_greeks_all("SPY", expiration_gte="2026-07-05")
        check("gte filters earlier expirations",
              all(key[1] >= "2026-07-05" for key in g2) and len(g2) >= 1, str(list(g2)))
    finally:
        _uninstall()


def test_greeks_unavailable_returns_empty():
    _uninstall()
    g, spot, ts = tl.snapshot_chain_greeks_all("SPY")
    check("no client -> ({}, None, 0.0)", g == {} and spot is None and ts == 0.0,
          f"{len(g)},{spot},{ts}")


def test_bulk_chunks():
    import datetime as dt
    from scripts.theta_bulk_pull import _chunks
    # 2026-01-01 .. 2026-03-15 with 28-day chunks -> contiguous, none > 28 days
    ch = list(_chunks(dt.date(2026, 1, 1), dt.date(2026, 3, 15), 28))
    check("chunks contiguous + cover the range",
          ch[0][0] == dt.date(2026, 1, 1) and ch[-1][1] == dt.date(2026, 3, 15)
          and all(ch[i + 1][0] == ch[i][1] + dt.timedelta(days=1) for i in range(len(ch) - 1)),
          str(ch))
    check("no chunk exceeds size",
          all((c1 - c0).days + 1 <= 28 for c0, c1 in ch), str([(str(a), str(b)) for a, b in ch]))
    single = list(_chunks(dt.date(2026, 6, 24), dt.date(2026, 6, 24), 28))
    check("single-day range -> one chunk", single == [(dt.date(2026, 6, 24), dt.date(2026, 6, 24))], str(single))


if __name__ == "__main__":
    print("test_thetadata_lib")
    test_basic_parse()
    test_nan_and_nonpositive_filtered()
    test_request_mapping()
    test_unavailable_returns_empty()
    test_auto_prefers_library_then_falls_back()
    test_snapshot_chain_greeks_all()
    test_greeks_unavailable_returns_empty()
    test_bulk_chunks()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
