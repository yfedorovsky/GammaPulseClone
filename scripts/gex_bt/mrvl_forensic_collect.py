"""MRVL 6/18 forensic: reconstruct the full day (price + flow + GEX/charm) at
fine granularity, to correlate and find what we missed on an OPEX trend day.

Local sources (fast): Tradier 1-min bars, our flow_alerts, daily_oi_snapshot OI.
GEX/charm reconstructed per 5-min from OI + bar spot + BSM (server.gex funcs,
true intraday seconds-to-close T). Flat-IV approximation for the SHAPE — king/
floor are OI-driven, so location is robust; magnitudes are approximate. The OPRA
validated-side timeline (one ThetaData pass) is added separately.

Out -> data/mrvl_forensic_20260618.json   Run: .venv\\Scripts\\python.exe ...
"""
import json
import sqlite3
import time
import requests
import sys
from datetime import datetime
sys.path.insert(0, ".")
from server.config import get_settings
from server.gex import _bsm_gamma, _bsm_charm

S = get_settings()
TB = S.tradier_base_url.rstrip("/")
TH = {"Authorization": f"Bearer {S.tradier_token}", "Accept": "application/json"}
DATE = "2026-06-18"
IV = 0.55          # flat-IV approximation for the GEX/charm shape
R, Q = 0.045, 0.0
CLOSE_H = 16

# --- 1. underlying 1-min bars ---
r = requests.get(f"{TB}/markets/timesales", headers=TH, timeout=25, params={
    "symbol": "MRVL", "interval": "1min", "start": f"{DATE} 09:30",
    "end": f"{DATE} 16:05", "session_filter": "open"})
bars = [{"t": b["time"][11:16], "o": b["open"], "h": b["high"], "l": b["low"],
         "c": b["close"], "v": b["volume"]} for b in
        ((r.json().get("series") or {}).get("data") or [])]

# --- 2. our flow_alerts ---
con = sqlite3.connect("file:snapshots.db?mode=ro", uri=True)
flow = [{"t": time.strftime("%H:%M:%S", time.localtime(x[0])), "strike": x[1],
         "type": x[2], "side": x[3], "sent": x[4], "notional": x[5],
         "vol_oi": x[6], "conv": x[7], "spot_rec": x[8]} for x in con.execute(
    "SELECT ts,strike,option_type,side,sentiment,notional,vol_oi,conviction,spot "
    "FROM flow_alerts WHERE ticker='MRVL' AND date(ts,'unixepoch','localtime')=? "
    "ORDER BY ts", (DATE,))]

# --- 3. OI per strike (latest capture per strike+type) ---
oi_rows = con.execute(
    "SELECT strike, option_type, oi, captured_ts FROM daily_oi_snapshot "
    "WHERE ticker='MRVL' AND exp=? ORDER BY captured_ts", (DATE,)).fetchall()
con.close()
oi = {}  # (strike, 'C'/'P') -> latest oi
for strike, otype, o, cts in oi_rows:
    oi[(strike, (otype or "")[:1].upper())] = o
strikes = sorted({k[0] for k in oi})

# --- 4. GEX/charm timeline per 5-min bar ---
def T_years(hhmm):
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    secs = (CLOSE_H * 3600) - (h * 3600 + m * 60)
    return max(secs, 300) / (365.0 * 24 * 3600)

gex_ts = []
for b in bars[::5]:
    spot = b["c"]
    if not spot:
        continue
    T = T_years(b["t"])
    per = {}
    net_gex = net_charm = 0.0
    for K in strikes:
        for typ, sign in (("C", 1.0), ("P", -1.0)):
            o = oi.get((K, typ), 0)
            if not o or abs(K - spot) / spot > 0.12:
                continue
            g = _bsm_gamma(spot, K, IV, T)
            c = _bsm_charm(spot, K, IV, T, is_call=(typ == "C"))
            gd = g * o * 100 * spot * spot * 0.01 * sign
            cd = c * o * 100 * spot * sign
            per[K] = per.get(K, 0.0) + gd
            net_gex += gd
            net_charm += cd
    # king = max +GEX strike; floor = max +GEX below spot; ceiling above
    pos = [(k, v) for k, v in per.items() if v > 0]
    king = max(pos, key=lambda x: x[1])[0] if pos else None
    below = [(k, v) for k, v in pos if k < spot]
    above = [(k, v) for k, v in pos if k > spot]
    floor = max(below, key=lambda x: x[1])[0] if below else None
    ceiling = max(above, key=lambda x: x[1])[0] if above else None
    gex_ts.append({"t": b["t"], "spot": round(spot, 2), "net_gex": round(net_gex, 0),
                   "net_charm": round(net_charm, 0), "king": king, "floor": floor,
                   "ceiling": ceiling})

out = {"date": DATE, "bars_1min": bars, "flow_alerts": flow,
       "oi_by_strike": {f"{k[0]}{k[1]}": v for k, v in oi.items()},
       "gex_charm_timeline": gex_ts}
with open("data/mrvl_forensic_20260618.json", "w") as f:
    json.dump(out, f)
print(f"bars={len(bars)} flow={len(flow)} oi_strikes={len(strikes)} gex_pts={len(gex_ts)}")
print("\n=== GEX/charm timeline (5-min) — king/floor evolution + the break ===")
for g in gex_ts:
    print(f"  {g['t']}  spot={g['spot']:>7}  king={g['king']}  floor={g['floor']}  "
          f"ceil={g['ceiling']}  netGEX={g['net_gex']/1e6:+.0f}M  netCharm={g['net_charm']/1e6:+.1f}M")
