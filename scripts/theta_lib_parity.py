"""Parity gate: ThetaData Python library vs the live Terminal REST path.

The P&L backfill (server/alert_outcomes.fetch_option_nbbo_bars + compute_option_outcome)
is the keystone we grade the whole engine on. Before cutting it over to the Terminal-free
Python library, this harness proves the library reproduces the REST path to the cent:
same NBBO bars, same ASK-IN/BID-OUT realized outcome, same short-horizon markout.

Runs both transports for the same contracts in one process and diffs them. REST needs the
Terminal up at 25503; the library needs THETADATA_API_KEY (loaded from .env). If they
disagree, DO NOT cut over.

    python scripts/theta_lib_parity.py

ASCII-only output (Windows cp1252 console). Read-only; no DB writes.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_outcomes import (  # noqa: E402
    compute_option_outcome,
    fetch_option_nbbo_bars,
)

_ENV = str(ROOT / ".env")

# (symbol, expiration, strike, right, date) — hand-picked liquid contracts with a
# full RTH of bars. Covers call + put + the SPXW root-mapping path.
_CASES = [
    ("SPY", "2026-07-01", 737.0, "C", "2026-06-29"),
    ("SPY", "2026-07-01", 737.0, "P", "2026-06-29"),
    ("SPY", "2026-06-30", 745.0, "C", "2026-06-29"),
]

# Fields compute_option_outcome returns that must match exactly.
_OUTCOME_KEYS = (
    "opt_high_after", "opt_low_after", "opt_mfe_pct", "opt_mae_pct",
    "opt_close_eod", "opt_close_next_day", "opt_entry_mid",
    "opt_mark_1m_pct", "opt_mark_5m_pct", "opt_mark_15m_pct", "_entry_ask",
)


def _lib_client():
    from thetadata import ThetaClient
    return ThetaClient(dotenv_path=_ENV, dataframe_type="pandas")


def lib_fetch_option_nbbo_bars(client, symbol, expiration, strike, right,
                               start_date, end_date):
    """Library adapter: returns the SAME [{ts,date,bid,ask,mid}] shape as the REST
    fetch_option_nbbo_bars. This is the candidate that will move into
    server/thetadata_lib.py once parity holds."""
    r = "call" if str(right).upper().startswith("C") else "put"
    d0 = _dt.date.fromisoformat(start_date)
    d1 = _dt.date.fromisoformat(end_date)
    df = client.option_history_quote(
        symbol=symbol, expiration=expiration, strike=f"{float(strike):.2f}",
        right=r, interval="1m", start_date=d0, end_date=d1,
    )
    if df is None or len(df) == 0:
        return []
    out = []
    for row in df.itertuples(index=False):
        bid, ask = row.bid, row.ask
        # library gives NaN for pre-open/empty bars; same bid>0 & ask>0 gate as REST
        if not (bid > 0) or not (ask > 0):
            continue
        pdt = row.timestamp.to_pydatetime()  # already tz-aware ET
        out.append({
            "ts": pdt.timestamp(),
            "date": pdt.strftime("%Y-%m-%d"),
            "bid": float(bid), "ask": float(ask),
            "mid": (float(bid) + float(ask)) / 2.0,
        })
    out.sort(key=lambda b: b["ts"])
    return out


def _bars_diff(rest, lib):
    """Compare two bar lists keyed by integer epoch second. Returns
    (n_rest, n_lib, n_common, max_bid_diff, max_ask_diff, n_only_rest, n_only_lib)."""
    r = {int(round(b["ts"])): b for b in rest}
    l = {int(round(b["ts"])): b for b in lib}
    common = r.keys() & l.keys()
    max_bid = max((abs(r[k]["bid"] - l[k]["bid"]) for k in common), default=0.0)
    max_ask = max((abs(r[k]["ask"] - l[k]["ask"]) for k in common), default=0.0)
    return (len(r), len(l), len(common), max_bid, max_ask,
            len(r.keys() - l.keys()), len(l.keys() - r.keys()))


def _fire_ts(date_str, hh=10, mm=0):
    from zoneinfo import ZoneInfo
    d = _dt.date.fromisoformat(date_str)
    return _dt.datetime(d.year, d.month, d.day, hh, mm,
                        tzinfo=ZoneInfo("America/New_York")).timestamp()


def main():
    print("=" * 72)
    print("THETADATA LIBRARY vs REST PARITY GATE")
    print("=" * 72)
    client = _lib_client()
    ok = True
    for (sym, exp, strike, right, date) in _CASES:
        label = f"{sym} {exp} {strike:g}{right} @ {date}"
        print(f"\n--- {label} ---")
        rest = fetch_option_nbbo_bars(sym, exp, strike, right, date, date)
        lib = lib_fetch_option_nbbo_bars(client, sym, exp, strike, right, date, date)
        nR, nL, nC, mbid, mask, oR, oL = _bars_diff(rest, lib)
        print(f"  bars: REST={nR}  LIB={nL}  common={nC}  only_rest={oR}  only_lib={oL}")
        print(f"  max bid diff={mbid:.4f}  max ask diff={mask:.4f}")
        bars_ok = (nR > 0 and abs(nR - nL) <= 1 and mbid < 0.005 and mask < 0.005
                   and oR <= 1 and oL <= 1)
        if not rest:
            print("  [WARN] REST returned no bars (Terminal down or no data) - skipping")
            continue

        ft = _fire_ts(date)
        oc_r = compute_option_outcome(rest, ft, date)
        oc_l = compute_option_outcome(lib, ft, date)
        if oc_r is None or oc_l is None:
            print(f"  [WARN] outcome None (REST={oc_r is None}, LIB={oc_l is None})")
            outcome_ok = (oc_r is None) == (oc_l is None)
        else:
            diffs = []
            for k in _OUTCOME_KEYS:
                a, b = oc_r.get(k), oc_l.get(k)
                if a is None or b is None:
                    if a != b:
                        diffs.append(f"{k}: REST={a} LIB={b}")
                elif abs(float(a) - float(b)) > 0.011:
                    diffs.append(f"{k}: REST={a} LIB={b}")
            outcome_ok = not diffs
            print(f"  outcome: REST mfe={oc_r['opt_mfe_pct']} mae={oc_r['opt_mae_pct']} "
                  f"mark1m={oc_r.get('opt_mark_1m_pct')} mark5m={oc_r.get('opt_mark_5m_pct')}")
            print(f"           LIB  mfe={oc_l['opt_mfe_pct']} mae={oc_l['opt_mae_pct']} "
                  f"mark1m={oc_l.get('opt_mark_1m_pct')} mark5m={oc_l.get('opt_mark_5m_pct')}")
            for d in diffs:
                print(f"    MISMATCH {d}")
        verdict = bars_ok and outcome_ok
        ok = ok and verdict
        print(f"  ==> {'PASS' if verdict else 'FAIL'}")

    print("\n" + "=" * 72)
    print("PARITY GATE: " + ("PASS - safe to cut the backfill over to the library"
                             if ok else "FAIL - do NOT cut over; investigate diffs"))
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
