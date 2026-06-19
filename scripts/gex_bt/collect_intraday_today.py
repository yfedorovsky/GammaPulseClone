"""Collect today's intraday data ONCE for the scan names, for offline strategy
backtesting (so parallel analysis never re-hits the single Theta terminal).

Per name: underlying 5-min bars (Tradier timesales: o/h/l/c/v/vwap) + the 0DTE
ATM-call full 5-min NBBO path (Theta v3 history/quote). Saved to JSON.

Run: .venv\\Scripts\\python.exe scripts/gex_bt/collect_intraday_today.py
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
DATE, DATE_C = "2026-06-18", "20260618"
OUT = "data/intraday_today_20260618.json"

NAMES = ["QUBT", "WOLF", "SMR", "HIMS", "SMCI", "ENTG", "RBLX", "CRDO", "ALAB", "BE",
         "GLW", "TSM", "JBLU", "BFLY", "DJT", "UA", "UAA", "OUST", "DHT", "WRBY",
         "PENG", "TXG", "EQPT", "CHYM", "KMX", "LTH", "FRO", "JOBY", "EC", "RKT"]
INUNI = {"QUBT", "WOLF", "SMR", "HIMS", "SMCI", "ENTG", "RBLX", "CRDO", "ALAB", "BE", "GLW", "TSM"}


def tg(path, **p):
    r = requests.get(f"{TBASE}{path}", params=p, headers=THDR, timeout=20)
    return r.json() if r.status_code == 200 else {}


def fmt_strike(k):
    return f"{k:.3f}".rstrip("0").rstrip(".")


def opt_path(sym, strike):
    """Full 5-min NBBO path for the 0DTE call: [{t,bid,ask}] (t = 'HH:MM')."""
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


def und_bars(sym):
    d = tg("/markets/timesales", symbol=sym, interval="5min",
           start=f"{DATE} 09:30", end=f"{DATE} 16:00", session_filter="open")
    bars = ((d.get("series") or {}).get("data")) or []
    if isinstance(bars, dict):
        bars = [bars]
    out = []
    for b in bars:
        out.append({"t": (b.get("time") or "")[11:16], "o": b.get("open"), "h": b.get("high"),
                    "l": b.get("low"), "c": b.get("close"), "v": b.get("volume") or 0,
                    "vwap": b.get("vwap")})
    return out


data = {}
for sym in NAMES:
    q = (tg("/markets/quotes", symbols=sym).get("quotes") or {}).get("quote") or {}
    spot, op = q.get("last"), q.get("open")
    if not spot:
        print(f"{sym}: no quote — skip"); continue
    exps = (tg("/markets/options/expirations", symbol=sym).get("expirations") or {}).get("date") or []
    exps = exps if isinstance(exps, list) else [exps]
    if DATE not in exps:
        print(f"{sym}: no 0DTE — skip"); continue
    strikes = (tg("/markets/options/strikes", symbol=sym, expiration=DATE).get("strikes") or {}).get("strike") or []
    strikes = strikes if isinstance(strikes, list) else [strikes]
    if not strikes:
        print(f"{sym}: no strikes — skip"); continue
    atm = min(strikes, key=lambda s: abs(s - spot))
    bars = und_bars(sym)
    opath = opt_path(sym, atm)
    if not opath or not bars:
        print(f"{sym}: missing bars({len(bars)})/option({len(opath)}) — skip"); continue
    data[sym] = {"in_universe": sym in INUNI, "open": op, "last": spot, "atm_strike": atm,
                 "expiration": DATE, "underlying_bars": bars, "option_path": opath}
    chg = (spot - op) / op * 100 if op else 0
    print(f"{sym:5} K={atm:<7} bars={len(bars)} optpts={len(opath)} close_vs_open={chg:+.1f}%")

with open(OUT, "w") as f:
    json.dump(data, f)
print(f"\nsaved {len(data)} names -> {OUT}")
