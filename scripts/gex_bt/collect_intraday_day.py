"""Collect intraday data for ANY past day (multi-regime replay of the 0DTE grid).

Same shape as collect_intraday_today.py but parameterized by date, with the
0DTE expiration = that date (Friday weeklies), ATM strike nearest the day's
OPEN (from Theta's listed strikes), and the day's own intraday bars/quotes.

Usage: .venv\\Scripts\\python.exe scripts/gex_bt/collect_intraday_day.py 2026-06-05
"""
import json
import sys
import requests
sys.path.insert(0, ".")
from server.config import get_settings

S = get_settings()
TBASE = S.tradier_base_url.rstrip("/")
THDR = {"Authorization": f"Bearer {S.tradier_token}", "Accept": "application/json"}
THETA = "http://127.0.0.1:25503"

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-06-05"
DATE_C = DATE.replace("-", "")
OUT = f"data/intraday_{DATE_C}.json"

# Past-date strikes come from chains.db (Theta list/strikes is current-snapshot
# only). Only the 7 scan names present in chains.db's 116-root universe — the
# liquid semis core (= the actual movers).
import sqlite3
_CON = sqlite3.connect("file:data/chains_ytd_2026.db?mode=ro", uri=True)
NAMES = ["WOLF", "SMCI", "CRDO", "ALAB", "BE", "GLW", "TSM"]
INUNI = set(NAMES)


def fmt_strike(k):
    return f"{k:.3f}".rstrip("0").rstrip(".")


def chains_strikes(sym):
    """Historical 0DTE call strikes for (sym, DATE) from chains.db."""
    rows = _CON.execute(
        "SELECT DISTINCT strike FROM option_eod WHERE root=? AND date=? "
        "AND expiration=? AND right='C'", (sym, DATE, DATE)).fetchall()
    return [r[0] for r in rows]


def und_bars(sym):
    r = requests.get(f"{TBASE}/markets/timesales", headers=THDR, timeout=20, params={
        "symbol": sym, "interval": "5min", "start": f"{DATE} 09:30", "end": f"{DATE} 16:00",
        "session_filter": "open"})
    d = r.json() if r.status_code == 200 else {}
    bars = ((d.get("series") or {}).get("data")) or []
    if isinstance(bars, dict):
        bars = [bars]
    return [{"t": (b.get("time") or "")[11:16], "o": b.get("open"), "h": b.get("high"),
             "l": b.get("low"), "c": b.get("close"), "v": b.get("volume") or 0,
             "vwap": b.get("vwap")} for b in bars]


def opt_path(sym, strike):
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote", timeout=45, params={
            "symbol": sym, "expiration": DATE_C, "strike": fmt_strike(strike), "right": "C",
            "start_date": DATE_C, "end_date": DATE_C,
            "start_time": "09:35:00.000", "end_time": "15:55:00.000", "interval": "5m"})
        lines = [l for l in r.text.splitlines() if l.strip()]
        if len(lines) < 2:
            return []
        h = [x.strip().strip('"') for x in lines[0].split(",")]
        ib, ia, it = h.index("bid"), h.index("ask"), h.index("timestamp")
        out = []
        for ln in lines[1:]:
            c = ln.split(",")
            try:
                out.append({"t": c[it][11:16], "bid": float(c[ib]), "ask": float(c[ia])})
            except (ValueError, IndexError):
                continue
        return out
    except Exception:
        return []


data = {}
for sym in NAMES:
    bars = und_bars(sym)
    if not bars or bars[0].get("o") is None:
        print(f"{sym}: no bars — skip"); continue
    day_open = bars[0]["o"]
    strikes = chains_strikes(sym)
    if not strikes:
        print(f"{sym}: no 0DTE strikes on {DATE} — skip"); continue
    atm = min(strikes, key=lambda s: abs(s - day_open))
    opath = opt_path(sym, atm)
    if not opath:
        print(f"{sym}: no option path — skip"); continue
    last_c = next((b["c"] for b in reversed(bars) if b.get("c") is not None), day_open)
    data[sym] = {"in_universe": sym in INUNI, "open": day_open, "last": last_c,
                 "atm_strike": atm, "expiration": DATE,
                 "underlying_bars": bars, "option_path": opath}
    chg = (last_c - day_open) / day_open * 100 if day_open else 0
    print(f"{sym:5} K={atm:<7} bars={len(bars)} optpts={len(opath)} close_vs_open={chg:+.1f}%")

with open(OUT, "w") as f:
    json.dump(data, f)
print(f"\nsaved {len(data)} names -> {OUT}")
