"""DEPRECATED — DO NOT USE — kept for audit trail only.

This script computes outcomes from INTRINSIC value (max(spot-strike, 0)) and
uses SPY×10 as a proxy for SPX intraday. Both are wrong:
  - Intrinsic ignores time premium; for OTM 0DTE options it returns 0
    even when the option is trading $0.50-$2.00. This systematically
    inflates wipeout counts.
  - SPY×10 is not equal to SPX intraday; the basis drifts and produces
    bogus "ITM excursions" that never happened on the real option.

The columns it populates on `zero_dte_alerts` (peak_pnl_pct, eod_pnl_pct,
mins_above_entry, mins_2x_entry, outcome_category) are CONTAMINATED. They
remain in the database for historical reference but should not be used
for analysis.

Use instead:
  python scripts/backfill_alert_outcomes_nbbo.py

That script pulls real OPRA NBBO via ThetaData and writes to a separate
table `zero_dte_alerts_nbbo_outcomes`. See
`docs/research/EXIT_POLICY_NBBO_FINDING.md` for the impact of the bug.

This script will refuse to run unless --i-know-this-is-broken is passed.
"""
import sys
if "--i-know-this-is-broken" not in sys.argv:
    print("DEPRECATED. Use scripts/backfill_alert_outcomes_nbbo.py instead.")
    print("See module docstring for context.")
    sys.exit(1)
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_annotations import get_minute_bars, apply_migrations  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"
ST_DB = "structural_turns.db"


def categorize_outcome(peak_pnl: float | None) -> str:
    if peak_pnl is None:
        return "NO_DATA"
    if peak_pnl >= 200:
        return "WIN_BIG"
    if peak_pnl >= 50:
        return "WIN"
    if peak_pnl >= 0:
        return "MARGINAL"
    if peak_pnl >= -50:
        return "LOSS_BOUNCED"
    return "WIPEOUT"


def compute_outcome(alert: dict) -> dict:
    """Compute outcome columns for one alert.

    For SPY/QQQ uses Databento. For SPX uses SPY*10 as spot proxy
    (rough but the only available historical source)."""
    fire_ts = int(alert["fired_at"])
    fire_dt = datetime.fromtimestamp(fire_ts)
    fire_hhmm = fire_dt.strftime("%H:%M")
    day = fire_dt.strftime("%Y-%m-%d")
    ticker = alert["ticker"]
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"])
    right = alert["right"].upper()

    # For SPX, use SPY proxy (10x scaling)
    if ticker in ("SPX", "SPXW"):
        bars = get_minute_bars("SPY", day)
        if not bars.empty:
            bars = bars.copy()
            for col in ("open", "high", "low", "close"):
                bars[col] = bars[col] * 10
    else:
        bars = get_minute_bars(ticker, day)

    if bars.empty:
        return {"peak_pnl_pct": None, "peak_hhmm": None, "mins_to_peak": None,
                "eod_pnl_pct": None, "reached_itm": None,
                "mins_above_entry": None, "mins_2x_entry": None,
                "outcome_category": "NO_DATA"}

    # Trade window: from fire minute to 15:59
    # Robust to datetime64[s, tz] vs datetime64[ns, tz] dtype variation.
    minute_ts = bars["minute"].apply(lambda t: int(t.timestamp())).astype("int64")
    sub = bars[minute_ts >= fire_ts].copy()
    if sub.empty:
        return {"peak_pnl_pct": None, "peak_hhmm": None, "mins_to_peak": None,
                "eod_pnl_pct": None, "reached_itm": None,
                "mins_above_entry": None, "mins_2x_entry": None,
                "outcome_category": "NO_DATA"}

    if right in ("C", "CALL"):
        sub["intrinsic_max"] = (sub["high"] - strike).clip(lower=0)
        sub["intrinsic_close"] = (sub["close"] - strike).clip(lower=0)
    else:
        sub["intrinsic_max"] = (strike - sub["low"]).clip(lower=0)
        sub["intrinsic_close"] = (strike - sub["close"]).clip(lower=0)

    peak_intrinsic = float(sub["intrinsic_max"].max())
    peak_idx = sub["intrinsic_max"].idxmax()
    peak_row = sub.loc[peak_idx]
    peak_hhmm = peak_row["hhmm"] if "hhmm" in peak_row else \
        peak_row["minute"].strftime("%H:%M")
    mins_to_peak = int((peak_row["minute"].timestamp() - fire_ts) / 60)
    eod_intrinsic = float(sub.iloc[-1]["intrinsic_close"])

    peak_pnl = (peak_intrinsic - entry) / entry * 100 if entry > 0 else None
    eod_pnl = (eod_intrinsic - entry) / entry * 100 if entry > 0 else None

    mins_above_entry = int((sub["intrinsic_max"] > entry).sum())
    mins_2x = int((sub["intrinsic_max"] >= entry * 2).sum())

    return {
        "peak_pnl_pct": round(peak_pnl, 2) if peak_pnl is not None else None,
        "peak_hhmm": peak_hhmm,
        "mins_to_peak": mins_to_peak,
        "eod_pnl_pct": round(eod_pnl, 2) if eod_pnl is not None else None,
        "reached_itm": 1 if peak_intrinsic > 0 else 0,
        "mins_above_entry": mins_above_entry,
        "mins_2x_entry": mins_2x,
        "outcome_category": categorize_outcome(peak_pnl),
    }


def st_confirmation_status(alert: dict) -> int:
    """Returns 1 if a same-direction qualified ST fire occurred within
    90 min before fire_ts, else 0."""
    fire_ts = int(alert["fired_at"])
    direction = alert["direction"].upper()
    cutoff = fire_ts - 90 * 60
    try:
        conn = sqlite3.connect(ST_DB)
        cur = conn.execute(
            "SELECT COUNT(*) FROM structural_turns "
            "WHERE qualified = 1 AND direction = ? "
            "AND ts BETWEEN ? AND ?",
            (direction, cutoff, fire_ts),
        )
        n = cur.fetchone()[0]
        conn.close()
        return 1 if n > 0 else 0
    except Exception:
        return 0


def main() -> int:
    print("[outcomes] applying migrations...", flush=True)
    apply_migrations(ALERT_DB)

    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM zero_dte_alerts ORDER BY fired_at"
    ).fetchall()]
    conn.close()

    print(f"[outcomes] backfilling {len(alerts)} alerts...", flush=True)
    n_done = 0
    for a in alerts:
        try:
            outcome = compute_outcome(a)
            outcome["st_confirmation_within_90m"] = st_confirmation_status(a)

            conn = sqlite3.connect(ALERT_DB)
            cols = ", ".join(f"{k} = ?" for k in outcome.keys())
            vals = list(outcome.values()) + [a["alert_id"]]
            conn.execute(
                f"UPDATE zero_dte_alerts SET {cols} WHERE alert_id = ?", vals,
            )
            conn.commit()
            conn.close()

            n_done += 1
            fire_dt = datetime.fromtimestamp(a["fired_at"]).strftime("%m-%d %H:%M")
            cat = outcome.get("outcome_category", "?")
            peak = outcome.get("peak_pnl_pct")
            peak_str = f"{peak:+.0f}%" if peak is not None else "?"
            st_conf = outcome.get("st_confirmation_within_90m", 0)
            print(f"  {fire_dt} {a['ticker']:<4} K={a['strike']:.0f}  "
                  f"peak={peak_str:<7} cat={cat:<13} ST={st_conf}",
                  flush=True)
        except Exception as e:
            print(f"  ! {a['alert_id']}: {type(e).__name__}: {e}",
                  flush=True)

    print(f"\n[outcomes] {n_done} updated", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
