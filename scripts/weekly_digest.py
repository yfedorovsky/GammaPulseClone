"""End-of-week alert performance digest.

Runs Friday 4:30pm (or any time) to summarize this week's alert WR across
every fire-and-forget pathway. Read-only — no behavior changes.

Sources covered:
  - zero_dte_alerts (separate DB, option-price MFE via ThetaData)
  - soe_signal      (signal_outcomes table, spot return)
  - setup_forming   (signal_outcomes, spot return — wired Apr 27)
  - net_flow_alert  (signal_outcomes, spot return — wired Apr 27)
  - sweep           (signal_outcomes, spot return)
  - flow_alert      (signal_outcomes, spot return)

For 0DTE specifically: spot return is misleading because option price
moves nonlinearly via gamma. We pull real ThetaData quote history per
contract and report MFE / MAE / end-of-window vs entry.

Run:
    python scripts/weekly_digest.py            # last 7 days
    python scripts/weekly_digest.py --days 14
    python scripts/weekly_digest.py --no-backfill   # skip backfill, query only
    python scripts/weekly_digest.py --utf8     # force utf-8 stdout (Windows)
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.config import get_settings


THETA = "http://127.0.0.1:25503"
ZERO_DTE_DB = "zero_dte_alerts.db"

# Apr 23-24 baseline from the original audit (5 alerts, all SPY/QQQ B+ bullish)
BASELINE_0DTE = {
    "n": 5,
    "hit_50_pct": 100,
    "hit_100_pct": 40,
    "hit_target_pct": 0,
    "avg_mfe_pct": 90,
    "avg_end_pct": -38,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--no-backfill", action="store_true",
                   help="Skip running scripts/backfill_outcomes.py")
    p.add_argument("--utf8", action="store_true",
                   help="Force utf-8 stdout (use on Windows for emoji output)")
    return p.parse_args()


def run_backfill(days: int) -> None:
    print(f"[1/3] Running backfill_outcomes for last {days} days...")
    cmd = [sys.executable, "scripts/backfill_outcomes.py", "--days-back", str(days)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        # Print only the summary tail to stay readable
        if r.returncode != 0:
            print(f"  WARN: backfill exited {r.returncode}")
            print(r.stderr[-500:] if r.stderr else "")
        else:
            print(r.stdout.split("\n")[-15:])
    except subprocess.TimeoutExpired:
        print("  WARN: backfill timed out at 10min")


def signal_outcomes_summary(days: int) -> None:
    print(f"\n[2/3] Signal-outcome WR by source_type (last {days} days)")
    print("-" * 70)
    cutoff = int(time.time()) - days * 86400
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    try:
        for stype in ("soe_signal", "setup_forming", "net_flow_alert",
                      "sweep", "flow_alert"):
            df = pd.read_sql_query("""
                SELECT direction, grade, return_1d, return_3d, return_1w,
                       hit_1d, hit_3d, hit_1w
                FROM signal_outcomes
                WHERE source_type = ? AND trigger_ts >= ?
            """, c, params=(stype, cutoff))
            if df.empty:
                print(f"\n  {stype}: 0 alerts in window")
                continue

            print(f"\n  {stype}: n={len(df)}")
            # Direction-aware hit (for BUY: ret > 0; SELL: ret < 0)
            for h in ("1d", "3d", "1w"):
                hit_col = f"hit_{h}"
                ret_col = f"return_{h}"
                sub = df.dropna(subset=[hit_col])
                if not len(sub):
                    print(f"    {h}: no forward data yet")
                    continue
                hit = sub[hit_col].mean() * 100
                avg = sub[ret_col].mean() * 100
                print(f"    {h}: n={len(sub):>4}  hit={hit:>5.1f}%  avg_ret={avg:+5.2f}%")

            # Grade breakdown when present
            if df["grade"].notna().any():
                print(f"    By grade (1d hit):")
                for g, gsub in df.groupby("grade"):
                    sub = gsub.dropna(subset=["hit_1d"])
                    if len(sub) >= 3:
                        hit = sub["hit_1d"].mean() * 100
                        print(f"      {g:<25} n={len(sub):>3}  1d_hit={hit:>5.1f}%")
    finally:
        c.close()


def zero_dte_audit(days: int) -> None:
    """Pull real ThetaData option quotes for every 0DTE alert this week
    and report MFE / MAE / end-of-window vs Apr 23-24 baseline."""
    print(f"\n[3/3] 0DTE alerts: real option-price MFE/MAE (last {days} days)")
    print("-" * 70)
    cutoff = time.time() - days * 86400
    if not Path(ZERO_DTE_DB).exists():
        print(f"  {ZERO_DTE_DB} not found — skipping")
        return
    c = sqlite3.connect(ZERO_DTE_DB)
    try:
        alerts = pd.read_sql_query("""
            SELECT alert_id, ticker, direction, grade, fired_at, spot, strike,
                   right, expiration, est_entry_price, target_mid, stop_mid,
                   time_stop_minutes
            FROM zero_dte_alerts
            WHERE fired_at >= ?
            ORDER BY fired_at
        """, c, params=(cutoff,))
    finally:
        c.close()

    if alerts.empty:
        print(f"  0 alerts fired this week (baseline week had {BASELINE_0DTE['n']})")
        return

    print(f"  {len(alerts)} alerts to audit (baseline week: {BASELINE_0DTE['n']})\n")

    results = []
    for _, a in alerts.iterrows():
        fired_dt = datetime.fromtimestamp(a["fired_at"])
        end_dt = fired_dt + timedelta(minutes=int(a["time_stop_minutes"]))

        exp = a["expiration"]
        if isinstance(exp, str) and len(exp) == 8 and exp.isdigit():
            exp = f"{exp[:4]}-{exp[4:6]}-{exp[6:]}"

        params = {
            "symbol": a["ticker"],
            "expiration": exp,
            "strike": f"{float(a['strike']):.3f}",
            "right": (a["right"] or "C")[0].upper(),
            "start_date": fired_dt.strftime("%Y-%m-%d"),
            "end_date": fired_dt.strftime("%Y-%m-%d"),
            "interval": "1m",
        }
        try:
            r = requests.get(f"{THETA}/v3/option/history/quote",
                             params=params, timeout=30)
            if r.status_code != 200:
                print(f"    {a['alert_id'][:30]} HTTP {r.status_code}")
                continue
            df = pd.read_csv(io.StringIO(r.text))
        except Exception as e:
            print(f"    {a['alert_id'][:30]} err: {e}")
            continue

        if df.empty:
            continue
        df["ts"] = pd.to_datetime(df["timestamp"])
        df = df[(df["ts"] >= fired_dt) & (df["ts"] <= end_dt)]
        df = df[(df["bid"] > 0) | (df["ask"] > 0)]
        if df.empty:
            continue

        df["mid"] = (df["bid"] + df["ask"]) / 2
        entry = float(a["est_entry_price"])
        max_mid = df["mid"].max()
        min_mid = df["mid"].min()
        end_mid = df["mid"].iloc[-1]
        target = float(a["target_mid"])

        mfe_pct = (max_mid / entry - 1) * 100
        mae_pct = (min_mid / entry - 1) * 100
        end_pct = (end_mid / entry - 1) * 100
        results.append({
            "ticker": a["ticker"],
            "grade": a["grade"],
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "end_pct": end_pct,
            "hit_50": max_mid >= entry * 1.5,
            "hit_100": max_mid >= entry * 2.0,
            "hit_200": max_mid >= entry * 3.0,
            "hit_target": max_mid >= target,
            "min_to_mfe": (df.loc[df["mid"].idxmax(), "ts"] - fired_dt).total_seconds() / 60,
        })
        print(f"    {a['ticker']} {float(a['strike']):.0f}{params['right']} "
              f"{fired_dt.strftime('%a %H:%M')} grade={a['grade']}  "
              f"MFE=+{mfe_pct:.0f}% (in {results[-1]['min_to_mfe']:.0f}min)  "
              f"MAE={mae_pct:+.0f}%  end={end_pct:+.0f}%")

    if not results:
        print("  No quotable alerts (none had ThetaData coverage)")
        return

    r = pd.DataFrame(results)
    print()
    print("  " + "=" * 56)
    print(f"  THIS WEEK (n={len(r)}) vs BASELINE Apr 23-24 (n={BASELINE_0DTE['n']})")
    print("  " + "=" * 56)
    rows = [
        ("Hit +50% any point",  r["hit_50"].mean() * 100,  BASELINE_0DTE["hit_50_pct"]),
        ("Hit +100% any point", r["hit_100"].mean() * 100, BASELINE_0DTE["hit_100_pct"]),
        ("Hit target_mid (3x)", r["hit_target"].mean() * 100, BASELINE_0DTE["hit_target_pct"]),
        ("Avg MFE",             r["mfe_pct"].mean(),       BASELINE_0DTE["avg_mfe_pct"]),
        ("Avg end-of-window",   r["end_pct"].mean(),       BASELINE_0DTE["avg_end_pct"]),
    ]
    for label, this_v, base_v in rows:
        delta = this_v - base_v
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
        print(f"  {label:<24} this={this_v:>+7.1f}%  baseline={base_v:>+5.0f}%  {arrow}{abs(delta):>5.1f}pp")

    giveback = r["mfe_pct"].mean() - r["end_pct"].mean()
    base_giveback = BASELINE_0DTE["avg_mfe_pct"] - BASELINE_0DTE["avg_end_pct"]
    print(f"  {'Giveback (MFE-end)':<24} this={giveback:>+7.1f}pp baseline={base_giveback:>+5.0f}pp"
          f"  {'↑' if giveback > base_giveback else '↓'}{abs(giveback - base_giveback):>5.1f}pp")
    print(f"  ↑ Smaller giveback = better discipline / structural improvement")


def main() -> int:
    args = parse_args()
    if args.utf8:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 70)
    print(f"GammaPulse weekly alert digest — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Window: last {args.days} days")
    print("=" * 70)

    if not args.no_backfill:
        run_backfill(args.days)
    else:
        print("[1/3] Skipping backfill (--no-backfill)")

    signal_outcomes_summary(args.days)
    zero_dte_audit(args.days)

    print()
    print("=" * 70)
    print("Digest complete. No behavior changes — monitor only.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
