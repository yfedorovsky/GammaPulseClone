"""Phase 1 shadow alert detector — EOD mode.

For a given trading day, this script:
  1. Pulls SPY 1-min bars (Databento)
  2. Runs the 4 robust signal detectors from the unified backtest
     - pmh_break, sweep_pmh, orb15_break, orb30_break, ema_cross_imm
  3. For each signal that fired, simulates the trade via real ThetaData NBBO
  4. Records each shadow fire to shadow_alerts.db with full outcome data

After 30 days of shadow alerts, run shadow_validation.py to compare:
  - Forward-window MFE distribution vs 6-month backtest distribution
  - Forward win rate vs backtest win rate
  - Whether the edge persists

Usage:
  python scripts/shadow_alerts_eod.py --date 2026-05-05
  python scripts/shadow_alerts_eod.py --date today

The shadow alerts are NOT sent to Telegram (no execution, just logging).
This is Phase 1 validation — paper-only, observation-only.
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.unified_setup_backtest import (
    bars_5min_with_indicators, bars_1min,
    get_premarket_high_low, get_prior_day_high_low,
    classify_daytype, simulate_trade,
    sig_pmh_break, sig_sweep_pmh_reclaim,
    sig_orb15, sig_orb30, sig_ema_cross_immediate,
)


SHADOW_DB = "shadow_alerts.db"

# ROBUST SETUPS (post-Phase-0): only these are eligible for forward shadow
ROBUST_SIGNALS = {
    "pmh_break": sig_pmh_break,
    "sweep_pmh": sig_sweep_pmh_reclaim,
    "orb15_break": sig_orb15,
    "orb30_break": sig_orb30,
    "ema_cross_imm": sig_ema_cross_immediate,
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_alerts (
    setup TEXT, day TEXT, cross_hhmm TEXT,
    direction TEXT, strike REAL, right TEXT,
    daytype TEXT, vwap_slope_at_entry REAL, inside_pdr INTEGER,
    -- entry
    entry_hhmm TEXT, entry_mid REAL,
    -- outcomes
    peak_mid REAL, peak_hhmm TEXT, eod_mid REAL, mins_to_peak INTEGER,
    mfe_pct REAL, eod_pct REAL,
    -- exit policies
    pol_tp50_s30 REAL, pol_tp100_s30 REAL, pol_tp50_und_inv REAL,
    pol_tp50_ts5 REAL, pol_tp50_ts10 REAL, pol_tp50_ts30 REAL,
    -- mfe by minute (for forward time-stop validation)
    mfe_min1 REAL, mfe_min3 REAL, mfe_min5 REAL, mfe_min10 REAL,
    -- meta
    invalidation_level REAL, invalidation_type TEXT,
    status TEXT,
    fired_at_ts INTEGER,
    PRIMARY KEY (setup, day, cross_hhmm)
);
CREATE INDEX IF NOT EXISTS idx_shadow_setup ON shadow_alerts(setup);
CREATE INDEX IF NOT EXISTS idx_shadow_day ON shadow_alerts(day);
"""


def run_for_day(date: str, conn: sqlite3.Connection, verbose: bool = True) -> int:
    if verbose:
        print(f"[shadow] processing {date}", flush=True)
    b1 = bars_1min(date)
    b5 = bars_5min_with_indicators(date)
    if b5.empty:
        print(f"[shadow] {date}: no SPY bars (likely non-trading day or "
              f"data missing)", flush=True)
        return 0
    pmh, pml = get_premarket_high_low(date)
    pdh, pdl = get_prior_day_high_low(date)
    ctx = {"pmh": pmh, "pml": pml, "pdh": pdh, "pdl": pdl}
    daytype = classify_daytype(b5, pdh, pdl)
    midday = b5[b5["hhmm"] == "12:00"]
    slope = float(midday.iloc[0]["vwap_slope"]) if not midday.empty else 0.0
    inside_pdr = 0
    if not pd.isna(pdh) and not pd.isna(pdl):
        day_high = b5["high"].max()
        day_low = b5["low"].min()
        if day_high <= pdh and day_low >= pdl:
            inside_pdr = 1

    n_total = 0
    fired_at_ts = int(datetime.now().timestamp())
    for setup_name, sig_fn in ROBUST_SIGNALS.items():
        try:
            entries = sig_fn(b1, b5, ctx)
        except Exception as e:
            print(f"  ! {setup_name}: {type(e).__name__}: {e}", flush=True)
            continue
        for entry in entries:
            t = simulate_trade(date, setup_name, entry, b1, b5,
                               daytype, slope, inside_pdr)
            if t is None:
                continue
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO shadow_alerts VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,
                        ?,?,?,?,
                        ?,?,?,?
                    )""",
                    (t.setup, t.day, t.cross_hhmm, t.direction,
                     t.strike, t.right, daytype, slope, inside_pdr,
                     t.entry_hhmm, t.entry_mid,
                     t.peak_mid, t.peak_hhmm, t.eod_mid, t.mins_to_peak,
                     t.mfe_pct, t.eod_pct,
                     t.pol_tp50_s30, t.pol_tp100_s30, t.pol_tp50_und_inv,
                     t.pol_tp50_ts5, t.pol_tp50_ts10, t.pol_tp50_ts30,
                     t.mfe_min1, t.mfe_min3, t.mfe_min5, t.mfe_min10,
                     t.invalidation_level, t.invalidation_type, t.status,
                     fired_at_ts))
                conn.commit()
                n_total += 1
                if verbose:
                    print(f"  [{setup_name}] {t.cross_hhmm} {t.direction} K={t.strike} "
                          f"entry=${t.entry_mid:.2f} MFE={t.mfe_pct:+.0f}% EOD={t.eod_pct:+.0f}% "
                          f"TP+50/S-30={t.pol_tp50_s30:+.0f}% TP+100/S-30={t.pol_tp100_s30:+.0f}%",
                          flush=True)
            except Exception as e:
                print(f"  ! save fail: {e}", flush=True)
    return n_total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True,
                   help="YYYY-MM-DD or 'today' or 'yesterday'")
    p.add_argument("--start", help="YYYY-MM-DD (range start, inclusive)")
    p.add_argument("--end", help="YYYY-MM-DD (range end, inclusive)")
    args = p.parse_args()

    conn = sqlite3.connect(SHADOW_DB)
    conn.executescript(SCHEMA)

    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
        days = []
        d = start
        while d <= end:
            days.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
        for day in days:
            run_for_day(day, conn)
    else:
        if args.date == "today":
            date = datetime.now().strftime("%Y-%m-%d")
        elif args.date == "yesterday":
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            date = args.date
        run_for_day(date, conn)

    # Summary so far
    n = conn.execute("SELECT COUNT(*) FROM shadow_alerts").fetchone()[0]
    days_n = conn.execute("SELECT COUNT(DISTINCT day) FROM shadow_alerts").fetchone()[0]
    print(f"\n[shadow] DB now has {n} total shadow alerts across {days_n} days",
          flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
