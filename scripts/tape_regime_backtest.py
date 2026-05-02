"""Backtest the tape regime classifier against the 6-day historical
0DTE alert window.

For each of the 21 historical SPY/QQQ alerts, compute the regime that
would have been displayed in the telegram banner at fire-time, using
Databento minute bars as the data source.

Goal: verify that winning-day alerts had a different regime distribution
than losing-day alerts. If yes, the classifier surfaces the bimodality
finding from INTRINSIC_CAPTURE_ANALYSIS.md as actionable annotation.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import load_window  # noqa: E402
from server.tape_regime import classify_tape_regime  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"
DB_START = int(datetime(2025, 10, 30).timestamp())
DB_END = int(datetime(2026, 5, 1, 23, 59).timestamp())

# From INTRINSIC_CAPTURE_ANALYSIS — alerts whose strike ever exceeded
# entry-paid premium (peak P&L > 0). Built from the per-alert CSV.
WINNING_ALERTS = {
    "1777391311633_QQQ_bul",  # Apr 28 11:48 QQQ peak +213%
    "1777387169182_QQQ_bul",  # Apr 28 10:39 QQQ peak +3%
    "1777643719899_SPY_bul",  # May 1 09:55 SPY peak +73%
    "1777643729949_QQQ_bul",  # May 1 09:55 QQQ peak +50%
    "1777661922320_SPY_bul",  # May 1 14:58 SPY peak +115%
}


def session_minute_bars(ticker: str, day: str) -> list[dict]:
    df = load_window(ticker, day, start_hhmm="09:30", end_hhmm="16:00",
                     actions=["T"])
    if df.empty:
        return []
    df["t"] = pd.to_datetime(df["ts_event"], utc=True) \
              .dt.tz_convert("America/New_York")
    df["minute"] = df["t"].dt.floor("min")
    g = df.groupby("minute").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
    ).reset_index()
    return [
        {
            "ts": int(r["minute"].timestamp()),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
        }
        for _, r in g.iterrows()
    ]


def main() -> int:
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT alert_id, ticker, fired_at, strike, est_entry_price
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ? AND ticker IN ('SPY', 'QQQ')
           ORDER BY fired_at""",
        (DB_START, DB_END),
    )
    alerts = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Cache bars per (ticker, day) to avoid re-loading
    bars_cache: dict[tuple[str, str], list[dict]] = {}

    rows = []
    for a in alerts:
        fire_dt = datetime.fromtimestamp(a["fired_at"])
        day = fire_dt.strftime("%Y-%m-%d")
        ticker = a["ticker"]
        key = (ticker, day)
        if key not in bars_cache:
            bars_cache[key] = session_minute_bars(ticker, day)
        bars = bars_cache[key]
        if not bars:
            print(f"  {a['alert_id']}: no bars")
            continue
        result = classify_tape_regime(bars, int(a["fired_at"]))
        is_winner = a["alert_id"] in WINNING_ALERTS
        rows.append({
            "alert_id": a["alert_id"],
            "day": day,
            "fire_hhmm": fire_dt.strftime("%H:%M"),
            "ticker": ticker,
            "winner": is_winner,
            "regime": result.regime,
            "open_to_spot_pct": round(result.open_to_spot_pct * 100, 2),
            "range_pct": round(result.range_pct * 100, 2),
            "lod_touch_min": result.mins_since_lod_touch,
            "hod_touch_min": result.mins_since_hod_touch,
            "n_new_hods_60m": result.n_new_hods_60m,
            "n_new_lods_60m": result.n_new_lods_60m,
            "reason": result.reason,
        })

    df = pd.DataFrame(rows)
    print("=== Per-alert regime classifications ===")
    print(df[["fire_hhmm", "ticker", "winner", "regime",
              "open_to_spot_pct", "range_pct", "lod_touch_min",
              "hod_touch_min"]].to_string(index=False))
    print()
    print("=== Regime × Winner cross-tab ===")
    ct = pd.crosstab(df["regime"], df["winner"], margins=True)
    print(ct)
    print()
    print("=== Per-day regime trajectory (first/middle/last alert) ===")
    for day in sorted(df["day"].unique()):
        sub = df[df["day"] == day].sort_values("fire_hhmm")
        n_winners = sub["winner"].sum()
        regimes = " → ".join(f"{r['fire_hhmm']}:{r['regime']}"
                             for _, r in sub.iterrows())
        print(f"  {day} ({len(sub)} alerts, {n_winners} winners): {regimes}")

    out_path = ROOT / "docs" / "research" / "tape_regime_backtest.csv"
    df.to_csv(out_path, index=False)
    print(f"\n[wrote] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
