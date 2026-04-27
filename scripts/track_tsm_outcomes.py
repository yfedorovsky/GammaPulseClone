"""TSM SOE outcomes tracker — Apr 27 follow-up.

Today the system fired 4 SOE A SUPPORT BOUNCE signals on TSM with $48M
of bull-call premium in flow_alerts, BUT spot closed -1.1%. Either:
  (a) bullish flow was wrong → SOE alerts will close losers
  (b) accumulation at a near-term bottom → SOE alerts will pay 1-3d
Mir's Q1 cascade thesis says TSM "set the tone" — testable here.

Run after each session for the next 3 days to see how those 4 alerts
resolve. Pulls forward returns from snapshots for spot, plus actual
option quote history for the picked contracts via ThetaData.

Usage:
    python scripts/track_tsm_outcomes.py
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.config import get_settings

THETA = "http://127.0.0.1:25503"
ALERT_DATE = datetime(2026, 4, 27)


def main() -> int:
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    alerts = pd.read_sql_query("""
        SELECT id, ts, direction, grade, signal_type, score, strike,
               expiration, spot, target, stop, rr_ratio
        FROM soe_signals
        WHERE ticker = 'TSM' AND ts >= ?
        ORDER BY ts
    """, c, params=(int(ALERT_DATE.timestamp()),))

    if alerts.empty:
        print("No TSM SOE alerts in window.")
        return 0

    print(f"Tracking {len(alerts)} TSM SOE alerts from {ALERT_DATE:%Y-%m-%d}\n")

    # Spot trajectory since alert day
    end_ts = int((datetime.now()).timestamp())
    spots = pd.read_sql_query("""
        SELECT ts, spot FROM snapshots
        WHERE ticker = 'TSM' AND ts >= ? ORDER BY ts
    """, c, params=(int(ALERT_DATE.timestamp()),))
    spots['date'] = pd.to_datetime(spots['ts'], unit='s').dt.date

    # Daily close per session
    daily = spots.groupby('date')['spot'].agg(['first', 'min', 'max', 'last']).reset_index()
    print("TSM daily price action since alert date:")
    print(daily.to_string(index=False))

    # For each alert, pull intraday option quotes from alert ts forward
    print("\nPer-alert option outcomes (quotes from ThetaData):\n")
    for _, a in alerts.iterrows():
        fired = datetime.fromtimestamp(a['ts'])
        print(f"--- Alert #{a['id']} {fired:%H:%M} ${a['strike']:.0f}C "
              f"{a['expiration']} (entry spot ${a['spot']:.2f}) ---")

        # Pull each session's quote history
        cur_date = fired.date()
        end_date = (datetime.now()).date()
        while cur_date <= end_date:
            params = {
                "symbol": "TSM",
                "expiration": a['expiration'],
                "strike": f"{a['strike']:.3f}",
                "right": "C",
                "start_date": cur_date.isoformat(),
                "end_date": cur_date.isoformat(),
                "interval": "1m",
            }
            try:
                r = requests.get(f"{THETA}/v3/option/history/quote",
                                 params=params, timeout=20)
                df = pd.read_csv(io.StringIO(r.text))
            except Exception as e:
                print(f"  {cur_date}  fetch error: {e}")
                cur_date += timedelta(days=1)
                continue
            if df.empty:
                cur_date += timedelta(days=1)
                continue
            df['t'] = pd.to_datetime(df['timestamp'])
            df = df[(df['bid'] > 0) | (df['ask'] > 0)]
            if df.empty:
                cur_date += timedelta(days=1)
                continue
            df['mid'] = (df['bid'] + df['ask']) / 2

            # On alert day, slice from alert ts onwards
            if cur_date == fired.date():
                df = df[df['t'] >= fired]
                if df.empty:
                    cur_date += timedelta(days=1)
                    continue

            day_open = df['mid'].iloc[0]
            day_high = df['mid'].max()
            day_low = df['mid'].min()
            day_close = df['mid'].iloc[-1]
            mfe_pct = (day_high / day_open - 1) * 100
            mae_pct = (day_low / day_open - 1) * 100
            close_pct = (day_close / day_open - 1) * 100

            print(f"  {cur_date}  open=${day_open:.2f}  high=${day_high:.2f}  "
                  f"low=${day_low:.2f}  close=${day_close:.2f}  "
                  f"({close_pct:+.1f}% MFE {mfe_pct:+.0f}% MAE {mae_pct:+.0f}%)")
            cur_date += timedelta(days=1)
        print()

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
