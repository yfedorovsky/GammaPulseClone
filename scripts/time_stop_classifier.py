"""TIME_STOP classifier evaluation.

Question: at minute N after fire, can we classify ultimate winner vs loser
by checking "did MFE go positive within first N minutes?"

For each cutoff N in {1, 3, 5, 7, 10, 15}, compute:
  - precision: of alerts that had MFE>0 by min N, what % ended as winners?
  - recall: of all eventual winners, what % had MFE>0 by min N?
  - skip-rate: what % of all alerts would have been time-stopped?
  - winners-saved: what % of eventual winners would have been time-stopped (BAD)?
  - wipeouts-avoided: what % of eventual wipeouts would have been time-stopped (GOOD)?
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.alert_annotations import get_minute_bars  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"


def per_minute_mfe(alert: dict) -> pd.DataFrame:
    fire_ts = int(alert["fired_at"])
    fire_dt = datetime.fromtimestamp(fire_ts)
    day = fire_dt.strftime("%Y-%m-%d")
    ticker = alert["ticker"]
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"])
    right = (alert["right"] or "").upper()

    if ticker in ("SPX", "SPXW"):
        bars = get_minute_bars("SPY", day)
        if bars.empty:
            return pd.DataFrame()
        bars = bars.copy()
        for col in ("open", "high", "low", "close"):
            bars[col] = bars[col] * 10
    else:
        bars = get_minute_bars(ticker, day)
    if bars.empty:
        return pd.DataFrame()

    minute_ts = bars["minute"].apply(lambda t: int(t.timestamp())).astype("int64")
    sub = bars[minute_ts >= fire_ts].copy().reset_index(drop=True)
    if sub.empty:
        return pd.DataFrame()
    sub["minute_idx"] = range(len(sub))

    if right in ("C", "CALL"):
        sub["intrinsic_max"] = (sub["high"] - strike).clip(lower=0)
    else:
        sub["intrinsic_max"] = (strike - sub["low"]).clip(lower=0)
    sub["pnl_max_pct"] = (sub["intrinsic_max"] - entry) / entry * 100
    return sub[["minute_idx", "intrinsic_max", "pnl_max_pct"]]


def main() -> int:
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM zero_dte_alerts WHERE peak_pnl_pct IS NOT NULL ORDER BY fired_at"
    ).fetchall()]
    conn.close()

    print(f"Building MFE curves for {len(alerts)} historical alerts...")
    rows = []
    for a in alerts:
        pm = per_minute_mfe(a)
        if pm.empty:
            continue
        # Compute MFE-by-minute-N for each cutoff
        rec = {
            "alert_id": a["alert_id"],
            "fire_dt": datetime.fromtimestamp(a["fired_at"]).strftime("%m-%d %H:%M"),
            "ticker": a["ticker"],
            "direction": a["direction"],
            "outcome": a["outcome_category"],
            "ultimate_peak_pct": float(a["peak_pnl_pct"]) if a["peak_pnl_pct"] else None,
            "ultimate_eod_pct": float(a["eod_pnl_pct"]) if a["eod_pnl_pct"] else None,
            "ultimate_winner": (a["peak_pnl_pct"] or 0) > 0,
            "ultimate_big_winner": (a["peak_pnl_pct"] or 0) > 50,
            "ultimate_wipeout": (a["outcome_category"] == "WIPEOUT"),
        }
        for cut in [1, 2, 3, 5, 7, 10, 15]:
            sub = pm[pm["minute_idx"] <= cut]
            mfe_by_n = float(sub["pnl_max_pct"].max()) if len(sub) else None
            rec[f"mfe_min{cut}"] = mfe_by_n
            rec[f"positive_by_min{cut}"] = (mfe_by_n is not None and mfe_by_n > 0)
        rows.append(rec)

    df = pd.DataFrame(rows)
    print(f"Built curves for {len(df)} alerts. Outcome breakdown:")
    print(f"  ultimate_winner: {df['ultimate_winner'].sum()}/{len(df)}")
    print(f"  ultimate_big_winner (peak>50): {df['ultimate_big_winner'].sum()}/{len(df)}")
    print(f"  ultimate_wipeout: {df['ultimate_wipeout'].sum()}/{len(df)}")
    print()

    # Classifier table
    print("=" * 100)
    print("TIME_STOP CLASSIFIER: 'positive by min N' as predictor of ultimate winner")
    print("=" * 100)
    print(f"{'cutoff':<10} {'kept':<6} {'skipped':<8} {'wins_kept':<14} "
          f"{'wins_lost':<14} {'wipes_skipped':<15} {'precision':<10} {'recall':<8}")
    print("-" * 100)
    for cut in [1, 2, 3, 5, 7, 10, 15]:
        col = f"positive_by_min{cut}"
        kept = df[df[col]]
        skipped = df[~df[col]]
        wins_kept = kept["ultimate_winner"].sum()
        wins_lost = skipped["ultimate_winner"].sum()
        wipes_skipped = skipped["ultimate_wipeout"].sum()
        precision = wins_kept / len(kept) * 100 if len(kept) else 0
        recall = wins_kept / df["ultimate_winner"].sum() * 100
        print(f"min {cut:<6} {len(kept):<6} {len(skipped):<8} "
              f"{wins_kept}/{df['ultimate_winner'].sum()} ({wins_kept/df['ultimate_winner'].sum()*100:.0f}%)  "
              f"{wins_lost} skipped winners  "
              f"{wipes_skipped}/{df['ultimate_wipeout'].sum()} ({wipes_skipped/df['ultimate_wipeout'].sum()*100:.0f}%)   "
              f"{precision:.0f}%       {recall:.0f}%")
    print()
    print("LEGEND:")
    print("  precision = of kept alerts, % that were actual winners")
    print("  recall    = of all winners, % that we kept")
    print("  TS rule   = 'if MFE has not gone positive by minute N, time-stop now'")
    print()

    # Per-alert detail at min 5 (recommended cutoff)
    print("=" * 100)
    print("PER-ALERT @ min 5: 'positive by min 5' classification vs ultimate outcome")
    print("=" * 100)
    print(f"{'fire_dt':<14} {'tkr':<4} {'dir':<5} {'outcome':<13} "
          f"{'MFE@1':<8} {'MFE@3':<8} {'MFE@5':<8} {'MFE@10':<8} "
          f"{'pos@5?':<7} {'ultimate_peak':<14}")
    print("-" * 100)
    for _, r in df.iterrows():
        m1 = f"{r['mfe_min1']:+.0f}%" if r['mfe_min1'] is not None else "n/a"
        m3 = f"{r['mfe_min3']:+.0f}%" if r['mfe_min3'] is not None else "n/a"
        m5 = f"{r['mfe_min5']:+.0f}%" if r['mfe_min5'] is not None else "n/a"
        m10 = f"{r['mfe_min10']:+.0f}%" if r['mfe_min10'] is not None else "n/a"
        flag = "YES" if r['positive_by_min5'] else "no"
        peak = f"{r['ultimate_peak_pct']:+.0f}%" if r['ultimate_peak_pct'] is not None else "n/a"
        print(f"{r['fire_dt']:<14} {r['ticker']:<4} {r['direction'][:4]:<5} "
              f"{r['outcome']:<13} {m1:<8} {m3:<8} {m5:<8} {m10:<8} "
              f"{flag:<7} {peak:<14}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
