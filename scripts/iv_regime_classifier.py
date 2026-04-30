"""Classify each backtest day by IV regime (term structure + level).

Pulls SPX ATM IV for 0DTE and 5DTE at session open, computes:
  - term_spread = iv_0dte - iv_5dte  (positive = front-end hump = event risk)
  - iv_level = iv_5dte               (calm vs stressed regime)

Categorizes into 4 regimes based on the user's MenthorQ chart hypothesis:
  CALM_FLAT      iv_5dte <= 18%  AND term_spread <= 3 vol pts
  CALM_HUMP      iv_5dte <= 18%  AND term_spread >  3 vol pts   (FOMC/event)
  STRESSED_FLAT  iv_5dte >  18%  AND term_spread <= 3 vol pts
  STRESSED_HUMP  iv_5dte >  18%  AND term_spread >  3 vol pts

Then joins to docs/research/structural_turn_30d_fires.csv and reports
WR / avg P&L per regime.

Output:
  docs/research/iv_regime_breakdown.md
  docs/research/iv_regime_breakdown.csv

Run:
  python scripts/iv_regime_classifier.py
"""
from __future__ import annotations

import io
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

THETA = "http://127.0.0.1:25503"
SNAPSHOTS_DB = ROOT / "snapshots.db"
FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "iv_regime_breakdown.md"
OUT_CSV = ROOT / "docs" / "research" / "iv_regime_breakdown.csv"
CACHE_DB = ROOT / "scripts" / ".iv_regime_cache.db"

CALM_LEVEL_PCT = 0.18      # iv_5dte cutoff: below = calm regime
HUMP_SPREAD_PCT = 0.03     # term spread (0dte - 5dte) cutoff for hump

SPX_TICKER_FOR_BARS = "SPX"
SPX_OPTION_ROOT = "SPXW"
SAMPLE_TIME_HHMM = "09:35"  # post-open, settled NBBO


def _ensure_cache():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""
      CREATE TABLE IF NOT EXISTS iv_term_struct (
        date TEXT PRIMARY KEY,
        spot REAL, atm_strike REAL,
        iv_0dte REAL, iv_5dte REAL,
        term_spread REAL,
        regime TEXT,
        cached_at INTEGER
      )
    """)
    conn.commit()
    return conn


def get_spx_spot_at_open(date_str: str) -> float | None:
    """Pull SPX spot at 09:35 from snapshots.db."""
    target_dt = datetime.fromisoformat(date_str).replace(hour=9, minute=35)
    target_ts = int(target_dt.timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB)
    try:
        cur = conn.execute(
            "SELECT spot FROM snapshots WHERE ticker='SPX' "
            "AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 1",
            (target_ts, target_ts + 600),  # within first 10 min after 09:35
        )
        row = cur.fetchone()
        return float(row[0]) if row else None
    finally:
        conn.close()


def find_5dte_expiry(date_str: str) -> str:
    """Return the 5-business-day forward expiration as YYYY-MM-DD.

    Skips weekends. SPX has dailies M/W/F so any 5BD-forward date is
    a valid expiry.
    """
    d = datetime.fromisoformat(date_str)
    added = 0
    while added < 5:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.strftime("%Y-%m-%d")


def pull_atm_iv(expiration: str, strike: float, date: str,
                target_hhmm: str = SAMPLE_TIME_HHMM) -> float | None:
    """Pull ATM IV at 09:35 ET for given contract."""
    params = {
        "symbol": SPX_OPTION_ROOT, "expiration": expiration,
        "strike": f"{strike:.3f}", "right": "C",
        "start_date": date, "end_date": date, "interval": "1m",
    }
    try:
        r = requests.get(
            f"{THETA}/v3/option/history/greeks/implied_volatility",
            params=params, timeout=15,
        )
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty:
            return None
        df["t"] = pd.to_datetime(df["timestamp"])
        df["hhmm"] = df["t"].dt.strftime("%H:%M")
        row = df[df["hhmm"] >= target_hhmm].head(1)
        if row.empty:
            return None
        iv = row.iloc[0].get("implied_vol")
        return float(iv) if iv and iv > 0 else None
    except Exception:
        return None


def classify_regime(iv_5dte: float, term_spread: float) -> str:
    if iv_5dte is None or term_spread is None:
        return "UNKNOWN"
    calm = iv_5dte <= CALM_LEVEL_PCT
    hump = term_spread > HUMP_SPREAD_PCT
    if calm and not hump: return "CALM_FLAT"
    if calm and hump:     return "CALM_HUMP"
    if not calm and not hump: return "STRESSED_FLAT"
    return "STRESSED_HUMP"


def get_or_compute_regime(date_str: str, conn: sqlite3.Connection) -> dict:
    cur = conn.execute(
        "SELECT spot, atm_strike, iv_0dte, iv_5dte, term_spread, regime "
        "FROM iv_term_struct WHERE date=?", (date_str,),
    )
    row = cur.fetchone()
    if row is not None:
        return {
            "date": date_str, "spot": row[0], "atm_strike": row[1],
            "iv_0dte": row[2], "iv_5dte": row[3],
            "term_spread": row[4], "regime": row[5],
        }
    spot = get_spx_spot_at_open(date_str)
    if spot is None:
        return {"date": date_str, "regime": "NO_SPOT"}
    atm = round(spot / 5) * 5  # SPX $5 strikes
    exp_5dte = find_5dte_expiry(date_str)

    iv_0 = pull_atm_iv(date_str, atm, date_str)  # 0DTE = exp == date
    iv_5 = pull_atm_iv(exp_5dte, atm, date_str)
    term_spread = (iv_0 - iv_5) if (iv_0 and iv_5) else None
    regime = classify_regime(iv_5, term_spread)

    conn.execute(
        "INSERT OR REPLACE INTO iv_term_struct VALUES (?,?,?,?,?,?,?,?)",
        (date_str, spot, atm, iv_0, iv_5, term_spread, regime, int(time.time())),
    )
    conn.commit()
    return {
        "date": date_str, "spot": spot, "atm_strike": atm,
        "iv_0dte": iv_0, "iv_5dte": iv_5,
        "term_spread": term_spread, "regime": regime,
    }


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    days = sorted(fires["day"].unique())
    print(f"Classifying {len(days)} days...")
    conn = _ensure_cache()

    rows = []
    for d in days:
        info = get_or_compute_regime(d, conn)
        iv0 = info.get("iv_0dte")
        iv5 = info.get("iv_5dte")
        ts = info.get("term_spread")
        print(f"  {d}: spot={info.get('spot')}  atm={info.get('atm_strike')}  "
              f"iv_0dte={iv0*100 if iv0 else None}  iv_5dte={iv5*100 if iv5 else None}  "
              f"spread={ts*100 if ts else None}  regime={info['regime']}",
              flush=True)
        rows.append(info)

    regime_df = pd.DataFrame(rows).rename(columns={"regime": "iv_regime"})
    fires_with_regime = fires.merge(
        regime_df[["date", "iv_regime", "iv_0dte", "iv_5dte", "term_spread"]],
        left_on="day", right_on="date", how="left",
    )

    # Per-regime aggregate (using opt_eod_pnl from baseline, hold-to-EOD)
    print("\n=== Per-regime aggregate (hold-to-EOD baseline) ===")
    for regime, sub in fires_with_regime.groupby("iv_regime"):
        sub_e = sub.dropna(subset=["opt_eod_pnl"])
        wr = (sub_e["opt_eod_pnl"] > 0).mean() * 100 if len(sub_e) else 0
        avg = sub_e["opt_eod_pnl"].mean() if len(sub_e) else 0
        print(f"  {regime:15s}  fires={len(sub):>2}  with_eod={len(sub_e):>2}  "
              f"WR={wr:>5.1f}%  avg={avg:>+7.1f}%")

    # Direction breakdown per regime
    print("\n=== Per-regime BY DIRECTION ===")
    for regime, sub in fires_with_regime.groupby("iv_regime"):
        for direction in ["BULLISH", "BEARISH"]:
            ssub = sub[sub["direction"] == direction].dropna(subset=["opt_eod_pnl"])
            if len(ssub) == 0:
                continue
            wr = (ssub["opt_eod_pnl"] > 0).mean() * 100
            avg = ssub["opt_eod_pnl"].mean()
            print(f"  {regime:15s} {direction:8s}  n={len(ssub):>2}  "
                  f"WR={wr:>5.1f}%  avg={avg:>+7.1f}%")

    # Markdown report
    md = ["# IV Regime Breakdown — n=27 fires across 11 days\n"]
    md.append("Each backtest day classified using SPX ATM IV at 09:35 ET:")
    md.append(f"- `iv_5dte` (level) cutoff: {CALM_LEVEL_PCT*100:.0f}%")
    md.append(f"- `term_spread = iv_0dte - iv_5dte` cutoff: "
              f"{HUMP_SPREAD_PCT*100:.0f} vol points\n")
    md.append("## Regime classification per day\n")
    md.append("| Day | Spot | ATM | IV 0DTE | IV 5DTE | Spread | Regime |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        iv0 = r.get("iv_0dte"); iv5 = r.get("iv_5dte"); ts = r.get("term_spread")
        md.append(
            f"| {r['date']} | {r.get('spot') or '?':.2f} | {r.get('atm_strike') or '?'} | "
            f"{iv0*100:.1f}% | {iv5*100:.1f}% | {ts*100:+.1f} | {r['regime']} |"
        )
    md.append("\n## P&L per regime (hold-to-EOD baseline)\n")
    md.append("| Regime | Fires | with_EOD | WR | Avg |")
    md.append("|---|---|---|---|---|")
    for regime, sub in fires_with_regime.groupby("iv_regime"):
        sub_e = sub.dropna(subset=["opt_eod_pnl"])
        wr = (sub_e["opt_eod_pnl"] > 0).mean() * 100 if len(sub_e) else 0
        avg = sub_e["opt_eod_pnl"].mean() if len(sub_e) else 0
        md.append(f"| {regime} | {len(sub)} | {len(sub_e)} | "
                  f"{wr:.1f}% | {avg:+.1f}% |")
    md.append("\n## P&L per regime by direction\n")
    md.append("| Regime | Direction | n | WR | Avg |")
    md.append("|---|---|---|---|---|")
    for regime, sub in fires_with_regime.groupby("iv_regime"):
        for direction in ["BULLISH", "BEARISH"]:
            ssub = sub[sub["direction"] == direction].dropna(subset=["opt_eod_pnl"])
            if len(ssub) == 0:
                continue
            wr = (ssub["opt_eod_pnl"] > 0).mean() * 100
            avg = ssub["opt_eod_pnl"].mean()
            md.append(f"| {regime} | {direction} | {len(ssub)} | "
                      f"{wr:.1f}% | {avg:+.1f}% |")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fires_with_regime.to_csv(OUT_CSV, index=False)
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    print(f"CSV    -> {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
