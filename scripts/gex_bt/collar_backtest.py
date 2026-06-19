"""JHEQX collar pin/support backtest — deterministic engine (pre-reg §4-5).

Pre-registration: docs/research/JPM_COLLAR_PREREG.md. This is the DETERMINISTIC
core — no LLM in the numbers. The overnight Workflow runs this across full history
and adversarially reviews the output; the numbers come from here so they are
reproducible and Direction-A clean.

Per quarter-end (last business day of Mar/Jun/Sep/Dec, ThetaData covers ~2012+):
  1. Detect collar legs from SPXW settled OI as-of T-1 (band-gated, look-ahead
     safe — only OI known before the test window) via collar_detector._pick_leg.
  2. Pull the SPX index EOD path into expiry.
  3. H1 (pin/cap): did the run-in / settle land near the short-call strike?
  4. H2 (support): did the long-put strike act as support on the run-in?
  Each measured vs a PLACEBO strike (nearest round number NOT a real leg) so a
  "pin" must beat placebo, not just 50%.

Data path (confirmed 6/18, RTH-closed only):
  OI    GET /v3/option/history/open_interest?symbol=SPXW&expiration=&start_date=&end_date=
  price GET /v3/index/history/eod?symbol=SPX&start_date=&end_date=  (close column)

Usage:
    python scripts/gex_bt/collar_backtest.py 2024 2025      # year range (inclusive)
    python scripts/gex_bt/collar_backtest.py 2012 2025 --json out.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server.collar_detector import (  # noqa: E402
    _pick_leg, _SHORT_CALL_BAND, _LONG_PUT_BAND, _SHORT_PUT_BAND,
)

REST = "http://127.0.0.1:25503"
RUNIN_DAYS = 10            # trading-day window into expiry we test
PIN_BAND_PCT = 0.5         # |close - strike|/spot <= this = "at the level"


# ── calendar ─────────────────────────────────────────────────────────

def _last_business_day(year: int, month: int) -> dt.date:
    d = dt.date(year, 12, 31) if month == 12 else dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    try:
        from server.market_calendar import is_market_holiday
        while d.weekday() >= 5 or is_market_holiday(d):
            d -= dt.timedelta(days=1)
    except Exception:
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
    return d


def quarter_ends(y0: int, y1: int) -> list[dt.date]:
    out = []
    for y in range(y0, y1 + 1):
        for m in (3, 6, 9, 12):
            out.append(_last_business_day(y, m))
    today = dt.date.today()
    return [d for d in out if d < today]   # only settled quarters


# ── ThetaData v3 ─────────────────────────────────────────────────────

def _ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def fetch_oi(expiry: dt.date, asof: dt.date) -> dict:
    """SPXW settled OI as-of `asof`, keyed (('C'|'P'), strike). Empty on failure."""
    r = requests.get(f"{REST}/v3/option/history/open_interest", timeout=60, params={
        "symbol": "SPXW", "expiration": _ymd(expiry),
        "start_date": _ymd(asof), "end_date": _ymd(asof)})
    if r.status_code != 200:
        return {}
    out: dict[tuple[str, float], float] = {}
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    for ln in lines[1:]:
        c = ln.split(",")
        if len(c) < 6:
            continue
        try:
            strike = float(c[2]); right = c[3].strip().strip('"')[:1].upper()
            oi = float(c[5])
        except (ValueError, IndexError):
            continue
        if right in ("C", "P"):
            out[(right, strike)] = max(out.get((right, strike), 0.0), oi)
    return out


# SPX daily price path comes from the LOCAL analogues dataset (yfinance ^GSPC,
# 1927+, true daily OHLC), NOT ThetaData /v3/index/history/eod — the latter is
# recency-tiered on our subscription (2024+ only; 2023 and earlier return 403
# "VALUE/PROFESSIONAL subscription required"), which would gut the sample to ~8
# quarters. The local set restores ~46 quarters (bounded by SPXW OI from 2014-09)
# and gives real daily lows for the H2 support-touch test.
_SPX_DAILY: dict[dt.date, dict] | None = None


def _spx_daily() -> dict[dt.date, dict]:
    global _SPX_DAILY
    if _SPX_DAILY is None:
        from server.analogue_data import load_bars
        bars, _src = load_bars("SPX")
        _SPX_DAILY = {dt.date.fromisoformat(b["date"][:10]): b for b in bars}
    return _SPX_DAILY


def fetch_spx_eod(start: dt.date, end: dt.date) -> list[tuple[dt.date, float, float, float]]:
    """Local SPX daily bars in [start, end] as (date, close, low, high)."""
    daily = _spx_daily()
    out = []
    for d, b in daily.items():
        if start <= d <= end and b.get("close"):
            out.append((d, float(b["close"]), float(b["low"]), float(b["high"])))
    return sorted(out)


# ── per-event analysis ───────────────────────────────────────────────

def _prev_business_day(d: dt.date) -> dt.date:
    p = d - dt.timedelta(days=1)
    try:
        from server.market_calendar import is_market_holiday
        while p.weekday() >= 5 or is_market_holiday(p):
            p -= dt.timedelta(days=1)
    except Exception:
        while p.weekday() >= 5:
            p -= dt.timedelta(days=1)
    return p


def _placebo_strike(spot: float, real: set[float], step: float = 100.0) -> float:
    """Nearest round-`step` strike to spot that is NOT a real collar leg."""
    base = round(spot / step) * step
    for off in range(0, 20):
        for cand in (base + off * step, base - off * step):
            if cand not in real and cand > 0:
                return cand
    return base


def analyze_event(expiry: dt.date) -> dict | None:
    asof = _prev_business_day(expiry)
    oi = fetch_oi(expiry, asof)
    if not oi:
        return {"expiry": expiry.isoformat(), "error": "no_oi"}
    # spot as-of T-1 = SPX close on asof (look back a couple weeks for the run-in)
    eod = fetch_spx_eod(asof - dt.timedelta(days=21), expiry)
    if not eod:
        return {"expiry": expiry.isoformat(), "error": "no_price"}
    asof_close = next((c for d, c, _lo, _hi in reversed(eod) if d <= asof), None)
    if not asof_close:
        return {"expiry": expiry.isoformat(), "error": "no_asof_close"}

    vals = sorted(oi.values())
    med = vals[len(vals) // 2] if vals else 0.0
    sc = _pick_leg(oi, "C", asof_close, _SHORT_CALL_BAND, med)
    lp = _pick_leg(oi, "P", asof_close, _LONG_PUT_BAND, med)
    sp = _pick_leg(oi, "P", asof_close, _SHORT_PUT_BAND, med)

    # run-in path = last RUNIN_DAYS bars up to & including expiry
    path = [(d, c, lo, hi) for d, c, lo, hi in eod if d <= expiry][-RUNIN_DAYS:]
    settle = path[-1][1] if path else None

    res = {
        "expiry": expiry.isoformat(), "asof": asof.isoformat(),
        "asof_close": round(asof_close, 2), "settle": round(settle, 2) if settle else None,
        "short_call": sc, "long_put": lp, "short_put": sp,
        "runin_n": len(path),
    }
    real = {leg["strike"] for leg in (sc, lp, sp) if leg}

    # H1 pin/cap: did the settle land within PIN_BAND of the short-call strike,
    # vs a placebo round strike near the cap?
    if sc and settle:
        cap = sc["strike"]
        plc = _placebo_strike(cap, real)
        res["h1_cap_dist_pct"] = round((settle - cap) / settle * 100, 3)
        res["h1_pin_hit"] = abs(settle - cap) / settle * 100 <= PIN_BAND_PCT
        res["h1_placebo_strike"] = plc
        res["h1_placebo_hit"] = abs(settle - plc) / settle * 100 <= PIN_BAND_PCT
    # H2 support: did the run-in (real daily) low touch the long-put strike and
    # hold (close above it at settle)?
    if lp and path:
        sup = lp["strike"]
        run_low = min(lo for _, _, lo, _ in path)
        res["h2_run_low"] = round(run_low, 2)
        res["h2_touched"] = run_low <= sup
        res["h2_held"] = (run_low <= sup) and settle > sup
    return res


# ── driver ───────────────────────────────────────────────────────────

def run(y0: int, y1: int) -> dict:
    events = quarter_ends(y0, y1)
    rows = []
    for e in events:
        try:
            r = analyze_event(e)
        except Exception as ex:
            r = {"expiry": e.isoformat(), "error": repr(ex)}
        rows.append(r)
        tag = r.get("error") or (
            f"cap={r.get('short_call', {}) and r['short_call']['strike']} "
            f"settle={r.get('settle')} pin={r.get('h1_pin_hit')} "
            f"plc={r.get('h1_placebo_hit')} h2held={r.get('h2_held')}")
        print(f"  {e.isoformat()}  {tag}", flush=True)
    # aggregate H1/H2 (placebo-relative)
    ok = [r for r in rows if "h1_pin_hit" in r]
    pin = sum(1 for r in ok if r["h1_pin_hit"])
    plc = sum(1 for r in ok if r.get("h1_placebo_hit"))
    h2 = [r for r in rows if "h2_held" in r]
    held = sum(1 for r in h2 if r["h2_held"])
    summary = {
        "events": len(rows), "analyzable_h1": len(ok),
        "h1_pin_hits": pin, "h1_placebo_hits": plc,
        "h1_pin_rate": round(pin / len(ok), 3) if ok else None,
        "h1_placebo_rate": round(plc / len(ok), 3) if ok else None,
        "h2_events": len(h2), "h2_held": held,
        "h2_hold_rate": round(held / len(h2), 3) if h2 else None,
    }
    print("\n=== SUMMARY (descriptive — full stats/placebo/Holm in the Workflow) ===")
    print(json.dumps(summary, indent=2))
    return {"summary": summary, "events": rows}


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    y0 = int(a[0]) if a else 2024
    y1 = int(a[1]) if len(a) > 1 else y0
    out = run(y0, y1)
    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {p}")
