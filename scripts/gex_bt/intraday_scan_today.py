"""Today's Finviz-scan names — intraday 0DTE ATM-call returns, two entries.

Same-day scalp (the trade my EOD backtest could NOT see):
  Entry A: fixed 11:45 ET (ask)
  Entry B: first 5-min close that crosses ABOVE session VWAP after 10:00 (ask)
  Exit:    15:50 ET (bid)   — ask-in / bid-out = real spread

Underlying intraday bars (VWAP + context) from Tradier timesales; option NBBO
from the local Theta Terminal v3 (port 25503). One day, small n — this is a
distribution sniff-test (winners AND faders), NOT a backtest. Semis-tilted by
universe, as expected.

Run: .venv\\Scripts\\python.exe scripts/gex_bt/intraday_scan_today.py
"""
import sys
import requests
from datetime import datetime
sys.path.insert(0, ".")
from server.config import get_settings

S = get_settings()
TBASE = S.tradier_base_url.rstrip("/")
THDR = {"Authorization": f"Bearer {S.tradier_token}", "Accept": "application/json"}
THETA = "http://127.0.0.1:25503"
DATE = "2026-06-18"
DATE_C = "20260618"
EXIT_TOD = "15:50:00.000"

# 12 in-universe scan names (liquid, tech/semis-tilted)
NAMES = ["QUBT", "WOLF", "SMR", "HIMS", "SMCI", "ENTG", "RBLX", "CRDO", "ALAB", "BE", "GLW", "TSM"]


def tg(path, **params):
    r = requests.get(f"{TBASE}{path}", params=params, headers=THDR, timeout=20)
    return r.json() if r.status_code == 200 else {}


def _fmt_strike(k):
    """Theta v3 wants strike in dollars, decimals OK: 660.0->'660', 30.5->'30.5'."""
    return f"{k:.3f}".rstrip("0").rstrip(".")


def theta_q(sym, strike, tod):
    """(bid, ask) for the 0DTE call at time-of-day, or (None, None)."""
    try:
        r = requests.get(f"{THETA}/v3/option/at_time/quote", timeout=10, params={
            "symbol": sym, "expiration": DATE_C, "strike": _fmt_strike(strike),
            "right": "C", "start_date": DATE_C, "end_date": DATE_C, "time_of_day": tod})
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return None, None
        h = [x.strip().strip('"') for x in lines[0].split(",")]
        c = lines[-1].split(",")
        bid = float(c[h.index("bid")]); ask = float(c[h.index("ask")])
        return bid, ask
    except Exception:
        return None, None


def session_vwap_cross(sym):
    """First 5-min close crossing above session VWAP after 10:00 -> 'HH:MM:00.000'."""
    d = tg("/markets/timesales", symbol=sym, interval="5min",
           start=f"{DATE} 09:30", end=f"{DATE} 15:45", session_filter="open")
    bars = ((d.get("series") or {}).get("data")) or []
    if isinstance(bars, dict):
        bars = [bars]
    cum_pv = cum_v = 0.0
    prev_above = None
    for b in bars:
        hi, lo, cl, vol = b.get("high"), b.get("low"), b.get("close"), b.get("volume") or 0
        if cl is None:
            continue
        tp = (hi + lo + cl) / 3.0 if (hi and lo) else cl
        cum_pv += tp * vol; cum_v += vol
        vwap = cum_pv / cum_v if cum_v else cl
        above = cl > vwap
        t = (b.get("time") or "")[11:16]  # HH:MM
        if prev_above is not None and not prev_above and above and t >= "10:00":
            return f"{t}:00.000"
        prev_above = above
    return None


def pct(x):
    return f"{x*100:+.0f}%" if x is not None else "  n/a"


rows = []
for sym in NAMES:
    q = (tg("/markets/quotes", symbols=sym).get("quotes") or {}).get("quote") or {}
    spot, op = q.get("last"), q.get("open")
    if not spot:
        print(f"{sym}: no quote"); continue
    # nearest expiration, prefer 0DTE
    exps = (tg("/markets/options/expirations", symbol=sym).get("expirations") or {}).get("date") or []
    exps = exps if isinstance(exps, list) else [exps]
    is0 = DATE in exps
    # ATM strike from Tradier strikes for today's expiry (fallback: round spot)
    strikes = (tg("/markets/options/strikes", symbol=sym, expiration=DATE).get("strikes") or {}).get("strike") or []
    strikes = [s for s in (strikes if isinstance(strikes, list) else [strikes])]
    atm = min(strikes, key=lambda s: abs(s - spot)) if strikes else round(spot)
    # exit
    exit_bid, _ = theta_q(sym, atm, EXIT_TOD)
    # entry A: 11:45 ask
    _, a_ask = theta_q(sym, atm, "11:45:00.000")
    # exit_bid==0.0 is a REAL worthless expiry (-100%), NOT missing data —
    # count it, or the distribution is survivorship-biased to the runners.
    retA = (exit_bid - a_ask) / a_ask if (exit_bid is not None and a_ask) else None
    # entry B: vwap cross ask
    xt = session_vwap_cross(sym)
    b_ask = theta_q(sym, atm, xt)[1] if xt else None
    retB = (exit_bid - b_ask) / b_ask if (exit_bid is not None and b_ask) else None
    up1145 = (spot - op) / op if op else None  # EOD proxy of intraday strength
    rows.append((sym, "0DTE" if is0 else "near", atm, retA, retB, xt))
    print(f"{sym:5} {'0DTE' if is0 else 'near':4} K={atm:<7} "
          f"A(11:45)={pct(retA)}  B(vwapX@{xt or '--':>5})={pct(retB)}  "
          f"entryA_ask={a_ask}  entryB_ask={b_ask}  exit_bid={exit_bid}")

# aggregate
def agg(idx, label):
    vals = [r[idx] for r in rows if r[idx] is not None]
    if not vals:
        print(f"  {label}: n=0"); return
    n = len(vals); mean = sum(vals)/n
    vs = sorted(vals); med = vs[n//2]
    win = sum(1 for v in vals if v > 0)/n
    print(f"  {label}: n={n}  mean={mean*100:+.0f}%  median={med*100:+.0f}%  win={win*100:.0f}%  "
          f"best={max(vals)*100:+.0f}%  worst={min(vals)*100:+.0f}%")

print("\n=== DISTRIBUTION (0DTE ATM call, ask-in/bid-out, exit 15:50) ===")
agg(3, "A  fixed 11:45 ")
agg(4, "B  VWAP-cross  ")
print("\nNOTE: one day, semis-tilted, n<=12 — sniff-test for winners-vs-faders, not an edge.")
