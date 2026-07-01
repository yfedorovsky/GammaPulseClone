"""RTH probe: is Tradier's SPX quote real-time or 15-min delayed?

SPX is a computed index (no tape), so "real-time" here means: does the disseminated
value track a KNOWN real-time reference, or trail it? SPY trades on the consolidated
tape and is unambiguously real-time, so SPY x (SPX/SPY ratio) is our ground truth.

For each sample it captures, per source: the value, the feed's own timestamp, and the
staleness (local_now - feed_ts). The tell:
  * staleness ~ 0-2s  during RTH  -> real-time
  * staleness ~ 15min during RTH  -> DELAYED (index data not licensed real-time)
  * Tradier-SPX vs SPY-implied-SPX divergence during a move -> delayed SPX lags SPY

MUST be run during market hours (09:30-16:00 ET). After hours everything is frozen and
the test is meaningless.

    python scripts/spx_feed_latency_probe.py                 # single snapshot
    python scripts/spx_feed_latency_probe.py --samples 12 --interval 5   # 60s during a move

ASCII-only output.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ET = None
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    pass


def _now_et():
    return _dt.datetime.now(_ET) if _ET else _dt.datetime.now()


def _parse_ts(v):
    """Tradier trade_date (epoch ms) or ThetaData Timestamp -> aware datetime ET."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            return _dt.datetime.fromtimestamp(int(v) / 1000, _ET) if _ET \
                else _dt.datetime.fromtimestamp(int(v) / 1000)
        import pandas as pd
        return pd.Timestamp(v).to_pydatetime()
    except Exception:
        return None


def _stale_s(local, feed_ts):
    if feed_ts is None:
        return None
    try:
        if feed_ts.tzinfo is None and _ET is not None:
            feed_ts = feed_ts.replace(tzinfo=_ET)
        return (local - feed_ts).total_seconds()
    except Exception:
        return None


async def _tradier_snapshot(client):
    cl = await client._get_client()
    r = await cl.get("/markets/quotes", params={"symbols": "SPX,SPY", "greeks": "false"})
    qs = r.json().get("quotes", {}).get("quote", [])
    if isinstance(qs, dict):
        qs = [qs]
    return {q.get("symbol"): q for q in qs}


def _theta_underlying(tclient, exp):
    """Cheap SPX underlying (+ its feed ts) from the SPXW option snapshot."""
    df = tclient.option_snapshot_greeks_all(symbol="SPXW", expiration=exp, right="call")
    if df is None or len(df) == 0:
        return None, None
    row = df.iloc[len(df) // 2]
    return float(row.get("underlying_price") or 0) or None, _parse_ts(row.get("underlying_timestamp"))


async def run(samples, interval):
    from server.tradier import TradierClient
    from thetadata import ThetaClient
    tr = TradierClient()
    th = ThetaClient(dotenv_path=str(ROOT / ".env"), dataframe_type="pandas")
    exps = th.option_list_expirations(symbol="SPXW")
    today = _dt.date.today().isoformat()
    fut = sorted(str(x)[:10] for x in exps[exps.columns[-1]].tolist() if str(x)[:10] >= today)
    exp = fut[0] if fut else None

    print("=" * 82)
    print("SPX FEED LATENCY PROBE  (run during RTH — after-hours is frozen & meaningless)")
    print("=" * 82)
    hdr = f"{'local_et':>12} | {'trad_SPX':>9} {'stale':>7} | {'SPY':>8} {'stale':>6} | {'SPX~SPYx':>9} {'diverge':>8} | {'theta_SPX':>9} {'stale':>7}"
    print(hdr)
    print("-" * len(hdr))

    max_stale = {"tradier_spx": 0.0, "spy": 0.0, "theta": 0.0}
    for i in range(samples):
        local = _now_et()
        tq = await _tradier_snapshot(tr)
        spx = tq.get("SPX", {}); spy = tq.get("SPY", {})
        spx_last = spx.get("last"); spy_last = spy.get("last")
        spx_stale = _stale_s(local, _parse_ts(spx.get("trade_date")))
        spy_stale = _stale_s(local, _parse_ts(spy.get("trade_date")))
        th_px, th_ts = _theta_underlying(th, exp) if exp else (None, None)
        th_stale = _stale_s(local, th_ts)

        # SPY-implied SPX using this sample's own ratio anchor (first sample sets it)
        implied = None; diverge = None
        if spx_last and spy_last:
            if i == 0:
                run.ratio = float(spx_last) / float(spy_last)
            implied = float(spy_last) * run.ratio
            diverge = float(spx_last) - implied

        for k, v in (("tradier_spx", spx_stale), ("spy", spy_stale), ("theta", th_stale)):
            if v is not None:
                max_stale[k] = max(max_stale[k], abs(v))

        def f(x, nd=2):
            return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "-"
        print(f"{local.strftime('%H:%M:%S'):>12} | "
              f"{f(spx_last):>9} {f(spx_stale,1):>7} | {f(spy_last):>8} {f(spy_stale,1):>6} | "
              f"{f(implied):>9} {f(diverge):>8} | {f(th_px):>9} {f(th_stale,1):>7}")
        if i < samples - 1:
            time.sleep(interval)

    await tr.close()
    print("-" * len(hdr))
    print(f"max staleness (s):  Tradier-SPX={max_stale['tradier_spx']:.1f}  "
          f"SPY={max_stale['spy']:.1f}  Theta-SPX={max_stale['theta']:.1f}")
    print()
    v = max_stale["tradier_spx"]
    if v > 300:
        print(f"VERDICT: Tradier SPX is STALE by ~{v/60:.0f} min -> DELAYED index feed. "
              "Do NOT use for entries; use SPY tape (x ratio) or ThetaData option-underlying.")
    elif v <= 5:
        print("VERDICT: Tradier SPX staleness <=5s -> looks REAL-TIME. Confirm 'diverge' "
              "stays ~0 during a fast move (a delayed feed diverges from SPY-implied SPX).")
    else:
        print(f"VERDICT: Tradier SPX staleness ~{v:.0f}s -> inconclusive; re-run during an "
              "active trending minute and watch the 'diverge' column.")
    print("=" * 82)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    run.ratio = 10.03
    asyncio.run(run(max(1, args.samples), args.interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
