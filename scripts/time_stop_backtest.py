"""TIME_STOP backtest: for each historical alert, compute MFE-by-minute-N.

For each cutoff N (1, 3, 5, 7, 10, 15 min), test the rule:
  IF MFE(0..N) <= 0%, EXIT at minute N at intrinsic close
  ELSE hold to standard exit (TP+50%/Stop-30% or EOD)

Reports: hit rate, mean P&L, total P&L for each cutoff.
Compares to: hold-to-EOD baseline.
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


def fetch_alerts() -> pd.DataFrame:
    conn = sqlite3.connect(ALERT_DB)
    df = pd.read_sql(
        """SELECT alert_id, ticker, fired_at, direction, strike,
                  est_entry_price, right, outcome_category,
                  peak_pnl_pct, eod_pnl_pct, mins_above_entry
           FROM zero_dte_alerts
           WHERE peak_pnl_pct IS NOT NULL
           ORDER BY fired_at""",
        conn,
    )
    conn.close()
    return df


def per_minute_pnl(alert: dict) -> pd.DataFrame:
    """Return per-minute intrinsic P&L for an alert.

    Columns: minute_idx (0..N), hhmm, intrinsic_close, pnl_pct.
    """
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
    sub = bars[minute_ts >= fire_ts].copy()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.reset_index(drop=True)
    sub["minute_idx"] = range(len(sub))

    if right in ("C", "CALL"):
        sub["intrinsic_max"] = (sub["high"] - strike).clip(lower=0)
        sub["intrinsic_close"] = (sub["close"] - strike).clip(lower=0)
    else:
        sub["intrinsic_max"] = (strike - sub["low"]).clip(lower=0)
        sub["intrinsic_close"] = (strike - sub["close"]).clip(lower=0)

    sub["pnl_close_pct"] = (sub["intrinsic_close"] - entry) / entry * 100
    sub["pnl_max_pct"] = (sub["intrinsic_max"] - entry) / entry * 100
    if "hhmm" not in sub.columns:
        sub["hhmm"] = sub["minute"].apply(lambda t: t.strftime("%H:%M"))
    return sub[["minute_idx", "hhmm", "intrinsic_close", "intrinsic_max",
                "pnl_close_pct", "pnl_max_pct"]]


def simulate_time_stop(
    pm: pd.DataFrame, cutoff_min: int, threshold_pct: float = 0.0
) -> dict:
    """Simulate: if max P&L by minute `cutoff_min` is <= threshold_pct,
    exit at minute `cutoff_min` at intrinsic_close. Else hold to EOD.

    Returns: {policy_pnl_pct, exit_reason, exit_minute}
    """
    if pm.empty:
        return {"policy_pnl_pct": None, "exit_reason": "NO_DATA", "exit_minute": None}

    early = pm[pm["minute_idx"] <= cutoff_min]
    max_early = early["pnl_max_pct"].max()

    if max_early <= threshold_pct:
        # TIME STOP: exit at minute cutoff
        row = pm[pm["minute_idx"] == cutoff_min]
        if row.empty:
            row = pm.iloc[[-1]]
        return {
            "policy_pnl_pct": float(row.iloc[0]["pnl_close_pct"]),
            "exit_reason": "TIME_STOP",
            "exit_minute": int(row.iloc[0]["minute_idx"]),
        }
    else:
        # HOLD TO EOD
        last = pm.iloc[-1]
        return {
            "policy_pnl_pct": float(last["pnl_close_pct"]),
            "exit_reason": "EOD",
            "exit_minute": int(last["minute_idx"]),
        }


def simulate_tp_stop_time(
    pm: pd.DataFrame,
    tp_pct: float = 50.0,
    stop_pct: float = -30.0,
    time_stop_min: int = 5,
) -> dict:
    """Combined ladder:
      - At minute time_stop_min: if max P&L <= 0, exit at intrinsic_close
      - Otherwise check TP+stop_pct as the trade evolves
      - At EOD: exit
    """
    if pm.empty:
        return {"policy_pnl_pct": None, "exit_reason": "NO_DATA"}

    # Time stop check
    early = pm[pm["minute_idx"] <= time_stop_min]
    if early["pnl_max_pct"].max() <= 0:
        row = pm[pm["minute_idx"] == time_stop_min]
        if row.empty:
            row = pm.iloc[[-1]]
        return {
            "policy_pnl_pct": float(row.iloc[0]["pnl_close_pct"]),
            "exit_reason": "TIME_STOP",
            "exit_minute": int(row.iloc[0]["minute_idx"]),
        }

    # Walk forward, check TP first then stop on each minute
    for _, r in pm.iterrows():
        if r["pnl_max_pct"] >= tp_pct:
            return {
                "policy_pnl_pct": float(tp_pct),
                "exit_reason": "TP",
                "exit_minute": int(r["minute_idx"]),
            }
        if r["pnl_close_pct"] <= stop_pct:
            return {
                "policy_pnl_pct": float(stop_pct),
                "exit_reason": "STOP",
                "exit_minute": int(r["minute_idx"]),
            }

    # EOD
    last = pm.iloc[-1]
    return {
        "policy_pnl_pct": float(last["pnl_close_pct"]),
        "exit_reason": "EOD",
        "exit_minute": int(last["minute_idx"]),
    }


def main() -> int:
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM zero_dte_alerts WHERE peak_pnl_pct IS NOT NULL ORDER BY fired_at"
    ).fetchall()]
    conn.close()

    print(f"Backtesting on {len(alerts)} historical alerts")
    print()

    # Build per-minute P&L curves once per alert
    curves = {}
    for a in alerts:
        pm = per_minute_pnl(a)
        if not pm.empty:
            curves[a["alert_id"]] = (a, pm)
    print(f"Successfully loaded curves for {len(curves)} alerts")
    print()

    # Cutoffs to test
    cutoffs = [1, 3, 5, 7, 10, 15]

    # === Pure time-stop only ===
    print("=" * 90)
    print("PURE TIME-STOP: exit at min N if MFE(0..N) <= 0, else hold to EOD")
    print("=" * 90)
    print(f"{'cutoff':<8} {'n':<4} {'time_stop_fired':<16} {'mean_pnl':<10} "
          f"{'median':<8} {'wins':<6} {'wipeouts':<10}")
    print("-" * 90)
    baseline = []
    for aid, (a, pm) in curves.items():
        baseline.append(pm.iloc[-1]["pnl_close_pct"])
    base_mean = sum(baseline) / len(baseline)
    base_wipes = sum(1 for x in baseline if x <= -90)
    base_wins = sum(1 for x in baseline if x > 0)
    print(f"{'BASELINE (hold EOD)':<28} {len(baseline):<4} {0:<16} "
          f"{base_mean:>+6.0f}%   {sorted(baseline)[len(baseline)//2]:>+5.0f}% "
          f"{base_wins:<6} {base_wipes:<10}")
    for cut in cutoffs:
        results = []
        ts_count = 0
        for aid, (a, pm) in curves.items():
            r = simulate_time_stop(pm, cutoff_min=cut)
            results.append(r["policy_pnl_pct"])
            if r["exit_reason"] == "TIME_STOP":
                ts_count += 1
        n = len(results)
        mean_p = sum(results) / n
        med = sorted(results)[n // 2]
        wins = sum(1 for x in results if x > 0)
        wipes = sum(1 for x in results if x <= -90)
        print(f"{f'TS {cut}min':<28} {n:<4} {ts_count:<16} "
              f"{mean_p:>+6.0f}%   {med:>+5.0f}% {wins:<6} {wipes:<10}")
    print()

    # === Combined: time-stop + TP/Stop ladder ===
    print("=" * 90)
    print("COMBINED LADDER: TIME_STOP @ N min + TP+50% / STOP-30% during hold")
    print("=" * 90)
    print(f"{'config':<32} {'n':<4} {'TS':<4} {'TP':<4} {'STOP':<6} {'EOD':<5} "
          f"{'mean':<7} {'median':<8} {'wins':<6}")
    print("-" * 90)
    for cut in [3, 5, 7, 10]:
        for tp in [50, 100]:
            for stop in [-30, -50]:
                results = {"TS": 0, "TP": 0, "STOP": 0, "EOD": 0}
                pnls = []
                for aid, (a, pm) in curves.items():
                    r = simulate_tp_stop_time(
                        pm, tp_pct=tp, stop_pct=stop, time_stop_min=cut
                    )
                    pnls.append(r["policy_pnl_pct"])
                    results[r["exit_reason"]] = results.get(r["exit_reason"], 0) + 1
                n = len(pnls)
                mean_p = sum(pnls) / n
                med = sorted(pnls)[n // 2]
                wins = sum(1 for x in pnls if x > 0)
                cfg = f"TS{cut}+TP{tp}+S{stop}"
                print(f"{cfg:<32} {n:<4} {results['TS']:<4} {results['TP']:<4} "
                      f"{results['STOP']:<6} {results['EOD']:<5} "
                      f"{mean_p:>+5.0f}%  {med:>+5.0f}%  {wins:<6}")
    print()

    # Per-alert detail with the recommended config (TS5 + TP50 + Stop -30)
    print("=" * 90)
    print("PER-ALERT DETAIL: TIME_STOP @ 5 min + TP+50% + STOP -30%")
    print("=" * 90)
    print(f"{'fire_dt':<17} {'tkr':<4} {'dir':<5} {'K':<6} {'baseline_eod':<13} "
          f"{'policy':<9} {'reason':<10} {'@min'}")
    print("-" * 90)
    delta_sum = 0
    for aid, (a, pm) in curves.items():
        r = simulate_tp_stop_time(pm, tp_pct=50, stop_pct=-30, time_stop_min=5)
        baseline_eod = pm.iloc[-1]["pnl_close_pct"]
        policy = r["policy_pnl_pct"]
        delta = policy - baseline_eod
        delta_sum += delta
        fire_dt = datetime.fromtimestamp(a["fired_at"]).strftime("%m-%d %H:%M")
        print(f"{fire_dt:<17} {a['ticker']:<4} {a['direction'][:4]:<5} "
              f"{a['strike']:<6.0f} {baseline_eod:>+6.0f}%       "
              f"{policy:>+5.0f}%   {r['exit_reason']:<10} {r['exit_minute']}")
    print(f"\nTotal P&L delta (policy - baseline): {delta_sum:+.0f}pp across "
          f"{len(curves)} alerts = {delta_sum/len(curves):+.1f}pp/alert avg")

    return 0


if __name__ == "__main__":
    sys.exit(main())
